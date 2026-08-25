"""REST endpoints for the ``/api/bibliometrics`` resource.

Wraps the v2.0.0 :mod:`bibliometrics` package (Publish-or-Perish indices,
JCR-style journal metrics, VOSviewer network analyses, CiteSpace burst
detection) and exposes them via HTTP. All heavy deps and sibling modules
are lazy-imported inside the request handlers so the blueprint registers
even when ``bibliometrics`` itself has not been wired up yet.
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

bibliometrics_bp = Blueprint("bibliometrics", __name__, url_prefix="/api/bibliometrics")


def _service_unavailable(name: str):
    """Helper: build a 503 JSON response for a missing backend service."""
    return jsonify({
        "error": "service_unavailable",
        "message": f"{name} is not initialised; backend module not yet wired up.",
    }), 503


def _coerce_papers(payload: Any) -> list:
    """Convert the request payload's ``papers`` field into a list of dicts.

    Accepts either a list of dicts (already JSON-friendly) or a list of
    Paper-like dicts produced by the canonical ``Paper.to_dict`` path.
    """
    if not isinstance(payload, dict):
        return []
    papers = payload.get("papers") or []
    out = []
    for p in papers:
        if isinstance(p, dict):
            out.append(p)
        elif hasattr(p, "to_dict"):
            out.append(p.to_dict())
        elif hasattr(p, "__dict__"):
            out.append({k: v for k, v in vars(p).items() if not k.startswith("_")})
    return out


@bibliometrics_bp.route("/indices", methods=["POST"])
def indices():
    """Compute all Publish-or-Perish indices from citation + year vectors.

    Body: ``{"citations": [int, ...], "years": [int, ...]?}``.

    Returns:
        ``{"indices": {...}}`` — the dict produced by
        :meth:`bibliometrics.pop_indices.PoPIndices.compute_all`.
    """
    payload = request.get_json(silent=True) or {}
    citations = payload.get("citations") or []
    years = payload.get("years")
    try:
        citations = [int(c) for c in citations]
    except (TypeError, ValueError):
        return jsonify({"error": "bad_request",
                        "message": "citations must be a list of ints"}), 400
    if years is not None:
        try:
            years = [int(y) for y in years] or None
        except (TypeError, ValueError):
            return jsonify({"error": "bad_request",
                            "message": "years must be a list of ints"}), 400
    try:
        from bibliometrics.pop_indices import PoPIndices
        result = PoPIndices().compute_all(citations, years=years)
        return jsonify({"indices": result})
    except Exception as exc:
        logger.exception("/api/bibliometrics/indices failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@bibliometrics_bp.route("/journal-metrics", methods=["POST"])
def journal_metrics():
    """Compute all 13 JCR-style metrics for a single journal.

    Body: ``{"papers": [...], "journal": str, "year": int?}``.

    Returns:
        ``{"metrics": {...}}`` — the dict produced by
        :meth:`bibliometrics.journal_metrics.JournalMetrics.compute_journal_metrics`.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    journal = payload.get("journal")
    if not journal:
        return jsonify({"error": "bad_request",
                        "message": "journal (str) is required"}), 400
    year = payload.get("year")
    try:
        from bibliometrics.journal_metrics import JournalMetrics
        result = JournalMetrics().compute_journal_metrics(papers, journal, year=year)
        return jsonify({"metrics": result})
    except Exception as exc:
        logger.exception("/api/bibliometrics/journal-metrics failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@bibliometrics_bp.route("/vos", methods=["POST"])
def vos():
    """Build a VOSviewer-style network from the supplied papers.

    Body: ``{"papers": [...], "analysis_type": str}`` where ``analysis_type``
    is one of ``"bibliographic_coupling"``, ``"co_citation"``,
    ``"co_authorship"``, ``"term_co_occurrence"``.

    Returns:
        ``{"graph": {"nodes": [...], "edges": [...]}}`` — a node-link dict
        ready for any D3/Cytoscape client.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    atype = (payload.get("analysis_type") or "bibliographic_coupling").strip()
    try:
        from bibliometrics.vosviewer import VOSAnalyzer
        analyzer = VOSAnalyzer()
        dispatch = {
            "bibliographic_coupling": analyzer.bibliographic_coupling,
            "co_citation":            analyzer.co_citation_analysis,
            "co_authorship":          analyzer.co_authorship_analysis,
            "term_co_occurrence":     analyzer.term_co_occurrence,
        }
        if atype not in dispatch:
            return jsonify({"error": "bad_request",
                            "message": f"analysis_type must be one of {list(dispatch)!r}"}), 400
        graph = dispatch[atype](papers)
        # Convert networkx.Graph to a node-link dict.
        try:
            from networkx.readwrite import json_graph
            data = json_graph.node_link_data(graph)
        except Exception:
            data = {
                "nodes": [{"id": str(n)} for n in graph.nodes()],
                "edges": [{"source": str(u), "target": str(v)} for u, v in graph.edges()],
            }
        return jsonify({"graph": data})
    except Exception as exc:
        logger.exception("/api/bibliometrics/vos failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@bibliometrics_bp.route("/bursts", methods=["POST"])
def bursts():
    """Run CiteSpace-style citation-burst detection over the corpus.

    Body: ``{"papers": [...], "time_window": int?}``.

    Returns:
        ``{"bursts": [...]}`` — list of burst dicts (each as produced by
        :meth:`bibliometrics.citespace.Burst.to_dict`).
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    time_window = int(payload.get("time_window", 1) or 1)
    try:
        from bibliometrics.citespace import CiteSpaceAnalyzer
        analyzer = CiteSpaceAnalyzer()
        bursts = analyzer.detect_citation_bursts(papers, time_window=time_window)
        return jsonify({"bursts": [b.to_dict() if hasattr(b, "to_dict") else dict(b) for b in bursts]})
    except Exception as exc:
        logger.exception("/api/bibliometrics/bursts failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@bibliometrics_bp.route("/author-profile/<author_id>", methods=["GET"])
def author_profile(author_id: str):
    """Return the full bibliometric profile for a single author.

    The endpoint currently expects the request body to carry the list of
    that author's papers (``{"papers": [...]}``) — when a database is
    available the lookup will be wired up to the canonical paper store.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    if not papers:
        return _service_unavailable("author paper corpus (POST papers in body)")
    try:
        from bibliometrics.pop_indices import AuthorProfile
        profile = AuthorProfile.from_papers(papers, name=author_id)
        return jsonify({"profile": profile.__dict__ if hasattr(profile, "__dict__") else str(profile)})
    except Exception as exc:
        logger.exception("/api/bibliometrics/author-profile failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@bibliometrics_bp.route("/journal-profile/<path:journal_name>", methods=["GET"])
def journal_profile(journal_name: str):
    """Return the full bibliometric profile for a single journal.

    The endpoint currently expects the request body to carry the list of
    that journal's papers (``{"papers": [...]}``).
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    if not papers:
        return _service_unavailable("journal paper corpus (POST papers in body)")
    try:
        from bibliometrics.journal_metrics import JournalProfile
        profile = JournalProfile.from_papers(papers, journal_name)
        return jsonify({"profile": profile.__dict__ if hasattr(profile, "__dict__") else str(profile)})
    except Exception as exc:
        logger.exception("/api/bibliometrics/journal-profile failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502
