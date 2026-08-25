"""REST endpoints for the ``/api/ai`` resource.

Provides streaming chat (via Server-Sent Events), summarization, model
discovery, and embedding generation. All heavy AI dependencies
(``openai``, ``anthropic``, ``langchain``, ``sentence-transformers``)
are imported lazily inside handlers so the web server boots even when
those packages are not installed.
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

logger = logging.getLogger(__name__)

ai_bp = Blueprint("ai", __name__, url_prefix="/api/ai")


def _state() -> "Any":
    """Return the shared :class:`ServerState` singleton."""
    from web.server import ServerState

    return ServerState()


def _service_unavailable(name: str):
    """Helper: build a 503 JSON response for a missing backend service."""
    return jsonify({
        "error": "service_unavailable",
        "message": f"{name} is not initialised; backend module not yet wired up.",
    }), 503


def _sse(payload: dict[str, Any]) -> str:
    """Format a dict as a Server-Sent-Events data line."""
    return f"data: {json.dumps(payload)}\n\n"


@ai_bp.route("/chat", methods=["POST"])
def chat():
    """Stream a chat completion as Server-Sent Events.

    Body: ``{"message": str, "history": [ {role, content} ]?,
    "use_rag": bool?, "project_id": int?}``.

    The response is ``text/event-stream``; each event is a JSON object
    with ``{"token": str}`` for incremental output, ending with a
    ``{"done": true}`` event.
    """
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"error": "bad_request",
                        "message": "message is required"}), 400

    history = payload.get("history") or []
    use_rag = bool(payload.get("use_rag", False))
    project_id = payload.get("project_id")

    state = _state()
    engine = state.chat_engine

    def generate() -> Generator[str, None, None]:
        if engine is None or not hasattr(engine, "stream_chat"):
            yield _sse({"error": "chat_engine_unavailable",
                        "message": "ChatEngine not yet wired up."})
            yield _sse({"done": True})
            return

        try:
            for token in engine.stream_chat(
                message=message, history=history,
                use_rag=use_rag, project_id=project_id,
            ):
                yield _sse({"token": token})
            yield _sse({"done": True})
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("chat stream failed: %s", exc)
            yield _sse({"error": "internal_error", "message": str(exc)})
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
    """Summarize one or more papers.

    Body: ``{"paper_ids": [int], "type": str?}`` where ``type`` is one
    of ``abstract`` (default), ``key_findings``, ``lay_summary``,
    ``bulleted``.
    """
    payload = request.get_json(silent=True) or {}
    paper_ids = payload.get("paper_ids") or []
    if not isinstance(paper_ids, list) or not paper_ids:
        return jsonify({"error": "bad_request",
                        "message": "paper_ids (non-empty list) is required"}), 400

    summary_type = payload.get("type", "abstract")

    state = _state()
    db = state.db
    engine = state.chat_engine
    if engine is None:
        return _service_unavailable("ChatEngine")
    if db is None:
        return _service_unavailable("DatabaseConnection")

    try:
        if hasattr(engine, "summarize"):
            result = engine.summarize(paper_ids, summary_type=summary_type)
        else:
            result = {"paper_ids": paper_ids, "summary": "",
                      "type": summary_type}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("summarize failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify({"paper_ids": paper_ids, "type": summary_type,
                    "summary": result})


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
            "anthropic": ["claude-3-5-sonnet", "claude-3-haiku",
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
    vectors, one per input text.
    """
    payload = request.get_json(silent=True) or {}
    texts = payload.get("texts") or []
    if not isinstance(texts, list) or not texts:
        return jsonify({"error": "bad_request",
                        "message": "texts (non-empty list) is required"}), 400

    model = payload.get("model", "default")
    state = _state()

    try:
        import importlib

        module = importlib.import_module("data_science.embeddings")
        cls = getattr(module, "EmbeddingEngine")
        emb_engine = cls()
        if hasattr(emb_engine, "embed"):
            vectors = emb_engine.embed(texts, model=model)
        else:
            vectors = []
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("embeddings failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 502

    return jsonify({"model": model, "count": len(vectors),
                    "vectors": vectors})
