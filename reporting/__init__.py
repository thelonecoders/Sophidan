"""Reporting package: exports + report builders for the Academic Research Suite.

Module-level contract functions (PATCH CONTRACT #6) — consumed by
``web/routes/export.py`` (``reporting.export_csv`` / ``.export_xlsx`` /
``.export_bibtex``) and re-exported from their concrete submodules:

* :func:`export_csv` — CSV (``.tsv`` targets switch to tab-delimited).
* :func:`export_xlsx` — real ``.xlsx`` workbook (openpyxl).
* :func:`export_bibtex` — BibTeX ``.bib`` file.
* :class:`RisExporter` — RIS records (``.ris``), new in v2.0.1.

Builder classes (``PDFReport``, ``DOCXReport``, ``PPTXReport``) and their
heavy dependencies (reportlab / python-docx / python-pptx) are resolved
lazily via :data:`__getattr__` so ``import reporting`` stays cheap and
dependency-free.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

from .bibtex_export import BibTeXExporter, export_bibtex
from .csv_export import (
    CSVExporter,
    DEFAULT_AUTHOR_COLUMNS,
    DEFAULT_PAPER_COLUMNS,
    export_csv,
    export_xlsx,
    sanitize_csv_value,
)
from .ris_exporter import RisExporter

__all__ = [
    # contract #6 module functions
    "export_csv",
    "export_xlsx",
    "export_bibtex",
    # exporters
    "CSVExporter",
    "BibTeXExporter",
    "RisExporter",
    "sanitize_csv_value",
    "DEFAULT_PAPER_COLUMNS",
    "DEFAULT_AUTHOR_COLUMNS",
    # lazily resolved builder classes
    "PDFReport",
    "DOCXReport",
    "PPTXReport",
]

_LAZY_BUILDERS = {
    "PDFReport": "reporting.pdf_report",
    "DOCXReport": "reporting.docx_report",
    "PPTXReport": "reporting.pptx_report",
}


def __getattr__(name: str):  # noqa: D401 - PEP 562 module-level __getattr__
    """Lazily resolve the report builder classes (heavy deps optional)."""
    module_path = _LAZY_BUILDERS.get(name)
    if module_path is not None:
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, name)
    raise AttributeError(f"module 'reporting' has no attribute {name!r}")
