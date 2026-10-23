"""REST endpoints for the ``/api/ai`` resource.

Provides streaming chat (Server-Sent Events), non-streaming chat,
summarization, model discovery, and embedding generation.

ChatEngine contract (contract #5):

* ``stream_chat(messages=None, prompt=None, **kw)`` — token generator.
* ``chat(messages=None, prompt=None, **kw) -> ChatResponse`` (compat →
  ``send()``).
* ``summarize(text, max_words=250) -> str``.

Embeddings use ``data_science.embeddings.EmbeddingsModel.encode``.
A missing engine yields a clear 503 JSON body — exception detail is
never echoed to clients.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import json
import logging
from typing import Any, Generator

from flask import Blueprint, Response, jsonify, request, stream_with_context

from web.routes._common import (
    as_int,
    bad_request,
    error_response,
    json_safe,
    not_found,
    serialize_paper,
    service_unavailable,
)

logger = logging.getLogger(__name__)

ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")


def _state() -> "Any":
    """Return the shared :class:`ServerState` singleton."""
    from web.server import ServerState

    return ServerState()


def _sse(payload: dict[str, Any]) -> str:
    """Format a dict as a Server-Sent-Events data line."""
    return f"data: {json.dumps(payload)}\n\n"


def _build_messages(history: list, message: str) -> list[dict[str, str]]:
    """Merge chat history + the new user message into a message list."""
    messages: list[dict[str, str]] = []
    for item in history or []:
        if isinstance(item, dict) and item.get("role") and \
                item.get("content") is not None:
            messages.append({"role": str(item["role"]),
                             "content": str(item["content"])})
    messages.append({"role": "user", "content": message})
    return messages


def _configured_provider(engine: Any) -> str:
    """Return the engine's effective LLM provider id ('' if unknown)."""
    client = getattr(engine, "llm_client", None)
    if client is None:
        client = getattr(engine, "client", None)
    raw = getattr(client, "provider", None) if client is not None else None
    if raw is None:
        try:
            from config.settings import get_settings

            raw = getattr(get_settings(), "ai_provider", None)
        except Exception:  # pragma: no cover - defensive
            raw = None
    return str(getattr(raw, "value", raw) or "").strip().lower()


def _no_provider_response():
    """503 JSON for a ChatEngine with no usable provider configured."""
    return jsonify({
        "error": "no_provider",
        "message": "No LLM provider is configured. Set ai_provider "
                   "(openai|anthropic|ollama) and the matching API key "
                   "in Settings (or the OPENAI_API_KEY / ANTHROPIC_API_KEY "
                   "environment variables), then restart the server.",
    }), 503


@ai_bp.route("/chat", methods=["POST"])
def chat():
    """Stream a chat completion as Server-Sent Events (or plain JSON).

    Body: ``{"message": str, "history": [ {role, content} ]?,
    "stream": bool?, "project_id": int?}``.

    Streaming (default) returns ``text/event-stream``; each event is a
    JSON object with ``{"token": str}`` for incremental output, ending
    with a ``{"done": true}`` event. With ``"stream": false`` the
    complete ``ChatResponse`` is returned as JSON.
    """
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return bad_request("message is required")

    history = payload.get("history") or []
    if not isinstance(history, list):
        return bad_request("history must be a list of {role, content} items")
    project_id = payload.get("project_id")
    stream = payload.get("stream", True)

    engine = _state().chat_engine
    if engine is None:
        return service_unavailable("ChatEngine")
    if _configured_provider(engine) in ("", "none", "echo"):
        # Contract #5 fallback engines (echo) must not masquerade as a
        # working assistant — fail with a clear, actionable 503.
        return _no_provider_response()

    messages = _build_messages(history, message)

    if not stream:
        try:
            # Contract: chat(messages=None, prompt=None, **kw) -> ChatResponse
            response = engine.chat(messages=messages, prompt=message,
                                   project_id=project_id)
        except Exception as exc:  # pragma: no cover - defensive
            return error_response(logger, "chat", exc, status=502,
                                  error="chat_failed")
        if hasattr(response, "to_dict"):
            body = response.to_dict()
        elif hasattr(response, "__dict__"):
            body = {k: v for k, v in vars(response).items()
                    if not k.startswith("_")}
        else:
            body = {"response": str(response)}
        return jsonify(json_safe(body))

    def generate() -> Generator[str, None, None]:
        try:
            # Contract: stream_chat(messages=None, prompt=None, **kw)
            for token in engine.stream_chat(messages=messages,
                                            prompt=message,
                                            project_id=project_id):
                yield _sse({"token": token})
            yield _sse({"done": True})
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("chat stream failed: %s", exc)
            yield _sse({"error": "chat_failed",
                        "message": "the chat stream failed; see server logs"})
            yield _sse({"done": True})

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # disable proxy buffering
        "Connection": "keep-alive",
    }
    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream", headers=headers)


