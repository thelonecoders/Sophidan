"""Gephi-style partition coloring.

A :class:`Partition` is a mapping ``{node -> group_id}``. Partitions can be
constructed from:

* a node attribute (:meth:`Partition.from_attribute`),
* a list of community sets (:meth:`Partition.from_communities`), or
* an on-the-fly clustering of the graph (:meth:`Partition.from_clustering`).

Once constructed, the partition exposes a palette of node colors
(:meth:`Partition.colors`), a legend (:meth:`Partition.legend`), helpers to
apply colors to matplotlib / Graphviz graphs, and the partition's modularity
score (:meth:`Partition.modularity`).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

__all__ = ["Partition"]


# ---------------------------------------------------------------------------
# Palettes — hex colour lists matching Gephi's named palettes (where applicable).
# ---------------------------------------------------------------------------
_PALETTES: Dict[str, List[str]] = {
    # Category10 (Plotly / D3): bright, distinguishable, good for ≤10 groups.
    "category10": [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ],
    # Set3 (ColorBrewer): pastel, good for up to 12 groups.
    "set3": [
        "#8dd3c7", "#ffffb3", "#bebada", "#fb8072", "#80b1d3",
        "#fdb462", "#b3de69", "#fccde5", "#d9d9d9", "#bc80bd",
        "#ccebc5", "#ffed6f",
    ],
    # Spectral diverging (10-step): good for ordinal partitions.
    "spectral": [
        "#9e0142", "#d53e4f", "#f46d43", "#fdae61", "#fee08b",
        "#e6f598", "#abdda4", "#66c2a5", "#3288bd", "#5e4fa2",
    ],
    # Viridis (10-step): perceptually uniform sequential.
    "viridis": [
        "#440154", "#482878", "#3e4a89", "#31688e", "#26828e",
        "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725",
    ],
}


def _get_palette(name: str, n: int) -> List[str]:
    """Return ``n`` colours from the named palette.

    If the palette has fewer than ``n`` colours, the list is cycled (with a
    hue rotation for the wraps to keep distinct entries visually distinct).

    Args:
        name: One of ``'category10'``, ``'set3'``, ``'spectral'``, ``'viridis'``.
        n: Required colour count.

    Returns:
        List of ``n`` hex colour strings.
    """
    name = name.lower().strip()
    if name not in _PALETTES:
        logger.warning("Unknown palette %r — falling back to 'category10'.", name)
        name = "category10"
    base = _PALETTES[name]
    if n <= len(base):
        return base[:n]
    # Cycle + rotate hue for overflow entries.
    out: List[str] = []
    for i in range(n):
        c = base[i % len(base)]
        if i < len(base):
            out.append(c)
        else:
            out.append(_rotate_hue(c, (i // len(base)) * 30))
    return out


def _rotate_hue(hex_color: str, degrees: float) -> str:
    """Rotate the hue of a hex colour by ``degrees`` (returns hex string)."""
    import colorsys  # stdlib
    h = h_l = s_l = v_l = 0.0
    try:
        h, l, s = _hex_to_hls(hex_color)
        h_l, s_l, v_l = h, s, l
    except Exception as exc:  # noqa: BLE001
        logger.debug("Hue rotation failed (%s); returning original", exc)
        return hex_color
    # HLS → HSV-ish hue rotation; use colorsys round-trip.
    r, g, b = colorsys.hls_to_rgb((h + degrees / 360.0) % 1.0, l, s)
    return "#{:02x}{:02x}{:02x}".format(
        int(r * 255), int(g * 255), int(b * 255))


def _hex_to_hls(hex_color: str) -> Tuple[float, float, float]:
    """Convert ``#rrggbb`` to HLS (hue, lightness, saturation) in ``[0, 1]``."""
    import colorsys  # stdlib
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Expected #rrggbb hex colour, got {hex_color!r}")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return colorsys.rgb_to_hls(r, g, b)


