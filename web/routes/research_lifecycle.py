"""REST endpoints for the ``/api/lifecycle`` (research lifecycle) resource.

Wraps the v2.0.0 :mod:`research_lifecycle` package: gap detection, idea
generation, protocol templates, extraction templates, quality
assessment, reporting checklists, and AI-assisted writing.

Every handler calls the real engine signatures (no phantom methods):

* ``ResearchGapDetector().from_corpus(papers, topic=...)`` — instance
  method returning :class:`ResearchGap` objects.
* ``ProtocolTemplateLibrary().get(name) -> ProtocolTemplate``;
  ``ProtocolBuilder().from_template(tpl) -> Protocol``;
  ``ProtocolBuilder.fill_section(proto, heading, body)`` (static).
* ``WritingAssistant.draft_section(section_heading, outline_item,
  supporting_papers)`` and ``WritingAssistant.generate_abstract(paper)``.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from web.routes._common import as_int, error_response, normalize_papers_payload

logger = logging.getLogger(__name__)

lifecycle_bp = Blueprint("lifecycle", __name__, url_prefix="/api/lifecycle")


def _bad_request(msg: str):
    return jsonify({"error": "bad_request", "message": msg}), 400


def _coerce_papers(payload: Any) -> list:
    """Best-effort conversion of the payload's ``papers`` field into dicts."""
    if not isinstance(payload, dict):
        return []
    return normalize_papers_payload(payload.get("papers"))


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
        # Instance method: from_corpus(papers, topic=None, max_gaps=10).
        detector = ResearchGapDetector()
        result = detector.from_corpus(papers, topic=topic)
        return jsonify({"gaps": [g.to_dict() if hasattr(g, "to_dict") else str(g) for g in (result or [])]})
    except Exception as exc:
        return error_response(logger, "/api/lifecycle/gaps", exc,
                              status=502, error="analysis_failed")


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
        return error_response(logger, "/api/lifecycle/ideas", exc,
                              status=502, error="analysis_failed")


@lifecycle_bp.route("/protocol-templates", methods=["GET"])
def protocol_templates():
    """List the available protocol templates."""
    try:
        from research_lifecycle.protocol_templates import ProtocolTemplateLibrary
        names = ProtocolTemplateLibrary.available()
        return jsonify({"templates": list(names)})
    except Exception as exc:
        return error_response(logger, "/api/lifecycle/protocol-templates", exc,
                              status=502, error="analysis_failed")


@lifecycle_bp.route("/protocol", methods=["POST"])
def protocol():
    """Build a populated protocol from a template.

    Body: ``{"template": str, "project_id": int?, "fields": {heading:
    body, ...}}``.

    Pipeline: ``ProtocolTemplateLibrary().get(template)`` →
    ``ProtocolBuilder().from_template(tpl)`` →
    ``ProtocolBuilder.fill_section(proto, heading, body)`` (static) for
    each supplied field.
    """
    payload = request.get_json(silent=True) or {}
    template = payload.get("template") or "systematic_review"
    fields = payload.get("fields") or {}
    if not isinstance(fields, dict):
        return _bad_request("fields must be an object of {heading: body}")
    project_id = None
    if payload.get("project_id") is not None:
        try:
            project_id = as_int(payload.get("project_id"), name="project_id")
        except ValueError as exc:
            return _bad_request(str(exc))
    try:
        from research_lifecycle.protocol_templates import (
            ProtocolBuilder, ProtocolTemplateLibrary,
        )
        tpl = ProtocolTemplateLibrary().get(template)
        # Real signature: from_template(template, project_id=None).
        proto = ProtocolBuilder().from_template(tpl, project_id=project_id)
        for heading, body in fields.items():
            ProtocolBuilder.fill_section(proto, str(heading), str(body))
        data = proto.__dict__ if hasattr(proto, "__dict__") else str(proto)
        return jsonify({
            "template": template,
            "project_id": payload.get("project_id"),
            "protocol": data,
        })
    except KeyError:
        return _bad_request(f"unknown protocol template: {template}")
    except Exception as exc:
        return error_response(logger, "/api/lifecycle/protocol", exc,
                              status=502, error="analysis_failed")


@lifecycle_bp.route("/extraction-templates", methods=["GET"])
def extraction_templates():
    """List the available data-extraction templates."""
    try:
        from research_lifecycle.data_extraction import ExtractionTemplateLibrary
        names = ExtractionTemplateLibrary.available()
        return jsonify({"templates": list(names)})
    except Exception as exc:
        return error_response(logger, "/api/lifecycle/extraction-templates", exc,
                              status=502, error="analysis_failed")


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
        return error_response(logger, "/api/lifecycle/quality-assessment", exc,
                              status=502, error="analysis_failed")


@lifecycle_bp.route("/reporting-checklists", methods=["GET"])
def reporting_checklists():
    """List the available EQUATOR reporting checklists."""
    try:
        from research_lifecycle.reporting_checklists import ReportingChecklist
        names = ReportingChecklist.available_checklists()
        return jsonify({"checklists": list(names)})
    except Exception as exc:
        return error_response(logger, "/api/lifecycle/reporting-checklists", exc,
                              status=502, error="analysis_failed")


@lifecycle_bp.route("/write", methods=["POST"])
def write():
    """AI-assisted writing helper.

    Body: ``{"task": str, "content": str, "papers": [...]?}`` where
    ``task`` is one of ``"outline"``, ``"draft_section"``,
    ``"improve_prose"``, ``"check_grammar"``, ``"generate_abstract"``,
    ``"generate_title"``, ``"format_citation"``, ``"paraphrase"``,
    ``"summarize_for_imrad"``.

    Real signatures used: ``draft_section(section_heading,
    outline_item, supporting_papers)`` and
    ``generate_abstract(paper)``. For the single-paper tasks the first
    paper in ``papers`` (or a stub built from ``content``) is passed.
    """
    payload = request.get_json(silent=True) or {}
    task = (payload.get("task") or "outline").strip().lower()
    content = payload.get("content", "")
    papers = _coerce_papers(payload)
    section_heading = payload.get("section_heading") or content
    outline_item = payload.get("outline_item") or content
    try:
        from research_lifecycle.writing_assistant import WritingAssistant
        wa = WritingAssistant()
        if task == "outline":
            result = wa.outline(str(content or "Untitled topic"),
                                papers=papers or None)
        elif task == "draft_section":
            result = wa.draft_section(
                str(section_heading), str(outline_item),
                papers or [])
        elif task == "improve_prose":
            result = wa.improve_prose(str(content))
        elif task == "check_grammar":
            result = wa.check_grammar(str(content))
        elif task == "generate_abstract":
            result = wa.generate_abstract(
                papers[0] if papers
                else {"title": str(content), "abstract": str(content)})
        elif task == "generate_title":
            result = wa.generate_title(
                papers[0] if papers
                else {"title": str(content), "abstract": str(content)})
        elif task == "format_citation":
            result = wa.format_citation(
                papers[0] if papers
                else {"title": str(content), "authors": []})
        elif task == "paraphrase":
            result = wa.paraphrase(str(content))
        elif task == "summarize_for_imrad":
            # Single-paper summarisation.
            paper = papers[0] if papers \
                else {"title": str(content), "abstract": str(content)}
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
        return error_response(logger, "/api/lifecycle/write", exc,
                              status=502, error="analysis_failed")
