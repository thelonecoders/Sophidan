"""Modern dark/light theme stylesheet and palette management for the
Academic Research Suite Qt application.

The :class:`ModernTheme` class centralises all colour constants and Qt
stylesheet (QSS) strings used across the UI.  It exposes a small public
API (:meth:`ModernTheme.apply`, :meth:`ModernTheme.get_palette`) plus a
``theme_changed`` Qt signal that other widgets can subscribe to in
order to react to live theme switches.

Design goals
------------
* Pure dark/light variants with the same electric-blue accent.
* Sidebar darker than the content area for visual hierarchy.
* Rounded buttons, styled scrollbars, hover/pressed/disabled states.
* No hard dependency on ``qt_material`` — if it is installed, its icon
  font family name is exposed via :data:`ModernTheme.ICON_FONT`,
  otherwise the system default is used.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
from typing import Optional

from qtpy.QtCore import QObject, Signal
from qtpy.QtGui import QPalette, QColor
from qtpy.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class ModernTheme(QObject):
    """Centralised theme constants, QSS stylesheets, and palette factory.

    The class is intentionally light-weight: it holds no Qt widget state
    of its own — only colour constants and stylesheet strings.  The
    ``theme_changed`` signal is emitted whenever :meth:`apply` swaps the
    active stylesheet so that downstream widgets can refresh cached
    colours if needed.

    Attributes:
        ACCENT: Electric blue used for highlights, active nav, buttons.
        SUCCESS: Green used for "ok" badges / trend up.
        WARNING: Amber used for caution indicators.
        DANGER: Red used for destructive actions / errors.
        INFO: Cyan used for informational badges.
        DARK_QSS: Complete dark-theme QSS stylesheet.
        LIGHT_QSS: Complete light-theme QSS stylesheet.
        ICON_FONT: Font family name to use for icon glyphs, or ``None``
            if no icon-font library is installed.
    """

    # --- Colour palette -------------------------------------------------
    ACCENT = "#3B82F6"
    ACCENT_HOVER = "#2563EB"
    ACCENT_PRESSED = "#1D4ED8"
    SUCCESS = "#10B981"
    WARNING = "#F59E0B"
    DANGER = "#EF4444"
    INFO = "#06B6D4"

    # Dark theme background tiers (sidebar < content < card).
    DARK_BG_SIDEBAR = "#0F172A"   # slate-900
    DARK_BG_CONTENT = "#1E293B"   # slate-800
    DARK_BG_CARD = "#334155"      # slate-700
    DARK_BG_INPUT = "#1E293B"
    DARK_TEXT = "#F1F5F9"         # slate-100
    DARK_TEXT_MUTED = "#94A3B8"   # slate-400
    DARK_BORDER = "#334155"

    # Light theme background tiers.
    LIGHT_BG_SIDEBAR = "#F1F5F9"  # slate-100
    LIGHT_BG_CONTENT = "#FFFFFF"
    LIGHT_BG_CARD = "#F8FAFC"
    LIGHT_BG_INPUT = "#FFFFFF"
    LIGHT_TEXT = "#0F172A"        # slate-900
    LIGHT_TEXT_MUTED = "#64748B"  # slate-500
    LIGHT_BORDER = "#E2E8F0"

    # Qt signal emitted whenever the active theme changes.  The payload
    # is the new theme name ("dark" or "light").
    theme_changed = Signal(str)

    #: Icon font family — set if ``qt_material`` is importable, else ``None``.
    ICON_FONT: Optional[str] = None

    # --- QSS stylesheets ------------------------------------------------
    DARK_QSS: str = """
    /* ===== Global ===== */
    QWidget {
        background-color: #1E293B;
        color: #F1F5F9;
        font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', sans-serif;
        font-size: 10pt;
    }
    QMainWindow, QDialog {
        background-color: #1E293B;
    }
    QToolTip {
        background-color: #0F172A;
        color: #F1F5F9;
        border: 1px solid #3B82F6;
        padding: 4px 8px;
        border-radius: 4px;
    }

    /* ===== Sidebar ===== */
    #Sidebar {
        background-color: #0F172A;
        border-right: 1px solid #1E293B;
    }
    #SidebarNavButton {
        background-color: transparent;
        color: #94A3B8;
        border: none;
        border-left: 3px solid transparent;
        text-align: left;
        padding: 10px 14px;
        font-size: 10pt;
    }
    #SidebarNavButton:hover {
        background-color: #1E293B;
        color: #F1F5F9;
    }
    #SidebarNavButton[active="true"] {
        background-color: #1E293B;
        color: #3B82F6;
        border-left: 3px solid #3B82F6;
        font-weight: 600;
    }
    #SidebarHamburger {
        background-color: transparent;
        border: none;
        color: #94A3B8;
        padding: 8px;
        font-size: 14pt;
    }
    #SidebarHamburger:hover { color: #F1F5F9; }

    /* ===== Cards / frames ===== */
    QFrame#Card {
        background-color: #334155;
        border: 1px solid #475569;
        border-radius: 8px;
    }

    /* ===== Buttons ===== */
    QPushButton {
        background-color: #334155;
        color: #F1F5F9;
        border: 1px solid #475569;
        padding: 8px 16px;
        border-radius: 6px;
        min-width: 72px;
    }
    QPushButton:hover { background-color: #475569; }
    QPushButton:pressed { background-color: #1E293B; }
    QPushButton:disabled { background-color: #1E293B; color: #64748B; }
    QPushButton#PrimaryBtn {
        background-color: #3B82F6;
        border: 1px solid #2563EB;
        color: #FFFFFF;
        font-weight: 600;
    }
    QPushButton#PrimaryBtn:hover { background-color: #2563EB; }
    QPushButton#PrimaryBtn:pressed { background-color: #1D4ED8; }
    QPushButton#DangerBtn {
        background-color: #EF4444;
        border: 1px solid #DC2626;
        color: #FFFFFF;
    }
    QPushButton#DangerBtn:hover { background-color: #DC2626; }
    QPushButton#GhostBtn {
        background-color: transparent;
        border: 1px solid #475569;
        color: #F1F5F9;
    }
    QPushButton#GhostBtn:hover { background-color: #334155; }

    /* ===== Inputs ===== */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QDateEdit, QDateTimeEdit {
        background-color: #1E293B;
        color: #F1F5F9;
        border: 1px solid #475569;
        padding: 6px 8px;
        border-radius: 6px;
        selection-background-color: #3B82F6;
    }
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
        border: 1px solid #3B82F6;
    }
    QComboBox::drop-down { border: none; width: 22px; }
    QComboBox QAbstractItemView {
        background-color: #1E293B;
        color: #F1F5F9;
        border: 1px solid #475569;
        selection-background-color: #3B82F6;
    }

    /* ===== Tables ===== */
    QTableView, QTreeView, QListView {
        background-color: #1E293B;
        alternate-background-color: #243349;
        color: #F1F5F9;
        border: 1px solid #334155;
        gridline-color: #334155;
        border-radius: 6px;
        selection-background-color: #3B82F6;
        selection-color: #FFFFFF;
    }
    QTableView::item, QTreeView::item { padding: 5px 6px; }
    QTableView::item:selected { background-color: #3B82F6; }
    QHeaderView::section {
        background-color: #0F172A;
        color: #94A3B8;
        padding: 6px 8px;
        border: none;
        border-right: 1px solid #1E293B;
        border-bottom: 1px solid #1E293B;
        font-weight: 600;
    }
    QHeaderView::section:hover { color: #F1F5F9; }

    /* ===== Menus ===== */
    QMenuBar {
        background-color: #0F172A;
        color: #F1F5F9;
        border-bottom: 1px solid #1E293B;
    }
    QMenuBar::item { background: transparent; padding: 6px 10px; }
    QMenuBar::item:selected { background-color: #1E293B; color: #3B82F6; }
    QMenu {
        background-color: #1E293B;
        color: #F1F5F9;
        border: 1px solid #334155;
        padding: 4px;
    }
    QMenu::item { padding: 6px 24px; border-radius: 4px; }
    QMenu::item:selected { background-color: #3B82F6; color: #FFFFFF; }
    QMenu::separator { height: 1px; background-color: #334155; margin: 4px 8px; }

    /* ===== Status / toolbars ===== */
    QStatusBar {
        background-color: #0F172A;
        color: #94A3B8;
        border-top: 1px solid #1E293B;
    }
    QStatusBar::item { border: none; }
    QToolBar {
        background-color: #0F172A;
        border-bottom: 1px solid #1E293B;
        spacing: 4px;
        padding: 4px;
    }
    QToolBar::separator { background-color: #1E293B; width: 1px; margin: 6px 4px; }

    /* ===== Tabs ===== */
    QTabWidget::pane {
        border: 1px solid #334155;
        border-radius: 6px;
        top: -1px;
    }
    QTabBar::tab {
        background-color: #1E293B;
        color: #94A3B8;
        padding: 8px 16px;
        border: 1px solid transparent;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #334155;
        color: #3B82F6;
        border-color: #334155;
    }
    QTabBar::tab:hover:!selected { background-color: #243349; color: #F1F5F9; }

    /* ===== Progress ===== */
    QProgressBar {
        border: 1px solid #334155;
        border-radius: 6px;
        text-align: center;
        background-color: #1E293B;
        color: #F1F5F9;
        height: 18px;
    }
    QProgressBar::chunk {
        background-color: #3B82F6;
        border-radius: 4px;
    }

    /* ===== Scrollbars ===== */
    QScrollBar:vertical {
        background: transparent;
        width: 12px;
        margin: 2px;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 12px;
        margin: 2px;
    }
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
        background: #475569;
        border-radius: 4px;
        min-height: 24px;
        min-width: 24px;
    }
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
        background: #64748B;
    }
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {
        background: transparent;
        border: none;
        width: 0px;
        height: 0px;
    }

    /* ===== Dock widgets ===== */
    QDockWidget {
        titlebar-close-icon: none;
        titlebar-normal-icon: none;
    }
    QDockWidget::title {
        text-align: left;
        background: #0F172A;
        padding: 6px 10px;
        font-weight: 600;
        color: #94A3B8;
    }

    /* ===== Splitter ===== */
    QSplitter::handle { background-color: #1E293B; }
    QSplitter::handle:hover { background-color: #3B82F6; }

    /* ===== MessageBox ===== */
    QMessageBox { background-color: #1E293B; }
    QMessageBox QLabel { color: #F1F5F9; }

    /* ===== Welcome screen action cards ===== */
    QFrame#ActionCard {
        background-color: #334155;
        border: 1px solid #475569;
        border-radius: 12px;
    }
    QFrame#ActionCard:hover {
        border: 1px solid #3B82F6;
        background-color: #3B4658;
    }
    """

    LIGHT_QSS: str = """
    /* ===== Global ===== */
    QWidget {
        background-color: #FFFFFF;
        color: #0F172A;
        font-family: 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', sans-serif;
        font-size: 10pt;
    }
    QMainWindow, QDialog { background-color: #FFFFFF; }
    QToolTip {
        background-color: #0F172A;
        color: #F1F5F9;
        border: 1px solid #3B82F6;
        padding: 4px 8px;
        border-radius: 4px;
    }

    /* ===== Sidebar ===== */
    #Sidebar {
        background-color: #F1F5F9;
        border-right: 1px solid #E2E8F0;
    }
    #SidebarNavButton {
        background-color: transparent;
        color: #64748B;
        border: none;
        border-left: 3px solid transparent;
        text-align: left;
        padding: 10px 14px;
        font-size: 10pt;
    }
    #SidebarNavButton:hover {
        background-color: #E2E8F0;
        color: #0F172A;
    }
    #SidebarNavButton[active="true"] {
        background-color: #E2E8F0;
        color: #3B82F6;
        border-left: 3px solid #3B82F6;
        font-weight: 600;
    }
    #SidebarHamburger {
        background-color: transparent;
        border: none;
        color: #64748B;
        padding: 8px;
        font-size: 14pt;
    }
    #SidebarHamburger:hover { color: #0F172A; }

    /* ===== Cards / frames ===== */
    QFrame#Card {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
    }

    /* ===== Buttons ===== */
    QPushButton {
        background-color: #F1F5F9;
        color: #0F172A;
        border: 1px solid #CBD5E1;
        padding: 8px 16px;
        border-radius: 6px;
        min-width: 72px;
    }
    QPushButton:hover { background-color: #E2E8F0; }
    QPushButton:pressed { background-color: #CBD5E1; }
    QPushButton:disabled { background-color: #F8FAFC; color: #94A3B8; }
    QPushButton#PrimaryBtn {
        background-color: #3B82F6;
        border: 1px solid #2563EB;
        color: #FFFFFF;
        font-weight: 600;
    }
    QPushButton#PrimaryBtn:hover { background-color: #2563EB; }
    QPushButton#PrimaryBtn:pressed { background-color: #1D4ED8; }
    QPushButton#DangerBtn {
        background-color: #EF4444;
        border: 1px solid #DC2626;
        color: #FFFFFF;
    }
    QPushButton#DangerBtn:hover { background-color: #DC2626; }
    QPushButton#GhostBtn {
        background-color: transparent;
        border: 1px solid #CBD5E1;
        color: #0F172A;
    }
    QPushButton#GhostBtn:hover { background-color: #F1F5F9; }

    /* ===== Inputs ===== */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QDateEdit, QDateTimeEdit {
        background-color: #FFFFFF;
        color: #0F172A;
        border: 1px solid #CBD5E1;
        padding: 6px 8px;
        border-radius: 6px;
        selection-background-color: #3B82F6;
        selection-color: #FFFFFF;
    }
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
        border: 1px solid #3B82F6;
    }
    QComboBox::drop-down { border: none; width: 22px; }
    QComboBox QAbstractItemView {
        background-color: #FFFFFF;
        color: #0F172A;
        border: 1px solid #CBD5E1;
        selection-background-color: #3B82F6;
        selection-color: #FFFFFF;
    }

    /* ===== Tables ===== */
    QTableView, QTreeView, QListView {
        background-color: #FFFFFF;
        alternate-background-color: #F8FAFC;
        color: #0F172A;
        border: 1px solid #E2E8F0;
        gridline-color: #E2E8F0;
        border-radius: 6px;
        selection-background-color: #3B82F6;
        selection-color: #FFFFFF;
    }
    QTableView::item, QTreeView::item { padding: 5px 6px; }
    QTableView::item:selected { background-color: #3B82F6; color: #FFFFFF; }
    QHeaderView::section {
        background-color: #F1F5F9;
        color: #64748B;
        padding: 6px 8px;
        border: none;
        border-right: 1px solid #E2E8F0;
        border-bottom: 1px solid #E2E8F0;
        font-weight: 600;
    }
    QHeaderView::section:hover { color: #0F172A; }

    /* ===== Menus ===== */
    QMenuBar {
        background-color: #F1F5F9;
        color: #0F172A;
        border-bottom: 1px solid #E2E8F0;
    }
    QMenuBar::item { background: transparent; padding: 6px 10px; }
    QMenuBar::item:selected { background-color: #E2E8F0; color: #3B82F6; }
    QMenu {
        background-color: #FFFFFF;
        color: #0F172A;
        border: 1px solid #E2E8F0;
        padding: 4px;
    }
    QMenu::item { padding: 6px 24px; border-radius: 4px; }
    QMenu::item:selected { background-color: #3B82F6; color: #FFFFFF; }
    QMenu::separator { height: 1px; background-color: #E2E8F0; margin: 4px 8px; }

    /* ===== Status / toolbars ===== */
    QStatusBar {
        background-color: #F1F5F9;
        color: #64748B;
        border-top: 1px solid #E2E8F0;
    }
    QStatusBar::item { border: none; }
    QToolBar {
        background-color: #F1F5F9;
        border-bottom: 1px solid #E2E8F0;
        spacing: 4px;
        padding: 4px;
    }
    QToolBar::separator { background-color: #E2E8F0; width: 1px; margin: 6px 4px; }

    /* ===== Tabs ===== */
    QTabWidget::pane {
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        top: -1px;
    }
    QTabBar::tab {
        background-color: #F1F5F9;
        color: #64748B;
        padding: 8px 16px;
        border: 1px solid transparent;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background-color: #FFFFFF;
        color: #3B82F6;
        border-color: #E2E8F0;
    }
    QTabBar::tab:hover:!selected { background-color: #E2E8F0; color: #0F172A; }

    /* ===== Progress ===== */
    QProgressBar {
        border: 1px solid #E2E8F0;
        border-radius: 6px;
        text-align: center;
        background-color: #F1F5F9;
        color: #0F172A;
        height: 18px;
    }
    QProgressBar::chunk {
        background-color: #3B82F6;
        border-radius: 4px;
    }

    /* ===== Scrollbars ===== */
    QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
    QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
        background: #CBD5E1;
        border-radius: 4px;
        min-height: 24px;
        min-width: 24px;
    }
    QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
        background: #94A3B8;
    }
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {
        background: transparent; border: none; width: 0px; height: 0px;
    }

    /* ===== Dock widgets ===== */
    QDockWidget::title {
        text-align: left;
        background: #F1F5F9;
        padding: 6px 10px;
        font-weight: 600;
        color: #64748B;
    }

    /* ===== Splitter ===== */
    QSplitter::handle { background-color: #E2E8F0; }
    QSplitter::handle:hover { background-color: #3B82F6; }

    /* ===== MessageBox ===== */
    QMessageBox { background-color: #FFFFFF; }
    QMessageBox QLabel { color: #0F172A; }

    /* ===== Welcome screen action cards ===== */
    QFrame#ActionCard {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
    }
    QFrame#ActionCard:hover {
        border: 1px solid #3B82F6;
        background-color: #EFF6FF;
    }
    """

    @classmethod
    def apply(cls, app: QApplication, theme: str = "dark") -> None:
        """Apply the given theme stylesheet to ``app``.

        Args:
            app: The active :class:`QApplication` instance.
            theme: Either ``"dark"`` or ``"light"``.  Any other value
                falls back to ``"dark"`` with a warning log.
        """
        theme = (theme or "dark").lower()
        if theme not in ("dark", "light"):
            logger.warning("Unknown theme %r — falling back to dark.", theme)
            theme = "dark"
        qss = cls.DARK_QSS if theme == "dark" else cls.LIGHT_QSS
        try:
            app.setStyleSheet(qss)
            palette = cls.get_palette(theme)
            if palette is not None:
                app.setPalette(palette)
            logger.info("Applied %s theme.", theme)
            # Emit via a shared instance so subscribers can connect.
            _instance().theme_changed.emit(theme)
        except Exception:  # pragma: no cover — defensive
            logger.exception("Failed to apply theme %r", theme)

    @classmethod
    def get_palette(cls, theme: str) -> Optional[QPalette]:
        """Build a :class:`QPalette` matching the requested theme.

        Args:
            theme: ``"dark"`` or ``"light"``.

        Returns:
            A configured :class:`QPalette`, or ``None`` if the theme
            name was not recognised.
        """
        theme = (theme or "dark").lower()
        palette = QPalette()
        if theme == "dark":
            palette.setColor(QPalette.Window, QColor(cls.DARK_BG_CONTENT))
            palette.setColor(QPalette.WindowText, QColor(cls.DARK_TEXT))
            palette.setColor(QPalette.Base, QColor(cls.DARK_BG_INPUT))
            palette.setColor(QPalette.AlternateBase, QColor("#243349"))
            palette.setColor(QPalette.Text, QColor(cls.DARK_TEXT))
            palette.setColor(QPalette.Button, QColor(cls.DARK_BG_CARD))
            palette.setColor(QPalette.ButtonText, QColor(cls.DARK_TEXT))
            palette.setColor(QPalette.Highlight, QColor(cls.ACCENT))
            palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
            palette.setColor(QPalette.ToolTipBase, QColor(cls.DARK_BG_SIDEBAR))
            palette.setColor(QPalette.ToolTipText, QColor(cls.DARK_TEXT))
            palette.setColor(QPalette.PlaceholderText, QColor(cls.DARK_TEXT_MUTED))
            palette.setColor(QPalette.Disabled, QPalette.WindowText,
                            QColor(cls.DARK_TEXT_MUTED))
            palette.setColor(QPalette.Disabled, QPalette.ButtonText,
                            QColor(cls.DARK_TEXT_MUTED))
        elif theme == "light":
            palette.setColor(QPalette.Window, QColor(cls.LIGHT_BG_CONTENT))
            palette.setColor(QPalette.WindowText, QColor(cls.LIGHT_TEXT))
            palette.setColor(QPalette.Base, QColor(cls.LIGHT_BG_INPUT))
            palette.setColor(QPalette.AlternateBase, QColor("#F8FAFC"))
            palette.setColor(QPalette.Text, QColor(cls.LIGHT_TEXT))
            palette.setColor(QPalette.Button, QColor(cls.LIGHT_BG_SIDEBAR))
            palette.setColor(QPalette.ButtonText, QColor(cls.LIGHT_TEXT))
            palette.setColor(QPalette.Highlight, QColor(cls.ACCENT))
            palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
            palette.setColor(QPalette.ToolTipBase, QColor(cls.LIGHT_TEXT))
            palette.setColor(QPalette.ToolTipText, QColor("#FFFFFF"))
            palette.setColor(QPalette.PlaceholderText, QColor(cls.LIGHT_TEXT_MUTED))
            palette.setColor(QPalette.Disabled, QPalette.WindowText,
                            QColor(cls.LIGHT_TEXT_MUTED))
            palette.setColor(QPalette.Disabled, QPalette.ButtonText,
                            QColor(cls.LIGHT_TEXT_MUTED))
        else:
            return None
        return palette

    @classmethod
    def is_dark(cls, theme: str) -> bool:
        """Return ``True`` iff the given theme name resolves to dark."""
        return (theme or "dark").lower() == "dark"


# ---------------------------------------------------------------------------
# Module-level singleton so callers can ``ModernTheme.theme_changed.connect``
# without first instantiating the class.
# ---------------------------------------------------------------------------
_INSTANCE: Optional[ModernTheme] = None


def _instance() -> ModernTheme:
    """Return (creating if needed) the shared :class:`ModernTheme` instance."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ModernTheme()
    return _INSTANCE


def _detect_icon_font() -> Optional[str]:
    """Detect an icon font family from optional Qt icon libraries.

    Tries ``qt_material`` (which bundles Material Design Icons) and then
    ``qtawesome`` (FontAwesome).  Returns ``None`` if neither is
    importable so callers can fall back to unicode glyphs.
    """
    try:  # pragma: no cover — depends on optional deps
        import qt_material  # type: ignore  # noqa: F401
        # qt_material uses the "Material Icons" font family.
        return "Material Icons"
    except Exception:
        pass
    try:  # pragma: no cover
        import qtawesome as qta  # type: ignore  # noqa: F401
        return qta.iconic_font or "FontAwesome"
    except Exception:
        pass
    return None


ModernTheme.ICON_FONT = _detect_icon_font()
