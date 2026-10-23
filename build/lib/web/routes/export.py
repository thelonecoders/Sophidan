"""REST endpoints for the ``/api/export`` resource.

Generates downloadable files: tabular paper exports (CSV/XLSX/JSON),
BibTeX bibliographies, and full PDF/DOCX/PPTX reports built through the
real ``reporting`` builder APIs.

Reporting contract (contract #6) — module-level functions and builder
classes this module calls:

* ``export_csv(papers, path=None)`` / ``export_xlsx(...)`` /
  ``export_bibtex(...)`` — each call writes a temp file; the default
  response is the documented file download (with an ``X-Paper-Count``
  header), and ``"return_path": true`` in the body opts into a JSON
  ``{"path": str, "count": int}`` response instead.
* ``PDFReport(title, author)`` + ``add_cover_page`` / ``add_section`` /
  ``add_papers_table`` + ``build(path)``.
* ``DOCXReport(title, author)`` + ``add_heading`` / ``add_papers_table``
  + ``build(path)``.
* ``PPTXReport(title, subtitle)`` + ``add_title_slide`` /
  ``add_papers_slides`` + ``build(path)``.

``POST /api/export/report`` returns the generated file **path**.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import importlib
import io
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

from flask import Blueprint, jsonify, request, send_file

from web.routes._common import (
    MAX_PAPER_SCAN,
    as_int,
    bad_request,
    error_response,
    not_found,
    service_unavailable,
    temp_file_path,
)

logger = logging.getLogger(__name__)

export_bp = Blueprint("export", __name__, url_prefix="/api/export")

# Where generated reports land (parent dirs auto-created by the
# reporting builders). Overridable through ``ARS_REPORT_DIR``.
_REPORT_DIR = os.environ.get(
    "ARS_REPORT_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "data", "reports"),
)


def _state() -> "Any":
    """Return the shared :class:`ServerState` singleton."""
    from web.server import ServerState

    return ServerState()


def _resolve_papers(paper_ids: Any) -> list[dict[str, Any]]:
    """Resolve a list of paper ids to dicts via the database contract."""
    state = _state()
    db = state.db
    if db is None:
        return []
    return db.get_papers_by_ids(paper_ids) or []


def _import_reporting_fn(*candidates: tuple[str, str]) -> Callable[..., Any]:
    """Import the first existing ``(module, attr)`` reporting function.

    Contract #6 places the export helpers on the ``reporting`` package
    (re-exported) and the concrete submodules; both spellings resolve.
    """
    last_exc: Exception | None = None
    for module_path, attr in candidates:
        try:
            module = importlib.import_module(module_path)
            return getattr(module, attr)
        except (ImportError, AttributeError) as exc:
            last_exc = exc
    raise ImportError(
        f"none of the reporting export candidates could be imported: "
        f"{candidates!r} (last error: {last_exc})"
    )


def _run_export_to_bytes(func: Callable[..., Any], papers: list, suffix: str) -> bytes:
    """Call a contract export function and return the produced bytes.

    The contract signature is ``func(papers, path=None)``. We always
    pass an on-disk path (never ``mktemp``), read the file back, and
    fall back to a returned str/bytes payload if the function chose to
    return its output instead of writing it.
    """
    path = temp_file_path(suffix)
    try:
        result = func(papers, path)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, "rb") as fh:
                return fh.read()
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
        if isinstance(result, str):
            return result.encode("utf-8")
        raise RuntimeError("export function produced no output")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _download(data: bytes, mimetype: str, download_name: str, count: int):
    """Send the generated export file with a ``X-Paper-Count`` header.

    The response body stays the documented file download; the paper
    count travels in a header so programmatic clients get the
    ``path + count`` surface (mandate #3) without breaking the
    documented shape. ``return_path: true`` in the request body opts
    into a JSON ``{"path", "count"}`` response instead.
    """
    response = send_file(io.BytesIO(data), mimetype=mimetype,
                         as_attachment=True, download_name=download_name)
    response.headers["X-Paper-Count"] = str(int(count))
    return response


def _run_export_to_path(func: Callable[..., Any], papers: list,
                        suffix: str) -> str:
    """Call a contract export function writing to a persistent temp path.

    Mandate #3: ``export_csv(papers)`` / ``export_xlsx(papers)`` /
    ``export_bibtex(papers)`` write to a temp file; the caller returns
    that path plus the paper count. Used when the request sets
    ``"return_path": true`` (the default keeps the documented download
    shape). The file is the caller's to clean up.
    """
    path = temp_file_path(suffix)
    result = func(papers, path)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        # The contract allows returning str/bytes instead of writing;
        # persist it ourselves so the returned path is always real.
        if isinstance(result, (bytes, bytearray)):
            payload = bytes(result)
        elif isinstance(result, str):
            payload = result.encode("utf-8")
        else:
            raise RuntimeError("export function produced no output")
        with open(path, "wb") as fh:
            fh.write(payload)
    return path


def _maybe_path_response(payload: dict, fmt: str, importer: Callable[[], Any],
                         papers: list, suffix: str):
    """Honour ``return_path: true`` → JSON ``{path, count}`` (or None)."""
    if not payload.get("return_path"):
        return None
    path = _run_export_to_path(importer(), papers, suffix)
    return jsonify({
        "format": fmt,
        "path": path,
        "count": len(papers),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@export_bp.route("/papers", methods=["POST"])
def export_papers():
    """Export a list of papers to a downloadable file.

    Body: ``{"format": "csv"|"json"|"xlsx"|"tsv", "paper_ids": [int],
    "columns": [str]?, "return_path": bool?}``. Default response is a
    file download (``X-Paper-Count`` header); ``"return_path": true``
    yields ``{"path": str, "count": int}`` for a server-side temp file.
    """
    payload = request.get_json(silent=True) or {}
    fmt = (payload.get("format") or "csv").lower()
    paper_ids = payload.get("paper_ids") or []

    if fmt not in {"csv", "json", "tsv", "xlsx"}:
        return bad_request("format must be csv|json|tsv|xlsx")
    if not isinstance(paper_ids, list) or not paper_ids:
        return bad_request("paper_ids (non-empty list) is required")
    try:
        paper_ids = [as_int(pid, name="paper_ids entry") for pid in paper_ids]
    except ValueError as exc:
        return bad_request(str(exc))

    state = _state()
    if state.db is None:
        return service_unavailable("DatabaseConnection")

    papers = _resolve_papers(paper_ids)
    if not papers:
        return not_found("no papers resolved for given ids")

    try:
        if fmt in ("csv", "tsv"):
            def _csv_importer():
                return _import_reporting_fn(
                    ("reporting", "export_csv"),
                    ("reporting.csv_export", "export_csv"),
                )

            by_path = _maybe_path_response(payload, fmt, _csv_importer,
                                           papers,
                                           ".csv" if fmt == "csv" else ".tsv")
            if by_path is not None:
                return by_path
            # Contract: export_csv(papers, path=None) — TSV is a CSV
            # with a tab delimiter; the contract function handles the
            # delimiter when handed a .tsv target via the same call.
            data = _run_export_to_bytes(_csv_importer(), papers,
                                        ".csv" if fmt == "csv" else ".tsv")
            mimetype = ("text/csv" if fmt == "csv"
                        else "text/tab-separated-values")
            return _download(data, mimetype, f"papers.{fmt}",
                             count=len(papers))
        if fmt == "json":
            buf = io.BytesIO(json.dumps(papers, default=str,
                                        indent=2).encode("utf-8"))
            return _download(buf.getvalue(), "application/json",
                             "papers.json", count=len(papers))
        # xlsx — contract: export_xlsx(papers, path=None)
        def _xlsx_importer():
            return _import_reporting_fn(
                ("reporting", "export_xlsx"),
                ("reporting.csv_export", "export_xlsx"),
            )

        by_path = _maybe_path_response(payload, "xlsx", _xlsx_importer,
                                       papers, ".xlsx")
        if by_path is not None:
            return by_path
        data = _run_export_to_bytes(_xlsx_importer(), papers, ".xlsx")
        return _download(
            data,
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet",
            "papers.xlsx", count=len(papers))
    except ImportError as exc:
        logger.error("reporting export function missing: %s", exc)
        return jsonify({
            "error": "not_implemented",
            "message": "the requested export backend is unavailable",
        }), 501
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "export_papers", exc)


def _report_papers_for_project(db: Any, project_id: int) -> list[dict[str, Any]]:
    """Fetch the project's papers through the DB contract."""
    try:
        return db.list_papers(project_id=project_id,
                              limit=MAX_PAPER_SCAN, offset=0) or []
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("list_papers(project_id=%s) failed: %s",
                       project_id, exc)
        return []


def _summary_paragraph(papers: list) -> str:
    """A short corpus summary used as the report's opening section."""
    if not papers:
        return ("No papers were attached to this project at report time. "
                "Import literature via the scraping endpoints and retry.")
    years = sorted({int(p["year"]) for p in papers
                    if isinstance(p.get("year"), int)})
    total_citations = sum(int(p.get("citation_count") or 0) for p in papers)
    span = (f", spanning {years[0]}–{years[-1]}" if years else "")
    return (
        f"This report was generated by the Academic Research Suite on "
        f"{datetime.now(timezone.utc).date().isoformat()} from the project's "
        f"local corpus of {len(papers)} papers{span}, comprising "
        f"{total_citations} recorded citations in total."
    )


def _build_pdf_report(papers: list, sections: list[str], title: str,
                      author: str | None, path: str) -> str:
    """Build a real PDF via the ``PDFReport`` builder API."""
    from reporting.pdf_report import PDFReport

    report = PDFReport(title, author=author)
    report.add_cover_page({
        "title": title,
        "author": author or "Academic Research Suite",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "papers": len(papers),
    })
    for heading in sections:
        if heading.lower() in {"summary", "overview", "introduction"}:
            report.add_section(heading, _summary_paragraph(papers))
        elif heading.lower() in {"papers", "corpus", "bibliography"}:
            report.add_section(heading,
                               f"Corpus listing ({len(papers)} papers).")
        else:
            report.add_section(heading,
                               f"{heading} — see the corpus table below.")
    report.add_papers_table(papers)
    return report.build(path)


def _build_docx_report(papers: list, sections: list[str], title: str,
                       author: str | None, path: str) -> str:
    """Build a real DOCX via the ``DOCXReport`` builder API."""
    from reporting.docx_report import DOCXReport

    report = DOCXReport(title, author=author)
    for heading in sections:
        report.add_heading(heading, level=1)
        if heading.lower() in {"summary", "overview", "introduction"}:
            report.add_paragraph(_summary_paragraph(papers))
    report.add_papers_table(papers)
    return report.build(path)


def _build_pptx_report(papers: list, sections: list[str], title: str,
                       author: str | None, path: str) -> str:
    """Build a real PPTX deck via the ``PPTXReport`` builder API."""
    from reporting.pptx_report import PPTXReport

    deck = PPTXReport(title, subtitle=f"{len(papers)} papers")
    deck.add_title_slide(title, subtitle=f"{len(papers)} papers",
                         author=author)
    for heading in sections:
        deck.add_section_slide(heading)
    # Contract #6: PPTXReport.add_papers_slides(papers).
    deck.add_papers_slides(papers)
    return deck.build(path)


@export_bp.route("/report", methods=["POST"])
def export_report():
    """Generate a full project report (PDF / DOCX / PPTX).

    Body: ``{"type": "pdf"|"docx"|"pptx", "project_id": int,
    "sections": [str]?}``. Papers are fetched from the database and the
    report is built through the real reporting builder API; the
    response returns the generated file **path**.
    """
    payload = request.get_json(silent=True) or {}
    report_type = (payload.get("type") or "pdf").lower()
    sections = payload.get("sections") or ["Summary", "Papers"]

    if report_type not in {"pdf", "docx", "pptx"}:
        return bad_request("type must be pdf|docx|pptx")
    try:
        project_id = as_int(payload.get("project_id"), name="project_id")
    except ValueError as exc:
        return bad_request(str(exc))
    if not isinstance(sections, list) or not sections:
        sections = ["Summary", "Papers"]
    sections = [str(s) for s in sections][:12]

    state = _state()
    if state.db is None:
        return service_unavailable("DatabaseConnection")

    papers = _report_papers_for_project(state.db, project_id)
    title = payload.get("title") or f"Project {project_id} — Research Report"
    author = payload.get("author") or None

    os.makedirs(_REPORT_DIR, exist_ok=True)
    path = os.path.join(_REPORT_DIR,
                        f"report_project{project_id}.{report_type}")

    builders = {
        "pdf": _build_pdf_report,
        "docx": _build_docx_report,
        "pptx": _build_pptx_report,
    }
    try:
        generated = builders[report_type](papers, sections, title, author, path)
    except ImportError as exc:
        logger.error("report builder missing: %s", exc)
        return jsonify({
            "error": "not_implemented",
            "message": "the requested report backend is unavailable",
        }), 501
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "export_report", exc)

    return jsonify({
        "type": report_type,
        "project_id": project_id,
        "papers": len(papers),
        "path": generated or path,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@export_bp.route("/bibtex", methods=["POST"])
def export_bibtex():
    """Export the given papers to a BibTeX file.

    Body: ``{"paper_ids": [int]}``. Returns ``application/x-bibtex``.
    """
    payload = request.get_json(silent=True) or {}
    paper_ids = payload.get("paper_ids") or []
    if not isinstance(paper_ids, list) or not paper_ids:
        return bad_request("paper_ids (non-empty list) is required")
    try:
        paper_ids = [as_int(pid, name="paper_ids entry") for pid in paper_ids]
    except ValueError as exc:
        return bad_request(str(exc))

    state = _state()
    if state.db is None:
        return service_unavailable("DatabaseConnection")

    papers = _resolve_papers(paper_ids)
    if not papers:
        return not_found("no papers resolved for given ids")

    try:
        # Contract: export_bibtex(papers, path=None)
        def _bibtex_importer():
            return _import_reporting_fn(
                ("reporting", "export_bibtex"),
                ("reporting.bibtex_export", "export_bibtex"),
            )

        by_path = _maybe_path_response(payload, "bibtex", _bibtex_importer,
                                       papers, ".bib")
        if by_path is not None:
            return by_path
        data = _run_export_to_bytes(_bibtex_importer(), papers, ".bib")
        return _download(data, "application/x-bibtex", "references.bib",
                         count=len(papers))
    except ImportError as exc:
        logger.error("reporting export_bibtex missing: %s", exc)
        return jsonify({
            "error": "not_implemented",
            "message": "the BibTeX export backend is unavailable",
        }), 501
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "export_bibtex", exc)
