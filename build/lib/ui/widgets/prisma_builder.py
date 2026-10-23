"""Interactive PRISMA 2020 flow-diagram builder widget.

Provides :class:`PRISMAFlowBuilder` — a three-pane Qt interface to the
v2.0.0 :mod:`prisma` package:

* Left: form fields for every ``PRISMAStageCounts`` value.
* Center: live preview of the PRISMA flow diagram (rendered via
  :class:`prisma.flow_diagram.PRISMAFlowGenerator`).
* Right: extension (Standard/IPD/NMA/ScR/Harms/Abstract/Diagnostic) and
  style (BMJ/JAMA/Lancet) selectors.
* Bottom: Save PNG / SVG / PDF / Export-to-Word / Generate Checklist.

Every heavy dependency (matplotlib, reportlab, python-docx, the prisma
package itself) is lazy-imported inside the relevant handlers so the
widget imports cleanly in a minimal environment.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, List, Optional

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTextEdit, QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

__all__ = ["PRISMAFlowBuilder"]


# Canonical field metadata: (label, attribute name on PRISMAStageCounts, kind).
# ``reasons`` is special — rendered as a list of (reason, count) tuples.
_STAGE_FIELDS: List[tuple] = [
    ("Records from databases",     "n_records_databases",                    "int"),
    ("Records from registers",     "n_records_registers",                    "int"),
    ("Total records",               "n_records_total",                       "int"),
    ("Before duplicates",           "n_records_before_duplicates",           "int"),
    ("After duplicates",            "n_records_after_duplicates",            "int"),
    ("Duplicates removed",          "n_duplicates_removed",                  "int"),
    ("Records screened (title/abstract)", "n_records_screened",              "int"),
    ("Excluded at title/abstract", "n_records_excluded_title_abstract",     "int"),
    ("Full-text sought",            "n_records_sought_full_text",            "int"),
    ("Full-text not retrieved",    "n_records_not_retrieved",               "int"),
    ("Full-text assessed",          "n_full_text_assessed",                  "int"),
    ("Full-text excluded",          "n_full_text_excluded",                  "int"),
    ("Included in qualitative",     "n_studies_included_qualitative",        "int"),
    ("Included in quantitative",    "n_studies_included_quantitative",       "int"),
]

_EXTENSIONS: List[str] = ["standard", "ipd", "nma", "scr", "harms", "abstract", "diagnostic"]
_STYLES: List[str] = ["bmj", "jama", "lancet"]


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (font fallback + unicode minus)."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


class PRISMAFlowBuilder(QWidget):
    """Interactive PRISMA 2020 flow-diagram builder.

    The widget keeps a live :class:`PRISMAStageCounts` instance and
    re-renders the flow diagram every time a field or style changes.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("PRISMAFlowBuilder")
        self._counts: Any = None
        self._generator: Any = None
        self._figure: Any = None
        self._canvas: Any = None
        self._reasons: List[tuple] = []
        self._field_widgets: dict = {}
        self._build_ui()
        self._init_counts()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left: form (inside a scroll area in case the panel is short).
        left = QGroupBox("Stage Counts")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 8, 8)
        form_host = QWidget()
        form = QFormLayout(form_host)
        form.setSpacing(4)
        for label, attr, _kind in _STAGE_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText("—")
            edit.editingFinished.connect(self._on_field_changed)
            form.addRow(label, edit)
            self._field_widgets[attr] = edit
        # Excluded-with-reasons sub-form.
        self._reasons_list = QListWidget()
        self._reasons_list.setAlternatingRowColors(True)
        reason_row = QHBoxLayout()
        self._reason_text = QLineEdit()
        self._reason_text.setPlaceholderText("Reason")
        self._reason_count = QSpinBox()
        self._reason_count.setRange(0, 1000000)
        self._reason_add = QPushButton("+")
        self._reason_add.clicked.connect(self._on_add_reason)
        self._reason_remove = QPushButton("−")
        self._reason_remove.clicked.connect(self._on_remove_reason)
        reason_row.addWidget(self._reason_text, stretch=1)
        reason_row.addWidget(self._reason_count)
        reason_row.addWidget(self._reason_add)
        reason_row.addWidget(self._reason_remove)
        form.addRow("Excluded reasons list:", self._reasons_list)
        form.addRow(QLabel("(reason, count)"), reason_row)
        left_lay.addWidget(form_host)
        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        splitter.addWidget(scroll)

        # Center: live preview.
        center = QFrame()
        center.setObjectName("PreviewHost")
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        self._build_canvas(center_lay)
        splitter.addWidget(center)

        # Right: extension + style selectors.
        right = QGroupBox("Settings")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 8, 8, 8)
        right_lay.addWidget(QLabel("Extension"))
        self.ext_combo = QComboBox()
        self.ext_combo.addItems(_EXTENSIONS)
        self.ext_combo.currentIndexChanged.connect(self._on_field_changed)
        right_lay.addWidget(self.ext_combo)
        right_lay.addSpacing(6)
        right_lay.addWidget(QLabel("Style"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(_STYLES)
        self.style_combo.currentIndexChanged.connect(self._on_field_changed)
        right_lay.addWidget(self.style_combo)
        right_lay.addSpacing(6)
        right_lay.addWidget(QLabel("Title"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Review title")
        self.title_edit.editingFinished.connect(self._on_field_changed)
        right_lay.addWidget(self.title_edit)
        right_lay.addStretch()
        # Live checklist preview (read-only).
        right_lay.addWidget(QLabel("27-item Checklist"))
        self.checklist_view = QTextEdit()
        self.checklist_view.setReadOnly(True)
        self.checklist_view.setMinimumHeight(120)
        right_lay.addWidget(self.checklist_view)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter, stretch=1)

        # Bottom: toolbar.
        toolbar = QHBoxLayout()
        self.btn_save_png = QPushButton("Save PNG")
        self.btn_save_svg = QPushButton("Save SVG")
        self.btn_save_pdf = QPushButton("Save PDF")
        self.btn_export_word = QPushButton("Export to Word")
        self.btn_checklist = QPushButton("Generate Checklist")
        for b in (self.btn_save_png, self.btn_save_svg, self.btn_save_pdf,
                  self.btn_export_word, self.btn_checklist):
            toolbar.addWidget(b)
        toolbar.addStretch()
        outer.addLayout(toolbar)

        # Connect signals.
        self.btn_save_png.clicked.connect(self._on_save_png)
        self.btn_save_svg.clicked.connect(self._on_save_svg)
        self.btn_save_pdf.clicked.connect(self._on_save_pdf)
        self.btn_export_word.clicked.connect(self._on_export_word)
        self.btn_checklist.clicked.connect(self._on_generate_checklist)

    def _build_canvas(self, layout: QVBoxLayout) -> None:
        _configure_matplotlib()
        try:
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_qt5agg import (
                FigureCanvasQTAgg, NavigationToolbar2QT,
            )
            self._figure = plt.Figure(constrained_layout=True, figsize=(8, 11))
            self._canvas = FigureCanvasQTAgg(self._figure)
            layout.addWidget(self._canvas, stretch=1)
            try:
                layout.addWidget(NavigationToolbar2QT(self._canvas, self))
            except Exception as exc:
                logger.debug("NavigationToolbar2QT (prisma) failed: %s", exc)
        except Exception as exc:
            logger.warning("matplotlib canvas unavailable: %s", exc)
            layout.addWidget(QLabel(f"(matplotlib unavailable: {exc})", self))

    # ------------------------------------------------------------------ State
    def _init_counts(self) -> None:
        try:
            from prisma.flow_diagram import PRISMAStageCounts
            self._counts = PRISMAStageCounts()
        except Exception as exc:
            logger.warning("PRISMAStageCounts unavailable: %s", exc)
            self._counts = None
        self._refresh_preview()

    def _gather_counts(self) -> None:
        """Pull the current values from the form into ``self._counts``."""
        if self._counts is None:
            return
        for label, attr, _kind in _STAGE_FIELDS:
            edit = self._field_widgets.get(attr)
            if edit is None:
                continue
            text = edit.text().strip()
            if not text:
                setattr(self._counts, attr, None)
                continue
            try:
                setattr(self._counts, attr, int(text))
            except ValueError:
                setattr(self._counts, attr, None)
        try:
            self._counts.n_excluded_with_reasons = list(self._reasons)
        except Exception:
            pass

    # ------------------------------------------------------------------ Slots
    def _on_field_changed(self, *args: Any) -> None:
        """Re-render the preview whenever any field or selector changes."""
        self._refresh_preview()

    def _on_add_reason(self) -> None:
        reason = self._reason_text.text().strip()
        if not reason:
            return
        count = int(self._reason_count.value() or 0)
        self._reasons.append((reason, count))
        self._reasons_list.addItem(f"{reason} — {count}")
        self._reason_text.clear()
        self._reason_count.setValue(0)
        self._refresh_preview()

    def _on_remove_reason(self) -> None:
        row = self._reasons_list.currentRow()
        if row < 0 or row >= len(self._reasons):
            return
        del self._reasons[row]
        self._reasons_list.takeItem(row)
        self._refresh_preview()

    # ------------------------------------------------------------------ Rendering
    def _build_generator(self) -> Any:
        """Construct a PRISMAFlowGenerator from the current form state."""
        self._gather_counts()
        if self._counts is None:
            return None
        try:
            from prisma.flow_diagram import PRISMAFlowGenerator
            ext = self.ext_combo.currentText() or "standard"
            title = self.title_edit.text().strip()
            self._generator = PRISMAFlowGenerator(self._counts, title=title, extension=ext)
            return self._generator
        except Exception as exc:
            logger.exception("PRISMAFlowGenerator build failed: %s", exc)
            return None

    def _refresh_preview(self) -> None:
        """Re-render the matplotlib figure inside the central canvas."""
        if self._canvas is None or self._figure is None:
            return
        gen = self._build_generator()
        if gen is None:
            return
        try:
            style = self.style_combo.currentText() or "bmj"
            # Clear current axes.
            self._figure.clear()
            ax = self._figure.add_subplot(111)
            # PRISMAFlowGenerator.render_matplotlib creates its own figure;
            # we re-render onto our embedded axes by calling the lower-level
            # drawing routine (the public renderer returns a Figure object,
            # but for the live preview we copy the produced figure's artists
            # via bbox reblit).
            try:
                produced = gen.render_matplotlib(style=style)
                if produced is not None:
                    # Replace our figure with the produced one for display.
                    self._canvas.figure = produced
                    self._figure = produced
                    self._canvas.draw_idle()
                    return
            except Exception as exc:
                logger.debug("render_matplotlib failed: %s", exc)
            # Fallback: textual note on our own axes.
            ax.text(0.5, 0.5, "(PRISMA flow preview)", ha="center", va="center",
                    transform=ax.transAxes)
            ax.set_axis_off()
            self._canvas.draw_idle()
        except Exception as exc:
            logger.warning("PRISMA preview render failed: %s", exc)

    # ------------------------------------------------------------------ Exporters
    def _on_save_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save PNG", "prisma.png", "PNG (*.png)")
        if not path:
            return
        gen = self._build_generator()
        if gen is None:
            return
        try:
            gen.render_png(path, dpi=300, style=self.style_combo.currentText() or "bmj")
            logger.info("PRISMA PNG saved to %s", path)
        except Exception as exc:
            logger.exception("render_png failed: %s", exc)

    def _on_save_svg(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save SVG", "prisma.svg", "SVG (*.svg)")
        if not path:
            return
        gen = self._build_generator()
        if gen is None:
            return
        try:
            gen.render_svg(path, style=self.style_combo.currentText() or "bmj")
            logger.info("PRISMA SVG saved to %s", path)
        except Exception as exc:
            logger.exception("render_svg failed: %s", exc)

    def _on_save_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF", "prisma.pdf", "PDF (*.pdf)")
        if not path:
            return
        gen = self._build_generator()
        if gen is None:
            return
        try:
            gen.render_pdf(path, style=self.style_combo.currentText() or "bmj")
            logger.info("PRISMA PDF saved to %s", path)
        except Exception as exc:
            logger.exception("render_pdf failed: %s", exc)

    def _on_export_word(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export to Word", "prisma_checklist.docx",
                                              "Word (*.docx)")
        if not path:
            return
        try:
            from prisma.checklist import PRISMAChecklist
            checklist = PRISMAChecklist()
            checklist.to_docx(path)
            logger.info("PRISMA checklist DOCX saved to %s", path)
        except Exception as exc:
            logger.exception("PRISMA checklist DOCX failed: %s", exc)

    def _on_generate_checklist(self) -> None:
        """Render the 27-item PRISMA 2020 checklist into the right panel."""
        try:
            from prisma.checklist import PRISMAChecklist
            cl = PRISMAChecklist()
            md = cl.to_markdown()
            self.checklist_view.setPlainText(md)
            logger.info("PRISMA checklist rendered (%d items).", len(cl.items) if hasattr(cl, "items") else 0)
        except Exception as exc:
            logger.exception("PRISMA checklist render failed: %s", exc)
            self.checklist_view.setPlainText(f"(checklist unavailable: {exc})")
