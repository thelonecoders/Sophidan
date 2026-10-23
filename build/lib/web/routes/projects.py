"""REST endpoints for the ``/api/projects`` resource.

Provides CRUD for projects plus sub-resources for papers, snapshots,
and side-by-side comparison of two projects.

Every handler calls the real :class:`ProjectManager` API directly
(no ``hasattr`` guards faking success — a missing manager yields a
503 and a failed call yields a generic 500, never ``str(exc)``).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from web.routes._common import as_int, error_response, json_safe

logger = logging.getLogger(__name__)

projects_bp = Blueprint("projects", __name__, url_prefix="/api/projects")


def _state() -> "Any":
    """Return the shared :class:`ServerState` singleton."""
    from web.server import ServerState

    return ServerState()


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
    return json_safe(data)


@projects_bp.route("/", methods=["GET"])
def list_projects():
    """List all projects (optionally filtered by ``?q=``)."""
    state = _state()
    pm = state.project_manager
    if pm is None:
        return error_response(logger, "ProjectManager unavailable",
                              RuntimeError("ProjectManager not initialised"),
                              status=503, error="service_unavailable")

    q = request.args.get("q")
    try:
        # Contract: list_projects(query=None) -> list[Project]
        projects = pm.list_projects(query=q) or []
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "list_projects", exc)

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
        return error_response(logger, "ProjectManager unavailable",
                              RuntimeError("ProjectManager not initialised"),
                              status=503, error="service_unavailable")

    payload = request.get_json(silent=True) or {}
    if not payload.get("name"):
        return jsonify({"error": "bad_request",
                        "message": "name is required"}), 400

    try:
        # Contract: create_project(name, description="", color=..., settings=None)
        project = pm.create_project(
            name=payload["name"],
            description=payload.get("description", ""),
            color=payload.get("color", "#3B82F6"),
            settings=payload.get("settings"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "create_project", exc)

    return jsonify(_serialize(project)), 201


@projects_bp.route("/<int:project_id>", methods=["GET"])
def get_project(project_id: int):
    """Return the full project record."""
    state = _state()
    pm = state.project_manager
    if pm is None:
        return error_response(logger, "ProjectManager unavailable",
                              RuntimeError("ProjectManager not initialised"),
                              status=503, error="service_unavailable")

    try:
        # Contract: get_project(project_id) -> Project
        project = pm.get_project(project_id)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "get_project", exc)

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
        return error_response(logger, "ProjectManager unavailable",
                              RuntimeError("ProjectManager not initialised"),
                              status=503, error="service_unavailable")

    payload = request.get_json(silent=True) or {}
    try:
        # Contract: update_project(project_id, payload) -> Project | None
        project = pm.update_project(project_id, payload)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "update_project", exc)

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
        return error_response(logger, "ProjectManager unavailable",
                              RuntimeError("ProjectManager not initialised"),
                              status=503, error="service_unavailable")

    try:
        # Contract: delete_project(project_id) -> bool
        deleted = pm.delete_project(project_id)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "delete_project", exc)

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
        return error_response(logger, "ProjectManager unavailable",
                              RuntimeError("ProjectManager not initialised"),
                              status=503, error="service_unavailable")

    payload = request.get_json(silent=True) or {}
    paper_ids = payload.get("paper_ids", [])
    if not isinstance(paper_ids, list) or not paper_ids:
        return jsonify({"error": "bad_request",
                        "message": "paper_ids (non-empty list) is required"}), 400
    try:
        paper_ids = [as_int(pid, name="paper_ids entry") for pid in paper_ids]
    except ValueError as exc:
        return jsonify({"error": "bad_request", "message": str(exc)}), 400

    try:
        # Contract: add_papers_to_project(project_id, paper_ids) -> int
        added = pm.add_papers_to_project(project_id, paper_ids)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "add_papers", exc)

    return jsonify({"project_id": project_id, "added": added,
                    "paper_ids": paper_ids})


@projects_bp.route("/<int:project_id>/papers/<int:paper_id>", methods=["DELETE"])
def remove_paper(project_id: int, paper_id: int):
    """Detach a paper from a project."""
    state = _state()
    pm = state.project_manager
    if pm is None:
        return error_response(logger, "ProjectManager unavailable",
                              RuntimeError("ProjectManager not initialised"),
                              status=503, error="service_unavailable")

    try:
        # Contract: remove_paper_from_project(project_id, paper_id) -> bool
        removed = pm.remove_paper_from_project(project_id, paper_id)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "remove_paper", exc)

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
        return error_response(logger, "ProjectManager unavailable",
                              RuntimeError("ProjectManager not initialised"),
                              status=503, error="service_unavailable")

    try:
        # Contract: list_snapshots(project_id) -> list
        snaps = pm.list_snapshots(project_id) or []
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "list_snapshots", exc)

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
        return error_response(logger, "ProjectManager unavailable",
                              RuntimeError("ProjectManager not initialised"),
                              status=503, error="service_unavailable")

    payload = request.get_json(silent=True) or {}
    try:
        # Contract: create_snapshot(project_id, payload)
        snapshot = pm.create_snapshot(project_id, payload)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "create_snapshot", exc)

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
        return error_response(logger, "ProjectManager unavailable",
                              RuntimeError("ProjectManager not initialised"),
                              status=503, error="service_unavailable")

    payload = request.get_json(silent=True) or {}
    a_id = payload.get("a")
    b_id = payload.get("b")
    if not isinstance(a_id, int) or not isinstance(b_id, int):
        return jsonify({"error": "bad_request",
                        "message": "a and b (integers) are required"}), 400

    try:
        # Contract: compare_projects(a_id, b_id) -> ComparisonResult
        result = pm.compare_projects(a_id, b_id)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "compare_projects", exc)

    return jsonify(_serialize(result))
