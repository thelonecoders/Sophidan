"""Initial onboarding view shown when the app starts with no project open.

The :class:`WelcomeScreen` widget presents the user with a hero logo,
three large action cards (Start New Project / Open Recent / Quick
Search), a list of the five most recent projects, and a status strip
showing database / proxy / AI-provider health.  All three action cards
emit dedicated signals so the main window can react.
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
from qtpy.QtGui import QFont
from qtpy.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)


class _ActionCard(QFrame):
    """A clickable card with an icon glyph, title, and subtitle."""

    def __init__(
        self,
        icon: str,
        title: str,
        subtitle: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ActionCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(8)

        icon_label = QLabel(icon, self)
        icon_font = QFont(icon_label.font())
        icon_font.setPointSize(28)
        icon_label.setFont(icon_font)
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label)

        title_label = QLabel(title, self)
        title_font = QFont(title_label.font())
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        sub_label = QLabel(subtitle, self)
        sub_label.setAlignment(Qt.AlignCenter)
        sub_label.setWordWrap(True)
        sub_label.setStyleSheet("color: #94A3B8; font-size: 9pt;")
        layout.addWidget(sub_label)


class WelcomeScreen(QWidget):
    """Onboarding view shown before the user opens or creates a project.

    Signals:
        on_new_project_clicked: Emitted when the user clicks the
            "Start New Project" card or button.
        on_open_project_clicked: Emitted when the user clicks the
            "Open Recent" card (or double-clicks a recent project).
        on_search_clicked: Emitted when the user clicks the
            "Quick Search" card.
    """

    on_new_project_clicked = Signal()
    on_open_project_clicked = Signal()
    on_search_clicked = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("WelcomeScreen")
        self._recent_projects: List[dict[str, Any]] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 40, 40, 20)
        root.setSpacing(24)

        root.addStretch(1)

        # --- Hero logo + tagline --------------------------------------
        logo = QLabel("\U0001F52C", self)  # microscope glyph
        logo.setAlignment(Qt.AlignCenter)
        logo_font = QFont(logo.font())
        logo_font.setPointSize(56)
        logo.setFont(logo_font)
        root.addWidget(logo)

        title = QLabel("Academic Research Suite", self)
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont(title.font())
        title_font.setPointSize(28)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        tagline = QLabel(
            "An integrated environment for bibliometric discovery, "
            "scraping, analysis, and reporting.",
            self,
        )
        tagline.setAlignment(Qt.AlignCenter)
        tagline.setWordWrap(True)
        tagline.setStyleSheet("color: #94A3B8; font-size: 11pt;")
        root.addWidget(tagline)

        root.addSpacing(12)

        # --- Three large action cards --------------------------------
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)

        self._card_new = _ActionCard(
            "\U0001F680", "Start New Project",
            "Create a fresh research workspace.",
        )
        self._card_open = _ActionCard(
            "\U0001F4C2", "Open Recent",
            "Resume work on an existing project.",
        )
        self._card_search = _ActionCard(
            "\U0001F50E", "Quick Search",
            "Jump straight into the literature search panel.",
        )
        for card in (self._card_new, self._card_open, self._card_search):
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            cards_row.addWidget(card)

        # Mouse-click handling via mousePressEvent override on each card.
        self._card_new.mousePressEvent = self._make_click_handler(self.on_new_project_clicked)
        self._card_open.mousePressEvent = self._make_click_handler(self.on_open_project_clicked)
        self._card_search.mousePressEvent = self._make_click_handler(self.on_search_clicked)

        root.addLayout(cards_row)

        root.addSpacing(16)

        # --- Recent projects list ------------------------------------
        recent_label = QLabel("Recent Projects", self)
        recent_font = QFont(recent_label.font())
        recent_font.setPointSize(12)
        recent_font.setBold(True)
        recent_label.setFont(recent_font)
        root.addWidget(recent_label)

        self._recent_list = QListWidget(self)
        self._recent_list.setMinimumHeight(120)
        self._recent_list.setMaximumHeight(180)
        self._recent_list.itemDoubleClicked.connect(self._on_recent_double_clicked)
        root.addWidget(self._recent_list)

        root.addStretch(2)

        # --- Bottom status strip --------------------------------------
        self._status_strip = QHBoxLayout()
        self._status_strip.setContentsMargins(0, 0, 0, 0)

        self._db_label = self._make_status_chip("\U0001F4BE", "Database: idle")
        self._proxy_label = self._make_status_chip("\U0001F310", "Proxies: 0 active")
        self._ai_label = self._make_status_chip("\U0001F916", "AI: not configured")

        self._status_strip.addWidget(self._db_label)
        self._status_strip.addWidget(self._proxy_label)
        self._status_strip.addWidget(self._ai_label)
        self._status_strip.addStretch(1)

        root.addLayout(self._status_strip)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _make_status_chip(icon: str, text: str) -> QLabel:
        """Create a small pill-style label for the status strip."""
        chip = QLabel(f"{icon}  {text}")
        chip.setStyleSheet(
            "background-color: #334155; color: #F1F5F9; "
            "padding: 6px 12px; border-radius: 12px; font-size: 9pt;"
        )
        return chip

    def _make_click_handler(self, signal: Signal):  # type: ignore[valid-type]
        """Return a mousePressEvent handler that emits ``signal``."""
        def handler(event):  # noqa: ANN001 — Qt signature
            if event.button() == Qt.LeftButton:
                signal.emit()
            # Allow default handling of other buttons.
            super(_ActionCard, self).mousePressEvent(event)  # type: ignore[misc]
        return handler

    def _on_recent_double_clicked(self, item: QListWidgetItem) -> None:
        """Emit ``on_open_project_clicked`` when a recent project is chosen."""
        self.on_open_project_clicked.emit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_recent_projects(self, projects: Sequence[dict[str, Any]]) -> None:
        """Populate the recent-projects list.

        Args:
            projects: Iterable of dict-like records.  Each record is
                expected to expose ``name``, ``path`` and optionally
                ``modified`` keys.  At most five entries are shown.
        """
        self._recent_projects = list(projects)[:5]
        self._recent_list.clear()
        for proj in self._recent_projects:
            name = str(proj.get("name", "Untitled"))
            path = str(proj.get("path", ""))
            modified = proj.get("modified")
            if isinstance(modified, datetime):
                modified_str = modified.strftime("%Y-%m-%d %H:%M")
            elif modified:
                modified_str = str(modified)
            else:
                modified_str = "—"
            display = f"{name}   •   {modified_str}"
            if path:
                display += f"   •   {path}"
            item = QListWidgetItem(display)
            item.setToolTip(path or name)
            self._recent_list.addItem(item)

    def set_db_status(self, status: str) -> None:
        """Update the database status chip text."""
        self._db_label.setText(f"\U0001F4BE  Database: {status}")

    def set_proxy_status(self, active_count: int) -> None:
        """Update the proxy status chip with the active proxy count."""
        self._proxy_label.setText(f"\U0001F310  Proxies: {active_count} active")

    def set_ai_provider(self, provider: str) -> None:
        """Update the AI provider chip text."""
        provider = provider or "not configured"
        self._ai_label.setText(f"\U0001F916  AI: {provider}")

    def get_recent_projects(self) -> List[dict[str, Any]]:
        """Return the currently displayed recent-project records."""
        return list(self._recent_projects)
