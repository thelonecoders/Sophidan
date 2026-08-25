"""Gephi-style "Preview" tab — publication-grade network rendering.

Wraps matplotlib / pyvis / plotly / Cytoscape.js behind a single
:class:`PreviewRenderer` driven by a :class:`PreviewSettings` dataclass.
The renderer can also accept an optional :class:`~gephi_viz.partition.Partition`
and :class:`~gephi_viz.ranking.Ranking` to drive node colors / sizes /
edge widths.

All matplotlib figures use ``constrained_layout=True`` (never
``tight_layout()``); project-wide rcParams (font fallback + unicode minus) are
applied via :func:`_configure_matplotlib`.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = ["PreviewSettings", "PreviewRenderer"]


# ---------------------------------------------------------------------------
# Settings dataclass
# ---------------------------------------------------------------------------
@dataclass
class PreviewSettings:
    """Settings for the :class:`PreviewRenderer`.

    Mirrors Gephi's Preview tab: node shape / size range, edge style, labels,
    background colour, legend visibility, etc.

    Attributes:
        node_shape: ``'circle'``, ``'square'``, ``'diamond'`` or ``'triangle'``.
        node_size_min: Lower bound on rendered node size (points).
        node_size_max: Upper bound on rendered node size (points).
        node_color_palette: Palette name when partition drives node colors.
        edge_color: Default edge hex colour (used when no ranking is set).
        edge_width_min: Lower bound on rendered edge width (points).
        edge_width_max: Upper bound on rendered edge width (points).
        edge_curved: Draw curved edges (matplotlib FancyArrowPatch).
        edge_opacity: Edge alpha in ``[0, 1]``.
        show_node_labels: Render node labels.
        font_family: Label font family.
        font_size: Label font size (points).
        font_color: Label hex colour.
        show_edge_labels: Render edge labels (uses edge ``label`` attr).
        background_color: Canvas hex colour.
        show_legend: Render a legend when a partition is supplied.
        label_shorten: Truncate labels to ~20 characters with ``…``.
        arrow_size: Arrow head size (points) for directed edges.
    """

    node_shape: str = "circle"
    node_size_min: float = 5.0
    node_size_max: float = 50.0
    node_color_palette: str = "category10"
    edge_color: str = "#888888"
    edge_width_min: float = 0.3
    edge_width_max: float = 3.0
    edge_curved: bool = True
    edge_opacity: float = 0.5
    show_node_labels: bool = True
    font_family: str = "Inter"
    font_size: float = 8.0
    font_color: str = "#000000"
    show_edge_labels: bool = False
    background_color: str = "#FFFFFF"
    show_legend: bool = True
    label_shorten: bool = True
    arrow_size: float = 2.0


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (font fallback + unicode minus)."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def _shorten(label: str, n: int = 20) -> str:
    """Truncate ``label`` to ``n`` chars with an ellipsis (if needed)."""
    if not label:
        return ""
    s = str(label)
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


# Map partition-palette names to matplotlib colormap equivalents (for rankings).
_PARTITION_PALETTE_TO_CMAP = {
    "category10": "viridis",
    "set3": "tab20",
    "spectral": "Spectral",
    "viridis": "viridis",
}


def _partition_palette_to_mpl_cmap(palette: str) -> str:
    """Translate a partition palette name to a matplotlib colormap name.

    ``'category10'`` → ``'viridis'``; ``'spectral'`` → ``'Spectral'``;
    ``'set3'`` → ``'tab20'``. Anything else is returned unchanged (letting
    matplotlib raise the usual warning).
    """
    return _PARTITION_PALETTE_TO_CMAP.get(palette.lower().strip(), palette)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------
class PreviewRenderer:
    """Publication-grade renderer for ``networkx`` graphs.

    The renderer accepts:

    * a ``networkx`` graph (with optional ``pos`` node attribute, or one
      computed via a layout),
    * an optional :class:`~gephi_viz.partition.Partition` (node colors),
    * an optional :class:`~gephi_viz.ranking.Ranking` (node sizes / edge
      widths / colors, *overrides* the partition colors when present),
    * a :class:`PreviewSettings` instance.

    The renderer supports matplotlib (PNG/SVG/PDF), pyvis (interactive HTML),
    plotly (interactive HTML, optional 3D), and Cytoscape.js (interactive HTML).
    """

    def __init__(
        self,
        graph: Any,
        settings: Optional[PreviewSettings] = None,
        partition: Optional[Any] = None,
        ranking: Optional[Any] = None,
        positions: Optional[Dict[Any, Tuple[float, float]]] = None,
    ) -> None:
        self.graph = graph
        self.settings = settings or PreviewSettings()
        self.partition = partition
        self.ranking = ranking
        self._positions = positions

    # ----------------------------------------------------------- Positions

    def positions(self) -> Dict[Any, Tuple[float, float]]:
        """Return the node positions used for rendering.

        If ``positions`` was supplied at construction it is reused; otherwise
        the graph's ``pos`` node attribute is used; otherwise a spring layout
        is computed (with a fixed seed for reproducibility).
        """
        import networkx as nx  # lazy
        if self._positions is not None:
            return dict(self._positions)
        # Check for a 'pos' node attribute.
        if self.graph.number_of_nodes() > 0:
            first = next(iter(self.graph.nodes(data=True)))
            if first[1].get("pos") is not None:
                return {n: tuple(data["pos"]) for n, data in self.graph.nodes(data=True)}
        # Fall back to spring layout.
        try:
            pos = nx.spring_layout(self.graph, seed=42)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Spring layout failed: %s — using random layout.", exc)
            pos = nx.random_layout(self.graph, seed=42)
        return dict(pos)

    # ----------------------------------------------------------- Style prep

    def _node_sizes(self) -> Dict[Any, float]:
        """Compute per-node sizes (driven by ranking if present, else degree)."""
        s = self.settings
        if self.ranking is not None:
            sizes = self.ranking.to_node_sizes(self.graph,
                                               min_size=s.node_size_min,
                                               max_size=s.node_size_max)
            # Fill missing.
            for n in self.graph.nodes():
                if n not in sizes:
                    sizes[n] = s.node_size_min
            return sizes
        # Default: degree-based sizing.
        import math as _math
        deg = {n: float(d) for n, d in self.graph.degree()}
        if not deg:
            return {}
        dmin = min(deg.values())
        dmax = max(deg.values())
        out: Dict[Any, float] = {}
        span = (dmax - dmin) if dmax > dmin else 1.0
        for n, d in deg.items():
            t = (d - dmin) / span
            out[n] = s.node_size_min + t * (s.node_size_max - s.node_size_min)
        return out

    def _node_colors(self) -> Dict[Any, str]:
        """Compute per-node colors (ranking → partition → default)."""
        s = self.settings
        if self.ranking is not None:
            # Partition palette names aren't always valid mpl colormaps; map
            # them to a sensible sequential colormap equivalent.
            cmap = _partition_palette_to_mpl_cmap(s.node_color_palette)
            return self.ranking.to_node_colors(self.graph, cmap=cmap)
        if self.partition is not None:
            return self.partition.colors(palette=s.node_color_palette)
        return {n: "#1f77b4" for n in self.graph.nodes()}

    def _edge_widths(self) -> Dict[Tuple[Any, Any], float]:
        """Compute per-edge widths."""
        s = self.settings
        if self.ranking is not None:
            return self.ranking.to_edge_widths(self.graph,
                                               min_width=s.edge_width_min,
                                               max_width=s.edge_width_max)
        return {(u, v): s.edge_width_min for u, v in self.graph.edges()}

    def _edge_colors(self) -> Dict[Tuple[Any, Any], str]:
        """Compute per-edge colors."""
        s = self.settings
        if self.ranking is not None:
            return self.ranking.to_edge_colors(self.graph, cmap="viridis")
        return {(u, v): s.edge_color for u, v in self.graph.edges()}

    def _node_labels(self) -> Dict[Any, str]:
        """Compute per-node label text (only for nodes that should be labelled)."""
        s = self.settings
        if not s.show_node_labels:
            return {}
        if self.ranking is not None:
            labels = self.ranking.to_node_labels(self.graph, top_n=20)
        else:
            labels = {}
            for n in self.graph.nodes():
                data = self.graph.nodes[n]
                labels[n] = data.get("label") or data.get("title") or str(n)
        if s.label_shorten:
            labels = {n: _shorten(t) for n, t in labels.items()}
        return labels

    # ----------------------------------------------------------- Matplotlib

    def render_matplotlib(self, figsize: Tuple[float, float] = (12, 12),
                          dpi: int = 300):
        """Render the graph to a matplotlib ``Figure`` (PNG/SVG/PDF-friendly).

        Args:
            figsize: Figure size in inches.
            dpi: Dots per inch.

        Returns:
            A :class:`matplotlib.figure.Figure` (caller is responsible for
            saving / closing it).
        """
        import matplotlib.pyplot as plt  # lazy
        from matplotlib.lines import Line2D  # lazy
        from matplotlib.patches import Circle, Polygon, RegularPolygon  # lazy
        import numpy as np  # lazy
        _configure_matplotlib()
        s = self.settings
        # Background colour.
        facecolor = s.background_color
        fig = plt.Figure(figsize=figsize, dpi=dpi, constrained_layout=True,
                         facecolor=facecolor)
        ax = fig.add_subplot(111)
        ax.set_facecolor(facecolor)
        ax.set_axis_off()
        if self.graph is None or self.graph.number_of_nodes() == 0:
            ax.text(0.5, 0.5, "No graph", ha="center", va="center",
                    transform=ax.transAxes, color="#888888")
            return fig
        pos = self.positions()
        sizes = self._node_sizes()
        colors = self._node_colors()
        ewidths = self._edge_widths()
        ecolors = self._edge_colors()
        # Draw edges.
        for (u, v), w in ewidths.items():
            if u not in pos or v not in pos:
                continue
            x1, y1 = pos[u]
            x2, y2 = pos[v]
            color = ecolors.get((u, v), s.edge_color)
            if s.edge_curved:
                # Quadratic Bezier via ConnectionPatch-like arc.
                import matplotlib.path as mpath  # lazy
                import matplotlib.patches as mpatches  # lazy
                mid_x = (x1 + x2) / 2.0 + (y2 - y1) * 0.1
                mid_y = (y1 + y2) / 2.0 - (x2 - x1) * 0.1
                path = mpath.Path(
                    [(x1, y1), (mid_x, mid_y), (x2, y2)],
                    [mpath.Path.MOVETO, mpath.Path.CURVE3, mpath.Path.CURVE3],
                )
                patch = mpatches.PathPatch(path, fill=False, edgecolor=color,
                                           linewidth=w, alpha=s.edge_opacity,
                                           zorder=1)
                ax.add_patch(patch)
            else:
                ax.plot([x1, x2], [y1, y2], color=color, linewidth=w,
                        alpha=s.edge_opacity, zorder=1, solid_capstyle="round")
            # Arrows for directed graphs.
            if self.graph.is_directed() and s.arrow_size > 0:
                dx, dy = (x2 - x1), (y2 - y1)
                length = float((dx ** 2 + dy ** 2) ** 0.5) or 1e-6
                # Place arrow at ~90% of the edge to avoid being hidden by node.
                ax.scatter(
                    [x1 + 0.85 * dx], [y1 + 0.85 * dy],
                    marker=">", s=s.arrow_size * 10,
                    color=color, alpha=s.edge_opacity, zorder=2,
                )
        # Draw nodes.
        for n in self.graph.nodes():
            if n not in pos:
                continue
            x, y = pos[n]
            sz = sizes.get(n, s.node_size_min)
            color = colors.get(n, "#1f77b4")
            # Convert matplotlib size (area) to radius.
            radius = float(np.sqrt(sz)) * 0.012
            shape = s.node_shape.lower()
            if shape == "square":
                patch = Polygon([(x - radius, y - radius),
                                 (x + radius, y - radius),
                                 (x + radius, y + radius),
                                 (x - radius, y + radius)],
                                closed=True, facecolor=color,
                                edgecolor="white", linewidth=0.4, zorder=3)
                ax.add_patch(patch)
            elif shape == "diamond":
                patch = Polygon([(x, y + radius * 1.4),
                                 (x + radius * 1.4, y),
                                 (x, y - radius * 1.4),
                                 (x - radius * 1.4, y)],
                                closed=True, facecolor=color,
                                edgecolor="white", linewidth=0.4, zorder=3)
                ax.add_patch(patch)
            elif shape == "triangle":
                patch = RegularPolygon((x, y), numVertices=3, radius=radius * 1.4,
                                       orientation=0, facecolor=color,
                                       edgecolor="white", linewidth=0.4, zorder=3)
                ax.add_patch(patch)
            else:  # circle
                patch = Circle((x, y), radius=radius, facecolor=color,
                               edgecolor="white", linewidth=0.4, zorder=3)
                ax.add_patch(patch)
        # Draw labels.
        labels = self._node_labels()
        for n, text in labels.items():
            if n not in pos:
                continue
            x, y = pos[n]
            sz = sizes.get(n, s.node_size_min)
            radius = float(np.sqrt(sz)) * 0.012
            ax.text(x, y - radius - 0.02, text,
                    fontsize=s.font_size, color=s.font_color,
                    ha="center", va="top", family=s.font_family, zorder=4)
        # Axes bounds.
        xs = [p[0] for p in pos.values()]
        ys = [p[1] for p in pos.values()]
        if xs and ys:
            margin = max(1e-3, (max(xs) - min(xs)) * 0.05)
            ax.set_xlim(min(xs) - margin, max(xs) + margin)
            ax.set_ylim(min(ys) - margin, max(ys) + margin)
            ax.set_aspect("equal", adjustable="datalim")
        # Legend.
        if s.show_legend and self.partition is not None:
            legend_items = self.partition.legend(palette=s.node_color_palette)
            handles = [Line2D([0], [0], marker="o", linestyle="", markersize=8,
                             markerfacecolor=c, markeredgecolor="white",
                             label=lbl)
                       for lbl, c in legend_items]
            ax.legend(handles=handles, loc="best", fontsize=s.font_size,
                      framealpha=0.85)
        return fig

    # ----------------------------------------------------------- Exporters

    def export_png(self, path: str, dpi: int = 300,
                   figsize: Tuple[float, float] = (12, 12)) -> None:
        """Save the matplotlib figure to ``path`` as a PNG."""
        fig = self.render_matplotlib(figsize=figsize, dpi=dpi)
        fig.savefig(path, format="png", dpi=dpi, facecolor=fig.get_facecolor())
        logger.info("PreviewRenderer exported PNG to %s", path)

    def export_svg(self, path: str,
                  figsize: Tuple[float, float] = (12, 12)) -> None:
        """Save the matplotlib figure to ``path`` as SVG."""
        fig = self.render_matplotlib(figsize=figsize, dpi=72)
        fig.savefig(path, format="svg", facecolor=fig.get_facecolor())
        logger.info("PreviewRenderer exported SVG to %s", path)

    def export_pdf(self, path: str,
                  figsize: Tuple[float, float] = (12, 12)) -> None:
        """Save the matplotlib figure to ``path`` as PDF."""
        fig = self.render_matplotlib(figsize=figsize, dpi=300)
        fig.savefig(path, format="pdf", facecolor=fig.get_facecolor())
        logger.info("PreviewRenderer exported PDF to %s", path)

    # ----------------------------------------------------------- Pyvis

    def render_pyvis(self, output_html: str) -> None:
        """Render the graph to an interactive pyvis HTML file.

        Requires the optional ``pyvis`` package; raises ``ImportError`` if not
        installed.
        """
        try:
            from pyvis.network import Network  # lazy
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "pyvis is required for render_pyvis(). Install it with "
                "`pip install pyvis`."
            ) from exc
        s = self.settings
        net = Network(height="800px", width="100%",
                      bgcolor=s.background_color, font_color=s.font_color,
                      notebook=False, directed=self.graph.is_directed())
        # Build positions list for pyvis (it has its own layout, but we honour
        # the supplied positions if available).
        sizes = self._node_sizes()
        colors = self._node_colors()
        labels = self._node_labels()
        for n in self.graph.nodes():
            data = self.graph.nodes[n]
            label = labels.get(n) or data.get("label") or data.get("title") or str(n)
            net.add_node(str(n), label=str(label), size=float(sizes.get(n, 10)),
                         color=colors.get(n, "#1f77b4"))
        ewidths = self._edge_widths()
        ecolors = self._edge_colors()
        for u, v in self.graph.edges():
            edge_data = self.graph[u][v]
            label = str(edge_data.get("label", "")) if s.show_edge_labels else ""
            net.add_edge(str(u), str(v), label=label,
                         width=float(ewidths.get((u, v), 1.0)),
                         color=ecolors.get((u, v), s.edge_color))
        net.write_html(output_html, notebook=False)
        logger.info("PreviewRenderer wrote pyvis HTML to %s", output_html)

    # ----------------------------------------------------------- Plotly

    def render_plotly(self, output_html: Optional[str] = None, dim3: bool = False):
        """Render the graph to an interactive plotly Figure (2D or 3D).

        Args:
            output_html: If supplied, the figure is also written to this HTML
                file (plotly's ``write_html``).
            dim3: If ``True``, render a 3D scatter (z = node degree).

        Returns:
            A :class:`plotly.graph_objs.Figure`.
        """
        try:
            import plotly.graph_objects as go  # lazy
            import numpy as np  # lazy
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "plotly is required for render_plotly(). Install it with "
                "`pip install plotly`."
            ) from exc
        s = self.settings
        pos = self.positions()
        sizes = self._node_sizes()
        colors = self._node_colors()
        labels = self._node_labels()
        # Edge traces.
        edge_x: List[float] = []
        edge_y: List[float] = []
        edge_z: List[float] = []
        for u, v in self.graph.edges():
            if u not in pos or v not in pos:
                continue
            x1, y1 = pos[u]
            x2, y2 = pos[v]
            edge_x += [x1, x2, None]
            edge_y += [y1, y2, None]
            if dim3:
                edge_z += [0.0, 0.0, None]
        if dim3:
            edge_trace = go.Scatter3d(
                x=edge_x, y=edge_y, z=edge_z, mode="lines",
                line=dict(width=0.5, color=s.edge_color),
                opacity=s.edge_opacity, hoverinfo="none",
            )
        else:
            edge_trace = go.Scatter(
                x=edge_x, y=edge_y, mode="lines",
                line=dict(width=0.5, color=s.edge_color),
                opacity=s.edge_opacity, hoverinfo="none",
            )
        # Node traces.
        node_x = [pos[n][0] for n in self.graph.nodes() if n in pos]
        node_y = [pos[n][1] for n in self.graph.nodes() if n in pos]
        node_z = [float(self.graph.degree(n)) for n in self.graph.nodes() if n in pos]
        node_color = [colors.get(n, "#1f77b4") for n in self.graph.nodes() if n in pos]
        node_size = [max(5.0, float(np.sqrt(sizes.get(n, 10))))
                     for n in self.graph.nodes() if n in pos]
        node_text = [labels.get(n, str(n)) for n in self.graph.nodes() if n in pos]
        hover_text = [
            f"{n}<br>degree: {self.graph.degree(n)}"
            for n in self.graph.nodes() if n in pos
        ]
        if dim3:
            node_trace = go.Scatter3d(
                x=node_x, y=node_y, z=node_z, mode="markers+text",
                marker=dict(size=node_size, color=node_color,
                             line=dict(width=0.5, color="white")),
                text=node_text, hovertext=hover_text, hoverinfo="text",
                textfont=dict(size=s.font_size, color=s.font_color),
            )
        else:
            node_trace = go.Scatter(
                x=node_x, y=node_y, mode="markers+text",
                marker=dict(size=node_size, color=node_color,
                             line=dict(width=0.5, color="white")),
                text=node_text, hovertext=hover_text, hoverinfo="text",
                textfont=dict(size=s.font_size, color=s.font_color),
            )
        layout = go.Layout(
            showlegend=False,
            hovermode="closest",
            margin=dict(b=0, l=0, r=0, t=0),
            plot_bgcolor=s.background_color,
            paper_bgcolor=s.background_color,
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            scene=dict(
                xaxis=dict(showbackground=False, showticklabels=False, title=""),
                yaxis=dict(showbackground=False, showticklabels=False, title=""),
                zaxis=dict(showbackground=False, showticklabels=False, title=""),
            ) if dim3 else None,
        )
        fig = go.Figure(data=[edge_trace, node_trace], layout=layout)
        if output_html:
            fig.write_html(output_html)
            logger.info("PreviewRenderer wrote plotly HTML to %s", output_html)
        return fig

    # ----------------------------------------------------------- Cytoscape.js

    def render_cytoscape(self, output_html: Optional[str] = None) -> str:
        """Render the graph as a self-contained Cytoscape.js HTML file.

        Args:
            output_html: If supplied, also write the HTML to this file path.

        Returns:
            The HTML document as a string.
        """
        s = self.settings
        sizes = self._node_sizes()
        colors = self._node_colors()
        labels = self._node_labels()
        ewidths = self._edge_widths()
        ecolors = self._edge_colors()
        pos = self.positions()
        # Compute bounds for normalisation.
        xs = [p[0] for p in pos.values()] or [0.0]
        ys = [p[1] for p in pos.values()] or [0.0]
        x_span = (max(xs) - min(xs)) or 1.0
        y_span = (max(ys) - min(ys)) or 1.0

        nodes_js: List[str] = []
        for n in self.graph.nodes():
            x, y = pos.get(n, (0.0, 0.0))
            nx_ = (x - min(xs)) / x_span * 800 + 50
            ny_ = (y - min(ys)) / y_span * 600 + 50
            data = self.graph.nodes[n]
            label = labels.get(n) or data.get("label") or data.get("title") or str(n)
            label = html.escape(str(label))
            size = float(sizes.get(n, s.node_size_min))
            color = colors.get(n, "#1f77b4")
            nodes_js.append(
                "{ data: { id: " + json.dumps(str(n)) + ", "
                "label: " + json.dumps(label) + ", "
                "size: " + json.dumps(size) + ", "
                "color: " + json.dumps(color) + " }, "
                "position: { x: " + json.dumps(nx_) + ", y: " + json.dumps(ny_) + " } }"
            )
        edges_js: List[str] = []
        for i, (u, v) in enumerate(self.graph.edges()):
            w = float(ewidths.get((u, v), s.edge_width_min))
            c = ecolors.get((u, v), s.edge_color)
            edges_js.append(
                "{ data: { id: " + json.dumps(f"e{i}") + ", "
                "source: " + json.dumps(str(u)) + ", "
                "target: " + json.dumps(str(v)) + ", "
                "width: " + json.dumps(w) + ", "
                "color: " + json.dumps(c) + " } }"
            )
        legend_html = ""
        if s.show_legend and self.partition is not None:
            legend_items = self.partition.legend(palette=s.node_color_palette)
            legend_parts: List[str] = []
            legend_parts.append(
                "<div style='position:absolute;top:8px;right:8px;"
                "background:rgba(255,255,255,0.9);padding:8px;"
                "border-radius:4px;font-family:" + s.font_family + ";"
                "font-size:" + str(s.font_size) + "px;'>"
            )
            for lbl, col in legend_items:
                legend_parts.append(
                    "<div style='margin:2px;'>"
                    "<span style='display:inline-block;width:10px;height:10px;"
                    "background:" + col + ";margin-right:6px;'></span>"
                    "<span>" + html.escape(str(lbl)) + "</span></div>"
                )
            legend_parts.append("</div>")
            legend_html = "".join(legend_parts)
        style_obj = (
            "{'background-color':'data(color)',"
            "'width':20,'height':20,'label':'data(label)',"
            "'font-size':" + json.dumps(s.font_size) + ","
            "'color':" + json.dumps(s.font_color) + "}"
        )
        edge_style_obj = (
            "{'line-color':'data(color)',"
            "'width':'data(width)',"
            "'opacity':" + json.dumps(s.edge_opacity) + "}"
        )
        html_doc = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>html,body,#cy{margin:0;padding:0;width:100%;height:100vh;"
            "background:" + s.background_color + ";font-family:" + s.font_family + ";"
            "color:" + s.font_color + ";}</style>"
            "<script src='https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/"
            "cytoscape.min.js'></script>"
            "</head><body><div id='cy'></div>"
            "<script>var nodes=[" + ",".join(nodes_js) + "];"
            "var edges=[" + ",".join(edges_js) + "];"
            "var cy=cytoscape({container:document.getElementById('cy'),"
            "elements:nodes.concat(edges),style:["
            "{selector:'node',style:" + style_obj + "},"
            "{selector:'edge',style:" + edge_style_obj + "}"
            "],layout:{name:'preset'}});"
            "</script>"
            + legend_html + "</body></html>"
        )
        if output_html:
            with open(output_html, "w", encoding="utf-8") as fh:
                fh.write(html_doc)
            logger.info("PreviewRenderer wrote Cytoscape.js HTML to %s", output_html)
        return html_doc
