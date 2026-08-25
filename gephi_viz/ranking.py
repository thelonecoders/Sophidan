"""Gephi-style ranking-based sizing and coloring.

A :class:`Ranking` is a continuous numerical mapping ``{node -> value}``.
Once constructed, the ranking can be projected to:

* node sizes (``to_node_sizes``) — linear or log scale, between ``min_size``
  and ``max_size``;
* node colors (``to_node_colors``) — via a matplotlib colormap;
* edge widths (``to_edge_widths``) — by the rank of the source/target's mean;
* edge colors (``to_edge_colors``) — same;
* node labels (``to_node_labels``) — keep only the top-N labels.

Rankings are constructed from either a node attribute
(:meth:`Ranking.from_node_attribute`) or a centrality computation
(:meth:`Ranking.from_centralities`).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = ["Ranking"]


# ---------------------------------------------------------------------------
# Supported colormaps — validated against matplotlib at call time.
# ---------------------------------------------------------------------------
_NODE_RANK_ATTRS = {
    "pagerank", "betweenness", "closeness", "eigenvector",
    "degree", "in_degree", "out_degree", "weighted_degree",
}


def _normalise(values: Dict[Any, float], scale: str = "linear",
               out_min: float = 0.0, out_max: float = 1.0) -> Dict[Any, float]:
    """Map ``values`` to ``[out_min, out_max]`` (linear or log)."""
    if not values:
        return {}
    raw_v = list(values.values())
    vmin = float(min(raw_v))
    vmax = float(max(raw_v))
    if vmax <= vmin:
        # Constant — return midpoint.
        mid = (out_min + out_max) / 2.0
        return {k: mid for k in values}
    out: Dict[Any, float] = {}
    if scale == "log":
        # Shift to strictly positive before taking log.
        shift = 0.0
        if vmin <= 0:
            shift = -vmin + 1e-6
        log_min = math.log(vmin + shift) if (vmin + shift) > 0 else 0.0
        log_max = math.log(vmax + shift)
        denom = (log_max - log_min) if log_max > log_min else 1.0
        for k, v in values.items():
            t = (math.log(v + shift) - log_min) / denom
            out[k] = out_min + t * (out_max - out_min)
    else:
        span = vmax - vmin
        for k, v in values.items():
            t = (v - vmin) / span
            out[k] = out_min + t * (out_max - out_min)
    return out


def _rgba_to_hex(rgba) -> str:
    """Convert an ``(r, g, b[, a])`` tuple in ``[0, 1]`` to ``#rrggbb``."""
    r, g, b = rgba[0], rgba[1], rgba[2]
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(r * 255)))),
        max(0, min(255, int(round(g * 255)))),
        max(0, min(255, int(round(b * 255)))),
    )


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
class Ranking:
    """A continuous ranking of graph nodes by some numeric attribute.

    Attributes:
        values: ``{node: float}`` mapping.
    """

    def __init__(self, values: Dict[Any, float]) -> None:
        self.values: Dict[Any, float] = {k: float(v) for k, v in values.items()}
        # Sort nodes by descending rank for convenience.
        self._sorted: Optional[List[Tuple[Any, float]]] = None

    # ----------------------------------------------------------- Constructors

    @classmethod
    def from_node_attribute(cls, graph: Any, attribute: str) -> "Ranking":
        """Build a ranking from a numeric node attribute.

        Nodes missing the attribute get rank 0.0. Non-numeric values are
        silently coerced via ``float()``; if that fails, they're treated as 0.

        Args:
            graph: Input graph.
            attribute: Node attribute name (e.g. ``'pagerank'``, ``'year'``).
        """
        values: Dict[Any, float] = {}
        for node, data in graph.nodes(data=True):
            v = data.get(attribute)
            if v is None:
                values[node] = 0.0
                continue
            try:
                values[node] = float(v)
            except (TypeError, ValueError):
                values[node] = 0.0
        return cls(values)

    @classmethod
    def from_centralities(cls, graph: Any,
                          centrality_fn: str = "pagerank") -> "Ranking":
        """Build a ranking from a centrality computation.

        Args:
            graph: Input graph.
            centrality_fn: One of ``'pagerank'``, ``'betweenness'``,
                ``'closeness'``, ``'eigenvector'``, ``'degree'``,
                ``'in_degree'``, ``'out_degree'``, ``'weighted_degree'``.
        """
        centrality_fn = centrality_fn.lower().strip()
        import networkx as nx  # lazy
        if graph.number_of_nodes() == 0:
            return cls({})
        try:
            if centrality_fn == "pagerank":
                vals = nx.pagerank(graph, max_iter=1000, tol=1e-6)
            elif centrality_fn == "betweenness":
                vals = nx.betweenness_centrality(graph, normalized=True)
            elif centrality_fn == "closeness":
                vals = nx.closeness_centrality(graph)
            elif centrality_fn == "eigenvector":
                vals = nx.eigenvector_centrality(graph, max_iter=1000, tol=1e-6)
            elif centrality_fn == "degree":
                if graph.is_directed():
                    vals = {n: float(d) for n, d in graph.in_degree()}
                else:
                    vals = {n: float(d) for n, d in graph.degree()}
            elif centrality_fn == "in_degree":
                vals = {n: float(d) for n, d in graph.in_degree()}
            elif centrality_fn == "out_degree":
                vals = {n: float(d) for n, d in graph.out_degree()}
            elif centrality_fn == "weighted_degree":
                vals = {n: float(d) for n, d in graph.degree(weight="weight")}
            else:
                raise ValueError(
                    f"Unknown centrality_fn: {centrality_fn!r}. "
                    f"Expected one of {sorted(_NODE_RANK_ATTRS)}."
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Centrality %s failed: %s — falling back to degree.",
                           centrality_fn, exc)
            vals = {n: float(d) for n, d in graph.degree()}
        return cls({n: float(v) for n, v in vals.items()})

    # ----------------------------------------------------------- Properties

    def __len__(self) -> int:
        return len(self.values)

    def top_n(self, n: int = 10) -> List[Tuple[Any, float]]:
        """Return the top-``n`` ``(node, value)`` pairs (descending)."""
        if self._sorted is None:
            self._sorted = sorted(self.values.items(),
                                  key=lambda kv: -kv[1])
        return self._sorted[:n]

    # ----------------------------------------------------------- Projections

    def to_node_sizes(self, graph: Any, min_size: float = 50.0,
                      max_size: float = 400.0,
                      scale: str = "linear") -> Dict[Any, float]:
        """Project the ranking to per-node sizes in ``[min_size, max_size]``.

        Args:
            graph: Input graph (used only for iteration order — values come
                from this ranking).
            min_size: Lower bound on the returned sizes.
            max_size: Upper bound on the returned sizes.
            scale: ``'linear'`` or ``'log'``.
        """
        if scale not in {"linear", "log"}:
            raise ValueError(f"scale must be 'linear' or 'log', got {scale!r}")
        # Only rank nodes that exist in the graph AND have a value.
        scoped = {n: self.values[n] for n in graph.nodes() if n in self.values}
        return _normalise(scoped, scale=scale, out_min=min_size, out_max=max_size)

    def to_node_colors(self, graph: Any, cmap: str = "viridis") -> Dict[Any, str]:
        """Project the ranking to per-node hex colours via a matplotlib colormap.

        Args:
            graph: Input graph.
            cmap: Any matplotlib colormap name (e.g. ``'viridis'``,
                ``'plasma'``, ``'RdYlBu'``, ``'coolwarm'``).
        """
        import matplotlib.pyplot as plt  # lazy
        try:
            cm = plt.get_cmap(cmap)
        except (ValueError, KeyError):
            logger.warning("Unknown cmap %r — falling back to 'viridis'.", cmap)
            cm = plt.get_cmap("viridis")
        scoped = {n: self.values[n] for n in graph.nodes() if n in self.values}
        normed = _normalise(scoped, scale="linear", out_min=0.0, out_max=1.0)
        return {n: _rgba_to_hex(cm(t)) for n, t in normed.items()}

    def to_edge_widths(self, graph: Any, min_width: float = 0.5,
                       max_width: float = 5.0) -> Dict[Tuple[Any, Any], float]:
        """Project the ranking to per-edge widths.

        An edge's width is proportional to the average rank of its endpoints.

        Args:
            graph: Input graph.
            min_width: Minimum edge width.
            max_width: Maximum edge width.
        """
        edge_vals: Dict[Tuple[Any, Any], float] = {}
        for u, v in graph.edges():
            vu = self.values.get(u, 0.0)
            vv = self.values.get(v, 0.0)
            edge_vals[(u, v)] = (vu + vv) / 2.0
        return _normalise(edge_vals, scale="linear",
                          out_min=min_width, out_max=max_width)

    def to_edge_colors(self, graph: Any, cmap: str = "viridis") -> Dict[Tuple[Any, Any], str]:
        """Project the ranking to per-edge hex colours via a matplotlib colormap."""
        import matplotlib.pyplot as plt  # lazy
        try:
            cm = plt.get_cmap(cmap)
        except (ValueError, KeyError):
            cm = plt.get_cmap("viridis")
        edge_vals: Dict[Tuple[Any, Any], float] = {}
        for u, v in graph.edges():
            vu = self.values.get(u, 0.0)
            vv = self.values.get(v, 0.0)
            edge_vals[(u, v)] = (vu + vv) / 2.0
        normed = _normalise(edge_vals, scale="linear", out_min=0.0, out_max=1.0)
        return {e: _rgba_to_hex(cm(t)) for e, t in normed.items()}

    def to_node_labels(self, graph: Any, top_n: int = 20) -> Dict[Any, str]:
        """Return labels for only the top-``n`` ranked nodes.

        The label text is the node's ``label`` or ``title`` attribute if
        present, otherwise the node id coerced to ``str``.

        Args:
            graph: Input graph.
            top_n: Number of top-ranked nodes to keep.
        """
        top = set(n for n, _ in self.top_n(top_n))
        out: Dict[Any, str] = {}
        for node in graph.nodes():
            if node not in top:
                continue
            data = graph.nodes[node]
            label = data.get("label") or data.get("title") or str(node)
            out[node] = str(label)
        return out
