"""REST endpoints for the ``/api/papers`` resource.

Provides listing, filtering, full-text search, manual insertion,
similar-paper lookup (via embeddings), and deletion of papers. All
backend services are accessed lazily through :class:`ServerState` so the
endpoints degrade to informative 503 responses when the database layer
has not been wired up yet.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import uuid
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

papers_bp = Blueprint("papers", __name__, url_prefix="/api/papers")


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


def _serialize_paper(paper: Any) -> dict[str, Any]:
    """Best-effort conversion of a paper-like object to a JSON dict.

    Accepts SQLAlchemy models, dataclasses, or plain dicts. Falls back
    to ``vars()`` or ``__dict__`` and strips private attributes.
    """
    if isinstance(paper, dict):
        data = dict(paper)
    elif hasattr(paper, "to_dict") and callable(paper.to_dict):
        data = paper.to_dict()
    elif hasattr(paper, "__dict__"):
        data = {k: v for k, v in vars(paper).items() if not k.startswith("_")}
    else:
        data = {"value": str(paper)}
    # Strip SQLAlchemy internal state if present.
    data.pop("_sa_instance_state", None)
    return data


@papers_bp.route("/", methods=["GET"])
def list_papers():
    """List papers with pagination and optional filters.

    Query params:
        source:     Filter by data source (e.g. ``arxiv``).
        year:       Filter by publication year.
        q:          Free-text filter on title / abstract.
        project_id: Restrict to papers attached to a project.
        page:       1-indexed page number (default 1).
        per_page:   Page size, capped at 100 (default 20).
    """
    state = _state()
    db = state.db
    if db is None:
        return _service_unavailable("DatabaseConnection")

    source = request.args.get("source")
    year = request.args.get("year", type=int)
    q = request.args.get("q")
    project_id = request.args.get("project_id", type=int)
    page = max(request.args.get("page", default=1, type=int), 1)
    per_page = min(max(request.args.get("per_page", default=20, type=int), 1), 100)

    try:
        # ``list_papers`` is the canonical method name on DatabaseConnection.
        if hasattr(db, "list_papers"):
            papers, total = db.list_papers(
                source=source, year=year, query=q,
                project_id=project_id, page=page, per_page=per_page,
            )
        else:
            # Fallback for in-development DB stubs.
            papers, total = [], 0
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("list_papers failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify({
        "papers": [_serialize_paper(p) for p in papers],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
    })


@papers_bp.route("/<int:paper_id>", methods=["GET"])
def get_paper(paper_id: int):
    """Return the full record for a single paper."""
    state = _state()
    db = state.db
    if db is None:
        return _service_unavailable("DatabaseConnection")

    try:
        if hasattr(db, "get_paper"):
            paper = db.get_paper(paper_id)
        else:
            paper = None
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("get_paper failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    if paper is None:
        return jsonify({"error": "not_found",
                        "message": f"paper {paper_id} not found"}), 404
    return jsonify(_serialize_paper(paper))


@papers_bp.route("/", methods=["POST"])
def add_paper():
    """Add a paper manually.

    Expects a JSON body whose keys mirror the :class:`Paper` model
    (``title``, ``authors``, ``year``, ``doi``, ``abstract``, ``source``).
    Returns the created paper with its assigned ``id``.
    """
    state = _state()
    db = state.db
    if db is None:
        return _service_unavailable("DatabaseConnection")

    payload = request.get_json(silent=True) or {}
    if not payload.get("title"):
        return jsonify({"error": "bad_request",
                        "message": "title is required"}), 400

    payload.setdefault("source", "manual")
    payload.setdefault("external_id", str(uuid.uuid4()))

    try:
        if hasattr(db, "add_paper"):
            paper = db.add_paper(payload)
        else:
            paper = {"id": 0, **payload}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("add_paper failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify(_serialize_paper(paper)), 201


@papers_bp.route("/<int:paper_id>", methods=["DELETE"])
def delete_paper(paper_id: int):
    """Delete a paper by id."""
    state = _state()
    db = state.db
    if db is None:
        return _service_unavailable("DatabaseConnection")

    try:
        if hasattr(db, "delete_paper"):
            deleted = db.delete_paper(paper_id)
        else:
            deleted = False
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("delete_paper failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    if not deleted:
        return jsonify({"error": "not_found",
                        "message": f"paper {paper_id} not found"}), 404
    return jsonify({"deleted": True, "id": paper_id})


@papers_bp.route("/<int:paper_id>/similar", methods=["GET"])
def similar_papers(paper_id: int):
    """Find papers similar to the given one via embeddings.

    Query params:
        limit: Maximum number of neighbours (default 10).
    """
    state = _state()
    db = state.db
    if db is None:
        return _service_unavailable("DatabaseConnection")

    limit = min(max(request.args.get("limit", default=10, type=int), 1), 50)

    try:
        if hasattr(db, "find_similar_papers"):
            neighbours = db.find_similar_papers(paper_id, limit=limit) or []
        else:
            neighbours = []
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("similar_papers failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify({
        "paper_id": paper_id,
        "similar": [_serialize_paper(p) for p in neighbours],
    })


@papers_bp.route("/search", methods=["GET"])
def search_papers():
    """Full-text search across stored papers.

    Query params:
        q:       Search query (required).
        sources: Comma-separated source filter (optional).
        limit:   Maximum results (default 25, capped at 100).
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "bad_request",
                        "message": "q parameter is required"}), 400

    state = _state()
    db = state.db
    if db is None:
        return _service_unavailable("DatabaseConnection")

    sources_raw = request.args.get("sources", "")
    sources = [s.strip() for s in sources_raw.split(",") if s.strip()] or None
    limit = min(max(request.args.get("limit", default=25, type=int), 1), 100)

    try:
        if hasattr(db, "search_papers"):
            results = db.search_papers(q, sources=sources, limit=limit) or []
        else:
            results = []
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("search_papers failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify({
        "query": q,
        "sources": sources,
        "count": len(results),
        "results": [_serialize_paper(p) for p in results],
    })
