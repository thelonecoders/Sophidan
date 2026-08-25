"""REST endpoints for the ``/api/sr`` (systematic review) resource.

Wraps the v2.0.0 :mod:`systematic_review` and :mod:`prisma` packages:
protocol CRUD, screening decisions, risk-of-bias assessments,
data-extraction forms, synthesis methods, and PRISMA flow-diagram
generation. All heavy deps are lazy-imported inside the handlers.
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

sr_bp = Blueprint("sr", __name__, url_prefix="/api/sr")


def _bad_request(msg: str):
    return jsonify({"error": "bad_request", "message": msg}), 400


# In-memory registries (single-process dev server only; the production
# path should persist to the canonical SQLite DB via the project_manager).
_PROTOCOLS: dict = {}
_SCREENING: dict = {}
_ROB: dict = {}
_EXTRACTIONS: dict = {}


# ----------------------------------------------------------------- Protocol
@sr_bp.route("/protocol", methods=["POST"])
def create_protocol():
    """Create a new systematic-review protocol from a template.

    Body: ``{"template": str}`` (defaults to ``"cochrane"``).

    Returns:
        ``{"id": str, "protocol": {...}}``.
    """
    payload = request.get_json(silent=True) or {}
    template = payload.get("template") or "cochrane"
    try:
        from systematic_review.protocol import SystematicReviewProtocol
        proto = SystematicReviewProtocol.from_template(template)
        pid = uuid.uuid4().hex
        _PROTOCOLS[pid] = proto
        return jsonify({"id": pid, "protocol": proto.to_dict() if hasattr(proto, "to_dict") else str(proto)})
    except Exception as exc:
        logger.exception("/api/sr/protocol (create) failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@sr_bp.route("/protocol/<protocol_id>", methods=["GET"])
def get_protocol(protocol_id: str):
    """Retrieve a stored protocol by id."""
    proto = _PROTOCOLS.get(protocol_id)
    if proto is None:
        return jsonify({"error": "not_found", "message": f"protocol {protocol_id} not found"}), 404
    return jsonify({"id": protocol_id, "protocol": proto.to_dict() if hasattr(proto, "to_dict") else str(proto)})


@sr_bp.route("/protocol/<protocol_id>", methods=["PUT"])
def update_protocol(protocol_id: str):
    """Update fields on a stored protocol.

    Body: a dict whose keys map onto :class:`SystematicReviewProtocol`
    attributes (``title``, ``research_question``, ``objectives``, ...).
    """
    payload = request.get_json(silent=True) or {}
    proto = _PROTOCOLS.get(protocol_id)
    if proto is None:
        return jsonify({"error": "not_found", "message": f"protocol {protocol_id} not found"}), 404
    try:
        for k, v in payload.items():
            if hasattr(proto, k):
                setattr(proto, k, v)
        return jsonify({"id": protocol_id, "protocol": proto.to_dict() if hasattr(proto, "to_dict") else str(proto)})
    except Exception as exc:
        logger.exception("/api/sr/protocol (update) failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


# ----------------------------------------------------------------- Screening
@sr_bp.route("/screening/import", methods=["POST"])
def screening_import():
    """Bulk-import papers as new screening records.

    Body: ``{"papers": [...]}``.

    Returns:
        ``{"imported": int, "record_ids": [...]}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = payload.get("papers") or []
    try:
        from systematic_review.screening import ScreeningManager
        mgr = ScreeningManager()
        n = mgr.load_from_search(papers)
        return jsonify({"imported": n, "record_ids": [r.record_id for r in mgr.records()]})
    except Exception as exc:
        logger.exception("/api/sr/screening/import failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@sr_bp.route("/screening/<record_id>/decide", methods=["POST"])
def screening_decide(record_id: str):
    """Record a screening decision for a single record.

    Body: ``{"decision": str, "reviewer": str, "reason": str?, "stage": str?}``.

    Returns:
        ``{"record_id": str, "decision": str}``.
    """
    payload = request.get_json(silent=True) or {}
    decision = payload.get("decision")
    reviewer = payload.get("reviewer", "anonymous")
    reason = payload.get("reason")
    stage = payload.get("stage", "title_abstract")
    if not decision:
        return _bad_request("decision is required")
    try:
        from systematic_review.screening import ScreeningManager, ScreeningStage
        mgr = ScreeningManager()
        if stage == "full_text":
            record = mgr.screen_full_text(record_id, decision=decision,
                                          reviewer=reviewer, reason=reason or "")
        else:
            stage_enum = ScreeningStage.from_value(stage) if stage else None
            record = mgr.screen_title_abstract(record_id, decision=decision,
                                                reviewer=reviewer, reason=reason or "")
        return jsonify({
            "record_id": record_id,
            "decision": decision,
            "record": record.to_dict() if hasattr(record, "to_dict") else str(record),
        })
    except Exception as exc:
        logger.exception("/api/sr/screening/<id>/decide failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@sr_bp.route("/screening/progress", methods=["GET"])
def screening_progress():
    """Return stage-count progress for the in-memory screening manager."""
    try:
        from systematic_review.screening import ScreeningManager
        mgr = ScreeningManager()
        progress = mgr.progress()
        return jsonify({"progress": progress})
    except Exception as exc:
        logger.exception("/api/sr/screening/progress failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


# ----------------------------------------------------------------- Risk of Bias
@sr_bp.route("/rob/<study_id>", methods=["POST"])
def rob_assess(study_id: str):
    """Run a risk-of-bias assessment for a single study.

    Body: ``{"tool": str, "assessment": {...}}`` where ``tool`` is one of
    ``"rob2"``, ``"robins_i"``, ``"quadas_2"``, ``"nos"``.
    """
    payload = request.get_json(silent=True) or {}
    tool_name = (payload.get("tool") or "rob2").strip().lower()
    assessment = payload.get("assessment") or {}
    try:
        from systematic_review.risk_of_bias import (
            CochraneRoB2, ROBINS_I, QUADAS2, NewcastleOttawaScale,
        )
        tool_map = {
            "rob2": CochraneRoB2,
            "robins_i": ROBINS_I,
            "robins-i": ROBINS_I,
            "quadas_2": QUADAS2,
            "quadas-2": QUADAS2,
            "quadas2": QUADAS2,
            "nos": NewcastleOttawaScale,
        }
        cls = tool_map.get(tool_name)
        if cls is None:
            return _bad_request(f"unknown tool: {tool_name}")
        result = cls().assess(assessment)
        _ROB[study_id] = result
        return jsonify({
            "study_id": study_id,
            "tool": tool_name,
            "result": result.to_dict() if hasattr(result, "to_dict") else str(result),
        })
    except Exception as exc:
        logger.exception("/api/sr/rob (POST) failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@sr_bp.route("/rob/<study_id>", methods=["GET"])
def rob_get(study_id: str):
    """Retrieve the stored risk-of-bias result for a study."""
    result = _ROB.get(study_id)
    if result is None:
        return jsonify({"error": "not_found",
                        "message": f"RoB result for {study_id} not found"}), 404
    return jsonify({
        "study_id": study_id,
        "result": result.to_dict() if hasattr(result, "to_dict") else str(result),
    })


# ----------------------------------------------------------------- Extraction
@sr_bp.route("/extraction/<study_id>", methods=["POST"])
def extraction(study_id: str):
    """Persist a per-study data-extraction form.

    Body: ``{"form_data": {...}, "template": str?}``.
    """
    payload = request.get_json(silent=True) or {}
    form_data = payload.get("form_data") or {}
    template = payload.get("template") or "cochrane"
    try:
        from systematic_review.data_extraction import (
            DataExtractionForm, DataExtractor,
        )
        form = DataExtractionForm.from_template(template)
        for k, v in form_data.items():
            try:
                setattr(form, k, v)
            except Exception:
                pass
        extractor = DataExtractor()
        extractor.add_extraction(study_id, form)
        _EXTRACTIONS[study_id] = form
        return jsonify({
            "study_id": study_id,
            "extraction": form.to_dict() if hasattr(form, "to_dict") else str(form),
        })
    except Exception as exc:
        logger.exception("/api/sr/extraction failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


# ----------------------------------------------------------------- Synthesis
@sr_bp.route("/synthesis", methods=["POST"])
def synthesis():
    """Run a synthesis method over the supplied extractions.

    Body: ``{"method": str, "extractions": [...]}`` where ``method`` is
    one of ``"narrative"``, ``"meta_analysis"``, ``"qca"``,
    ``"network_meta_analysis"``.
    """
    payload = request.get_json(silent=True) or {}
    method = (payload.get("method") or "narrative").strip().lower()
    extractions = payload.get("extractions") or []
    try:
        from systematic_review.synthesis import SynthesisFactory, SynthesisMethod
        method_map = {
            "narrative": SynthesisMethod.NARRATIVE,
            "meta_analysis": SynthesisMethod.META_ANALYSIS,
            "meta-analysis": SynthesisMethod.META_ANALYSIS,
            "qca": SynthesisMethod.QCA,
            "network_meta_analysis": SynthesisMethod.NETWORK_META_ANALYSIS,
            "network-meta-analysis": SynthesisMethod.NETWORK_META_ANALYSIS,
        }
        synth = SynthesisFactory.create(method_map.get(method, SynthesisMethod.NARRATIVE))
        result = synth.synthesize(extractions)
        return jsonify({
            "method": method,
            "result": result.to_dict() if hasattr(result, "to_dict") else str(result),
        })
    except Exception as exc:
        logger.exception("/api/sr/synthesis failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


# ----------------------------------------------------------------- PRISMA
@sr_bp.route("/prisma-flow", methods=["POST"])
def prisma_flow():
    """Generate a PRISMA flow diagram (SVG/PNG) from the supplied counts.

    Body: ``{"counts": {...}, "format": "svg"|"png"|"pdf"?, "title": str?,
    "extension": str?, "style": str?}``.

    Returns:
        ``{"format": str, "content_b64": str}`` (base64-encoded file
        content) for raster/vector formats.
    """
    payload = request.get_json(silent=True) or {}
    counts_data = payload.get("counts") or {}
    fmt = (payload.get("format") or "svg").strip().lower()
    title = payload.get("title", "")
    extension = payload.get("extension", "standard")
    style = payload.get("style", "bmj")
    try:
        from prisma.flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts
        counts = PRISMAStageCounts.from_dict(counts_data)
        gen = PRISMAFlowGenerator(counts, title=title, extension=extension)
        # Render to a temp path then read back.
        import base64
        import tempfile
        import os
        if fmt == "svg":
            path = tempfile.mktemp(suffix=".svg")
            gen.render_svg(path, style=style)
        elif fmt == "png":
            path = tempfile.mktemp(suffix=".png")
            gen.render_png(path, dpi=150, style=style)
        elif fmt == "pdf":
            path = tempfile.mktemp(suffix=".pdf")
            gen.render_pdf(path, style=style)
        else:
            return _bad_request("format must be one of svg|png|pdf")
        with open(path, "rb") as fh:
            content = base64.b64encode(fh.read()).decode("ascii")
        try:
            os.remove(path)
        except OSError:
            pass
        return jsonify({"format": fmt, "content_b64": content})
    except Exception as exc:
        logger.exception("/api/sr/prisma-flow failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@sr_bp.route("/prisma-checklist", methods=["GET"])
def prisma_checklist():
    """Return the canonical 27-item PRISMA 2020 checklist."""
    try:
        from prisma.checklist import PRISMAChecklist
        cl = PRISMAChecklist()
        return jsonify({"items": [i.to_dict() if hasattr(i, "to_dict") else dict(i) for i in cl.items] if hasattr(cl, "items") else []})
    except Exception as exc:
        logger.exception("/api/sr/prisma-checklist failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502
