"""Main application shell for the Academic Research Suite.

The :class:`MainWindow` is a :class:`QMainWindow` that wires together the
sidebar navigation, a central :class:`QStackedWidget` of lazily-loaded
pages, a top toolbar (global search, AI provider selector, theme
toggle), a bottom status bar (scraping queue size, active tasks, DB
size, log viewer button), and the menu bar / keyboard shortcuts.

Pages are loaded lazily on first access — sibling widgets that have
not yet been written by other agents fall back to a friendly
"Coming soon" placeholder so the window is always usable.

Data flow: the window owns a small "data bridge" (:meth:`_push_papers_to_pages`)
that fans the current paper corpus out to every page that exposes a
``set_papers`` API.  It is invoked once at startup (papers loaded from
the database) and again whenever the search panel emits fresh results.

A module-level :func:`get_main_window` accessor returns the singleton
instance (creating it on first call).
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import importlib
import inspect
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

from qtpy.QtCore import Qt, QSize, QTimer
from qtpy.QtGui import QIcon, QKeySequence
from qtpy.QtWidgets import (
    QAction, QActionGroup, QApplication, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QShortcut, QStackedWidget, QStatusBar, QToolBar, QToolButton,
    QTextEdit, QWidget, QVBoxLayout,
)

from ui.modern_theme import ModernTheme
from ui.widgets.sidebar import Sidebar
from ui.welcome_screen import WelcomeScreen

if TYPE_CHECKING:  # pragma: no cover
    from project_management.workspace import Workspace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Page registry: page_key → (module_path, class_name)
# ---------------------------------------------------------------------------
# The factory builds each page lazily inside :meth:`_load_page` so that the
# heavy imports only happen on first access.
#
# NOTE: the in-app Help is intentionally *not* a stack page — it is opened
# as a modal QDialog from the Help menu / sidebar (see :meth:`_on_help_dialog`)
# because a QDialog hidden via accept() can never be re-shown inside a
# QStackedWidget.
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
    # v2.0.0 — added by v2-ui-web
    "bibliometrics":     {"module": "ui.widgets.bibliometric_dashboard", "class": "BibliometricDashboard"},
    "gephi_advanced":    {"module": "ui.widgets.gephi_advanced_view",   "class": "GephiAdvancedView"},
    "systematic_review": {"module": "ui.widgets.systematic_review_view", "class": "SystematicReviewView"},
    "meta_analysis":     {"module": "ui.widgets.meta_analysis_view",      "class": "MetaAnalysisView"},
    "prisma_builder":    {"module": "ui.widgets.prisma_builder",          "class": "PRISMAFlowBuilder"},
    "q1_figures":        {"module": "ui.widgets.q1_figure_studio",        "class": "Q1FigureStudio"},
    "innovation":        {"module": "ui.widgets.innovation_panel",         "class": "InnovationPanel"},
}

#: Pages that should receive the shared paper corpus via ``set_papers``.
_PAPER_PAGES: tuple = ("data", "reports", "bibliometrics", "innovation",
                       "meta_analysis", "analysis")

#: Keys of the quick-action tiles on the dashboard → navigation targets.
_QUICK_ACTION_TARGETS: Dict[str, str] = {
    "new_scrape": "search",
    "ask_ai": "ai_chat",
    "generate_report": "reports",
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
        lay.addWidget(sub)
        lay.addStretch(1)


# ---------------------------------------------------------------------------
# Result normalisation helpers
# ---------------------------------------------------------------------------
def _paper_to_dict(paper: Any) -> Optional[Dict[str, Any]]:
    """Coerce a ``Paper``-like object (or dict) into a plain dict."""
    if isinstance(paper, dict):
        return dict(paper)
    for meth in ("to_dict", "as_dict"):
        fn = getattr(paper, meth, None)
        if callable(fn):
            try:
                data = fn()
                if isinstance(data, dict):
                    return dict(data)
            except Exception:  # noqa: BLE001 — defensive
                logger.debug("paper.%s() failed", meth, exc_info=True)
    # Last resort: public attributes.
    try:
        return {
            k: v for k, v in vars(paper).items()
            if not k.startswith("_") and isinstance(
                v, (str, int, float, bool, list, tuple, type(None)))
        }
    except TypeError:
        return None


def normalize_papers(payload: Any) -> List[Dict[str, Any]]:
    """Normalise any search-result payload into ``list[dict]``.

    Accepts: :class:`ScraperResult`-like objects (``.papers``), plain
    lists of papers, ``{"papers": [...]}`` / ``{"results": [...]}``
    dicts, or ``None``.
    """
    if payload is None:
        return []
    raw: Any = payload
    papers_attr = getattr(payload, "papers", None)
    if papers_attr is not None and not isinstance(payload, dict):
        raw = papers_attr
    elif isinstance(payload, dict):
        raw = payload.get("papers", payload.get("results", payload))
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    out: List[Dict[str, Any]] = []
    for p in list(raw):
        d = _paper_to_dict(p)
        if d:
            out.append(d)
    return out


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
        self._current_papers: List[Dict[str, Any]] = []
        self._db: Optional[Any] = None

        self._build_ui()
        self._build_menus()
        self._wire_signals()
        self._apply_shortcuts()

        # Restore the persisted theme (falls back to dark).
        self.set_theme(self._load_theme_preference(), persist=False)

        # Start on the welcome screen; it stays reachable via the
        # "Home" nav item until the first project is opened.
        self.show_page("welcome")

        # Status-bar refresh timer (Queue / Tasks / DB chips).
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._refresh_status_chips)
        self._status_timer.start()

        # Defer the initial DB load until the window is visible.
        QTimer.singleShot(0, self._load_initial_data)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # --- Sidebar ----------------------------------------------
        self._sidebar = Sidebar(parent=self)
        self._sidebar.page_changed.connect(self.show_page)

        # --- Central stacked widget -------------------------------
        self._stack = QStackedWidget(self)
        # The welcome screen lives at stack index 0 and is reachable
        # through the "Home" sidebar entry.
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
        self._global_search.setPlaceholderText(
            "Search the literature…  (Enter to run, Ctrl+Shift+F to focus)")
        self._global_search.setMinimumWidth(360)
        self._global_search.setClearButtonEnabled(True)
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
        sb.addWidget(self._status_queue)
        sb.addWidget(self._status_tasks)
        sb.addWidget(self._status_db)
        sb.addPermanentWidget(self._make_log_button_widget(sb))
        sb.showMessage("Ready.", 5000)

        # Seed the AI-provider selector from settings.
        try:
            from config.settings import get_settings
            provider = (get_settings().ai_provider or "none").lower()
            idx = {"openai": 1, "anthropic": 2, "ollama": 3}.get(provider, 0)
            self._ai_provider.setCurrentIndex(idx)
        except Exception:  # noqa: BLE001 — settings are optional at boot
            logger.debug("Could not seed AI provider selector.", exc_info=True)

    def _make_log_button_widget(self, parent: QWidget) -> QWidget:
        """Return a small clickable label that opens the log viewer."""
        w = QWidget(parent)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 0, 0, 0)
        self._act_logs = QAction("\U0001F4DD  Logs", self)
        self._act_logs.setToolTip("Open the application log viewer (Ctrl+L)")
        self._act_logs.triggered.connect(self._open_log_viewer)
        tb = QToolButton(parent=w)
        tb.setDefaultAction(self._act_logs)
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
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._act_theme_dark = QAction("Dark Theme", self, checkable=True)
        self._act_theme_light = QAction("Light Theme", self, checkable=True)
        self._act_theme_system = QAction("System Theme", self, checkable=True)
        for act, name in (
            (self._act_theme_dark, "dark"),
            (self._act_theme_light, "light"),
            (self._act_theme_system, "system"),
        ):
            act.setActionGroup(self._theme_group)
            act.triggered.connect(lambda _checked=False, n=name: self.set_theme(n))
            view_menu.addAction(act)

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
        tools_menu.addSeparator()
        act_reporting = QAction("Report Wizard…", self)
        act_reporting.triggered.connect(self._on_report_wizard)
        tools_menu.addAction(act_reporting)
        act_log = QAction("Log Viewer…", self)
        act_log.triggered.connect(self._open_log_viewer)
        tools_menu.addAction(act_log)

        # Help menu
        help_menu = mb.addMenu("&Help")
        act_help = QAction("Help Contents…", self)
        act_help.setShortcut(QKeySequence("F1"))
        act_help.triggered.connect(self._on_help_dialog)
        help_menu.addAction(act_help)
        act_about = QAction("&About", self)
        act_about.triggered.connect(self._on_about)
        help_menu.addAction(act_about)
        act_docs = QAction("&Documentation", self)
        act_docs.triggered.connect(self._on_docs)
        help_menu.addAction(act_docs)
        act_github = QAction("&GitHub Repository", self)
        act_github.triggered.connect(self._on_github)
        help_menu.addAction(act_github)

    # ------------------------------------------------------------------
    # Keyboard shortcuts (documented in ui.dialogs.help_dialog.SHORTCUTS)
    # ------------------------------------------------------------------
    def _apply_shortcuts(self) -> None:
        # Ctrl+K → jump to the search page query field.
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._focus_search_query)
        # Ctrl+Shift+F → focus the global toolbar search.
        QShortcut(QKeySequence("Ctrl+Shift+F"), self,
                  activated=self._global_search.setFocus)
        # Ctrl+Shift+T → toggle theme.
        QShortcut(QKeySequence("Ctrl+Shift+T"), self, activated=self.toggle_theme)
        # F5 → run the analysis on the Analysis page.
        QShortcut(QKeySequence("F5"), self, activated=self._run_current_analysis)
        # Esc → cancel the running background task (search / analysis).
        QShortcut(QKeySequence("Esc"), self, activated=self._cancel_active_task)
        # Ctrl+Shift+K → clear chat history.
        QShortcut(QKeySequence("Ctrl+Shift+K"), self, activated=self._clear_chat_history)
        # Ctrl+R → refresh the proxy pool.
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self._refresh_proxy_pool)
        # Ctrl+B → toggle sidebar.
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self._sidebar.toggle_collapse)
        # Ctrl+L → open the log viewer.
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self._open_log_viewer)

    # ------------------------------------------------------------------
    # Page navigation (lazy load)
    # ------------------------------------------------------------------
    def show_page(self, page_key: str) -> None:
        """Switch the central widget to ``page_key``, lazy-loading if needed.

        The special keys ``welcome`` and ``help`` are handled inline:
        ``welcome`` shows the onboarding screen; ``help`` opens the Help
        dialog modally (a QDialog cannot live inside a QStackedWidget).

        Args:
            page_key: One of the keys in :data:`_PAGE_REGISTRY`, or
                ``"welcome"`` / ``"help"``.
        """
        if page_key == "help":
            self._on_help_dialog()
            return
        if page_key == "welcome":
            self._stack.setCurrentWidget(self._welcome)
            self._sidebar.set_active("welcome")
            self._current_page_key = "welcome"
            return
        if page_key not in _PAGE_REGISTRY:
            logger.warning("Unknown page_key %r — ignoring.", page_key)
            return
        self._ensure_page_loaded(page_key)
        target = self._pages[page_key]
        self._stack.setCurrentWidget(target)
        self._sidebar.set_active(page_key)
        self._current_page_key = page_key

    def _ensure_page_loaded(self, page_key: str) -> Optional[QWidget]:
        """Lazily build ``page_key`` and swap it into the stack in place.

        Returns the real widget, or ``None`` if only a placeholder could
        be shown.  Replaced placeholder pages are destroyed via
        ``deleteLater`` so the swap does not leak memory.
        """
        widget = self._pages.get(page_key)
        if widget is not None and not isinstance(widget, _PlaceholderPage):
            return widget
        new_widget = self._load_page(page_key)
        if new_widget is None:
            return None
        old = self._pages.get(page_key)
        idx = self._stack.indexOf(old) if old is not None else -1
        if idx < 0:
            idx = self._stack.addWidget(new_widget)
        else:
            self._stack.removeWidget(old)
            self._stack.insertWidget(idx, new_widget)
            if old is not None:
                old.deleteLater()  # free the replaced placeholder
        self._pages[page_key] = new_widget
        return new_widget

    def _load_page(self, page_key: str) -> Optional[QWidget]:
        """Import the page module and instantiate the widget class.

        The constructor is called keyword-aware: pages whose ``__init__``
        accepts a ``parent`` argument get ``parent=self``; pages with a
        different first parameter (e.g. ``AIChatWidget(project_id, …)``)
        are constructed with keyword arguments only so the window object
        is never mistaken for a ``project_id``.
        """
        spec = _PAGE_REGISTRY.get(page_key)
        if spec is None:
            return _PlaceholderPage(page_key, "Unknown page.")
        try:
            module = importlib.import_module(spec["module"])
            cls = getattr(module, spec["class"])
            widget = self._instantiate_page(cls)
            self._connect_page_signals(page_key, widget)
            # Feed the shared corpus to freshly created data pages.
            self._push_papers_to_pages(self._current_papers, pages=[widget])
            logger.info("Loaded page %r from %s.%s", page_key,
                        spec["module"], spec["class"])
            return widget
        except Exception as exc:  # pragma: no cover — depends on other agents
            logger.warning(
                "Could not load page %r from %s.%s: %s — using placeholder.",
                page_key, spec["module"], spec["class"], exc,
            )
            self.statusBar().showMessage(
                f"Page '{page_key}' unavailable: {exc}", 8000)
            return _PlaceholderPage(
                page_key,
                reason=f"Module {spec['module']}.{spec['class']} not available yet.",
                parent=self,
            )

    def _instantiate_page(self, cls: type) -> QWidget:
        """Instantiate a page class with keyword-aware arguments.

        Pages whose ``__init__`` accepts a ``parent`` keyword get
        ``parent=self``; pages with a different first parameter (e.g.
        ``AIChatWidget(project_id, parent)``) still receive ``parent``
        *by keyword*, so the window is never mistaken for a
        ``project_id``.
        """
        try:
            params = inspect.signature(cls.__init__).parameters
        except (TypeError, ValueError):  # pragma: no cover — defensive
            params = {}
        if "parent" in params:
            return cls(parent=self)
        return cls()

    # ------------------------------------------------------------------
    # Per-page signal wiring (called once per page at load time)
    # ------------------------------------------------------------------
    def _connect_page_signals(self, page_key: str, widget: QWidget) -> None:
        """Wire the cross-page signals of a freshly loaded page."""
        if page_key == "dashboard":
            qt = getattr(widget, "quick_action", None)
            if qt is not None:
                try:
                    qt.connect(self._on_quick_action)
                except Exception:  # noqa: BLE001
                    logger.debug("dashboard.quick_action connect failed.",
                                 exc_info=True)
        elif page_key == "search":
            rr = getattr(widget, "results_ready", None)
            if rr is not None:
                try:
                    rr.connect(self._on_search_results)
                except Exception:  # noqa: BLE001
                    logger.debug("search.results_ready connect failed.",
                                 exc_info=True)
            ap = getattr(widget, "add_to_project", None)
            if ap is not None:
                try:
                    ap.connect(self._on_add_result_to_project)
                except Exception:  # noqa: BLE001
                    logger.debug("search.add_to_project connect failed.",
                                 exc_info=True)
        elif page_key == "data":
            ap = getattr(widget, "add_to_project_requested", None)
            if ap is not None:
                try:
                    ap.connect(self._on_add_papers_to_project)
                except Exception:  # noqa: BLE001
                    logger.debug("data.add_to_project_requested connect failed.",
                                 exc_info=True)
            sm = getattr(widget, "status_message", None)
            if sm is not None:
                try:
                    sm.connect(self._status_message)
                except Exception:  # noqa: BLE001
                    logger.debug("data.status_message connect failed.",
                                 exc_info=True)
        elif page_key == "reports":
            rg = getattr(widget, "report_generated", None)
            if rg is not None:
                try:
                    rg.connect(lambda path: self._status_message(
                        f"Report generated: {path}"))
                except Exception:  # noqa: BLE001
                    logger.debug("reports.report_generated connect failed.",
                                 exc_info=True)
        elif page_key == "settings":
            ss = getattr(widget, "settings_saved", None)
            if ss is not None:
                try:
                    ss.connect(self._on_settings_saved)
                except Exception:  # noqa: BLE001
                    logger.debug("settings.settings_saved connect failed.",
                                 exc_info=True)

    # ------------------------------------------------------------------
    # Data bridge — fans the shared corpus out to every data page
    # ------------------------------------------------------------------
    def _push_papers_to_pages(
        self,
        papers: Sequence[Dict[str, Any]],
        pages: Optional[Sequence[QWidget]] = None,
    ) -> None:
        """Push ``papers`` into every page exposing ``set_papers``.

        Args:
            papers: The paper dicts to distribute.
            pages: Optional explicit list of widgets; defaults to all
                currently-loaded pages in :data:`_PAPER_PAGES`.
        """
        records = list(papers)
        targets: List[QWidget] = []
        if pages is not None:
            targets = list(pages)
        else:
            for key in _PAPER_PAGES:
                w = self._pages.get(key)
                if w is not None and not isinstance(w, _PlaceholderPage):
                    targets.append(w)
        for w in targets:
            setter = getattr(w, "set_papers", None)
            if not callable(setter):
                continue
            try:
                setter(records)
            except Exception:  # noqa: BLE001 — never break the bridge
                logger.exception("set_papers failed on %s", type(w).__name__)

    # ------------------------------------------------------------------
    # Startup data load
    # ------------------------------------------------------------------
    def _get_db(self) -> Optional[Any]:
        """Return (creating on first use) the shared DatabaseConnection."""
        if self._db is None:
            try:
                from database.connection import DatabaseConnection
                self._db = DatabaseConnection()
            except Exception as exc:  # noqa: BLE001
                logger.warning("DatabaseConnection unavailable: %s", exc)
        return self._db

    def _load_initial_data(self) -> None:
        """Load the paper corpus from the DB and seed all summary views."""
        papers: List[Dict[str, Any]] = []
        db = self._get_db()
        if db is not None:
            list_papers = getattr(db, "list_papers", None)
            if callable(list_papers):
                try:
                    papers = normalize_papers(list_papers(limit=500))
                except TypeError:
                    try:
                        papers = normalize_papers(list_papers())
                    except Exception:  # noqa: BLE001
                        logger.exception("list_papers failed.")
                except Exception:  # noqa: BLE001
                    logger.exception("list_papers failed.")
        self._current_papers = papers

        # Pre-load the two lightweight data pages so they show the corpus.
        for key in ("data", "reports"):
            self._ensure_page_loaded(key)
        self._push_papers_to_pages(papers)

        # Dashboard stats.
        dash = self._pages.get("dashboard")
        if dash is not None and not isinstance(dash, _PlaceholderPage):
            try:
                authors = {
                    a.strip() for p in papers
                    for a in (p.get("authors") if isinstance(p.get("authors"), list)
                              else [p.get("authors")] if p.get("authors") else [])
                    if isinstance(a, str) and a.strip()
                }
                projects = 0
                try:
                    from project_management.project_manager import ProjectManager
                    projects = len(ProjectManager(self._get_db()).list_projects())
                except Exception:  # noqa: BLE001
                    logger.debug("ProjectManager count unavailable.", exc_info=True)
                dash.set_stats(len(papers), len(authors), projects, None)
                dash.set_recent_papers(papers[:10])
            except Exception:  # noqa: BLE001
                logger.exception("Dashboard seeding failed.")

        # Welcome screen chips + recent projects.
        try:
            self._welcome.set_db_status(f"{len(papers)} papers" if papers
                                        else "empty")
            try:
                from proxy.proxy_pool import ProxyPool
                pool = ProxyPool()
                n = len(pool.list_proxies()) if hasattr(pool, "list_proxies") else 0
                self._welcome.set_proxy_status(n)
            except Exception:  # noqa: BLE001
                self._welcome.set_proxy_status(0)
            try:
                from config.settings import get_settings
                self._welcome.set_ai_provider(get_settings().ai_provider)
            except Exception:  # noqa: BLE001
                pass
            try:
                from project_management.project_manager import ProjectManager
                recents = ProjectManager(self._get_db()).list_projects()
                self._welcome.set_recent_projects(
                    recents if isinstance(recents, list) else [])
            except Exception:  # noqa: BLE001
                logger.debug("Recent projects unavailable.", exc_info=True)
        except Exception:  # noqa: BLE001
            logger.exception("Welcome screen seeding failed.")

    # ------------------------------------------------------------------
    # Cross-page slots
    # ------------------------------------------------------------------
    def _on_quick_action(self, action: str) -> None:
        """Handle a dashboard quick-action tile click."""
        if action == "new_project":
            self._on_new_project()
            return
        target = _QUICK_ACTION_TARGETS.get(action)
        if target:
            self.show_page(target)
        else:
            logger.warning("Unknown quick action %r", action)

    def _on_search_results(self, payload: Any) -> None:
        """Fan fresh search results out to every data page."""
        papers = normalize_papers(payload)
        self._current_papers = papers
        self._push_papers_to_pages(papers)
        self._status_message(f"Search complete — {len(papers)} papers "
                             f"loaded into Data / Reports / Analysis.")

    def _on_add_result_to_project(self, paper: Any) -> None:
        """Insert a search-result card's paper into the library (DB)."""
        self._on_add_papers_to_project([paper])

    def _on_add_papers_to_project(self, papers: Any) -> None:
        """Insert one or more papers into the library via ``db.add_paper``.

        Accepts a list/tuple of paper dicts (DataView context menu) or a
        single paper object (search-panel cards).  ``add_paper`` itself
        publishes the ``paper_added`` event, so the dashboard activity
        feed updates without a duplicate manual publish here.
        """
        if papers is None:
            return
        if not isinstance(papers, (list, tuple)):
            papers = [papers]
        db = self._get_db()
        add_paper = getattr(db, "add_paper", None) if db else None
        if not callable(add_paper):
            self._status_message("Database unavailable — paper not saved.")
            logger.warning("add_to_project: DatabaseConnection.add_paper missing.")
            return
        added: List[Dict[str, Any]] = []
        failures = 0
        for paper in papers:
            record = _paper_to_dict(paper)
            if not record:
                failures += 1
                continue
            try:
                new_id = add_paper(record)
                record.setdefault("id", new_id)
                added.append(record)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                logger.exception("add_paper failed.")
                if len(papers) == 1:
                    QMessageBox.warning(self, "Add to Project",
                                        f"Could not save the paper:\n{exc}")
        if not added:
            if failures and len(papers) > 1:
                self._status_message(
                    f"Could not save {failures} paper(s) — see logs.")
            elif not failures:
                self._status_message(
                    "Could not read the paper record — not saved.")
            return
        titles = ", ".join(
            str(r.get("title", "(untitled)")).strip()[:40]
            for r in added[:2])
        more = f" (+{len(added) - 2} more)" if len(added) > 2 else ""
        msg = f"Added {len(added)} paper(s) to the library: {titles}{more}."
        if failures:
            msg += f" {failures} skipped."
        self._status_message(msg)
        # Keep the data pages in sync with the new library state.
        merged = list(self._current_papers)
        merged[:0] = added
        self._current_papers = merged
        self._push_papers_to_pages(merged)

    def _on_settings_saved(self, settings: Dict[str, Any]) -> None:
        """React to a settings save (apply theme immediately)."""
        theme = str(settings.get("theme", "") or "")
        if theme and theme != self._theme:
            self.set_theme(theme)
        self._status_message("Settings saved.")

    # ------------------------------------------------------------------
    # Theme management
    # ------------------------------------------------------------------
    @staticmethod
    def _load_theme_preference() -> str:
        """Read the persisted theme from the config (default ``dark``)."""
        try:
            from utils.config_manager import ConfigManager
            cfg = ConfigManager()
            theme = cfg.get("theme", None)
            if theme is None:
                # ``theme_name`` is a native Settings field — read it as a
                # fallback for builds where the flat ``theme`` key is not
                # yet registered.
                theme = cfg.get("theme_name", "dark")
                if isinstance(theme, str) and theme.startswith("modern_"):
                    theme = theme.replace("modern_", "")
            return str(theme or "dark").lower()
        except Exception:  # noqa: BLE001 — config layer is optional
            return "dark"

    def set_theme(self, theme: str, persist: bool = True) -> None:
        """Apply ``theme`` to the whole application.

        Args:
            theme: ``"dark"``, ``"light"`` or ``"system"``.
            persist: When ``True`` the choice is written to the
                :class:`ConfigManager`` (key ``theme``).
        """
        app = QApplication.instance()
        if app is None:
            logger.warning("No QApplication — cannot apply theme.")
            return
        ModernTheme.apply(app, theme)
        self._theme = theme
        self._sync_theme_actions()
        if persist:
            try:
                from utils.config_manager import ConfigManager
                cfg = ConfigManager()
                # Contract key (P-a registers flat ``theme``).
                cfg.set("theme", theme, persist=True)
                # Mirror into the native Settings field so the choice
                # already persists on builds without the flat key.
                cfg.set("theme_name", f"modern_{theme}", persist=True)
            except Exception:  # noqa: BLE001
                logger.debug("Could not persist theme choice.", exc_info=True)

    def _sync_theme_actions(self) -> None:
        """Keep the View-menu theme actions in sync with the active theme."""
        mapping = {
            "dark": self._act_theme_dark,
            "light": self._act_theme_light,
            "system": self._act_theme_system,
        }
        act = mapping.get(self._theme)
        if act is not None and not act.isChecked():
            act.setChecked(True)

    def toggle_theme(self) -> None:
        """Flip between dark and light themes."""
        self.set_theme("light" if self._theme != "light" else "dark")

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
        """Handle the "New Project" action — delegate to ProjectExplorer."""
        self.show_page("projects")
        explorer = self._pages.get("projects")
        if explorer is not None and not isinstance(explorer, _PlaceholderPage):
            handler = getattr(explorer, "_on_new_project", None)
            if callable(handler):
                handler()
            else:
                self._status_message("Use “New Project” in the Projects page.")
        else:
            self._status_message("Projects page unavailable in this build.")

    def _on_open_project(self) -> None:
        """Prompt the user to open an existing project file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Project",
            os.path.expanduser("~"),
            "Academic Research Suite Project (*.arsp *.json);;All Files (*)",
        )
        if not path:
            return
        logger.info("Opening project: %s", path)
        # project_management.workspace.Workspace(db, path) — the real API.
        try:
            from project_management.workspace import Workspace  # type: ignore
            self._workspace = Workspace(path=Path(path))
            self._status_message(f"Opened project: {Path(path).name}")
        except Exception as exc:
            logger.warning("Workspace open failed (%s) — keeping existing workspace.", exc)
            QMessageBox.warning(
                self, "Open Project",
                f"Could not open the project file:\n{exc}")
            return
        self.show_page("projects")
        explorer = self._pages.get("projects")
        refresh = getattr(explorer, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:  # noqa: BLE001
                logger.debug("ProjectExplorer refresh failed.", exc_info=True)

    def _on_save_project(self) -> None:
        """Save the current project (delegates to Workspace if present)."""
        if self._workspace is None:
            self._status_message("No active workspace to save.")
            return
        try:
            save_fn = getattr(self._workspace, "save", None)
            if callable(save_fn):
                save_fn()
                self._status_message("Project saved.")
                logger.info("Project saved.")
            else:
                self._status_message("Workspace does not support saving.")
        except Exception:
            logger.exception("Failed to save project.")
            QMessageBox.warning(self, "Save Project",
                                "Saving the project failed — see logs.")

    def _on_export(self) -> None:
        """Open the export wizard pre-loaded with the current papers."""
        papers = self._current_papers
        if not papers:
            db = self._get_db()
            list_papers = getattr(db, "list_papers", None) if db else None
            if callable(list_papers):
                try:
                    papers = normalize_papers(list_papers(limit=500))
                except Exception:  # noqa: BLE001
                    logger.exception("Could not load papers for export.")
        try:
            from ui.dialogs.export_wizard import ExportWizard
            wiz = ExportWizard(self, data=papers or None)
            wiz.exec_()
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Export wizard unavailable.")
            self._status_message(f"Export wizard unavailable: {exc}")
        self.show_page("data")

    def _on_report_wizard(self) -> None:
        """Open the ReportingDashboard wizard with the current corpus."""
        try:
            from ui.dialogs.reporting_dashboard import ReportingDashboard
        except Exception as exc:  # noqa: BLE001
            logger.exception("Reporting wizard unavailable.")
            self._status_message(f"Report wizard unavailable: {exc}")
            return
        dlg = ReportingDashboard(self, data=self._current_papers or None)
        dlg.exec_()

    def _on_global_search(self) -> None:
        """Route the toolbar query to the search page and run it."""
        text = self._global_search.text().strip()
        if not text:
            return
        logger.info("Global search: %s", text)
        self.show_page("search")
        panel = self._pages.get("search")
        if panel is not None and not isinstance(panel, _PlaceholderPage):
            runner = getattr(panel, "run_search", None)
            if callable(runner):
                try:
                    runner(text)
                    return
                except Exception:  # noqa: BLE001
                    logger.exception("Global search dispatch failed.")
            setter = getattr(panel, "query_input", None)
            if setter is not None:
                setter.setText(text)
        else:
            self._status_message("Search page unavailable in this build.")

    def _focus_search_query(self) -> None:
        """Ctrl+K — jump to the search page and focus its query field."""
        self.show_page("search")
        panel = self._pages.get("search")
        query_input = getattr(panel, "query_input", None)
        if query_input is not None:
            query_input.setFocus()

    def _on_ai_provider_changed(self, provider: str) -> None:
        """Persist the selected AI provider into the settings."""
        logger.info("AI provider set to %s", provider)
        key = {"OpenAI": "openai", "Anthropic": "anthropic",
               "Ollama (local)": "ollama"}.get(provider)
        if key is None:
            return
        try:
            from utils.config_manager import ConfigManager
            ConfigManager().set("ai_provider", key, persist=True)
            self._status_message(f"AI provider set to {provider} — "
                                 f"re-open AI Chat to apply.")
        except Exception:  # noqa: BLE001
            logger.exception("Could not persist AI provider choice.")

    # ------------------------------------------------------------------
    # Shortcut helpers (F5 / Esc / Ctrl+Shift+K / Ctrl+R)
    # ------------------------------------------------------------------
    def _active_page(self) -> Optional[QWidget]:
        """Return the loaded widget for the current page (or None)."""
        key = self._current_page_key
        if not key:
            return None
        w = self._pages.get(key)
        return w if w is not None and not isinstance(w, _PlaceholderPage) else None

    def _run_current_analysis(self) -> None:
        """F5 — run the analysis on the Analysis page."""
        self.show_page("analysis")
        page = self._pages.get("analysis")
        run = getattr(page, "_on_run", None)
        if callable(run):
            try:
                run()
            except Exception:  # noqa: BLE001
                logger.exception("F5 analysis run failed.")
        else:
            self._status_message("Analysis page unavailable in this build.")

    def _cancel_active_task(self) -> None:
        """Esc — cancel the running search / analysis task, if any."""
        for key in ("search", "analysis"):
            page = self._pages.get(key)
            if page is None or isinstance(page, _PlaceholderPage):
                continue
            cancel = getattr(page, "_on_cancel", None)
            busy_btn = getattr(page, "search_button", None) or \
                getattr(page, "run_button", None)
            if cancel is not None and busy_btn is not None:
                if not busy_btn.isEnabled():
                    try:
                        cancel()
                        self._status_message("Cancellation requested…")
                        return
                    except Exception:  # noqa: BLE001
                        logger.exception("Cancel failed on %s.", key)

    def _clear_chat_history(self) -> None:
        """Ctrl+Shift+K — clear the AI chat history."""
        self.show_page("ai_chat")
        page = self._pages.get("ai_chat")
        clear = getattr(page, "_on_clear_history", None)
        if callable(clear):
            try:
                clear()
            except Exception:  # noqa: BLE001
                logger.exception("Clear chat history failed.")
        else:
            self._status_message("AI Chat page unavailable in this build.")

    def _refresh_proxy_pool(self) -> None:
        """Ctrl+R — refresh the proxy pool."""
        self.show_page("proxy")
        page = self._pages.get("proxy")
        refresh = getattr(page, "_on_refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:  # noqa: BLE001
                logger.exception("Proxy refresh failed.")
        else:
            self._status_message("Proxy page unavailable in this build.")

    # ------------------------------------------------------------------
    # Status bar updaters
    # ------------------------------------------------------------------
    def _status_message(self, text: str, timeout: int = 8000) -> None:
        """Show a transient message in the status bar (error surfacing)."""
        logger.info(text) if timeout > 0 else logger.debug(text)
        self.statusBar().showMessage(text, timeout)

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

    def _refresh_status_chips(self) -> None:
        """Periodically refresh Queue / Tasks / DB chips.

        * Tasks — number of active worker threads in the shared
          :class:`~utils.workers.WorkerPool`.
        * Queue — number of pages currently running a background task
          (search / analysis / proxy refresh).
        * DB — size of the SQLite file on disk.
        """
        tasks = 0
        try:
            from utils.workers import WorkerPool
            tasks = WorkerPool.instance().active_count()
        except Exception:  # noqa: BLE001
            logger.debug("WorkerPool count unavailable.", exc_info=True)
        self.set_active_tasks(tasks)

        queue = 0
        for key, btn_attr in (("search", "search_button"),
                              ("analysis", "run_button"),
                              ("proxy", "refresh_button")):
            page = self._pages.get(key)
            if page is None or isinstance(page, _PlaceholderPage):
                continue
            btn = getattr(page, btn_attr, None)
            if btn is not None and not btn.isEnabled():
                queue += 1
        self.set_queue_size(queue)

        try:
            from config.settings import get_settings
            db_path = get_settings().resolve_path("db_path")
            size = db_path.stat().st_size if db_path.exists() else 0
        except Exception:  # noqa: BLE001
            size = 0
        self.set_db_size(size)

    def _open_log_viewer(self) -> None:
        """Open a read-only log viewer dialog for the application log."""
        logger.info("Opening log viewer.")
        path = self._resolve_log_path()
        body = "(no log file available yet)"
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
            except OSError:
                body = "(could not read log file)"
        else:
            body = body if path is None else \
                f"(log file not created yet:\n{path})"
        dlg = _LogViewerDialog(path, body, self)
        dlg.exec_()

    @staticmethod
    def _resolve_log_path() -> Optional[str]:
        """Return the path of the rotating application log file.

        Prefers ``utils.logger.get_log_path()`` (added by the core
        agent); falls back to the canonical ``<project>/logs/ars.log``
        location used by :mod:`utils.logger`.
        """
        try:
            from utils.logger import get_log_path  # type: ignore
            p = get_log_path()
            if p:
                return str(p)
        except Exception:  # noqa: BLE001 — helper may not exist yet
            pass
        root = Path(__file__).resolve().parent.parent
        return str(root / "logs" / "ars.log")

    # ------------------------------------------------------------------
    # Help menu handlers
    # ------------------------------------------------------------------
    def _on_help_dialog(self) -> None:
        """Open the in-app help as a modal dialog."""
        try:
            from ui.dialogs.help_dialog import HelpDialog
            HelpDialog(self).exec_()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Help dialog failed to open.")
            QMessageBox.warning(self, "Help",
                                f"Help is unavailable:\n{exc}")

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About Academic Research Suite",
            (
                "<h3>Academic Research Suite</h3>"
                "<p>An integrated environment for bibliometric discovery, "
                "scraping, analysis, and reporting.</p>"
                f"<p style='color:{ModernTheme.DARK_TEXT_MUTED}'>"
                "MIT License — Copyright (c) 2026</p>"
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
            webbrowser.open("https://github.com/thelonecoders/Sophidan")

    def _on_github(self) -> None:
        import webbrowser
        webbrowser.open("https://github.com/thelonecoders/Sophidan")

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
        """Prompt the user to save unsaved changes, then tear down pages."""
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
        if not event.isAccepted():
            return
        # Give every loaded page a chance to stop background workers
        # (e.g. the AI-chat streaming thread) before the window dies.
        for key, widget in list(self._pages.items()):
            if widget is None or isinstance(widget, _PlaceholderPage):
                continue
            shutdown = getattr(widget, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:  # noqa: BLE001
                    logger.debug("shutdown() failed on %s", key, exc_info=True)
        self._status_timer.stop()
        # Tear down singleton.
        global _MAIN_WINDOW_INSTANCE
        if _MAIN_WINDOW_INSTANCE is self:
            _MAIN_WINDOW_INSTANCE = None

    def _has_unsaved_changes(self) -> bool:
        """Return ``True`` if the workspace reports unsaved changes.

        The workspace only exposes a dirty flag when one is trivially
        available; otherwise we never nag the user on quit.
        """
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
# Log viewer dialog
# ---------------------------------------------------------------------------
class _LogViewerDialog(QDialog):
    """Read-only log viewer shown by :meth:`MainWindow._open_log_viewer`."""

    def __init__(self, log_path: Optional[str], body: str,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Log Viewer")
        self.resize(820, 600)
        v = QVBoxLayout(self)
        if log_path:
            path_label = QLabel(f"Log file: <code>{log_path}</code>", self)
            path_label.setTextFormat(Qt.RichText)
            v.addWidget(path_label)
        edit = QTextEdit(self)
        edit.setReadOnly(True)
        edit.setPlainText(body[-200_000:])  # cap to last 200k chars
        v.addWidget(edit)
        btn = QPushButton("Close", self)
        btn.clicked.connect(self.accept)
        v.addWidget(btn)


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
