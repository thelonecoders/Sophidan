"""Data-science workspace widget for the Academic Research Suite.

Provides :class:`AnalysisViewWidget` — a left/center/right layout for selecting
an analysis type (Topic Modeling, Clustering, Temporal, Bibliometrics,
Embeddings), configuring parameters, running the analysis in a background
``utils.workers.Worker``, and rendering results as matplotlib figures, tables,
or interactive HTML. Includes export buttons and progress / cancel controls.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ui.modern_theme import ModernTheme

logger = logging.getLogger(__name__)

# Analysis types presented in the left selector.
ANALYSIS_TYPES: List[str] = [
    "Topic Modeling",
    "Clustering",
    "Temporal",
    "Bibliometrics",
    "Embeddings",
]

# Methods per analysis type.
ANALYSIS_METHODS: Dict[str, List[str]] = {
    "Topic Modeling": ["BERTopic", "LDA", "NMF"],
    "Clustering": ["KMeans", "DBSCAN", "Agglomerative"],
    "Temporal": ["Yearly counts", "Cumulative", "Trend detection"],
    "Bibliometrics": ["h-index", "Citation distribution", "Productivity"],
    "Embeddings": ["Sentence-Transformers", "PCA", "UMAP"],
}


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


class AnalysisViewWidget(QWidget):
    """Data-science workspace widget.

    Lets the user pick an analysis type from the left column, configure
    parameters in the center, run it on a background Worker, then render
    results (matplotlib figure, table, or interactive HTML) with export
    buttons for the figure, model, and results CSV.
    """

    analysis_started = Signal(str)
    analysis_finished = Signal(object)
    analysis_error = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the workspace with an empty dataset reference."""
        super().__init__(parent)
        self._data: Any = None
        self._worker: Optional[Any] = None
        self._cancel_requested: bool = False
        self._last_result: Any = None
        self._last_figure: Any = None
        self._last_table: Optional[List[List[str]]] = None
        self._last_html: Optional[str] = None
        self._figure: Any = None
        self._canvas: Any = None
        self._toolbar: Any = None
        self._ax: Any = None

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left column: analysis type selector
        left = QGroupBox("Analysis")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 6, 8, 6)
        self.type_combo = QComboBox()
        self.type_combo.addItems(ANALYSIS_TYPES)
        left_layout.addWidget(QLabel("Type:"))
        left_layout.addWidget(self.type_combo)

        self.method_combo = QComboBox()
        left_layout.addWidget(QLabel("Method:"))
        left_layout.addWidget(self.method_combo)

        left_layout.addStretch()
        splitter.addWidget(left)

        # Center: parameters + run + results
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

        # Parameters group
        params_box = QGroupBox("Parameters")
        params_layout = QFormLayout(params_box)
        params_layout.setContentsMargins(8, 6, 8, 6)

        self.num_topics_slider = QSlider(Qt.Orientation.Horizontal)
        self.num_topics_slider.setRange(2, 50)
        self.num_topics_slider.setValue(10)
        self.num_topics_label = QLabel("10")
        self.num_topics_slider.valueChanged.connect(
            lambda v: self.num_topics_label.setText(str(v))
        )
        topics_row = QHBoxLayout()
        topics_row.addWidget(self.num_topics_slider, stretch=1)
        topics_row.addWidget(self.num_topics_label)
        params_layout.addRow("Num topics / clusters:", topics_row)

        self.year_from = QSpinBox()
        self.year_from.setRange(1900, 2100)
        self.year_from.setValue(2000)
        self.year_to = QSpinBox()
        self.year_to.setRange(1900, 2100)
        self.year_to.setValue(2100)
        params_layout.addRow("Year range:", self._row(self.year_from, self.year_to))

        self.random_state = QSpinBox()
        self.random_state.setRange(0, 2**31 - 1)
        self.random_state.setValue(42)
        params_layout.addRow("Random state:", self.random_state)

        center_layout.addWidget(params_box)

        # Run / export buttons
        actions = QHBoxLayout()
        self.run_button = QPushButton("Run Analysis")
        self.run_button.setObjectName("PrimaryBtn")
        self.export_figure_btn = QPushButton("Save Figure")
        self.export_model_btn = QPushButton("Save Model")
        self.export_csv_btn = QPushButton("Export Results CSV")
        for btn in (self.export_figure_btn, self.export_model_btn, self.export_csv_btn):
            btn.setEnabled(False)
        actions.addWidget(self.run_button)
        actions.addStretch()
        actions.addWidget(self.export_figure_btn)
        actions.addWidget(self.export_model_btn)
        actions.addWidget(self.export_csv_btn)
        center_layout.addLayout(actions)

        # Results area (figure / table / html stacked)
        results_box = QGroupBox("Results")
        results_layout = QVBoxLayout(results_box)
        self.results_stack = QSplitter(Qt.Orientation.Vertical)
        self.results_stack.setChildrenCollapsible(False)
        # Figure pane
        fig_holder = QFrame()
        fig_holder_layout = QVBoxLayout(fig_holder)
        fig_holder_layout.setContentsMargins(0, 0, 0, 0)
        self._build_figure_canvas(fig_holder_layout)
        self.results_stack.addWidget(fig_holder)
        # Table pane
        self.table = QTableWidget(0, 0)
        self.results_stack.addWidget(self.table)
        # HTML pane
        self.html_browser = QTextBrowser()
        self.html_browser.setOpenExternalLinks(True)
        self.results_stack.addWidget(self.html_browser)
        self.results_stack.setStretchFactor(0, 3)
        self.results_stack.setStretchFactor(1, 1)
        self.results_stack.setStretchFactor(2, 1)
        results_layout.addWidget(self.results_stack)
        center_layout.addWidget(results_box, stretch=1)

        # Progress bar + cancel
        bottom = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.status_label = QLabel("Idle")
        self.status_label.setStyleSheet(
            f"color:{ModernTheme.DARK_TEXT_MUTED};")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        bottom.addWidget(self.progress_bar, stretch=2)
        bottom.addWidget(self.status_label, stretch=1)
        bottom.addWidget(self.cancel_button)
        center_layout.addLayout(bottom)

        splitter.addWidget(center)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        outer.addWidget(splitter, stretch=1)

        # Populate initial method list
        self._refresh_methods()

    def _row(self, *widgets: QWidget) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            lay.addWidget(w)
        return row

    def _build_figure_canvas(self, layout: QVBoxLayout) -> None:
        """Build the embedded matplotlib FigureCanvasQTAgg + NavigationToolbar2QT."""
        _configure_matplotlib()
        import matplotlib.pyplot as plt  # noqa: WPS433 lazy
        from matplotlib.backends.backend_qt5agg import (  # noqa: WPS433 lazy
            FigureCanvasQTAgg,
            NavigationToolbar2QT,
        )
        self._figure = plt.Figure(constrained_layout=True)
        self._ax = self._figure.add_subplot(111)
        self._ax.set_axis_off()
        self._ax.text(0.5, 0.5, "Run an analysis to see results.",
                      ha="center", va="center",
                      transform=self._ax.transAxes, color=ModernTheme.DARK_TEXT_MUTED)
        self._canvas = FigureCanvasQTAgg(self._figure)
        layout.addWidget(self._canvas, stretch=1)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        layout.addWidget(self._toolbar)

    def _connect_signals(self) -> None:
        self.type_combo.currentIndexChanged.connect(self._refresh_methods)
        self.run_button.clicked.connect(self._on_run)
        self.cancel_button.clicked.connect(self._on_cancel)
        self.export_figure_btn.clicked.connect(self._export_figure)
        self.export_model_btn.clicked.connect(self._export_model)
        self.export_csv_btn.clicked.connect(self._export_csv)

    def _refresh_methods(self) -> None:
        method_list = ANALYSIS_METHODS.get(self.type_combo.currentText(), [])
        self.method_combo.clear()
        self.method_combo.addItems(method_list)

    # -------------------------------------------------------------- Public

    def set_data(self, data: Any) -> None:
        """Provide a DataFrame (or compatible) to be analyzed."""
        self._data = data

    def set_papers(self, papers: Any) -> None:
        """Data-bridge entry point — accept a list of paper dicts."""
        self.set_data(papers)

    def _papers_as_records(self) -> List[Dict[str, Any]]:
        """Normalize ``self._data`` into a list of paper dicts."""
        data = self._data
        if data is None:
            return []
        # DataFrame duck-typing (avoids a hard pandas import).
        if hasattr(data, "columns") and hasattr(data, "to_dict"):
            try:
                return [dict(r) for r in data.to_dict("records")]
            except Exception:  # noqa: BLE001
                logger.debug("DataFrame conversion failed.", exc_info=True)
                return []
        if isinstance(data, dict):
            return [dict(data)]
        if isinstance(data, (list, tuple)):
            out: List[Dict[str, Any]] = []
            for item in data:
                if isinstance(item, dict):
                    out.append(dict(item))
                else:
                    to_dict = getattr(item, "to_dict", None)
                    if callable(to_dict):
                        try:
                            d = to_dict()
                            if isinstance(d, dict):
                                out.append(d)
                        except Exception:  # noqa: BLE001
                            logger.debug("Paper.to_dict failed.", exc_info=True)
            return out
        return []

    # ---------------------------------------------------------------- Run

    def _build_params(self) -> Dict[str, Any]:
        return {
            "type": self.type_combo.currentText(),
            "method": self.method_combo.currentText(),
            "num_topics": self.num_topics_slider.value(),
            "year_from": self.year_from.value(),
            "year_to": self.year_to.value(),
            "random_state": self.random_state.value(),
        }

    def _on_run(self) -> None:
        if self._data is None:
            QMessageBox.information(
                self, "No data", "Please load data into the analysis view first."
            )
            return
        params = self._build_params()
        self._cancel_requested = False
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting…")
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        for btn in (self.export_figure_btn, self.export_model_btn, self.export_csv_btn):
            btn.setEnabled(False)
        self.analysis_started.emit(params["type"])

        from utils.workers import Worker, WorkerPool

        def _work(progress_callback=None) -> Any:
            report = progress_callback or (lambda pct, msg="": None)
            report(0, f"Running {params['type']} ({params['method']})…")
            result = self._invoke_analysis(params)
            report(100, "Done")
            return result

        self._worker = Worker(_work)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.result.connect(self._on_analysis_complete)
        self._worker.signals.error.connect(self._on_analysis_error)
        self._worker.signals.finished.connect(
            lambda: setattr(self, "_worker_running", False))
        self._worker_running = True
        WorkerPool.instance().submit(self._worker)

    def _invoke_analysis(self, params: Dict[str, Any]) -> Any:
        """Dispatch to the appropriate ``data_science`` module.

        Calls the engine-contract APIs (P-d):

        * ``TopicModeler(method=…).analyze(papers, **kw) -> dict``
        * ``Clusterer(method=…).analyze(papers, **kw) -> dict``
        * ``TemporalAnalyzer(papers).analyze(**kw) -> dict``
        * ``Bibliometrics(papers).summary() -> dict``
        * ``EmbeddingsModel(…).encode(texts)``

        Lazy-imports the heavy modules so the widget itself remains
        importable without those deps installed.
        """
        a_type = params["type"]
        papers = self._papers_as_records()
        if not papers:
            raise ValueError(
                "No analysable papers loaded — run a search or open a "
                "project first.")
        if a_type == "Topic Modeling":
            from data_science.topic_modeler import TopicModeler
            model = TopicModeler(method=params["method"])
            return self._normalize_result(model.analyze(
                papers,
                num_topics=params["num_topics"],
                random_state=params["random_state"],
            ))
        if a_type == "Clustering":
            from data_science.clustering import Clusterer
            clusterer = Clusterer(method=params["method"])
            return self._normalize_result(clusterer.analyze(
                papers,
                n_clusters=params["num_topics"],
                random_state=params["random_state"],
            ))
        if a_type == "Temporal":
            from data_science.temporal_analysis import TemporalAnalyzer
            ta = TemporalAnalyzer(papers)
            return self._normalize_result(ta.analyze())
        if a_type == "Bibliometrics":
            from data_science.statistics import Bibliometrics
            bib = Bibliometrics(papers)
            return self._normalize_result(bib.summary())
        if a_type == "Embeddings":
            from data_science.embeddings import EmbeddingsModel
            emb = EmbeddingsModel()
            texts = [
                " ".join(str(p.get(k, "")) for k in ("title", "abstract"))
                for p in papers
            ]
            vectors = emb.encode(texts)
            dim = 0
            if vectors is not None and len(vectors):
                try:
                    dim = len(vectors[0])
                except TypeError:  # pragma: no cover — scalar mock vectors
                    dim = 1
            return self._normalize_result({
                "summary": {
                    "documents": len(texts),
                    "dimensions": dim,
                    "method": params["method"],
                },
            })
        return None

    @staticmethod
    def _normalize_result(result: Any) -> Any:
        """Coerce an analysis result into the ``{figure, table, html}``
        shape expected by :meth:`_render_result`."""
        if result is None:
            return None
        if isinstance(result, dict):
            if any(k in result for k in ("figure", "table", "html")):
                return result
            # Generic dict → render as an HTML key/value table.
            rows = "".join(
                f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"
                for k, v in result.items()
            )
            return {"html": f"<table>{rows}</table>"}
        # DataFrame duck-typing.
        if hasattr(result, "to_html") and hasattr(result, "columns"):
            try:
                return {"html": result.to_html(border=0, max_rows=200)}
            except Exception:  # noqa: BLE001
                pass
        if isinstance(result, (list, tuple)):
            return {"html": "<pre>" + "\n".join(str(r) for r in result[:200]) + "</pre>"}
        return {"html": f"<pre>{result}</pre>"}

    # --------------------------------------------------------- Progress/end

    def _on_progress(self, percent: int, message: str = "") -> None:
        """Worker progress callback — ``signals.progress(int, str)``."""
        self.progress_bar.setValue(int(percent))
        if message:
            self.status_label.setText(str(message))

    def _on_analysis_complete(self, result: Any) -> None:
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress_bar.setValue(100)
        self.status_label.setText("Analysis complete.")
        self._last_result = result
        try:
            self._render_result(result)
        except Exception as exc:  # noqa: BLE001
            logger.error("Render failed: %s", exc)
        for btn in (self.export_figure_btn, self.export_model_btn, self.export_csv_btn):
            btn.setEnabled(True)
        self.analysis_finished.emit(result)

    def _on_analysis_error(self, err: Any) -> None:
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        msg = str(err).strip().splitlines()[-1] if str(err).strip() else "unknown error"
        logger.error("Analysis failed: %s", err)
        self.status_label.setText(f"Error: {msg}")
        self.analysis_error.emit(str(err))

    def _on_cancel(self) -> None:
        """Flag cooperative cancellation — the current step will finish."""
        self._cancel_requested = True
        self.status_label.setText(
            "Cancellation requested — waiting for the current step…")

    # ------------------------------------------------------------ Rendering

    def _render_result(self, result: Any) -> None:
        """Render the result dict (figure, table, html) into the stacked panes."""
        self._last_figure = None
        self._last_table = None
        self._last_html = None

        if result is None:
            self._clear_figure()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self.html_browser.clear()
            return

        if not isinstance(result, dict):
            # Treat as opaque result object
            self.html_browser.setPlainText(str(result))
            return

        fig = result.get("figure")
        table = result.get("table")
        html = result.get("html")
        if fig is not None:
            self._last_figure = fig
            self._render_figure(fig)
        else:
            self._clear_figure()
        if table is not None:
            self._last_table = table
            self._render_table(table)
        else:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
        if html is not None:
            self._last_html = html
            self.html_browser.setHtml(html)
        else:
            self.html_browser.clear()

    def _render_figure(self, fig: Any) -> None:
        """Replace the embedded figure with the one provided by the analysis."""
        if self._canvas is None:
            return
        # Replace canvas figure: simplest approach is to update Figure attribute.
        try:
            self._figure.clear()
            # Copy axes from the provided figure
            for ax in fig.get_axes():
                # Re-add via subplot position copying is complex; use blit copy instead.
                pass
            # Simpler: swap the canvas figure to the result figure.
            self._canvas.figure = fig
            self._figure = fig
            self._canvas.draw_idle()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to render figure: %s", exc)

    def _clear_figure(self) -> None:
        if self._ax is None:
            return
        self._figure.clear()
        self._ax = self._figure.add_subplot(111)
        self._ax.set_axis_off()
        self._ax.text(0.5, 0.5, "No figure available.",
                     ha="center", va="center",
                     transform=self._ax.transAxes, color=ModernTheme.DARK_TEXT_MUTED)
        if self._canvas is not None:
            self._canvas.draw_idle()

    def _render_table(self, table: Any) -> None:
        """Render a list-of-rows (with header row) into the QTableWidget."""
        try:
            rows: List[List[str]] = [list(map(str, r)) for r in table]
        except Exception:  # noqa: BLE001
            rows = []
        if not rows:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return
        headers = rows[0]
        body = rows[1:]
        self.table.setRowCount(len(body))
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        for r, row in enumerate(body):
            for c, val in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(val))
        self.table.resizeColumnsToContents()

    # ------------------------------------------------------------ Exports

    def _export_figure(self) -> None:
        if self._last_figure is None:
            QMessageBox.information(self, "Export Figure", "No figure to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Figure", "analysis.png", "PNG image (*.png)"
        )
        if not path:
            return
        try:
            self._last_figure.savefig(path, format="png")
            logger.info("Figure saved to %s", path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export Figure", f"Failed: {exc}")

    def _export_model(self) -> None:
        if self._last_result is None:
            QMessageBox.information(self, "Save Model", "No model to save.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Model", "model.pkl", "Pickle file (*.pkl)"
        )
        if not path:
            return
        try:
            import pickle
            with open(path, "wb") as fh:
                pickle.dump(self._last_result, fh)
            logger.info("Model saved to %s", path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save Model", f"Failed: {exc}")

    def _export_csv(self) -> None:
        if not self._last_table:
            QMessageBox.information(self, "Export CSV", "No tabular results to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Results CSV", "results.csv", "CSV file (*.csv)"
        )
        if not path:
            return
        try:
            import csv
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerows(self._last_table)
            logger.info("CSV exported to %s", path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export CSV", f"Failed: {exc}")
