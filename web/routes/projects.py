"""REST endpoints for the ``/api/projects`` resource.

Provides CRUD for projects plus sub-resources for papers, snapshots,
and side-by-side comparison of two projects.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

projects_bp = Blueprint("projects", __name__, url_prefix="/api/projects")


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


def _serialize(obj: Any) -> dict[str, Any]:
    """Best-effort serializer for projects / snapshots / comparison results."""
    if isinstance(obj, dict):
        data = dict(obj)
    elif hasattr(obj, "to_dict") and callable(obj.to_dict):
        data = obj.to_dict()
    elif hasattr(obj, "__dict__"):
        data = {k: v for k, v in vars(obj).items() if not k.startswith("_")}
    else:
        data = {"value": str(obj)}
    data.pop("_sa_instance_state", None)
    return data


@projects_bp.route("/", methods=["GET"])
def list_projects():
    """List all projects (optionally filtered by ``?q=``)."""
    state = _state()
    pm = state.project_manager
    if pm is None:
        return _service_unavailable("ProjectManager")

    q = request.args.get("q")
    try:
        if hasattr(pm, "list_projects"):
            projects = pm.list_projects(query=q) or []
        else:
            projects = []
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("list_projects failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify({"projects": [_serialize(p) for p in projects],
                    "count": len(projects)})


@projects_bp.route("/", methods=["POST"])
def create_project():
    """Create a new project.

    Body: ``{"name": str, "description": str?, "settings": dict?,
             "color": str?}``.
    """
    state = _state()
    pm = state.project_manager
    if pm is None:
        return _service_unavailable("ProjectManager")

    payload = request.get_json(silent=True) or {}
    if not payload.get("name"):
        return jsonify({"error": "bad_request",
                        "message": "name is required"}), 400

    try:
        if hasattr(pm, "create_project"):
            project = pm.create_project(
                name=payload["name"],
                description=payload.get("description", ""),
                color=payload.get("color", "#3B82F6"),
                settings=payload.get("settings"),
            )
        else:
            project = {"id": 0, **payload}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("create_project failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify(_serialize(project)), 201


@projects_bp.route("/<int:project_id>", methods=["GET"])
def get_project(project_id: int):
    """Return the full project record."""
    state = _state()
    pm = state.project_manager
    if pm is None:
        return _service_unavailable("ProjectManager")

    try:
        if hasattr(pm, "get_project"):
            project = pm.get_project(project_id)
        else:
            project = None
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("get_project failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    if project is None:
        return jsonify({"error": "not_found",
                        "message": f"project {project_id} not found"}), 404
    return jsonify(_serialize(project))


@projects_bp.route("/<int:project_id>", methods=["PUT"])
def update_project(project_id: int):
    """Update project metadata. Body is a partial dict of fields to set."""
    state = _state()
    pm = state.project_manager
    if pm is None:
        return _service_unavailable("ProjectManager")

    payload = request.get_json(silent=True) or {}
    try:
        if hasattr(pm, "update_project"):
            project = pm.update_project(project_id, payload)
        else:
            project = {"id": project_id, **payload}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("update_project failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    if project is None:
        return jsonify({"error": "not_found",
                        "message": f"project {project_id} not found"}), 404
    return jsonify(_serialize(project))


@projects_bp.route("/<int:project_id>", methods=["DELETE"])
def delete_project(project_id: int):
    """Delete a project (does not delete its papers)."""
    state = _state()
    pm = state.project_manager
    if pm is None:
        return _service_unavailable("ProjectManager")

    try:
        if hasattr(pm, "delete_project"):
            deleted = pm.delete_project(project_id)
        else:
            deleted = False
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("delete_project failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    if not deleted:
        return jsonify({"error": "not_found",
                        "message": f"project {project_id} not found"}), 404
    return jsonify({"deleted": True, "id": project_id})


@projects_bp.route("/<int:project_id>/papers", methods=["POST"])
def add_papers(project_id: int):
    """Attach papers to a project.

    Body: ``{"paper_ids": [int, ...]}``.
    """
    state = _state()
    pm = state.project_manager
    if pm is None:
        return _service_unavailable("ProjectManager")

    payload = request.get_json(silent=True) or {}
    paper_ids = payload.get("paper_ids", [])
    if not isinstance(paper_ids, list) or not paper_ids:
        return jsonify({"error": "bad_request",
                        "message": "paper_ids (non-empty list) is required"}), 400

    try:
        if hasattr(pm, "add_papers_to_project"):
            added = pm.add_papers_to_project(project_id, paper_ids)
        else:
            added = 0
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("add_papers failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify({"project_id": project_id, "added": added,
                    "paper_ids": paper_ids})


@projects_bp.route("/<int:project_id>/papers/<int:paper_id>", methods=["DELETE"])
def remove_paper(project_id: int, paper_id: int):
    """Detach a paper from a project."""
    state = _state()
    pm = state.project_manager
    if pm is None:
        return _service_unavailable("ProjectManager")

    try:
        if hasattr(pm, "remove_paper_from_project"):
            removed = pm.remove_paper_from_project(project_id, paper_id)
        else:
            removed = False
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("remove_paper failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    if not removed:
        return jsonify({"error": "not_found",
                        "message": f"paper {paper_id} not in project {project_id}"}), 404
    return jsonify({"removed": True, "project_id": project_id,
                    "paper_id": paper_id})


@projects_bp.route("/<int:project_id>/snapshots", methods=["GET"])
def list_snapshots(project_id: int):
    """List all snapshots for a project."""
    state = _state()
    pm = state.project_manager
    if pm is None:
        return _service_unavailable("ProjectManager")

    try:
        if hasattr(pm, "list_snapshots"):
            snaps = pm.list_snapshots(project_id) or []
        else:
            snaps = []
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("list_snapshots failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify({"project_id": project_id,
                    "snapshots": [_serialize(s) for s in snaps],
                    "count": len(snaps)})


@projects_bp.route("/<int:project_id>/snapshots", methods=["POST"])
def create_snapshot(project_id: int):
    """Create a new snapshot of the project's current state.

    Body: ``{"label": str?, "description": str?}``.
    """
    state = _state()
    pm = state.project_manager
    if pm is None:
        return _service_unavailable("ProjectManager")

    payload = request.get_json(silent=True) or {}
    try:
        if hasattr(pm, "create_snapshot"):
            snapshot = pm.create_snapshot(project_id, payload)
        else:
            snapshot = {"project_id": project_id, **payload}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("create_snapshot failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify(_serialize(snapshot)), 201


@projects_bp.route("/compare", methods=["POST"])
def compare_projects():
    """Compare two projects side-by-side.

    Body: ``{"a": int, "b": int}``. Returns a :class:`ComparisonResult`
    dict including shared papers, unique papers, and bibliometric deltas.
    """
    state = _state()
    pm = state.project_manager
    if pm is None:
        return _service_unavailable("ProjectManager")

    payload = request.get_json(silent=True) or {}
    a_id = payload.get("a")
    b_id = payload.get("b")
    if not isinstance(a_id, int) or not isinstance(b_id, int):
        return jsonify({"error": "bad_request",
                        "message": "a and b (integers) are required"}), 400

    try:
        if hasattr(pm, "compare_projects"):
            result = pm.compare_projects(a_id, b_id)
        else:
            result = {
                "a": a_id, "b": b_id,
                "shared_papers": [], "unique_to_a": [], "unique_to_b": [],
                "metrics": {},
            }
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("compare_projects failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify(_serialize(result))
