"""Interactive graph visualization widget built on matplotlib + networkx.

Provides :class:`NetworkViewWidget` — embeds a ``networkx.Graph`` rendered with
matplotlib's ``FigureCanvasQTAgg`` inside a Qt widget. Supports graph-type /
layout / node-size / edge-filter controls, hover tooltips, click selection,
double-click drill-in, an info side panel, zoom controls and PNG/SVG export.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Graph-type identifiers exposed in the toolbar.
GRAPH_TYPES: List[str] = ["Citation", "Collaboration", "Temporal"]
# Layout algorithm identifiers.
LAYOUTS: List[str] = ["spring", "kamada", "circular", "hierarchical"]
# Node-size metric identifiers.
NODE_SIZE_METRICS: List[str] = ["degree", "betweenness", "closeness", "eigenvector"]


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (font fallback + unicode minus)."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


class NetworkViewWidget(QWidget):
    """Interactive network visualization widget.

    Renders a ``networkx.Graph`` via matplotlib embedded in Qt (FigureCanvasQTAgg
    + NavigationToolbar2QT). Supports hover tooltips, click selection, double-
    click drill-in, and PNG/SVG export.

    Emits:
      * ``node_selected(str)`` when a node is clicked.
      * ``node_double_clicked(str)`` when a node is double-clicked (drill-in).
    """

    node_selected = Signal(str)
    node_double_clicked = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the widget with an empty graph and build the UI."""
        super().__init__(parent)
        self._graph: Any = None
        self._positions: Dict[Any, Tuple[float, float]] = {}
        self._selected_node: Optional[Any] = None
        self._figure: Any = None
        self._canvas: Any = None
        self._toolbar: Any = None
        self._ax: Any = None
        self._hover_annotation: Any = None
        self._click_cid: Optional[int] = None
        self._motion_cid: Optional[int] = None
        self._dbl_cid: Optional[int] = None

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Graph:"))
        self.graph_type_combo = QComboBox()
        self.graph_type_combo.addItems(GRAPH_TYPES)
        toolbar.addWidget(self.graph_type_combo)

        toolbar.addWidget(QLabel("Layout:"))
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(LAYOUTS)
        toolbar.addWidget(self.layout_combo)

        toolbar.addWidget(QLabel("Node size:"))
        self.node_size_combo = QComboBox()
        self.node_size_combo.addItems(NODE_SIZE_METRICS)
        toolbar.addWidget(self.node_size_combo)

        toolbar.addWidget(QLabel("Min edges:"))
        self.min_edge_spin = QSpinBox()
        self.min_edge_spin.setRange(0, 1000)
        self.min_edge_spin.setValue(0)
        toolbar.addWidget(self.min_edge_spin)

        toolbar.addStretch()

        self.relayout_btn = QPushButton("Re-layout")
        toolbar.addWidget(self.relayout_btn)
        self.export_png_btn = QPushButton("Export PNG")
        toolbar.addWidget(self.export_png_btn)
        self.export_svg_btn = QPushButton("Export SVG")
        toolbar.addWidget(self.export_svg_btn)
        outer.addLayout(toolbar)

        # Splitter: canvas + info panel
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Canvas container
        canvas_holder = QFrame()
        canvas_holder.setObjectName("CanvasHolder")
        canvas_layout = QVBoxLayout(canvas_holder)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self._build_canvas(canvas_layout)
        splitter.addWidget(canvas_holder)

        # Right info panel
        info_panel = self._build_info_panel()
        splitter.addWidget(info_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, stretch=1)

        # Bottom legend + zoom
        bottom = QHBoxLayout()
        legend = QLabel(
            "<span style='color:#888'>● Node size = degree (drag toolbar to zoom/pan)</span>"
        )
        bottom.addWidget(legend)
        bottom.addStretch()
        zoom_in = QPushButton("Zoom +")
        zoom_out = QPushButton("Zoom −")
        zoom_in.clicked.connect(self._zoom_in)
        zoom_out.clicked.connect(self._zoom_out)
        bottom.addWidget(zoom_out)
        bottom.addWidget(zoom_in)
        outer.addLayout(bottom)

    def _build_canvas(self, layout: QVBoxLayout) -> None:
        """Build the matplotlib Figure + FigureCanvasQTAgg + NavigationToolbar."""
        _configure_matplotlib()
        import matplotlib.pyplot as plt  # noqa: WPS433 lazy
        from matplotlib.backends.backend_qt5agg import (  # noqa: WPS433 lazy
            FigureCanvasQTAgg,
            NavigationToolbar2QT,
        )
        self._figure = plt.Figure(constrained_layout=True)
        self._ax = self._figure.add_subplot(111)
        self._canvas = FigureCanvasQTAgg(self._figure)
        layout.addWidget(self._canvas, stretch=1)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        layout.addWidget(self._toolbar)

        # Hover annotation (initially hidden)
        self._hover_annotation = self._ax.annotate(
            "",
            xy=(0, 0),
            xytext=(10, 10),
            textcoords="offset points",
            bbox=dict(boxstyle="round", fc="#2b2b2b", ec="#888", alpha=0.92),
            arrowprops=dict(arrowstyle="->"),
        )
        self._hover_annotation.set_visible(False)

        self._click_cid = self._canvas.mpl_connect(
            "button_press_event", self._on_mpl_click
        )
        self._motion_cid = self._canvas.mpl_connect(
            "motion_notify_event", self._on_mpl_motion
        )
        self._dbl_cid = self._canvas.mpl_connect(
            "button_release_event", self._on_mpl_double_release
        )

    def _build_info_panel(self) -> QWidget:
        """Build the right-hand info panel for the currently selected node."""
        panel = QGroupBox("Selected Node")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 6)

        form = QFormLayout()
        form.setSpacing(4)
        self.lbl_title = QLabel("—")
        self.lbl_authors = QLabel("—")
        self.lbl_year = QLabel("—")
        self.lbl_citations = QLabel("—")
        self.lbl_neighbors = QLabel("—")
        for lbl in (self.lbl_title, self.lbl_authors, self.lbl_year,
                    self.lbl_citations, self.lbl_neighbors):
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
        form.addRow("Title:", self.lbl_title)
        form.addRow("Authors:", self.lbl_authors)
        form.addRow("Year:", self.lbl_year)
        form.addRow("Citations:", self.lbl_citations)
        form.addRow("Neighbors:", self.lbl_neighbors)
        layout.addLayout(form)

        layout.addStretch()
        self.info_browser = QTextBrowser()
        self.info_browser.setOpenExternalLinks(True)
        self.info_browser.setMaximumHeight(120)
        layout.addWidget(self.info_browser)
        return panel

    def _connect_signals(self) -> None:
        self.graph_type_combo.currentIndexChanged.connect(self._redraw)
        self.layout_combo.currentIndexChanged.connect(self._redraw)
        self.node_size_combo.currentIndexChanged.connect(self._redraw)
        self.min_edge_spin.valueChanged.connect(self._redraw)
        self.relayout_btn.clicked.connect(self._redraw)
        self.export_png_btn.clicked.connect(lambda: self._export("png"))
        self.export_svg_btn.clicked.connect(lambda: self._export("svg"))

    # -------------------------------------------------------------- Public

    def set_graph(self, graph: Any) -> None:
        """Replace the current graph and re-render."""
        import networkx as nx  # noqa: WPS433 lazy
        if graph is None:
            self._graph = None
            self._positions = {}
            self._clear_axes()
            return
        if not isinstance(graph, nx.Graph):
            logger.warning("set_graph expected networkx.Graph, got %r", type(graph))
            self._graph = graph
        else:
            self._graph = graph
        self._selected_node = None
        self._redraw()

    @property
    def graph(self) -> Any:
        """Return the underlying networkx graph (or None)."""
        return self._graph

    # -------------------------------------------------------------- Drawing

    def _compute_layout(self) -> Dict[Any, Tuple[float, float]]:
        """Compute node positions using the selected layout algorithm."""
        import networkx as nx  # noqa: WPS433 lazy
        g = self._graph
        if g is None or g.number_of_nodes() == 0:
            return {}
        layout_name = self.layout_combo.currentText()
        try:
            if layout_name == "spring":
                pos = nx.spring_layout(g, seed=42)
            elif layout_name == "kamada":
                pos = nx.kamada_kawai_layout(g)
            elif layout_name == "circular":
                pos = nx.circular_layout(g)
            elif layout_name == "hierarchical":
                # Approximate hierarchical via shell layout with degree buckets.
                nodes = list(g.nodes())
                nodes_sorted = sorted(
                    nodes, key=lambda n: g.degree(n), reverse=True
                )
                layers = 4
                buckets: List[List[Any]] = [[] for _ in range(layers)]
                for i, n in enumerate(nodes_sorted):
                    buckets[i % layers].append(n)
                pos = nx.shell_layout(g, shells=buckets)
            else:
                pos = nx.spring_layout(g, seed=42)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Layout %s failed (%s); falling back to spring", layout_name, exc)
            pos = nx.spring_layout(g, seed=42)
        return pos

    def _node_sizes(self) -> List[float]:
        """Compute per-node sizes based on the selected metric."""
        import networkx as nx  # noqa: WPS433 lazy
        g = self._graph
        if g is None or g.number_of_nodes() == 0:
            return []
        metric = self.node_size_combo.currentText()
        try:
            if metric == "betweenness":
                values = nx.betweenness_centrality(g)
            elif metric == "closeness":
                values = nx.closeness_centrality(g)
            elif metric == "eigenvector":
                values = nx.eigenvector_centrality(g, max_iter=500, tol=1e-6)
            else:
                values = {n: float(g.degree(n)) for n in g.nodes()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Centrality %s failed (%s); using degree", metric, exc)
            values = {n: float(g.degree(n)) for n in g.nodes()}

        max_v = max(values.values()) if values else 1.0
        if max_v <= 0:
            max_v = 1.0
        return [40 + 600 * (values.get(n, 0) / max_v) for n in g.nodes()]

    def _filter_graph(self) -> Any:
        """Return a subgraph copy after applying the minimum-edge filter."""
        import networkx as nx  # noqa: WPS433 lazy
        if self._graph is None:
            return None
        threshold = self.min_edge_spin.value()
        if threshold <= 0:
            return self._graph
        keep = [n for n, d in self._graph.degree() if d >= threshold]
        return self._graph.subgraph(keep).copy()

    def _clear_axes(self) -> None:
        if self._ax is None:
            return
        self._ax.clear()
        self._ax.set_axis_off()
        if self._canvas is not None:
            self._canvas.draw_idle()

    def _redraw(self) -> None:
        """Re-render the graph using current toolbar settings."""
        if self._ax is None:
            return
        import networkx as nx  # noqa: WPS433 lazy
        self._clear_axes()
        g = self._filter_graph()
        if g is None or g.number_of_nodes() == 0:
            self._ax.text(0.5, 0.5, "No graph loaded", ha="center", va="center",
                          transform=self._ax.transAxes, color="#888")
            self._canvas.draw_idle()
            return

        self._positions = self._compute_layout()
        sizes = self._node_sizes()
        try:
            colors = self._node_colors(g)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Coloring failed (%s); using single color", exc)
            colors = ["#007acc"] * g.number_of_nodes()

        try:
            nx.draw_networkx_edges(g, self._positions, ax=self._ax, alpha=0.4,
                                   edge_color="#888")
            nx.draw_networkx_nodes(g, self._positions, ax=self._ax, node_size=sizes,
                                   node_color=colors, edgecolors="white",
                                   linewidths=0.5)
            nx.draw_networkx_labels(g, self._positions, ax=self._ax, font_size=7)
        except Exception as exc:  # noqa: BLE001
            logger.error("Drawing graph failed: %s", exc)
        self._ax.set_axis_off()
        title = f"{g.number_of_nodes()} nodes  •  {g.number_of_edges()} edges"
        self._ax.set_title(title, fontsize=9)
        self._canvas.draw_idle()

    def _node_colors(self, g: Any) -> List[str]:
        """Color nodes via greedy coloring."""
        import networkx as nx  # noqa: WPS433 lazy
        try:
            coloring = nx.coloring.greedy_color(g, strategy="largest_first")
        except Exception:  # noqa: BLE001
            return ["#007acc"] * g.number_of_nodes()
        n_colors = max(coloring.values()) + 1 if coloring else 1
        cmap = [
            "#007acc", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
            "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        ]
        return [cmap[coloring.get(n, 0) % len(cmap)] for n in g.nodes()]

    # ------------------------------------------------------- Mouse handling

    def _nearest_node(self, xdata: float, ydata: float) -> Optional[Any]:
        if not self._positions:
            return None
        best, best_d = None, float("inf")
        for node, (x, y) in self._positions.items():
            d = (x - xdata) ** 2 + (y - ydata) ** 2
            if d < best_d:
                best_d, best = d, node
        # threshold: 5% of axis range
        if self._ax is not None and best_d > 0.01:
            return None
        return best

    def _on_mpl_motion(self, event: Any) -> None:
        """Show tooltip on hover."""
        if event.inaxes != self._ax or self._positions is None:
            return
        node = self._nearest_node(event.xdata, event.ydata)
        if node is None:
            self._hover_annotation.set_visible(False)
            self._canvas.draw_idle()
            return
        x, y = self._positions[node]
        self._hover_annotation.xy = (x, y)
        info = self._node_tooltip(node)
        self._hover_annotation.set_text(info)
        self._hover_annotation.set_visible(True)
        self._canvas.draw_idle()

    def _on_mpl_click(self, event: Any) -> None:
        """Select node on click (single)."""
        if event.inaxes != self._ax or event.dblclick:
            return
        if event.xdata is None or event.ydata is None:
            return
        node = self._nearest_node(event.xdata, event.ydata)
        if node is None:
            return
        self._selected_node = node
        self.node_selected.emit(str(node))
        self._refresh_info_panel(node)

    def _on_mpl_double_release(self, event: Any) -> None:
        """Trigger drill-in on double click."""
        if event.inaxes != self._ax or event.xdata is None or event.ydata is None:
            return
        if event.dblclick:
            node = self._nearest_node(event.xdata, event.ydata)
            if node is not None:
                self.node_double_clicked.emit(str(node))

    def _node_tooltip(self, node: Any) -> str:
        g = self._graph
        if g is None:
            return str(node)
        data = g.nodes[node] if g.has_node(node) else {}
        title = data.get("title") or data.get("label") or str(node)
        deg = g.degree(node) if g.has_node(node) else 0
        year = data.get("year", "")
        return f"{title}\nNode: {node}\nDegree: {deg}\nYear: {year}"

    def _refresh_info_panel(self, node: Any) -> None:
        g = self._graph
        if g is None or not g.has_node(node):
            return
        data = g.nodes[node]
        neighbors = list(g.neighbors(node))
        self.lbl_title.setText(str(data.get("title") or node))
        self.lbl_authors.setText(str(data.get("authors", "—")))
        self.lbl_year.setText(str(data.get("year", "—")))
        self.lbl_citations.setText(str(data.get("citations", "—")))
        self.lbl_neighbors.setText(f"{len(neighbors)} neighbors")
        if neighbors:
            preview = ", ".join(str(n) for n in neighbors[:10])
            if len(neighbors) > 10:
                preview += f" (+{len(neighbors) - 10})"
            self.info_browser.setText(preview)
        else:
            self.info_browser.setText("")

    # ------------------------------------------------------- Zoom / export

    def _zoom_in(self) -> None:
        if self._ax is None:
            return
        xlim = self._ax.get_xlim()
        ylim = self._ax.get_ylim()
        cx = sum(xlim) / 2
        cy = sum(ylim) / 2
        dx = (xlim[1] - xlim[0]) * 0.2
        dy = (ylim[1] - ylim[0]) * 0.2
        self._ax.set_xlim(cx - dx, cx + dx)
        self._ax.set_ylim(cy - dy, cy + dy)
        self._canvas.draw_idle()

    def _zoom_out(self) -> None:
        if self._ax is None:
            return
        xlim = self._ax.get_xlim()
        ylim = self._ax.get_ylim()
        cx = sum(xlim) / 2
        cy = sum(ylim) / 2
        dx = (xlim[1] - xlim[0]) * 0.8
        dy = (ylim[1] - ylim[0]) * 0.8
        self._ax.set_xlim(cx - dx, cx + dx)
        self._ax.set_ylim(cy - dy, cy + dy)
        self._canvas.draw_idle()

    def _export(self, fmt: str) -> None:
        if self._figure is None:
            return
        filt = "PNG image (*.png)" if fmt == "png" else "SVG image (*.svg)"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export graph", "", filt
        )
        if not path:
            return
        try:
            self._figure.savefig(path, format=fmt)
            logger.info("Graph exported to %s", path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Export failed: %s", exc)
