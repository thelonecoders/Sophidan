"""REST endpoints for the ``/api/lifecycle`` (research lifecycle) resource.

Wraps the v2.0.0 :mod:`research_lifecycle` package: gap detection, idea
generation, protocol templates, extraction templates, quality
assessment, reporting checklists, and AI-assisted writing.
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

lifecycle_bp = Blueprint("lifecycle", __name__, url_prefix="/api/lifecycle")


def _bad_request(msg: str):
    return jsonify({"error": "bad_request", "message": msg}), 400


def _coerce_papers(payload: Any) -> list:
    """Best-effort conversion of the payload's ``papers`` field into dicts."""
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


@lifecycle_bp.route("/gaps", methods=["POST"])
def gaps():
    """Detect research gaps for a topic.

    Body: ``{"papers": [...], "topic": str}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    topic = payload.get("topic", "")
    try:
        from research_lifecycle.ideation import ResearchGapDetector
        detector = ResearchGapDetector.from_corpus(papers)
        result = detector.from_literature_review(topic=topic)
        return jsonify({"gaps": [g.to_dict() if hasattr(g, "to_dict") else str(g) for g in (result or [])]})
    except Exception as exc:
        logger.exception("/api/lifecycle/gaps failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@lifecycle_bp.route("/ideas", methods=["POST"])
def ideas():
    """Generate research ideas for a topic.

    Body: ``{"topic": str, "papers": [...]}``.
    """
    payload = request.get_json(silent=True) or {}
    papers = _coerce_papers(payload)
    topic = payload.get("topic", "")
    try:
        from research_lifecycle.ideation import IdeaGenerator
        gen = IdeaGenerator()
        result = gen.generate(topic=topic, papers=papers)
        return jsonify({"ideas": [i.to_dict() if hasattr(i, "to_dict") else str(i) for i in (result or [])]})
    except Exception as exc:
        logger.exception("/api/lifecycle/ideas failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@lifecycle_bp.route("/protocol-templates", methods=["GET"])
def protocol_templates():
    """List the available protocol templates."""
    try:
        from research_lifecycle.protocol_templates import ProtocolTemplateLibrary
        names = ProtocolTemplateLibrary.available()
        return jsonify({"templates": list(names)})
    except Exception as exc:
        logger.exception("/api/lifecycle/protocol-templates failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@lifecycle_bp.route("/protocol", methods=["POST"])
def protocol():
    """Build a populated protocol from a template.

    Body: ``{"template": str, "project_id": str?, "fields": {...}?}``.
    """
    payload = request.get_json(silent=True) or {}
    template = payload.get("template") or "systematic_review"
    fields = payload.get("fields") or {}
    try:
        from research_lifecycle.protocol_templates import ProtocolBuilder
        proto = ProtocolBuilder.from_template(template)
        for k, v in fields.items():
            try:
                proto.fill_section(k, str(v))
            except Exception as exc:
                logger.debug("fill_section(%s) failed: %s", k, exc)
        return jsonify({
            "template": template,
            "project_id": payload.get("project_id"),
            "protocol": proto.protocol.to_dict() if (hasattr(proto, "protocol") and hasattr(proto.protocol, "to_dict")) else str(proto),
        })
    except Exception as exc:
        logger.exception("/api/lifecycle/protocol failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@lifecycle_bp.route("/extraction-templates", methods=["GET"])
def extraction_templates():
    """List the available data-extraction templates."""
    try:
        from research_lifecycle.data_extraction import ExtractionTemplateLibrary
        names = ExtractionTemplateLibrary.available()
        return jsonify({"templates": list(names)})
    except Exception as exc:
        logger.exception("/api/lifecycle/extraction-templates failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@lifecycle_bp.route("/quality-assessment", methods=["POST"])
def quality_assessment():
    """Run a quality / risk-of-bias assessment for a single study.

    Body: ``{"tool": str, "study_data": {...}}`` where ``tool`` is one
    of ``"mmat"``, ``"strobe"``, ``"consort"``, ``"prisma"``, ``"care"``,
    ``"care_plus"``, ``"srqr"``, ``"entreq"``, ``"casp"``.
    """
    payload = request.get_json(silent=True) or {}
    tool_name = (payload.get("tool") or "mmat").strip().lower()
    study_data = payload.get("study_data") or {}
    try:
        from research_lifecycle.quality_assessment import (
            MMAT, STROBEChecklist, CONSORTChecklist, PRISMAComplianceChecklist,
            CAREChecklist, CAREPlusChecklist, SRQRChecklist, ENTREQChecklist,
            CASPChecklist,
        )
        tool_map = {
            "mmat": MMAT,
            "strobe": STROBEChecklist,
            "consort": CONSORTChecklist,
            "prisma": PRISMAComplianceChecklist,
            "care": CAREChecklist,
            "care_plus": CAREPlusChecklist,
            "care+": CAREPlusChecklist,
            "srqr": SRQRChecklist,
            "entreq": ENTREQChecklist,
            "casp": CASPChecklist,
        }
        cls = tool_map.get(tool_name)
        if cls is None:
            return _bad_request(f"unknown tool: {tool_name}")
        result = cls().assess(study_data)
        return jsonify({
            "tool": tool_name,
            "result": result.to_dict() if hasattr(result, "to_dict") else str(result),
        })
    except Exception as exc:
        logger.exception("/api/lifecycle/quality-assessment failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@lifecycle_bp.route("/reporting-checklists", methods=["GET"])
def reporting_checklists():
    """List the available EQUATOR reporting checklists."""
    try:
        from research_lifecycle.reporting_checklists import ReportingChecklist
        names = ReportingChecklist.available_checklists()
        return jsonify({"checklists": list(names)})
    except Exception as exc:
        logger.exception("/api/lifecycle/reporting-checklists failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@lifecycle_bp.route("/write", methods=["POST"])
def write():
    """AI-assisted writing helper.

    Body: ``{"task": str, "content": str, "papers": [...]?}`` where
    ``task`` is one of ``"outline"``, ``"draft_section"``,
    ``"improve_prose"``, ``"check_grammar"``, ``"generate_abstract"``,
    ``"generate_title"``, ``"format_citation"``, ``"paraphrase"``,
    ``"summarize_for_imrad"``.
    """
    payload = request.get_json(silent=True) or {}
    task = (payload.get("task") or "outline").strip().lower()
    content = payload.get("content", "")
    papers = _coerce_papers(payload)
    try:
        from research_lifecycle.writing_assistant import WritingAssistant
        wa = WritingAssistant()
        if task == "outline":
            result = wa.outline(content)
        elif task == "draft_section":
            result = wa.draft_section(content, papers=papers or None)
        elif task == "improve_prose":
            result = wa.improve_prose(content)
        elif task == "check_grammar":
            result = wa.check_grammar(content)
        elif task == "generate_abstract":
            result = wa.generate_abstract(content, papers=papers or None)
        elif task == "generate_title":
            result = wa.generate_title(content)
        elif task == "format_citation":
            result = wa.format_citation(content)
        elif task == "paraphrase":
            result = wa.paraphrase(content)
        elif task == "summarize_for_imrad":
            # Single-paper summarisation.
            paper = papers[0] if papers else content
            result = wa.summarize_for_imrad(paper)
        else:
            return _bad_request(f"unknown task: {task}")
        # Normalise lists / dicts to JSON-friendly shapes.
        if isinstance(result, list):
            return jsonify({"task": task, "result": [str(r) for r in result]})
        if isinstance(result, dict):
            return jsonify({"task": task, "result": result})
        return jsonify({"task": task, "result": str(result)})
    except Exception as exc:
        logger.exception("/api/lifecycle/write failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502
