"""Gephi-style "Statistics" panel.

Wraps networkx's algorithmic suite in a single :class:`NetworkStatistics`
class that exposes Gephi's common metrics (degree, density, modularity,
clustering, PageRank, HITS, betweenness, etc.) with consistent error
handling. :meth:`NetworkStatistics.compute_all` returns a structured
:class:`NetworkStatsReport` that can be serialised to a pandas DataFrame,
Markdown table, or plain dict.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

__all__ = ["NetworkStatistics", "NetworkStatsReport"]


def _safe_top_n(d: Optional[Dict[Any, float]], n: int = 10) -> List[Tuple[Any, float]]:
    """Return the top-``n`` ``(node, score)`` pairs from ``d`` (descending)."""
    if not d:
        return []
    items = sorted(d.items(), key=lambda kv: float(kv[1]), reverse=True)
    return [(k, float(v)) for k, v in items[:n]]


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------
@dataclass
class NetworkStatsReport:
    """Structured summary of a graph's Gephi-style statistics.

    Attributes:
        avg_degree: Average node degree.
        avg_weighted_degree: Average weighted degree.
        diameter: Longest shortest-path length (graph diameter).
        density: Edge density (edges / max possible).
        modularity: Louvain modularity score (0..1).
        avg_clustering: Average local clustering coefficient.
        avg_path_length: Average shortest-path length.
        num_components: Number of weakly connected components.
        num_strong_components: Number of strongly connected components (DiGraph only).
        total_nodes: Total node count.
        total_edges: Total edge count.
        top_10_authorities: Top HITS authority nodes.
        top_10_hubs: Top HITS hub nodes.
        top_10_pagerank: Top PageRank nodes.
        top_10_betweenness: Top betweenness-centrality nodes.
        top_10_closeness: Top closeness-centrality nodes.
    """

    avg_degree: float = 0.0
    avg_weighted_degree: float = 0.0
    diameter: int = 0
    density: float = 0.0
    modularity: float = 0.0
    avg_clustering: float = 0.0
    avg_path_length: float = 0.0
    num_components: int = 0
    num_strong_components: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    top_10_authorities: List[Tuple[Any, float]] = field(default_factory=list)
    top_10_hubs: List[Tuple[Any, float]] = field(default_factory=list)
    top_10_pagerank: List[Tuple[Any, float]] = field(default_factory=list)
    top_10_betweenness: List[Tuple[Any, float]] = field(default_factory=list)
    top_10_closeness: List[Tuple[Any, float]] = field(default_factory=list)

    # ------------------------------------------------------- Serialisers

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict (top-N lists become list-of-lists)."""
        d = asdict(self)
        for k in ("top_10_authorities", "top_10_hubs", "top_10_pagerank",
                  "top_10_betweenness", "top_10_closeness"):
            d[k] = [[str(node), float(score)] for node, score in d[k]]
        return d

    def to_dataframe(self):
        """Return a tidy pandas DataFrame of the scalar statistics.

        Top-N lists are NOT included (use :meth:`to_dict` for those).
        """
        import pandas as pd  # lazy
        scalars = {
            k: v for k, v in asdict(self).items()
            if not k.startswith("top_10")
        }
        return pd.DataFrame([scalars])

    def to_markdown(self) -> str:
        """Return a Markdown table of the scalar statistics.

        Top-N lists are rendered as additional sub-sections.
        """
        scalars = {
            k: v for k, v in asdict(self).items()
            if not k.startswith("top_10")
        }
        lines = ["| Metric | Value |", "|---|---|"]
        for k, v in scalars.items():
            if isinstance(v, float):
                lines.append(f"| {k} | {v:.4f} |")
            else:
                lines.append(f"| {k} | {v} |")
        # Top-N sections.
        for label, items in [
            ("Top 10 Authorities", self.top_10_authorities),
            ("Top 10 Hubs", self.top_10_hubs),
            ("Top 10 PageRank", self.top_10_pagerank),
            ("Top 10 Betweenness", self.top_10_betweenness),
            ("Top 10 Closeness", self.top_10_closeness),
        ]:
            if not items:
                continue
            lines.append(f"\n### {label}\n")
            lines.append("| Node | Score |")
            lines.append("|---|---|")
            for node, score in items:
                lines.append(f"| {node} | {score:.4f} |")
        return "\n".join(lines)

    def __str__(self) -> str:
        return (f"<NetworkStatsReport nodes={self.total_nodes} "
                f"edges={self.total_edges} density={self.density:.4f} "
                f"components={self.num_components} "
                f"avg_degree={self.avg_degree:.3f} "
                f"modularity={self.modularity:.4f}>")


