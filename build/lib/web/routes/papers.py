"""REST endpoints for the ``/api/papers`` resource.

Provides listing (with pagination), full-text search, manual insertion,
similar-paper lookup, and deletion of papers.

All handlers are wired directly to the canonical
:class:`database.connection.DatabaseConnection` paper CRUD contract
(contract #3):

* ``list_papers(project_id=None, query=None, limit=100, offset=0) -> list[dict]``
* ``get_paper(pid) -> dict | None``
* ``add_paper(data: dict) -> int``
* ``delete_paper(pid) -> bool``
* ``search_papers(q, limit=50) -> list[dict]``
* ``find_similar_papers(pid, limit=10) -> list[dict]``
* ``get_papers_by_ids(ids) -> list[dict]``

Bad input yields 400, unknown ids yield 404, and a missing database
layer yields 503.
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

from web.routes._common import (
    MAX_PAPER_SCAN,
    as_int,
    bad_request,
    error_response,
    json_safe,
    not_found,
    serialize_papers,
    service_unavailable,
)

logger = logging.getLogger(__name__)

papers_bp = Blueprint("papers", __name__, url_prefix="/api/papers")

# Pagination contract: ``limit``/``offset`` query params with a hard
# page-size cap (audit 4-g mandate #2). ``page``/``per_page`` remain
# accepted as legacy aliases mapped onto the same window.
MAX_PAGE_LIMIT = 500
DEFAULT_PAGE_LIMIT = 100


def _state() -> "Any":
    """Return the shared :class:`ServerState` singleton."""
    from web.server import ServerState

    return ServerState()


def _db():
    """Return the shared database connection (or ``None``)."""
    return _state().db


@papers_bp.route("/", methods=["GET"])
def list_papers():
    """List papers with limit/offset pagination and optional filters.

    Query params:
        limit:      Page size (default 100, capped at 500).
        offset:     0-indexed row offset (default 0).
        page:       Legacy alias — 1-indexed page (overrides ``offset``).
        per_page:   Legacy alias — page size (overrides ``limit``).
        source:     Filter by data source (e.g. ``arxiv``) — applied
                    post-fetch (the DB contract has no source column).
        year:       Filter by publication year — applied post-fetch.
        q:          Free-text filter forwarded to
                    ``DatabaseConnection.list_papers(query=...)``.
        project_id: Restrict to papers attached to a project.
    """
    try:
        limit = as_int(request.args.get("limit"), DEFAULT_PAGE_LIMIT,
                       name="limit", minimum=1, maximum=MAX_PAGE_LIMIT)
        offset = as_int(request.args.get("offset"), 0, name="offset",
                        minimum=0)
        legacy_page = request.args.get("page")
        legacy_per_page = request.args.get("per_page")
        if legacy_per_page is not None:
            limit = as_int(legacy_per_page, name="per_page",
                           minimum=1, maximum=MAX_PAGE_LIMIT)
        if legacy_page is not None:
            page = as_int(legacy_page, name="page", minimum=1)
            offset = (page - 1) * limit
        year = (as_int(request.args.get("year"), None, name="year")
                if request.args.get("year") is not None else None)
        project_id = (as_int(request.args.get("project_id"), None,
                             name="project_id")
                      if request.args.get("project_id") is not None else None)
    except ValueError as exc:
        return bad_request(str(exc))

    source = request.args.get("source") or None
    q = request.args.get("q") or None

    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    try:
        # Contract: list_papers(project_id=None, query=None, limit=100,
        #                       offset=0) -> list[dict]
        # Source/year are filtered post-fetch (the contract has no such
        # columns), so those requests scan the bounded maximum.
        scan_limit = (MAX_PAPER_SCAN if (source or year)
                      else min(MAX_PAPER_SCAN, offset + limit))
        records = db.list_papers(
            project_id=project_id, query=q, limit=scan_limit, offset=0,
        ) or []
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "list_papers", exc)

    # Post-fetch filters for params the DB contract does not expose.
    if source is not None:
        records = [p for p in records
                   if str(p.get("source", "")).lower() == source.lower()]
    if year is not None:
        records = [p for p in records
                   if _paper_year(p) == year]

    total = len(records)
    page_items = records[offset:offset + limit]
    page = (offset // limit) + 1 if limit else 1

    return jsonify({
        "papers": serialize_papers(page_items),
        "limit": limit,
        "offset": offset,
        "page": page,
        "per_page": limit,
        "total": total,
        "pages": (total + limit - 1) // limit if limit else 0,
    })


def _paper_year(paper: dict[str, Any]) -> int | None:
    """Extract a comparable publication year from a paper dict."""
    raw = paper.get("year")
    try:
        return int(str(raw)[:4])
    except (TypeError, ValueError):
        return None


@papers_bp.route("/<int:paper_id>", methods=["GET"])
def get_paper(paper_id: int):
    """Return the full record for a single paper (404 when missing)."""
    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    try:
        paper = db.get_paper(paper_id)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "get_paper", exc)

    if paper is None:
        return not_found(f"paper {paper_id} not found")
    return jsonify(json_safe(paper))


@papers_bp.route("/", methods=["POST"])
def add_paper():
    """Add a paper manually.

    Expects a JSON object whose keys mirror the paper schema
    (``title`` is required; optional ``authors``, ``year``, ``doi``,
    ``abstract``, ``journal``, ``source``, ...). Returns the created
    paper with its assigned ``id`` (201).
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return bad_request("request body must be a JSON object")
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return bad_request("title (non-empty string) is required")

    authors = payload.get("authors")
    if authors is not None and not isinstance(authors, list):
        return bad_request("authors must be a list")
    if payload.get("year") is not None:
        try:
            payload["year"] = as_int(payload.get("year"), name="year")
        except ValueError as exc:
            return bad_request(str(exc))

    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    payload.setdefault("source", "manual")
    payload.setdefault("external_id", str(uuid.uuid4()))
    payload = json_safe(payload)  # strip dates/decimals the ORM may reject

    try:
        # Contract: add_paper(data: dict) -> int
        paper_id = db.add_paper(payload)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "add_paper", exc)

    body = dict(payload)
    body["id"] = paper_id
    return jsonify(json_safe(body)), 201


