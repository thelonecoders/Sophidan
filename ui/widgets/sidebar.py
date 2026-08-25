"""Vertical navigation rail used as the leftmost panel of the main window.

The :class:`Sidebar` widget renders a list of :class:`NavItem` entries,
optionally collapses to an icon-only rail, and emits a ``page_changed``
signal whenever the active item changes.  It is intentionally
self-contained: it does not import any sibling UI module so that the
rest of the application can stay lazy-loadable.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from qtpy.QtCore import Qt, Signal, QSize
from qtpy.QtGui import QIcon, QFont
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QSpacerItem, QSizePolicy,
    QButtonGroup, QToolButton, QLabel,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NavItem:
    """A single sidebar navigation entry.

    Attributes:
        name: Human-readable label shown when expanded.
        icon: Glyph used as the icon — typically a unicode/emoji
            character (e.g. ``"\\U0001F4E6"``) or, if a Material/
            FontAwesome font is available, the corresponding code-point
            string (e.g. ``"\\uF0E0"``).
        page_key: Stable identifier emitted via ``page_changed``.
        section: ``"top"`` for navigation items rendered first, or
            ``"bottom"`` for items pinned to the bottom of the rail.
    """
    name: str
    icon: str
    page_key: str
    section: str = "top"


def default_nav_items() -> List[NavItem]:
    """Return the canonical list of sidebar navigation items.

    Items are split between the *top* section (core navigation) and the
    *bottom* section (settings / help).  Glyphs use simple emoji so the
    sidebar degrades gracefully when no icon-font library is installed.
    """
    return [
        NavItem("Dashboard", "\U0001F3E0", "dashboard", "top"),
        NavItem("Search",    "\U0001F50D", "search",    "top"),
        NavItem("Projects",  "\U0001F4C1", "projects",  "top"),
        NavItem("Data",      "\U0001F4CA", "data",      "top"),
        NavItem("Knowledge Graph", "\U0001F578", "knowledge_graph", "top"),
        NavItem("Analysis",  "\U0001F9EE", "analysis", "top"),
        NavItem("AI Chat",   "\U0001F916", "ai_chat",   "top"),
        NavItem("Proxy",     "\U0001F310", "proxy",     "top"),
        NavItem("Reports",   "\U0001F4DD", "reports",   "top"),
        # v2.0.0 — added by v2-ui-web
        NavItem("Bibliometrics",     "\U0001F4CA", "bibliometrics",     "top"),
        NavItem("Advanced Networks", "\U0001F578",  "gephi_advanced",    "top"),
        NavItem("Systematic Review", "\U0001F4CB", "systematic_review", "top"),
        NavItem("Meta-Analysis",     "\U0001F4C8", "meta_analysis",     "top"),
        NavItem("PRISMA Builder",    "\U0001F504", "prisma_builder",    "top"),
        NavItem("Q1 Figures",        "\U0001F3A8", "q1_figures",        "top"),
        NavItem("Innovation",        "\U0001F4A1", "innovation",        "top"),
        NavItem("Settings",  "\u2699\ufe0f", "settings", "bottom"),
        NavItem("Help",      "\u2753", "help", "bottom"),
    ]


class _NavButton(QPushButton):
    """A single sidebar navigation button.

    The button stores its associated :class:`NavItem` and exposes it
    via the :attr:`item` attribute.  It uses the ``SidebarNavButton``
    object name so the QSS stylesheet can style it appropriately.
    """

    def __init__(self, item: NavItem, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.item: NavItem = item
        self.setObjectName("SidebarNavButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(item.name)
        self.setToolTip(item.name)
        self._refresh_text(expanded=True)

    def _refresh_text(self, expanded: bool) -> None:
        """Update the button label depending on the collapse state."""
        if expanded:
            self.setText(f"  {self.item.icon}   {self.item.name}")
        else:
            self.setText(f"  {self.item.icon}  ")

    def set_active(self, active: bool) -> None:
        """Toggle the active visual state via the QSS ``[active]`` selector."""
        self.setChecked(active)
        self.setProperty("active", "true" if active else "false")
        # Re-polish so the new property value takes effect immediately.
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)

    def set_expanded(self, expanded: bool) -> None:
        self._refresh_text(expanded)
        self.updateGeometry()


class Sidebar(QWidget):
    """Collapsible vertical navigation rail.

    The widget renders the canonical navigation items defined by
    :func:`default_nav_items` and emits ``page_changed(page_key)`` when
    the user selects a new entry.

    Signals:
        page_changed: Emitted with the new ``page_key`` whenever the
            active navigation item changes.
    """

    page_changed = Signal(str)

    #: Width of the rail when expanded.
    EXPANDED_WIDTH = 220
    #: Width of the rail when collapsed (icons only).
    COLLAPSED_WIDTH = 60

    def __init__(
        self,
        items: Optional[List[NavItem]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self._items: List[NavItem] = list(items) if items else default_nav_items()
        self._buttons: dict[str, _NavButton] = {}
        self._collapsed: bool = False
        self._active_key: Optional[str] = None

        self._build_ui()
        # Default to the first top-section item so the sidebar is never
        # in an indeterminate state.
        first_key = next(
            (i.page_key for i in self._items if i.section == "top"),
            None,
        )
        if first_key is not None:
            self.set_active(first_key)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 8)
        outer.setSpacing(4)

        # Hamburger / collapse toggle.
        self._hamburger = QToolButton(self)
        self._hamburger.setObjectName("SidebarHamburger")
        self._hamburger.setText("\u2630")  # trigram for heaven ≡
        self._hamburger.setToolTip("Collapse / expand sidebar")
        self._hamburger.setCursor(Qt.PointingHandCursor)
        self._hamburger.setCheckable(True)
        self._hamburger.clicked.connect(self.toggle_collapse)
        outer.addWidget(self._hamburger)

        # Optional app label (shown only when expanded).
        self._app_label = QLabel("Academic\nResearch Suite", self)
        self._app_label.setAlignment(Qt.AlignCenter)
        app_font = self._app_label.font()
        app_font.setPointSize(9)
        app_font.setBold(True)
        self._app_label.setFont(app_font)
        self._app_label.setWordWrap(True)
        outer.addWidget(self._app_label)

        outer.addSpacing(8)

        # Top navigation items.
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for item in self._items:
            if item.section != "top":
                continue
            btn = _NavButton(item, self)
            self._group.addButton(btn)
            self._buttons[item.page_key] = btn
            btn.clicked.connect(lambda _checked=False, k=item.page_key: self._on_clicked(k))
            outer.addWidget(btn)

        # Spacer pushes bottom items to the bottom.
        outer.addItem(
            QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        )

        # Bottom items (Settings / Help).
        for item in self._items:
            if item.section != "bottom":
                continue
            btn = _NavButton(item, self)
            self._group.addButton(btn)
            self._buttons[item.page_key] = btn
            btn.clicked.connect(lambda _checked=False, k=item.page_key: self._on_clicked(k))
            outer.addWidget(btn)

        self._apply_width()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_active(self, page_key: str) -> None:
        """Programmatically mark ``page_key`` as the active page.

        Args:
            page_key: The ``page_key`` of one of the registered
                :class:`NavItem` entries.
        """
        if page_key not in self._buttons:
            logger.warning("Unknown page_key %r — ignoring set_active.", page_key)
            return
        # Deactivate previous.
        if self._active_key and self._active_key in self._buttons:
            self._buttons[self._active_key].set_active(False)
        self._active_key = page_key
        self._buttons[page_key].set_active(True)

    def get_active(self) -> Optional[str]:
        """Return the ``page_key`` of the currently active item."""
        return self._active_key

    def set_collapsed(self, collapsed: bool) -> None:
        """Collapse or expand the rail."""
        self._collapsed = bool(collapsed)
        self._hamburger.setChecked(self._collapsed)
        self._app_label.setVisible(not self._collapsed)
        for btn in self._buttons.values():
            btn.set_expanded(not self._collapsed)
        self._apply_width()

    def toggle_collapse(self) -> None:
        """Toggle the collapsed state and update the hamburger button."""
        self.set_collapsed(not self._collapsed)

    def is_collapsed(self) -> bool:
        """Return ``True`` if the sidebar is currently collapsed."""
        return self._collapsed

    def items(self) -> List[NavItem]:
        """Return a shallow copy of the registered navigation items."""
        return list(self._items)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _apply_width(self) -> None:
        width = self.COLLAPSED_WIDTH if self._collapsed else self.EXPANDED_WIDTH
        self.setFixedWidth(width)

    def _on_clicked(self, page_key: str) -> None:
        """Handle button clicks — update active state and emit signal."""
        self.set_active(page_key)
        self.page_changed.emit(page_key)

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------
    def sizeHint(self) -> QSize:  # noqa: N802 — Qt API
        width = self.COLLAPSED_WIDTH if self._collapsed else self.EXPANDED_WIDTH
        return QSize(width, super().sizeHint().height())
