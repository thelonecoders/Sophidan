"""In-app help dialog.

Provides :class:`HelpDialog` — a modal QDialog with five tabs (Quick Start,
Keyboard Shortcuts, FAQ, About, License). Includes a searchable shortcuts
table, accordion-style FAQ, full MIT license text, and links/credits.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from qtpy.QtCore import Qt
from qtpy.QtGui import QFont, QTextOption
from qtpy.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# (action, shortcut) tuples for the shortcuts table.
SHORTCUTS: List[Tuple[str, str]] = [
    ("New Project", "Ctrl+N"),
    ("Open Project…", "Ctrl+O"),
    ("Save Project", "Ctrl+S"),
    ("Search", "Ctrl+F"),
    ("Advanced Search…", "Ctrl+Shift+F"),
    ("Run Analysis", "F5"),
    ("Cancel Running Task", "Esc"),
    ("Send Chat Message", "Ctrl+Enter"),
    ("Clear Chat History", "Ctrl+Shift+K"),
    ("Refresh Proxy Pool", "Ctrl+R"),
    ("Export…", "Ctrl+E"),
    ("Open Settings", "Ctrl+,"),
    ("Toggle Sidebar", "Ctrl+B"),
    ("Toggle Log Viewer", "Ctrl+L"),
    ("Open Help", "F1"),
    ("Quit", "Ctrl+Q"),
]

# (question, answer) tuples for the FAQ accordion.
FAQ: List[Tuple[str, str]] = [
    (
        "How do I create a new research project?",
        "Go to File > New Project… (Ctrl+N), enter a name and pick a parent "
        "directory. A project folder will be created to store datasets, "
        "snapshots and analysis results.",
    ),
    (
        "Which data sources are supported?",
        "arXiv, PubMed, OpenAlex, Semantic Scholar, Google Scholar, "
        "Crossref, DBLP and ORCID. Pick one or many in the Sources row of "
        "the Search panel.",
    ),
    (
        "Why am I getting blocked by a source?",
        "Most academic sources rate-limit aggressive requests. Enable the "
        "proxy pool (Tools > Proxy Management) and rotate proxies to "
        "distribute load.",
    ),
    (
        "How does the AI assistant work?",
        "The AI Chat panel uses your configured provider (Ollama local, "
        "OpenAI or Anthropic). Enable 'Use RAG' to ground answers in your "
        "loaded papers via the embedded vector store.",
    ),
    (
        "Where is my data stored?",
        "By default in the 'data/' directory under the application root. "
        "Change this in Settings > General > Data dir. Each project gets its "
        "own subfolder under data/projects/{project_id}/.",
    ),
    (
        "Can I export my data for use in other tools?",
        "Yes. Use File > Export… (Ctrl+E) to export papers to CSV, JSON, "
        "BibTeX, RIS, Excel or Parquet. Reports can be generated as PDF, "
        "DOCX, PPTX, BibTeX or CSV via the Reporting wizard.",
    ),
]


class FaqItem(QGroupBox):
    """A single FAQ entry rendered as a collapsible (checkable) group box."""

    def __init__(self, question: str, answer: str,
                 parent: Optional[QWidget] = None) -> None:
        """Build the collapsible FAQ item."""
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(False)
        self.setTitle(question)
        self._answer = answer
        self.toggled.connect(self._on_toggle)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.answer_label = QLabel(answer)
        self.answer_label.setWordWrap(True)
        self.answer_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.answer_label)
        self._on_toggle(False)

    def _on_toggle(self, checked: bool) -> None:
        self.answer_label.setVisible(checked)


class HelpDialog(QDialog):
    """In-app help dialog with five tabs (Quick Start, Shortcuts, FAQ, About, License)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the dialog and build all tabs."""
        super().__init__(parent)
        self.setWindowTitle("Help — Academic Research Suite")
        self.setMinimumSize(820, 620)
        self._build_ui()

    # ----------------------------------------------------------- UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_quick_start(), "Quick Start")
        self.tabs.addTab(self._build_shortcuts_tab(), "Keyboard Shortcuts")
        self.tabs.addTab(self._build_faq_tab(), "FAQ")
        self.tabs.addTab(self._build_about_tab(), "About")
        self.tabs.addTab(self._build_license_tab(), "License")
        outer.addWidget(self.tabs, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        outer.addLayout(close_row)

    # ------------------------------------------------------ Quick Start

    def _build_quick_start(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        title = QLabel("Quick Start Guide")
        f = QFont()
        f.setPointSize(16)
        f.setBold(True)
        title.setFont(f)
        layout.addWidget(title)
        steps = [
            ("Create a project", "File > New Project… (Ctrl+N) and pick a parent folder."),
            ("Acquire data", "Open the Search panel, enter a query, pick sources and click Search."),
            ("Add to project", "Click 'Add to Project' on any result card to save it."),
            ("Explore the network", "Open Network View to visualize citations and collaborations."),
            ("Run analysis & export", "Pick an analysis type, run it, then File > Export… (Ctrl+E)."),
        ]
        for i, (heading, body) in enumerate(steps, start=1):
            step_label = QLabel(f"<b>Step {i} — {heading}</b><br/>{body}")
            step_label.setWordWrap(True)
            step_label.setTextFormat(Qt.TextFormat.RichText)
            step_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(step_label)
        layout.addStretch()
        return page

    # ------------------------------------------------------ Shortcuts

    def _build_shortcuts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Filter:"))
        self.shortcut_filter = QLineEdit()
        self.shortcut_filter.setPlaceholderText("Type to filter…")
        self.shortcut_filter.textChanged.connect(self._filter_shortcuts)
        search_row.addWidget(self.shortcut_filter, stretch=1)
        layout.addLayout(search_row)

        self.shortcut_table = QTableWidget(len(SHORTCUTS), 2)
        self.shortcut_table.setHorizontalHeaderLabels(["Action", "Shortcut"])
        self.shortcut_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.shortcut_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.shortcut_table.horizontalHeader().setStretchLastSection(True)
        self.shortcut_table.verticalHeader().setVisible(False)
        for r, (action, shortcut) in enumerate(SHORTCUTS):
            self.shortcut_table.setItem(r, 0, QTableWidgetItem(action))
            self.shortcut_table.setItem(r, 1, QTableWidgetItem(shortcut))
        self.shortcut_table.resizeColumnsToContents()
        layout.addWidget(self.shortcut_table, stretch=1)
        return page

    def _filter_shortcuts(self, text: str) -> None:
        text_low = text.strip().lower()
        for r in range(self.shortcut_table.rowCount()):
            item_action = self.shortcut_table.item(r, 0)
            item_short = self.shortcut_table.item(r, 1)
            haystack = " ".join(
                (item_action.text() if item_action else "")
                + " " + (item_short.text() if item_short else "")
            ).lower()
            self.shortcut_table.setRowHidden(r, bool(text_low) and text_low not in haystack)

    # ------------------------------------------------------ FAQ

    def _build_faq_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        hint = QLabel("Click a question to expand its answer.")
        hint.setStyleSheet("color:#888;")
        layout.addWidget(hint)
        self._faq_items: List[FaqItem] = []
        for q, a in FAQ:
            item = FaqItem(q, a)
            self._faq_items.append(item)
            layout.addWidget(item)
        layout.addStretch()
        return page

    # ------------------------------------------------------ About

    def _build_about_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Academic Research Suite")
        f = QFont()
        f.setPointSize(18)
        f.setBold(True)
        title.setFont(f)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        version = QLabel("Version 0.1.0")
        version.setStyleSheet("color:#888;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        layout.addWidget(self._about_section("Tech stack",
            "Python 3.10+, PyQt5/PySide2 (via qtpy), SQLite, networkx, "
            "scikit-learn, matplotlib, sentence-transformers, langchain, "
            "reportlab / python-docx / python-pptx."))
        layout.addWidget(self._about_section("Contributors",
            "Academic Research Suite contributors. See /LICENSE for the "
            "full list of copyright holders."))
        layout.addWidget(self._about_section("Links",
            "Project repository: <a href='https://example.com/ars'>"
            "https://example.com/ars</a><br/>"
            "Documentation: <a href='https://example.com/ars/docs'>"
            "https://example.com/ars/docs</a>"))
        layout.addStretch()
        return page

    def _about_section(self, title: str, body: str) -> QGroupBox:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 6)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(body)
        browser.setFrameStyle(QTextBrowser.Shape.NoFrame)
        layout.addWidget(browser)
        return box

    # ------------------------------------------------------ License

    def _build_license_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        license_text = self._license_text()
        edit = QPlainTextEdit()
        edit.setPlainText(license_text)
        edit.setReadOnly(True)
        edit.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.addWidget(edit, stretch=1)
        return page

    def _license_text(self) -> str:
        """Return the full MIT license text."""
        return (
            "MIT License\n"
            "\n"
            "Copyright (c) 2026 Academic Research Suite contributors\n"
            "\n"
            "Permission is hereby granted, free of charge, to any person obtaining a "
            "copy of this software and associated documentation files (the "
            "\"Software\"), to deal in the Software without restriction, including "
            "without limitation the rights to use, copy, modify, merge, publish, "
            "distribute, sublicense, and/or sell copies of the Software, and to "
            "permit persons to whom the Software is furnished to do so, subject to "
            "the following conditions:\n"
            "\n"
            "The above copyright notice and this permission notice shall be included "
            "in all copies or substantial portions of the Software.\n"
            "\n"
            "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, "
            "EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF "
            "MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. "
            "IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY "
            "CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, "
            "TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE "
            "SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n"
        )
