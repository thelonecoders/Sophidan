"""Main application shell for the Academic Research Suite.

The :class:`MainWindow` is a :class:`QMainWindow` that wires together the
sidebar navigation, a central :class:`QStackedWidget` of lazily-loaded
pages, a top toolbar (global search, AI provider selector, theme
toggle), a bottom status bar (scraping queue size, active tasks, DB
size, log viewer button), and the menu bar / keyboard shortcuts.

Pages are loaded lazily on first access — sibling widgets that have
not yet been written by other agents fall back to a friendly
"Coming soon" placeholder so the window is always usable.

A module-level :func:`get_main_window` accessor returns the singleton
instance (creating it on first call).
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import importlib
import logging
import os
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from qtpy.QtCore import Qt, QSize
from qtpy.QtGui import QIcon, QKeySequence
from qtpy.QtWidgets import (
    QAction, QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QShortcut, QStackedWidget,
    QStatusBar, QToolBar, QWidget, QVBoxLayout,
)

from ui.modern_theme import ModernTheme
from ui.widgets.sidebar import Sidebar
from ui.welcome_screen import WelcomeScreen

if TYPE_CHECKING:  # pragma: no cover
    from project_management.workspace import Workspace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Page registry: page_key → (module_path, class_name, factory_kwargs_fn)
# ---------------------------------------------------------------------------
# The factory for each page is a zero-arg callable that returns a QWidget.
# We build the factories lazily inside :meth:`_load_page` so that the
# heavy imports only happen on first access.
_PAGE_REGISTRY: Dict[str, Dict[str, str]] = {
    "dashboard":        {"module": "ui.widgets.dashboard",       "class": "DashboardWidget"},
    "search":           {"module": "ui.widgets.search_panel",     "class": "SearchPanel"},
    "projects":         {"module": "ui.widgets.project_explorer", "class": "ProjectExplorer"},
    "data":             {"module": "ui.widgets.data_view",        "class": "DataViewWidget"},
    "knowledge_graph":  {"module": "ui.widgets.network_view",      "class": "NetworkViewWidget"},
    "analysis":         {"module": "ui.widgets.analysis_view",     "class": "AnalysisViewWidget"},
    "ai_chat":          {"module": "ui.widgets.ai_chat",           "class": "AIChatWidget"},
    "proxy":            {"module": "ui.widgets.proxy_panel",        "class": "ProxyPanel"},
    "reports":          {"module": "ui.widgets.reports_view",      "class": "ReportsView"},  # may not exist
    "settings":         {"module": "ui.widgets.settings_panel",    "class": "SettingsPanel"},
    "help":             {"module": "ui.dialogs.help_dialog",       "class": "HelpDialog"},
    # v2.0.0 — added by v2-ui-web
    "bibliometrics":     {"module": "ui.widgets.bibliometric_dashboard", "class": "BibliometricDashboard"},
    "gephi_advanced":    {"module": "ui.widgets.gephi_advanced_view",   "class": "GephiAdvancedView"},
    "systematic_review": {"module": "ui.widgets.systematic_review_view", "class": "SystematicReviewView"},
    "meta_analysis":     {"module": "ui.widgets.meta_analysis_view",      "class": "MetaAnalysisView"},
    "prisma_builder":    {"module": "ui.widgets.prisma_builder",          "class": "PRISMAFlowBuilder"},
    "q1_figures":        {"module": "ui.widgets.q1_figure_studio",        "class": "Q1FigureStudio"},
    "innovation":        {"module": "ui.widgets.innovation_panel",         "class": "InnovationPanel"},
}


# ---------------------------------------------------------------------------
# Placeholder page
# ---------------------------------------------------------------------------
class _PlaceholderPage(QWidget):
    """Shown when a sibling widget module has not yet been written."""

    def __init__(self, page_key: str, reason: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"Placeholder_{page_key}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.setAlignment(Qt.AlignCenter)
        title = QLabel(f"\U0001F6A7  {page_key.replace('_', ' ').title()}", self)
        title.setAlignment(Qt.AlignCenter)
        f = title.font()
        f.setPointSize(18)
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)
        sub = QLabel(reason or "This panel is not available yet.", self)
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("color: #94A3B8;")
        lay.addWidget(sub)
        lay.addStretch(1)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    """Application shell hosting the sidebar + stacked central pages.

    Args:
        workspace: Optional :class:`Workspace` instance used for shared
            state.  May be ``None`` while other agents are still
            implementing the project-management layer.
        parent: Optional Qt parent.
    """

    def __init__(
        self,
        workspace: Optional["Workspace"] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MainWindow")
        self.setWindowTitle("Academic Research Suite")
        self.resize(1400, 900)
        self.setMinimumSize(960, 640)

        self._workspace: Optional["Workspace"] = workspace
        self._theme: str = "dark"
        self._pages: Dict[str, QWidget] = {}
        self._current_page_key: Optional[str] = None

        self._build_ui()
        self._wire_signals()
        self._apply_shortcuts()

        # Start on the dashboard.
        self.show_page("dashboard")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # --- Sidebar ----------------------------------------------
        self._sidebar = Sidebar(parent=self)
        self._sidebar.page_changed.connect(self.show_page)

        # --- Central stacked widget -------------------------------
        self._stack = QStackedWidget(self)
        # A small wrapper so the welcome screen can be shown as page 0.
        self._welcome = WelcomeScreen(self)
        self._welcome.on_new_project_clicked.connect(self._on_new_project)
        self._welcome.on_open_project_clicked.connect(self._on_open_project)
        self._welcome.on_search_clicked.connect(lambda: self.show_page("search"))
        self._stack.addWidget(self._welcome)
        # Add a placeholder for each registered page so the stack layout
        # is stable; we'll swap in the real widget lazily on first show.
        for key in _PAGE_REGISTRY:
            placeholder = _PlaceholderPage(key, "Loading…", self)
            self._stack.addWidget(placeholder)
            self._pages[key] = placeholder

        # --- Central host layout ---------------------------------
        central = QWidget(self)
        host = QHBoxLayout(central)
        host.setContentsMargins(0, 0, 0, 0)
        host.setSpacing(0)
        host.addWidget(self._sidebar)
        host.addWidget(self._stack, stretch=1)
        self.setCentralWidget(central)

        # --- Toolbar ----------------------------------------------
        self._toolbar = QToolBar("Main Toolbar", self)
        self._toolbar.setMovable(False)
        self._toolbar.setIconSize(QSize(18, 18))
        self.addToolBar(self._toolbar)

        self._global_search = QLineEdit(self._toolbar)
        self._global_search.setPlaceholderText("Global search…  (Ctrl+K)")
        self._global_search.setMinimumWidth(360)
        self._global_search.returnPressed.connect(self._on_global_search)
        self._toolbar.addWidget(QLabel("  \U0001F50D  ", self._toolbar))
        self._toolbar.addWidget(self._global_search)

        self._toolbar.addSeparator()

        self._ai_provider = QComboBox(self._toolbar)
        self._ai_provider.addItems(["— AI Provider —", "OpenAI", "Anthropic", "Ollama (local)"])
        self._ai_provider.setToolTip("Select the active AI provider")
        self._ai_provider.currentTextChanged.connect(self._on_ai_provider_changed)
        self._toolbar.addWidget(QLabel("  \U0001F916  ", self._toolbar))
        self._toolbar.addWidget(self._ai_provider)

        self._toolbar.addSeparator()

        self._theme_toggle = QAction("\U0001F313  Theme", self)
        self._theme_toggle.setToolTip("Toggle dark/light theme (Ctrl+Shift+T)")
        self._theme_toggle.triggered.connect(self.toggle_theme)
        self._toolbar.addAction(self._theme_toggle)

        # --- Status bar -------------------------------------------
        sb = QStatusBar(self)
        self.setStatusBar(sb)
        self._status_queue = QLabel("\u23F1  Queue: 0", sb)
        self._status_tasks = QLabel("\u2699  Tasks: 0", sb)
        self._status_db = QLabel("\U0001F4BE  DB: 0 KB", sb)
        self._status_log_btn = QAction("\U0001F4DD  Logs", self)
        self._status_log_btn.triggered.connect(self._open_log_viewer)
        sb.addWidget(self._status_queue)
        sb.addWidget(self._status_tasks)
        sb.addWidget(self._status_db)
        sb.addPermanentWidget(self._make_log_button_widget(sb))

        # --- Menu bar ---------------------------------------------
        self._build_menus()

    def _make_log_button_widget(self, parent: QWidget) -> QWidget:
        """Return a small clickable label that opens the log viewer."""
        w = QWidget(parent)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 0, 0, 0)
        btn = QAction("\U0001F4DD  Logs", self)
        btn.triggered.connect(self._open_log_viewer)
        # Re-use a tool button styled as a status-bar item.
        from qtpy.QtWidgets import QToolButton
        tb = QToolButton(parent=w)
        tb.setDefaultAction(btn)
        tb.setAutoRaise(True)
        lay.addWidget(tb)
        return w

    def _build_menus(self) -> None:
        mb = self.menuBar()

        # File menu
        file_menu = mb.addMenu("&File")
        self._act_new = QAction("&New Project…", self)
        self._act_new.setShortcut(QKeySequence("Ctrl+N"))
        self._act_new.triggered.connect(self._on_new_project)
        file_menu.addAction(self._act_new)

        self._act_open = QAction("&Open Project…", self)
        self._act_open.setShortcut(QKeySequence("Ctrl+O"))
        self._act_open.triggered.connect(self._on_open_project)
        file_menu.addAction(self._act_open)

        self._act_save = QAction("&Save Project", self)
        self._act_save.setShortcut(QKeySequence("Ctrl+S"))
        self._act_save.triggered.connect(self._on_save_project)
        file_menu.addAction(self._act_save)

        self._act_export = QAction("&Export…", self)
        self._act_export.setShortcut(QKeySequence("Ctrl+E"))
        self._act_export.triggered.connect(self._on_export)
        file_menu.addAction(self._act_export)

        file_menu.addSeparator()
        self._act_quit = QAction("&Quit", self)
        self._act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        self._act_quit.triggered.connect(self.close)
        file_menu.addAction(self._act_quit)

        # Edit menu
        edit_menu = mb.addMenu("&Edit")
        edit_menu.addAction(QAction("Cut",   self, shortcut=QKeySequence.Cut))
        edit_menu.addAction(QAction("Copy",  self, shortcut=QKeySequence.Copy))
        edit_menu.addAction(QAction("Paste", self, shortcut=QKeySequence.Paste))
        edit_menu.addSeparator()
        act_prefs = QAction("Preferences…", self)
        act_prefs.setShortcut(QKeySequence("Ctrl+,"))
        act_prefs.triggered.connect(lambda: self.show_page("settings"))
        edit_menu.addAction(act_prefs)

        # View menu
        view_menu = mb.addMenu("&View")
        act_theme_dark = QAction("Dark Theme", self, checkable=True)
        act_theme_dark.setChecked(True)
        act_theme_dark.triggered.connect(lambda: self.set_theme("dark"))
        act_theme_light = QAction("Light Theme", self, checkable=True)
        act_theme_light.triggered.connect(lambda: self.set_theme("light"))
        view_menu.addAction(act_theme_dark)
        view_menu.addAction(act_theme_light)

        view_menu.addSeparator()
        act_toggle_sidebar = QAction("Toggle Sidebar", self)
        act_toggle_sidebar.setShortcut(QKeySequence("F9"))
        act_toggle_sidebar.triggered.connect(self._sidebar.toggle_collapse)
        view_menu.addAction(act_toggle_sidebar)

        act_toggle_toolbar = QAction("Toggle Toolbar", self, checkable=True)
        act_toggle_toolbar.setChecked(True)
        act_toggle_toolbar.toggled.connect(self._toolbar.setVisible)
        view_menu.addAction(act_toggle_toolbar)

        # Tools menu
        tools_menu = mb.addMenu("&Tools")
        act_scrape = QAction("New Scrape…", self)
        act_scrape.triggered.connect(lambda: self.show_page("search"))
        tools_menu.addAction(act_scrape)
        act_proxy = QAction("Proxy Manager…", self)
        act_proxy.triggered.connect(lambda: self.show_page("proxy"))
        tools_menu.addAction(act_proxy)
        act_ai = QAction("AI Chat…", self)
        act_ai.triggered.connect(lambda: self.show_page("ai_chat"))
        tools_menu.addAction(act_ai)

        # Help menu
        help_menu = mb.addMenu("&Help")
        act_about = QAction("&About", self)
        act_about.triggered.connect(self._on_about)
        help_menu.addAction(act_about)
        act_docs = QAction("&Documentation", self)
        act_docs.setShortcut(QKeySequence("F1"))
        act_docs.triggered.connect(self._on_docs)
        help_menu.addAction(act_docs)
        act_github = QAction("&GitHub Repository", self)
        act_github.triggered.connect(self._on_github)
        help_menu.addAction(act_github)

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------
    def _apply_shortcuts(self) -> None:
        # Ctrl+K → command palette (we surface search panel as the
        # closest equivalent in this build).
        QShortcut(QKeySequence("Ctrl+K"), self,
                  activated=lambda: self.show_page("search"))
        QShortcut(QKeySequence("Ctrl+F"), self,
                  activated=lambda: self._global_search.setFocus())
        QShortcut(QKeySequence("Ctrl+Shift+T"), self,
                  activated=self.toggle_theme)

    # ------------------------------------------------------------------
    # Page navigation (lazy load)
    # ------------------------------------------------------------------
    def show_page(self, page_key: str) -> None:
        """Switch the central widget to ``page_key``, lazy-loading if needed.

        Args:
            page_key: One of the keys in :data:`_PAGE_REGISTRY`.
        """
        if page_key not in _PAGE_REGISTRY:
            logger.warning("Unknown page_key %r — ignoring.", page_key)
            return
        # Lazy-load on first access.
        widget = self._pages.get(page_key)
        if widget is None or isinstance(widget, _PlaceholderPage):
            widget = self._load_page(page_key)
            if widget is not None:
                idx = self._stack.indexOf(self._pages.get(page_key, widget))
                if idx < 0:
                    idx = self._stack.addWidget(widget)
                else:
                    self._stack.removeWidget(self._pages[page_key])
                    self._stack.insertWidget(idx, widget)
                self._pages[page_key] = widget
        target = self._pages[page_key]
        self._stack.setCurrentWidget(target)
        self._sidebar.set_active(page_key)
        self._current_page_key = page_key

    def _load_page(self, page_key: str) -> Optional[QWidget]:
        """Import the page module and instantiate the widget class."""
        spec = _PAGE_REGISTRY.get(page_key)
        if spec is None:
            return _PlaceholderPage(page_key, "Unknown page.")
        try:
            module = importlib.import_module(spec["module"])
            cls = getattr(module, spec["class"])
            widget = cls(self)
            logger.info("Loaded page %r from %s.%s", page_key,
                        spec["module"], spec["class"])
            return widget
        except Exception as exc:  # pragma: no cover — depends on other agents
            logger.warning(
                "Could not load page %r from %s.%s: %s — using placeholder.",
                page_key, spec["module"], spec["class"], exc,
            )
            return _PlaceholderPage(
                page_key,
                reason=f"Module {spec['module']}.{spec['class']} not available yet.",
                parent=self,
            )

    # ------------------------------------------------------------------
    # Theme management
    # ------------------------------------------------------------------
    def set_theme(self, theme: str) -> None:
        """Apply ``theme`` to the whole application."""
        app = QApplication.instance()
        if app is None:
            logger.warning("No QApplication — cannot apply theme.")
            return
        ModernTheme.apply(app, theme)
        self._theme = theme

    def toggle_theme(self) -> None:
        """Flip between dark and light themes."""
        self.set_theme("light" if self._theme == "dark" else "dark")

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------
    def _wire_signals(self) -> None:
        # Subscribe to global theme changes via the shared ModernTheme
        # singleton instance so downstream widgets can refresh cached
        # colours if needed.
        try:
            from ui.modern_theme import _instance as _theme_instance
            _theme_instance().theme_changed.connect(self._on_theme_changed)
        except Exception:
            logger.debug("Could not subscribe to ModernTheme.theme_changed.")

    def _on_theme_changed(self, theme: str) -> None:
        logger.debug("Theme changed to %s", theme)
        self.update()

    # ------------------------------------------------------------------
    # Menu / toolbar handlers
    # ------------------------------------------------------------------
    def _on_new_project(self) -> None:
        """Handle the "New Project" action."""
        logger.info("New Project requested.")
        # If a project-management dialog is available, defer to it;
        # otherwise just take the user to the dashboard.
        try:
            from ui.dialogs.export_wizard import ExportWizard  # noqa: F401  (lazy probe)
        except Exception:
            pass
        self.show_page("dashboard")

    def _on_open_project(self) -> None:
        """Prompt the user to open an existing project file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project",
            os.path.expanduser("~"),
            "Academic Research Suite Project (*.arsp);;All Files (*)",
        )
        if not path:
            return
        logger.info("Opening project: %s", path)
        # Hand off to project_management.workspace.Workspace if available.
        try:
            from project_management.workspace import Workspace  # type: ignore
            self._workspace = Workspace.load(path)
        except Exception as exc:
            logger.warning("Workspace.load failed (%s) — keeping existing workspace.", exc)
        self.show_page("dashboard")

    def _on_save_project(self) -> None:
        """Save the current project (delegates to Workspace if present)."""
        if self._workspace is None:
            logger.info("No active workspace to save.")
            return
        try:
            save_fn = getattr(self._workspace, "save", None)
            if callable(save_fn):
                save_fn()
                logger.info("Project saved.")
        except Exception:
            logger.exception("Failed to save project.")

    def _on_export(self) -> None:
        """Open the export wizard if available, else fall back to data view."""
        try:
            from ui.dialogs.export_wizard import ExportWizard
            wiz = ExportWizard(self)
            wiz.exec_()
            return
        except Exception:
            pass
        self.show_page("data")

    def _on_global_search(self) -> None:
        """Run a global search using the current text in the search box."""
        text = self._global_search.text().strip()
        if not text:
            return
        logger.info("Global search: %s", text)
        self.show_page("search")

    def _on_ai_provider_changed(self, provider: str) -> None:
        """Persist the selected AI provider into the workspace."""
        logger.info("AI provider set to %s", provider)
        if self._workspace is None:
            return
        try:
            setattr(self._workspace, "ai_provider", provider)
        except Exception:
            logger.exception("Could not set AI provider on workspace.")

    # ------------------------------------------------------------------
    # Status bar updaters
    # ------------------------------------------------------------------
    def set_queue_size(self, size: int) -> None:
        self._status_queue.setText(f"\u23F1  Queue: {size}")

    def set_active_tasks(self, count: int) -> None:
        self._status_tasks.setText(f"\u2699  Tasks: {count}")

    def set_db_size(self, size_bytes: int) -> None:
        """Update the DB-size status chip.

        Args:
            size_bytes: Database file size in bytes (will be formatted).
        """
        if size_bytes < 1024:
            text = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            text = f"{size_bytes / 1024:.1f} KB"
        else:
            text = f"{size_bytes / (1024 * 1024):.1f} MB"
        self._status_db.setText(f"\U0001F4BE  DB: {text}")

    def _open_log_viewer(self) -> None:
        """Open a simple read-only log viewer dialog."""
        try:
            from ui.dialogs.help_dialog import HelpDialog  # noqa: F401
        except Exception:
            pass
        # Defer to a lightweight built-in viewer if a dedicated one is
        # not available yet.
        logger.info("Opening log viewer.")
        try:
            from utils.logger import get_log_path  # type: ignore
            path = get_log_path()
        except Exception:
            path = None
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
            except OSError:
                body = "(could not read log file)"
        else:
            body = "(no log file available yet)"
        from qtpy.QtWidgets import QDialog, QTextEdit, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle("Log Viewer")
        dlg.resize(800, 600)
        v = QVBoxLayout(dlg)
        edit = QTextEdit(dlg)
        edit.setReadOnly(True)
        edit.setPlainText(body[-200_000:])  # cap to last 200k chars
        v.addWidget(edit)
        btn = QPushButton("Close", dlg)
        btn.clicked.connect(dlg.accept)
        v.addWidget(btn)
        dlg.exec_()

    # ------------------------------------------------------------------
    # Help menu handlers
    # ------------------------------------------------------------------
    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About Academic Research Suite",
            (
                "<h3>Academic Research Suite</h3>"
                "<p>An integrated environment for bibliometric discovery, "
                "scraping, analysis, and reporting.</p>"
                "<p style='color:#94A3B8'>MIT License — Copyright (c) 2026</p>"
            ),
        )

    def _on_docs(self) -> None:
        import webbrowser
        # Try the bundled docs first; fall back to the project README.
        docs_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "docs", "user_guide.md",
        )
        if os.path.exists(docs_path):
            webbrowser.open(f"file://{docs_path}")
        else:
            webbrowser.open("https://github.com/academic-research-suite/ars")

    def _on_github(self) -> None:
        import webbrowser
        webbrowser.open("https://github.com/academic-research-suite/ars")

    # ------------------------------------------------------------------
    # Workspace accessor
    # ------------------------------------------------------------------
    def workspace(self) -> Optional["Workspace"]:
        """Return the workspace currently bound to this window."""
        return self._workspace

    def set_workspace(self, workspace: Optional["Workspace"]) -> None:
        """Bind a new workspace instance to the window."""
        self._workspace = workspace

    # ------------------------------------------------------------------
    # Close event
    # ------------------------------------------------------------------
    def closeEvent(self, event):  # noqa: N802 — Qt API
        """Prompt the user to save unsaved changes before closing."""
        if self._has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save changes before quitting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Save:
                self._on_save_project()
                event.accept()
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
                return
        else:
            event.accept()
        # Tear down singleton.
        global _MAIN_WINDOW_INSTANCE
        if _MAIN_WINDOW_INSTANCE is self:
            _MAIN_WINDOW_INSTANCE = None

    def _has_unsaved_changes(self) -> bool:
        """Return ``True`` if the workspace reports unsaved changes."""
        if self._workspace is None:
            return False
        try:
            dirty = getattr(self._workspace, "dirty", None)
            if isinstance(dirty, bool):
                return dirty
            if callable(dirty):
                return bool(dirty())
        except Exception:
            logger.exception("Could not query workspace.dirty.")
        return False


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------
_MAIN_WINDOW_INSTANCE: Optional[MainWindow] = None


def get_main_window(
    workspace: Optional["Workspace"] = None,
    parent: Optional[QWidget] = None,
) -> MainWindow:
    """Return the singleton :class:`MainWindow` instance.

    On the first call, a new :class:`MainWindow` is constructed.  The
    optional ``workspace`` argument is forwarded only on the first
    call; subsequent calls ignore it.

    Args:
        workspace: Optional :class:`Workspace` instance to bind.
        parent: Optional Qt parent (used only on first construction).

    Returns:
        The shared :class:`MainWindow` instance.
    """
    global _MAIN_WINDOW_INSTANCE
    if _MAIN_WINDOW_INSTANCE is None:
        _MAIN_WINDOW_INSTANCE = MainWindow(workspace=workspace, parent=parent)
    elif workspace is not None:
        _MAIN_WINDOW_INSTANCE.set_workspace(workspace)
    return _MAIN_WINDOW_INSTANCE


def reset_main_window() -> None:
    """Destroy the cached singleton — useful in tests."""
    global _MAIN_WINDOW_INSTANCE
    if _MAIN_WINDOW_INSTANCE is not None:
        try:
            _MAIN_WINDOW_INSTANCE.close()
        except Exception:
            pass
        _MAIN_WINDOW_INSTANCE = None