# ---------------------------------------------------------------------------
# NetworkStatistics
# ---------------------------------------------------------------------------
class NetworkStatistics:
    """Gephi's "Statistics" panel as a single class.

    The class is stateless — every method takes the graph explicitly so a
    single instance can be reused on many graphs. All methods gracefully
    handle empty / disconnected / directed graphs (returning ``0`` / ``{}``
    when the metric is undefined).
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"{__name__}.{type(self).__name__}")

    # --------------------------------------------------------------- Basics

    def node_count(self, g: Any) -> int:
        """Return ``g.number_of_nodes()``."""
        return int(g.number_of_nodes()) if g is not None else 0

    def edge_count(self, g: Any) -> int:
        """Return ``g.number_of_edges()``."""
        return int(g.number_of_edges()) if g is not None else 0

    def avg_degree(self, g: Any) -> float:
        """Average node degree (total degree for directed graphs)."""
        if g is None or g.number_of_nodes() == 0:
            return 0.0
        total = sum(d for _, d in g.degree())
        return float(total) / float(g.number_of_nodes())

    def avg_weighted_degree(self, g: Any) -> float:
        """Average weighted node degree (sum of edge weights)."""
        if g is None or g.number_of_nodes() == 0:
            return 0.0
        total = 0.0
        for _, _, data in g.edges(data=True):
            try:
                total += float(data.get("weight", 1.0))
            except (TypeError, ValueError):
                total += 1.0
        return float(total) / float(g.number_of_nodes())

    def graph_density(self, g: Any) -> float:
        """Edge density (``edges / max_possible_edges``)."""
        if g is None or g.number_of_nodes() == 0:
            return 0.0
        try:
            return float(nx_density(g))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Density failed: %s", exc)
            return 0.0

    def network_diameter(self, g: Any) -> int:
        """Graph diameter (longest shortest path) on the largest component."""
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return 0
        try:
            if g.is_directed():
                # Diameter is only well-defined for strongly connected DiGraphs;
                # compute on the largest strongly connected component.
                comps = list(nx.strongly_connected_components(g))
            else:
                comps = list(nx.connected_components(g))
            if not comps:
                return 0
            largest = max(comps, key=len)
            if len(largest) < 2:
                return 0
            sub = g.subgraph(largest)
            return int(nx.diameter(sub))
        except (nx.NetworkXError, Exception) as exc:  # noqa: BLE001
            self.logger.warning("Diameter failed: %s", exc)
            return 0

    def avg_path_length(self, g: Any) -> float:
        """Average shortest-path length on the largest component."""
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return 0.0
        try:
            if g.is_directed():
                comps = list(nx.strongly_connected_components(g))
            else:
                comps = list(nx.connected_components(g))
            if not comps:
                return 0.0
            largest = max(comps, key=len)
            if len(largest) < 2:
                return 0.0
            sub = g.subgraph(largest)
            return float(nx.average_shortest_path_length(sub))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Avg path length failed: %s", exc)
            return 0.0

    # --------------------------------------------------------------- Topology

    def connected_components(self, g: Any) -> List[Set[Any]]:
        """Weakly connected components (undirected view of any graph)."""
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            return [set(c) for c in nx.weakly_connected_components(g)]
        return [set(c) for c in nx.connected_components(g)]

    def strongly_connected_components(self, g: Any) -> List[Set[Any]]:
        """Strongly connected components (DiGraph; empty for undirected)."""
        import networkx as nx  # lazy
        if g is None or not g.is_directed() or g.number_of_nodes() == 0:
            return []
        return [set(c) for c in nx.strongly_connected_components(g)]

    def clustering_coefficient(self, g: Any) -> float:
        """Average local clustering coefficient."""
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return 0.0
        if g.is_directed():
            g = g.to_undirected()
        try:
            return float(nx.average_clustering(g))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Clustering failed: %s", exc)
            return 0.0

    def avg_clustering_coefficient(self, g: Any) -> float:
        """Alias of :meth:`clustering_coefficient` (Gephi naming)."""
        return self.clustering_coefficient(g)

    # --------------------------------------------------------------- Centrality

    def pagerank(self, g: Any) -> Dict[Any, float]:
        """PageRank centrality per node."""
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return {}
        try:
            return {n: float(s) for n, s in nx.pagerank(g, max_iter=1000, tol=1e-6).items()}
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("PageRank failed: %s", exc)
            return {}

    def betweenness_centrality(self, g: Any) -> Dict[Any, float]:
        """Betweenness centrality per node (normalised)."""
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return {}
        try:
            return {n: float(s) for n, s in nx.betweenness_centrality(g, normalized=True).items()}
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Betweenness failed: %s", exc)
            return {}

    def closeness_centrality(self, g: Any) -> Dict[Any, float]:
        """Closeness centrality per node."""
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return {}
        try:
            return {n: float(s) for n, s in nx.closeness_centrality(g).items()}
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Closeness failed: %s", exc)
            return {}

    def eccentricity(self, g: Any) -> Dict[Any, float]:
        """Per-node eccentricity (max shortest-path length to any other node)."""
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return {}
        out: Dict[Any, float] = {}
        # Compute per-component so disconnected graphs don't raise.
        if g.is_directed():
            comps = list(nx.strongly_connected_components(g))
        else:
            comps = list(nx.connected_components(g))
        for comp in comps:
            if len(comp) < 2:
                continue
            sub = g.subgraph(comp)
            try:
                e = nx.eccentricity(sub)
                out.update({n: float(v) for n, v in e.items()})
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("eccentricity failed on component: %s", exc)
        return out

    def hits_authority(self, g: Any) -> Dict[Any, float]:
        """HITS authority scores per node."""
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return {}
        if not g.is_directed():
            g = g.to_directed()
        try:
            _, auth = nx.hits(g, max_iter=1000, tol=1e-6)
            return {n: float(s) for n, s in auth.items()}
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("HITS authority failed: %s", exc)
            return {}

    def hits_hub(self, g: Any) -> Dict[Any, float]:
        """HITS hub scores per node."""
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return {}
        if not g.is_directed():
            g = g.to_directed()
        try:
            hubs, _ = nx.hits(g, max_iter=1000, tol=1e-6)
            return {n: float(s) for n, s in hubs.items()}
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("HITS hub failed: %s", exc)
            return {}

    # --------------------------------------------------------------- Modularity

    def modularity(self, g: Any, communities: Optional[List[Set[Any]]] = None) -> float:
        """Compute the modularity of a partition.

        If ``communities`` is ``None``, Louvain is used to detect communities
        on the fly, and the resulting partition's modularity is returned.

        Args:
            g: Input graph.
            communities: Optional list of community sets.

        Returns:
            Modularity score in ``[-0.5, 1]`` (typically ``[0, 0.7]``).
        """
        import networkx as nx  # lazy
        if g is None or g.number_of_nodes() == 0:
            return 0.0
        if g.is_directed():
            g = g.to_undirected()
        if communities is None:
            try:
                from networkx.algorithms.community import louvain_communities
                communities = list(louvain_communities(g, seed=42))
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Louvain failed: %s", exc)
                return 0.0
        try:
            from networkx.algorithms.community import modularity as _mod
            return float(_mod(g, communities))
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Modularity failed: %s", exc)
            return 0.0

    # --------------------------------------------------------------- Aggregate

    def compute_all(self, g: Any) -> NetworkStatsReport:
        """Run every metric on ``g`` and return a structured report.

        Heavier metrics (betweenness, HITS) are skipped for graphs with more
        than 5,000 nodes to keep interactive performance reasonable.
        """
        if g is None or g.number_of_nodes() == 0:
            return NetworkStatsReport()
        n_nodes = g.number_of_nodes()
        # Scalar metrics — always computed.
        avg_deg = self.avg_degree(g)
        avg_wdeg = self.avg_weighted_degree(g)
        density = self.graph_density(g)
        avg_clust = self.clustering_coefficient(g)
        n_components = len(self.connected_components(g))
        n_strong = len(self.strongly_connected_components(g))
        # Diameter / path length — expensive on large graphs; cap at 5k nodes.
        if n_nodes <= 5000:
            diameter = self.network_diameter(g)
            avg_path = self.avg_path_length(g)
        else:
            diameter = 0
            avg_path = 0.0
            self.logger.info("Skipping diameter/avg_path for graph with %d nodes.",
                             n_nodes)
        # Modularity — always computed (uses louvain by default).
        mod = self.modularity(g)
        # Centrality top-N.
        pr = self.pagerank(g) if n_nodes <= 50000 else {}
        bt = self.betweenness_centrality(g) if n_nodes <= 5000 else {}
        cc = self.closeness_centrality(g) if n_nodes <= 50000 else {}
        auth = self.hits_authority(g) if n_nodes <= 5000 else {}
        hubs = self.hits_hub(g) if n_nodes <= 5000 else {}
        return NetworkStatsReport(
            avg_degree=avg_deg,
            avg_weighted_degree=avg_wdeg,
            diameter=diameter,
            density=density,
            modularity=mod,
            avg_clustering=avg_clust,
            avg_path_length=avg_path,
            num_components=n_components,
            num_strong_components=n_strong,
            total_nodes=int(n_nodes),
            total_edges=int(g.number_of_edges()),
            top_10_authorities=_safe_top_n(auth),
            top_10_hubs=_safe_top_n(hubs),
            top_10_pagerank=_safe_top_n(pr),
            top_10_betweenness=_safe_top_n(bt),
            top_10_closeness=_safe_top_n(cc),
        )


def nx_density(g: Any) -> float:
    """Thin wrapper around ``networkx.density`` to ease testing."""
    import networkx as nx  # lazy
    return float(nx.density(g))
