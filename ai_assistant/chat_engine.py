"""Multi-turn chat engine with optional RAG and tool/function-calling support.

The :class:`ChatEngine` maintains a conversation history, dispatches user
messages to an :class:`LLMClient`, optionally augments prompts with retrieval
results from a :class:`RAGEngine`, and emits Qt signals for streaming /
completion / error events. A lightweight tool/function-calling layer recognizes
common research intents (``search_papers``, ``analyze_topic``,
``visualize_data``, ``export_data``) and routes them to registered handlers.

When ``qtpy`` (and thus PyQt5 or PySide2) is unavailable, the engine falls
back to a stub ``QObject`` / ``Signal`` implementation so the module is always
importable for tests.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Qt signal/QObject shim
# ---------------------------------------------------------------------------
try:
    from qtpy.QtCore import QObject as _QObject, Signal as _Signal  # type: ignore

    _HAS_QT = True
except Exception:  # noqa: BLE001 - qtpy optional at runtime
    _HAS_QT = False
    logger.debug("qtpy not available; using stub Signal/QObject for ChatEngine.")

    class _Signal:  # type: ignore[no-redef]
        """Stub replacement for ``qtpy.QtCore.Signal`` (no Qt event loop needed)."""

        def __init__(self, *types: type) -> None:
            self._types = types
            self._handlers: List[Callable[..., Any]] = []

        def connect(self, handler: Callable[..., Any]) -> Callable[..., Any]:
            """Register ``handler`` to be called when the signal is emitted."""
            self._handlers.append(handler)
            return handler

        def disconnect(self, handler: Optional[Callable[..., Any]] = None) -> None:
            """Remove a handler (or all handlers when ``handler is None``)."""
            if handler is None:
                self._handlers.clear()
            else:
                self._handlers = [h for h in self._handlers if h is not handler]

        def emit(self, *args: Any, **kwargs: Any) -> None:
            """Invoke every connected handler with the supplied arguments."""
            for handler in list(self._handlers):
                try:
                    handler(*args, **kwargs)
                except Exception:  # noqa: BLE001 - one bad handler shouldn't break others
                    logger.exception("Signal handler raised: %r", handler)

    class _QObject:  # type: ignore[no-redef]
        """Stub replacement for ``qtpy.QtCore.QObject``."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass


