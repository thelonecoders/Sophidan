"""REST endpoints for the ``/api/analytics`` resource.

Wraps the :mod:`data_science` and :mod:`knowledge_graph` modules to
expose topic modeling, clustering, temporal analysis, network
extraction, and bibliometric summaries via HTTP.
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

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


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


def _run_analysis(module_path: str, class_name: str, project_id: int,
                  method: str | None = None, **kwargs: Any):
    """Helper: lazily import an analysis class and invoke ``analyze``.

    Args:
        module_path: Dotted path to the analysis module.
        class_name:  Class to instantiate.
        project_id:  Project whose papers to analyze.
        method:      Optional method name (e.g. ``"lda"``, ``"kmeans"``).
        **kwargs:    Extra kwargs forwarded to ``analyze``.

    Returns:
        Tuple ``(result, error)`` — exactly one is non-None.
    """
    state = _state()
    db = state.db
    try:
        import importlib

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        analyzer = cls(db) if db is not None else cls()
        if hasattr(analyzer, "analyze"):
            if method is not None:
                return analyzer.analyze(project_id=project_id,
                                       method=method, **kwargs), None
            return analyzer.analyze(project_id=project_id, **kwargs), None
        return None, f"{class_name} has no analyze() method"
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("%s.%s failed: %s", module_path, class_name, exc)
        return None, str(exc)


@analytics_bp.route("/topic-model", methods=["POST"])
def topic_model():
    """Run topic modeling on a project's papers.

    Body: ``{"project_id": int, "num_topics": int?, "method": str?}``.

    Returns:
        ``{"topics": [{"id": int, "words": [(str, float)], "weight": float}]}``.
    """
    payload = request.get_json(silent=True) or {}
    project_id = payload.get("project_id")
    if not isinstance(project_id, int):
        return jsonify({"error": "bad_request",
                        "message": "project_id (int) is required"}), 400
    num_topics = int(payload.get("num_topics", 8))
    method = payload.get("method", "bertopic")

    result, err = _run_analysis(
        "data_science.topic_modeler", "TopicModeler",
        project_id=project_id, method=method, num_topics=num_topics,
    )
    if err is not None:
        return jsonify({"error": "analysis_failed", "message": err}), 502
    return jsonify({"project_id": project_id, "method": method,
                    "num_topics": num_topics, "topics": result})


@analytics_bp.route("/cluster", methods=["POST"])
def cluster():
    """Cluster a project's papers.

    Body: ``{"project_id": int, "method": str?, "n_clusters": int?}``.

    Returns:
        ``{"labels": {paper_id: int}, "silhouette": float?}``.
    """
    payload = request.get_json(silent=True) or {}
    project_id = payload.get("project_id")
    if not isinstance(project_id, int):
        return jsonify({"error": "bad_request",
                        "message": "project_id (int) is required"}), 400
    method = payload.get("method", "kmeans")
    n_clusters = int(payload.get("n_clusters", 5))

    result, err = _run_analysis(
        "data_science.clustering", "Clusterer",
        project_id=project_id, method=method, n_clusters=n_clusters,
    )
    if err is not None:
        return jsonify({"error": "analysis_failed", "message": err}), 502
    return jsonify({"project_id": project_id, "method": method,
                    "n_clusters": n_clusters, "labels": result})


@analytics_bp.route("/temporal", methods=["POST"])
def temporal():
    """Compute a temporal time series for a project.

    Body: ``{"project_id": int, "metric": str?}``. ``metric`` is one of
    ``publications`` (default), ``citations``, ``authors``.
    """
    payload = request.get_json(silent=True) or {}
    project_id = payload.get("project_id")
    if not isinstance(project_id, int):
        return jsonify({"error": "bad_request",
                        "message": "project_id (int) is required"}), 400
    metric = payload.get("metric", "publications")

    result, err = _run_analysis(
        "data_science.temporal_analysis", "TemporalAnalyzer",
        project_id=project_id, metric=metric,
    )
    if err is not None:
        return jsonify({"error": "analysis_failed", "message": err}), 502
    return jsonify({"project_id": project_id, "metric": metric,
                    "series": result})


@analytics_bp.route("/network/<int:project_id>", methods=["GET"])
def network(project_id: int):
    """Return a cytoscape-formatted network for a project.

    Query param ``type`` selects one of:
        ``citation``      — citation graph (default).
        ``collaboration`` — co-authorship graph.
        ``temporal``     — temporal evolution graph.
    """
    net_type = request.args.get("type", "citation")
    if net_type not in {"citation", "collaboration", "temporal"}:
        return jsonify({"error": "bad_request",
                        "message": "type must be citation|collaboration|temporal"}), 400

    state = _state()
    db = state.db
    if db is None:
        return _service_unavailable("DatabaseConnection")

    module_map = {
        "citation": ("knowledge_graph.citation_graph", "CitationGraph"),
        "collaboration": ("knowledge_graph.collaboration_graph",
                          "CollaborationGraph"),
        "temporal": ("knowledge_graph.temporal_network", "TemporalNetwork"),
    }
    module_path, class_name = module_map[net_type]

    try:
        import importlib

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        graph = cls(db) if db is not None else cls()
        if hasattr(graph, "to_cytoscape"):
            data = graph.to_cytoscape(project_id)
        elif hasattr(graph, "build"):
            data = graph.build(project_id)
        else:
            data = {"elements": {"nodes": [], "edges": []}}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("network failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502

    return jsonify({"project_id": project_id, "type": net_type,
                    "network": data})


@analytics_bp.route("/stats/<int:project_id>", methods=["GET"])
def stats(project_id: int):
    """Return a bibliometric summary for a project.

    Includes paper count, year range, total citations, h-index,
    top authors, top venues, and source breakdown.
    """
    state = _state()
    db = state.db
    if db is None:
        return _service_unavailable("DatabaseConnection")

    try:
        import importlib

        module = importlib.import_module("data_science.statistics")
        cls = getattr(module, "BibliometricStats")
        stats_engine = cls(db) if db is not None else cls()
        if hasattr(stats_engine, "summary"):
            summary = stats_engine.summary(project_id)
        else:
            summary = {}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("stats failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502

    return jsonify({"project_id": project_id, "stats": summary})
