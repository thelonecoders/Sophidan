"""REST endpoints for the ``/api/analytics`` resource.

Wraps the :mod:`data_science` and :mod:`knowledge_graph` modules to
expose topic modeling, clustering, temporal analysis, network
extraction, and bibliometric summaries via HTTP.

Analytics contract (contract #7):

* Papers are fetched through the DatabaseConnection contract:
  ``db.list_papers(project_id=..., limit=..., offset=0)``.
* ``TopicModeler(method=m).analyze(papers, **kw) -> dict``
* ``Clusterer(method=m).analyze(papers, **kw) -> dict``
* ``TemporalAnalyzer(papers).analyze(**kw) -> dict``
* ``Bibliometrics(papers).summary() -> dict``
* Graphs: ``CitationGraph().build(papers)`` (and the collaboration /
  temporal equivalents), serialised via
  ``networkx_pro.graph_io.GraphIO.to_cytoscape(g)``.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from web.routes._common import (
    MAX_PAPER_SCAN,
    as_int,
    bad_request,
    error_response,
    json_safe,
    service_unavailable,
)

logger = logging.getLogger(__name__)

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")

# Upper bound on the corpus an analysis will pull per request.
_MAX_CORPUS = min(MAX_PAPER_SCAN, 5000)


def _state() -> "Any":
    """Return the shared :class:`ServerState` singleton."""
    from web.server import ServerState

    return ServerState()


def _db() -> Any:
    """Return the shared database connection (or ``None``)."""
    return _state().db


def _fetch_papers(project_id: int) -> list[dict[str, Any]]:
    """Fetch a project's papers through the DB contract."""
    db = _db()
    if db is None:
        return []
    return db.list_papers(project_id=project_id,
                          limit=_MAX_CORPUS, offset=0) or []


@analytics_bp.route("/topic-model", methods=["POST"])
def topic_model():
    """Run topic modeling on a project's papers.

    Body: ``{"project_id": int, "num_topics": int?, "method": str?}``.

    Returns:
        ``{"result": {...}}`` — the dict produced by
        ``TopicModeler(method).analyze(papers, num_topics=...)``.
    """
    payload = request.get_json(silent=True) or {}
    try:
        project_id = as_int(payload.get("project_id"), name="project_id")
        num_topics = as_int(payload.get("num_topics"), 8, name="num_topics",
                            minimum=2, maximum=100)
    except ValueError as exc:
        return bad_request(str(exc))
    method = payload.get("method", "nmf")

    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    papers = _fetch_papers(project_id)
    if not papers:
        return bad_request(f"project {project_id} has no papers to analyze")

    try:
        from data_science.topic_modeler import TopicModeler

        result = TopicModeler(method=method).analyze(
            papers, num_topics=num_topics)
    except ValueError as exc:  # invalid method / parameters
        logger.warning("topic-model rejected: %s", exc)
        return bad_request("invalid method or parameters")
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "topic_model", exc, status=502,
                              error="analysis_failed")

    return jsonify({
        "project_id": project_id,
        "method": method,
        "num_topics": num_topics,
        "papers_analyzed": len(papers),
        "result": json_safe(result),
    })


@analytics_bp.route("/cluster", methods=["POST"])
def cluster():
    """Cluster a project's papers.

    Body: ``{"project_id": int, "method": str?, "n_clusters": int?}``.

    Returns:
        ``{"result": {...}}`` — the dict produced by
        ``Clusterer(method).analyze(papers, n_clusters=...)``.
    """
    payload = request.get_json(silent=True) or {}
    try:
        project_id = as_int(payload.get("project_id"), name="project_id")
        n_clusters = as_int(payload.get("n_clusters"), 5,
                            name="n_clusters", minimum=2, maximum=100)
    except ValueError as exc:
        return bad_request(str(exc))
    method = payload.get("method", "kmeans")

    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    papers = _fetch_papers(project_id)
    if not papers:
        return bad_request(f"project {project_id} has no papers to analyze")

    try:
        from data_science.clustering import Clusterer

        result = Clusterer(method=method).analyze(
            papers, n_clusters=n_clusters)
    except ValueError as exc:
        logger.warning("cluster rejected: %s", exc)
        return bad_request("invalid method or parameters")
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "cluster", exc, status=502,
                              error="analysis_failed")

    return jsonify({
        "project_id": project_id,
        "method": method,
        "n_clusters": n_clusters,
        "papers_analyzed": len(papers),
        "result": json_safe(result),
    })


