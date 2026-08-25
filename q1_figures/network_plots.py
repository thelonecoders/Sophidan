"""Publication-grade network / graph figures.

The :class:`Q1NetworkPlots` class produces matplotlib figures from
NetworkX graphs (or any object exposing ``nodes`` / ``edges``).
Heavy deps (networkx, numpy, scipy) are imported lazily.

Supported layouts / plot types:

* :meth:`network_figure` — general spring / circular / kamada-kawai /
  force-atlas-2 layout with optional partition / ranking colour.
* :meth:`bipartite_figure` — two-column bipartite layout.
* :meth:`circular_network` — circular layout with arc edges.
* :meth:`arc_diagram` — linear arc diagram.
* :meth:`heatmap_graph` — adjacency matrix heatmap + dendrograms.
* :meth:`sankey_diagram` — flow diagram (matplotlib.sankey).
* :meth:`chord_diagram` — circular chord diagram.
* :meth:`hive_plot` — three-axis hive plot.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .palettes import JournalPalettes

logger = logging.getLogger(__name__)


def _palette(name_or_list: Union[str, Sequence[str]]) -> List[str]:
    if isinstance(name_or_list, str):
        try:
            return JournalPalettes.get(name_or_list)
        except KeyError:
            return JournalPalettes.NATURE
    return list(name_or_list)


class Q1NetworkPlots:
    """Publication-grade network figures from NetworkX graphs."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _layout(graph, layout: str, **kwargs):
        import networkx as nx
        if layout == "spring":
            return nx.spring_layout(graph, **kwargs)
        if layout == "circular":
            return nx.circular_layout(graph, **kwargs)
        if layout == "kamada_kawai":
            return nx.kamada_kawai_layout(graph, **kwargs)
        if layout == "force_atlas_2":
            try:
                from fa2 import ForceAtlas2  # type: ignore
                fa = ForceAtlas2(verbose=False)
                pos = fa.forceatlas2_layout(
                    graph, iterations=kwargs.get("iterations", 50),
                    pos=kwargs.get("pos"),
                )
                return pos
            except Exception as exc:
                logger.debug(
                    "ForceAtlas2 unavailable (%s); falling back to spring_layout",
                    exc,
                )
                return nx.spring_layout(graph, **kwargs)
        logger.warning("Unknown layout %r — defaulting to spring", layout)
        return nx.spring_layout(graph, **kwargs)

    @staticmethod
    def _partition_to_colors(partition: Dict[Any, int], palette: List[str]):
        """Map a partition dict {node: community_id} → colour list."""
        if not partition:
            return {}
        max_comm = max(partition.values()) if partition else 0
        colors: Dict[Any, str] = {}
        for node, comm in partition.items():
            colors[node] = palette[int(comm) % len(palette)]
        return colors

    # ------------------------------------------------------------------
    # General network figure
    # ------------------------------------------------------------------
    @staticmethod
    def network_figure(
        graph,
        layout: str = "spring",
        partition: Optional[Dict[Any, int]] = None,
        ranking: Optional[Dict[Any, float]] = None,
        palette: Union[str, Sequence[str]] = "nature",
        figsize: Tuple[float, float] = (3.5, 3.5),
        dpi: int = 300,
        label_top_n: int = 10,
        node_size_range: Tuple[float, float] = (20, 200),
        edge_alpha: float = 0.3,
        show_legend: bool = True,
    ):
        """Render a NetworkX graph with publication styling.

        Args:
            graph: A NetworkX Graph (or any object exposing ``nodes``
                and ``edges``).
            layout: ``'spring'``, ``'circular'``, ``'kamada_kawai'``,
                or ``'force_atlas_2'`` (latter requires the optional
                ``fa2`` package, falls back to spring if missing).
            partition: Optional ``{node: community_id}`` dict; when
                supplied, nodes are coloured by community.
            ranking: Optional ``{node: float}`` dict; when supplied,
                node size is scaled by the ranking value.
            palette: Palette name or colour list.
            figsize: Figure size in inches.
            dpi: Figure DPI.
            label_top_n: Label only the top-N highest-degree nodes.
            node_size_range: ``(min, max)`` node size in points².
            edge_alpha: Edge transparency.
            show_legend: When ``True`` and ``partition`` is supplied,
                add a community legend.

        Returns:
            matplotlib Figure.
        """
        import matplotlib.pyplot as plt
        import networkx as nx
        colors = _palette(palette)
        pos = Q1NetworkPlots._layout(graph, layout)
        # Node sizes
        if ranking is not None:
            min_r, max_r = min(ranking.values()), max(ranking.values())
            span = max(max_r - min_r, 1e-12)
            sizes = [
                node_size_range[0] + (node_size_range[1] - node_size_range[0])
                * (ranking.get(n, min_r) - min_r) / span
                for n in graph.nodes()
            ]
        else:
            deg = dict(graph.degree())
            max_deg = max(deg.values()) if deg else 1
            sizes = [
                node_size_range[0] + (node_size_range[1] - node_size_range[0])
                * (deg.get(n, 0) / max(max_deg, 1))
                for n in graph.nodes()
            ]
        # Node colours
        if partition is not None:
            color_map = Q1NetworkPlots._partition_to_colors(partition, colors)
            node_colors = [color_map.get(n, colors[0]) for n in graph.nodes()]
        else:
            node_colors = [colors[0]] * len(graph.nodes())
        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True, dpi=dpi)
        # Draw edges
        nx.draw_networkx_edges(graph, pos, ax=ax, alpha=edge_alpha,
                              width=0.4, edge_color="#666666")
        # Draw nodes
        nx.draw_networkx_nodes(graph, pos, ax=ax, node_size=sizes,
                               node_color=node_colors, edgecolors="black",
                               linewidths=0.3)
        # Labels: only top-N by degree
        if label_top_n > 0:
            deg = dict(graph.degree())
            top = sorted(deg, key=lambda n: deg[n], reverse=True)[:label_top_n]
            labels = {n: str(n) for n in top}
            nx.draw_networkx_labels(graph, pos, labels=labels, ax=ax,
                                    font_size=6, font_color="black")
        ax.set_axis_off()
        if show_legend and partition is not None:
            handles = []
            from matplotlib.lines import Line2D
            for comm in sorted(set(partition.values())):
                handles.append(Line2D(
                    [0], [0], marker="o", color="w",
                    markerfacecolor=colors[int(comm) % len(colors)],
                    markeredgecolor="black", markersize=6,
                    label=f"Community {comm + 1}",
                ))
            ax.legend(handles=handles, loc="best", frameon=False, fontsize=7)
        return fig

    # ------------------------------------------------------------------
    # Bipartite
    # ------------------------------------------------------------------
    @staticmethod
    def bipartite_figure(
        graph,
        set_a_label: str = "Authors",
        set_b_label: str = "Papers",
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Bipartite layout — set A on the left, set B on the right."""
        import matplotlib.pyplot as plt
        import networkx as nx
        colors = _palette(palette)
        try:
            set_a, set_b = nx.bipartite.sets(graph)
        except Exception:
            # Fall back: assume 'bipartite' attribute on each node.
            set_a = {n for n, d in graph.nodes(data=True) if d.get("bipartite", 0) == 0}
            set_b = {n for n, d in graph.nodes(data=True) if d.get("bipartite", 0) == 1}
        pos: Dict[Any, Tuple[float, float]] = {}
        for i, n in enumerate(sorted(set_a)):
            pos[n] = (0.0, i / max(len(set_a), 1))
        for i, n in enumerate(sorted(set_b)):
            pos[n] = (1.0, i / max(len(set_b), 1))
        fig, ax = plt.subplots(figsize=(6, max(4, 0.2 * (len(set_a) + len(set_b)))),
                               constrained_layout=True, dpi=120)
        nx.draw_networkx_edges(graph, pos, ax=ax, alpha=0.3, width=0.3,
                               edge_color="#888888")
        nx.draw_networkx_nodes(graph, pos, ax=ax, nodelist=list(set_a),
                               node_color=colors[0], node_size=30,
                               edgecolors="black", linewidths=0.3)
        nx.draw_networkx_nodes(graph, pos, ax=ax, nodelist=list(set_b),
                               node_color=colors[1], node_size=30,
                               edgecolors="black", linewidths=0.3)
        nx.draw_networkx_labels(graph, pos, ax=ax, font_size=5)
        ax.text(0, -0.05, set_a_label, ha="center", va="top",
                fontsize=8, fontweight="bold", transform=ax.transAxes)
        ax.text(1, -0.05, set_b_label, ha="center", va="top",
                fontsize=8, fontweight="bold", transform=ax.transAxes)
        ax.set_axis_off()
        return fig

    # ------------------------------------------------------------------
    # Circular network + arc diagram
    # ------------------------------------------------------------------
    @staticmethod
    def circular_network(
        graph,
        partition: Optional[Dict[Any, int]] = None,
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Circular layout with arc edges (instead of straight lines)."""
        import matplotlib.pyplot as plt
        import networkx as nx
        import numpy as np
        colors = _palette(palette)
        nodes = list(graph.nodes())
        n = len(nodes)
        if n == 0:
            fig, ax = plt.subplots(constrained_layout=True, dpi=120)
            ax.set_axis_off()
            return fig
        # Position nodes on a unit circle
        theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
        pos = {node: (math.cos(t), math.sin(t)) for node, t in zip(nodes, theta)}
        fig, ax = plt.subplots(figsize=(5, 5), constrained_layout=True, dpi=120)
        # Draw arc edges (cubic Bezier through origin)
        for u, v in graph.edges():
            x1, y1 = pos[u]
            x2, y2 = pos[v]
            # Bezier control point at the origin
            t_arr = np.linspace(0, 1, 30)
            bezier_x = (1 - t_arr) ** 3 * x1 + 3 * (1 - t_arr) ** 2 * t_arr * 0 + (1 - t_arr) * t_arr ** 2 * 0 + t_arr ** 3 * x2
            bezier_y = (1 - t_arr) ** 3 * y1 + 3 * (1 - t_arr) ** 2 * t_arr * 0 + (1 - t_arr) * t_arr ** 2 * 0 + t_arr ** 3 * y2
            ax.plot(bezier_x, bezier_y, color="#888888", alpha=0.3, linewidth=0.4)
        if partition is not None:
            color_map = Q1NetworkPlots._partition_to_colors(partition, colors)
            node_colors = [color_map.get(n, colors[0]) for n in nodes]
        else:
            node_colors = [colors[0]] * n
        ax.scatter([p[0] for p in pos.values()],
                   [p[1] for p in pos.values()],
                   s=60, c=node_colors, edgecolors="black", linewidths=0.3,
                   zorder=5)
        for node, (x, y) in pos.items():
            ax.text(x * 1.15, y * 1.15, str(node), fontsize=5,
                    ha="center", va="center")
        ax.set_xlim(-1.4, 1.4)
        ax.set_ylim(-1.4, 1.4)
        ax.set_aspect("equal")
        ax.set_axis_off()
        return fig

    @staticmethod
    def arc_diagram(
        graph,
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Linear arc diagram — nodes on a horizontal line, arcs above."""
        import matplotlib.pyplot as plt
        import numpy as np
        colors = _palette(palette)
        nodes = list(graph.nodes())
        n = len(nodes)
        if n == 0:
            fig, ax = plt.subplots(constrained_layout=True, dpi=120)
            ax.set_axis_off()
            return fig
        pos = {node: (i, 0) for i, node in enumerate(nodes)}
        fig, ax = plt.subplots(figsize=(max(4, 0.3 * n), 3),
                                constrained_layout=True, dpi=120)
        # Draw arcs as semicircles above the line
        for u, v in graph.edges():
            x1, _ = pos[u]
            x2, _ = pos[v]
            if x1 > x2:
                x1, x2 = x2, x1
            r = (x2 - x1) / 2.0
            cx = (x1 + x2) / 2.0
            theta = np.linspace(0, np.pi, 50)
            ax.plot(cx + r * np.cos(theta), r * np.sin(theta),
                    color="#888888", alpha=0.4, linewidth=0.4)
        ax.scatter([p[0] for p in pos.values()],
                   [p[1] for p in pos.values()],
                   s=40, c=colors[0], edgecolors="black", linewidths=0.3,
                   zorder=5)
        for node, (x, _) in pos.items():
            ax.text(x, -0.2, str(node), fontsize=5,
                    ha="center", va="top", rotation=45)
        ax.set_ylim(-0.5, max(2, n * 0.1))
        ax.set_axis_off()
        return fig

    # ------------------------------------------------------------------
    # Heatmap with dendrograms
    # ------------------------------------------------------------------
    @staticmethod
    def heatmap_graph(
        adj_matrix,
        labels: Optional[Sequence[str]] = None,
        palette: str = "viridis",
        show_dendro: bool = True,
    ):
        """Adjacency matrix heatmap with hierarchical-clustering dendrograms."""
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib import gridspec
        from scipy.cluster.hierarchy import linkage, dendrogram
        from scipy.spatial.distance import squareform
        try:
            cmap = JournalPalettes.as_cmap(palette)
        except KeyError:
            cmap = JournalPalettes.as_cmap("viridis")
        mat = np.asarray(adj_matrix)
        n = mat.shape[0]
        if labels is None:
            labels = [str(i) for i in range(n)]
        # Hierarchical clustering
        if show_dendro:
            fig = plt.figure(figsize=(7, 7), constrained_layout=True, dpi=120)
            gs = gridspec.GridSpec(2, 2, width_ratios=[1, 5], height_ratios=[1, 5],
                                   figure=fig)
            ax_top = fig.add_subplot(gs[0, 1])
            ax_left = fig.add_subplot(gs[1, 0])
            ax_main = fig.add_subplot(gs[1, 1])
            # Convert distance matrix
            try:
                dist = squareform(mat, checks=False)
            except Exception:
                dist = mat[np.triu_indices(n, k=1)]
            Z = linkage(dist, method="average")
            dendro = dendrogram(Z, no_plot=True)
            order = dendro["leaves"]
            mat_ordered = mat[np.ix_(order, order)]
            labels_ordered = [labels[i] for i in order]
            # Top dendrogram
            dendrogram(Z, ax=ax_top, color_threshold=0)
            ax_top.set_axis_off()
            # Left dendrogram (rotated)
            dendrogram(Z, ax=ax_left, orientation="left",
                       color_threshold=0)
            ax_left.set_axis_off()
            # Heatmap
            im = ax_main.imshow(mat_ordered, aspect="equal", cmap=cmap)
            ax_main.set_xticks(range(n))
            ax_main.set_xticklabels(labels_ordered, fontsize=6, rotation=45,
                                     ha="right")
            ax_main.set_yticks(range(n))
            ax_main.set_yticklabels(labels_ordered, fontsize=6)
            fig.colorbar(im, ax=ax_main, shrink=0.6, label="Weight")
        else:
            fig, ax_main = plt.subplots(figsize=(6, 6), constrained_layout=True,
                                         dpi=120)
            im = ax_main.imshow(mat, aspect="equal", cmap=cmap)
            ax_main.set_xticks(range(n))
            ax_main.set_xticklabels(labels, fontsize=6, rotation=45, ha="right")
            ax_main.set_yticks(range(n))
            ax_main.set_yticklabels(labels, fontsize=6)
            fig.colorbar(im, ax=ax_main, shrink=0.6, label="Weight")
        return fig

    # ------------------------------------------------------------------
    # Sankey / chord / hive
    # ------------------------------------------------------------------
    @staticmethod
    def sankey_diagram(
        flows: Sequence[Tuple[str, str, float]],
        palette: Union[str, Sequence[str]] = "nature",
        figsize: Tuple[float, float] = (8, 5),
    ):
        """Flow diagram using :mod:`matplotlib.sankey`.

        Args:
            flows: List of ``(source, target, value)`` tuples.  Each
                unique source contributes an outflow and each unique
                target an inflow.
            palette: Palette name or list.
            figsize: Figure size.
        """
        import matplotlib.pyplot as plt
        from matplotlib.sankey import Sankey
        colors = _palette(palette)
        sources: Dict[str, float] = {}
        targets: Dict[str, float] = {}
        for src, dst, val in flows:
            sources[src] = sources.get(src, 0) + val
            targets[dst] = targets.get(dst, 0) + val
        fig = plt.figure(figsize=figsize, constrained_layout=True, dpi=120)
        ax = fig.add_subplot(1, 1, 1)
        total_in = sum(sources.values()) or 1.0
        # Build Sankey flows
        outflows = [-v / total_in for v in sources.values()]
        inflows = [v / total_in for v in targets.values()]
        sankey = Sankey(ax=ax, unit=None, scale=1.0, margin=0.1)
        try:
            sankey.add(
                flows=[1.0] + inflows + outflows,
                labels=["start"] + list(targets.keys()) + list(sources.keys()),
                orientations=[0] + [1] * len(inflows) + [-1] * len(outflows),
            )
            sankey.finish()
        except Exception as exc:
            logger.warning("Sankey rendering failed (%s); drawing fallback bars", exc)
            ax.bar(range(len(sources)), list(sources.values()),
                   color=colors[0], label="Outflow")
            ax.set_xticks(range(len(sources)))
            ax.set_xticklabels(list(sources.keys()), rotation=45, ha="right")
        return fig

    @staticmethod
    def chord_diagram(
        flows: Sequence[Tuple[str, str, float]],
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Circular chord diagram.

        Nodes are placed around a circle; flow weight is encoded as
        arc width and chord thickness.
        """
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.patches import FancyArrowPatch
        colors = _palette(palette)
        # Collect unique nodes
        node_set: Dict[str, int] = {}
        for src, dst, _ in flows:
            if src not in node_set:
                node_set[src] = len(node_set)
            if dst not in node_set:
                node_set[dst] = len(node_set)
        nodes = list(node_set.keys())
        n = len(nodes)
        if n == 0:
            fig, ax = plt.subplots(constrained_layout=True, dpi=120)
            ax.set_axis_off()
            return fig
        # Compute total flow per node for arc widths
        node_total: Dict[str, float] = {n_: 0.0 for n_ in nodes}
        for src, dst, val in flows:
            node_total[src] += val
            node_total[dst] += val
        total = sum(node_total.values()) or 1.0
        # Place nodes around a circle; arc width proportional to total flow.
        theta_start = 0.0
        node_thetas: Dict[str, Tuple[float, float]] = {}
        for node in nodes:
            arc = 2 * np.pi * node_total[node] / total
            node_thetas[node] = (theta_start, theta_start + arc)
            theta_start += arc + 0.02  # small gap
        # Compute midpoints for chord endpoints
        node_mid: Dict[str, float] = {
            n_: (t[0] + t[1]) / 2.0 for n_, t in node_thetas.items()
        }
        fig, ax = plt.subplots(figsize=(6, 6), constrained_layout=True, dpi=120)
        # Draw arcs
        for i, node in enumerate(nodes):
            t0, t1 = node_thetas[node]
            theta = np.linspace(t0, t1, 30)
            r_outer = 1.0
            r_inner = 0.95
            x_outer = r_outer * np.cos(theta)
            y_outer = r_outer * np.sin(theta)
            x_inner = r_inner * np.cos(theta[::-1])
            y_inner = r_inner * np.sin(theta[::-1])
            ax.fill(
                list(x_outer) + list(x_inner),
                list(y_outer) + list(y_inner),
                color=colors[i % len(colors)], alpha=0.7,
            )
            # Label outside
            mid_t = (t0 + t1) / 2.0
            ax.text(1.1 * math.cos(mid_t), 1.1 * math.sin(mid_t), node,
                    ha="center", va="center", fontsize=7)
        # Draw chords as quadratic bezier curves through the centre
        for src, dst, val in flows:
            if src == dst:
                continue
            t_src = node_mid[src]
            t_dst = node_mid[dst]
            x1, y1 = math.cos(t_src), math.sin(t_src)
            x2, y2 = math.cos(t_dst), math.sin(t_dst)
            # Quadratic bezier with control point at origin
            t_arr = np.linspace(0, 1, 50)
            bx = (1 - t_arr) ** 2 * x1 + 2 * (1 - t_arr) * t_arr * 0 + t_arr ** 2 * x2
            by = (1 - t_arr) ** 2 * y1 + 2 * (1 - t_arr) * t_arr * 0 + t_arr ** 2 * y2
            ax.plot(bx, by, color=colors[node_set[src] % len(colors)],
                    alpha=min(0.6, 0.2 + 0.6 * val / total), linewidth=0.6)
        ax.set_xlim(-1.4, 1.4)
        ax.set_ylim(-1.4, 1.4)
        ax.set_aspect("equal")
        ax.set_axis_off()
        return fig

    @staticmethod
    def hive_plot(
        nodes_by_axis: Dict[str, Sequence[Tuple[str, float]]],
        edges: Sequence[Tuple[str, str]],
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Hive plot — three radial axes with nodes positioned by rank.

        Args:
            nodes_by_axis: ``{axis_name: [(node_id, rank), ...]}`` —
                typically three axes (e.g. ``'source'``, ``'hub'``,
                ``'sink'``), each containing the nodes assigned to
                that axis with a ranking value (e.g. degree, betweenness).
            edges: List of ``(node_id, node_id)`` tuples; only edges
                connecting nodes on different axes are drawn.
            palette: Palette name or list.
        """
        import matplotlib.pyplot as plt
        import numpy as np
        colors = _palette(palette)
        axes = list(nodes_by_axis.keys())
        n_axes = len(axes)
        if n_axes == 0:
            fig, ax = plt.subplots(constrained_layout=True, dpi=120)
            ax.set_axis_off()
            return fig
        # Evenly space axes around the circle
        axis_angle = {a: 2 * np.pi * i / n_axes - np.pi / 2.0
                       for i, a in enumerate(axes)}
        # Compute node positions along each axis
        node_pos: Dict[str, Tuple[float, float]] = {}
        for ax_name, lst in nodes_by_axis.items():
            if not lst:
                continue
            ranks = [r for _, r in lst]
            min_r, max_r = min(ranks), max(ranks)
            span = max(max_r - min_r, 1e-12)
            for node_id, rank in lst:
                r = 0.2 + 0.8 * (rank - min_r) / span
                angle = axis_angle[ax_name]
                node_pos[node_id] = (r * math.cos(angle), r * math.sin(angle))
        fig, ax = plt.subplots(figsize=(5, 5), constrained_layout=True, dpi=120)
        # Draw axes
        for ax_name, angle in axis_angle.items():
            x = [0, math.cos(angle)]
            y = [0, math.sin(angle)]
            ax.plot(x, y, color="black", linewidth=0.6)
            ax.text(1.15 * math.cos(angle), 1.15 * math.sin(angle),
                    ax_name, ha="center", va="center", fontsize=8,
                    fontweight="bold")
        # Draw edges as bezier curves through near-centre
        for u, v in edges:
            if u not in node_pos or v not in node_pos:
                continue
            x1, y1 = node_pos[u]
            x2, y2 = node_pos[v]
            t_arr = np.linspace(0, 1, 30)
            # Bezier with control point at origin
            cx = 0.0
            cy = 0.0
            bx = (1 - t_arr) ** 2 * x1 + 2 * (1 - t_arr) * t_arr * cx + t_arr ** 2 * x2
            by = (1 - t_arr) ** 2 * y1 + 2 * (1 - t_arr) * t_arr * cy + t_arr ** 2 * y2
            ax.plot(bx, by, color=colors[0], alpha=0.2, linewidth=0.3)
        # Draw nodes
        for ax_name, lst in nodes_by_axis.items():
            i = axes.index(ax_name)
            for node_id, _ in lst:
                if node_id in node_pos:
                    x, y = node_pos[node_id]
                    ax.scatter([x], [y], s=30,
                               color=colors[i % len(colors)],
                               edgecolors="black", linewidths=0.3, zorder=5)
        ax.set_xlim(-1.3, 1.3)
        ax.set_ylim(-1.3, 1.3)
        ax.set_aspect("equal")
        ax.set_axis_off()
        return fig