@ai_bp.route("/summarize", methods=["POST"])
def summarize():
    """Summarize free text or the project's papers.

    Body: ``{"text": str, "max_words": int?}`` or
    ``{"paper_ids": [int], "max_words": int?}`` (the papers' titles +
    abstracts are concatenated into the text to summarize).
    """
    payload = request.get_json(silent=True) or {}
    max_words = 250
    if payload.get("max_words") is not None:
        try:
            max_words = as_int(payload.get("max_words"), 250,
                               name="max_words", minimum=20, maximum=2000)
        except ValueError as exc:
            return bad_request(str(exc))

    text = payload.get("text")
    paper_ids = payload.get("paper_ids")

    engine = _state().chat_engine
    if engine is None:
        return service_unavailable("ChatEngine")
    if _configured_provider(engine) in ("", "none", "echo"):
        return _no_provider_response()

    if text is None and paper_ids:
        if not isinstance(paper_ids, list):
            return bad_request("paper_ids must be a list of ints")
        db = _state().db
        if db is None:
            return service_unavailable("DatabaseConnection")
        try:
            ids = [as_int(pid, name="paper_ids entry") for pid in paper_ids]
            papers = db.get_papers_by_ids(ids) or []
        except ValueError as exc:
            return bad_request(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return error_response(logger, "summarize paper lookup", exc)
        if not papers:
            return not_found("no papers resolved for given ids")
        parts = []
        for paper in papers:
            record = serialize_paper(paper)
            title = record.get("title") or ""
            abstract = record.get("abstract") or ""
            parts.append(f"{title}. {abstract}".strip())
        text = "\n\n".join(parts)

    if not text or not str(text).strip():
        return bad_request("text (or paper_ids) is required")

    try:
        # Contract: summarize(text, max_words=250) -> str
        result = engine.summarize(str(text), max_words=max_words)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "summarize", exc, status=502,
                              error="summarize_failed")

    return jsonify({"summary": result, "max_words": max_words})


@ai_bp.route("/models", methods=["GET"])
def list_models():
    """List available LLM models.

    Query param ``provider`` filters to ``openai``, ``anthropic``,
    ``ollama``, or ``all`` (default).
    """
    provider = request.args.get("provider", "all")
    state = _state()
    engine = state.chat_engine

    if engine is not None and hasattr(engine, "list_models"):
        try:
            models = engine.list_models(provider=provider)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("list_models failed: %s", exc)
            models = {}
    else:
        # Sensible defaults so the endpoint always returns something useful.
        models = {
            "openai": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
            "anthropic": ["claude-sonnet-5-5", "claude-opus-5-5",
                          "claude-haiku-4-5-20251001",
                          "claude-3-5-sonnet", "claude-3-haiku",
                          "claude-3-opus"],
            "ollama": ["llama3", "mistral", "phi3", "qwen2.5"],
        }
        if provider != "all" and provider in models:
            models = {provider: models[provider]}

    return jsonify({"provider": provider, "models": models})


@ai_bp.route("/embeddings", methods=["POST"])
def embeddings():
    """Generate embeddings for a list of texts.

    Body: ``{"texts": [str], "model": str?}``. Returns a list of float
    vectors, one per input text (``EmbeddingsModel.encode``; mock mode
    activates automatically when sentence-transformers is missing).
    """
    payload = request.get_json(silent=True) or {}
    texts = payload.get("texts") or []
    if not isinstance(texts, list) or not texts or \
            not all(isinstance(t, str) for t in texts):
        return bad_request("texts (non-empty list of strings) is required")

    model = payload.get("model") or "all-MiniLM-L6-v2"

    try:
        from data_science.embeddings import EmbeddingsModel

        emb_model = EmbeddingsModel(model_name=model)
        vectors = emb_model.encode(texts)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "embeddings", exc, status=502,
                              error="embeddings_failed")

    # numpy arrays (or lists of arrays) → plain nested lists.
    tolist = getattr(vectors, "tolist", None)
    if callable(tolist):
        vectors = tolist()
    vectors = [list(v) for v in vectors]

    return jsonify({"model": model, "count": len(vectors),
                    "vectors": vectors})
