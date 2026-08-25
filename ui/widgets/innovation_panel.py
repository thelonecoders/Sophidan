"""Innovation & frontier exploration widget.

Provides :class:`InnovationPanel` — a four-quadrant Qt interface to
the v2.0.0 :mod:`innovation` package:

* Top: four stat cards (Top Burst Paper, Emerging Topic, Top Novelty
  Score, Forecast Confidence).
* Left: tab list (Citation Bursts / Knowledge Frontiers / Trend Forecast
  / Paper Recommendations / Collaboration Recommendations / Novelty
  Scores / Research Directions).
* Center: visualization area (changes per tab — timeline for bursts,
  scatter for frontiers, line+forecast for trends, ranked list for
  recommendations).
* Right: detail panel for the selected item.
* Bottom: Refresh Analysis + Export Insights buttons.

Every heavy dep is lazy-imported.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QSplitter,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)

__all__ = ["InnovationPanel"]


_TABS: List[str] = [
    "Citation Bursts", "Knowledge Frontiers", "Trend Forecast",
    "Paper Recommendations", "Collaboration Recommendations",
    "Novelty Scores", "Research Directions",
]


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (font fallback + unicode minus)."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


class _StatCard(QFrame):
    """Tiny stat card showing a caption + value."""

    def __init__(self, label: str, value: str = "—", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        self._value_label = QLabel(value)
        f = self._value_label.font()
        f.setPointSize(14)
        f.setBold(True)
        self._value_label.setFont(f)
        self._value_label.setAlignment(Qt.AlignCenter)
        self._caption = QLabel(label)
        self._caption.setAlignment(Qt.AlignCenter)
        cf = self._caption.font()
        cf.setPointSize(8)
        self._caption.setFont(cf)
        lay.addWidget(self._value_label)
        lay.addWidget(self._caption)
        self.setMinimumHeight(60)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_value(self, value: Any) -> None:
        self._value_label.setText(str(value) if value is not None else "—")


class InnovationPanel(QWidget):
    """Innovation & frontier exploration dashboard."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("InnovationPanel")
        self._papers: List[Any] = []
        self._last_bursts: List[Any] = []
        self._last_frontiers: List[Any] = []
        self._last_forecasts: List[Any] = []
        self._last_recommendations: List[Any] = []
        self._last_collabs: List[Any] = []
        self._last_novelties: List[Any] = []
        self._last_directions: List[Any] = []
        self._figure: Any = None
        self._canvas: Any = None
        self._build_ui()

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Top: 4 stat cards.
        cards = QHBoxLayout()
        self.card_burst = _StatCard("Top Burst Paper")
        self.card_frontier = _StatCard("Emerging Topic")
        self.card_novelty = _StatCard("Top Novelty Score")
        self.card_forecast = _StatCard("Forecast Confidence")
        for c in (self.card_burst, self.card_frontier, self.card_novelty, self.card_forecast):
            cards.addWidget(c)
        outer.addLayout(cards)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left: tab selector (using a QListWidget for vertical tab bar).
        left = QGroupBox("Analysis")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 8, 8)
        self.tab_list = QListWidget()
        for t in _TABS:
            QListWidgetItem(t, self.tab_list)
        self.tab_list.setCurrentRow(0)
        self.tab_list.currentRowChanged.connect(self._on_tab_changed)
        left_lay.addWidget(self.tab_list)
        splitter.addWidget(left)

        # Center: visualization area (matplotlib + a list view).
        center = QWidget()
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        self._build_canvas(center_lay)
        self.center_list = QListWidget()
        self.center_list.setAlternatingRowColors(True)
        self.center_list.itemSelectionChanged.connect(self._on_center_select)
        center_lay.addWidget(self.center_list, stretch=1)
        splitter.addWidget(center)

        # Right: detail panel.
        right = QGroupBox("Detail")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 8, 8, 8)
        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        right_lay.addWidget(self.detail_view)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter, stretch=1)

        # Bottom toolbar.
        bottom = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh Analysis")
        self.btn_export = QPushButton("Export Insights")
        self.btn_refresh.setStyleSheet("font-size:12pt; padding:6px 12px;")
        bottom.addWidget(self.btn_refresh)
        bottom.addWidget(self.btn_export)
        bottom.addStretch()
        outer.addLayout(bottom)

        self.btn_refresh.clicked.connect(self._on_refresh)
        self.btn_export.clicked.connect(self._on_export)

    def _build_canvas(self, layout: QVBoxLayout) -> None:
        _configure_matplotlib()
        try:
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
            self._figure = plt.Figure(constrained_layout=True, figsize=(6, 4))
            self._canvas = FigureCanvasQTAgg(self._figure)
            self._canvas.setMinimumHeight(200)
            layout.addWidget(self._canvas)
        except Exception as exc:
            logger.warning("matplotlib canvas unavailable: %s", exc)

    # ----------------------------------------------------------------- API
    def set_papers(self, papers: List[Any]) -> None:
        self._papers = list(papers or [])

    # ----------------------------------------------------------------- Slots
    def _on_tab_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(_TABS):
            return
        tab = _TABS[idx]
        self._refresh_center_list(tab)
        self._redraw_canvas(tab)

    def _on_center_select(self) -> None:
        item = self.center_list.currentItem()
        if item is None:
            return
        self.detail_view.setPlainText(item.data(Qt.UserRole) or item.text())

    def _on_refresh(self) -> None:
        """Re-run all innovation analyses on the bound corpus."""
        if not self._papers:
            logger.info("No papers bound — cannot refresh.")
            return
        self._run_bursts()
        self._run_frontiers()
        self._run_forecast()
        self._run_recommendations()
        self._run_collaborations()
        self._run_novelties()
        self._run_directions()
        # Update the top stat cards.
        self._refresh_stat_cards()
        self._on_tab_changed(self.tab_list.currentRow())

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export Insights", "innovation_insights.json",
                                              "JSON (*.json)")
        if not path:
            return
        payload = {
            "bursts": [b.to_dict() if hasattr(b, "to_dict") else dict(b) for b in self._last_bursts],
            "frontiers": [f.to_dict() if hasattr(f, "to_dict") else dict(f) for f in self._last_frontiers],
            "forecasts": [f.to_dict() if hasattr(f, "to_dict") else dict(f) for f in self._last_forecasts],
            "recommendations": [r.to_dict() if hasattr(r, "to_dict") else dict(r) for r in self._last_recommendations],
            "collaborations": [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in self._last_collabs],
            "novelties": [n.to_dict() if hasattr(n, "to_dict") else dict(n) for n in self._last_novelties],
            "directions": [d.to_dict() if hasattr(d, "to_dict") else dict(d) for d in self._last_directions],
        }
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)
            logger.info("Innovation insights saved to %s", path)
        except OSError:
            logger.exception("Export insights failed.")

    # ----------------------------------------------------------------- Analyses
    def _run_bursts(self) -> None:
        try:
            from innovation.citation_bursts import CitationBurstDetector
            det = CitationBurstDetector()
            self._last_bursts = list(det.detect_papers(self._papers))
        except Exception as exc:
            logger.exception("Citation bursts failed: %s", exc)
            self._last_bursts = []

    def _run_frontiers(self) -> None:
        try:
            from innovation.frontier_mapping import KnowledgeFrontier
            kf = KnowledgeFrontier(self._papers)
            self._last_frontiers = list(kf.compute_frontier())
        except Exception as exc:
            logger.exception("Frontier mapping failed: %s", exc)
            self._last_frontiers = []

    def _run_forecast(self) -> None:
        try:
            from innovation.trend_forecasting import TrendForecaster
            tf = TrendForecaster(self._papers)
            self._last_forecasts = list(tf.forecast_all_topics(top_n=5))
        except Exception as exc:
            logger.exception("Trend forecasting failed: %s", exc)
            self._last_forecasts = []

    def _run_recommendations(self) -> None:
        try:
            from innovation.paper_recommendation import PaperRecommender
            rec = PaperRecommender(self._papers)
            rec.index_papers()
            self._last_recommendations = list(rec.recommend_trending(top_k=20))
        except Exception as exc:
            logger.exception("Paper recommendation failed: %s", exc)
            self._last_recommendations = []

    def _run_collaborations(self) -> None:
        try:
            from innovation.collaboration_recommendation import CollaborationRecommender
            rec = CollaborationRecommender(self._papers)
            authors = rec.authors()[:5]
            results = []
            for a in authors:
                results.extend(rec.recommend_collaborators(a, top_k=5))
            self._last_collabs = results
        except Exception as exc:
            logger.exception("Collaboration recommendation failed: %s", exc)
            self._last_collabs = []

    def _run_novelties(self) -> None:
        try:
            from innovation.novelty_scoring import NoveltyScorer
            scorer = NoveltyScorer(self._papers)
            self._last_novelties = list(scorer.rank_novel_papers(top_n=20))
        except Exception as exc:
            logger.exception("Novelty scoring failed: %s", exc)
            self._last_novelties = []

    def _run_directions(self) -> None:
        try:
            from innovation.research_directions import ResearchDirectionRecommender
            rec = ResearchDirectionRecommender(self._papers)
            self._last_directions = list(rec.recommend_directions(topic="", count=10))
        except Exception as exc:
            logger.exception("Research directions failed: %s", exc)
            self._last_directions = []

    # ----------------------------------------------------------------- Helpers
    def _refresh_center_list(self, tab: str) -> None:
        self.center_list.clear()
        items: List[Any] = []
        if tab == "Citation Bursts":
            items = self._last_bursts
        elif tab == "Knowledge Frontiers":
            items = self._last_frontiers
        elif tab == "Trend Forecast":
            items = self._last_forecasts
        elif tab == "Paper Recommendations":
            items = self._last_recommendations
        elif tab == "Collaboration Recommendations":
            items = self._last_collabs
        elif tab == "Novelty Scores":
            items = self._last_novelties
        elif tab == "Research Directions":
            items = self._last_directions
        for it in items[:50]:
            label = self._summarize(it)
            list_item = QListWidgetItem(label)
            try:
                list_item.setData(Qt.UserRole, it.to_dict().__str__() if hasattr(it, "to_dict") else str(it))
            except Exception:
                list_item.setData(Qt.UserRole, str(it))
            self.center_list.addItem(list_item)

    @staticmethod
    def _summarize(item: Any) -> str:
        """Best-effort one-line summary of an innovation result object."""
        name = getattr(item, "entity_name", None) or getattr(item, "title", None) or getattr(item, "topic", None) or "?"
        score = getattr(item, "strength", None) or getattr(item, "novelty_score", None) or getattr(item, "r2", None)
        if score is None:
            return str(name)
        try:
            return f"{name} — score={float(score):.3f}"
        except (TypeError, ValueError):
            return f"{name} — {score}"

    def _redraw_canvas(self, tab: str) -> None:
        if self._canvas is None or self._figure is None:
            return
        try:
            self._figure.clear()
            ax = self._figure.add_subplot(111)
            ax.set_title(tab)
            ax.text(0.5, 0.5, f"(visualisation for {tab} goes here)",
                    ha="center", va="center", transform=ax.transAxes, alpha=0.6)
            self._canvas.draw_idle()
        except Exception as exc:
            logger.warning("Canvas redraw for %s failed: %s", tab, exc)

    def _refresh_stat_cards(self) -> None:
        if self._last_bursts:
            top_burst = self._last_bursts[0]
            self.card_burst.set_value(getattr(top_burst, "entity_name", "?"))
        if self._last_frontiers:
            self.card_frontier.set_value(getattr(self._last_frontiers[0], "id", "?"))
        if self._last_novelties:
            top = self._last_novelties[0]
            ns = getattr(top, "novelty_score", None)
            self.card_novelty.set_value(f"{float(ns):.3f}" if ns is not None else "?")
        if self._last_forecasts:
            f = self._last_forecasts[0]
            r2 = getattr(f, "r2", None)
            self.card_forecast.set_value(f"{float(r2):.3f}" if r2 is not None else "?")
