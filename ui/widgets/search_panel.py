"""Multi-source academic search panel with debounced autocomplete, filters, and result cards.

Provides :class:`SearchPanel` — a widget that orchestrates queries against the
``data_acquisition.scraping_engine.ScrapingEngine`` across arXiv, PubMed,
OpenAlex, Semantic Scholar, Google Scholar, Crossref, DBLP and ORCID. Emits
``results_ready`` with the aggregated scraper result once a search finishes.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from qtpy.QtCore import Qt, QTimer, Signal, QStringListModel
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Academic sources presented in the multi-select row.
SUPPORTED_SOURCES: List[str] = [
    "arXiv",
    "PubMed",
    "OpenAlex",
    "Semantic Scholar",
    "Google Scholar",
    "Crossref",
    "DBLP",
    "ORCID",
]

# Common fields-of-study shown in the filter dropdown.
FIELDS_OF_STUDY: List[str] = [
    "Computer Science",
    "Medicine",
    "Biology",
    "Chemistry",
    "Physics",
    "Mathematics",
    "Social Sciences",
    "Engineering",
    "Economics",
    "Psychology",
]

# Built-in suggestion seeds for query autocomplete.
_AUTOCOMPLETE_SEEDS: List[str] = [
    "machine learning", "deep learning", "neural networks",
    "natural language processing", "computer vision",
    "large language models", "transformer architecture",
    "reinforcement learning", "graph neural networks",
    "federated learning", "causal inference", "knowledge graph",
    "scientific reproducibility", "open science",
    "bibliometric analysis", "research collaboration networks",
    "climate change", "quantum computing", "CRISPR",
    "COVID-19", "drug discovery", "single-cell genomics",
]

# Default debounce delay (ms) for the query autocomplete.
AUTOCOMPLETE_DEBOUNCE_MS: int = 250


class ResultCard(QFrame):
    """A single search-result card showing metadata + an 'Add to Project' button."""

    add_to_project = Signal(dict)

    def __init__(self, result: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        """Initialize the card with a result record dict."""
        super().__init__(parent)
        self._result = result
        self.setObjectName("ResultCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        title = self._result.get("title", "(untitled)")
        title_label = QLabel(f"<b>{title}</b>")
        title_label.setWordWrap(True)
        title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(title_label)

        # Authors + year + source badge + citations
        meta_hbox = QHBoxLayout()
        authors = self._result.get("authors") or []
        if isinstance(authors, list):
            authors_str = ", ".join(str(a) for a in authors[:5])
            if len(authors) > 5:
                authors_str += f" (+{len(authors) - 5})"
        else:
            authors_str = str(authors)
        year = self._result.get("year", "")
        meta_label = QLabel(f"{authors_str}  •  {year}")
        meta_label.setStyleSheet("color:#888;")
        meta_label.setWordWrap(True)
        meta_hbox.addWidget(meta_label, stretch=1)

        source = self._result.get("source", "")
        if source:
            source_badge = QLabel(str(source))
            source_badge.setStyleSheet(
                "background-color:#007acc;color:white;padding:2px 8px;border-radius:8px;"
            )
            meta_hbox.addWidget(source_badge)

        citations = self._result.get("citations")
        if citations not in (None, ""):
            cit_label = QLabel(f"★ {citations}")
            cit_label.setStyleSheet("color:#ffc66d;font-weight:bold;")
            meta_hbox.addWidget(cit_label)
        layout.addLayout(meta_hbox)

        # Abstract preview (truncated)
        abstract = self._result.get("abstract", "")
        if abstract:
            preview = (abstract[:240] + "…") if len(abstract) > 240 else abstract
            abs_label = QLabel(preview)
            abs_label.setWordWrap(True)
            abs_label.setStyleSheet("color:#aaa;font-size:11px;")
            layout.addWidget(abs_label)

        action_hbox = QHBoxLayout()
        action_hbox.addStretch()
        add_btn = QPushButton("Add to Project")
        add_btn.clicked.connect(lambda: self.add_to_project.emit(self._result))
        action_hbox.addWidget(add_btn)
        layout.addLayout(action_hbox)

    @property
    def result(self) -> Dict[str, Any]:
        """Return the underlying result dict."""
        return self._result


class SearchPanel(QWidget):
    """Multi-source academic search panel.

    Provides:
      * Query input with debounced (250 ms) autocomplete.
      * Source multi-select checkboxes.
      * Filters row: year range, field-of-study, type, open-access-only.
      * Max-results slider (10–500).
      * Collapsible "Advanced" section for per-source-specific filters.
      * Results list of :class:`ResultCard` widgets.
      * Progress bar + status label + Cancel button.

    Emits ``results_ready`` with the aggregated scraper result object once a
    search completes. Uses ``data_acquisition.scraping_engine.ScrapingEngine``
    via lazy import, executed on a background ``utils.workers.Worker``.
    """

    results_ready = Signal(object)
    search_started = Signal(dict)
    search_finished = Signal()
    add_to_project = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Construct the panel and wire internal signals."""
        super().__init__(parent)
        self._engine: Optional[Any] = None
        self._autocomplete_timer: Optional[QTimer] = None
        self._search_task: Optional[Any] = None
        self._cancel_requested: bool = False
        self._all_results: List[Dict[str, Any]] = []

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # Query row
        query_row = QHBoxLayout()
        self.query_input = QLineEdit()
        self.query_input.setPlaceholderText("Search across academic sources…")
        self.query_input.setClearButtonEnabled(True)
        self._completer = QCompleter([], self.query_input)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.query_input.setCompleter(self._completer)
        query_row.addWidget(self.query_input, stretch=1)

        self.search_button = QPushButton("Search")
        self.search_button.setObjectName("PrimaryButton")
        query_row.addWidget(self.search_button)

        self.advanced_toggle = QPushButton("Advanced ▸")
        self.advanced_toggle.setCheckable(True)
        query_row.addWidget(self.advanced_toggle)
        outer.addLayout(query_row)

        # Sources multi-select
        sources_box = QGroupBox("Sources")
        sources_grid = QGridLayout(sources_box)
        sources_grid.setContentsMargins(8, 6, 8, 6)
        self.source_checks: Dict[str, QCheckBox] = {}
        for i, src in enumerate(SUPPORTED_SOURCES):
            cb = QCheckBox(src)
            cb.setChecked(src in ("arXiv", "OpenAlex", "Semantic Scholar"))
            self.source_checks[src] = cb
            sources_grid.addWidget(cb, i // 4, i % 4)
        outer.addWidget(sources_box)

        # Filters row
        filters_box = QGroupBox("Filters")
        fgrid = QGridLayout(filters_box)
        fgrid.setContentsMargins(8, 6, 8, 6)
        fgrid.setColumnStretch(4, 1)

        fgrid.addWidget(QLabel("Year from:"), 0, 0)
        self.year_from = QSpinBox()
        self.year_from.setRange(1900, 2100)
        self.year_from.setValue(2000)
        fgrid.addWidget(self.year_from, 0, 1)

        fgrid.addWidget(QLabel("Year to:"), 0, 2)
        self.year_to = QSpinBox()
        self.year_to.setRange(1900, 2100)
        self.year_to.setValue(2100)
        fgrid.addWidget(self.year_to, 0, 3)

        fgrid.addWidget(QLabel("Type:"), 1, 0)
        self.type_combo = QComboBox()
        self.type_combo.addItems(
            ["Any", "Journal Article", "Conference Paper", "Preprint",
             "Book", "Thesis", "Dataset"]
        )
        fgrid.addWidget(self.type_combo, 1, 1)

        fgrid.addWidget(QLabel("Fields:"), 1, 2)
        self.fields_combo = QComboBox()
        self.fields_combo.addItems(["All fields"] + FIELDS_OF_STUDY)
        fgrid.addWidget(self.fields_combo, 1, 3)

        self.oa_only = QCheckBox("Open Access only")
        fgrid.addWidget(self.oa_only, 1, 4)

        fgrid.addWidget(QLabel("Max results:"), 2, 0)
        max_row = QHBoxLayout()
        self.max_slider = QSlider(Qt.Orientation.Horizontal)
        self.max_slider.setRange(10, 500)
        self.max_slider.setValue(50)
        self.max_label = QLabel("50")
        self.max_label.setMinimumWidth(36)
        self.max_slider.valueChanged.connect(
            lambda v: self.max_label.setText(str(v))
        )
        max_row.addWidget(self.max_slider, stretch=1)
        max_row.addWidget(self.max_label)
        fgrid.addLayout(max_row, 2, 1, 1, 4)
        outer.addWidget(filters_box)

        # Collapsible Advanced section (per-source filters)
        self.advanced_box = QGroupBox("Advanced (per-source filters)")
        self.advanced_box.setVisible(False)
        adv_layout = QVBoxLayout(self.advanced_box)
        adv_layout.addWidget(QLabel("Source-specific options (JSON):"))
        self.advanced_editor = QPlainTextEdit()
        self.advanced_editor.setPlaceholderText(
            '{"arXiv": {"categories": ["cs.AI"]}, "PubMed": {"mesh": ["Neoplasms"]}}'
        )
        self.advanced_editor.setMaximumHeight(80)
        adv_layout.addWidget(self.advanced_editor)
        outer.addWidget(self.advanced_box)

        # Results
        results_box = QGroupBox("Results")
        results_layout = QVBoxLayout(results_box)
        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._results_container = QWidget()
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setContentsMargins(4, 4, 4, 4)
        self._results_layout.setSpacing(8)
        self._results_layout.addStretch()
        self.results_scroll.setWidget(self._results_container)
        results_layout.addWidget(self.results_scroll)
        outer.addWidget(results_box, stretch=1)

        # Bottom: progress + status + cancel
        bottom_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.status_label = QLabel("Idle")
        self.status_label.setStyleSheet("color:#888;")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        bottom_row.addWidget(self.progress_bar, stretch=2)
        bottom_row.addWidget(self.status_label, stretch=1)
        bottom_row.addWidget(self.cancel_button)
        outer.addLayout(bottom_row)

    def _connect_signals(self) -> None:
        """Wire widget signals to slots."""
        self.search_button.clicked.connect(self._on_search)
        self.cancel_button.clicked.connect(self._on_cancel)
        self.advanced_toggle.toggled.connect(self._on_advanced_toggle)
        self.query_input.textEdited.connect(self._on_query_edited)

    # ----------------------------------------------------------- Autocomplete

    def _on_query_edited(self, _text: str) -> None:
        if self._autocomplete_timer is None:
            self._autocomplete_timer = QTimer(self)
            self._autocomplete_timer.setSingleShot(True)
            self._autocomplete_timer.timeout.connect(self._refresh_completer)
        self._autocomplete_timer.start(AUTOCOMPLETE_DEBOUNCE_MS)

    def _refresh_completer(self) -> None:
        text = self.query_input.text().strip()
        if len(text) < 2:
            return
        suggestions = self._suggest_terms(text)
        model = self._completer.model()
        if not isinstance(model, QStringListModel):
            model = QStringListModel(suggestions, self._completer)
            self._completer.setModel(model)
        else:
            model.setStringList(suggestions)

    def _suggest_terms(self, text: str) -> List[str]:
        """Local suggestion list based on built-in seeds."""
        low = text.lower()
        return [s for s in _AUTOCOMPLETE_SEEDS if s.startswith(low)][:8]

    # --------------------------------------------------------------- Advanced

    def _on_advanced_toggle(self, checked: bool) -> None:
        self.advanced_box.setVisible(checked)
        self.advanced_toggle.setText("Advanced ▾" if checked else "Advanced ▸")

    # --------------------------------------------------------------- Search

    def _selected_sources(self) -> List[str]:
        return [name for name, cb in self.source_checks.items() if cb.isChecked()]

    def _build_query(self) -> Dict[str, Any]:
        return {
            "query": self.query_input.text().strip(),
            "sources": self._selected_sources(),
            "year_from": self.year_from.value(),
            "year_to": self.year_to.value(),
            "type": self.type_combo.currentText(),
            "field": self.fields_combo.currentText(),
            "open_access_only": self.oa_only.isChecked(),
            "max_results": self.max_slider.value(),
            "advanced": self._parse_advanced_editor(),
        }

    def _parse_advanced_editor(self) -> Dict[str, Any]:
        raw = self.advanced_editor.toPlainText().strip()
        if not raw:
            return {}
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except Exception as exc:  # noqa: BLE001
            logger.warning("Advanced filters JSON parse error: %s", exc)
        return {}

    def _on_search(self) -> None:
        query = self.query_input.text().strip()
        if not query:
            self.status_label.setText("Please enter a query.")
            return
        if not self._selected_sources():
            self.status_label.setText("Please select at least one source.")
            return
        self._cancel_requested = False
        self._all_results.clear()
        self._clear_results()
        self.progress_bar.setValue(0)
        self.search_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.search_started.emit(self._build_query())
        self._launch_search_worker()

    def _get_engine(self) -> Any:
        if self._engine is None:
            try:
                from data_acquisition.scraping_engine import ScrapingEngine
                self._engine = ScrapingEngine()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ScrapingEngine not available: %s", exc)
                self._engine = None
        return self._engine

    def _launch_search_worker(self) -> None:
        """Build and start a background Worker for the scraping task.

        Falls back to a synchronous call if ``utils.workers.Worker`` is not
        available (e.g. minimal environments used by import tests).
        """
        engine = self._get_engine()
        query_dict = self._build_query()
        if engine is None:
            self.status_label.setText("Search engine unavailable.")
            self.search_button.setEnabled(True)
            self.cancel_button.setEnabled(False)
            return

        try:
            from utils.workers import Worker  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("utils.workers.Worker not available, running sync: %s", exc)
            Worker = None  # type: ignore

        def _do_search() -> Any:
            return engine.search(
                query=query_dict["query"],
                sources=query_dict["sources"],
                year_range=(query_dict["year_from"], query_dict["year_to"]),
                max_results=query_dict["max_results"],
                open_access_only=query_dict["open_access_only"],
                advanced=query_dict["advanced"],
            )

        if Worker is None:
            try:
                self._on_search_complete(_do_search())
            except Exception as exc:  # noqa: BLE001
                self._on_search_error(str(exc))
            return

        self._search_task = Worker(_do_search)
        for sig_name, slot in (
            ("progress", self._on_progress),
            ("finished", lambda *_: self._on_search_complete(None)),
            ("error", self._on_search_error),
            ("result", self._on_search_complete),
        ):
            sig = getattr(self._search_task, sig_name, None)
            if sig is not None:
                try:
                    sig.connect(slot)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Could not connect %s: %s", sig_name, exc)
        try:
            self._search_task.start()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to start search worker: %s", exc)
            self._on_search_error(str(exc))

    # ------------------------------------------------------ Progress / finish

    def _on_progress(self, value: Any) -> None:
        if isinstance(value, int):
            self.progress_bar.setValue(value)
        elif isinstance(value, (tuple, list)) and value:
            cur = value[0]
            total = value[1] if len(value) > 1 else 0
            src = value[2] if len(value) > 2 else ""
            pct = int(100 * cur / total) if total else 0
            self.progress_bar.setValue(pct)
            if src:
                self.status_label.setText(f"Scraping {src} ({cur}/{total})…")
        if self._cancel_requested and self._search_task is not None:
            cancel_fn = getattr(self._search_task, "cancel", None)
            if callable(cancel_fn):
                cancel_fn()

    def _on_search_complete(self, result: Any) -> None:
        self.search_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.setValue(100)
        self.status_label.setText("Search complete.")
        results: List[Dict[str, Any]] = []
        if result is None:
            pass
        elif isinstance(result, list):
            results = result
        elif isinstance(result, dict) and "results" in result:
            results = list(result.get("results", []))
        else:
            try:
                results = list(result)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                results = []
        self._all_results = results
        self._populate_results(results)
        self.results_ready.emit(result)
        self.search_finished.emit()

    def _on_search_error(self, err: Any) -> None:
        self.search_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        msg = str(err)
        logger.error("Search failed: %s", msg)
        self.status_label.setText(f"Error: {msg}")

    def _on_cancel(self) -> None:
        self._cancel_requested = True
        if self._search_task is not None:
            cancel_fn = getattr(self._search_task, "cancel", None)
            if callable(cancel_fn):
                cancel_fn()
        self.status_label.setText("Canceling…")

    # ------------------------------------------------------------- Results UI

    def _clear_results(self) -> None:
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _populate_results(self, results: List[Dict[str, Any]]) -> None:
        self._clear_results()
        if not results:
            empty = QLabel("No results found.")
            empty.setStyleSheet("color:#888;padding:8px;")
            self._results_layout.insertWidget(0, empty)
            return
        for i, res in enumerate(results):
            card = ResultCard(res)
            card.add_to_project.connect(self.add_to_project.emit)
            self._results_layout.insertWidget(i, card)
        self.status_label.setText(f"{len(results)} results.")

    # ------------------------------------------------------------- Public API

    def set_results(self, results: List[Dict[str, Any]]) -> None:
        """Directly populate the results panel without running a search."""
        self._all_results = list(results)
        self._populate_results(results)
        self.results_ready.emit(results)

    @property
    def results(self) -> List[Dict[str, Any]]:
        """Return cached result list (read-only copy)."""
        return list(self._all_results)
