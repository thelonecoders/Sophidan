"""REST endpoints for the ``/api/innovation`` resource.

Wraps the v2.0.0 :mod:`innovation` package: citation bursts, knowledge
frontier mapping, trend forecasting, paper/collaboration
recommendation, novelty scoring, and research-direction recommendation.
All heavy deps are lazy-imported inside the handlers.
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

innovation_bp = Blueprint("innovation", __name__, url_prefix="/api/innovation")


def _bad_request(msg: str):
    return jsonify({"error": "bad_request", "message": msg}), 400


def _coerce_papers(payload: Any) -> list:
    """Best-effort conversion of the payload's ``papers`` field into Paper objects.

    Accepts JSON dicts (from HTTP), :class:`Paper` instances, or any
    object exposing ``__dict__`` (e.g. dataclass). Returns a list of
    :class:`Paper` objects so that downstream innovation modules (which
    expect attribute access on ``year``, ``title``, ``citations_count``,
    ``references``, ``keywords``, ``fields_of_study``) work uniformly.
    """
    if not isinstance(payload, dict):
        return []
    raw_papers = payload.get("papers") or []
    # Lazy import to avoid a top-level dep cycle (web → data_acquisition).
    try:
        from data_acquisition.base_scraper import Paper
    except Exception:  # pragma: no cover - defensive
        Paper = None

    out: list = []
    for p in raw_papers:
        if isinstance(p, dict):
            if Paper is None:
                out.append(p)
                continue
            try:
                out.append(Paper(
                    title=str(p.get("title", "")),
                    authors=list(p.get("authors", []) or []),
                    abstract=str(p.get("abstract", "")),
                    year=p.get("year"),
                    doi=p.get("doi"),
                    url=p.get("url"),
                    source=str(p.get("source", "")),
                    citations_count=p.get("citations_count"),
                    references=list(p.get("references", []) or []),
                    keywords=list(p.get("keywords", []) or []),
                    pdf_url=p.get("pdf_url"),
                    issn=p.get("issn"),
                    isbn=p.get("isbn"),
                    publisher=p.get("publisher"),
                    journal=p.get("journal"),
                    volume=p.get("volume"),
                    issue=p.get("issue"),
                    pages=p.get("pages"),
                    language=p.get("language"),
                    paper_type=p.get("paper_type"),
                    fields_of_study=list(p.get("fields_of_study", []) or []),
                    raw=dict(p.get("raw", p) or {}),
                ))
            except Exception:
                # Fall back to the raw dict if construction fails.
                out.append(p)
        elif Paper is not None and isinstance(p, Paper):
            out.append(p)
        elif hasattr(p, "to_dict"):
            d = p.to_dict()
            out.append(p if Paper is None else _coerce_papers({"papers": [d]})[0])
        elif hasattr(p, "__dict__"):
            # Generic dataclass-like: copy public attributes into a Paper.
            if Paper is None:
                out.append(p)
                continue
            attrs = {k: v for k, v in vars(p).items() if not k.startswith("_")}
            try:
                out.append(Paper(**{k: attrs[k] for k in (
                    "title", "authors", "abstract", "year", "doi", "url",
                    "source", "citations_count", "references", "keywords",
                    "pdf_url", "issn", "isbn", "publisher", "journal",
                    "volume", "issue", "pages", "language", "paper_type",
                    "fields_of_study", "raw",
                ) if k in attrs}))
            except Exception:
                out.append(p)
        else:
            out.append(p)
    return out


def _serialise(items: list) -> list:
    """Serialise a list of dataclass-like objects to dicts."""
    out = []
    for it in (items or []):
        if hasattr(it, "to_dict"):
            out.append(it.to_dict())
        elif isinstance(it, dict):
            out.append(dict(it))
        elif hasattr(it, "__dict__"):
            out.append({k: v for k, v in vars(it).items() if not k.startswith("_")})
        else:
            out.append(str(it))
    return out


@innovation_bp.route("/bursts", methods=["POST"])
def bursts():
    """Detect citation bursts in the supplied corpus.

    Body: ``{"papers": [...], "time_window": int?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    time_window = int(payload.get("time_window", 1) or 1)
    try:
        from innovation.citation_bursts import CitationBurstDetector
        det = CitationBurstDetector()
        result = det.detect_papers(papers, time_window=time_window)
        return jsonify({"bursts": _serialise(result)})
    except Exception as exc:
        logger.exception("/api/innovation/bursts failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@innovation_bp.route("/frontiers", methods=["POST"])
def frontiers():
    """Map knowledge frontier regions in the supplied corpus.

    Body: ``{"papers": [...], "method": "embedding_density"|"topic_model_boundary"|"citation_velocity"?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    method = (payload.get("method") or "embedding_density").strip()
    try:
        from innovation.frontier_mapping import KnowledgeFrontier
        kf = KnowledgeFrontier(papers)
        result = kf.compute_frontier(method=method)
        return jsonify({"frontiers": _serialise(result)})
    except Exception as exc:
        logger.exception("/api/innovation/frontiers failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@innovation_bp.route("/forecast", methods=["POST"])
def forecast():
    """Forecast future trends for a topic.

    Body: ``{"papers": [...], "topic": str, "years_ahead": int?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    topic = payload.get("topic")
    years_ahead = int(payload.get("years_ahead", 3) or 3)
    if not topic:
        return _bad_request("topic is required")
    try:
        from innovation.trend_forecasting import TrendForecaster
        tf = TrendForecaster(papers)
        result = tf.forecast_topic(topic, years_ahead=years_ahead)
        return jsonify({"forecast": result.to_dict() if hasattr(result, "to_dict") else _serialise([result])[0]})
    except Exception as exc:
        logger.exception("/api/innovation/forecast failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@innovation_bp.route("/recommend-papers", methods=["POST"])
def recommend_papers():
    """Recommend papers for a query or for a user-history.

    Body: ``{"papers": [...], "query": str?, "top_k": int?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    query = payload.get("query", "")
    top_k = int(payload.get("top_k", 10) or 10)
    try:
        from innovation.paper_recommendation import PaperRecommender
        rec = PaperRecommender(papers)
        rec.index_papers()
        if query:
            result = rec.recommend_for_query(query, top_k=top_k)
        else:
            result = rec.recommend_trending(top_k=top_k)
        return jsonify({"recommendations": _serialise(result)})
    except Exception as exc:
        logger.exception("/api/innovation/recommend-papers failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@innovation_bp.route("/recommend-collaborators", methods=["POST"])
def recommend_collaborators():
    """Recommend collaborators for a given author.

    Body: ``{"papers": [...], "author": str, "top_k": int?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    author = payload.get("author")
    top_k = int(payload.get("top_k", 10) or 10)
    if not author:
        return _bad_request("author is required")
    try:
        from innovation.collaboration_recommendation import CollaborationRecommender
        rec = CollaborationRecommender(papers)
        result = rec.recommend_collaborators(author, top_k=top_k)
        return jsonify({"recommendations": _serialise(result)})
    except Exception as exc:
        logger.exception("/api/innovation/recommend-collaborators failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@innovation_bp.route("/novelty", methods=["POST"])
def novelty():
    """Compute novelty scores for every paper in the corpus.

    Body: ``{"papers": [...]}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    try:
        from innovation.novelty_scoring import NoveltyScorer
        scorer = NoveltyScorer(papers)
        result = scorer.rank_novel_papers(top_n=len(papers))
        return jsonify({"novelty_scores": _serialise(result)})
    except Exception as exc:
        logger.exception("/api/innovation/novelty failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@innovation_bp.route("/directions", methods=["POST"])
def directions():
    """Recommend research directions for a given topic.

    Body: ``{"papers": [...], "topic": str, "count": int?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    topic = payload.get("topic", "")
    count = int(payload.get("count", 5) or 5)
    try:
        from innovation.research_directions import ResearchDirectionRecommender
        rec = ResearchDirectionRecommender(papers)
        result = rec.recommend_directions(topic=topic, count=count)
        return jsonify({"directions": _serialise(result)})
    except Exception as exc:
        logger.exception("/api/innovation/directions failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502
