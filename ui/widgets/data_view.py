"""Papers table with filtering, sorting, export and lazy DB loading.

The :class:`DataViewWidget` is the primary data-table view of the
Academic Research Suite.  It exposes a top filter bar (free-text search,
year range slider, source multi-select, field select, sort dropdown),
a centred ``QTableView`` backed by a custom :class:`PapersTableModel`
implementation of :class:`QAbstractTableModel`, a right-click context
menu with paper-level actions, and a bottom pagination / export bar.

Pagination uses lazy chunked loading: callers feed papers 100 at a
time via :meth:`add_papers` and the widget surfaces only the current
page to the table model for performance.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import csv
import json
import logging
import os
from typing import Any, Iterable, List, Optional, Sequence

from qtpy.QtCore import (
    QAbstractTableModel, QModelIndex, Qt, Signal,
)
from qtpy.QtWidgets import (
    QAbstractItemView, QAction, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton,
    QSlider, QSpinBox, QStyle, QTableView, QVBoxLayout, QWidget,
    QWidgetAction,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Table model
# ---------------------------------------------------------------------------
class PapersTableModel(QAbstractTableModel):
    """Minimal table model exposing the columns of a paper record.

    The model intentionally copies the rows supplied via
    :meth:`set_papers` so external mutation of the source list cannot
    corrupt the view.
    """

    #: Column headers and their keys into the paper dict.
    COLUMNS: list[tuple[str, str]] = [
        ("Title",     "title"),
        ("Authors",   "authors"),
        ("Year",      "year"),
        ("Source",    "source"),
        ("Citations", "citations"),
        ("DOI",       "doi"),
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._papers: List[dict[str, Any]] = []

    # --- Qt model API --------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._papers)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:  # noqa: D401
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if not (0 <= row < len(self._papers)):
            return None
        paper = self._papers[row]
        key = self.COLUMNS[col][1]
        if role == Qt.DisplayRole:
            value = paper.get(key)
            if value is None:
                return ""
            if key == "authors":
                # Authors may be either a list or a comma-separated string.
                if isinstance(value, (list, tuple)):
                    return ", ".join(str(a) for a in value)
                return str(value)
            if key == "year" and value:
                return str(value)
            if key == "citations" and value is not None:
                try:
                    return f"{int(value):,}"
                except (TypeError, ValueError):
                    return str(value)
            return str(value)
        if role == Qt.UserRole:
            return paper
        if role == Qt.ToolTipRole:
            return str(paper.get("title") or "")
        return None

    def headerData(self, section: int, orientation: int,  # noqa: N802
                  role: int = Qt.DisplayRole) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self.COLUMNS):
            return self.COLUMNS[section][0]
        if orientation == Qt.Vertical:
            return str(section + 1)
        return None

    # --- Public helpers -----------------------------------------------
    def set_papers(self, papers: Sequence[dict[str, Any]]) -> None:
        """Replace the underlying data with a copy of ``papers``."""
        self.beginResetModel()
        self._papers = [dict(p) for p in papers]
        self.endResetModel()

    def add_papers(self, papers: Sequence[dict[str, Any]]) -> None:
        """Append ``papers`` to the model."""
        if not papers:
            return
        start = len(self._papers)
        end = start + len(papers) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._papers.extend(dict(p) for p in papers)
        self.endInsertRows()

    def clear(self) -> None:
        """Drop all rows."""
        self.beginResetModel()
        self._papers = []
        self.endResetModel()

    def get_paper(self, row: int) -> Optional[dict[str, Any]]:
        """Return a shallow copy of the paper at ``row`` or ``None``."""
        if 0 <= row < len(self._papers):
            return dict(self._papers[row])
        return None

    def get_all_papers(self) -> List[dict[str, Any]]:
        """Return shallow copies of all papers currently in the model."""
        return [dict(p) for p in self._papers]

    @property
    def papers(self) -> List[dict[str, Any]]:
        """Internal reference to the underlying list (read-only use)."""
        return self._papers


# ---------------------------------------------------------------------------
# DataView widget
# ---------------------------------------------------------------------------
class DataViewWidget(QWidget):
    """Papers table with filtering, sorting, and export capabilities.

    Signals:
        paper_selected: Emitted with the ``paper_id`` of the row the
            user double-clicked.  ``paper_id`` is read from the paper
            dict's ``id`` (or ``paper_id``) field.
    """

    paper_selected = Signal(int)

    #: Page size used for lazy chunked loading.
    PAGE_SIZE: int = 100

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("DataViewWidget")

        # The full paper set loaded so far (may grow in 100-row chunks).
        self._all_papers: List[dict[str, Any]] = []
        # The currently-visible page (slice of ``_all_papers``).
        self._page_offset: int = 0
        self._model = PapersTableModel(self)
        self._available_sources: List[str] = []
        self._available_fields: List[str] = []
        self._selected_sources: set[str] = set()
        self._current_field: str = ""

        self._build_ui()
        self._update_pagination_label()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # --- Filter bar ----------------------------------------------
        filter_bar = QGridLayout()
        filter_bar.setContentsMargins(0, 0, 0, 0)
        filter_bar.setHorizontalSpacing(8)
        filter_bar.setVerticalSpacing(6)

        self._search_box = QLineEdit(self)
        self._search_box.setPlaceholderText("Search title, author, DOI…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._on_filter_changed)
        filter_bar.addWidget(QLabel("Search:", self), 0, 0)
        filter_bar.addWidget(self._search_box, 0, 1, 1, 3)

        self._year_min = QSpinBox(self)
        self._year_min.setRange(1900, 2100)
        self._year_min.setValue(1900)
        self._year_max = QSpinBox(self)
        self._year_max.setRange(1900, 2100)
        self._year_max.setValue(2100)
        self._year_min.valueChanged.connect(self._on_filter_changed)
        self._year_max.valueChanged.connect(self._on_filter_changed)
        filter_bar.addWidget(QLabel("Year range:", self), 1, 0)
        filter_bar.addWidget(self._year_min, 1, 1)
        filter_bar.addWidget(self._year_max, 1, 2)

        # Source multi-select via a combobox that opens a popup menu.
        self._source_combo = QComboBox(self)
        self._source_combo.addItem("All sources…")
        self._source_combo.currentIndexChanged.connect(self._show_source_popup)
        filter_bar.addWidget(QLabel("Source:", self), 1, 3)
        filter_bar.addWidget(self._source_combo, 1, 4)

        self._field_combo = QComboBox(self)
        self._field_combo.addItem("All fields")
        self._field_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_bar.addWidget(QLabel("Field:", self), 1, 5)
        filter_bar.addWidget(self._field_combo, 1, 6)

        self._sort_combo = QComboBox(self)
        for label, _key in [
            ("Newest first", "-year"),
            ("Oldest first", "+year"),
            ("Most cited", "-citations"),
            ("Title A→Z", "+title"),
        ]:
            self._sort_combo.addItem(label, _key)
        self._sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_bar.addWidget(QLabel("Sort:", self), 1, 7)
        filter_bar.addWidget(self._sort_combo, 1, 8)

        outer.addLayout(filter_bar)

        # --- Table ---------------------------------------------------
        self._table = QTableView(self)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.doubleClicked.connect(self._on_double_clicked)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

        header = self._table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._on_header_context_menu)
        # Reasonable default column widths.
        for col, width in enumerate([320, 200, 70, 110, 80, 180]):
            header.resizeSection(col, width)
        header.setStretchLastSection(False)
        # Hide/show via right-click header menu (built lazily).
        self._hidden_cols: set[int] = set()

        outer.addWidget(self._table, stretch=1)

        # --- Bottom bar: pagination + export -------------------------
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        self._selection_label = QLabel("0 selected", self)
        self._selection_label.setStyleSheet("color: #94A3B8;")
        bottom.addWidget(self._selection_label)

        bottom.addStretch(1)

        self._page_label = QLabel("0–0 of 0", self)
        self._page_label.setStyleSheet("color: #94A3B8;")
        bottom.addWidget(self._page_label)

        self._btn_prev = QPushButton("‹ Prev", self)
        self._btn_prev.setObjectName("GhostBtn")
        self._btn_next = QPushButton("Next ›", self)
        self._btn_next.setObjectName("GhostBtn")
        self._btn_prev.clicked.connect(self._prev_page)
        self._btn_next.clicked.connect(self._next_page)
        bottom.addWidget(self._btn_prev)
        bottom.addWidget(self._btn_next)

        bottom.addSpacing(12)

        self._btn_csv = QPushButton("CSV", self)
        self._btn_bibtex = QPushButton("BibTeX", self)
        self._btn_json = QPushButton("JSON", self)
        self._btn_csv.clicked.connect(lambda: self._export("csv"))
        self._btn_bibtex.clicked.connect(lambda: self._export("bibtex"))
        self._btn_json.clicked.connect(lambda: self._export("json"))
        for btn in (self._btn_csv, self._btn_bibtex, self._btn_json):
            btn.setObjectName("GhostBtn")
            bottom.addWidget(btn)

        outer.addLayout(bottom)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_papers(self, papers: Sequence[dict[str, Any]]) -> None:
        """Replace the entire paper set and reset pagination to page 1."""
        self._all_papers = list(papers)
        self._rebuild_filter_options()
        self._page_offset = 0
        self._refresh_page()

    def add_papers(self, papers: Sequence[dict[str, Any]]) -> None:
        """Append ``papers`` to the dataset (lazy chunked loading).

        If the user is currently on the last page, the new rows are made
        visible immediately; otherwise they are appended silently and
        become visible on the next page navigation.
        """
        new_count = len(papers)
        if new_count == 0:
            return
        prev_total = len(self._all_papers)
        self._all_papers.extend(papers)
        self._rebuild_filter_options()
        # If we were showing the last page previously, re-render so the
        # newly added rows appear without a manual "Next" click.
        max_offset = self._max_offset()
        if self._page_offset >= max_offset:
            self._page_offset = max_offset
        else:
            # Ensure offset is still valid if list shrank unexpectedly.
            self._page_offset = min(self._page_offset, max_offset)
        self._refresh_page()
        logger.debug("Added %d papers (total now %d).", new_count,
                     len(self._all_papers))
        # Suppress unused-variable lint for prev_total in case of strict CI.
        del prev_total

    def clear(self) -> None:
        """Drop all papers and reset the filter state."""
        self._all_papers = []
        self._available_sources = []
        self._available_fields = []
        self._selected_sources = set()
        self._current_field = ""
        self._page_offset = 0
        self._rebuild_filter_options()
        self._refresh_page()

    def get_selected(self) -> List[int]:
        """Return the list of paper ids currently selected in the view."""
        selected_rows = self._table.selectionModel().selectedRows()
        ids: List[int] = []
        for idx in selected_rows:
            paper = self._model.get_paper(idx.row())
            if not paper:
                continue
            pid = paper.get("id", paper.get("paper_id"))
            if pid is None:
                continue
            try:
                ids.append(int(pid))
            except (TypeError, ValueError):
                logger.warning("Skipping paper with non-int id %r", pid)
        return ids

    def get_selected_papers(self) -> List[dict[str, Any]]:
        """Return shallow copies of the currently selected paper records."""
        selected_rows = self._table.selectionModel().selectedRows()
        out: List[dict[str, Any]] = []
        for idx in selected_rows:
            paper = self._model.get_paper(idx.row())
            if paper is not None:
                out.append(paper)
        return out

    def get_all_papers(self) -> List[dict[str, Any]]:
        """Return shallow copies of *all* loaded papers (not just the page)."""
        return [dict(p) for p in self._all_papers]

    # ------------------------------------------------------------------
    # Filtering / pagination internals
    # ------------------------------------------------------------------
    def _rebuild_filter_options(self) -> None:
        """Refresh the source/field combo boxes from the current data."""
        sources = sorted({
            str(p.get("source", "")).strip()
            for p in self._all_papers
            if p.get("source")
        })
        fields = sorted({
            str(p.get("field", "")).strip()
            for p in self._all_papers
            if p.get("field")
        })

        # Update sources combo if changed.
        if sources != self._available_sources:
            self._available_sources = sources
            self._source_combo.blockSignals(True)
            self._source_combo.clear()
            self._source_combo.addItem("All sources…")
            self._source_combo.addItems(sources)
            self._source_combo.blockSignals(False)

        if fields != self._available_fields:
            self._available_fields = fields
            self._field_combo.blockSignals(True)
            self._field_combo.clear()
            self._field_combo.addItem("All fields")
            self._field_combo.addItems(fields)
            self._field_combo.blockSignals(False)

    def _filtered_papers(self) -> List[dict[str, Any]]:
        """Apply the current filter bar settings to ``_all_papers``."""
        q = self._search_box.text().strip().lower()
        y_min = self._year_min.value()
        y_max = self._year_max.value()
        sel_field = self._field_combo.currentText()
        sel_field = "" if sel_field in ("All fields",) else sel_field

        out: List[dict[str, Any]] = []
        for p in self._all_papers:
            try:
                year = int(p.get("year") or 0)
            except (TypeError, ValueError):
                year = 0
            if year and not (y_min <= year <= y_max):
                continue
            if sel_field and str(p.get("field", "")) != sel_field:
                continue
            if self._selected_sources and str(p.get("source", "")) not in self._selected_sources:
                continue
            if q:
                haystack = " ".join(str(p.get(k, "")) for k in
                                     ("title", "authors", "doi", "abstract")).lower()
                if q not in haystack:
                    continue
            out.append(p)

        # Sort.
        sort_key = self._sort_combo.currentData() or "-year"
        reverse = sort_key.startswith("-")
        field = sort_key.lstrip("+-")
        try:
            out.sort(key=lambda x: (x.get(field) is None, x.get(field)),
                     reverse=reverse)
        except TypeError:
            # Heterogeneous types — fall back to string compare.
            out.sort(key=lambda x: str(x.get(field)), reverse=reverse)
        return out

    def _max_offset(self) -> int:
        """Return the maximum valid page offset for the current data."""
        total = len(self._filtered_papers())
        if total == 0:
            return 0
        return ((total - 1) // self.PAGE_SIZE) * self.PAGE_SIZE

    def _refresh_page(self) -> None:
        """Push the current page slice into the table model."""
        filtered = self._filtered_papers()
        total = len(filtered)
        start = self._page_offset
        end = min(start + self.PAGE_SIZE, total)
        page = filtered[start:end] if total else []
        self._model.set_papers(page)
        self._update_pagination_label()
        self._update_selection_label()
        self._btn_prev.setEnabled(start > 0)
        self._btn_next.setEnabled(end < total)

    def _update_pagination_label(self) -> None:
        total = len(self._filtered_papers())
        if total == 0:
            self._page_label.setText("0–0 of 0")
            return
        start = self._page_offset + 1
        end = min(self._page_offset + self.PAGE_SIZE, total)
        self._page_label.setText(f"{start}–{end} of {total:,}")

    def _update_selection_label(self) -> None:
        n = len(self._table.selectionModel().selectedRows()) if self._table.selectionModel() else 0
        self._selection_label.setText(f"{n} selected")

    def _prev_page(self) -> None:
        if self._page_offset > 0:
            self._page_offset = max(0, self._page_offset - self.PAGE_SIZE)
            self._refresh_page()

    def _next_page(self) -> None:
        if self._page_offset < self._max_offset():
            self._page_offset += self.PAGE_SIZE
            self._refresh_page()

    # ------------------------------------------------------------------
    # Filter-bar event handlers
    # ------------------------------------------------------------------
    def _on_filter_changed(self, *args: Any) -> None:
        self._page_offset = 0
        self._refresh_page()

    def _show_source_popup(self, _index: int) -> None:
        """Open a small popup with checkboxes for each source."""
        # Only react to the placeholder "All sources…" entry.
        if self._source_combo.currentIndex() != 0:
            # User picked a single source directly.
            sel = self._source_combo.currentText()
            self._selected_sources = {sel} if sel else set()
            self._source_combo.blockSignals(True)
            self._source_combo.setCurrentIndex(0)
            self._source_combo.blockSignals(False)
            self._on_filter_changed()
            return
        # Build popup menu with checkable actions.
        menu = QMenu(self)
        for src in self._available_sources:
            act = QAction(src, menu)
            act.setCheckable(True)
            act.setChecked(src in self._selected_sources)
            act.toggled.connect(self._on_source_toggled)
            menu.addAction(act)
        menu.exec_(self._source_combo.mapToGlobal(
            self._source_combo.rect().bottomLeft()))

    def _on_source_toggled(self, checked: bool) -> None:
        action = self.sender()
        if action is None:
            return
        src = action.text()
        if checked:
            self._selected_sources.add(src)
        else:
            self._selected_sources.discard(src)
        self._on_filter_changed()

    # ------------------------------------------------------------------
    # Table interactions
    # ------------------------------------------------------------------
    def _on_double_clicked(self, index: QModelIndex) -> None:
        paper = self._model.get_paper(index.row())
        if not paper:
            return
        pid = paper.get("id", paper.get("paper_id"))
        if pid is None:
            logger.debug("Paper has no id; cannot emit paper_selected.")
            return
        try:
            self.paper_selected.emit(int(pid))
        except (TypeError, ValueError):
            logger.warning("Paper id %r is not int-castable; skipping.", pid)

    def _on_context_menu(self, pos: Any) -> None:
        """Build and show the right-click context menu."""
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        menu = QMenu(self)
        act_view = QAction("View Details…", menu)
        act_add_proj = QAction("Add to Project…", menu)
        act_export_sel = QAction("Export Selected…", menu)
        act_cite = QAction("Cite…", menu)
        act_copy_doi = QAction("Copy DOI", menu)
        act_open_url = QAction("Open URL", menu)
        menu.addAction(act_view)
        menu.addSeparator()
        menu.addAction(act_add_proj)
        menu.addAction(act_export_sel)
        menu.addSeparator()
        menu.addAction(act_cite)
        menu.addAction(act_copy_doi)
        menu.addAction(act_open_url)

        act_view.triggered.connect(lambda: self._on_double_clicked(index))
        act_copy_doi.triggered.connect(lambda: self._copy_doi(index))
        act_open_url.triggered.connect(lambda: self._open_url(index))
        act_export_sel.triggered.connect(lambda: self._export("csv"))
        # Add to Project / Cite are no-ops here; the parent window
        # typically hooks into them via signal reflection.
        menu.exec_(self._table.viewport().mapToGlobal(pos))

    def _on_header_context_menu(self, pos: Any) -> None:
        """Allow hiding/showing columns via right-click on the header."""
        header = self._table.horizontalHeader()
        menu = QMenu(self)
        for col, (label, _key) in enumerate(self._model.COLUMNS):
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(col not in self._hidden_cols)
            act.toggled.connect(lambda checked, c=col: self._toggle_column(c, checked))
            menu.addAction(act)
        menu.exec_(header.mapToGlobal(pos))

    def _toggle_column(self, col: int, show: bool) -> None:
        if show:
            self._table.showColumn(col)
            self._hidden_cols.discard(col)
        else:
            self._table.hideColumn(col)
            self._hidden_cols.add(col)

    def _copy_doi(self, index: QModelIndex) -> None:
        paper = self._model.get_paper(index.row())
        if not paper:
            return
        doi = str(paper.get("doi") or "").strip()
        if not doi:
            logger.info("No DOI for the selected paper.")
            return
        from qtpy.QtWidgets import QApplication as _QApp
        cb = _QApp.clipboard()
        if cb is not None:
            cb.setText(doi)
            logger.info("Copied DOI to clipboard: %s", doi)

    def _open_url(self, index: QModelIndex) -> None:
        paper = self._model.get_paper(index.row())
        if not paper:
            return
        url = str(paper.get("url") or "").strip()
        if not url and paper.get("doi"):
            url = f"https://doi.org/{paper['doi']}"
        if not url:
            logger.info("No URL or DOI for the selected paper.")
            return
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:  # pragma: no cover
            logger.exception("Failed to open URL %r", url)

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------
    def _export(self, fmt: str) -> None:
        """Export the selected rows (or all visible rows if none selected)."""
        papers = self.get_selected_papers()
        if not papers:
            papers = self._model.get_all_papers()
        if not papers:
            logger.info("No papers to export.")
            return

        default_name = f"papers.{fmt}"
        if fmt == "csv":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export to CSV", default_name, "CSV Files (*.csv)")
            if path:
                self._write_csv(path, papers)
        elif fmt == "json":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export to JSON", default_name, "JSON Files (*.json)")
            if path:
                self._write_json(path, papers)
        elif fmt == "bibtex":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export to BibTeX", default_name, "BibTeX Files (*.bib)")
            if path:
                self._write_bibtex(path, papers)
        else:
            logger.warning("Unknown export format %r", fmt)

    def _write_csv(self, path: str, papers: Sequence[dict[str, Any]]) -> None:
        keys = ["title", "authors", "year", "source", "citations", "doi", "url"]
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
                writer.writeheader()
                for p in papers:
                    row = dict(p)
                    if isinstance(row.get("authors"), (list, tuple)):
                        row["authors"] = "; ".join(str(a) for a in row["authors"])
                    writer.writerow(row)
            logger.info("Wrote %d papers to %s", len(papers), path)
        except OSError:
            logger.exception("Failed to write CSV to %s", path)

    def _write_json(self, path: str, papers: Sequence[dict[str, Any]]) -> None:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(list(papers), fh, indent=2, default=str)
            logger.info("Wrote %d papers to %s", len(papers), path)
        except OSError:
            logger.exception("Failed to write JSON to %s", path)

    def _write_bibtex(self, path: str, papers: Sequence[dict[str, Any]]) -> None:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for i, p in enumerate(papers, start=1):
                    key = (str(p.get("doi") or "").replace("/", "_")
                           or f"paper{i}")
                    title = str(p.get("title") or "").replace("{", "").replace("}", "")
                    authors = p.get("authors", "")
                    if isinstance(authors, (list, tuple)):
                        authors = " and ".join(str(a) for a in authors)
                    year = p.get("year") or ""
                    venue = p.get("source") or ""
                    doi = p.get("doi") or ""
                    fh.write(f"@misc{{{key},\n")
                    fh.write(f"  title = {{{title}}},\n")
                    fh.write(f"  author = {{{authors}}},\n")
                    fh.write(f"  year = {{{year}}},\n")
                    if venue:
                        fh.write(f"  journal = {{{venue}}},\n")
                    if doi:
                        fh.write(f"  doi = {{{doi}}},\n")
                    fh.write("}\n\n")
            logger.info("Wrote %d papers to %s", len(papers), path)
        except OSError:
            logger.exception("Failed to write BibTeX to %s", path)

    # ------------------------------------------------------------------
    # Selection model hook
    # ------------------------------------------------------------------
    def selectionCommand(self, index: QModelIndex, event: Any = None) -> int:  # noqa: N802
        """Default selection behaviour — kept explicit so subclasses can
        override cleanly."""
        return super().selectionCommand(index, event)  # type: ignore[arg-type]
