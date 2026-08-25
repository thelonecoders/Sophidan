"""REST endpoints for the ``/api/export`` resource.

Generates downloadable files: tabular paper exports (CSV/JSON), full
reports (PDF/DOCX/PPTX), and BibTeX bibliographies. Files are streamed
back to the client with the appropriate Content-Type / Content-Disposition
headers.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import io
import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request, send_file

logger = logging.getLogger(__name__)

export_bp = Blueprint("export", __name__, url_prefix="/api/export")


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


def _resolve_papers(paper_ids: list[int]) -> list[dict[str, Any]]:
    """Resolve a list of paper ids to dicts via the database connection."""
    state = _state()
    db = state.db
    if db is None or not hasattr(db, "get_papers_by_ids"):
        return []
    try:
        return db.get_papers_by_ids(paper_ids) or []
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("get_papers_by_ids failed: %s", exc)
        return []


@export_bp.route("/papers", methods=["POST"])
def export_papers():
    """Export a list of papers to a downloadable file.

    Body: ``{"format": "csv"|"json"|"xlsx"|"tsv", "paper_ids": [int],
    "columns": [str]?}``. Returns a file download.
    """
    payload = request.get_json(silent=True) or {}
    fmt = (payload.get("format") or "csv").lower()
    paper_ids = payload.get("paper_ids") or []
    columns = payload.get("columns")

    if fmt not in {"csv", "json", "tsv", "xlsx"}:
        return jsonify({"error": "bad_request",
                        "message": "format must be csv|json|tsv|xlsx"}), 400
    if not isinstance(paper_ids, list) or not paper_ids:
        return jsonify({"error": "bad_request",
                        "message": "paper_ids (non-empty list) is required"}), 400

    papers = _resolve_papers(paper_ids)
    if not papers:
        return jsonify({"error": "not_found",
                        "message": "no papers resolved for given ids"}), 404

    try:
        if fmt == "csv":
            from reporting.csv_export import export_csv

            buf = io.BytesIO()
            export_csv(papers, buf, columns=columns)
            buf.seek(0)
            return send_file(buf, mimetype="text/csv",
                             as_attachment=True,
                             download_name="papers.csv")
        if fmt == "tsv":
            from reporting.csv_export import export_csv

            buf = io.BytesIO()
            export_csv(papers, buf, columns=columns, delimiter="\t")
            buf.seek(0)
            return send_file(buf, mimetype="text/tab-separated-values",
                             as_attachment=True,
                             download_name="papers.tsv")
        if fmt == "json":
            import json

            buf = io.BytesIO(json.dumps(papers, default=str,
                                        indent=2).encode("utf-8"))
            buf.seek(0)
            return send_file(buf, mimetype="application/json",
                             as_attachment=True,
                             download_name="papers.json")
        # xlsx
        try:
            from reporting.csv_export import export_xlsx  # type: ignore

            buf = io.BytesIO()
            export_xlsx(papers, buf, columns=columns)
            buf.seek(0)
            return send_file(buf, mimetype="application/vnd.openxmlformats-"
                                          "officedocument.spreadsheetml.sheet",
                             as_attachment=True, download_name="papers.xlsx")
        except ImportError:
            return jsonify({"error": "not_implemented",
                            "message": "xlsx export requires openpyxl"}), 501
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("export_papers failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500


@export_bp.route("/report", methods=["POST"])
def export_report():
    """Generate a full project report (PDF / DOCX / PPTX).

    Body: ``{"type": "pdf"|"docx"|"pptx", "project_id": int,
    "sections": [str]?}``. Returns a file download.
    """
    payload = request.get_json(silent=True) or {}
    report_type = (payload.get("type") or "pdf").lower()
    project_id = payload.get("project_id")
    sections = payload.get("sections") or ["summary", "papers",
                                           "analytics", "network"]

    if report_type not in {"pdf", "docx", "pptx"}:
        return jsonify({"error": "bad_request",
                        "message": "type must be pdf|docx|pptx"}), 400
    if not isinstance(project_id, int):
        return jsonify({"error": "bad_request",
                        "message": "project_id (int) is required"}), 400

    module_map = {
        "pdf": ("reporting.pdf_report", "PDFReport", "application/pdf",
                "report.pdf"),
        "docx": ("reporting.docx_report", "DOCXReport",
                 "application/vnd.openxmlformats-officedocument."
                 "wordprocessingml.document", "report.docx"),
        "pptx": ("reporting.pptx_report", "PPTXReport",
                 "application/vnd.openxmlformats-officedocument."
                 "presentationml.presentation", "report.pptx"),
    }
    module_path, class_name, mimetype, filename = module_map[report_type]

    state = _state()
    if state.db is None:
        return _service_unavailable("DatabaseConnection")
    if state.project_manager is None:
        return _service_unavailable("ProjectManager")

    try:
        import importlib

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        report = cls(state.project_manager, state.db)
        if not hasattr(report, "generate"):
            return jsonify({"error": "not_implemented",
                            "message": f"{class_name}.generate missing"}), 501
        buf = report.generate(project_id=project_id, sections=sections)
        if isinstance(buf, (bytes, bytearray)):
            buf = io.BytesIO(buf)
        else:
            buf.seek(0) if hasattr(buf, "seek") else None
        return send_file(buf, mimetype=mimetype, as_attachment=True,
                         download_name=filename)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("export_report failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500


@export_bp.route("/bibtex", methods=["POST"])
def export_bibtex():
    """Export the given papers to a BibTeX file.

    Body: ``{"paper_ids": [int]}``. Returns ``application/x-bibtex``.
    """
    payload = request.get_json(silent=True) or {}
    paper_ids = payload.get("paper_ids") or []
    if not isinstance(paper_ids, list) or not paper_ids:
        return jsonify({"error": "bad_request",
                        "message": "paper_ids (non-empty list) is required"}), 400

    papers = _resolve_papers(paper_ids)
    if not papers:
        return jsonify({"error": "not_found",
                        "message": "no papers resolved for given ids"}), 404

    try:
        from reporting.bibtex_export import export_bibtex as _do_export

        text = _do_export(papers)
        buf = io.BytesIO(text.encode("utf-8"))
        buf.seek(0)
        return send_file(buf, mimetype="application/x-bibtex",
                         as_attachment=True,
                         download_name="references.bib")
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("export_bibtex failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500
