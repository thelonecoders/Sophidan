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
    """A clickable card with an icon glyph, title, and subtitle.

    Keyboard-accessible: focusable via Tab, activated with
    Enter/Return/Space, and exposed with a button role + accessible
    name so screen readers announce it.
    """

    clicked = Signal()  # emitted on mouse click OR keyboard activation

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
        # Accessibility / keyboard support.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)

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
        # Colour inherits from the global QSS so both themes stay legible.
        sub_label.setStyleSheet("font-size: 9pt;")
        layout.addWidget(sub_label)

    # --- Interaction -------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                           Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


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
        # Colour inherits from the global QSS (theme-aware).
        tagline.setStyleSheet("font-size: 11pt;")
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

        # Cards emit a proper ``clicked`` signal (mouse + keyboard).
        self._card_new.clicked.connect(self.on_new_project_clicked.emit)
        self._card_open.clicked.connect(self.on_open_project_clicked.emit)
        self._card_search.clicked.connect(self.on_search_clicked.emit)

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
        chip.setObjectName("StatusChip")
        return chip

    def _on_recent_double_clicked(self, item: QListWidgetItem) -> None:
        """Emit ``on_open_project_clicked`` when a recent project is chosen."""
        self.on_open_project_clicked.emit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_recent_projects(self, projects: Sequence[Any]) -> None:
        """Populate the recent-projects list.

        Args:
            projects: Iterable of records.  Each record may be a plain
                dict (``name`` / ``path`` / ``modified`` keys), a
                :class:`ProjectManager` ``Project`` dataclass, or any
                object exposing ``name`` / ``updated_at`` attributes.
                At most five entries are shown.
        """
        records: List[dict[str, Any]] = []
        for proj in list(projects)[:5]:
            if isinstance(proj, dict):
                records.append(dict(proj))
                continue
            to_dict = getattr(proj, "to_dict", None)
            if callable(to_dict):
                try:
                    data = to_dict()
                    if isinstance(data, dict):
                        records.append(data)
                        continue
                except Exception:  # noqa: BLE001 — fall through to attrs
                    logger.debug("Project.to_dict() failed.", exc_info=True)
            name = getattr(proj, "name", None)
            if name is not None:
                records.append({
                    "name": name,
                    "modified": getattr(proj, "updated_at",
                                        getattr(proj, "modified", None)),
                })
        self._recent_projects = records
        self._recent_list.clear()
        for proj in records:
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
