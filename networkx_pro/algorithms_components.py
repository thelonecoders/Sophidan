"""Component / substructure analysis — connectivity, k-cores, cliques, triangles.

The :class:`ComponentAnalysis` class wraps :mod:`networkx` component and
substructure routines:

- Connected / strongly / weakly components, condensation DAG.
- Articulation points (cut vertices) and bridges.
- Core decomposition: k-core, k-shell, k-crust, k-corona, k-truss,
  core-number, onion layers.
- Clique enumeration: all cliques (iter), max-weight clique, count
  per node, cliques containing a given node.
- Triangles, transitivity, average clustering coefficient.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union

__all__ = ["ComponentAnalysis"]

logger = logging.getLogger(__name__)


class ComponentAnalysis:
    """Stateless collection of component / substructure algorithms."""

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------
    @staticmethod
    def connected_components(g: Any) -> List[Set[Any]]:
        """Return connected components (undirected) as a list of node-sets."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        return [set(c) for c in nx.connected_components(g)]

    @staticmethod
    def strongly_connected_components(g: Any) -> List[Set[Any]]:
        """Return strongly connected components (DiGraph only) as a list of sets."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if not g.is_directed():
            logger.debug("strongly_connected_components called on undirected graph — "
                         "returning connected_components instead.")
            return [set(c) for c in nx.connected_components(g)]
        return [set(c) for c in nx.strongly_connected_components(g)]

    @staticmethod
    def weakly_connected_components(g: Any) -> List[Set[Any]]:
        """Return weakly connected components (DiGraph) as a list of sets."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if not g.is_directed():
            return [set(c) for c in nx.connected_components(g)]
        return [set(c) for c in nx.weakly_connected_components(g)]

    @staticmethod
    def condensation(g: Any) -> Any:
        """Return the condensation DAG of a directed graph.

        Each SCC of ``g`` collapses into a single node in the returned
        :class:`networkx.DiGraph`. Undirected graphs are converted first.

        Args:
            g: A networkx graph.

        Returns:
            A :class:`networkx.DiGraph` whose nodes are SCC indices and
            whose node attribute ``members`` holds the original node set.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return nx.DiGraph()
        if not g.is_directed():
            g = g.to_directed()
        try:
            return nx.condensation(g)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("condensation failed: %s", exc)
            return nx.DiGraph()

    # ------------------------------------------------------------------
    # Cut vertices and bridges
    # ------------------------------------------------------------------
    @staticmethod
    def articulation_points(g: Any) -> List[Any]:
        """Return articulation points (cut vertices).

        Args:
            g: Undirected graph.

        Returns:
            A list of nodes.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        try:
            return list(nx.articulation_points(g))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("articulation_points failed: %s", exc)
            return []

    @staticmethod
    def bridges(g: Any) -> List[Tuple[Any, Any]]:
        """Return bridge edges.

        Args:
            g: Undirected graph.

        Returns:
            A list of ``(u, v)`` tuples.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        try:
            return [tuple(e) for e in nx.bridges(g)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("bridges failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Core decomposition
    # ------------------------------------------------------------------
    @staticmethod
    def core_number(g: Any) -> Dict[Any, int]:
        """Return the core number for each node.

        Args:
            g: Undirected graph.

        Returns:
            ``{node: core_number}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if g.is_directed():
            g = g.to_undirected()
        try:
            return {n: int(c) for n, c in nx.core_number(g).items()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("core_number failed: %s", exc)
            return {}

    @staticmethod
    def k_core(
        g: Any,
        k: Optional[int] = None,
        core_number: Optional[Dict[Any, int]] = None,
    ) -> Any:
        """Return the k-core subgraph.

        Args:
            g: Undirected graph.
            k: Threshold (default: max core number).
            core_number: Pre-computed core-number dict.

        Returns:
            A :class:`networkx.Graph` subgraph view.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return nx.Graph()
        if g.is_directed():
            g = g.to_undirected()
        try:
            return nx.k_core(g, k=k, core_number=core_number)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("k_core failed: %s", exc)
            return nx.Graph()

    @staticmethod
    def k_shell(
        g: Any,
        k: Optional[int] = None,
        core_number: Optional[Dict[Any, int]] = None,
    ) -> Any:
        """Return the k-shell subgraph (nodes whose core number == k)."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return nx.Graph()
        if g.is_directed():
            g = g.to_undirected()
        try:
            return nx.k_shell(g, k=k, core_number=core_number)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("k_shell failed: %s", exc)
            return nx.Graph()

    @staticmethod
    def k_crust(
        g: Any,
        k: Optional[int] = None,
        core_number: Optional[Dict[Any, int]] = None,
    ) -> Any:
        """Return the k-crust subgraph (everything below the k-core)."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return nx.Graph()
        if g.is_directed():
            g = g.to_undirected()
        try:
            return nx.k_crust(g, k=k, core_number=core_number)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("k_crust failed: %s", exc)
            return nx.Graph()

    @staticmethod
    def k_corona(
        g: Any,
        k: int,
        core_number: Optional[Dict[Any, int]] = None,
    ) -> Any:
        """Return the k-corona subgraph.

        The k-corona is the subgraph of nodes in the k-core that have
        exactly ``k`` neighbours in the k-core.
        """
        import networkx as nx

        if g.number_of_nodes() == 0 or k is None:
            return nx.Graph()
        if g.is_directed():
            g = g.to_undirected()
        try:
            return nx.k_corona(g, k=k, core_number=core_number)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("k_corona failed: %s", exc)
            return nx.Graph()

    @staticmethod
    def k_truss(g: Any, k: int) -> Any:
        """Return the k-truss subgraph.

        A k-truss is the maximal subgraph in which every edge appears
        in at least ``k - 2`` triangles *within the subgraph*.

        Args:
            g: Undirected graph.
            k: Truss threshold.

        Returns:
            A :class:`networkx.Graph` subgraph.
        """
        import networkx as nx

        if g.number_of_nodes() == 0 or k is None:
            return nx.Graph()
        if g.is_directed():
            g = g.to_undirected()
        try:
            return nx.k_truss(g, k)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("k_truss failed: %s", exc)
            return nx.Graph()

    @staticmethod
    def onion_layers(g: Any) -> Dict[Any, int]:
        """Return the onion-layer index for each node.

        Onion layers are a generalisation of the k-core decomposition
        that exposes the order in which nodes are peeled off.

        Args:
            g: Undirected graph.

        Returns:
            ``{node: layer_index}`` (layer 1 = outermost shell).
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if g.is_directed():
            g = g.to_undirected()
        try:
            return {n: int(layer) for n, layer in nx.onion_layers(g).items()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("onion_layers failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Cliques
    # ------------------------------------------------------------------
    @staticmethod
    def number_of_cliques(g: Any, nodes: Optional[List[Any]] = None) -> Dict[Any, int]:
        """Return the number of maximal cliques each node belongs to.

        Args:
            g: Undirected graph.
            nodes: Restrict to this node list (default: all nodes).

        Returns:
            ``{node: count}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if g.is_directed():
            g = g.to_undirected()
        try:
            result = nx.number_of_cliques(g, nodes=nodes)
            return {n: int(c) for n, c in result.items()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("number_of_cliques failed: %s", exc)
            return {}

    @staticmethod
    def cliques_containing_node(g: Any, node: Any) -> List[List[Any]]:
        """Return all maximal cliques that contain ``node``.

        Note: ``networkx.algorithms.clique.cliques_containing_node`` was
        deprecated and removed in networkx 3.x; this is a faithful
        reimplementation using :func:`find_cliques`.

        Args:
            g: Undirected graph.
            node: A node in ``g``.

        Returns:
            A list of cliques (each clique is a list of nodes).
        """
        import networkx as nx

        if g.number_of_nodes() == 0 or node not in g:
            return []
        if g.is_directed():
            g = g.to_undirected()
        try:
            return [list(c) for c in nx.find_cliques(g) if node in c]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("cliques_containing_node failed: %s", exc)
            return []

    @staticmethod
    def all_cliques(g: Any, limit: Optional[int] = None) -> Iterator[List[Any]]:
        """Yield every maximal clique in ``g`` (up to ``limit``).

        Args:
            g: Undirected graph.
            limit: Maximum number of cliques to yield (``None`` = all).

        Yields:
            Lists of nodes forming each clique.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return
        if g.is_directed():
            g = g.to_undirected()
        try:
            for i, c in enumerate(nx.find_cliques(g)):
                yield list(c)
                if limit is not None and i + 1 >= limit:
                    return
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("all_cliques failed: %s", exc)

    @staticmethod
    def max_weight_clique(
        g: Any,
        weight: Optional[str] = None,
    ) -> Tuple[List[Any], int]:
        """Return the maximum-weight clique.

        Args:
            g: Undirected graph (no self-loops).
            weight: Node-attribute name carrying each node's weight
                (``None`` = unit weight).

        Returns:
            ``(clique, total_weight)``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return [], 0
        if g.is_directed():
            g = g.to_undirected()
        try:
            clique, total = nx.max_weight_clique(g, weight=weight)
            return list(clique), int(total)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("max_weight_clique failed: %s", exc)
            return [], 0

    # ------------------------------------------------------------------
    # Triangles / clustering
    # ------------------------------------------------------------------
    @staticmethod
    def triangles(g: Any, nodes: Optional[Union[Any, List[Any]]] = None) -> Dict[Any, int]:
        """Return the number of triangles each node participates in.

        Args:
            g: Undirected graph.
            nodes: Restrict to this node / list of nodes.

        Returns:
            ``{node: triangle_count}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if g.is_directed():
            g = g.to_undirected()
        try:
            return {n: int(c) for n, c in nx.triangles(g, nodes=nodes).items()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("triangles failed: %s", exc)
            return {}

    @staticmethod
    def transitivity(g: Any) -> float:
        """Return the transitivity (global clustering coefficient).

        Args:
            g: Undirected graph.

        Returns:
            A float in ``[0, 1]``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0 or g.number_of_edges() == 0:
            return 0.0
        if g.is_directed():
            g = g.to_undirected()
        try:
            return float(nx.transitivity(g))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("transitivity failed: %s", exc)
            return 0.0

    @staticmethod
    def average_clustering(
        g: Any,
        nodes: Optional[Union[Any, List[Any]]] = None,
        weight: Optional[str] = None,
        count_zeros: bool = True,
    ) -> float:
        """Return the average clustering coefficient.

        Args:
            g: Undirected graph.
            nodes: Restrict to this node / list of nodes.
            weight: Edge attribute used as weight.
            count_zeros: Include zero-clustering nodes in the average.

        Returns:
            A float in ``[0, 1]``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return 0.0
        if g.is_directed():
            g = g.to_undirected()
        try:
            return float(nx.average_clustering(
                g, nodes=nodes, weight=weight, count_zeros=count_zeros,
            ))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("average_clustering failed: %s", exc)
            return 0.0
