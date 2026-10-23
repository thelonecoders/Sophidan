"""Unified LLM client supporting Ollama, OpenAI, Anthropic, and an offline echo mode.

This module provides a single ``LLMClient`` class that wraps the three supported
LLM SDKs (OpenAI, Anthropic, Ollama) behind a provider-agnostic API. All heavy
third-party SDKs are imported lazily inside ``_ensure_client`` so that the module
imports cleanly even when those packages are not installed. When ``provider``
is ``LLMProvider.NONE`` (or any of the string aliases ``"none"``, ``"echo"``,
``"offline"``), a deterministic in-process echo backend is used so the entire
suite is testable without network access or API keys.

Defaults are read from the **flat** settings fields (``ai_provider``,
``ai_model``, ``ai_api_key``, ``ai_base_url``) exposed by
``config.settings.get_settings()``. The client also accumulates token/call
usage statistics (see :meth:`LLMClient.usage_stats`).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Union

import numpy as np

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """Supported LLM provider backends.

    Attributes:
        OLLAMA: Local Ollama server (https://ollama.com).
        OPENAI: OpenAI Chat Completions API.
        ANTHROPIC: Anthropic Messages API.
        NONE: Offline deterministic echo backend for tests and CI.
    """

    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    NONE = "none"


def _estimate_tokens(text: Union[str, List[str], None]) -> int:
    """Estimate a token count as ``chars / 4`` (heuristic fallback)."""
    if text is None:
        return 0
    if isinstance(text, str):
        return max(0, len(text) // 4)
    return max(0, sum(len(t or "") for t in text) // 4)


_REASONING_MODEL_RE = re.compile(r"(^o\d)")


def _is_reasoning_model(model: str) -> bool:
    """Return ``True`` for OpenAI o-series / reasoning-style models.

    These models reject ``temperature`` values other than the default,
    so the parameter must be omitted rather than sent.
    """
    m = (model or "").strip().lower()
    if not m:
        return False
    if _REASONING_MODEL_RE.match(m):
        return True
    return "reasoning" in m


class _EchoBackend:
    """Deterministic in-process backend used when ``provider == LLMProvider.NONE``.

    All outputs are a pure function of the inputs so tests can assert exact
    response strings. Embeddings are derived from a SHA-256 hash of the input
    text, projected into a fixed-dimensional vector space.
    """

    EMBEDDING_DIM = 384
    MODELS = ("echo", "echo-deterministic", "offline")

    def __init__(self, model: str = "echo") -> None:
        self.model = model

    # --- Chat --------------------------------------------------------------
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False,
    ) -> Union[str, Iterator[str]]:
        """Echo the last user message back as a deterministic offline response."""
        if not messages:
            text = "[echo] (no input)"
        else:
            last = messages[-1]
            role = last.get("role", "user") if isinstance(last, dict) else "user"
            content = last.get("content", "") if isinstance(last, dict) else str(last)
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
            truncated = content[: max(0, max_tokens - 120)]
            text = (
                f"[echo:{digest}] Received ({role}): {truncated}\n\n"
                f"(Offline mode — provider=NONE — no real LLM was contacted.)"
            )
        if stream:
            return self._chunk_stream(text)
        return text

    def complete(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False,
    ) -> Union[str, Iterator[str]]:
        """Echo-style completion."""
        return self.chat(
            [{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

    # --- Embeddings --------------------------------------------------------
    def embed(self, text: Union[str, List[str]]) -> np.ndarray:
        """Hash-based deterministic embedding vector in [-1, 1] of fixed length."""
        single = isinstance(text, str)
        texts = [text] if single else list(text)
        dim = self.EMBEDDING_DIM
        out = np.zeros((len(texts), dim), dtype=np.float32)
        for i, t in enumerate(texts):
            raw = t.encode("utf-8") if isinstance(t, str) else str(t).encode("utf-8")
            digest = hashlib.sha256(raw).digest()
            # Stretch / tile the 32-byte hash to fill `dim` floats.
            buf = (digest * (dim // 32 + 1))[:dim]
            arr = np.frombuffer(buf, dtype=np.uint8).astype(np.float32)
            arr = (arr / 255.0) * 2.0 - 1.0  # normalize to [-1, 1]
            norm = float(np.linalg.norm(arr))
            if norm > 0:
                arr = arr / norm
            out[i] = arr
        return out[0] if single else out

    def list_models(self) -> List[str]:
        """Return the deterministic model identifiers available in echo mode."""
        return list(self.MODELS)

    @staticmethod
    def _chunk_stream(text: str, chunk_size: int = 4) -> Iterator[str]:
        """Yield ``text`` in small chunks to simulate token streaming."""
        for i in range(0, len(text), chunk_size):
            yield text[i : i + chunk_size]


class LLMClient:
    """Unified chat / completion / embedding client.

    The client supports OpenAI, Anthropic, and Ollama behind a single API.
    Provider SDKs are imported lazily — instantiating ``LLMClient`` itself
    never requires any of them. The ``NONE`` provider uses an in-process
    echo backend suitable for offline / test mode.

    Usage / cost accounting: every chat, streaming-chat and embedding call
    updates an internal counter exposed via :meth:`usage_stats`.

    Example:
        >>> client = LLMClient(provider="none", model="echo")
        >>> client.chat([{"role": "user", "content": "hello"}])
        '[echo:8b1a99...] Received (user): hello ...'
    """

    DEFAULT_EMBEDDING_DIM = 384

    # Ollama context-window option (tokens). Ollama defaults to a small
    # num_ctx which silently truncates long prompts; we request a sane,
    # explicit window instead.
    OLLAMA_NUM_CTX = 4096

    _PROVIDER_ALIASES: Dict[str, LLMProvider] = {
        "openai": LLMProvider.OPENAI,
        "gpt": LLMProvider.OPENAI,
        "chatgpt": LLMProvider.OPENAI,
        "anthropic": LLMProvider.ANTHROPIC,
        "claude": LLMProvider.ANTHROPIC,
        "ollama": LLMProvider.OLLAMA,
        "llama": LLMProvider.OLLAMA,
        "local": LLMProvider.OLLAMA,
        "none": LLMProvider.NONE,
        "echo": LLMProvider.NONE,
        "offline": LLMProvider.NONE,
        "": LLMProvider.NONE,
    }

    _PROVIDER_DEFAULT_MODELS: Dict[LLMProvider, str] = {
        LLMProvider.OPENAI: "gpt-4o",
        LLMProvider.ANTHROPIC: "claude-3-5-sonnet-20241022",
        LLMProvider.OLLAMA: "llama3.1",
        LLMProvider.NONE: "echo",
    }

    def __init__(
        self,
        provider: Union[LLMProvider, str] = LLMProvider.NONE,
        model: str = "echo",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        allow_synthetic: bool = False,
        embedding_model: Optional[str] = None,
    ) -> None:
        """Initialize the unified LLM client.

        Args:
            provider: ``LLMProvider`` enum member, or string alias such as
                ``"openai"``, ``"anthropic"``, ``"ollama"``, ``"none"``,
                ``"echo"``, or ``"offline"``.
            model: Model identifier (e.g. ``"gpt-4o"``,
                ``"claude-3-5-sonnet-20241022"``, ``"llama3.1"``). For the
                echo backend any string is accepted.
            api_key: API key for cloud providers. When ``None`` the client
                falls back to the flat settings fields (``ai_api_key``) and
                then to the appropriate environment variable.
            base_url: Optional override for the provider's API endpoint.
            allow_synthetic: Explicit opt-in to the deterministic hash-based
                embedding fallback for providers without a native embeddings
                endpoint (currently Anthropic). When ``False`` (default),
                :meth:`embed` raises a clear error for such providers instead
                of silently producing synthetic vectors.
            embedding_model: Optional embedding-model identifier override
                (e.g. ``"text-embedding-3-small"`` or ``"nomic-embed-text"``).

        Raises:
            ValueError: If ``provider`` cannot be resolved.
        """
        self.provider = self._resolve_provider(provider)
        self.model = model or "echo"
        self.api_key = api_key
        self.base_url = base_url
        self.allow_synthetic = bool(allow_synthetic)
        self.embedding_model = embedding_model
        self.ollama_num_ctx = self.OLLAMA_NUM_CTX
        self._client: Any = None
        self._usage_lock = threading.Lock()
        self._usage: Dict[str, int] = {
            "calls": 0,
            "chat_calls": 0,
            "stream_calls": 0,
            "embedding_calls": 0,
            "errors": 0,
            "tokens_in": 0,
            "tokens_out": 0,
        }
        self._apply_defaults_from_settings()
        logger.debug(
            "LLMClient initialized: provider=%s, model=%s, base_url=%s",
            self.provider.value,
            self.model,
            self.base_url,
        )

    # --- Usage accounting --------------------------------------------------
    def _record(
        self,
        kind: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        error: bool = False,
    ) -> None:
        """Update the internal usage counters (thread-safe)."""
        with self._usage_lock:
            self._usage["calls"] += 1
            if kind in self._usage:
                self._usage[kind] += 1
            self._usage["tokens_in"] += max(0, int(tokens_in))
            self._usage["tokens_out"] += max(0, int(tokens_out))
            if error:
                self._usage["errors"] += 1

    def usage_stats(self) -> Dict[str, int]:
        """Return a copy of the accumulated usage totals.

        Keys: ``calls``, ``chat_calls``, ``stream_calls``,
        ``embedding_calls``, ``errors``, ``tokens_in``, ``tokens_out``.
        """
        with self._usage_lock:
            return dict(self._usage)

    def reset_usage(self) -> None:
        """Zero all usage counters (primarily for tests)."""
        with self._usage_lock:
            for k in self._usage:
                self._usage[k] = 0

    # --- Provider resolution ----------------------------------------------
    @classmethod
    def _resolve_provider(cls, provider: Union[LLMProvider, str]) -> LLMProvider:
        """Normalize the ``provider`` argument to a ``LLMProvider`` enum value."""
        if isinstance(provider, LLMProvider):
            return provider
        key = str(provider).strip().lower()
        if key in cls._PROVIDER_ALIASES:
            return cls._PROVIDER_ALIASES[key]
        try:
            return LLMProvider(key)
        except ValueError as exc:
            raise ValueError(f"Unknown LLM provider: {provider!r}") from exc

    @staticmethod
    def _settings_field(settings: Any, name: str) -> Any:
        """Read a **flat** field from a settings object or mapping."""
        if settings is None:
            return None
        if isinstance(settings, dict):
            return settings.get(name)
        return getattr(settings, name, None)

    def _apply_defaults_from_settings(self) -> None:
        """Populate missing fields from ``config.settings.get_settings()``.

        Settings expose FLAT fields (``ai_provider``, ``ai_model``,
        ``ai_api_key``, ``ai_base_url``) — there is no nested
        ``ai_assistant`` section. The settings module is imported lazily and
        the call is wrapped in a broad ``try/except`` so this method is a
        no-op when config is not yet available (e.g. during early bootstrap
        or tests).
        """
        settings: Any = None
        try:
            from config.settings import get_settings  # type: ignore[import]

            settings = get_settings()
        except Exception:  # noqa: BLE001 - settings is optional at this layer
            settings = None

        # Flat settings fields (CONTRACT #5). Fall back to a nested
        # "ai_assistant" mapping only if it exists (defensive, some
        # deployments used that shape historically).
        flat: Dict[str, Any] = {}
        for name in ("ai_provider", "ai_model", "ai_api_key", "ai_base_url"):
            val = self._settings_field(settings, name)
            if val:
                flat[name] = val
        if not any(flat.values()):
            nested = self._settings_field(settings, "ai_assistant")
            if isinstance(nested, dict):
                alias = {
                    "provider": "ai_provider",
                    "model": "ai_model",
                    "api_key": "ai_api_key",
                    "base_url": "ai_base_url",
                }
                for k, v in nested.items():
                    if k in alias and v and alias[k] not in flat:
                        flat[alias[k]] = v

        if self.provider is LLMProvider.NONE and flat.get("ai_provider"):
            try:
                self.provider = self._resolve_provider(flat["ai_provider"])
            except ValueError:
                logger.warning(
                    "Ignoring unknown provider in settings: %r", flat["ai_provider"]
                )

        if self.model in ("", "echo", None) and flat.get("ai_model"):
            self.model = str(flat["ai_model"])
        if self.api_key is None and flat.get("ai_api_key"):
            self.api_key = str(flat["ai_api_key"])
        if self.base_url is None and flat.get("ai_base_url"):
            self.base_url = str(flat["ai_base_url"])

        # A real provider was configured but no concrete model: pick a
        # provider-appropriate default rather than leaving the echo model.
        if self.provider is not LLMProvider.NONE and self.model in ("", "echo", None):
            self.model = self._PROVIDER_DEFAULT_MODELS.get(self.provider, self.model)

        # Final fallback: well-known environment variables.
        env_keys = {
            LLMProvider.OPENAI: ("OPENAI_API_KEY", "OPENAI_BASE_URL"),
            LLMProvider.ANTHROPIC: ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
            LLMProvider.OLLAMA: ("OLLAMA_API_KEY", "OLLAMA_BASE_URL"),
            LLMProvider.NONE: (None, None),
        }.get(self.provider, (None, None))

        if env_keys:
            env_key, env_url = env_keys
            if self.api_key is None and env_key:
                self.api_key = os.environ.get(env_key)
            if self.base_url is None and env_url:
                self.base_url = os.environ.get(env_url)

    # --- Client initialization --------------------------------------------
    def _ensure_client(self) -> Any:
        """Lazily construct and cache the underlying provider SDK client."""
        if self._client is not None:
            return self._client

        if self.provider is LLMProvider.NONE:
            self._client = _EchoBackend(model=self.model)
            return self._client

        if self.provider is LLMProvider.OPENAI:
            try:
                import openai  # type: ignore[import]
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise ImportError(
                    "openai package is required for the OpenAI provider. "
                    "Install with: pip install openai"
                ) from exc
            kwargs: Dict[str, Any] = {"api_key": self.api_key or "missing"}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.OpenAI(**kwargs)

        elif self.provider is LLMProvider.ANTHROPIC:
            try:
                import anthropic  # type: ignore[import]
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise ImportError(
                    "anthropic package is required for the Anthropic provider. "
                    "Install with: pip install anthropic"
                ) from exc
            kwargs = {"api_key": self.api_key or "missing"}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = anthropic.Anthropic(**kwargs)

        elif self.provider is LLMProvider.OLLAMA:
            try:
                import ollama  # type: ignore[import]
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise ImportError(
                    "ollama package is required for the Ollama provider. "
                    "Install with: pip install ollama"
                ) from exc
            kwargs = {}
            if self.base_url:
                kwargs["host"] = self.base_url
            self._client = ollama.Client(**kwargs)

        else:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported provider: {self.provider}")

        return self._client

    # --- OpenAI parameter handling ----------------------------------------
    @staticmethod
    def _openai_params(
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        stream: bool,
    ) -> Dict[str, Any]:
        """Build Chat-Completions kwargs for the current (2026) OpenAI API.

        * ``max_completion_tokens`` replaces the deprecated ``max_tokens``.
        * ``temperature`` is omitted for o-series / reasoning models (the
          API only accepts the default temperature there).
        """
        params: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_completion_tokens": int(max_tokens),
        }
        if not _is_reasoning_model(model):
            params["temperature"] = float(temperature)
        return params

    def _openai_create(
        self,
        client: Any,
        params: Dict[str, Any],
        max_tokens: int,
    ) -> Any:
        """Call ``client.chat.completions.create`` with compatibility retries.

        Handles two legacy-server failure modes:
        1. Server rejects ``max_completion_tokens`` → retry with deprecated
           ``max_tokens``.
        2. Server rejects ``temperature`` (BadRequest) → retry without it.
        """
        try:
            return client.chat.completions.create(**params)
        except Exception as exc:  # noqa: BLE001 - inspected + re-raised below
            import openai  # imported lazily but guaranteed by _ensure_client

            message = str(exc)
            lowered = message.lower()
            bad_request = getattr(openai, "BadRequestError", None)
            is_bad = isinstance(exc, bad_request) if bad_request else False

            retry: Dict[str, Any] = dict(params)
            changed = False
            if "max_completion_tokens" in lowered and "max_completion_tokens" in retry:
                retry.pop("max_completion_tokens")
                retry["max_tokens"] = int(max_tokens)
                changed = True
            if "temperature" in retry and (
                is_bad and "temperature" in lowered
                or "unsupported" in lowered and "temperature" in lowered
            ):
                retry.pop("temperature")
                changed = True
            if not changed:
                self._record("chat_calls", error=True)
                raise
            logger.debug("Retrying OpenAI call with adjusted params: %s", message[:200])
            return client.chat.completions.create(**retry)

    # --- Public API --------------------------------------------------------
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False,
    ) -> Union[str, Iterator[str]]:
        """Send a chat-style request to the active provider.

        Args:
            messages: OpenAI-style message list with ``role`` and ``content``
                keys (``role`` ∈ {"system", "user", "assistant", "tool"}).
            temperature: Sampling temperature in [0.0, 2.0].
            max_tokens: Maximum tokens to generate.
            stream: If ``True``, return an iterator yielding string chunks.

        Returns:
            The full assistant response string (``stream=False``) or an
            iterator of string chunks (``stream=True``).
        """
        client = self._ensure_client()
        if stream:
            return self._stream_chat(client, messages, temperature, max_tokens)
        return self._sync_chat(client, messages, temperature, max_tokens)

    def _sync_chat(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Synchronous (non-streaming) chat implementation."""
        if self.provider is LLMProvider.NONE:
            try:
                result = client.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                )
                out = str(result)
                self._record(
                    "chat_calls",
                    tokens_in=_estimate_tokens([m.get("content", "") for m in messages]),
                    tokens_out=_estimate_tokens(out),
                )
                return out
            except Exception:  # noqa: BLE001
                self._record("chat_calls", error=True)
                raise

        if self.provider is LLMProvider.OPENAI:
            params = self._openai_params(self.model, messages, temperature, max_tokens, False)
            response = self._openai_create(client, params, max_tokens)
            self._record_openai_usage(response, input_texts=messages)
            return response.choices[0].message.content or ""

        if self.provider is LLMProvider.ANTHROPIC:
            system_text, non_system = self._split_anthropic_messages(messages)
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": non_system,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if system_text:
                kwargs["system"] = system_text
            try:
                response = client.messages.create(**kwargs)
            except Exception:  # noqa: BLE001
                self._record("chat_calls", error=True)
                raise
            self._record_anthropic_usage(response, input_texts=messages)
            parts: List[str] = []
            for block in response.content:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
            return "".join(parts)

        if self.provider is LLMProvider.OLLAMA:
            options = {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": int(getattr(self, "ollama_num_ctx", self.OLLAMA_NUM_CTX)),
            }
            try:
                response = client.chat(
                    model=self.model,
                    messages=messages,
                    options=options,
                    stream=False,
                )
            except Exception:  # noqa: BLE001
                self._record("chat_calls", error=True)
                raise
            self._record_ollama_usage(response, input_texts=messages)
            if isinstance(response, dict):
                return str(response.get("message", {}).get("content", ""))
            try:
                return str(response.message.content or "")
            except AttributeError:
                return str(getattr(response, "message", {}).get("content", ""))

        raise ValueError(f"Unsupported provider: {self.provider}")

    def _stream_chat(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        """Yield response text chunks from the active provider."""
        if self.provider is LLMProvider.NONE:
            collected: List[str] = []
            try:
                for chunk in client.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                ):
                    collected.append(chunk)
                    yield chunk
            except Exception:  # noqa: BLE001
                self._record("stream_calls", error=True)
                raise
            self._record(
                "stream_calls",
                tokens_in=_estimate_tokens([m.get("content", "") for m in messages]),
                tokens_out=_estimate_tokens("".join(collected)),
            )
            return

        if self.provider is LLMProvider.OPENAI:
            params = self._openai_params(self.model, messages, temperature, max_tokens, True)
            stream = self._openai_create(client, params, max_tokens)
            collected: List[str] = []
            usage = None
            try:
                for event in stream:
                    try:
                        # Some servers emit a final chunk carrying usage stats.
                        usage = getattr(event, "usage", None) or usage
                    except Exception:  # noqa: BLE001 - defensive
                        pass
                    try:
                        delta = event.choices[0].delta.content
                    except (AttributeError, IndexError):
                        delta = None
                    if delta:
                        collected.append(delta)
                        yield delta
            except Exception:  # noqa: BLE001
                self._record("stream_calls", error=True)
                raise
            if usage is not None:
                self._record_openai_usage(usage, input_texts=messages, streamed=True)
            else:
                self._record(
                    "stream_calls",
                    tokens_in=_estimate_tokens([m.get("content", "") for m in messages]),
                    tokens_out=_estimate_tokens(collected),
                )
            return

        if self.provider is LLMProvider.ANTHROPIC:
            system_text, non_system = self._split_anthropic_messages(messages)
            kwargs = {
                "model": self.model,
                "messages": non_system,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if system_text:
                kwargs["system"] = system_text
            collected: List[str] = []
            try:
                with client.messages.stream(**kwargs) as s:
                    for text in s.text_stream:
                        if text:
                            collected.append(text)
                            yield text
            except Exception:  # noqa: BLE001
                self._record("stream_calls", error=True)
                raise
            self._record(
                "stream_calls",
                tokens_in=_estimate_tokens([m.get("content", "") for m in messages]),
                tokens_out=_estimate_tokens(collected),
            )
            return

        if self.provider is LLMProvider.OLLAMA:
            options = {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": int(getattr(self, "ollama_num_ctx", self.OLLAMA_NUM_CTX)),
            }
            stream = client.chat(
                model=self.model,
                messages=messages,
                options=options,
                stream=True,
            )
            collected: List[str] = []
            last_event: Any = None
            try:
                for event in stream:
                    last_event = event
                    if isinstance(event, dict):
                        content = event.get("message", {}).get("content", "")
                    else:
                        content = getattr(getattr(event, "message", None), "content", "")
                    if content:
                        collected.append(content)
                        yield content
            except Exception:  # noqa: BLE001
                self._record("stream_calls", error=True)
                raise
            self._record_ollama_usage(last_event, input_texts=messages, streamed=True)
            return

        raise ValueError(f"Unsupported provider: {self.provider}")

    # --- Usage extraction from provider responses --------------------------
    def _record_openai_usage(
        self,
        response: Any,
        input_texts: Any,
        streamed: bool = False,
    ) -> None:
        """Record usage from an OpenAI response (or streaming usage chunk)."""
        usage = getattr(response, "usage", None)
        tokens_in = tokens_out = 0
        if usage is not None:
            tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
            tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        if not tokens_in:
            if isinstance(input_texts, list):
                tokens_in = _estimate_tokens(
                    [m.get("content", "") if isinstance(m, dict) else str(m) for m in input_texts]
                )
            else:
                tokens_in = _estimate_tokens(input_texts)
        kind = "stream_calls" if streamed else "chat_calls"
        self._record(kind, tokens_in=tokens_in, tokens_out=tokens_out)

    def _record_anthropic_usage(self, response: Any, input_texts: Any) -> None:
        """Record usage from an Anthropic Messages response."""
        usage = getattr(response, "usage", None)
        tokens_in = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        tokens_out = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
        if not tokens_in:
            tokens_in = _estimate_tokens(
                [m.get("content", "") if isinstance(m, dict) else str(m) for m in input_texts]
            )
        self._record("chat_calls", tokens_in=tokens_in, tokens_out=tokens_out)

    def _record_ollama_usage(
        self,
        response: Any,
        input_texts: Any,
        streamed: bool = False,
    ) -> None:
        """Record usage from an Ollama response (final event when streaming)."""
        def _get(obj: Any, key: str) -> int:
            if isinstance(obj, dict):
                return int(obj.get(key, 0) or 0)
            return int(getattr(obj, key, 0) or 0)

        tokens_in = _get(response, "prompt_eval_count")
        tokens_out = _get(response, "eval_count")
        if not tokens_in:
            tokens_in = _estimate_tokens(
                [m.get("content", "") if isinstance(m, dict) else str(m) for m in input_texts]
            )
        kind = "stream_calls" if streamed else "chat_calls"
        self._record(kind, tokens_in=tokens_in, tokens_out=tokens_out)

    @staticmethod
    def _split_anthropic_messages(
        messages: List[Dict[str, str]],
    ) -> tuple[str, List[Dict[str, str]]]:
        """Extract the Anthropic-style ``system`` text and remaining messages."""
        system_parts: List[str] = []
        non_system: List[Dict[str, str]] = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            if m.get("role") == "system":
                system_parts.append(str(m.get("content", "")))
            else:
                non_system.append(m)
        return "\n\n".join(p for p in system_parts if p), non_system

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Run a single-prompt completion (non-streaming convenience wrapper).

        Args:
            prompt: The prompt text.
            **kwargs: Forwarded to :meth:`chat` (e.g. ``temperature``,
                ``max_tokens``).

        Returns:
            The assistant response as a string.
        """
        kwargs.pop("stream", None)
        return str(
            self.chat(
                [{"role": "user", "content": prompt}],
                stream=False,
                **kwargs,
            )
        )

    def embed(self, text: Union[str, List[str]]) -> np.ndarray:
        """Compute embedding vectors for the given text(s).

        Args:
            text: A single string or a list of strings.

        Returns:
            ``np.ndarray`` of shape ``(dim,)`` for a single input or
            ``(n, dim)`` for a list. The dimension depends on the provider
            (384 for the echo backend; OpenAI ``text-embedding-3-small``
            returns 1536 dimensions).

        Raises:
            RuntimeError: If the provider has no native embeddings endpoint
                (Anthropic) and ``allow_synthetic`` was not set.
        """
        client = self._ensure_client()

        if self.provider is LLMProvider.NONE:
            self._record("embedding_calls", tokens_in=_estimate_tokens(text))
            return client.embed(text)

        if self.provider is LLMProvider.OPENAI:
            model = self._resolve_embedding_model("text-embedding-3-small")
            inputs = [text] if isinstance(text, str) else list(text)
            try:
                response = client.embeddings.create(model=model, input=inputs)
            except Exception:  # noqa: BLE001
                self._record("embedding_calls", error=True)
                raise
            usage = getattr(response, "usage", None)
            tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else _estimate_tokens(inputs)
            self._record("embedding_calls", tokens_in=tokens_in)
            mat = np.array(
                [d.embedding for d in response.data],
                dtype=np.float32,
            )
            return mat[0] if isinstance(text, str) else mat

        if self.provider is LLMProvider.ANTHROPIC:
            # Anthropic has no native embeddings endpoint. Never fall back to
            # synthetic vectors silently — a RAG index built on hash vectors
            # looks plausible but retrieves garbage.
            if not self.allow_synthetic:
                self._record("embedding_calls", error=True)
                raise RuntimeError(
                    "Anthropic has no native embeddings API, and this LLMClient "
                    "was created with allow_synthetic=False. Configure a real "
                    "embedder for the RAG engine (e.g. OpenAI or Ollama "
                    "embeddings, or data_science.embeddings.EmbeddingsModel), "
                    "or construct LLMClient(..., allow_synthetic=True) to "
                    "explicitly accept degraded hash-based vectors (NOT "
                    "recommended for production retrieval)."
                )
            logger.warning(
                "Anthropic has no native embeddings API; using the explicitly "
                "allowed hash-based synthetic fallback (allow_synthetic=True)."
            )
            self._record("embedding_calls", tokens_in=_estimate_tokens(text))
            return _EchoBackend().embed(text)

        if self.provider is LLMProvider.OLLAMA:
            model = self._resolve_embedding_model("nomic-embed-text")
            inputs = [text] if isinstance(text, str) else list(text)
            try:
                self._record("embedding_calls", tokens_in=_estimate_tokens(inputs))
                return self._ollama_embed(client, model, inputs, single=isinstance(text, str))
            except Exception:  # noqa: BLE001
                self._record("embedding_calls", error=True)
                raise

        raise ValueError(f"Unsupported provider: {self.provider}")

    def _ollama_embed(
        self,
        client: Any,
        model: str,
        inputs: List[str],
        single: bool,
    ) -> np.ndarray:
        """Ollama embeddings via the batched ``client.embed`` API.

        Falls back to the legacy per-item ``client.embeddings`` endpoint when
        the installed Ollama server/SDK does not expose ``embed``.
        """
        if hasattr(client, "embed"):
            response = client.embed(model=model, input=inputs)
            if isinstance(response, dict):
                vecs = response.get("embeddings") or []
            else:
                vecs = getattr(response, "embeddings", None) or []
            mat = np.asarray(vecs, dtype=np.float32)
            if mat.ndim == 1 and mat.size:
                mat = mat.reshape(1, -1)
            if mat.shape[0] != len(inputs):
                raise ValueError(
                    f"Ollama embed returned {mat.shape[0]} vectors for "
                    f"{len(inputs)} inputs."
                )
            return mat[0] if single else mat

        # Legacy endpoint: one request per input.
        vecs_out: List[np.ndarray] = []
        for t in inputs:
            response = client.embeddings(model=model, prompt=t)
            if isinstance(response, dict):
                vec = response.get("embedding", [])
            else:
                vec = getattr(response, "embedding", [])
            vecs_out.append(np.asarray(vec, dtype=np.float32))
        mat = np.stack(vecs_out) if vecs_out else np.zeros((0, 0), dtype=np.float32)
        return mat[0] if single else mat

    def _resolve_embedding_model(self, default: str) -> str:
        """Return the configured embedding model name or a sensible default."""
        # Allow callers to override the embedding model via a `embedding_model`
        # attribute set externally; otherwise fall back to a sane default.
        return getattr(self, "embedding_model", None) or default

    def list_models(self) -> List[str]:
        """Return the list of available model identifiers for the active provider."""
        client = self._ensure_client()
        if self.provider is LLMProvider.NONE:
            return client.list_models()

        if self.provider is LLMProvider.OPENAI:
            try:
                response = client.models.list()
                return [m.id for m in response.data]
            except Exception:  # noqa: BLE001 - degraded but usable
                logger.exception("Failed to list OpenAI models")
                return ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]

        if self.provider is LLMProvider.ANTHROPIC:
            # Prefer the real Models API (client.models.list, 2026 SDKs);
            # fall back to a hardcoded known-good list.
            try:
                response = client.models.list()
                names: List[str] = []
                for m in getattr(response, "data", []) or []:
                    mid = getattr(m, "id", None) or getattr(m, "name", None)
                    if mid:
                        names.append(str(mid))
                if names:
                    return names
            except Exception:  # noqa: BLE001 - degraded but usable
                logger.debug("Anthropic models.list() unavailable; using fallback list.")
            return [
                "claude-sonnet-5-5",
                "claude-opus-5-5",
                "claude-haiku-4-5-20251001",
                "claude-3-5-sonnet-20241022",
                "claude-3-5-haiku-20241022",
                "claude-3-opus-20240229",
            ]

        if self.provider is LLMProvider.OLLAMA:
            try:
                response = client.list()
                if isinstance(response, dict):
                    models = response.get("models", [])
                else:
                    models = getattr(response, "models", [])
                names: List[str] = []
                for m in models:
                    if isinstance(m, dict):
                        names.append(m.get("name") or m.get("model") or "")
                    else:
                        names.append(getattr(m, "name", "") or getattr(m, "model", ""))
                return [n for n in names if n]
            except Exception:  # noqa: BLE001
                logger.exception("Failed to list Ollama models")
                return ["llama3.1", "mistral", "qwen2.5"]

        raise ValueError(f"Unsupported provider: {self.provider}")


__all__ = ["LLMProvider", "LLMClient"]