# ---------------------------------------------------------------------------
# Partition
# ---------------------------------------------------------------------------
class Partition:
    """A node→group mapping with palette support.

    Attributes:
        mapping: ``{node: group_id}`` dictionary.
        groups: Ordered list of distinct ``group_id`` values (insertion order).
    """

    def __init__(self, mapping: Dict[Any, Any]) -> None:
        self.mapping: Dict[Any, Any] = dict(mapping)
        # Distinct group ids in stable (insertion) order.
        seen: Dict[Any, None] = {}
        for g_id in mapping.values():
            if g_id not in seen:
                seen[g_id] = None
        self.groups: List[Any] = list(seen.keys())

    # ----------------------------------------------------------- Constructors

    @classmethod
    def from_attribute(cls, graph: Any, attribute: str) -> "Partition":
        """Partition by a node attribute (e.g. ``'community'``, ``'year'``).

        Nodes missing the attribute are placed in a ``None`` group.
        """
        mapping: Dict[Any, Any] = {}
        for node, data in graph.nodes(data=True):
            mapping[node] = data.get(attribute)
        return cls(mapping)

    @classmethod
    def from_communities(cls, graph: Any,
                         communities: Sequence[Set[Any]]) -> "Partition":
        """Partition from a list of community sets.

        Any node not appearing in any community is placed in a singleton
        group with id ``-1``.
        """
        mapping: Dict[Any, Any] = {}
        for cid, comm in enumerate(communities):
            for node in comm:
                mapping[node] = cid
        # Singletons for unassigned nodes.
        for node in graph.nodes():
            if node not in mapping:
                mapping[node] = -1
        return cls(mapping)

    @classmethod
    def from_clustering(cls, graph: Any,
                        method: str = "louvain",
                        k: Optional[int] = None) -> "Partition":
        """Partition by clustering the graph.

        Args:
            graph: Input graph.
            method: One of ``'louvain'``, ``'girvan_newman'``, ``'kmeans'``.
            k: Required for ``'kmeans'`` (number of clusters); ignored for
                the other methods.
        """
        method = method.lower().strip()
        if method == "louvain":
            return cls._from_louvain(graph)
        if method == "girvan_newman":
            return cls._from_girvan_newman(graph)
        if method == "kmeans":
            if k is None:
                raise ValueError("kmeans requires k (number of clusters).")
            return cls._from_kmeans(graph, int(k))
        raise ValueError(
            f"Unknown clustering method: {method!r}. "
            f"Expected one of louvain|girvan_newman|kmeans."
        )

    @classmethod
    def _from_louvain(cls, graph: Any) -> "Partition":
        import networkx as nx  # lazy
        try:
            from networkx.algorithms.community import louvain_communities
        except ImportError as exc:  # pragma: no cover - nx < 3.2
            raise RuntimeError(
                "louvain_communities is unavailable in this networkx version."
            ) from exc
        g = graph.to_undirected() if graph.is_directed() else graph
        comms = list(louvain_communities(g, seed=42))
        return cls.from_communities(graph, comms)

    @classmethod
    def _from_girvan_newman(cls, graph: Any) -> "Partition":
        from networkx.algorithms.community import girvan_newman  # lazy
        g = graph.to_undirected() if graph.is_directed() else graph
        try:
            comms = next(girvan_newman(g))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Girvan-Newman failed: %s", exc)
            comms = [set(g.nodes())]
        return cls.from_communities(graph, list(comms))

    @classmethod
    def _from_kmeans(cls, graph: Any, k: int) -> "Partition":
        import networkx as nx  # lazy
        import numpy as np  # lazy
        from sklearn.cluster import KMeans  # lazy
        from sklearn.preprocessing import StandardScaler  # lazy
        g = graph.to_undirected() if graph.is_directed() else graph
        # Build spectral embedding (top-k eigenvectors of the Laplacian).
        n = g.number_of_nodes()
        if n == 0:
            return cls({})
        nodes = list(g.nodes())
        try:
            lap = nx.laplacian_matrix(g, nodelist=nodes).astype(np.float64)
            # Compute the first k eigenvectors (smallest eigenvalues).
            from scipy.sparse.linalg import eigsh  # lazy
            vals, vecs = eigsh(lap, k=min(k, n - 1) if n > 1 else 1, which="SM")
            emb = StandardScaler().fit_transform(vecs)
            km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(emb)
            labels = km.labels_
        except Exception as exc:  # noqa: BLE001
            logger.warning("Spectral k-means failed (%s); using degree-based k-means.", exc)
            degs = np.array([g.degree(n) for n in nodes], dtype=np.float64).reshape(-1, 1)
            km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(degs)
            labels = km.labels_
        mapping = {node: int(labels[i]) for i, node in enumerate(nodes)}
        return cls(mapping)

    # ----------------------------------------------------------- Properties

    def __len__(self) -> int:
        return len(self.mapping)

    def num_groups(self) -> int:
        """Number of distinct groups."""
        return len(self.groups)

    def members(self, group_id: Any) -> List[Any]:
        """Return the nodes assigned to ``group_id``."""
        return [n for n, g in self.mapping.items() if g == group_id]

    def group_sizes(self) -> Dict[Any, int]:
        """Return ``{group_id: size}`` for every group."""
        out: Dict[Any, int] = {g: 0 for g in self.groups}
        for g_id in self.mapping.values():
            out[g_id] = out.get(g_id, 0) + 1
        return out

    # ----------------------------------------------------------- Colors

    def colors(self, palette: str = "category10") -> Dict[Any, str]:
        """Return ``{node: '#rrggbb'}`` for every node in the partition.

        Args:
            palette: One of ``'category10'``, ``'set3'``, ``'spectral'``,
                ``'viridis'``.
        """
        n = len(self.groups)
        cmap = _get_palette(palette, max(n, 1))
        gid_to_color = {g: cmap[i] for i, g in enumerate(self.groups)}
        return {node: gid_to_color[gid] for node, gid in self.mapping.items()}

    def legend(self, palette: str = "category10") -> List[Tuple[str, str]]:
        """Return ``[(label, color_hex), ...]`` per partition group (sorted by size desc)."""
        sizes = self.group_sizes()
        cmap = _get_palette(palette, max(len(self.groups), 1))
        gid_to_color = {g: cmap[i] for i, g in enumerate(self.groups)}
        items: List[Tuple[str, str]] = []
        for g_id in sorted(self.groups, key=lambda g: -sizes.get(g, 0)):
            label = str(g_id) if g_id is not None else "(none)"
            items.append((f"{label} ({sizes.get(g_id, 0)})", gid_to_color[g_id]))
        return items

    # ----------------------------------------------------------- Apply

    def apply_to_matplotlib(self, graph: Any, palette: str = "category10") -> List[str]:
        """Return a list of matplotlib-compatible colour strings (in ``graph.nodes()`` order)."""
        colors = self.colors(palette)
        return [colors.get(node, "#888888") for node in graph.nodes()]

    def apply_to_graphviz(self, graph: Any, palette: str = "category10") -> None:
        """Set the ``color`` attribute on every node of ``graph`` in place."""
        colors = self.colors(palette)
        for node in graph.nodes():
            graph.nodes[node]["color"] = colors.get(node, "#888888")
            graph.nodes[node]["fillcolor"] = colors.get(node, "#888888")
            graph.nodes[node]["style"] = "filled"

    def write_to_graph(self, graph: Any, attribute: str = "color",
                       palette: str = "category10") -> None:
        """Write ``{node: attribute = color_hex}`` into ``graph`` in place.

        Args:
            graph: The graph whose nodes will receive the colour attribute.
            attribute: Node attribute name to write the colour to.
            palette: Palette name.
        """
        colors = self.colors(palette)
        for node in graph.nodes():
            graph.nodes[node][attribute] = colors.get(node, "#888888")

    # ----------------------------------------------------------- Modularity

    def modularity(self, graph: Any) -> float:
        """Return the modularity of this partition on ``graph``."""
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return 0.0
        g = graph.to_undirected() if graph.is_directed() else graph
        # Group nodes by group id.
        groups: Dict[Any, Set[Any]] = {}
        for node, gid in self.mapping.items():
            if node in g:
                groups.setdefault(gid, set()).add(node)
        comm = list(groups.values())
        try:
            from networkx.algorithms.community import modularity as _mod
            return float(_mod(g, comm))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Modularity failed: %s", exc)
            return 0.0
