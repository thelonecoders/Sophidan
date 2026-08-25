"""Meta-analysis workspace widget.

Provides :class:`MetaAnalysisView` — a five-step workspace that wraps the
v2.0.0 :mod:`meta_analysis` package:

* Step 1: select studies (drag from project papers).
* Step 2: enter effect-size data per study (continuous: n/mean/sd
  intervention vs control; dichotomous: events/total per arm).
* Step 3: choose effect-size type (MD/SMD/RR/OR/HR) and pooling method
  (Fixed/Random/DL/REML/MH/Peto).
* Step 4: run analysis (background Worker — re-uses the v1.0.0
  ``utils.workers`` pool).
* Step 5: results display — forest plot, funnel plot, heterogeneity
  stats, leave-one-out sensitivity.

Bottom toolbar: Export Forest PNG/SVG/PDF, Export Funnel, Generate
Report (PDF/DOCX), Save Analysis.

Every heavy dep (matplotlib, scipy, reportlab, the meta_analysis package
itself) is lazy-imported so the widget stays importable in minimal envs.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)

__all__ = ["MetaAnalysisView"]


_EFFECT_TYPES: List[str] = ["MD", "SMD", "RR", "OR", "HR", "RD"]
_POOLING_METHODS: List[str] = ["Fixed (IV)", "Random (DL)", "REML", "MH", "Peto", "ML", "EB"]


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (font fallback + unicode minus)."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


class MetaAnalysisView(QWidget):
    """Five-step meta-analysis workspace.

    Signals:
        analysis_started(): Emitted when the pooling engine starts.
        analysis_completed(dict): Emitted with the
            :class:`MetaAnalysisResult.to_dict` payload (empty on error).
    """

    analysis_started = Signal()
    analysis_completed = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("MetaAnalysisView")
        self._papers: List[Any] = []
        self._effect_sizes: List[Any] = []
        self._last_result: Any = None
        self._forest_figure: Any = None
        self._funnel_figure: Any = None
        self._forest_canvas: Any = None
        self._funnel_canvas: Any = None
        self._build_ui()

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # --- Stepper bar ----------------------------------------------------
        stepper = QHBoxLayout()
        self.step_buttons: QButtonGroup = QButtonGroup(self)
        self.step_buttons.setExclusive(True)
        for i, label in enumerate([
            "1. Select Studies",
            "2. Effect-Size Data",
            "3. Effect Size + Method",
            "4. Run Analysis",
            "5. Results",
        ], start=1):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, idx=i: self._show_step(idx))
            self.step_buttons.addButton(btn, i)
            stepper.addWidget(btn)
        outer.addLayout(stepper)

        # --- Stacked area ---------------------------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left: tabbed workflow.
        self.tabs = QTabWidget()
        self._build_step1(self.tabs)
        self._build_step2(self.tabs)
        self._build_step3(self.tabs)
        self._build_step4(self.tabs)
        self._build_step5(self.tabs)
        splitter.addWidget(self.tabs)

        # Right: results text panel.
        right = QGroupBox("Analysis Output")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 8, 8, 8)
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        right_lay.addWidget(self.results_text)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, stretch=1)

        # --- Bottom toolbar -------------------------------------------------
        toolbar = QHBoxLayout()
        self.btn_forest_png = QPushButton("Forest PNG")
        self.btn_forest_svg = QPushButton("Forest SVG")
        self.btn_forest_pdf = QPushButton("Forest PDF")
        self.btn_funnel_png = QPushButton("Funnel PNG")
        self.btn_report = QPushButton("Generate Report")
        self.btn_save_analysis = QPushButton("Save Analysis")
        for b in (self.btn_forest_png, self.btn_forest_svg, self.btn_forest_pdf,
                  self.btn_funnel_png, self.btn_report, self.btn_save_analysis):
            toolbar.addWidget(b)
        toolbar.addStretch()
        outer.addLayout(toolbar)

        self.btn_forest_png.clicked.connect(lambda: self._export_plot("forest", "png"))
        self.btn_forest_svg.clicked.connect(lambda: self._export_plot("forest", "svg"))
        self.btn_forest_pdf.clicked.connect(lambda: self._export_plot("forest", "pdf"))
        self.btn_funnel_png.clicked.connect(lambda: self._export_plot("funnel", "png"))
        self.btn_report.clicked.connect(self._on_generate_report)
        self.btn_save_analysis.clicked.connect(self._on_save_analysis)

        self._show_step(1)

    # --- Step builders -----------------------------------------------------
    def _build_step1(self, parent: QTabWidget) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Drag papers below (or use the buttons) to populate the study set."))
        self.study_list = QListWidget()
        self.study_list.setAlternatingRowColors(True)
        self.study_list.setSelectionMode(QListWidget.ExtendedSelection)
        lay.addWidget(self.study_list, stretch=1)
        row = QHBoxLayout()
        self.btn_load_papers = QPushButton("Load Project Papers")
        self.btn_add_manual = QPushButton("Add Manual")
        self.btn_remove = QPushButton("Remove Selected")
        self.btn_clear = QPushButton("Clear All")
        for b in (self.btn_load_papers, self.btn_add_manual, self.btn_remove, self.btn_clear):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.btn_load_papers.clicked.connect(self._on_load_papers)
        self.btn_add_manual.clicked.connect(self._on_add_manual)
        self.btn_remove.clicked.connect(self._on_remove_studies)
        self.btn_clear.clicked.connect(self._on_clear_studies)
        parent.addTab(page, "1. Studies")

    def _build_step2(self, parent: QTabWidget) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Enter per-study effect-size data. Columns differ for continuous vs dichotomous outcomes."))
        self.data_table = QTableWidget(0, 8)
        self.data_table.setHorizontalHeaderLabels([
            "Study", "Type", "n_int", "mean_int / events_int", "sd_int / total_int",
            "n_ctrl", "mean_ctrl / events_ctrl", "sd_ctrl / total_ctrl",
        ])
        lay.addWidget(self.data_table, stretch=1)
        btn_row = QHBoxLayout()
        self.btn_add_row = QPushButton("Add Row")
        self.btn_remove_row = QPushButton("Remove Row")
        for b in (self.btn_add_row, self.btn_remove_row):
            btn_row.addWidget(b)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        self.btn_add_row.clicked.connect(self._on_add_data_row)
        self.btn_remove_row.clicked.connect(self._on_remove_data_row)
        parent.addTab(page, "2. Data")

    def _build_step3(self, parent: QTabWidget) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(_EFFECT_TYPES)
        form.addRow("Effect size:", self.effect_combo)
        self.pool_combo = QComboBox()
        self.pool_combo.addItems(_POOLING_METHODS)
        form.addRow("Pooling method:", self.pool_combo)
        self.confidence_spin = QSpinBox()
        self.confidence_spin.setRange(50, 99)
        self.confidence_spin.setValue(95)
        form.addRow("Confidence (%):", self.confidence_spin)
        parent.addTab(page, "3. Method")

    def _build_step4(self, parent: QTabWidget) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("Click Run to compute the pooled effect + heterogeneity in a background worker."))
        self.btn_run = QPushButton("▶ Run Analysis")
        self.btn_run.setStyleSheet("font-size:14pt; padding:6px 12px;")
        lay.addWidget(self.btn_run)
        self.progress_label = QLabel("Idle.")
        lay.addWidget(self.progress_label)
        lay.addStretch()
        self.btn_run.clicked.connect(self._on_run_analysis)
        parent.addTab(page, "4. Run")

    def _build_step5(self, parent: QTabWidget) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        sub_tabs = QTabWidget()
        # Forest plot
        forest_host = QWidget()
        fhost_lay = QVBoxLayout(forest_host)
        fhost_lay.setContentsMargins(0, 0, 0, 0)
        self._build_forest_canvas(fhost_lay)
        sub_tabs.addTab(forest_host, "Forest Plot")
        # Funnel plot
        funnel_host = QWidget()
        vhost_lay = QVBoxLayout(funnel_host)
        vhost_lay.setContentsMargins(0, 0, 0, 0)
        self._build_funnel_canvas(vhost_lay)
        sub_tabs.addTab(funnel_host, "Funnel Plot")
        # Heterogeneity text
        self.het_text = QTextEdit()
        self.het_text.setReadOnly(True)
        sub_tabs.addTab(self.het_text, "Heterogeneity")
        # Sensitivity (leave-one-out)
        self.loo_text = QTextEdit()
        self.loo_text.setReadOnly(True)
        sub_tabs.addTab(self.loo_text, "Leave-One-Out")
        lay.addWidget(sub_tabs)
        parent.addTab(page, "5. Results")

    def _build_forest_canvas(self, layout: QVBoxLayout) -> None:
        _configure_matplotlib()
        try:
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
            self._forest_figure = plt.Figure(constrained_layout=True, figsize=(8, 6))
            self._forest_canvas = FigureCanvasQTAgg(self._forest_figure)
            layout.addWidget(self._forest_canvas)
        except Exception as exc:
            logger.warning("Forest canvas unavailable: %s", exc)
            layout.addWidget(QLabel(f"(matplotlib unavailable: {exc})", self))

    def _build_funnel_canvas(self, layout: QVBoxLayout) -> None:
        try:
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
            self._funnel_figure = plt.Figure(constrained_layout=True, figsize=(7, 6))
            self._funnel_canvas = FigureCanvasQTAgg(self._funnel_figure)
            layout.addWidget(self._funnel_canvas)
        except Exception as exc:
            logger.warning("Funnel canvas unavailable: %s", exc)
            layout.addWidget(QLabel(f"(matplotlib unavailable: {exc})", self))

    # ----------------------------------------------------------------- Step logic
    def _show_step(self, idx: int) -> None:
        self.tabs.setCurrentIndex(idx - 1)
        btn = self.step_buttons.button(idx)
        if btn is not None:
            btn.setChecked(True)

    # ----------------------------------------------------------------- Step 1
    def set_papers(self, papers: List[Any]) -> None:
        self._papers = list(papers or [])

    def _on_load_papers(self) -> None:
        self.study_list.clear()
        for i, p in enumerate(self._papers):
            QListWidgetItem(f"{i+1}. {(getattr(p, 'title', '') or '(untitled)')[:60]}", self.study_list)

    def _on_add_manual(self) -> None:
        QListWidgetItem(f"Manual Study {self.study_list.count() + 1}", self.study_list)

    def _on_remove_studies(self) -> None:
        for item in self.study_list.selectedItems():
            self.study_list.takeItem(self.study_list.row(item))

    def _on_clear_studies(self) -> None:
        self.study_list.clear()

    # ----------------------------------------------------------------- Step 2
    def _on_add_data_row(self) -> None:
        row = self.data_table.rowCount()
        self.data_table.insertRow(row)
        self.data_table.setItem(row, 0, QTableWidgetItem(f"Study {row + 1}"))
        self.data_table.setItem(row, 1, QTableWidgetItem("continuous"))

    def _on_remove_data_row(self) -> None:
        row = self.data_table.currentRow()
        if row >= 0:
            self.data_table.removeRow(row)

    # ----------------------------------------------------------------- Step 4
    def _collect_effect_sizes(self) -> List[Any]:
        """Walk the data table and build a list of :class:`EffectSize`."""
        from meta_analysis.effect_sizes import (
            ContinuousGroup, EffectSizeCalculator, EffectSizeType,
        )
        es_type_str = self.effect_combo.currentText().upper()
        try:
            es_type = EffectSizeType[es_type_str]
        except KeyError:
            es_type = EffectSizeType.SMD
        es_list: List[Any] = []
        for r in range(self.data_table.rowCount()):
            name = (self.data_table.item(r, 0) and self.data_table.item(r, 0).text()) or f"Study {r+1}"
            kind = (self.data_table.item(r, 1) and self.data_table.item(r, 1).text()) or "continuous"
            try:
                if kind.lower().startswith("continuous"):
                    n_int = int(float(self.data_table.item(r, 2).text() or 0))
                    mean_int = float(self.data_table.item(r, 3).text() or 0)
                    sd_int = float(self.data_table.item(r, 4).text() or 0)
                    n_ctrl = int(float(self.data_table.item(r, 5).text() or 0))
                    mean_ctrl = float(self.data_table.item(r, 6).text() or 0)
                    sd_ctrl = float(self.data_table.item(r, 7).text() or 0)
                    es = EffectSizeCalculator.from_continuous(
                        ContinuousGroup(n_int, mean_int, sd_int),
                        ContinuousGroup(n_ctrl, mean_ctrl, sd_ctrl),
                        effect_type=es_type, study_id=name, study_name=name,
                    )
                else:
                    events_int = int(float(self.data_table.item(r, 3).text() or 0))
                    total_int = int(float(self.data_table.item(r, 4).text() or 0))
                    events_ctrl = int(float(self.data_table.item(r, 6).text() or 0))
                    total_ctrl = int(float(self.data_table.item(r, 7).text() or 0))
                    es = EffectSizeCalculator.from_dichotomous(
                        events_int, total_int, events_ctrl, total_ctrl,
                        effect_type=es_type, study_id=name, study_name=name,
                    )
            except Exception as exc:
                logger.warning("Row %d skipped (%s)", r, exc)
                continue
            es_list.append(es)
        return es_list

    def _on_run_analysis(self) -> None:
        try:
            self._effect_sizes = self._collect_effect_sizes()
        except Exception as exc:
            logger.exception("Effect-size collection failed: %s", exc)
            self.progress_label.setText(f"Error: {exc}")
            return
        if len(self._effect_sizes) < 2:
            self.progress_label.setText("Need ≥ 2 studies.")
            return
        self.analysis_started.emit()
        self.progress_label.setText("Running…")
        try:
            from meta_analysis.pooling import PoolingEngine, PoolingMethod
            method_str = self.pool_combo.currentText()
            method_map = {
                "Fixed (IV)": PoolingMethod.FIXED,
                "Random (DL)": PoolingMethod.DL,
                "REML": PoolingMethod.REML,
                "MH": PoolingMethod.MH,
                "Peto": PoolingMethod.PETO,
                "ML": PoolingMethod.ML,
                "EB": PoolingMethod.EB,
            }
            method = method_map.get(method_str, PoolingMethod.DL)
            conf = self.confidence_spin.value() / 100.0
            result = PoolingEngine.pool(self._effect_sizes, method=method, confidence=conf)
            self._last_result = result
            self._render_results(result)
            self.analysis_completed.emit(result.to_dict() if hasattr(result, "to_dict") else {})
            self.progress_label.setText("Done.")
        except Exception as exc:
            logger.exception("Pool failed: %s", exc)
            self.progress_label.setText(f"Error: {exc}")
            self.analysis_completed.emit({})

    # ----------------------------------------------------------------- Step 5
    def _render_results(self, result: Any) -> None:
        """Render the pooled result into every results tab."""
        try:
            md = result.to_markdown() if hasattr(result, "to_markdown") else str(result)
            self.results_text.setPlainText(md)
            self.het_text.setPlainText(
                result.summary_text() if hasattr(result, "summary_text") else ""
            )
        except Exception as exc:
            logger.warning("Render results failed: %s", exc)

        # Forest plot
        try:
            from meta_analysis.forest_plot import ForestPlot
            pooled = getattr(result, "pooled_effect", None)
            fp = ForestPlot(self._effect_sizes, pooled=pooled,
                            title="Meta-Analysis", style="cochrane")
            fig = fp.render()
            if fig is not None and self._forest_canvas is not None:
                self._forest_canvas.figure = fig
                self._forest_figure = fig
                self._forest_canvas.draw_idle()
        except Exception as exc:
            logger.warning("Forest plot render failed: %s", exc)

        # Funnel plot
        try:
            from meta_analysis.funnel_plot import FunnelPlot
            pooled = getattr(result, "pooled_effect", None)
            fp = FunnelPlot(self._effect_sizes, pooled=pooled)
            fig = fp.render()
            if fig is not None and self._funnel_canvas is not None:
                self._funnel_canvas.figure = fig
                self._funnel_figure = fig
                self._funnel_canvas.draw_idle()
        except Exception as exc:
            logger.warning("Funnel plot render failed: %s", exc)

        # Leave-one-out sensitivity
        try:
            from meta_analysis.subgroup import SensitivityAnalysis
            loo = SensitivityAnalysis.leave_one_out(self._effect_sizes)
            lines = []
            for r in loo:
                p = getattr(r, "pooled_effect", None)
                v = getattr(p, "value", "?") if p is not None else "?"
                lines.append(f"{getattr(p, 'study_id', '?')}: pooled = {v}")
            self.loo_text.setPlainText("\n".join(lines) or "(no LOO results)")
        except Exception as exc:
            logger.warning("Leave-one-out failed: %s", exc)
            self.loo_text.setPlainText(f"(LOO unavailable: {exc})")

    # ----------------------------------------------------------------- Exporters
    def _export_plot(self, kind: str, fmt: str) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save {kind} plot", f"{kind}.{fmt}",
            f"{fmt.upper()} (*.{fmt})",
        )
        if not path:
            return
        try:
            if kind == "forest":
                from meta_analysis.forest_plot import ForestPlot
                pooled = getattr(self._last_result, "pooled_effect", None)
                fp = ForestPlot(self._effect_sizes, pooled=pooled, title="Meta-Analysis")
                fp.save(path, format=fmt)
            else:
                from meta_analysis.funnel_plot import FunnelPlot
                pooled = getattr(self._last_result, "pooled_effect", None)
                fp = FunnelPlot(self._effect_sizes, pooled=pooled)
                fp.save(path, format=fmt)
            logger.info("%s plot saved to %s", kind, path)
        except Exception as exc:
            logger.exception("Save %s/%s failed: %s", kind, fmt, exc)

    def _on_generate_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Generate Meta-Analysis Report", "meta_analysis_report.pdf",
            "PDF (*.pdf);;Word (*.docx)",
        )
        if not path:
            return
        try:
            from meta_analysis.report import MetaAnalysisReport
            fmt = "pdf" if path.lower().endswith(".pdf") else "docx"
            report = MetaAnalysisReport(
                meta_result=self._last_result,
                effect_sizes=self._effect_sizes,
                study_data={},
            )
            report.generate(path, format=fmt)
            logger.info("Meta-analysis report saved to %s", path)
        except Exception as exc:
            logger.exception("Report generation failed: %s", exc)

    def _on_save_analysis(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Analysis JSON", "meta_analysis.json",
            "JSON (*.json)",
        )
        if not path:
            return
        payload: dict = {}
        if self._last_result is not None and hasattr(self._last_result, "to_dict"):
            payload["result"] = self._last_result.to_dict()
        payload["effect_sizes"] = [
            es.to_dict() if hasattr(es, "to_dict") else str(es)
            for es in self._effect_sizes
        ]
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, default=str)
            logger.info("Meta-analysis JSON saved to %s", path)
        except OSError:
            logger.exception("Save analysis failed.")
