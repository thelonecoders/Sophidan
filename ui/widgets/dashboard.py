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

from ui.modern_theme import ModernTheme

logger = logging.getLogger(__name__)

#: String topics the dashboard listens for.  The contract bus
#: normalises separator/spelling variants (``scrape:completed`` ≡
#: ``scrape_completed`` ≡ ``scrape_finished``, and maps
#: ``analysis_finished``→AnalysisCompleted / ``export_finished``→
#: ExportCompleted), so ONE representative per canonical topic is
#: subscribed — registering several spellings would fire the handler
#: multiple times per event.  The handler itself still matches every
#: variant it may receive.
_EVENT_TOPICS: tuple = (
    "paper_added",
    "scrape:completed",
    "scrape:failed",
    "analysis_finished",
    "export_finished",
)


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
        title_label.setStyleSheet(
            f"color: {ModernTheme.DARK_TEXT_MUTED}; font-size: 9pt;")
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
        trend_label.setStyleSheet(
            f"color: {ModernTheme.SUCCESS}; font-size: 9pt;")
        lay.addWidget(trend_label)
        self._trend_label = trend_label

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)

    def set_trend(self, trend: str, positive: bool = True) -> None:
        color = ModernTheme.SUCCESS if positive else ModernTheme.DANGER
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
        """Subscribe to the shared EventBus via ``get_event_bus()``.

        Uses string topics (both ``scrape:completed`` and
        ``scrape_completed`` spellings are registered so the dashboard
        reacts no matter which one the engine publishes).
        """
        try:  # pragma: no cover — depends on core module written by other agent
            from core.events import get_event_bus
        except Exception:
            logger.debug("core.events not available — dashboard will not get live updates.")
            return
        try:
            bus = get_event_bus()
            for topic in _EVENT_TOPICS:
                try:
                    bus.subscribe(topic, self._on_event)
                except TypeError:
                    # Pre-contract bus expecting EventType members.
                    continue
            self._event_subscriber = bus
            logger.info("Subscribed dashboard to %d EventBus topics.",
                        len(_EVENT_TOPICS))
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
        self._paper_count = papers
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
                f'<span style="font-size:{size}pt;color:{ModernTheme.ACCENT};'
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
    def _on_event(self, event_or_topic: Any, payload: Any = None) -> None:
        """Single dispatch point for every subscribed topic.

        Accepts either ``(Event)`` objects (pre-contract bus) or
        ``(topic, payload)`` pairs (contract bus) and routes them to the
        matching UI update.
        """
        topic = getattr(event_or_topic, "type", event_or_topic)
        name = getattr(topic, "value", topic)
        data = payload
        if data is None:
            data = getattr(event_or_topic, "payload", None)
        try:
            if name in ("paper_added",):
                self._on_paper_added(data)
            elif name in ("scrape:completed", "scrape_completed",
                          "scrape_finished"):
                self._on_scrape_finished(data)
            elif name in ("scrape:failed", "scrape_failed"):
                self._on_scrape_failed(data)
            elif name in ("analysis_finished",):
                self._on_analysis_finished(data)
            elif name in ("export_finished", "export_completed"):
                self._on_export_finished(data)
        except Exception:  # noqa: BLE001 — handlers must never break the bus
            logger.exception("Dashboard event handler failed for %r", name)

    def _append_activity(self, text: str) -> None:
        """Prepend a timestamped line to the Recent Activity timeline."""
        stamp = datetime.now().strftime("%H:%M")
        if not hasattr(self, "_activity_lines"):
            self._activity_lines: List[str] = []
        self._activity_lines.insert(0, f"[{stamp}] {text}")
        del self._activity_lines[12:]
        self.set_recent_activity(self._activity_lines)

    def _payload_title(self, payload: Any) -> str:
        """Best-effort human label from an event payload."""
        if isinstance(payload, dict):
            return str(payload.get("title") or payload.get("query") or "")
        return str(payload) if payload else ""

    def _on_paper_added(self, *args: Any, **kwargs: Any) -> None:
        payload = args[0] if args else None
        title = self._payload_title(payload) or "new paper"
        self._append_activity(f"Paper added to library — {title[:60]}")
        self._paper_count = getattr(self, "_paper_count", 0) + 1
        self._card_papers.set_value(f"{self._paper_count:,}")

    def _on_scrape_finished(self, *args: Any, **kwargs: Any) -> None:
        payload = args[0] if args else None
        query = self._payload_title(payload)
        label = f"Scrape finished — {query[:40]}" if query else "Scrape finished"
        self._append_activity(label)
        self._card_scrape.set_value(datetime.now().strftime("%Y-%m-%d %H:%M"))
        self._card_scrape.set_trend("latest run", positive=True)

    def _on_scrape_failed(self, *args: Any, **kwargs: Any) -> None:
        payload = args[0] if args else None
        self._append_activity(f"Scrape failed — {self._payload_title(payload)[:60]}")

    def _on_analysis_finished(self, *args: Any, **kwargs: Any) -> None:
        payload = args[0] if args else None
        self._append_activity(
            f"Analysis finished — {self._payload_title(payload)[:60]}")

    def _on_export_finished(self, *args: Any, **kwargs: Any) -> None:
        payload = args[0] if args else None
        self._append_activity(
            f"Export finished — {self._payload_title(payload)[:60]}")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _refresh_stat_cards(self) -> None:
        """Set the stat cards to a sensible zero-state on first show."""
        self._paper_count = 0
        self._activity_lines: List[str] = []
        self.set_stats(0, 0, 0, None)
