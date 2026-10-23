"""REST endpoints for the ``/api/scraping`` resource.

Provides async-style scrape task submission (returns a task id),
polling endpoints for status, live WebSocket progress streaming,
discovery of available scrapers, and task cancellation.

Worker contract (contract #8): the background thread calls
``ScrapingEngine.search_all(query, sources=..., max_results=...,
should_cancel=...)`` with a cancellation callable, stores **JSON-safe
dicts** (never ``Paper`` objects), and streams progress to the
``task:<id>`` Socket.IO room **and** the process-wide
:class:`core.events.EventBus` (string topics, e.g. ``scrape:progress``).
Task state is copied on write, so request threads never race the
worker mutating its local dict.
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

from web.routes._common import (
    accepted_kwargs,
    as_int,
    bad_request,
    error_response,
    json_safe,
    not_found,
    service_unavailable,
)

logger = logging.getLogger(__name__)

scraping_bp = Blueprint("scraping", __name__, url_prefix="/api/scraping")

# Cap on how many result dicts are retained per task in memory.
_MAX_STORED_RESULTS = 1000

# Cancellation flags per task id (threading.Event, checked by the
# worker between sources via the ``should_cancel`` callable).
_CANCEL_EVENTS: dict[str, threading.Event] = {}
_CANCEL_LOCK = threading.Lock()


def _state() -> "Any":
    """Return the shared :class:`ServerState` singleton."""
    from web.server import ServerState

    return ServerState()


def _service_unavailable(name: str):
    """Helper: build a 503 JSON response for a missing backend service."""
    return service_unavailable(name)


def _pop_cancel_event(task_id: str) -> threading.Event | None:
    with _CANCEL_LOCK:
        return _CANCEL_EVENTS.pop(task_id, None)


def _set_cancel_event(task_id: str) -> threading.Event:
    with _CANCEL_LOCK:
        event = _CANCEL_EVENTS.get(task_id)
        if event is None:
            event = threading.Event()
            _CANCEL_EVENTS[task_id] = event
        return event


def _bus_publish(topic: str, payload: dict[str, Any]) -> None:
    """Publish a string topic on the process-wide EventBus.

    Contract #2: ``publish(event_or_topic, payload=None)`` wraps a str
    topic into an :class:`core.events.Event`. Failures are logged at
    debug level and never break the scrape pipeline.
    """
    try:
        from core.events import get_event_bus

        get_event_bus().publish(topic, payload)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("event bus publish(%s) failed: %s", topic, exc)


# Full metadata catalog for every scraper shipped with the suite.
# Keyed by scraper name; ``requires_key`` entries are only registered
# by the engine when a usable API key is discoverable.
_SCRAPER_CATALOG: dict[str, dict[str, Any]] = {
    "arxiv": {"display": "arXiv", "supports": ["search", "metadata", "fulltext"],
              "rate_limit": "1 req/s", "requires_proxy": False, "requires_key": False},
    "pubmed": {"display": "PubMed", "supports": ["search", "metadata"],
               "rate_limit": "3 req/s (no key)", "requires_proxy": False, "requires_key": False},
    "openalex": {"display": "OpenAlex", "supports": ["search", "metadata", "citations"],
                 "rate_limit": "10 req/s (polite pool)", "requires_proxy": False, "requires_key": False},
    "semantic_scholar": {"display": "Semantic Scholar", "supports": ["search", "metadata", "embeddings"],
                         "rate_limit": "1 req/s (no key)", "requires_proxy": False, "requires_key": False},
    "crossref": {"display": "Crossref", "supports": ["search", "metadata", "doi_lookup"],
                 "rate_limit": "50 req/s (polite pool)", "requires_proxy": False, "requires_key": False},
    "dblp": {"display": "DBLP", "supports": ["search", "metadata"],
             "rate_limit": "1 req/s", "requires_proxy": False, "requires_key": False},
    "google_scholar": {"display": "Google Scholar", "supports": ["search", "metadata", "citations"],
                       "rate_limit": "very restricted", "requires_proxy": True, "requires_key": False},
    "orcid": {"display": "ORCID", "supports": ["author_lookup"],
              "rate_limit": "24 req/s", "requires_proxy": False, "requires_key": False},
    "springer": {"display": "Springer Nature", "supports": ["search", "metadata"],
                 "rate_limit": "API-key gated", "requires_proxy": False, "requires_key": True},
    "ieee": {"display": "IEEE Xplore", "supports": ["search", "metadata"],
             "rate_limit": "API-key gated", "requires_proxy": False, "requires_key": True},
    "acm": {"display": "ACM Digital Library", "supports": ["search", "metadata"],
            "rate_limit": "0.33 req/s", "requires_proxy": False, "requires_key": False},
    "core": {"display": "CORE", "supports": ["search", "metadata", "fulltext"],
             "rate_limit": "API-key gated", "requires_proxy": False, "requires_key": True},
    "base": {"display": "BASE", "supports": ["search", "metadata"],
             "rate_limit": "API-key gated (optional)", "requires_proxy": False, "requires_key": True},
    "unpaywall": {"display": "Unpaywall", "supports": ["oa_lookup"],
                  "rate_limit": "5 req/s", "requires_proxy": False, "requires_key": False},
    "opencitations": {"display": "OpenCitations", "supports": ["citations"],
                      "rate_limit": "3 req/s", "requires_proxy": False, "requires_key": False},
    "sciopen": {"display": "SciOpen", "supports": ["search", "metadata"],
                "rate_limit": "0.33 req/s", "requires_proxy": False, "requires_key": False},
    "wikipedia": {"display": "Wikipedia", "supports": ["search", "metadata"],
                  "rate_limit": "3 req/s", "requires_proxy": False, "requires_key": False},
}


def _default_scrapers() -> list[dict[str, Any]]:
    """Return metadata for the canonical set of scrapers.

    Used as a fallback when the ScrapingEngine cannot be imported, so
    that ``GET /api/scraping/sources`` always returns a useful answer.
    """
    return [
        dict(meta, name=name, active=not meta.get("requires_key", False))
        for name, meta in _SCRAPER_CATALOG.items()
    ]


def _paper_to_dict(paper: Any) -> dict[str, Any]:
    """Convert a scraper result to a JSON-safe dict (never a Paper obj)."""
    if isinstance(paper, dict):
        data = dict(paper)
    else:
        to_dict = getattr(paper, "to_dict", None)
        if callable(to_dict):
            data = to_dict()
        elif hasattr(paper, "__dict__"):
            data = {k: v for k, v in vars(paper).items()
                    if not k.startswith("_")}
        else:
            data = {"value": str(paper)}
    return json_safe(data)


def _extract_papers(result: Any) -> tuple[list, int]:
    """Normalise the many shapes ``search_all`` may return.

    Handles ``(papers, total)`` tuples, :class:`ScraperResult`-like
    objects with a ``.papers`` attribute, bare lists, and single items.
    """
    if result is None:
        return [], 0
    if isinstance(result, tuple) and len(result) == 2 \
            and isinstance(result[0], (list, tuple)):
        papers = list(result[0])
        total = result[1] if isinstance(result[1], int) else len(papers)
        return papers, total
    papers_attr = getattr(result, "papers", None)
    if isinstance(papers_attr, (list, tuple)):
        papers = list(papers_attr)
        total = getattr(result, "total_results", None)
        return papers, total if isinstance(total, int) else len(papers)
    if isinstance(result, (list, tuple)):
        return list(result), len(result)
    return [result], 1


def _emit_socket(state: Any, task_id: str, event: str,
                 data: dict[str, Any]) -> None:
    """Emit a Socket.IO event scoped to the ``task:<id>`` room."""
    sio = state.socketio
    if sio is None:
        return
    try:
        sio.emit(event, data, room=f"task:{task_id}", namespace="/")
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("socket emit %s failed: %s", event, exc)


def _run_scrape_task(task_id: str, query: str, sources: list[str],
                     max_results: int, filters: dict[str, Any],
                     cancel_event: threading.Event) -> None:
    """Background worker that drives ``ScrapingEngine.search_all``.

    Runs in a daemon thread, streams progress to the ``task:<id>``
    socket room and the EventBus, and publishes JSON-safe snapshots of
    the task state to the shared registry. All registry writes go
    through :meth:`ServerState.update_task`, which mutates the shared
    task dict under its lock — the ``/cancel`` route's ``cancelled``
    status can never be lost to a concurrent worker write.
    """
    state = _state()
    engine = state.scraping_engine

    def _progress(pct: Any = None, msg: str = "") -> None:
        try:
            progress = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            progress = None
        payload = {"task_id": task_id, "progress": progress, "message": msg}
        _emit_socket(state, task_id, "scrape:progress", payload)
        _bus_publish("scrape:progress", payload)

    state.update_task(task_id, {"status": "running",
                                "started_at": time.time()})

    try:
        if engine is None:
            _progress(0.0, "scraping engine unavailable")
            papers: list = []
            total = 0
        else:
            # Contract #8: search_all(query, sources=None, max_results=10,
            # should_cancel=None, **filters). Keyword injection is
            # signature-aware so the call also works against engines that
            # do not yet declare the new kwargs; body ``filters`` are
            # forwarded only when the engine declares them.
            wanted: dict[str, Any] = {
                "query": query,
                "sources": sources or None,
                "max_results": max_results,
                "should_cancel": cancel_event.is_set,
                "progress_callback": _progress,
                **{str(k): v for k, v in (filters or {}).items()},
            }
            kwargs = accepted_kwargs(engine.search_all, wanted)
            if "sources" not in kwargs:
                # Never drop the primary positional parameter.
                kwargs["sources"] = wanted["sources"]
            result = engine.search_all(**kwargs)
            raw_papers, total = _extract_papers(result)
            # Store serializable dicts (paper.to_dict()) — never Paper
            # objects — and cap memory retention per task.
            papers = [_paper_to_dict(p) for p in raw_papers][:_MAX_STORED_RESULTS]
            _progress(100.0, f"completed: {len(papers)} papers")

        done_payload = {"task_id": task_id, "count": len(papers)}
        _emit_socket(state, task_id, "scrape:complete", done_payload)
        _bus_publish("scrape:completed", done_payload)
        final = {
            "status": "cancelled" if cancel_event.is_set() else "completed",
            "completed_at": time.time(),
            "results_count": len(papers),
            "total": total if isinstance(total, int) else len(papers),
            "results": papers,
        }
    except Exception as exc:
        logger.exception("scrape task %s failed: %s", task_id, exc)
        cancelled = cancel_event.is_set()
        if cancelled:
            payload = {"task_id": task_id}
            _emit_socket(state, task_id, "scrape:cancelled", payload)
            _bus_publish("scrape:cancelled", payload)
        else:
            payload = {"task_id": task_id,
                       "error": "scrape failed; see server logs"}
            _emit_socket(state, task_id, "scrape:error", payload)
            _bus_publish("scrape:failed", payload)
        final = {
            "status": "cancelled" if cancelled else "failed",
            "completed_at": time.time(),
            "error": "task cancelled" if cancelled
                     else "scrape failed; see server logs",
        }
    finally:
        # Lock-guarded merge into the shared registry entry.
        state.update_task(task_id, final)
        if final.get("status") in {"completed", "failed", "cancelled"}:
            _pop_cancel_event(task_id)


@scraping_bp.route("/search", methods=["POST"])
def start_search():
    """Submit a new scraping search task.

    Body: ``{"query": str, "sources": [str]? , "max_results": int?,
    "filters": dict?}``. Returns ``{"task_id": str}`` immediately; the
    caller polls ``GET /api/scraping/tasks/<task_id>`` or subscribes via
    WebSocket for live updates.
    """
    payload = request.get_json(silent=True) or {}
    query = (payload.get("query") or "").strip()
    if not query:
        return bad_request("query is required")

    sources = payload.get("sources") or []
    if not isinstance(sources, list) or \
            not all(isinstance(s, str) for s in sources):
        return bad_request("sources must be a list of strings")
    try:
        max_results = as_int(payload.get("max_results"), 25,
                             name="max_results", minimum=1, maximum=1000)
    except ValueError as exc:
        return bad_request(str(exc))
    filters = payload.get("filters") or {}
    if not isinstance(filters, dict):
        return bad_request("filters must be an object")

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
    _state().register_task(task_id, task)

    cancel_event = _set_cancel_event(task_id)
    thread = threading.Thread(
        target=_run_scrape_task,
        args=(task_id, query, sources, max_results, filters, cancel_event),
        daemon=True,
        name=f"scrape-{task_id[:8]}",
    )
    thread.start()

    return jsonify({"task_id": task_id, "status": "queued"}), 202


@scraping_bp.route("/tasks/<task_id>", methods=["GET"])
def get_task(task_id: str):
    """Poll the status of a scrape task."""
    state = _state()
    task = state.get_task(task_id)
    if task is None:
        return not_found(f"task {task_id} not found")
    # json_safe guarantees datetime/Decimal fields from results
    # serialise cleanly.
    return jsonify(json_safe(task))


@scraping_bp.route("/tasks", methods=["GET"])
def list_tasks():
    """List all known scrape tasks."""
    state = _state()
    tasks = [json_safe(t) for t in state.all_tasks().values()]
    return jsonify({"tasks": tasks})


@scraping_bp.route("/sources", methods=["GET"])
def list_sources():
    """Return metadata for every available scraper.

    Queries the engine's real registry (``available_scrapers()``) and
    merges it with the static catalog, so the response always reflects
    which scrapers are actually registered (keyless + key-gated ones
    whose API key was found) and which are inactive.
    """
    state = _state()
    engine = state.scraping_engine
    active: list[str] = []
    if engine is not None and hasattr(engine, "available_scrapers"):
        try:
            active = list(engine.available_scrapers())
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("available_scrapers failed: %s", exc)
            active = []
    if active:
        sources = [
            dict(meta, name=name, active=(name in active))
            for name, meta in _SCRAPER_CATALOG.items()
        ]
        # Include any engine-registered scraper missing from the catalog.
        for name in active:
            if name not in _SCRAPER_CATALOG:
                sources.append({"name": name, "display": name,
                                "supports": ["search"], "rate_limit": "",
                                "requires_proxy": False,
                                "requires_key": False, "active": True})
    else:
        sources = _default_scrapers()
    active_count = sum(1 for s in sources if s.get("active"))
    return jsonify({"sources": sources, "count": len(sources),
                    "active_count": active_count})


@scraping_bp.route("/cancel/<task_id>", methods=["POST"])
def cancel_task(task_id: str):
    """Request cancellation of a running scrape task.

    The worker observes the flag between sources through the
    ``should_cancel`` callable handed to ``search_all``.
    """
    state = _state()
    task = state.get_task(task_id)
    if task is None:
        return not_found(f"task {task_id} not found")

    if task.get("status") in {"completed", "failed", "cancelled"}:
        return jsonify({"task_id": task_id, "status": task["status"],
                        "cancelled": False})

    with _CANCEL_LOCK:
        event = _CANCEL_EVENTS.get(task_id)
        if event is None:
            event = threading.Event()
            _CANCEL_EVENTS[task_id] = event
        event.set()

    # Lock-guarded status merge into the shared registry record.
    state.update_task(task_id, {"status": "cancelled",
                                "completed_at": time.time()})
    payload = {"task_id": task_id}
    _emit_socket(state, task_id, "scrape:cancelled", payload)
    _bus_publish("scrape:cancelled", payload)
    return jsonify({"task_id": task_id, "status": "cancelled",
                    "cancelled": True})
