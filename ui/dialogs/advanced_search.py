"""Advanced Search dialog.

Provides :class:`AdvancedSearchDialog` — a modal dialog for building complex,
field-specific queries with boolean operators, save/load query presets, and
structured return via :meth:`get_query`.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Field-specifier options for each row.
FIELD_OPTIONS: List[str] = [
    "title contains",
    "abstract contains",
    "author is",
    "year between",
    "year exactly",
    "venue is",
    "keyword",
    "DOI is",
    "ORCID is",
    "full-text contains",
]

# Boolean operators shown on rows after the first.
BOOLEAN_OPERATORS: List[str] = ["AND", "OR", "NOT"]

# Where saved query presets are stored.
PRESETS_DIR: str = os.path.join("data", "advanced_search_presets")


class QueryRowWidget(QWidget):
    """A single row of search criteria with a boolean operator + field + value."""

    removed = Signal(object)

    def __init__(self, is_first_row: bool = False,
                 parent: Optional[QWidget] = None) -> None:
        """Build a query row.

        Args:
            is_first_row: When True the boolean combo is hidden.
        """
        super().__init__(parent)
        self._build_ui(is_first_row)

    def _build_ui(self, is_first_row: bool) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.boolean_combo = QComboBox()
        self.boolean_combo.addItems(BOOLEAN_OPERATORS)
        self.boolean_combo.setVisible(not is_first_row)
        self.boolean_combo.setMinimumWidth(70)
        layout.addWidget(self.boolean_combo)

        self.field_combo = QComboBox()
        self.field_combo.addItems(FIELD_OPTIONS)
        self.field_combo.setMinimumWidth(160)
        layout.addWidget(self.field_combo)

        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("Enter value…")
        layout.addWidget(self.value_input, stretch=1)

        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(lambda: self.removed.emit(self))
        layout.addWidget(self.remove_button)

    def get_data(self) -> Dict[str, str]:
        """Return this row's data as a dict with boolean/field/value keys."""
        return {
            "boolean": self.boolean_combo.currentText() if self.boolean_combo.isVisible() else "",
            "field": self.field_combo.currentText(),
            "value": self.value_input.text().strip(),
        }

    def set_data(self, data: Dict[str, Any]) -> None:
        """Populate this row from a dict."""
        if "boolean" in data and data["boolean"]:
            idx = self.boolean_combo.findText(data["boolean"])
            if idx >= 0:
                self.boolean_combo.setCurrentIndex(idx)
            self.boolean_combo.setVisible(True)
        if "field" in data:
            idx = self.field_combo.findText(data["field"])
            if idx >= 0:
                self.field_combo.setCurrentIndex(idx)
        self.value_input.setText(str(data.get("value", "")))


