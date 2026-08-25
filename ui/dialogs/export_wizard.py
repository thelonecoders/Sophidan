"""Export Wizard dialog (multi-step data export).

Provides :class:`ExportWizard` — a modal QDialog wizard that walks the user
through:
  * Step 1: Choose format (CSV / JSON / BibTeX / RIS / Excel / Parquet).
  * Step 2: Choose scope (current project / all projects / search results /
    manual selection).
  * Step 3: Choose columns / fields to include.
  * Step 4: Choose output location.
  * Progress bar during export + "open folder after export" option.

Uses ``reporting.*`` modules (lazy import) and ``utils.workers.Worker``.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
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

# Export formats exposed in step 1.
EXPORT_FORMATS: List[str] = ["CSV", "JSON", "BibTeX", "RIS", "Excel", "Parquet"]

# Scope options presented in step 2.
SCOPE_OPTIONS: List[str] = [
    "Current project",
    "All projects",
    "Search results",
    "Manual selection",
]

# Default columns exposed in step 3.
DEFAULT_COLUMNS: List[str] = [
    "title", "authors", "year", "venue", "doi",
    "citations", "abstract", "keywords", "source",
]


class ExportWizard(QDialog):
    """Modal multi-step data export wizard dialog.

    Emits ``export_finished(str)`` with the saved file path on success.
    """

    export_finished = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None,
                 data: Any = None) -> None:
        """Initialize the wizard.

        Args:
            data: Optional data payload (list of dicts / DataFrame) to export.
        """
        super().__init__(parent)
        self.setWindowTitle("Export Wizard")
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

        self.step_label = QLabel()
        f = self.step_label.font()
        f.setPointSize(11)
        f.setBold(True)
        self.step_label.setFont(f)
        outer.addWidget(self.step_label)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_step1())
        self.stack.addWidget(self._build_step2())
        self.stack.addWidget(self._build_step3())
        self.stack.addWidget(self._build_step4())
        outer.addWidget(self.stack, stretch=1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)
        outer.addWidget(self.progress_bar)

        btns = QHBoxLayout()
        self.back_btn = QPushButton("◀ Back")
        self.next_btn = QPushButton("Next ▶")
        self.cancel_btn = QPushButton("Cancel")
        self.export_btn = QPushButton("Export")
        self.export_btn.setObjectName("PrimaryButton")
        self.export_btn.setVisible(False)
        btns.addWidget(self.cancel_btn)
        btns.addStretch()
        btns.addWidget(self.back_btn)
        btns.addWidget(self.next_btn)
        btns.addWidget(self.export_btn)
        outer.addLayout(btns)

    def _build_step1(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Step 1: Choose export format"))
        layout.addWidget(self._separator())
        self.format_buttons: Dict[str, QRadioButton] = {}
        self.format_group = QButtonGroup(self)
        for i, fmt in enumerate(EXPORT_FORMATS):
            rb = QRadioButton(fmt)
            if i == 0:
                rb.setChecked(True)
            self.format_buttons[fmt] = rb
            self.format_group.addButton(rb)
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
        self.manual_list = QListWidget()
        self.manual_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self.manual_list.setVisible(False)
        layout.addWidget(self.manual_list)
        layout.addStretch()
        return page

    def _build_step3(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Step 3: Choose columns / fields"))
        layout.addWidget(self._separator())

        col_row = QHBoxLayout()
        col_row.addWidget(QLabel("Preset:"))
        self.column_preset = QComboBox()
        self.column_preset.addItems(["Default", "Bibliographic only", "All available"])
        self.column_preset.currentIndexChanged.connect(self._apply_preset)
        col_row.addWidget(self.column_preset)
        col_row.addStretch()
        layout.addLayout(col_row)

        self.columns_list = QListWidget()
        for col in DEFAULT_COLUMNS:
            item = QListWidgetItem(col)
            item.setCheckState(Qt.CheckState.Checked)
            self.columns_list.addItem(item)
        layout.addWidget(self.columns_list, stretch=1)
        return page

    def _build_step4(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Step 4: Output location"))
        layout.addWidget(self._separator())
        form = QFormLayout()
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("export.csv")
        browse_row = QHBoxLayout()
        browse_row.addWidget(self.filename_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_output)
        browse_row.addWidget(browse_btn)
        browse_holder = QWidget()
        browse_holder.setLayout(browse_row)
        form.addRow("File name:", browse_holder)
        layout.addLayout(form)

        self.open_folder_check = QCheckBox("Open folder after export")
        self.open_folder_check.setChecked(True)
        layout.addWidget(self.open_folder_check)
        layout.addStretch()
        return page

    def _separator(self) -> QWidget:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        return sep

    def _connect_signals(self) -> None:
        self.next_btn.clicked.connect(self._on_next)
        self.back_btn.clicked.connect(self._on_back)
        self.cancel_btn.clicked.connect(self.reject)
        self.export_btn.clicked.connect(self._on_export)
        for rb in self.scope_buttons.values():
            rb.toggled.connect(self._update_scope_visibility)

    def _update_scope_visibility(self) -> None:
        self.manual_list.setVisible(
            self.scope_buttons["Manual selection"].isChecked()
        )

    def _apply_preset(self, index: int) -> None:
        if index == 0:  # Default
            states = [Qt.CheckState.Checked] * self.columns_list.count()
        elif index == 1:  # Bibliographic only
            for i in range(self.columns_list.count()):
                item = self.columns_list.item(i)
                col = item.text() if item is not None else ""
                state = (Qt.CheckState.Checked if col in
                          ("title", "authors", "year", "venue", "doi")
                          else Qt.CheckState.Unchecked)
                if item is not None:
                    item.setCheckState(state)
            return
        else:  # All
            states = [Qt.CheckState.Checked] * self.columns_list.count()
        for i, state in enumerate(states):
            item = self.columns_list.item(i)
            if item is not None:
                item.setCheckState(state)

    def _update_step(self) -> None:
        self.stack.setCurrentIndex(self._step)
        self.step_label.setText(f"Step {self._step + 1} / 4")
        self.back_btn.setEnabled(self._step > 0)
        self.next_btn.setVisible(self._step < 3)
        self.export_btn.setVisible(self._step == 3)

    def _on_next(self) -> None:
        if self._step < 3:
            self._step += 1
            self._update_step()

    def _on_back(self) -> None:
        if self._step > 0:
            self._step -= 1
            self._update_step()

    # ----------------------------------------------------------- Export

    def _browse_output(self) -> None:
        fmt = self._selected_format().lower()
        filt = {
            "csv": "CSV (*.csv)",
            "json": "JSON (*.json)",
            "bibtex": "BibTeX (*.bib)",
            "ris": "RIS (*.ris)",
            "excel": "Excel (*.xlsx)",
            "parquet": "Parquet (*.parquet)",
        }.get(fmt, "All files (*)")
        path, _ = QFileDialog.getSaveFileName(self, "Output File", "", filt)
        if path:
            self.filename_edit.setText(path)

    def _selected_format(self) -> str:
        for fmt, rb in self.format_buttons.items():
            if rb.isChecked():
                return fmt
        return EXPORT_FORMATS[0]

    def _selected_scope(self) -> str:
        for scope, rb in self.scope_buttons.items():
            if rb.isChecked():
                return scope
        return SCOPE_OPTIONS[0]

    def _selected_columns(self) -> List[str]:
        cols: List[str] = []
        for i in range(self.columns_list.count()):
            item = self.columns_list.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                cols.append(item.text())
        return cols

    def _selected_manual_items(self) -> List[str]:
        return [item.text() for item in self.manual_list.selectedItems()]

    def _build_config(self) -> Dict[str, Any]:
        return {
            "format": self._selected_format(),
            "scope": self._selected_scope(),
            "columns": self._selected_columns(),
            "output_path": self.filename_edit.text().strip(),
            "manual_items": self._selected_manual_items(),
            "data": self._data,
            "open_folder": self.open_folder_check.isChecked(),
        }

    def _on_export(self) -> None:
        config = self._build_config()
        if not config["output_path"]:
            QMessageBox.warning(self, "Output path required", "Please choose an output file.")
            return
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)

        try:
            from utils.workers import Worker  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("utils.workers.Worker unavailable, running sync: %s", exc)
            Worker = None  # type: ignore

        def _work() -> Any:
            return self._invoke_exporter(config)

        if Worker is None:
            try:
                path = _work()
                self._on_export_finished(path, config)
            except Exception as exc:  # noqa: BLE001
                self._on_export_error(str(exc))
            return

        self._worker = Worker(_work)
        for sig_name, slot in (
            ("progress", self.progress_bar.setValue),
            ("result", lambda p: self._on_export_finished(p, config)),
            ("error", self._on_export_error),
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
            self._on_export_error(str(exc))

    def _invoke_exporter(self, config: Dict[str, Any]) -> str:
        """Dispatch to the appropriate ``reporting.*`` exporter (lazy import)."""
        fmt = config["format"].lower()
        data = config["data"]
        path = config["output_path"]
        columns = config["columns"]
        try:
            if fmt == "csv":
                from reporting.csv_export import CSVExporter
                gen = CSVExporter()
                return gen.export(data, path, columns=columns)
            if fmt == "json":
                import json as _json
                with open(path, "w", encoding="utf-8") as fh:
                    _json.dump(data, fh, ensure_ascii=False, indent=2)
                return path
            if fmt == "bibtex":
                from reporting.bibtex_export import BibtexExporter
                gen = BibtexExporter()
                return gen.export(data, path)
            if fmt == "ris":
                from reporting.bibtex_export import RisExporter
                gen = RisExporter()
                return gen.export(data, path)
            if fmt == "excel":
                import pandas as pd
                df = pd.DataFrame(data) if data is not None else pd.DataFrame()
                df.to_excel(path, index=False)
                return path
            if fmt == "parquet":
                import pandas as pd
                df = pd.DataFrame(data) if data is not None else pd.DataFrame()
                df.to_parquet(path, index=False)
                return path
        except Exception as exc:  # noqa: BLE001
            logger.error("Export failed: %s", exc)
            raise
        return path

    def _on_export_finished(self, path: Any, config: Dict[str, Any]) -> None:
        self.progress_bar.setValue(100)
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        path_str = str(path)
        QMessageBox.information(self, "Done", f"Exported to:\n{path_str}")
        self.export_finished.emit(path_str)
        if config.get("open_folder"):
            self._open_folder(path_str)
        self.accept()

    def _on_export_error(self, err: Any) -> None:
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        logger.error("Export error: %s", err)
        QMessageBox.critical(self, "Error", f"Export failed:\n{err}")

    def _open_folder(self, path: str) -> None:
        """Open the file's containing folder in the OS file explorer."""
        folder = os.path.dirname(os.path.abspath(path))
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", folder], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not open folder %s: %s", folder, exc)

    # ----------------------------------------------------------- Public API

    def set_manual_items(self, items: List[str]) -> None:
        """Populate the manual selection list with display items."""
        self.manual_list.clear()
        for it in items:
            self.manual_list.addItem(QListWidgetItem(it))

    def set_available_columns(self, columns: List[str]) -> None:
        """Replace the columns available in step 3."""
        self.columns_list.clear()
        for col in columns:
            item = QListWidgetItem(col)
            item.setCheckState(Qt.CheckState.Checked)
            self.columns_list.addItem(item)

    def get_config(self) -> Dict[str, Any]:
        """Return the full export configuration chosen by the user."""
        return self._build_config()
