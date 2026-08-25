"""REST endpoints for the ``/api/scraping`` resource.

Provides async-style scrape task submission (returns a task id),
polling endpoints for status, live WebSocket progress streaming,
discovery of available scrapers, and task cancellation.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

scraping_bp = Blueprint("scraping", __name__, url_prefix="/api/scraping")


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


def _default_scrapers() -> list[dict[str, Any]]:
    """Return metadata for the canonical set of scrapers.

    Used as a fallback when the ScrapingEngine cannot be imported, so
    that ``GET /api/scraping/sources`` always returns a useful answer.
    """
    return [
        {"name": "arxiv", "display": "arXiv",
         "supports": ["search", "metadata", "fulltext"],
         "rate_limit": "1 req/s", "requires_proxy": False},
        {"name": "pubmed", "display": "PubMed",
         "supports": ["search", "metadata"],
         "rate_limit": "3 req/s (no key)", "requires_proxy": False},
        {"name": "openalex", "display": "OpenAlex",
         "supports": ["search", "metadata", "citations"],
         "rate_limit": "10 req/s (polite pool)", "requires_proxy": False},
        {"name": "semantic_scholar", "display": "Semantic Scholar",
         "supports": ["search", "metadata", "embeddings"],
         "rate_limit": "1 req/s (no key)", "requires_proxy": False},
        {"name": "crossref", "display": "Crossref",
         "supports": ["search", "metadata", "doi_lookup"],
         "rate_limit": "50 req/s (polite pool)", "requires_proxy": False},
        {"name": "dblp", "display": "DBLP",
         "supports": ["search", "metadata"],
         "rate_limit": "1 req/s", "requires_proxy": False},
        {"name": "google_scholar", "display": "Google Scholar",
         "supports": ["search", "metadata", "citations"],
         "rate_limit": "very restricted", "requires_proxy": True},
        {"name": "orcid", "display": "ORCID",
         "supports": ["author_lookup"],
         "rate_limit": "24 req/s", "requires_proxy": False},
    ]


def _run_scrape_task(task_id: str, query: str, sources: list[str],
                     max_results: int, filters: dict[str, Any]) -> None:
    """Background worker that drives the ScrapingEngine.

    Runs in a daemon thread, emits progress events through Socket.IO
    when available, and updates the task registry on completion.
    """
    state = _state()
    engine = state.scraping_engine
    task = state.get_task(task_id) or {}
    task.update({"status": "running", "started_at": time.time()})
    state.register_task(task_id, task)

    def _emit(event: str, data: dict[str, Any]) -> None:
        sio = state.socketio
        if sio is None:
            return
        try:
            sio.emit(event, data, room=f"task:{task_id}",
                      namespace="/")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("socket emit failed: %s", exc)

    try:
        if engine is None or not hasattr(engine, "search"):
            # Backend not wired up — simulate a brief noop so the API
            # surface still works end-to-end during development.
            _emit("scrape:progress", {"task_id": task_id, "progress": 0.0,
                                      "message": "engine unavailable"})
            results: list[Any] = []
            total = 0
        else:
            results, total = engine.search(
                query=query, sources=sources, max_results=max_results,
                filters=filters,
                progress_callback=lambda p, msg="": _emit(
                    "scrape:progress",
                    {"task_id": task_id, "progress": p, "message": msg},
                ),
            )
        task.update({
            "status": "completed",
            "completed_at": time.time(),
            "results_count": len(results) if hasattr(results, "__len__") else 0,
            "total": total if isinstance(total, int) else 0,
            "results": results if isinstance(results, list) else [],
        })
        _emit("scrape:complete", {"task_id": task_id,
                                  "count": task["results_count"]})
    except Exception as exc:
        logger.exception("scrape task %s failed: %s", task_id, exc)
        task.update({"status": "failed", "error": str(exc),
                     "completed_at": time.time()})
        _emit("scrape:error", {"task_id": task_id, "error": str(exc)})
    finally:
        state.register_task(task_id, task)


@scraping_bp.route("/search", methods=["POST"])
def start_search():
    """Submit a new scraping search task.

    Body: ``{"query": str, "sources": [str]? , "max_results": int?,
    "filters": dict?}``. Returns ``{"task_id": str}`` immediately; the
    caller polls ``GET /api/scraping/tasks/<task_id>`` or subscribes via
    WebSocket for live updates.
    """
    state = _state()
    payload = request.get_json(silent=True) or {}
    query = (payload.get("query") or "").strip()
    if not query:
        return jsonify({"error": "bad_request",
                        "message": "query is required"}), 400

    sources = payload.get("sources") or []
    max_results = int(payload.get("max_results", 25))
    filters = payload.get("filters") or {}

    task_id = uuid.uuid4().hex
    task = {
        "task_id": task_id,
        "query": query,
        "sources": sources,
        "max_results": max_results,
        "filters": filters,
        "status": "queued",
        "created_at": time.time(),
        "results_count": 0,
        "total": 0,
    }
    state.register_task(task_id, task)

    thread = threading.Thread(
        target=_run_scrape_task,
        args=(task_id, query, sources, max_results, filters),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "status": "queued"}), 202


@scraping_bp.route("/tasks/<task_id>", methods=["GET"])
def get_task(task_id: str):
    """Poll the status of a scrape task."""
    state = _state()
    task = state.get_task(task_id)
    if task is None:
        return jsonify({"error": "not_found",
                        "message": f"task {task_id} not found"}), 404
    return jsonify(task)


@scraping_bp.route("/tasks", methods=["GET"])
def list_tasks():
    """List all known scrape tasks."""
    state = _state()
    return jsonify({"tasks": list(state.all_tasks().values())})


@scraping_bp.route("/sources", methods=["GET"])
def list_sources():
    """Return metadata for every available scraper."""
    state = _state()
    engine = state.scraping_engine
    if engine is not None and hasattr(engine, "list_sources"):
        try:
            sources = engine.list_sources()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("list_sources failed: %s", exc)
            sources = _default_scrapers()
    else:
        sources = _default_scrapers()
    return jsonify({"sources": sources, "count": len(sources)})


@scraping_bp.route("/cancel/<task_id>", methods=["POST"])
def cancel_task(task_id: str):
    """Request cancellation of a running scrape task."""
    state = _state()
    task = state.get_task(task_id)
    if task is None:
        return jsonify({"error": "not_found",
                        "message": f"task {task_id} not found"}), 404

    if task.get("status") in {"completed", "failed", "cancelled"}:
        return jsonify({"task_id": task_id, "status": task["status"],
                        "cancelled": False})

    engine = state.scraping_engine
    if engine is not None and hasattr(engine, "cancel"):
        try:
            engine.cancel(task_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("engine.cancel failed: %s", exc)

    task["status"] = "cancelled"
    task["completed_at"] = time.time()
    state.register_task(task_id, task)
    sio = state.socketio
    if sio is not None:
        try:
            sio.emit("scrape:cancelled", {"task_id": task_id})
        except Exception:  # pragma: no cover - defensive
            pass
    return jsonify({"task_id": task_id, "status": "cancelled",
                    "cancelled": True})
