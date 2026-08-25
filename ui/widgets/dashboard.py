"""Dashboard landing widget shown after onboarding.

The :class:`DashboardWidget` presents a 4-card stat row at the top, a
two-column grid in the middle (Recent Activity timeline + Quick
Actions), and a bottom row with the 10 most recently added papers and
a "Trending Topics" word-cloud placeholder.  All cards are styled
``QFrame`` instances with rounded corners and a subtle shadow.

The widget subscribes to ``core.events.EventBus`` lazily: if the
``core.events`` module is not yet available (e.g. it has not been
written by the core agent), the dashboard silently falls back to a
no-op subscription so the UI remains importable in isolation.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
from datetime import datetime
from typing import Any, Iterable, List, Optional, Sequence

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QFont, QColor
from qtpy.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSpacerItem,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QPushButton,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Small UI helpers
# ---------------------------------------------------------------------------
class _StatCard(QFrame):
    """A small card showing a single statistic."""

    def __init__(
        self,
        icon: str,
        title: str,
        value: str,
        trend: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(4)

        top = QHBoxLayout()
        icon_label = QLabel(icon, self)
        icon_font = QFont(icon_label.font())
        icon_font.setPointSize(18)
        icon_label.setFont(icon_font)
        top.addWidget(icon_label)
        top.addStretch(1)
        title_label = QLabel(title, self)
        title_label.setStyleSheet("color: #94A3B8; font-size: 9pt;")
        top.addWidget(title_label)
        top.addStretch(1)
        lay.addLayout(top)

        value_label = QLabel(value, self)
        vfont = QFont(value_label.font())
        vfont.setPointSize(22)
        vfont.setBold(True)
        value_label.setFont(vfont)
        lay.addWidget(value_label)
        self._value_label = value_label

        trend_label = QLabel(trend, self)
        trend_label.setStyleSheet("color: #10B981; font-size: 9pt;")
        lay.addWidget(trend_label)
        self._trend_label = trend_label

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)

    def set_trend(self, trend: str, positive: bool = True) -> None:
        color = "#10B981" if positive else "#EF4444"
        self._trend_label.setText(trend)
        self._trend_label.setStyleSheet(f"color: {color}; font-size: 9pt;")


class _ActionTile(QPushButton):
    """Wide quick-action button used in the right-hand Quick Actions panel."""

    def __init__(self, icon: str, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(f"{icon}   {title}", parent)
        self.setObjectName("PrimaryBtn")
        self.setMinimumHeight(44)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


# ---------------------------------------------------------------------------
# Dashboard widget
# ---------------------------------------------------------------------------
class DashboardWidget(QWidget):
    """Landing-page widget shown right after the welcome screen.

    Signals:
        quick_action: Emitted with the action key when the user clicks
            a Quick Action button.  Keys: ``new_scrape``, ``new_project``,
            ``ask_ai``, ``generate_report``.
    """

    quick_action = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardWidget")

        self._recent_papers: List[dict[str, Any]] = []
        self._trending_topics: List[tuple[str, int]] = []
        self._event_subscriber = None  # type: ignore[var-annotated]

        self._build_ui()
        self._refresh_stat_cards()
        self._subscribe_events()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(14)

        # --- Stat cards row ------------------------------------------
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self._card_papers = _StatCard("\U0001F4DA", "Total Papers", "0")
        self._card_authors = _StatCard("\U0001F465", "Total Authors", "0")
        self._card_projects = _StatCard("\U0001F4C1", "Active Projects", "0")
        self._card_scrape = _StatCard("\U0001F50D", "Last Scrape", "—", "never")
        for card in (self._card_papers, self._card_authors,
                     self._card_projects, self._card_scrape):
            stats_row.addWidget(card)
        outer.addLayout(stats_row)

        # --- Middle two-column grid ----------------------------------
        middle = QHBoxLayout()
        middle.setSpacing(12)

        # Left: Recent Activity timeline.
        left_card = self._make_card("Recent Activity")
        left_lay = left_card.layout()
        self._activity_label = QLabel("No activity yet.", left_card)
        self._activity_label.setWordWrap(True)
        self._activity_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._activity_label.setStyleSheet("color: #94A3B8;")
        left_lay.addWidget(self._activity_label)
        left_lay.addStretch(1)
        middle.addWidget(left_card, stretch=1)

        # Right: Quick Actions buttons.
        right_card = self._make_card("Quick Actions")
        right_lay = right_card.layout()
        self._btn_new_scrape = _ActionTile("\U0001F50D", "New Scrape")
        self._btn_new_project = _ActionTile("\U0001F4C1", "New Project")
        self._btn_ask_ai = _ActionTile("\U0001F916", "Ask AI")
        self._btn_report = _ActionTile("\U0001F4DD", "Generate Report")
        for btn, key in (
            (self._btn_new_scrape, "new_scrape"),
            (self._btn_new_project, "new_project"),
            (self._btn_ask_ai, "ask_ai"),
            (self._btn_report, "generate_report"),
        ):
            btn.clicked.connect(lambda _checked=False, k=key: self.quick_action.emit(k))
            right_lay.addWidget(btn)
        right_lay.addStretch(1)
        middle.addWidget(right_card, stretch=1)

        outer.addLayout(middle, stretch=1)

        # --- Bottom row: recent papers + trending topics --------------
        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        papers_card = self._make_card("Recent Papers")
        papers_lay = papers_card.layout()
        self._papers_table = QTableWidget(0, 4, papers_card)
        self._papers_table.setHorizontalHeaderLabels(["Title", "Authors", "Year", "Source"])
        self._papers_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._papers_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._papers_table.verticalHeader().setVisible(False)
        self._papers_table.horizontalHeader().setStretchLastSection(True)
        papers_lay.addWidget(self._papers_table)
        bottom.addWidget(papers_card, stretch=3)

        trending_card = self._make_card("Trending Topics")
        trending_lay = trending_card.layout()
        self._trending_label = QLabel("No data yet.", trending_card)
        self._trending_label.setWordWrap(True)
        self._trending_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._trending_label.setStyleSheet("color: #94A3B8;")
        trending_lay.addWidget(self._trending_label)
        trending_lay.addStretch(1)
        bottom.addWidget(trending_card, stretch=2)

        outer.addLayout(bottom, stretch=2)

    @staticmethod
    def _make_card(title: str) -> QFrame:
        """Return a styled card frame with a title label and inner VLayout."""
        card = QFrame()
        card.setObjectName("Card")
        card.setFrameShape(QFrame.NoFrame)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        title_lbl = QLabel(title, card)
        tfont = QFont(title_lbl.font())
        tfont.setPointSize(11)
        tfont.setBold(True)
        title_lbl.setFont(tfont)
        lay.addWidget(title_lbl)
        return card

    # ------------------------------------------------------------------
    # Event bus subscription
    # ------------------------------------------------------------------
    def _subscribe_events(self) -> None:
        """Attempt to subscribe to ``core.events.EventBus`` if present."""
        try:  # pragma: no cover — depends on core module written by other agent
            from core.events import EventBus  # type: ignore
        except Exception:
            logger.debug("core.events not available — dashboard will not get live updates.")
            return
        try:
            bus = EventBus.instance() if hasattr(EventBus, "instance") else EventBus()
            # The concrete EventBus API is not yet pinned; we use the
            # commonly-seen ``subscribe(event, handler)`` signature.
            if hasattr(bus, "subscribe"):
                bus.subscribe("paper_added", self._on_paper_added)
                bus.subscribe("scrape_finished", self._on_scrape_finished)
                bus.subscribe("analysis_finished", self._on_analysis_finished)
                bus.subscribe("export_finished", self._on_export_finished)
            self._event_subscriber = bus
            logger.info("Subscribed dashboard to core.events.EventBus.")
        except Exception:  # pragma: no cover — defensive
            logger.exception("Failed to subscribe dashboard to EventBus.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_stats(self, papers: int, authors: int, projects: int,
                  last_scrape: Optional[datetime] = None) -> None:
        """Update the four stat cards with fresh counts.

        Args:
            papers: Total number of papers in the database.
            authors: Total number of distinct authors.
            projects: Number of active projects.
            last_scrape: Timestamp of the last scrape operation, or
                ``None`` if no scrape has been performed yet.
        """
        self._card_papers.set_value(f"{papers:,}")
        self._card_authors.set_value(f"{authors:,}")
        self._card_projects.set_value(f"{projects:,}")
        if last_scrape is None:
            self._card_scrape.set_value("—")
            self._card_scrape.set_trend("never", positive=False)
        else:
            self._card_scrape.set_value(last_scrape.strftime("%Y-%m-%d %H:%M"))
            self._card_scrape.set_trend("latest run", positive=True)

    def set_recent_papers(self, papers: Sequence[dict[str, Any]]) -> None:
        """Populate the Recent Papers table.

        Args:
            papers: At most 10 records, each expected to expose ``title``,
                ``authors``, ``year`` and ``source`` keys.
        """
        self._recent_papers = list(papers)[:10]
        self._papers_table.setRowCount(len(self._recent_papers))
        for row, paper in enumerate(self._recent_papers):
            cells = (
                str(paper.get("title", "")),
                str(paper.get("authors", "")),
                str(paper.get("year", "")),
                str(paper.get("source", "")),
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self._papers_table.setItem(row, col, item)
        self._papers_table.resizeColumnsToContents()

    def set_trending_topics(self, topics: Sequence[tuple[str, int]]) -> None:
        """Render the Trending Topics panel.

        Args:
            topics: Iterable of ``(topic, weight)`` tuples; the top 20
                are rendered as a pseudo word-cloud with font sizes
                proportional to the weight.
        """
        self._trending_topics = list(topics)[:20]
        if not self._trending_topics:
            self._trending_label.setText("No data yet.")
            return
        max_w = max((w for _, w in self._trending_topics), default=1) or 1
        parts: list[str] = []
        for topic, weight in self._trending_topics:
            ratio = max(0.5, weight / max_w)
            size = 10 + int(ratio * 12)
            parts.append(
                f'<span style="font-size:{size}pt;color:#3B82F6;'
                f'font-weight:600;">{topic}</span>'
            )
        self._trending_label.setText("   •   ".join(parts))

    def set_recent_activity(self, items: Sequence[str]) -> None:
        """Replace the Recent Activity timeline text.

        Args:
            items: Iterable of human-readable activity descriptions, most
                recent first.
        """
        if not items:
            self._activity_label.setText("No activity yet.")
            return
        self._activity_label.setText("\n".join(f"• {it}" for it in items))

    # ------------------------------------------------------------------
    # EventBus handlers — defensive: ignore payloads we don't understand.
    # ------------------------------------------------------------------
    def _on_paper_added(self, *args: Any, **kwargs: Any) -> None:
        logger.debug("Event paper_added received: %r %r", args, kwargs)

    def _on_scrape_finished(self, *args: Any, **kwargs: Any) -> None:
        logger.debug("Event scrape_finished received: %r %r", args, kwargs)

    def _on_analysis_finished(self, *args: Any, **kwargs: Any) -> None:
        logger.debug("Event analysis_finished received: %r %r", args, kwargs)

    def _on_export_finished(self, *args: Any, **kwargs: Any) -> None:
        logger.debug("Event export_finished received: %r %r", args, kwargs)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _refresh_stat_cards(self) -> None:
        """Set the stat cards to a sensible zero-state on first show."""
        self.set_stats(0, 0, 0, None)
