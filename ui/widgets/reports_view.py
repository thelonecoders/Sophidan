"""Reports landing page — browse, generate, and re-export reports.

The :class:`ReportsView` widget is the sidebar ``Reports`` destination.
It surfaces four panels:

* **Header**: page title and a "Generate New Report" button that opens
  the existing :class:`ui.dialogs.reporting_dashboard.ReportingDashboard`
  wizard.
* **Quick Export**: five single-click buttons (PDF, DOCX, BibTeX, CSV,
  PPTX) that lazily import the matching ``reporting.*`` module, prompt
  for an output path, and write the file.
* **Templates**: pre-built report templates (Literature Review,
  Systematic Review PRISMA, Meta-Analysis Cochrane, Bibliometric
  Report, Slide Deck) — each button opens the reporting dashboard
  pre-populated with template defaults.
* **Recent Reports**: a table that scans ``data/exports/`` for files
  with the extensions ``.pdf``, ``.docx``, ``.pptx``, ``.bib``,
  ``.csv``.  Each row exposes Open, Re-download (re-export), and
  Delete actions.  An empty-state widget is shown when no reports
  exist.

All heavy dependencies (the ``reporting`` package and its reportlab /
python-docx / python-pptx backends) are imported lazily so this module
is always importable in a stripped-down environment.

Signals:
    report_generated(str): Emitted with the saved file path when a
        new report is generated via the quick-export buttons or the
        reporting dashboard.
    report_opened(str): Emitted when the user opens an existing
        report file from the recent-reports table.
    report_deleted(str): Emitted when the user deletes a report
        file from the recent-reports table.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Any, List, Optional, Sequence

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)


__all__ = ["ReportsView", "TEMPLATE_DEFINITIONS", "QUICK_EXPORT_FORMATS"]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Folder scanned by the recent-reports table.
EXPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "exports",
)

#: File extensions recognised as reports (lower-case, dot-prefixed).
REPORT_EXTENSIONS: tuple = (".pdf", ".docx", ".pptx", ".bib", ".csv")

#: Human-readable labels for each quick-export format.
QUICK_EXPORT_FORMATS: List[dict] = [
    {"key": "pdf", "label": "PDF", "icon": "\U0001F4D5",
     "tooltip": "Generate a publication-quality PDF report (ReportLab).",
     "extension": ".pdf"},
    {"key": "docx", "label": "DOCX", "icon": "\U0001F4C4",
     "tooltip": "Generate a Word document with TOC and bibliography.",
     "extension": ".docx"},
    {"key": "bibtex", "label": "BibTeX", "icon": "\U0001F4DA",
     "tooltip": "Export references as a .bib file (BibTeX).",
     "extension": ".bib"},
    {"key": "csv", "label": "CSV", "icon": "\U0001F4CA",
     "tooltip": "Export one row per paper (UTF-8 with BOM).",
     "extension": ".csv"},
    {"key": "pptx", "label": "PPTX", "icon": "\U0001F4C8",
     "tooltip": "Generate a slide deck (python-pptx).",
     "extension": ".pptx"},
]

#: Pre-built report templates surfaced in the Templates section.
TEMPLATE_DEFINITIONS: List[dict] = [
    {
        "key": "literature_review",
        "title": "Literature Review",
        "icon": "\U0001F4D6",
        "tooltip": "Narrative literature-review template with abstract, "
                   "themes, gap analysis, and bibliography.",
        "report_type": "PDF",
        "sections": ["cover", "abstract", "results", "bibliography"],
    },
    {
        "key": "systematic_review_prisma",
        "title": "Systematic Review (PRISMA)",
        "icon": "\U0001F504",
        "tooltip": "PRISMA 2020 systematic-review report with flow diagram "
                   "and 27-item checklist.",
        "report_type": "DOCX",
        "sections": ["cover", "abstract", "methods", "results",
                     "tables", "bibliography"],
    },
    {
        "key": "meta_analysis_cochrane",
        "title": "Meta-Analysis (Cochrane)",
        "icon": "\U0001F4C9",
        "tooltip": "Cochrane-style meta-analysis report with forest plot, "
                   "funnel plot, and risk-of-bias summary.",
        "report_type": "PDF",
        "sections": ["cover", "abstract", "methods", "results",
                     "tables", "charts", "bibliography"],
    },
    {
        "key": "bibliometric_report",
        "title": "Bibliometric Report",
        "icon": "\U0001F4CA",
        "tooltip": "Bibliometric overview (h-index, citations over time, "
                   "top authors/journals, collaboration map).",
        "report_type": "PDF",
        "sections": ["cover", "results", "tables", "charts"],
    },
    {
        "key": "slide_deck",
        "title": "Slide Deck",
        "icon": "\U0001F4C8",
        "tooltip": "PowerPoint slide deck (one slide per paper plus summary).",
        "report_type": "PPTX",
        "sections": ["cover", "results", "charts"],
    },
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _human_size(num_bytes: float) -> str:
    """Format ``num_bytes`` as a human-readable size string."""
    if num_bytes < 0:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _file_type_label(ext: str) -> str:
    """Map a file extension to a human-readable type label."""
    mapping = {
        ".pdf": "PDF Document",
        ".docx": "Word Document",
        ".pptx": "PowerPoint Deck",
        ".bib": "BibTeX File",
        ".csv": "CSV Spreadsheet",
    }
    return mapping.get(ext.lower(), "Unknown")


def _default_export_path(file_prefix: str, extension: str) -> str:
    """Return a timestamped default export path inside ``EXPORTS_DIR``."""
    if not extension.startswith("."):
        extension = "." + extension
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(EXPORTS_DIR, f"{file_prefix}_{stamp}{extension}")


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class ReportsView(QWidget):
    """Sidebar "Reports" landing page.

    Shows quick-export buttons, pre-built templates, and a recent-reports
    table scanning ``data/exports/``.
    """

    report_generated = Signal(str)
    report_opened = Signal(str)
    report_deleted = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ReportsView")
        self._papers: List[Any] = []
        self._build_ui()
        self.refresh_recent_reports()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # --- Header -------------------------------------------------
        outer.addLayout(self._build_header())

        # --- Quick export ------------------------------------------
        outer.addWidget(self._build_quick_export())

        # --- Templates ---------------------------------------------
        outer.addWidget(self._build_templates())

        # --- Recent reports table + empty state -------------------
        self._recent_group, self._table, self._empty_label = (
            self._build_recent_reports()
        )
        outer.addWidget(self._recent_group, stretch=1)

    def _build_header(self) -> QHBoxLayout:
        lay = QHBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Reports", self)
        f = title.font()
        f.setPointSize(20)
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)
        lay.addStretch(1)
        self.btn_new_report = QPushButton("\U0001F4DD  Generate New Report", self)
        self.btn_new_report.setObjectName("PrimaryButton")
        self.btn_new_report.setToolTip(
            "Open the multi-step report wizard (type, scope, sections, "
            "output path)."
        )
        self.btn_new_report.setCursor(Qt.PointingHandCursor)
        self.btn_new_report.clicked.connect(self._on_open_dashboard)
        lay.addWidget(self.btn_new_report)
        return lay

    def _build_quick_export(self) -> QGroupBox:
        group = QGroupBox("Quick Export", self)
        lay = QGridLayout(group)
        lay.setContentsMargins(12, 16, 12, 12)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(8)
        self._quick_buttons: dict = {}
        for col, fmt in enumerate(QUICK_EXPORT_FORMATS):
            btn = QPushButton(f"{fmt['icon']}  {fmt['label']}", self)
            btn.setToolTip(fmt["tooltip"])
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(40)
            btn.clicked.connect(
                lambda _checked=False, k=fmt["key"]: self._on_quick_export(k)
            )
            lay.addWidget(btn, 0, col)
            self._quick_buttons[fmt["key"]] = btn
        return group

    def _build_templates(self) -> QGroupBox:
        group = QGroupBox("Templates", self)
        lay = QGridLayout(group)
        lay.setContentsMargins(12, 16, 12, 12)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(8)
        self._template_buttons: dict = {}
        cols = min(5, len(TEMPLATE_DEFINITIONS))
        for idx, tpl in enumerate(TEMPLATE_DEFINITIONS):
            row = idx // cols
            col = idx % cols
            btn = QPushButton(f"{tpl['icon']}\n{tpl['title']}", self)
            btn.setToolTip(tpl["tooltip"])
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(56)
            btn.setMinimumWidth(140)
            btn.clicked.connect(
                lambda _checked=False, k=tpl["key"]: self._on_template(k)
            )
            lay.addWidget(btn, row, col)
            self._template_buttons[tpl["key"]] = btn
        return group

    def _build_recent_reports(self):
        group = QGroupBox("Recent Reports", self)
        outer = QVBoxLayout(group)
        outer.setContentsMargins(12, 16, 12, 12)
        outer.setSpacing(6)

        # Toolbar (refresh + open exports folder).
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        lbl_hint = QLabel(
            f"Folder: <code>{EXPORTS_DIR}</code>", group,
        )
        lbl_hint.setToolTip("The folder scanned for generated reports.")
        lbl_hint.setTextFormat(Qt.RichText)
        toolbar.addWidget(lbl_hint)
        toolbar.addStretch(1)
        btn_refresh = QPushButton("\U0001F504  Refresh", group)
        btn_refresh.setToolTip("Re-scan the exports folder.")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(self.refresh_recent_reports)
        toolbar.addWidget(btn_refresh)
        self.btn_open_folder = QPushButton("\U0001F4C2  Open Folder", group)
        self.btn_open_folder.setToolTip(
            "Open the exports folder in the system file manager."
        )
        self.btn_open_folder.setCursor(Qt.PointingHandCursor)
        self.btn_open_folder.clicked.connect(self._on_open_folder)
        toolbar.addWidget(self.btn_open_folder)
        outer.addLayout(toolbar)

        # Table.
        table = QTableWidget(0, 5, group)
        table.setHorizontalHeaderLabels(
            ["Filename", "Type", "Size", "Created", "Actions"]
        )
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(0, 1)  # Stretch
        table.horizontalHeader().setSectionResizeMode(1, 2)  # Resize to contents
        table.horizontalHeader().setSectionResizeMode(2, 2)
        table.horizontalHeader().setSectionResizeMode(3, 2)
        table.horizontalHeader().setSectionResizeMode(4, 2)
        table.setColumnWidth(4, 220)
        outer.addWidget(table, stretch=1)

        # Empty-state widget (shown when no reports found).
        empty = QLabel(
            "\U0001F4C4  No reports yet.\n"
            "Use Quick Export above or click \u201cGenerate New Report\u201d "
            "to create one.",
            group,
        )
        empty.setAlignment(Qt.AlignCenter)
        empty.setStyleSheet("color: #94A3B8; padding: 32px;")
        empty.setVisible(False)
        outer.addWidget(empty)

        return group, table, empty

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_papers(self, papers: Sequence[Any]) -> None:
        """Set the paper collection used as the data source for reports."""
        self._papers = list(papers)
        logger.debug("ReportsView: %d papers available for export.",
                     len(self._papers))

    def refresh_recent_reports(self) -> None:
        """Re-scan ``EXPORTS_DIR`` and rebuild the recent-reports table."""
        files: List[dict] = []
        if os.path.isdir(EXPORTS_DIR):
            for name in sorted(os.listdir(EXPORTS_DIR), reverse=True):
                full = os.path.join(EXPORTS_DIR, name)
                if not os.path.isfile(full):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext not in REPORT_EXTENSIONS:
                    continue
                try:
                    stat = os.stat(full)
                except OSError as exc:
                    logger.warning("Cannot stat %s: %s", full, exc)
                    continue
                files.append({
                    "path": full,
                    "name": name,
                    "ext": ext,
                    "type": _file_type_label(ext),
                    "size": stat.st_size,
                    "size_str": _human_size(stat.st_size),
                    "created": datetime.fromtimestamp(stat.st_ctime),
                    "created_str": datetime.fromtimestamp(
                        stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
                })
        self._populate_table(files)
        self._empty_label.setVisible(not files)
        self._table.setVisible(bool(files))

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------
    def _populate_table(self, rows: List[dict]) -> None:
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            name_item = QTableWidgetItem(row["name"])
            name_item.setToolTip(row["path"])
            name_item.setData(Qt.UserRole, row["path"])
            type_item = QTableWidgetItem(row["type"])
            size_item = QTableWidgetItem(row["size_str"])
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            created_item = QTableWidgetItem(row["created_str"])
            self._table.setItem(r, 0, name_item)
            self._table.setItem(r, 1, type_item)
            self._table.setItem(r, 2, size_item)
            self._table.setItem(r, 3, created_item)
            self._table.setCellWidget(r, 4, self._build_row_actions(row))

    def _build_row_actions(self, row: dict) -> QWidget:
        wrap = QFrame()
        wrap_lay = QHBoxLayout(wrap)
        wrap_lay.setContentsMargins(4, 2, 4, 2)
        wrap_lay.setSpacing(4)
        btn_open = QPushButton("Open", wrap)
        btn_open.setToolTip(f"Open {row['name']} with the system default app.")
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.clicked.connect(
            lambda _checked=False, p=row["path"]: self._on_open_report(p)
        )
        btn_re = QPushButton("Re-export", wrap)
        btn_re.setToolTip("Re-generate this report (opens the export dialog).")
        btn_re.setCursor(Qt.PointingHandCursor)
        btn_re.clicked.connect(
            lambda _checked=False, e=row["ext"]: self._on_reexport(e)
        )
        btn_del = QPushButton("Delete", wrap)
        btn_del.setToolTip("Permanently delete this report file.")
        btn_del.setCursor(Qt.PointingHandCursor)
        btn_del.clicked.connect(
            lambda _checked=False, p=row["path"], n=row["name"]:
                self._on_delete_report(p, n)
        )
        wrap_lay.addWidget(btn_open)
        wrap_lay.addWidget(btn_re)
        wrap_lay.addWidget(btn_del)
        wrap_lay.addStretch(1)
        return wrap

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_open_dashboard(self) -> None:
        """Open the reporting dashboard wizard dialog."""
        try:
            from ui.dialogs.reporting_dashboard import ReportingDashboard
        except Exception as exc:  # pragma: no cover — depends on sibling module
            logger.error("Cannot import ReportingDashboard: %s", exc)
            QMessageBox.warning(
                self, "Reports",
                "The reporting wizard is not available in this build.",
            )
            return
        try:
            dlg = ReportingDashboard(parent=self, data=self._papers or None)
        except TypeError:
            # Older signature without ``data`` kwarg.
            dlg = ReportingDashboard(self)
        try:
            dlg.report_generated.connect(self.report_generated.emit)
        except Exception:
            logger.debug("ReportingDashboard has no report_generated signal.")
        if dlg.exec():
            path = getattr(dlg, "output_path", None) or \
                getattr(dlg, "_output_path", None)
            if path:
                self.report_generated.emit(path)
                self.refresh_recent_reports()

    def _on_quick_export(self, fmt_key: str) -> None:
        """Run a quick export for ``fmt_key`` (pdf/docx/bibtex/csv/pptx)."""
        fmt = next(
            (f for f in QUICK_EXPORT_FORMATS if f["key"] == fmt_key), None
        )
        if fmt is None:
            logger.warning("Unknown quick-export format %r", fmt_key)
            return
        if not self._papers:
            QMessageBox.information(
                self, "No data",
                "No papers are loaded.  Run a search or import a project "
                "before exporting a report.",
            )
            return
        default_path = _default_export_path(fmt["key"], fmt["extension"])
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save {fmt['label']} report", default_path,
            f"{fmt['label']} (*{fmt['extension']});;All files (*)",
        )
        if not path:
            return
        try:
            saved = self._run_export(fmt_key, self._papers, path)
        except Exception as exc:  # pragma: no cover — depends on heavy deps
            logger.error("Quick export %r failed: %s", fmt_key, exc,
                         exc_info=True)
            QMessageBox.critical(
                self, "Export failed",
                f"Could not generate {fmt['label']} report:\n{exc}",
            )
            return
        if saved:
            self.report_generated.emit(saved)
            self.refresh_recent_reports()
            QMessageBox.information(
                self, "Report generated",
                f"Saved: {saved}",
            )

    def _on_template(self, template_key: str) -> None:
        """Open the reporting dashboard pre-loaded with a template config."""
        tpl = next(
            (t for t in TEMPLATE_DEFINITIONS if t["key"] == template_key),
            None,
        )
        if tpl is None:
            logger.warning("Unknown template %r", template_key)
            return
        try:
            from ui.dialogs.reporting_dashboard import ReportingDashboard
        except Exception as exc:  # pragma: no cover
            logger.error("Cannot import ReportingDashboard: %s", exc)
            QMessageBox.warning(self, "Reports",
                                "The reporting wizard is not available.")
            return
        try:
            dlg = ReportingDashboard(parent=self, data=self._papers or None)
        except TypeError:
            dlg = ReportingDashboard(self)
        # Apply template defaults if the dialog exposes them.
        for attr, value in (
            ("preferred_report_type", tpl["report_type"]),
            ("preferred_sections", list(tpl["sections"])),
            ("preferred_title", tpl["title"]),
        ):
            if hasattr(dlg, attr):
                try:
                    setattr(dlg, attr, value)
                except Exception:
                    logger.debug("Could not set %s on ReportingDashboard.",
                                 attr)
        try:
            dlg.report_generated.connect(self.report_generated.emit)
        except Exception:
            logger.debug("ReportingDashboard has no report_generated signal.")
        if dlg.exec():
            path = getattr(dlg, "output_path", None) or \
                getattr(dlg, "_output_path", None)
            if path:
                self.report_generated.emit(path)
                self.refresh_recent_reports()

    def _on_open_report(self, path: str) -> None:
        """Open a report file with the OS default application."""
        if not os.path.isfile(path):
            QMessageBox.warning(self, "File missing",
                                f"File no longer exists:\n{path}")
            self.refresh_recent_reports()
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as exc:
            logger.warning("Could not open %s: %s", path, exc)
            QMessageBox.warning(self, "Open failed",
                                f"Could not open {path}:\n{exc}")
            return
        self.report_opened.emit(path)

    def _on_reexport(self, ext: str) -> None:
        """Trigger a quick export of the same type as an existing file."""
        fmt_key = ext.lstrip(".").lower()
        if fmt_key == "bib":
            fmt_key = "bibtex"
        self._on_quick_export(fmt_key)

    def _on_delete_report(self, path: str, name: str) -> None:
        """Delete a report file after confirmation."""
        confirm = QMessageBox.question(
            self, "Delete report",
            f"Permanently delete {name}?\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            os.remove(path)
        except OSError as exc:
            logger.warning("Could not delete %s: %s", path, exc)
            QMessageBox.warning(self, "Delete failed",
                                f"Could not delete {path}:\n{exc}")
            return
        self.report_deleted.emit(path)
        self.refresh_recent_reports()

    def _on_open_folder(self) -> None:
        """Open the exports folder in the system file manager."""
        os.makedirs(EXPORTS_DIR, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["explorer", EXPORTS_DIR], check=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", EXPORTS_DIR], check=False)
            else:
                subprocess.run(["xdg-open", EXPORTS_DIR], check=False)
        except Exception as exc:
            logger.warning("Could not open exports folder: %s", exc)

    # ------------------------------------------------------------------
    # Export dispatch (lazy imports of reporting.*)
    # ------------------------------------------------------------------
    @staticmethod
    def _run_export(fmt_key: str, papers: Sequence[Any], path: str) -> str:
        """Dispatch to the correct ``reporting.*`` exporter.

        Args:
            fmt_key: One of ``pdf``, ``docx``, ``bibtex``, ``csv``,
                ``pptx``.
            papers: Sequence of ``Paper``-like objects.
            path: Output file path.

        Returns:
            The absolute saved path on success.

        Raises:
            ImportError: If the required heavy dependency is missing.
            Exception: Re-raised from the underlying exporter.
        """
        if fmt_key == "pdf":
            from reporting.pdf_report import PDFReport  # lazy
            rpt = PDFReport("Quick PDF Report", author="Academic Research Suite")
            try:
                rpt.add_papers_table(list(papers))
            except Exception:
                logger.debug("PDFReport.add_papers_table signature changed.")
            return rpt.build(path)
        if fmt_key == "docx":
            from reporting.docx_report import DOCXReport  # lazy
            rpt = DOCXReport("Quick DOCX Report")
            try:
                rpt.add_papers_table(list(papers))
            except Exception:
                logger.debug("DOCXReport.add_papers_table signature changed.")
            return rpt.build(path)
        if fmt_key == "bibtex":
            from reporting.bibtex_export import BibTeXExporter  # lazy
            return BibTeXExporter().export(list(papers), path)
        if fmt_key == "csv":
            from reporting.csv_export import CSVExporter  # lazy
            return CSVExporter().export(list(papers), path)
        if fmt_key == "pptx":
            from reporting.pptx_report import PPTXReport  # lazy
            rpt = PPTXReport("Quick Slide Deck")
            try:
                rpt.add_papers_slides(list(papers))
            except Exception:
                logger.debug("PPTXReport.add_papers_slides signature changed.")
            return rpt.build(path)
        raise ValueError(f"Unknown export format {fmt_key!r}.")