@analytics_bp.route("/temporal", methods=["POST"])
def temporal():
    """Compute a temporal time series for a project.

    Body: ``{"project_id": int, "metric": str?}``. ``metric`` is one of
    ``publications`` (default), ``citations``, ``authors``.

    Returns:
        ``{"result": {...}}`` — the dict produced by
        ``TemporalAnalyzer(papers).analyze(metric=...)``.
    """
    payload = request.get_json(silent=True) or {}
    try:
        project_id = as_int(payload.get("project_id"), name="project_id")
    except ValueError as exc:
        return bad_request(str(exc))
    metric = payload.get("metric", "publications")

    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    papers = _fetch_papers(project_id)
    if not papers:
        return bad_request(f"project {project_id} has no papers to analyze")

    try:
        from data_science.temporal_analysis import TemporalAnalyzer

        result = TemporalAnalyzer(papers).analyze(metric=metric)
    except ValueError as exc:
        logger.warning("temporal rejected: %s", exc)
        return bad_request("invalid metric or parameters")
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "temporal", exc, status=502,
                              error="analysis_failed")

    return jsonify({
        "project_id": project_id,
        "metric": metric,
        "papers_analyzed": len(papers),
        "result": json_safe(result),
    })


@analytics_bp.route("/network/<int:project_id>", methods=["GET"])
def network(project_id: int):
    """Return a cytoscape-formatted network for a project.

    Query param ``type`` selects one of:
        ``citation``      — citation graph (default).
        ``collaboration`` — co-authorship graph.
        ``temporal``      — temporal evolution graph.

    Graphs are built from the project's papers
    (``<GraphClass>().build(papers)``) and serialised through
    ``GraphIO.to_cytoscape`` (which sanitises None/list attributes).
    """
    net_type = request.args.get("type", "citation")
    if net_type not in {"citation", "collaboration", "temporal"}:
        return bad_request("type must be citation|collaboration|temporal")

    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    papers = _fetch_papers(project_id)

    try:
        from networkx_pro.graph_io import GraphIO

        if net_type == "citation":
            from knowledge_graph.citation_graph import CitationGraph

            graph = CitationGraph().build(papers)
        elif net_type == "collaboration":
            from knowledge_graph.collaboration_graph import CollaborationGraph

            graph = CollaborationGraph().build(papers)
        else:
            from knowledge_graph.temporal_network import TemporalNetwork

            graph = TemporalNetwork().build(papers)
        data = GraphIO.to_cytoscape(graph)
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "network", exc, status=502,
                              error="analysis_failed")

    return jsonify({
        "project_id": project_id,
        "type": net_type,
        "papers": len(papers),
        "network": json_safe(data),
    })


@analytics_bp.route("/stats/<int:project_id>", methods=["GET"])
def stats(project_id: int):
    """Return a bibliometric summary for a project.

    Includes paper count, year range, total citations, h-index,
    top authors, top venues, and source breakdown — the dict produced
    by ``Bibliometrics(papers).summary()``.
    """
    db = _db()
    if db is None:
        return service_unavailable("DatabaseConnection")

    papers = _fetch_papers(project_id)

    try:
        from data_science.statistics import Bibliometrics

        summary = Bibliometrics(papers).summary()
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "stats", exc, status=502,
                              error="analysis_failed")

    return jsonify({
        "project_id": project_id,
        "papers": len(papers),
        "stats": json_safe(summary),
    })