class AdvancedSearchDialog(QDialog):
    """Modal dialog for building complex, field-specific search queries.

    Emits ``search_started`` with the structured query dict when the user
    clicks Start. The structured query can also be retrieved after accept
    via :meth:`get_query`.
    """

    search_started = Signal(dict)

    def __init__(self, available_scrapers: Optional[List[str]] = None,
                 parent: Optional[QWidget] = None) -> None:
        """Initialize the dialog with a list of source options.

        Args:
            available_scrapers: Source names for the multi-select dropdown.
                Defaults to a sensible multi-source list.
        """
        super().__init__(parent)
        self.setWindowTitle("Advanced Search")
        self.setModal(True)
        self.setMinimumWidth(720)
        self._available_scrapers = available_scrapers or [
            "arXiv", "PubMed", "OpenAlex", "Semantic Scholar",
            "Google Scholar", "Crossref", "DBLP", "ORCID",
        ]
        self._query_rows: List[QueryRowWidget] = []

        self._build_ui()
        self._connect_signals()
        self._add_query_row(is_first_row=True)

    # ------------------------------------------------------ UI

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Top form
        top_form = QFormLayout()
        self.source_combo = QComboBox()
        self.source_combo.addItems(self._available_scrapers)
        top_form.addRow("Source:", self.source_combo)

        self.year_from = QSpinBox()
        self.year_from.setRange(1900, 2100)
        self.year_from.setValue(2000)
        self.year_to = QSpinBox()
        self.year_to.setRange(1900, 2100)
        self.year_to.setValue(2100)
        year_row = QHBoxLayout()
        year_row.addWidget(self.year_from)
        year_row.addWidget(QLabel("to"))
        year_row.addWidget(self.year_to)
        year_row.addStretch()
        year_holder = QWidget()
        year_holder.setLayout(year_row)
        top_form.addRow("Year range:", year_holder)

        self.max_results = QSpinBox()
        self.max_results.setRange(1, 1000)
        self.max_results.setValue(50)
        top_form.addRow("Max results:", self.max_results)
        layout.addLayout(top_form)

        # Query builder scroll area
        layout.addWidget(QLabel("Build Your Query:"))
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rows_layout.setSpacing(6)
        self.scroll_area.setWidget(self.rows_container)
        layout.addWidget(self.scroll_area, stretch=1)

        # Add row + save/load
        row_btns = QHBoxLayout()
        self.add_row_button = QPushButton("+ Add Condition")
        self.save_query_button = QPushButton("Save Query…")
        self.load_query_button = QPushButton("Load Query…")
        row_btns.addWidget(self.add_row_button)
        row_btns.addStretch()
        row_btns.addWidget(self.save_query_button)
        row_btns.addWidget(self.load_query_button)
        layout.addLayout(row_btns)

        # Bottom buttons
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.start_button = QPushButton("Start Advanced Search")
        self.start_button.setObjectName("PrimaryButton")
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.start_button)
        layout.addLayout(bottom)

    def _connect_signals(self) -> None:
        self.add_row_button.clicked.connect(lambda: self._add_query_row(False))
        self.start_button.clicked.connect(self._on_start)
        self.cancel_button.clicked.connect(self.reject)
        self.save_query_button.clicked.connect(self._on_save_query)
        self.load_query_button.clicked.connect(self._on_load_query)

    # ------------------------------------------------------ Row management

    def _add_query_row(self, is_first_row: bool = False) -> None:
        row = QueryRowWidget(is_first_row)
        row.removed.connect(self._remove_query_row)
        self.rows_layout.addWidget(row)
        self._query_rows.append(row)
        for r in self._query_rows[1:]:
            r.boolean_combo.setVisible(True)
        self._validate()

    def _remove_query_row(self, row: QueryRowWidget) -> None:
        if len(self._query_rows) <= 1:
            return
        self.rows_layout.removeWidget(row)
        row.deleteLater()
        self._query_rows.remove(row)
        if self._query_rows:
            self._query_rows[0].boolean_combo.setVisible(False)
        self._validate()

    def _validate(self) -> None:
        valid = any(r.get_data()["value"] for r in self._query_rows)
        self.start_button.setEnabled(valid)

    # ------------------------------------------------------ Start / query

    def _on_start(self) -> None:
        query = self.get_query()
        self.search_started.emit(query)
        self.accept()

    def get_query(self) -> Dict[str, Any]:
        """Return a structured query dict built from the dialog state."""
        conditions: List[Dict[str, str]] = []
        for row in self._query_rows:
            data = row.get_data()
            if data["value"]:
                conditions.append(data)
        return {
            "source": self.source_combo.currentText(),
            "year_from": self.year_from.value(),
            "year_to": self.year_to.value(),
            "max_results": self.max_results.value(),
            "conditions": conditions,
        }

    # ------------------------------------------------------ Save / Load

    def _on_save_query(self) -> None:
        os.makedirs(PRESETS_DIR, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Query Preset", PRESETS_DIR, "JSON files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.get_query(), fh, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Saved", f"Query preset saved to {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save Query", f"Failed: {exc}")

    def _on_load_query(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Query Preset", PRESETS_DIR, "JSON files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Load Query", f"Failed: {exc}")
            return
        self.set_query(data)

    def set_query(self, query: Dict[str, Any]) -> None:
        """Populate the dialog from a structured query dict."""
        # Set source
        idx = self.source_combo.findText(str(query.get("source", "")))
        if idx >= 0:
            self.source_combo.setCurrentIndex(idx)
        self.year_from.setValue(int(query.get("year_from", 2000)))
        self.year_to.setValue(int(query.get("year_to", 2100)))
        self.max_results.setValue(int(query.get("max_results", 50)))
        # Clear current rows
        for row in list(self._query_rows):
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        self._query_rows.clear()
        conditions = query.get("conditions") or []
        if not conditions:
            self._add_query_row(is_first_row=True)
            return
        for i, cond in enumerate(conditions):
            self._add_query_row(is_first_row=(i == 0))
            self._query_rows[-1].set_data(cond)
        if self._query_rows:
            self._query_rows[0].boolean_combo.setVisible(False)
        self._validate()
