"""Pure-function library of advanced graph algorithms.

:class:`GraphAlgorithms` is a stateless utility class exposing static
methods for advanced graph-theoretic computations (k-core decomposition,
weighted betweenness, all-pairs shortest paths, modularity, assortativity,
reciprocity, density, diameter, triad census, link prediction, and
synthetic-graph generation for null-model comparison).

All methods are :func:`staticmethod` so they can be invoked without
instantiating the class, e.g. ``GraphAlgorithms.modularity(G, comms)``.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import networkx as nx

__all__ = ["GraphAlgorithms"]

logger = logging.getLogger(__name__)


class GraphAlgorithms:
    """Stateless collection of advanced graph algorithms.

    Every method is static and accepts a networkx graph as its first
    argument. None of the methods mutate the input graph.
    """

    # ------------------------------------------------------------------
    # Substructure
    # ------------------------------------------------------------------
    @staticmethod
    def k_core_decomposition(graph: nx.Graph, k: int) -> nx.Graph:
        """Return the k-core subgraph of ``graph``.

        The k-core is the maximal connected subgraph in which every node
        has degree ≥ ``k`` *within the subgraph*.

        Args:
            graph: Undirected :class:`networkx.Graph`. Directed graphs are
                converted to undirected first.
            k: The core number threshold.

        Returns:
            A new :class:`networkx.Graph` containing only nodes whose core
            number is ≥ ``k``. May be empty.
        """
        if graph.is_directed():
            graph = graph.to_undirected()
        if graph.number_of_nodes() == 0 or k <= 0:
            return graph.copy() if k <= 0 else nx.Graph()
        try:
            return nx.k_core(graph, k=k)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("k_core failed (k=%s): %s", k, exc)
            return nx.Graph()

    @staticmethod
    def betweenness_centrality_weighted(graph: nx.Graph) -> Dict[Any, float]:
        """Compute betweenness centrality using edge ``weight`` attribute.

        Args:
            graph: A networkx graph. ``weight`` attribute is required on
                edges; missing weights are treated as 1.

        Returns:
            ``{node: betweenness_score}`` dict.
        """
        if graph.number_of_nodes() == 0:
            return {}
        return dict(
            nx.betweenness_centrality(graph, weight="weight", normalized=True)
        )

    @staticmethod
    def all_pairs_shortest_path(
        graph: nx.Graph,
        cutoff: int = 5,
    ) -> Dict[Any, Dict[Any, List[Any]]]:
        """Compute shortest paths between all node pairs up to ``cutoff`` hops.

        Args:
            graph: A networkx graph.
            cutoff: Maximum path length (in number of edges) to return.

        Returns:
            ``{source: {target: [path]}}``. Pairs farther than ``cutoff``
            are omitted from the inner dict.
        """
        if graph.number_of_nodes() == 0:
            return {}
        return dict(nx.all_pairs_shortest_path(graph, cutoff=cutoff))

    # ------------------------------------------------------------------
    # Quality / structural metrics
    # ------------------------------------------------------------------
    @staticmethod
    def modularity(
        graph: nx.Graph,
        communities: Union[Dict[Any, int], List[set]],
    ) -> float:
        """Compute the modularity Q of a partition.

        Args:
            graph: Undirected :class:`networkx.Graph`. Directed graphs are
                converted to undirected first.
            communities: Either a ``{node: community_id}`` mapping or a
                list of sets of nodes (one set per community).

        Returns:
            The modularity score in ``[-0.5, 1]`` (typically).
        """
        if graph.is_directed():
            graph = graph.to_undirected()
        if graph.number_of_edges() == 0:
            return 0.0

        # Normalize input to a list-of-sets.
        if isinstance(communities, dict):
            from collections import defaultdict

            groups: Dict[int, set] = defaultdict(set)
            for node, cid in communities.items():
                groups[cid].add(node)
            comm_list: List[set] = list(groups.values())
        else:
            comm_list = [set(c) for c in communities]

        try:
            from networkx.algorithms.community.quality import modularity as _nx_modularity

            return float(_nx_modularity(graph, comm_list, weight="weight"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("modularity computation failed: %s", exc)
            return 0.0

    @staticmethod
    def assortativity(graph: nx.Graph, attribute: str) -> float:
        """Compute assortativity coefficient for a categorical node attribute.

        Args:
            graph: Undirected :class:`networkx.Graph`. Directed graphs are
                converted to undirected first.
            attribute: Name of the node attribute to compute assortativity
                against.

        Returns:
            The assortativity coefficient in ``[-1, 1]``. Returns ``0.0``
            when the attribute is missing on every node.
        """
        if graph.is_directed():
            graph = graph.to_undirected()
        if graph.number_of_edges() == 0:
            return 0.0
        has_attr = any(attribute in d for _, d in graph.nodes(data=True))
        if not has_attr:
            logger.debug("Attribute %r missing on every node — returning 0.", attribute)
            return 0.0
        try:
            return float(nx.attribute_assortativity_coefficient(graph, attribute))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("assortativity(%s) failed: %s", attribute, exc)
            return 0.0

    @staticmethod
    def reciprocity(graph: nx.Graph) -> float:
        """Fraction of directed edges that are reciprocated.

        Args:
            graph: A networkx graph. For undirected graphs, returns 1.0
                trivially (every undirected edge is by definition mutual).

        Returns:
            A float in ``[0, 1]``.
        """
        if not graph.is_directed():
            return 1.0 if graph.number_of_edges() > 0 else 0.0
        if graph.number_of_edges() == 0:
            return 0.0
        try:
            return float(nx.overall_reciprocity(graph))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("reciprocity failed: %s", exc)
            return 0.0

    @staticmethod
    def density(graph: nx.Graph) -> float:
        """Edge density of the graph.

        Args:
            graph: A networkx graph.

        Returns:
            ``2*m / (n*(n-1))`` for undirected graphs (or its directed
            variant). Returns ``0.0`` for graphs with fewer than 2 nodes.
        """
        if graph.number_of_nodes() < 2:
            return 0.0
        return float(nx.density(graph))

    @staticmethod
    def diameter(graph: nx.Graph) -> int:
        """Compute the graph diameter (longest shortest-path distance).

        For disconnected graphs, the *largest connected component*'s
        diameter is returned (since the global diameter is conventionally
        infinite).

        Args:
            graph: Undirected :class:`networkx.Graph`. Directed graphs use
                the largest *weakly* connected component.

        Returns:
            An integer (number of edges). ``0`` for empty / single-node
            graphs.
        """
        if graph.number_of_nodes() == 0:
            return 0
        if graph.number_of_nodes() == 1:
            return 0
        if graph.is_directed():
            comps = nx.weakly_connected_components(graph)
            sub = graph.subgraph(max(comps, key=len)).to_undirected()
        else:
            comps = nx.connected_components(graph)
            sub = graph.subgraph(max(comps, key=len))
        try:
            return int(nx.diameter(sub))
        except (nx.NetworkXError, Exception) as exc:  # pragma: no cover - defensive
            logger.warning("diameter failed: %s", exc)
            return 0

    @staticmethod
    def triad_census(graph: nx.Graph) -> Dict[str, int]:
        """Compute the triad census for a directed graph.

        Args:
            graph: A :class:`networkx.DiGraph`. Undirected graphs are
                converted to directed first (each undirected edge → two
                directed arcs).

        Returns:
            A dict mapping the 16 triad types (e.g. ``'003'``, ``'012'``,
            ``'300'``) to integer counts. Empty graph → all-zero counts.
        """
        if graph.number_of_nodes() < 3:
            # Return the canonical 16 keys with zero counts.
            return {name: 0 for name in _TRIAD_NAMES}
        if not graph.is_directed():
            graph = graph.to_directed()
        try:
            # networkx exposes this as ``triadic_census`` (not ``triad_census``).
            return {k: int(v) for k, v in nx.triadic_census(graph).items()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("triad_census failed: %s", exc)
            return {name: 0 for name in _TRIAD_NAMES}

    # ------------------------------------------------------------------
    # Link prediction
    # ------------------------------------------------------------------
    @staticmethod
    def link_prediction(
        graph: nx.Graph,
        method: str = "jaccard",
        top_n: Optional[int] = None,
    ) -> List[Tuple[Any, Any, float]]:
        """Predict missing links in ``graph``.

        For every pair of non-adjacent nodes with at least one common
        neighbor (when the method requires it — see below), a similarity
        score is computed and the top-scoring pairs are returned.

        Args:
            graph: Undirected :class:`networkx.Graph`. Directed graphs are
                converted to undirected first.
            method: ``'jaccard'`` (default), ``'adamic_adar'``,
                ``'preferential_attachment'``, or
                ``'resource_allocation'``.
            top_n: If set, return only the top ``n`` predictions. ``None``
                returns all candidate pairs.

        Returns:
            A list of ``(u, v, score)`` tuples sorted descending by score.
            Existing edges are excluded from predictions.

        Raises:
            ValueError: For unknown ``method``.
        """
        method = method.lower().strip()
        if graph.is_directed():
            graph = graph.to_undirected()
        if graph.number_of_nodes() < 2:
            return []
        # Generate candidate (non-edge) pairs as a *materialized* list.
        # NOTE: networkx 3.6 link-prediction functions exhibit a quirk where
        # passing a generator for ``ebunch`` yields an empty result; this is
        # worked around by eagerly converting to a list here.
        try:
            ebunch: List[Tuple[Any, Any]] = list(nx.non_edges(graph))
        except Exception:  # pragma: no cover - defensive
            ebunch = [
                (u, v)
                for u in graph
                for v in graph
                if u < v and not graph.has_edge(u, v)
            ]

        predictor_map = {
            "jaccard": nx.jaccard_coefficient,
            "adamic_adar": nx.adamic_adar_index,
            "preferential_attachment": nx.preferential_attachment,
            "resource_allocation": nx.resource_allocation_index,
        }
        if method not in predictor_map:
            raise ValueError(
                f"Unknown link prediction method: {method!r}. "
                f"Expected jaccard|adamic_adar|preferential_attachment|resource_allocation."
            )
        try:
            preds = list(predictor_map[method](graph, ebunch))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("link_prediction(%s) failed: %s", method, exc)
            return []
        # Filter zero-score predictions (irrelevant).
        preds = [(u, v, float(s)) for u, v, s in preds if s > 0]
        preds.sort(key=lambda x: -x[2])
        if top_n is not None:
            preds = preds[:top_n]
        return preds

    # ------------------------------------------------------------------
    # Synthetic graphs (null models)
    # ------------------------------------------------------------------
    @staticmethod
    def generate_synthetic(
        network_type: str = "small_world",
        n: int = 100,
        **kwargs: Any,
    ) -> nx.Graph:
        """Generate a synthetic graph as a null model.

        Useful for comparing empirical metrics (clustering, path length,
        degree distribution) against a known baseline.

        Args:
            network_type: ``'small_world'`` (Watts-Strogatz), ``'scale_free'``
                (Barabási-Albert), or ``'random'`` (Erdős-Rényi).
            n: Number of nodes.
            **kwargs: Network-type-specific parameters:

                - ``small_world``: ``k`` (neighbors per node, default 4),
                  ``p`` (rewiring probability, default 0.1), ``seed``.
                - ``scale_free``: ``m`` (edges per new node, default 2),
                  ``seed``.
                - ``random``: ``p`` (edge probability, default 0.05),
                  ``seed``.

        Returns:
            A freshly-generated :class:`networkx.Graph`.

        Raises:
            ValueError: For unknown ``network_type``.
        """
        network_type = network_type.lower().strip()
        seed = kwargs.get("seed", 42)
        if network_type == "small_world":
            k = int(kwargs.get("k", 4))
            p = float(kwargs.get("p", 0.1))
            k = max(2, min(k, n - 1))
            return nx.watts_strogatz_graph(n, k, p, seed=seed)
        if network_type == "scale_free":
            m = int(kwargs.get("m", 2))
            m = max(1, min(m, n - 1))
            return nx.barabasi_albert_graph(n, m, seed=seed)
        if network_type == "random":
            p = float(kwargs.get("p", 0.05))
            return nx.gnp_random_graph(n, p, seed=seed)
        raise ValueError(
            f"Unknown network_type: {network_type!r}. "
            f"Expected small_world|scale_free|random."
        )


# The 16 canonical triad census type codes (Mangan & Albright 1978).
_TRIAD_NAMES: Tuple[str, ...] = (
    "003",
    "012",
    "102",
    "021D",
    "021U",
    "021C",
    "111D",
    "111U",
    "030T",
    "030C",
    "201",
    "120D",
    "120U",
    "120C",
    "210",
    "300",
)