@papers_bp.route("/<int:paper_id>", methods=["DELETE"])
def delete_paper(paper_id: int):
    """Delete a paper by id (404 when it does not exist)."""
    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    try:
        deleted = db.delete_paper(paper_id)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "delete_paper", exc)

    if not deleted:
        return not_found(f"paper {paper_id} not found")
    return jsonify({"deleted": True, "id": paper_id})


@papers_bp.route("/<int:paper_id>/similar", methods=["GET"])
def similar_papers(paper_id: int):
    """Find papers similar to the given one via embeddings.

    Query params:
        limit: Maximum number of neighbours (default 10, max 50).
    """
    try:
        limit = as_int(request.args.get("limit"), 10, name="limit",
                       minimum=1, maximum=50)
    except ValueError as exc:
        return bad_request(str(exc))

    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    try:
        # Contract: find_similar_papers(pid, limit=10) -> list[dict]
        neighbours = db.find_similar_papers(paper_id, limit=limit) or []
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "similar_papers", exc)

    return jsonify({
        "paper_id": paper_id,
        "similar": serialize_papers(neighbours),
    })


@papers_bp.route("/search", methods=["GET"])
def search_papers():
    """Full-text search across stored papers.

    Query params:
        q:       Search query (required).
        sources: Comma-separated source filter (optional, post-fetch).
        limit:   Maximum results (default 25, capped at 100).
    """
    q = request.args.get("q", "").strip()
    if not q:
        return bad_request("q parameter is required")

    try:
        limit = as_int(request.args.get("limit"), 25, name="limit",
                       minimum=1, maximum=100)
    except ValueError as exc:
        return bad_request(str(exc))

    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    sources_raw = request.args.get("sources", "")
    sources = [s.strip() for s in sources_raw.split(",") if s.strip()] or None

    try:
        # Contract: search_papers(q, limit=50) -> list[dict]
        results = db.search_papers(q, limit=limit) or []
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "search_papers", exc)

    if sources:
        wanted = {s.lower() for s in sources}
        results = [p for p in results
                   if str(p.get("source", "")).lower() in wanted]

    return jsonify({
        "query": q,
        "sources": sources,
        "count": len(results),
        "results": serialize_papers(results),
    })