# ---------------------------------------------------------------------------
# ChatResponse dataclass
# ---------------------------------------------------------------------------
@dataclass
class ChatResponse:
    """A single assistant response.

    Attributes:
        content: The assistant's text response.
        sources: Papers cited via RAG (empty when RAG was not used).
        tool_calls: List of tool invocations performed while producing the
            response (each is a dict with ``name``, ``args``, ``result``).
        latency_ms: Wall-clock time from request to response, in milliseconds.
        tokens_used: Estimated token usage (chars / 4 when the provider does
            not report real usage).
    """

    content: str = ""
    sources: List[Any] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    tokens_used: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict suitable for JSON."""
        return {
            "content": self.content,
            "sources": [_paper_summary(s) for s in self.sources],
            "tool_calls": list(self.tool_calls),
            "latency_ms": float(self.latency_ms),
            "tokens_used": int(self.tokens_used),
        }

    def to_markdown(self) -> str:
        """Render the response as Markdown."""
        lines: List[str] = [self.content.strip(), ""]
        if self.sources:
            lines.append("**Sources:**")
            for i, s in enumerate(self.sources, start=1):
                lines.append(f"{i}. {_paper_summary(s)}")
            lines.append("")
        if self.tool_calls:
            lines.append("**Tools used:**")
            for tc in self.tool_calls:
                lines.append(
                    f"- `{tc.get('name', '?')}`({', '.join(f'{k}={v!r}' for k, v in (tc.get('args') or {}).items())})"
                )
            lines.append("")
        if self.tokens_used:
            lines.append(f"_Tokens: {self.tokens_used} · Latency: {self.latency_ms:.0f} ms_")
        return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Paper protocol
# ---------------------------------------------------------------------------
class Paper(Protocol):
    """Structural type for a paper used by the chat engine."""

    title: str
    abstract: str
    authors: Any
    id: Any
    doi: Any
    year: Any


def _paper_summary(paper: Any) -> str:
    """Return a one-line citation for a paper-like object."""
    title = getattr(paper, "title", "") or ""
    year = getattr(paper, "year", "") or ""
    authors = getattr(paper, "authors", "")
    if isinstance(authors, (list, tuple)):
        names = []
        for a in authors:
            if isinstance(a, str):
                names.append(a)
            elif hasattr(a, "name"):
                names.append(str(a.name))
            else:
                names.append(str(a))
        authors = ", ".join(names)
    parts = [title]
    if authors:
        parts.append(str(authors))
    if year:
        parts.append(str(year))
    label = " — ".join(p for p in parts if p)
    doi = getattr(paper, "doi", "")
    if doi:
        label += f" (doi:{doi})"
    return label or str(paper)


# ---------------------------------------------------------------------------
# ChatEngine
# ---------------------------------------------------------------------------
class ChatEngine(_QObject):
    """Multi-turn chat engine with optional RAG and tool-calling support.

    The engine emits four Qt-style signals over its lifecycle:
    ``response_started`` (no args) when a request begins,
    ``response_chunk(str)`` for streaming token chunks,
    ``response_completed(ChatResponse)`` when the response is finalized, and
    ``error(str)`` when an exception is caught.
    """

    # --- Qt signals (work both with qtpy and the stub fallback) ---------
    response_started = _Signal()
    response_chunk = _Signal(str)
    response_completed = _Signal(object)  # ChatResponse
    error = _Signal(str)

    DEFAULT_SYSTEM_PROMPT = (
        "You are the Academic Research Suite (ARS) assistant. "
        "Help the user find, summarize, and analyze academic papers. "
        "When the user asks a factual question about the indexed corpus, "
        "ground your answer in the supplied context and cite sources with "
        "[n] markers. Be concise and accurate; admit uncertainty when relevant."
    )

    # Intent keyword map for the simple function-calling pattern.
    _TOOL_PATTERNS: Dict[str, re.Pattern[str]] = {
        "search_papers": re.compile(
            r"\b(search|find|look up|query|fetch)\b.*\b(papers?|articles?|publications?)\b",
            re.IGNORECASE,
        ),
        "analyze_topic": re.compile(
            r"\b(analyze|analyse|explore|investigate|discuss|overview)\b.*\b(topic|theme|field|subject)\b",
            re.IGNORECASE,
        ),
        "visualize_data": re.compile(
            r"\b(plot|chart|graph|visualize|visualise|figure|draw)\b",
            re.IGNORECASE,
        ),
        "export_data": re.compile(
            r"\b(export|download|save|write)\b.*\b(bibtex|csv|json|markdown|pdf|docx|pptx)\b",
            re.IGNORECASE,
        ),
    }

    def __init__(
        self,
        llm_client: Any,
        rag_engine: Any = None,
        max_history: int = 20,
        system_prompt: Optional[str] = None,
        project: str = "",
        topic: str = "",
    ) -> None:
        """Initialize the chat engine.

        Args:
            llm_client: An :class:`LLMClient` (or compatible) used to generate
                responses.
            rag_engine: Optional :class:`RAGEngine` used to ground answers in
                the indexed corpus. When ``None``, the engine operates in
                plain LLM mode.
            max_history: Maximum number of (user, assistant) turns to keep in
                the in-memory conversation deque.
            system_prompt: Override the system prompt. When ``None``, a
                default is generated using ``project`` and ``topic``.
            project: Project name used to seed the default system prompt.
            topic: Focus topic used to seed the default system prompt.
        """
        super().__init__()
        self.llm_client = llm_client
        self.rag_engine = rag_engine
        self.max_history = max(1, int(max_history))
        self.system_prompt = system_prompt or self._default_system_prompt(project, topic)
        self._history: Deque[Dict[str, str]] = deque(maxlen=self.max_history)
        self._tools: Dict[str, Callable[..., Any]] = {}
        self._register_default_tools()
        logger.debug(
            "ChatEngine initialized: rag=%s, max_history=%d, qt=%s",
            rag_engine is not None,
            self.max_history,
            _HAS_QT,
        )

    # --- Default system prompt ------------------------------------------
    @classmethod
    def _default_system_prompt(cls, project: str = "", topic: str = "") -> str:
        """Build a default system prompt using ``PromptTemplates.CHAT_SYSTEM``."""
        try:
            from .prompts import PromptTemplates

            return PromptTemplates.format(
                "CHAT_SYSTEM",
                project=project or "(unspecified)",
                topic=topic or "(unspecified)",
            )
        except Exception:  # noqa: BLE001
            return cls.DEFAULT_SYSTEM_PROMPT

    # --- History management ---------------------------------------------
    def clear_history(self) -> None:
        """Drop all stored conversation history."""
        self._history.clear()

    def get_history(self) -> List[Dict[str, str]]:
        """Return a list copy of the conversation history."""
        return list(self._history)

    # --- Tool registry --------------------------------------------------
    def register_tool(self, name: str, handler: Callable[..., Any]) -> None:
        """Register a callable to be invoked when the ``name`` tool is triggered."""
        if not name.isidentifier():
            raise ValueError(f"Invalid tool name: {name!r}")
        self._tools[name] = handler
        logger.debug("Registered tool: %s", name)

    def _register_default_tools(self) -> None:
        """Register the four built-in tools with no-op defaults."""
        self._tools.update(
            {
                "search_papers": self._tool_search_papers,
                "analyze_topic": self._tool_analyze_topic,
                "visualize_data": self._tool_visualize_data,
                "export_data": self._tool_export_data,
            }
        )

    def available_tools(self) -> List[str]:
        """Return the names of all registered tools."""
        return sorted(self._tools)

    # --- Main entry point -----------------------------------------------
    def send(self, user_message: str, stream: bool = False) -> ChatResponse:
        """Send a user message and return the assistant's response.

        Args:
            user_message: The user's input text.
            stream: If ``True``, emit ``response_chunk`` for each streamed
                chunk and only build the final :class:`ChatResponse` after
                the stream is exhausted.

        Returns:
            A :class:`ChatResponse` containing the assistant's text, any
            sources pulled from RAG, tool calls that were triggered, and
            timing / token statistics.
        """
        if not isinstance(user_message, str) or not user_message.strip():
            err = "Empty user message."
            self.error.emit(err)
            return ChatResponse(content="", latency_ms=0.0, tokens_used=0)

        self.response_started.emit()
        started = time.perf_counter()
        tool_calls: List[Dict[str, Any]] = []
        sources: List[Any] = []

        try:
            # 1. Detect tool calls (intent-based).
            for name, pattern in self._TOOL_PATTERNS.items():
                m = pattern.search(user_message)
                if m is None:
                    continue
                handler = self._tools.get(name)
                if handler is None:
                    continue
                args = self._extract_tool_args(name, user_message)
                try:
                    result = handler(**args)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Tool %s raised.", name)
                    result = {"error": str(exc)}
                tool_calls.append({"name": name, "args": args, "result": result})

            # 2. Build prompt with optional RAG grounding.
            context = ""
            rag_response: Optional[Any] = None
            if self.rag_engine is not None:
                try:
                    rag_response = self.rag_engine.query(user_message, top_k=5)
                    sources = list(getattr(rag_response, "sources", []) or [])
                    context = self._format_rag_context(rag_response)
                except Exception:  # noqa: BLE001
                    logger.exception("RAG query failed; falling back to plain LLM.")
                    context = ""

            messages = self._build_messages(user_message, context)

            # 3. Generate the response.
            if stream:
                content_parts: List[str] = []
                for chunk in self._stream_response(messages):
                    content_parts.append(chunk)
                    self.response_chunk.emit(chunk)
                content = "".join(content_parts)
            else:
                content = self._sync_response(messages)

            tokens_used = self._estimate_tokens(content, user_message, context)
            response = ChatResponse(
                content=content.strip(),
                sources=sources,
                tool_calls=tool_calls,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                tokens_used=tokens_used,
            )

            # 4. Append to history.
            self._history.append({"role": "user", "content": user_message})
            self._history.append({"role": "assistant", "content": response.content})

            self.response_completed.emit(response)
            return response
        except Exception as exc:  # noqa: BLE001 - top-level safety net
            logger.exception("ChatEngine.send raised an exception.")
            self.error.emit(str(exc))
            return ChatResponse(
                content=f"[error] {exc}",
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )

    def send_streaming(self, user_message: str) -> Any:
        """Convenience wrapper that streams the response token-by-token.

        Args:
            user_message: The user input.

        Yields:
            String chunks as they arrive from the LLM provider.
        """
        self.response_started.emit()
        for chunk in self._stream_response(self._build_messages(user_message, "")):
            self.response_chunk.emit(chunk)
            yield chunk

    # --- Response generation --------------------------------------------
    def _build_messages(self, user_message: str, context: str) -> List[Dict[str, str]]:
        """Assemble the OpenAI-style message list for the LLM call."""
        messages: List[Dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
        if context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Use the following retrieved passages as grounding context. "
                        "Cite them with [n] markers when relevant.\n\n" + context
                    ),
                }
            )
        messages.extend(self._history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _sync_response(self, messages: List[Dict[str, str]]) -> str:
        """Generate a non-streaming response from the LLM client."""
        try:
            return str(self.llm_client.chat(messages, max_tokens=2000, stream=False))
        except TypeError:
            # Some clients only expose ``complete``.
            prompt = "\n\n".join(m["content"] for m in messages if m.get("content"))
            return str(self.llm_client.complete(prompt, max_tokens=2000))

    def _stream_response(self, messages: List[Dict[str, str]]) -> Any:
        """Yield response chunks from a streaming LLM client."""
        try:
            stream = self.llm_client.chat(messages, max_tokens=2000, stream=True)
        except TypeError:
            # Fallback: do a sync call and yield it as a single chunk.
            yield self._sync_response(messages)
            return
        # If the provider doesn't actually stream, fall back gracefully.
        if isinstance(stream, str):
            yield stream
            return
        for chunk in stream:
            if isinstance(chunk, str):
                yield chunk

    # --- Tool argument extraction --------------------------------------
    @staticmethod
    def _extract_tool_args(name: str, message: str) -> Dict[str, Any]:
        """Best-effort extraction of arguments for the matched tool."""
        if name == "search_papers":
            query = message.strip()
            return {"query": query}
        if name == "analyze_topic":
            return {"query": message.strip()}
        if name == "visualize_data":
            return {"metric": message.strip()}
        if name == "export_data":
            fmt_match = re.search(
                r"\b(bibtex|csv|json|markdown|pdf|docx|pptx)\b",
                message,
                re.IGNORECASE,
            )
            fmt = fmt_match.group(1).lower() if fmt_match else "json"
            return {"format": fmt}
        return {}

    # --- Default tool implementations ----------------------------------
    def _tool_search_papers(self, query: str = "") -> Dict[str, Any]:
        """Default ``search_papers`` handler — delegates to the RAG engine."""
        if self.rag_engine is None:
            return {"status": "no_rag", "message": "RAG engine not configured."}
        try:
            response = self.rag_engine.query(query or "", top_k=5)
            return {
                "status": "ok",
                "chunks": [c for c in getattr(response, "chunks", [])],
                "n_sources": len(getattr(response, "sources", []) or []),
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    def _tool_analyze_topic(self, query: str = "") -> Dict[str, Any]:
        """Default ``analyze_topic`` handler — returns the raw query for the LLM."""
        return {"status": "ok", "topic": query, "note": "Forwarded to LLM."}

    def _tool_visualize_data(self, metric: str = "") -> Dict[str, Any]:
        """Default ``visualize_data`` handler — stub for the UI layer."""
        return {
            "status": "ok",
            "metric": metric,
            "note": "Visualization request captured; UI layer should render.",
        }

    def _tool_export_data(self, format: str = "json") -> Dict[str, Any]:
        """Default ``export_data`` handler — stub for the export layer."""
        return {
            "status": "ok",
            "format": format,
            "note": "Export request captured; reporting layer should persist.",
        }

    # --- RAG context formatting ----------------------------------------
    @staticmethod
    def _format_rag_context(rag_response: Any) -> str:
        """Render retrieved chunks as numbered passages for the LLM prompt."""
        chunks = getattr(rag_response, "chunks", []) or []
        if not chunks:
            return ""
        lines: List[str] = []
        for i, c in enumerate(chunks, start=1):
            text = c.get("text", "") if isinstance(c, dict) else getattr(c, "text", "")
            lines.append(f"[{i}] {text[:800]}")
        return "\n\n".join(lines)

    # --- Token estimation ----------------------------------------------
    @staticmethod
    def _estimate_tokens(*parts: str) -> int:
        """Estimate token usage as ``chars / 4`` (heuristic)."""
        total_chars = sum(len(p or "") for p in parts)
        return max(0, total_chars // 4)


__all__ = ["ChatResponse", "ChatEngine", "Paper"]
