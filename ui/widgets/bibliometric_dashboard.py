"""VOSviewer/CiteSpace-style bibliometric dashboard widget.

Provides :class:`BibliometricDashboard` — a full-page widget that exposes
the v2.0.0 ``bibliometrics`` package (Publish-or-Perish indices +
VOSviewer network analyses + CiteSpace burst detection) through a
four-quadrant Qt dashboard:

* Top: metric cards (Total Papers / Total Citations / h-index /
  Avg citations per paper).
* Left: analysis-type selector (bibliographic coupling / co-citation /
  co-authorship / term co-occurrence / citation bursts).
* Center: matplotlib-embedded network visualisation (re-uses
  :class:`gephi_viz.interactive_canvas.InteractiveNetworkCanvas`).
* Right: top-10 papers/authors/journals ranked by citations.
* Bottom: timeline of publications per year.

All heavy dependencies (matplotlib, networkx, the bibliometrics package
itself) are lazy-imported inside ``_run_analysis`` so the widget is
always importable in headless / minimal environments.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, List, Optional

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)


__all__ = ["BibliometricDashboard"]


# Analysis-type identifiers exposed in the left selector.
ANALYSIS_TYPES: List[str] = [
    "Bibliographic Coupling",
    "Co-citation",
    "Co-authorship",
    "Term Co-occurrence",
    "Citation Bursts",
]


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (font fallback + unicode minus)."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


class _MetricCard(QFrame):
    """Small framed card showing a metric value + caption."""

    def __init__(self, label: str, value: str = "—", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        self._value_label = QLabel(value, self)
        f = self._value_label.font()
        f.setPointSize(20)
        f.setBold(True)
        self._value_label.setFont(f)
        self._value_label.setAlignment(Qt.AlignCenter)
        self._caption_label = QLabel(label, self)
        self._caption_label.setAlignment(Qt.AlignCenter)
        cf = self._caption_label.font()
        cf.setPointSize(9)
        self._caption_label.setFont(cf)
        lay.addWidget(self._value_label)
        lay.addWidget(self._caption_label)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value: Any) -> None:
        """Update the displayed metric value (formatted to 2dp for floats)."""
        if isinstance(value, float):
            text = f"{value:,.2f}"
        elif isinstance(value, int):
            text = f"{value:,}"
        else:
            text = str(value) if value is not None else "—"
        self._value_label.setText(text)


class BibliometricDashboard(QWidget):
    """VOSviewer/CiteSpace-style bibliometric analysis dashboard.

    Signals:
        analysis_started(str): Emitted when a background analysis begins.
        analysis_completed(dict): Emitted with the results of the latest
            analysis (an empty dict on failure).
        burst_detected(list): Emitted with a list of detected citation
            bursts (each as a dict).
    """

    analysis_started = Signal(str)
    analysis_completed = Signal(dict)
    burst_detected = Signal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("BibliometricDashboard")
        self._papers: List[Any] = []
        self._last_result: dict = {}
        self._canvas: Any = None
        self._build_ui()

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # --- Top: metric cards --------------------------------------
        cards_row = QHBoxLayout()
        self.card_papers = _MetricCard("Total Papers")
        self.card_citations = _MetricCard("Total Citations")
        self.card_h = _MetricCard("h-index")
        self.card_avg = _MetricCard("Avg Citations / Paper")
        for c in (self.card_papers, self.card_citations, self.card_h, self.card_avg):
            cards_row.addWidget(c)
        outer.addLayout(cards_row)

        # --- Middle: 3-pane splitter (left selector | canvas | right list)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left panel: analysis type + action buttons.
        left = QGroupBox("Analysis Type")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 8, 8)
        self.analysis_combo = QComboBox()
        self.analysis_combo.addItems(ANALYSIS_TYPES)
        left_lay.addWidget(self.analysis_combo)
        left_lay.addSpacing(8)
        self.btn_compute_indices = QPushButton("Compute All Indices")
        self.btn_vos_map = QPushButton("Generate VOS Map")
        self.btn_detect_bursts = QPushButton("Detect Bursts")
        self.btn_export_report = QPushButton("Export Report")
        for b in (self.btn_compute_indices, self.btn_vos_map,
                  self.btn_detect_bursts, self.btn_export_report):
            left_lay.addWidget(b)
        left_lay.addStretch()
        splitter.addWidget(left)

        # Center: interactive network canvas (lazy-constructed).
        center = QFrame()
        center.setObjectName("CanvasHost")
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        self._build_canvas(center_lay)
        splitter.addWidget(center)

        # Right: top-10 papers/authors/journals list.
        right = QGroupBox("Top 10 by Citations")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 8, 8, 8)
        self.top_combo = QComboBox()
        self.top_combo.addItems(["Papers", "Authors", "Journals"])
        right_lay.addWidget(self.top_combo)
        self.top_list = QListWidget()
        self.top_list.setAlternatingRowColors(True)
        right_lay.addWidget(self.top_list, stretch=1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter, stretch=1)

        # --- Bottom: timeline chart host -----------------------------
        bottom = QGroupBox("Publications per Year")
        bottom_lay = QVBoxLayout(bottom)
        bottom_lay.setContentsMargins(8, 8, 8, 8)
        self._timeline_figure: Any = None
        self._timeline_canvas: Any = None
        self._build_timeline(bottom_lay)
        outer.addWidget(bottom, stretch=0)

        # --- Connect signals ---------------------------------------
        self.btn_compute_indices.clicked.connect(self._on_compute_indices)
        self.btn_vos_map.clicked.connect(self._on_vos_map)
        self.btn_detect_bursts.clicked.connect(self._on_detect_bursts)
        self.btn_export_report.clicked.connect(self._on_export_report)
        self.top_combo.currentIndexChanged.connect(self._refresh_top_list)

    def _build_canvas(self, layout: QVBoxLayout) -> None:
        """Lazily instantiate the :class:`InteractiveNetworkCanvas`."""
        try:
            from gephi_viz.interactive_canvas import InteractiveNetworkCanvas
            self._canvas = InteractiveNetworkCanvas(self)
            layout.addWidget(self._canvas)
        except Exception as exc:
            logger.warning("InteractiveNetworkCanvas unavailable: %s", exc)
            placeholder = QLabel(
                f"\U0001F5FA  Network canvas unavailable.\n({exc})",
                self,
            )
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color:#94A3B8;")
            layout.addWidget(placeholder)

    def _build_timeline(self, layout: QVBoxLayout) -> None:
        _configure_matplotlib()
        try:
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_qt5agg import (
                FigureCanvasQTAgg, NavigationToolbar2QT,
            )
            self._timeline_figure = plt.Figure(constrained_layout=True, figsize=(6, 2.4))
            self._timeline_ax = self._timeline_figure.add_subplot(111)
            self._timeline_canvas = FigureCanvasQTAgg(self._timeline_figure)
            layout.addWidget(self._timeline_canvas)
            try:
                layout.addWidget(NavigationToolbar2QT(self._timeline_canvas, self))
            except Exception as exc:
                logger.debug("NavigationToolbar2QT (timeline) failed: %s", exc)
        except Exception as exc:
            logger.warning("matplotlib timeline unavailable: %s", exc)
            layout.addWidget(QLabel("(matplotlib unavailable for timeline)", self))

    # ----------------------------------------------------------------- API
    def set_papers(self, papers: List[Any]) -> None:
        """Bind a list of ``Paper`` (or duck-typed) objects and refresh cards."""
        self._papers = list(papers or [])
        self._refresh_metric_cards()
        self._refresh_timeline()
        self._refresh_top_list()

    def papers(self) -> List[Any]:
        """Return the currently bound paper corpus."""
        return list(self._papers)

    # ----------------------------------------------------------------- Slots
    def _on_compute_indices(self) -> None:
        """Run ``PoPIndices.compute_all`` on the bound paper corpus."""
        if not self._papers:
            logger.info("No papers bound — cannot compute indices.")
            return
        self.analysis_started.emit("indices")
        try:
            from bibliometrics.pop_indices import PoPIndices
            citations = [
                int(getattr(p, "citations_count", 0) or 0)
                for p in self._papers
            ]
            years = [getattr(p, "year", None) for p in self._papers]
            years = [int(y) for y in years if y] or None
            result = PoPIndices().compute_all(citations, years=years)
            self._last_result = {"indices": result}
            self._refresh_metric_cards(result)
            self.analysis_completed.emit(result)
        except Exception as exc:
            logger.exception("Compute indices failed: %s", exc)
            self.analysis_completed.emit({})

    def _on_vos_map(self) -> None:
        """Build a VOSviewer-style network for the selected analysis type."""
        if not self._papers:
            logger.info("No papers bound — cannot build VOS map.")
            return
        kind = self.analysis_combo.currentText()
        self.analysis_started.emit(f"vos:{kind}")
        try:
            from bibliometrics.vosviewer import VOSAnalyzer
            analyzer = VOSAnalyzer()
            graph = None
            if kind == "Bibliographic Coupling":
                graph = analyzer.bibliographic_coupling(self._papers)
            elif kind == "Co-citation":
                graph = analyzer.co_citation_analysis(self._papers)
            elif kind == "Co-authorship":
                graph = analyzer.co_authorship_analysis(self._papers)
            elif kind == "Term Co-occurrence":
                graph = analyzer.term_co_occurrence(self._papers)
            elif kind == "Citation Bursts":
                # Bursts tab — delegate to the bursts button.
                self._on_detect_bursts()
                return
            if graph is not None and self._canvas is not None:
                self._canvas.set_graph(graph)
            self._last_result["vos_graph"] = kind
            self.analysis_completed.emit({"vos": kind, "nodes": graph.number_of_nodes() if graph else 0})
        except Exception as exc:
            logger.exception("VOS map failed: %s", exc)
            self.analysis_completed.emit({})

    def _on_detect_bursts(self) -> None:
        """Run CiteSpace citation-burst detection over the corpus."""
        if not self._papers:
            logger.info("No papers bound — cannot detect bursts.")
            return
        self.analysis_started.emit("bursts")
        try:
            from bibliometrics.citespace import CiteSpaceAnalyzer
            analyzer = CiteSpaceAnalyzer()
            bursts = analyzer.detect_citation_bursts(self._papers)
            bursts_dicts = []
            try:
                bursts_dicts = [b.to_dict() if hasattr(b, "to_dict") else dict(b) for b in bursts]
            except Exception:
                bursts_dicts = []
            self._last_result["bursts"] = bursts_dicts
            self.burst_detected.emit(bursts_dicts)
            self.analysis_completed.emit({"bursts": len(bursts_dicts)})
            # Show burst summaries in the top-list panel.
            self._populate_top_list([
                f"{b.get('entity_name', b.get('paper_id', '?'))}  "
                f"({b.get('start_year', '?')}–{b.get('end_year', '?')}, "
                f"strength={b.get('strength', 0):.2f})"
                for b in bursts_dicts[:10]
            ])
        except Exception as exc:
            logger.exception("Burst detection failed: %s", exc)
            self.burst_detected.emit([])
            self.analysis_completed.emit({})

    def _on_export_report(self) -> None:
        """Export the latest analysis result as a JSON file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Bibliometric Report",
            "bibliometric_report.json",
            "JSON (*.json);;All Files (*)",
        )
        if not path:
            return
        import json
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self._last_result, fh, indent=2, default=str)
            logger.info("Bibliometric report saved to %s", path)
        except OSError:
            logger.exception("Could not write report to %s", path)

    # ----------------------------------------------------------------- Helpers
    def _refresh_metric_cards(self, indices: Optional[dict] = None) -> None:
        """Update the four metric cards from the bound papers / indices dict."""
        if not self._papers:
            for c in (self.card_papers, self.card_citations, self.card_h, self.card_avg):
                c.set_value("—")
            return
        citations = [int(getattr(p, "citations_count", 0) or 0) for p in self._papers]
        self.card_papers.set_value(len(self._papers))
        total = sum(citations)
        self.card_citations.set_value(total)
        if indices and "h_index" in indices:
            self.card_h.set_value(indices.get("h_index", "—"))
        else:
            # Cheap inline h-index.
            sorted_c = sorted(citations, reverse=True)
            h = next((i + 1 for i, c in enumerate(sorted_c) if c >= i + 1), 0)
            self.card_h.set_value(h)
        avg = total / len(citations) if citations else 0.0
        self.card_avg.set_value(avg)

    def _refresh_timeline(self) -> None:
        """Render a small bar chart of publications per year."""
        if self._timeline_canvas is None or not self._papers:
            return
        try:
            from collections import Counter
            counts = Counter(int(getattr(p, "year", 0) or 0) for p in self._papers if getattr(p, "year", None))
            years = sorted(c for c in counts if c > 0)
            if not years:
                return
            values = [counts[y] for y in years]
            self._timeline_ax.clear()
            self._timeline_ax.bar(years, values, color="#3B82F6")
            self._timeline_ax.set_xlabel("Year")
            self._timeline_ax.set_ylabel("Papers")
            self._timeline_figure.set_constrained_layout(True)
            self._timeline_canvas.draw_idle()
        except Exception as exc:
            logger.warning("Timeline render failed: %s", exc)

    def _refresh_top_list(self, _idx: int = 0) -> None:
        """Re-populate the top-10 list for the selected entity kind."""
        kind = self.top_combo.currentText()
        items: List[str] = []
        try:
            if kind == "Papers":
                ranked = sorted(self._papers, key=lambda p: int(getattr(p, "citations_count", 0) or 0), reverse=True)
                items = [
                    f"{(getattr(p, 'title', '') or '(untitled)')[:60]}  — {getattr(p, 'citations_count', 0)}"
                    for p in ranked[:10]
                ]
            elif kind == "Authors":
                counts: dict = {}
                for p in self._papers:
                    for a in (getattr(p, "authors", None) or []):
                        counts[a] = counts.get(a, 0) + int(getattr(p, "citations_count", 0) or 0)
                items = [f"{a}  — {c}" for a, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]]
            elif kind == "Journals":
                counts = {}
                for p in self._papers:
                    j = getattr(p, "journal", None) or "(unknown)"
                    counts[j] = counts.get(j, 0) + int(getattr(p, "citations_count", 0) or 0)
                items = [f"{j}  — {c}" for j, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]]
        except Exception as exc:
            logger.warning("Top-list refresh failed: %s", exc)
        self._populate_top_list(items)

    def _populate_top_list(self, items: List[str]) -> None:
        """Replace the right-hand list contents with ``items``."""
        self.top_list.clear()
        for it in items:
            QListWidgetItem(it, self.top_list)
