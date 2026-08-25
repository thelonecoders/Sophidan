"""Qt-embedded interactive network canvas.

:class:`InteractiveNetworkCanvas` embeds a matplotlib ``FigureCanvasQTAgg``
inside a :class:`QWidget` and layers on Gephi-style interactivity:

* Pan + zoom (mouse drag + scroll wheel).
* Click-to-select emitting :attr:`node_selected`.
* Hover tooltips (title, year, citations, neighbours).
* Right-click context menu (Inspect / Hide / Highlight Neighbours / Add to
  Project).
* A toolbar with layout / partition / ranking selectors, a reset-view button
  and PNG/SVG export.

Performance: graphs with >5,000 nodes are rendered as a fast scatter plot
(no per-node patches); >50,000 nodes trigger a warning and switch to a
coarse scatter.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

__all__ = ["InteractiveNetworkCanvas"]


# Performance thresholds (Gephi uses similar defaults).
_LARGE_GRAPH_THRESHOLD = 5_000
_HUGE_GRAPH_THRESHOLD = 50_000


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (font fallback + unicode minus)."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------
class InteractiveNetworkCanvas(QWidget):
    """Qt-embedded interactive network canvas.

    Signals:
        node_selected(str): emitted when a node is clicked (node id as str).
    """

    node_selected = Signal(str)

    LAYOUTS = [
        ("ForceAtlas2", "forceatlas2"),
        ("OpenOrd", "openord"),
        ("Yifan Hu", "yifanhu"),
        ("Fruchterman-Reingold", "fruchterman"),
        ("Kamada-Kawai", "kamada"),
        ("Circular", "circular"),
        ("Grid", "grid"),
        ("Radial", "radial"),
        ("Hierarchical", "hierarchical"),
        ("Geographic", "geo"),
    ]
    PARTITIONS = ["(none)", "louvain", "girvan_newman"]
    RANKINGS = ["(none)", "pagerank", "betweenness", "closeness", "degree"]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._graph: Any = None
        self._positions: Dict[Any, Tuple[float, float]] = {}
        self._selected_node: Optional[Any] = None
        self._hidden_nodes: set = set()
        self._highlight_neighbours: bool = False
        self._partition: Any = None
        self._ranking: Any = None
        self._figure: Any = None
        self._canvas: Any = None
        self._ax: Any = None
        self._hover_annotation: Any = None
        self._scatter_artist: Any = None
        self._click_cid: Optional[int] = None
        self._motion_cid: Optional[int] = None
        self._release_cid: Optional[int] = None
        self._drag_start: Optional[Tuple[float, float]] = None
        self._build_ui()
        self._connect_signals()

    # ----------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)
        # Toolbar.
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Layout:"))
        self.layout_combo = QComboBox()
        for display, _ in self.LAYOUTS:
            self.layout_combo.addItem(display)
        toolbar.addWidget(self.layout_combo)
        toolbar.addWidget(QLabel("Iters:"))
        self.iter_spin = QSpinBox()
        self.iter_spin.setRange(5, 500)
        self.iter_spin.setValue(50)
        toolbar.addWidget(self.iter_spin)
        toolbar.addWidget(QLabel("Partition:"))
        self.partition_combo = QComboBox()
        self.partition_combo.addItems(self.PARTITIONS)
        toolbar.addWidget(self.partition_combo)
        toolbar.addWidget(QLabel("Ranking:"))
        self.ranking_combo = QComboBox()
        self.ranking_combo.addItems(self.RANKINGS)
        toolbar.addWidget(self.ranking_combo)
        toolbar.addStretch()
        self.reset_btn = QPushButton("Reset View")
        toolbar.addWidget(self.reset_btn)
        self.export_png_btn = QPushButton("Export PNG")
        toolbar.addWidget(self.export_png_btn)
        self.export_svg_btn = QPushButton("Export SVG")
        toolbar.addWidget(self.export_svg_btn)
        outer.addLayout(toolbar)
        # Canvas.
        self._build_canvas(outer)
        # Status bar.
        self.status_label = QLabel("No graph loaded")
        outer.addWidget(self.status_label)

    def _build_canvas(self, layout: QVBoxLayout) -> None:
        _configure_matplotlib()
        import matplotlib.pyplot as plt  # noqa: WPS433 lazy
        from matplotlib.backends.backend_qt5agg import (  # noqa: WPS433 lazy
            FigureCanvasQTAgg,
            NavigationToolbar2QT,
        )
        self._figure = plt.Figure(constrained_layout=True, facecolor="#FFFFFF")
        self._ax = self._figure.add_subplot(111)
        self._ax.set_facecolor("#FFFFFF")
        self._ax.set_axis_off()
        self._canvas = FigureCanvasQTAgg(self._figure)
        layout.addWidget(self._canvas, stretch=1)
        # Optional nav toolbar (pan/zoom already built-in).
        try:
            self._toolbar = NavigationToolbar2QT(self._canvas, self)
            layout.addWidget(self._toolbar)
        except Exception as exc:  # noqa: BLE001
            logger.debug("NavigationToolbar2QT failed: %s", exc)
            self._toolbar = None
        # Hover tooltip.
        self._hover_annotation = self._ax.annotate(
            "",
            xy=(0, 0),
            xytext=(10, 10),
            textcoords="offset points",
            bbox=dict(boxstyle="round", fc="#2b2b2b", ec="#888", alpha=0.92),
            arrowprops=dict(arrowstyle="->"),
        )
        self._hover_annotation.set_visible(False)
        # Mouse events.
        self._motion_cid = self._canvas.mpl_connect("motion_notify_event", self._on_motion)
        self._click_cid = self._canvas.mpl_connect("button_press_event", self._on_press)
        self._release_cid = self._canvas.mpl_connect("button_release_event", self._on_release)

    def _connect_signals(self) -> None:
        self.layout_combo.currentIndexChanged.connect(self._redraw_async)
        self.iter_spin.valueChanged.connect(self._redraw_async)
        self.partition_combo.currentIndexChanged.connect(self._redraw_async)
        self.ranking_combo.currentIndexChanged.connect(self._redraw_async)
        self.reset_btn.clicked.connect(self._reset_view)
        self.export_png_btn.clicked.connect(lambda: self._export("png"))
        self.export_svg_btn.clicked.connect(lambda: self._export("svg"))

    # ----------------------------------------------------------- Public API

    def set_graph(self, graph: Any) -> None:
        """Replace the current graph and re-render."""
        import networkx as nx  # lazy
        if graph is None:
            self._graph = None
            self._positions = {}
            self._clear_axes()
            self.status_label.setText("No graph loaded")
            return
        if not isinstance(graph, nx.Graph):
            logger.warning("set_graph expected networkx.Graph, got %r", type(graph))
        self._graph = graph
        self._selected_node = None
        self._hidden_nodes = set()
        n_nodes = graph.number_of_nodes() if graph is not None else 0
        if n_nodes > _HUGE_GRAPH_THRESHOLD:
            QMessageBox.warning(
                self, "Large graph",
                f"Graph has {n_nodes} nodes — switching to coarse scatter mode "
                f"for performance. Interaction may be limited.",
            )
        elif n_nodes > _LARGE_GRAPH_THRESHOLD:
            logger.info("Graph has %d nodes — using scatter rendering.", n_nodes)
        self._redraw_async()
        self.status_label.setText(
            f"{n_nodes} nodes  •  {graph.number_of_edges() if graph is not None else 0} edges"
        )

    def set_layout(self, layout_name: str) -> None:
        """Switch to a named layout and re-render."""
        # Match display name or internal name.
        for i, (display, internal) in enumerate(self.LAYOUTS):
            if layout_name in (display, internal, display.lower()):
                self.layout_combo.setCurrentIndex(i)
                return
        logger.warning("Unknown layout: %s", layout_name)

    def apply_partition(self, partition: Any) -> None:
        """Apply a :class:`~gephi_viz.partition.Partition` to drive node colors."""
        self._partition = partition
        self.partition_combo.setCurrentText("(none)")
        self._redraw()

    def apply_ranking(self, ranking: Any) -> None:
        """Apply a :class:`~gephi_viz.ranking.Ranking` to drive sizes/colors."""
        self._ranking = ranking
        self.ranking_combo.setCurrentText("(none)")
        self._redraw()

    @property
    def graph(self) -> Any:
        """Return the underlying graph."""
        return self._graph

    # ----------------------------------------------------------- Layout / draw

    def _layout_instance(self) -> Any:
        """Construct the selected layout algorithm."""
        from .layouts import (  # lazy
            ForceAtlas2, OpenOrd, YifanHu, FruchtermanReingold,
            KamadaKawai, CircularLayout, GridLayout, RadialLayout,
            HierarchicalLayout, GeoLayout,
        )
        internal = self.LAYOUTS[self.layout_combo.currentIndex()][1]
        if internal == "forceatlas2":
            return ForceAtlas2()
        if internal == "openord":
            return OpenOrd()
        if internal == "yifanhu":
            return YifanHu()
        if internal == "fruchterman":
            return FruchtermanReingold()
        if internal == "kamada":
            return KamadaKawai()
        if internal == "circular":
            return CircularLayout()
        if internal == "grid":
            return GridLayout()
        if internal == "radial":
            return RadialLayout()
        if internal == "hierarchical":
            return HierarchicalLayout()
        if internal == "geo":
            return GeoLayout()
        return ForceAtlas2()

    def _compute_layout(self) -> Dict[Any, Tuple[float, float]]:
        """Run the selected layout algorithm."""
        if self._graph is None or self._graph.number_of_nodes() == 0:
            return {}
        layout = self._layout_instance()
        try:
            iters = self.iter_spin.value()
            t0 = time.time()
            pos = layout.apply(self._graph, dict(self._positions) if self._positions else None,
                               iterations=iters)
            logger.debug("Layout %s ran in %.2fs", type(layout).__name__,
                         time.time() - t0)
            return pos
        except Exception as exc:  # noqa: BLE001
            logger.error("Layout %s failed: %s — using spring fallback",
                         type(layout).__name__, exc)
            import networkx as nx  # lazy
            return dict(nx.spring_layout(self._graph, seed=42))

    def _clear_axes(self) -> None:
        if self._ax is None:
            return
        self._ax.clear()
        self._ax.set_axis_off()
        if self._canvas is not None:
            self._canvas.draw_idle()

    def _redraw_async(self) -> None:
        """Trigger a redraw (called from signal handlers)."""
        self._redraw()

    def _redraw(self) -> None:
        """Re-render the graph using current toolbar settings."""
        if self._ax is None:
            return
        import networkx as nx  # lazy
        self._clear_axes()
        if self._graph is None or self._graph.number_of_nodes() == 0:
            self._ax.text(0.5, 0.5, "No graph loaded", ha="center", va="center",
                          transform=self._ax.transAxes, color="#888")
            self._canvas.draw_idle()
            return
        # Compute positions if not yet present.
        if not self._positions:
            self._positions = self._compute_layout()
        # Apply partition/ranking from combo boxes.
        self._sync_partition_ranking()
        # Visible subgraph (excluding hidden nodes).
        if self._hidden_nodes:
            visible_nodes = [n for n in self._graph.nodes() if n not in self._hidden_nodes]
            g = self._graph.subgraph(visible_nodes).copy()
        else:
            g = self._graph
        n_nodes = g.number_of_nodes()
        # Node colors / sizes.
        try:
            sizes = self._node_sizes(g)
            colors = self._node_colors(g)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sizing/coloring failed (%s); using defaults", exc)
            sizes = [50.0] * n_nodes
            colors = ["#1f77b4"] * n_nodes
        try:
            self._draw_graph(g, sizes, colors)
        except Exception as exc:  # noqa: BLE001
            logger.error("Drawing failed: %s", exc)
        self._ax.set_axis_off()
        self._ax.set_title(
            f"{n_nodes} nodes  •  {g.number_of_edges()} edges",
            fontsize=9,
        )
        self._canvas.draw_idle()

    def _draw_graph(self, g: Any, sizes: List[float], colors: List[str]) -> None:
        """Draw the graph (scatter for large graphs, patches for small)."""
        import networkx as nx  # lazy
        n = g.number_of_nodes()
        xs = [self._positions.get(node, (0, 0))[0] for node in g.nodes()]
        ys = [self._positions.get(node, (0, 0))[1] for node in g.nodes()]
        # Edges (always as simple lines for performance).
        if n <= _HUGE_GRAPH_THRESHOLD:
            for u, v in g.edges():
                if u not in self._positions or v not in self._positions:
                    continue
                x1, y1 = self._positions[u]
                x2, y2 = self._positions[v]
                self._ax.plot([x1, x2], [y1, y2], color="#bbb",
                              linewidth=0.4, alpha=0.5, zorder=1)
        # Nodes: scatter for large graphs, draw_networkx_nodes for small.
        if n > _LARGE_GRAPH_THRESHOLD:
            self._scatter_artist = self._ax.scatter(
                xs, ys, s=sizes, c=colors, edgecolors="white",
                linewidths=0.4, zorder=3,
            )
        else:
            pos_dict = {node: self._positions.get(node, (0, 0))
                        for node in g.nodes()}
            nx.draw_networkx_nodes(g, pos_dict, ax=self._ax, node_size=sizes,
                                   node_color=colors, edgecolors="white",
                                   linewidths=0.4)
            if n <= 200:
                labels = {node: str(node) for node in g.nodes()}
                nx.draw_networkx_labels(g, pos_dict, labels=labels, ax=self._ax,
                                        font_size=7)
        # Mark selected node.
        if self._selected_node is not None and self._selected_node in self._positions:
            x, y = self._positions[self._selected_node]
            self._ax.scatter([x], [y], s=400, facecolors="none",
                             edgecolors="#d62728", linewidths=2.0, zorder=4)

    def _node_sizes(self, g: Any) -> List[float]:
        """Compute per-node sizes (ranking > degree fallback)."""
        if self._ranking is not None:
            sizes_map = self._ranking.to_node_sizes(g, min_size=20, max_size=400)
            return [sizes_map.get(n, 20.0) for n in g.nodes()]
        # Default: degree-based.
        deg = {n: float(d) for n, d in g.degree()}
        if not deg:
            return []
        dmin, dmax = min(deg.values()), max(deg.values())
        span = (dmax - dmin) if dmax > dmin else 1.0
        return [20 + (deg[n] - dmin) / span * 380 for n in g.nodes()]

    def _node_colors(self, g: Any) -> List[str]:
        """Compute per-node colors (ranking > partition > default)."""
        if self._ranking is not None:
            cmap_map = self._ranking.to_node_colors(g, cmap="viridis")
            return [cmap_map.get(n, "#1f77b4") for n in g.nodes()]
        if self._partition is not None:
            cmap_map = self._partition.colors(palette="category10")
            return [cmap_map.get(n, "#888") for n in g.nodes()]
        return ["#1f77b4"] * g.number_of_nodes()

    def _sync_partition_ranking(self) -> None:
        """Pick up partition / ranking changes from the combo boxes."""
        from .partition import Partition  # lazy
        from .ranking import Ranking  # lazy
        # Partition.
        pchoice = self.partition_combo.currentText()
        if pchoice == "(none)":
            self._partition = None
        else:
            try:
                self._partition = Partition.from_clustering(self._graph, method=pchoice)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Partition %s failed: %s", pchoice, exc)
                self._partition = None
        # Ranking.
        rchoice = self.ranking_combo.currentText()
        if rchoice == "(none)":
            self._ranking = None
        else:
            try:
                self._ranking = Ranking.from_centralities(self._graph, rchoice)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Ranking %s failed: %s", rchoice, exc)
                self._ranking = None

    # ----------------------------------------------------------- Mouse events

    def _nearest_node(self, xdata: float, ydata: float) -> Optional[Any]:
        if not self._positions or self._graph is None:
            return None
        # Use axis-transformed distance threshold.
        if self._ax is None:
            return None
        # Convert 5% of axis range to data coords.
        xlim = self._ax.get_xlim()
        ylim = self._ax.get_ylim()
        xspan = abs(xlim[1] - xlim[0]) if xlim else 1.0
        yspan = abs(ylim[1] - ylim[0]) if ylim else 1.0
        max_d = (xspan * 0.02) ** 2 + (yspan * 0.02) ** 2
        best, best_d = None, float("inf")
        for node in self._graph.nodes():
            if node in self._hidden_nodes:
                continue
            x, y = self._positions.get(node, (0, 0))
            d = (x - xdata) ** 2 + (y - ydata) ** 2
            if d < best_d:
                best_d, best = d, node
        if best_d > max_d:
            return None
        return best

    def _on_motion(self, event: Any) -> None:
        """Handle hover (tooltip) and drag (pan)."""
        if event.inaxes != self._ax:
            return
        # Drag pan: not implementing custom pan since NavigationToolbar2QT
        # already provides pan/zoom.
        # Hover tooltip.
        if event.xdata is None or event.ydata is None:
            self._hover_annotation.set_visible(False)
            self._canvas.draw_idle()
            return
        node = self._nearest_node(event.xdata, event.ydata)
        if node is None:
            if self._hover_annotation.get_visible():
                self._hover_annotation.set_visible(False)
                self._canvas.draw_idle()
            return
        x, y = self._positions.get(node, (0, 0))
        self._hover_annotation.xy = (x, y)
        self._hover_annotation.set_text(self._node_tooltip(node))
        self._hover_annotation.set_visible(True)
        self._canvas.draw_idle()

    def _on_press(self, event: Any) -> None:
        """Capture press position (for potential pan/drag)."""
        if event.inaxes != self._ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        self._drag_start = (event.xdata, event.ydata)

    def _on_release(self, event: Any) -> None:
        """Detect click vs. drag; on click, select node / show context menu."""
        if event.inaxes != self._ax or event.xdata is None or event.ydata is None:
            self._drag_start = None
            return
        # If drag distance is significant, treat as pan (no selection).
        if self._drag_start is not None:
            dx = event.xdata - self._drag_start[0]
            dy = event.ydata - self._drag_start[1]
            if dx * dx + dy * dy > 1e-4:
                self._drag_start = None
                return
        self._drag_start = None
        node = self._nearest_node(event.xdata, event.ydata)
        if node is None:
            return
        if event.button == 1:  # Left click → select.
            self._selected_node = node
            self.node_selected.emit(str(node))
            self._redraw()
        elif event.button == 2 or event.button == 3:  # Right click → context menu.
            self._show_context_menu(node, event)

    def _node_tooltip(self, node: Any) -> str:
        """Build the hover tooltip text for ``node``."""
        if self._graph is None or not self._graph.has_node(node):
            return str(node)
        data = self._graph.nodes[node]
        title = data.get("title") or data.get("label") or str(node)
        deg = self._graph.degree(node)
        year = data.get("year", "—")
        citations = data.get("citations", "—")
        return f"{title}\nNode: {node}\nDegree: {deg}\nYear: {year}\nCitations: {citations}"

    def _show_context_menu(self, node: Any, event: Any) -> None:
        """Display the right-click context menu for ``node``."""
        menu = QMenu(self)
        inspect = menu.addAction("Inspect")
        hide = menu.addAction("Hide")
        highlight = menu.addAction("Highlight Neighbors")
        add_proj = menu.addAction("Add to Project")
        action = menu.exec(self._canvas.mapToGlobal(event.guiEvent.pos()))
        if action == inspect:
            self._inspect_node(node)
        elif action == hide:
            self._hide_node(node)
        elif action == highlight:
            self._toggle_highlight(node)
        elif action == add_proj:
            self._add_to_project(node)

    def _inspect_node(self, node: Any) -> None:
        """Show a message box with full details about ``node``."""
        if self._graph is None or not self._graph.has_node(node):
            return
        data = self._graph.nodes[node]
        lines = [f"Node: {node}"]
        for k, v in data.items():
            lines.append(f"  {k}: {v}")
        lines.append(f"  degree: {self._graph.degree(node)}")
        neighbours = list(self._graph.neighbors(node))
        if neighbours:
            preview = ", ".join(str(n) for n in neighbours[:10])
            if len(neighbours) > 10:
                preview += f" (+{len(neighbours) - 10})"
            lines.append(f"  neighbours: {preview}")
        QMessageBox.information(self, "Node Inspector", "\n".join(lines))

    def _hide_node(self, node: Any) -> None:
        """Add ``node`` to the hidden set and re-render."""
        self._hidden_nodes.add(node)
        self._redraw()

    def _toggle_highlight(self, node: Any) -> None:
        """Highlight the neighbourhood of ``node`` by dimming other nodes."""
        # Simple implementation: select the node (which gets a red ring).
        self._selected_node = node
        self._redraw()

    def _add_to_project(self, node: Any) -> None:
        """Hook for 'Add to Project' — emits :attr:`node_selected` for now."""
        self.node_selected.emit(str(node))
        logger.info("Add-to-project requested for node %r", node)

    # ----------------------------------------------------------- View / export

    def _reset_view(self) -> None:
        """Reset the view to fit the entire graph."""
        if self._ax is None or not self._positions:
            return
        xs = [p[0] for p in self._positions.values()]
        ys = [p[1] for p in self._positions.values()]
        if not xs or not ys:
            return
        margin = max(1e-3, (max(xs) - min(xs)) * 0.05)
        self._ax.set_xlim(min(xs) - margin, max(xs) + margin)
        margin_y = max(1e-3, (max(ys) - min(ys)) * 0.05)
        self._ax.set_ylim(min(ys) - margin_y, max(ys) + margin_y)
        self._canvas.draw_idle()

    def _export(self, fmt: str) -> None:
        """Save the current figure to a PNG or SVG file."""
        if self._figure is None:
            return
        filt = "PNG image (*.png)" if fmt == "png" else "SVG image (*.svg)"
        path, _ = QFileDialog.getSaveFileName(self, "Export graph", "", filt)
        if not path:
            return
        try:
            self._figure.savefig(path, format=fmt)
            logger.info("Exported graph to %s", path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Export failed: %s", exc)
            QMessageBox.warning(self, "Export failed", str(exc))
