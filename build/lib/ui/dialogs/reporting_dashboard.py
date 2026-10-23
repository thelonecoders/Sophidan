"""Reporting Dashboard dialog (multi-step report generation wizard).

Provides :class:`ReportingDashboard` — a modal QDialog wizard that walks the
user through:
  * Step 1: Choose report type (PDF / DOCX / PPTX / BibTeX / CSV).
  * Step 2: Choose scope (current project / all projects / search results /
    manual selection).
  * Step 3: Choose sections to include (cover / abstract / methods / results /
    tables / charts / bibliography).
  * Step 4: Choose output location and filename.
  * Progress bar during generation.

Uses ``reporting.*`` modules (lazy import) and ``utils.workers.Worker`` for
background generation.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Supported report types.
REPORT_TYPES: List[str] = ["PDF", "DOCX", "PPTX", "BibTeX", "CSV"]

# Section checkboxes presented in step 3.
REPORT_SECTIONS: List[str] = [
    "cover", "abstract", "methods", "results", "tables", "charts", "bibliography",
]

# Scope options presented in step 2.
SCOPE_OPTIONS: List[str] = [
    "Current project",
    "All projects",
    "Search results",
    "Manual selection",
]


class ReportingDashboard(QDialog):
    """Modal multi-step report-generation wizard dialog.

    Emits ``report_generated(str)`` with the saved file path on success.
    """

    report_generated = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None,
                 data: Any = None) -> None:
        """Initialize the wizard.

        Args:
            data: Optional data payload to be passed to the report generators
                (typically a list of paper dicts or a DataFrame).
        """
        super().__init__(parent)
        self.setWindowTitle("Report Generation Wizard")
        self.setModal(True)
        self.setMinimumWidth(640)
        self._data = data
        self._worker: Optional[Any] = None
        self._step = 0

        self._build_ui()
        self._connect_signals()
        self._update_step()

    # ------------------------------------------------- Template defaults

    def set_preferred_config(self, report_type: Optional[str] = None,
                             sections: Optional[List[str]] = None,
                             title: Optional[str] = None) -> None:
        """Pre-select wizard options (used by ReportsView templates)."""
        if report_type:
            rb = self.report_type_buttons.get(str(report_type).upper()) \
                or self.report_type_buttons.get(str(report_type))
            if rb is not None:
                rb.setChecked(True)
        if sections:
            for sec, cb in self.section_checks.items():
                cb.setChecked(sec in sections)
        if title:
            self._preferred_title = str(title)

    # Pre-defined attributes consumed by set_preferred_config / _build_config.
    _preferred_title: Optional[str] = None

    def set_preferred_report_type(self, value: str) -> None:
        self.set_preferred_config(report_type=value)

    def set_preferred_sections(self, value: List[str]) -> None:
        self.set_preferred_config(sections=value)

    def set_preferred_title(self, value: str) -> None:
        self.set_preferred_config(title=value)

    # ----------------------------------------------------------- UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(10)

        # Step indicator
        self.step_label = QLabel()
        f = self.step_label.font()
        f.setPointSize(11)
        f.setBold(True)
        self.step_label.setFont(f)
        outer.addWidget(self.step_label)

        # Stacked widget for steps
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_step1())
        self.stack.addWidget(self._build_step2())
        self.stack.addWidget(self._build_step3())
        self.stack.addWidget(self._build_step4())
        outer.addWidget(self.stack, stretch=1)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        outer.addWidget(self.progress_bar)

        # Nav buttons
        btns = QHBoxLayout()
        self.back_btn = QPushButton("◀ Back")
        self.next_btn = QPushButton("Next ▶")
        self.cancel_btn = QPushButton("Cancel")
        self.generate_btn = QPushButton("Generate Report")
        self.generate_btn.setObjectName("PrimaryBtn")
        self.generate_btn.setVisible(False)
        btns.addWidget(self.cancel_btn)
        btns.addStretch()
        btns.addWidget(self.back_btn)
        btns.addWidget(self.next_btn)
        btns.addWidget(self.generate_btn)
        outer.addLayout(btns)

    def _build_step1(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Step 1: Choose report type"))
        layout.addWidget(self._separator())
        self.report_type_buttons: Dict[str, QRadioButton] = {}
        self.report_type_group = QButtonGroup(self)
        for i, rt in enumerate(REPORT_TYPES):
            rb = QRadioButton(rt)
            if i == 0:
                rb.setChecked(True)
            self.report_type_buttons[rt] = rb
            self.report_type_group.addButton(rb)
            layout.addWidget(rb)
        layout.addStretch()
        return page

    def _build_step2(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Step 2: Choose scope"))
        layout.addWidget(self._separator())
        self.scope_buttons: Dict[str, QRadioButton] = {}
        self.scope_group = QButtonGroup(self)
        for i, scope in enumerate(SCOPE_OPTIONS):
            rb = QRadioButton(scope)
            if i == 0:
                rb.setChecked(True)
            self.scope_buttons[scope] = rb
            self.scope_group.addButton(rb)
            layout.addWidget(rb)
        # Manual selection list
        self.manual_list = QListWidget()
        self.manual_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.manual_list.setVisible(False)
        layout.addWidget(self.manual_list)
        layout.addStretch()
        return page

    def _build_step3(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Step 3: Choose sections to include"))
        layout.addWidget(self._separator())
        self.section_checks: Dict[str, QCheckBox] = {}
        for sec in REPORT_SECTIONS:
            cb = QCheckBox(sec)
            cb.setChecked(True)
            self.section_checks[sec] = cb
            layout.addWidget(cb)
        layout.addStretch()
        return page

    def _build_step4(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Step 4: Output location"))
        layout.addWidget(self._separator())
        form = QFormLayout()
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("report.pdf")
        browse_row = QHBoxLayout()
        browse_row.addWidget(self.filename_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_output)
        browse_row.addWidget(browse_btn)
        browse_holder = QWidget()
        browse_holder.setLayout(browse_row)
        form.addRow("File name:", browse_holder)
        layout.addLayout(form)
        layout.addStretch()
        return page

    def _separator(self) -> QWidget:
        from qtpy.QtWidgets import QFrame
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        return sep

    def _connect_signals(self) -> None:
        self.next_btn.clicked.connect(self._on_next)
        self.back_btn.clicked.connect(self._on_back)
        self.cancel_btn.clicked.connect(self.reject)
        self.generate_btn.clicked.connect(self._on_generate)
        # Toggle manual selection list based on scope choice
        for rb in self.scope_buttons.values():
            rb.toggled.connect(self._update_scope_visibility)

    def _update_scope_visibility(self) -> None:
        self.manual_list.setVisible(
            self.scope_buttons["Manual selection"].isChecked()
        )

    def _update_step(self) -> None:
        self.stack.setCurrentIndex(self._step)
        self.step_label.setText(f"Step {self._step + 1} / 4")
        self.back_btn.setEnabled(self._step > 0)
        self.next_btn.setVisible(self._step < 3)
        self.generate_btn.setVisible(self._step == 3)

    def _on_next(self) -> None:
        if self._step < 3:
            self._step += 1
            self._update_step()

    def _on_back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._update_step()

    # ----------------------------------------------------------- Generation

    def _browse_output(self) -> None:
        report_type = self._selected_report_type().lower()
        filt = {
            "pdf": "PDF (*.pdf)",
            "docx": "Word document (*.docx)",
            "pptx": "PowerPoint (*.pptx)",
            "bibtex": "BibTeX (*.bib)",
            "csv": "CSV (*.csv)",
        }.get(report_type, "All files (*)")
        path, _ = QFileDialog.getSaveFileName(
            self, "Output File", "", filt
        )
        if path:
            self.filename_edit.setText(path)

    def _selected_report_type(self) -> str:
        for rt, rb in self.report_type_buttons.items():
            if rb.isChecked():
                return rt
        return REPORT_TYPES[0]

    def _selected_scope(self) -> str:
        for scope, rb in self.scope_buttons.items():
            if rb.isChecked():
                return scope
        return SCOPE_OPTIONS[0]

    def _selected_sections(self) -> List[str]:
        return [sec for sec, cb in self.section_checks.items() if cb.isChecked()]

    def _selected_manual_items(self) -> List[str]:
        return [item.text() for item in self.manual_list.selectedItems()]

    def _build_config(self) -> Dict[str, Any]:
        # Honor plain attributes set by callers (ReportsView templates)
        # before falling back to the wizard's own selections.
        preferred_rt = getattr(self, "preferred_report_type", None)
        report_type = str(preferred_rt) if preferred_rt else self._selected_report_type()
        preferred_secs = getattr(self, "preferred_sections", None)
        sections = list(preferred_secs) if preferred_secs else self._selected_sections()
        return {
            "report_type": report_type,
            "scope": self._selected_scope(),
            "sections": sections,
            "output_path": self.filename_edit.text().strip(),
            "manual_items": self._selected_manual_items(),
            "data": self._data,
        }

    def _on_generate(self) -> None:
        config = self._build_config()
        papers = config["data"]
        if not config["output_path"]:
            QMessageBox.warning(self, "Output path required", "Please choose an output file.")
            return
        if not papers:
            QMessageBox.warning(
                self, "No data",
                "No papers are loaded for the selected scope.\n"
                "Run a search or load a project, then reopen the wizard.")
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)

        from utils.workers import Worker, WorkerPool

        def _work(progress_callback=None) -> str:
            report = progress_callback or (lambda pct, msg="": None)
            report(0, "Generating report…")
            path = self._invoke_generator(config)
            report(100, "Done")
            return path

        self._worker = Worker(_work)
        self._worker.signals.progress.connect(self._on_generation_progress)
        self._worker.signals.result.connect(self._on_generation_finished)
        self._worker.signals.error.connect(self._on_generation_error)
        WorkerPool.instance().submit(self._worker)

    def _on_generation_progress(self, percent: int, message: str = "") -> None:
        self.progress_bar.setValue(int(percent))
        if message:
            self.progress_bar.setFormat(f"%p% — {message}")

    def _invoke_generator(self, config: Dict[str, Any]) -> str:
        """Dispatch to the ``reporting.*`` builder API (lazy import).

        The real classes are ``PDFReport`` / ``DOCXReport`` /
        ``PPTXReport`` / ``BibTeXExporter`` — a ``.generate()`` method
        exists on none of them; documents are assembled with the
        ``add_*`` builder methods and written via ``build(path)``.
        """
        rt = config["report_type"].lower()
        papers = list(config["data"] or [])
        path = config["output_path"]
        sections = set(config["sections"])
        title = (self._preferred_title
                 or getattr(self, "preferred_title", None)
                 or "Academic Research Report")

        if rt == "pdf":
            from reporting.pdf_report import PDFReport
            rpt = PDFReport(title=title, author="Academic Research Suite")
            if "cover" in sections:
                try:
                    rpt.add_cover_page({"title": title,
                                        "papers": len(papers)})
                except Exception:  # noqa: BLE001
                    logger.debug("PDF cover page skipped.", exc_info=True)
            if "abstract" in sections:
                rpt.add_section("Abstract",
                                f"This report summarises {len(papers)} papers.")
            if "methods" in sections:
                rpt.add_section("Methods",
                                "Papers were collected via the multi-source "
                                "search panel and curated in the Data view.")
            if "results" in sections:
                rpt.add_section("Results",
                                f"The corpus contains {len(papers)} records.")
            if "tables" in sections:
                rpt.add_papers_table(papers)
            if "bibliography" in sections:
                try:
                    from reporting.bibtex_export import BibTeXExporter
                    bib = BibTeXExporter().to_string(papers)
                    rpt.add_section("Bibliography", bib)
                except Exception:  # noqa: BLE001
                    logger.debug("PDF bibliography skipped.", exc_info=True)
            return rpt.build(path)

        if rt == "docx":
            from reporting.docx_report import DOCXReport
            rpt = DOCXReport(title=title, author="Academic Research Suite")
            if "cover" in sections:
                rpt.add_heading(title, level=0)
            if "abstract" in sections:
                rpt.add_heading("Abstract", level=1)
                rpt.add_paragraph(f"This report summarises {len(papers)} papers.")
            if "methods" in sections:
                rpt.add_heading("Methods", level=1)
                rpt.add_paragraph(
                    "Papers were collected via the multi-source search panel.")
            if "results" in sections:
                rpt.add_heading("Results", level=1)
                rpt.add_paragraph(f"The corpus contains {len(papers)} records.")
            if "tables" in sections:
                rpt.add_papers_table(papers)
            if "bibliography" in sections:
                rpt.add_bibliography(papers)
            return rpt.build(path)

        if rt == "pptx":
            from reporting.pptx_report import PPTXReport
            rpt = PPTXReport(title=title,
                             subtitle=f"Corpus of {len(papers)} papers")
            if "cover" in sections:
                rpt.add_title_slide(title,
                                    f"Corpus of {len(papers)} papers",
                                    author="Academic Research Suite")
            if "tables" in sections:
                try:
                    rpt.add_papers_slides(papers)
                except Exception:  # noqa: BLE001
                    logger.debug("PPTX paper slides skipped.", exc_info=True)
            return rpt.build(path)

        if rt == "bibtex":
            from reporting.bibtex_export import BibTeXExporter
            return BibTeXExporter().export(papers, path)

        if rt == "csv":
            from reporting.csv_export import CSVExporter
            return CSVExporter().export(papers, path)

        raise ValueError(f"Unsupported report type: {config['report_type']!r}")

    def _on_generation_finished(self, path: Any) -> None:
        self.progress_bar.setValue(100)
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        QMessageBox.information(self, "Done", f"Report generated:\n{path}")
        self.report_generated.emit(str(path))
        self.accept()

    def _on_generation_error(self, err: Any) -> None:
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        logger.error("Report generation error: %s", err)
        QMessageBox.critical(self, "Error", f"Report generation failed:\n{err}")

    # ----------------------------------------------------------- Public API

    def set_manual_items(self, items: List[str]) -> None:
        """Populate the manual selection list with display items."""
        self.manual_list.clear()
        for it in items:
            self.manual_list.addItem(QListWidgetItem(it))

    def get_config(self) -> Dict[str, Any]:
        """Return the full configuration dict chosen by the user."""
        return self._build_config()
