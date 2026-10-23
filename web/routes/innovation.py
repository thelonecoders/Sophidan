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

from web.routes._common import as_int, error_response, json_safe

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


def _serialise_one(it: Any) -> Any:
    """Serialise a single dataclass-like object to a JSON value."""
    if hasattr(it, "to_dict"):
        return json_safe(it.to_dict())
    if isinstance(it, dict):
        return json_safe(dict(it))
    if hasattr(it, "__dict__"):
        return json_safe({k: v for k, v in vars(it).items()
                          if not k.startswith("_")})
    return str(it)


def _serialise(items: list) -> list:
    """Serialise a list of results to JSON-friendly dicts.

    ``(paper, score)`` tuples (the shape returned by novelty ranking and
    paper recommendation) are serialised as
    ``{"paper": paper.to_dict(), "score": float}``; a two-tuple whose
    first element is not paper-like degrades to ``{"name": ..., "score"}`
    (e.g. collaboration recommendations return ``(author, score)``).
    """
    out = []
    for it in (items or []):
        if isinstance(it, tuple) and len(it) == 2 and \
                isinstance(it[1], (int, float)) and \
                not isinstance(it, str):
            first, second = it
            entry: dict[str, Any] = {"score": float(second)}
            if hasattr(first, "to_dict") or isinstance(first, dict) or \
                    hasattr(first, "__dict__"):
                entry["paper"] = _serialise_one(first)
            else:
                entry["name"] = str(first)
            out.append(entry)
        else:
            out.append(_serialise_one(it))
    return out


@innovation_bp.route("/bursts", methods=["POST"])
def bursts():
    """Detect citation bursts in the supplied corpus.

    Body: ``{"papers": [...], "time_window": int?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    try:
        time_window = as_int(payload.get("time_window"), 1,
                             name="time_window", minimum=1)
    except ValueError as exc:
        return _bad_request(str(exc))
    try:
        from innovation.citation_bursts import CitationBurstDetector
        det = CitationBurstDetector()
        result = det.detect_papers(papers, time_window=time_window)
        return jsonify({"bursts": _serialise(result)})
    except Exception as exc:
        return error_response(logger, "/api/innovation/bursts failed", exc,
                              status=502, error="analysis_failed")


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
        return error_response(logger, "/api/innovation/frontiers failed", exc,
                              status=502, error="analysis_failed")


@innovation_bp.route("/forecast", methods=["POST"])
def forecast():
    """Forecast future trends for a topic.

    Body: ``{"papers": [...], "topic": str, "years_ahead": int?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    topic = payload.get("topic")
    try:
        years_ahead = as_int(payload.get("years_ahead"), 3,
                             name="years_ahead", minimum=1, maximum=20)
    except ValueError as exc:
        return _bad_request(str(exc))
    if not topic:
        return _bad_request("topic is required")
    try:
        from innovation.trend_forecasting import TrendForecaster
        tf = TrendForecaster(papers)
        result = tf.forecast_topic(topic, years_ahead=years_ahead)
        return jsonify({"forecast": result.to_dict() if hasattr(result, "to_dict") else _serialise([result])[0]})
    except Exception as exc:
        return error_response(logger, "/api/innovation/forecast failed", exc,
                              status=502, error="analysis_failed")


@innovation_bp.route("/recommend-papers", methods=["POST"])
def recommend_papers():
    """Recommend papers for a query or for a user-history.

    Body: ``{"papers": [...], "query": str?, "top_k": int?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    query = payload.get("query", "")
    try:
        top_k = as_int(payload.get("top_k"), 10, name="top_k",
                       minimum=1, maximum=500)
    except ValueError as exc:
        return _bad_request(str(exc))
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
        return error_response(logger, "/api/innovation/recommend-papers failed", exc,
                              status=502, error="analysis_failed")


@innovation_bp.route("/recommend-collaborators", methods=["POST"])
def recommend_collaborators():
    """Recommend collaborators for a given author.

    Body: ``{"papers": [...], "author": str, "top_k": int?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    author = payload.get("author")
    try:
        top_k = as_int(payload.get("top_k"), 10, name="top_k",
                       minimum=1, maximum=500)
    except ValueError as exc:
        return _bad_request(str(exc))
    if not author:
        return _bad_request("author is required")
    try:
        from innovation.collaboration_recommendation import CollaborationRecommender
        rec = CollaborationRecommender(papers)
        result = rec.recommend_collaborators(author, top_k=top_k)
        return jsonify({"recommendations": _serialise(result)})
    except Exception as exc:
        return error_response(logger, "/api/innovation/recommend-collaborators failed", exc,
                              status=502, error="analysis_failed")


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
        return error_response(logger, "/api/innovation/novelty failed", exc,
                              status=502, error="analysis_failed")


@innovation_bp.route("/directions", methods=["POST"])
def directions():
    """Recommend research directions for a given topic.

    Body: ``{"papers": [...], "topic": str, "count": int?}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    topic = payload.get("topic", "")
    try:
        count = as_int(payload.get("count"), 5, name="count",
                       minimum=1, maximum=100)
    except ValueError as exc:
        return _bad_request(str(exc))
    try:
        from innovation.research_directions import ResearchDirectionRecommender
        rec = ResearchDirectionRecommender(papers)
        result = rec.recommend_directions(topic=topic, count=count)
        return jsonify({"directions": _serialise(result)})
    except Exception as exc:
        return error_response(logger, "/api/innovation/directions failed", exc,
                              status=502, error="analysis_failed")
