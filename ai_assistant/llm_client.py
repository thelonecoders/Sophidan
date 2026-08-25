"""Unified LLM client supporting Ollama, OpenAI, Anthropic, and an offline echo mode.

This module provides a single ``LLMClient`` class that wraps the three supported
LLM SDKs (OpenAI, Anthropic, Ollama) behind a provider-agnostic API. All heavy
third-party SDKs are imported lazily inside ``_ensure_client`` so that the module
imports cleanly even when those packages are not installed. When ``provider``
is ``LLMProvider.NONE`` (or any of the string aliases ``"none"``, ``"echo"``,
``"offline"``), a deterministic in-process echo backend is used so the entire
suite is testable without network access or API keys.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import hashlib
import logging
import os
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

    Example:
        >>> client = LLMClient(provider="none", model="echo")
        >>> client.chat([{"role": "user", "content": "hello"}])
        '[echo:8b1a99...] Received (user): hello ...'
    """

    DEFAULT_EMBEDDING_DIM = 384

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

    def __init__(
        self,
        provider: Union[LLMProvider, str] = LLMProvider.NONE,
        model: str = "echo",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
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
                falls back to ``config.settings.get_settings()`` and then to
                the appropriate environment variable.
            base_url: Optional override for the provider's API endpoint.

        Raises:
            ValueError: If ``provider`` cannot be resolved.
        """
        self.provider = self._resolve_provider(provider)
        self.model = model or "echo"
        self.api_key = api_key
        self.base_url = base_url
        self._client: Any = None
        self._apply_defaults_from_settings()
        logger.debug(
            "LLMClient initialized: provider=%s, model=%s, base_url=%s",
            self.provider.value,
            self.model,
            self.base_url,
        )

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

    def _apply_defaults_from_settings(self) -> None:
        """Populate missing fields from ``config.settings.get_settings()``.

        The settings module is imported lazily and the call is wrapped in a
        broad ``try/except`` so this method is a no-op when config is not yet
        available (e.g. during early bootstrap or tests).
        """
        settings: Any = None
        try:
            from config.settings import get_settings  # type: ignore[import]

            settings = get_settings()
        except Exception:  # noqa: BLE001 - settings is optional at this layer
            settings = None

        ai_cfg: Dict[str, Any] = {}
        if isinstance(settings, dict):
            ai_cfg = settings.get("ai_assistant", {}) or {}
        elif settings is not None:
            # Best-effort: try attribute / method access on a settings object.
            ai_cfg = getattr(settings, "ai_assistant", {}) or {}
            if not isinstance(ai_cfg, dict):
                ai_cfg = {}

        if self.provider is LLMProvider.NONE and ai_cfg.get("provider"):
            try:
                self.provider = self._resolve_provider(ai_cfg["provider"])
            except ValueError:
                logger.warning("Ignoring unknown provider in settings: %r", ai_cfg["provider"])

        if self.model in ("", "echo", None) and ai_cfg.get("model"):
            self.model = ai_cfg["model"]
        if self.api_key is None and ai_cfg.get("api_key"):
            self.api_key = ai_cfg["api_key"]
        if self.base_url is None and ai_cfg.get("base_url"):
            self.base_url = ai_cfg["base_url"]

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
            result = client.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
            return str(result)

        if self.provider is LLMProvider.OPENAI:
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
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
            response = client.messages.create(**kwargs)
            parts: List[str] = []
            for block in response.content:
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
            return "".join(parts)

        if self.provider is LLMProvider.OLLAMA:
            response = client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": temperature, "num_predict": max_tokens},
                stream=False,
            )
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
            for chunk in client.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            ):
                yield chunk
            return

        if self.provider is LLMProvider.OPENAI:
            stream = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for event in stream:
                try:
                    delta = event.choices[0].delta.content
                except (AttributeError, IndexError):
                    delta = None
                if delta:
                    yield delta
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
            with client.messages.stream(**kwargs) as s:
                for text in s.text_stream:
                    if text:
                        yield text
            return

        if self.provider is LLMProvider.OLLAMA:
            stream = client.chat(
                model=self.model,
                messages=messages,
                options={"temperature": temperature, "num_predict": max_tokens},
                stream=True,
            )
            for event in stream:
                if isinstance(event, dict):
                    content = event.get("message", {}).get("content", "")
                else:
                    content = getattr(getattr(event, "message", None), "content", "")
                if content:
                    yield content
            return

        raise ValueError(f"Unsupported provider: {self.provider}")

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
        """
        client = self._ensure_client()

        if self.provider is LLMProvider.NONE:
            return client.embed(text)

        if self.provider is LLMProvider.OPENAI:
            model = self._resolve_embedding_model("text-embedding-3-small")
            inputs = [text] if isinstance(text, str) else list(text)
            response = client.embeddings.create(model=model, input=inputs)
            mat = np.array(
                [d.embedding for d in response.data],
                dtype=np.float32,
            )
            return mat[0] if isinstance(text, str) else mat

        if self.provider is LLMProvider.ANTHROPIC:
            # Anthropic does not expose a native embeddings endpoint in the
            # SDK; fall back to the deterministic hash-based embedder so RAG
            # pipelines still function.
            logger.warning(
                "Anthropic has no native embeddings API; using hash-based fallback."
            )
            return _EchoBackend().embed(text)

        if self.provider is LLMProvider.OLLAMA:
            model = self._resolve_embedding_model("nomic-embed-text")
            inputs = [text] if isinstance(text, str) else list(text)
            vecs: List[np.ndarray] = []
            for t in inputs:
                response = client.embeddings(model=model, prompt=t)
                if isinstance(response, dict):
                    vec = response.get("embedding", [])
                else:
                    vec = getattr(response, "embedding", [])
                vecs.append(np.asarray(vec, dtype=np.float32))
            mat = np.stack(vecs) if vecs else np.zeros((0, 0), dtype=np.float32)
            return mat[0] if isinstance(text, str) else mat

        raise ValueError(f"Unsupported provider: {self.provider}")

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
            # Anthropic does not expose a public list-models endpoint.
            return [
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
