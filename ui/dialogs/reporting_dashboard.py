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
        self.generate_btn.setObjectName("PrimaryButton")
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
        return {
            "report_type": self._selected_report_type(),
            "scope": self._selected_scope(),
            "sections": self._selected_sections(),
            "output_path": self.filename_edit.text().strip(),
            "manual_items": self._selected_manual_items(),
            "data": self._data,
        }

    def _on_generate(self) -> None:
        config = self._build_config()
        if not config["output_path"]:
            QMessageBox.warning(self, "Output path required", "Please choose an output file.")
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)

        try:
            from utils.workers import Worker  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("utils.workers.Worker unavailable, running sync: %s", exc)
            Worker = None  # type: ignore

        def _work() -> Any:
            return self._invoke_generator(config)

        if Worker is None:
            try:
                path = _work()
                self._on_generation_finished(path)
            except Exception as exc:  # noqa: BLE001
                self._on_generation_error(str(exc))
            return

        self._worker = Worker(_work)
        for sig_name, slot in (
            ("progress", self.progress_bar.setValue),
            ("result", self._on_generation_finished),
            ("error", self._on_generation_error),
        ):
            sig = getattr(self._worker, sig_name, None)
            if sig is not None:
                try:
                    sig.connect(slot)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Could not connect %s: %s", sig_name, exc)
        try:
            self._worker.start()
        except Exception as exc:  # noqa: BLE001
            self._on_generation_error(str(exc))

    def _invoke_generator(self, config: Dict[str, Any]) -> str:
        """Dispatch to the appropriate ``reporting.*`` module (lazy import)."""
        rt = config["report_type"].lower()
        data = config["data"]
        path = config["output_path"]
        sections = config["sections"]
        try:
            if rt == "pdf":
                from reporting.pdf_report import PDFReportGenerator
                gen = PDFReportGenerator()
                return gen.generate(data, path, sections=sections)
            if rt == "docx":
                from reporting.docx_report import DocxReportGenerator
                gen = DocxReportGenerator()
                return gen.generate(data, path, sections=sections)
            if rt == "pptx":
                from reporting.pptx_report import PptxReportGenerator
                gen = PptxReportGenerator()
                return gen.generate(data, path, sections=sections)
            if rt == "bibtex":
                from reporting.bibtex_export import BibtexExporter
                gen = BibtexExporter()
                return gen.export(data, path)
            if rt == "csv":
                from reporting.csv_export import CSVExporter
                gen = CSVExporter()
                return gen.export(data, path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Report generation failed: %s", exc)
            raise
        return path

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
