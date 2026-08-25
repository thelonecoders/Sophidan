"""Bipartite-graph analysis — projections, clustering, redundancy.

The :class:`BipartiteAnalysis` class wraps :mod:`networkx.bipartite`
with consistent behaviour:

- Every method takes a :class:`networkx.Graph` whose nodes have a
  ``bipartite`` attribute (``0`` or ``1``) — this is the canonical
  networkx convention.
- Projection methods take an explicit ``nodes`` argument: the node-set
  to project *onto*. The complementary set is inferred.
- :meth:`redundancy` requires ``bipartite.node_redundancy`` (built-in).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

__all__ = ["BipartiteAnalysis"]

logger = logging.getLogger(__name__)


class BipartiteAnalysis:
    """Stateless collection of bipartite-graph algorithms."""

    # ------------------------------------------------------------------
    # Structural queries
    # ------------------------------------------------------------------
    @staticmethod
    def is_bipartite(g: Any) -> bool:
        """Return ``True`` if ``g`` is bipartite (no odd cycle).

        Args:
            g: A networkx graph.

        Returns:
            ``True`` / ``False``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return True
        try:
            return bool(nx.is_bipartite(g))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("is_bipartite failed: %s", exc)
            return False

    @staticmethod
    def bipartite_sets(g: Any) -> Tuple[Set[Any], Set[Any]]:
        """Return the two node-sets of a bipartite graph.

        Args:
            g: A networkx graph (must already be bipartite with
                ``bipartite`` node attributes OR an unlabelled bipartite
                graph that networkx can colour).

        Returns:
            ``(set_a, set_b)`` — the two partitions.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return set(), set()
        try:
            top, bottom = nx.bipartite.sets(g)
            return set(top), set(bottom)
        except nx.AmbiguousSolution:
            logger.debug("bipartite_sets: ambiguous — falling back to color().")
            try:
                colors = nx.bipartite.color(g)
                top = {n for n, c in colors.items() if c == 0}
                bottom = {n for n, c in colors.items() if c == 1}
                return top, bottom
            except Exception as exc:
                logger.warning("bipartite_sets fallback failed: %s", exc)
                return set(), set()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("bipartite_sets failed: %s", exc)
            return set(), set()

    @staticmethod
    def bipartite_density(g: Any, nodes: List[Any]) -> float:
        """Return the bipartite density (edges / (|A| × |B|)).

        Args:
            g: A bipartite graph.
            nodes: One partition (the other is inferred).

        Returns:
            A float in ``[0, 1]``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return 0.0
        try:
            return float(nx.bipartite.density(g, nodes))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("bipartite_density failed: %s", exc)
            return 0.0

    @staticmethod
    def bipartite_degrees(
        g: Any,
        nodes: List[Any],
        reverse: bool = False,
    ) -> Tuple[Dict[Any, int], Dict[int, int]]:
        """Return degree dicts for both bipartite partitions.

        Args:
            g: A bipartite graph.
            nodes: One partition (the other is inferred).
            reverse: When ``True``, swap which partition is returned first.
                (NetworkX 3.x removed the ``reverse`` parameter from
                ``bipartite.degrees``; we honour the legacy API by
                post-swapping the tuple.)

        Returns:
            ``(deg_of_other_side, deg_of_given_nodes)`` — two dicts.
            Note: the order is *opposite-side-first* to match
            networkx's canonical return shape.
        """
        from networkx.algorithms import bipartite

        if g.number_of_nodes() == 0:
            return {}, {}
        try:
            deg_other, deg_given = bipartite.degrees(g, nodes=nodes)
            if reverse:
                return dict(deg_given), dict(deg_other)
            return dict(deg_other), dict(deg_given)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("bipartite_degrees failed: %s", exc)
            return {}, {}

    # ------------------------------------------------------------------
    # Projections
    # ------------------------------------------------------------------
    @staticmethod
    def projected_graph(
        g: Any,
        nodes: List[Any],
        multigraph: bool = False,
    ) -> Any:
        """Return the simple (or multigraph) projection of ``g`` onto ``nodes``.

        Args:
            g: A bipartite graph.
            nodes: The partition to keep (other partition is collapsed).
            multigraph: If ``True`` return a :class:`MultiGraph` with one
                parallel edge per shared neighbour.

        Returns:
            A :class:`networkx.Graph` (or :class:`MultiGraph`).
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return nx.MultiGraph() if multigraph else nx.Graph()
        try:
            return nx.bipartite.projected_graph(g, nodes, multigraph=multigraph)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("projected_graph failed: %s", exc)
            return nx.MultiGraph() if multigraph else nx.Graph()

    @staticmethod
    def weighted_projected_graph(
        g: Any,
        nodes: List[Any],
        ratio: bool = False,
    ) -> Any:
        """Return the weighted projection (edge weight = shared neighbours).

        Args:
            g: A bipartite graph.
            nodes: The partition to keep.
            ratio: If ``True``, weights are normalised by the maximum
                possible shared neighbours.

        Returns:
            A :class:`networkx.Graph` with edge attribute ``weight``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return nx.Graph()
        try:
            return nx.bipartite.weighted_projected_graph(g, nodes, ratio=ratio)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("weighted_projected_graph failed: %s", exc)
            return nx.Graph()

    @staticmethod
    def collaboration_weighted_projected_graph(
        g: Any,
        nodes: List[Any],
    ) -> Any:
        """Return Newman's collaboration-weighted projection.

        Each projected edge ``(u, v)`` has weight ``Σ 1 / (deg(t) - 1)``
        over all shared neighbours ``t``.

        Args:
            g: A bipartite graph.
            nodes: The partition to keep.

        Returns:
            A :class:`networkx.Graph` with edge attribute ``weight``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return nx.Graph()
        try:
            return nx.bipartite.collaboration_weighted_projected_graph(g, nodes)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("collaboration_weighted_projected_graph failed: %s", exc)
            return nx.Graph()

    @staticmethod
    def generic_weighted_projected_graph(
        g: Any,
        nodes: List[Any],
        weight_function: Optional[Callable] = None,
    ) -> Any:
        """Return a weighted projection using a user-supplied weight function.

        Args:
            g: A bipartite graph.
            nodes: The partition to keep.
            weight_function: ``f(g, u, v) -> float``. Defaults to
                the simple shared-neighbour count.

        Returns:
            A :class:`networkx.Graph` with edge attribute ``weight``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return nx.Graph()
        try:
            return nx.bipartite.generic_weighted_projected_graph(
                g, nodes, weight_function=weight_function,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("generic_weighted_projected_graph failed: %s", exc)
            return nx.Graph()

    # ------------------------------------------------------------------
    # Clustering & redundancy
    # ------------------------------------------------------------------
    @staticmethod
    def clustering(
        g: Any,
        nodes: Optional[Union[Any, List[Any]]] = None,
        mode: str = "dot",
    ) -> Dict[Any, float]:
        """Return local bipartite clustering coefficient.

        Args:
            g: A bipartite graph.
            nodes: Restrict to this node / list of nodes.
            mode: ``'dot'`` (default, Latapy et al. 2008), ``'min'``,
                or ``'max'``.

        Returns:
            ``{node: cc}``.
        """
        from networkx.algorithms import bipartite

        if g.number_of_nodes() == 0:
            return {}
        try:
            result = bipartite.clustering(g, nodes=nodes, mode=mode)
            return {n: float(c) for n, c in result.items()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("clustering failed: %s", exc)
            return {}

    @staticmethod
    def average_clustering(
        g: Any,
        nodes: Optional[Union[Any, List[Any]]] = None,
        mode: str = "dot",
    ) -> float:
        """Return the average bipartite clustering coefficient.

        Args:
            g: A bipartite graph.
            nodes: Restrict to this node / list of nodes.
            mode: ``'dot'`` (default), ``'min'``, or ``'max'``.

        Returns:
            A float in ``[0, 1]``.
        """
        from networkx.algorithms import bipartite

        if g.number_of_nodes() == 0:
            return 0.0
        try:
            return float(bipartite.average_clustering(g, nodes=nodes, mode=mode))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("average_clustering failed: %s", exc)
            return 0.0

    @staticmethod
    def redundancy(g: Any, nodes: List[Any]) -> Dict[Any, float]:
        """Return the per-node redundancy (Latapy et al. 2008).

        Redundancy measures the extent to which a node's neighbours are
        redundant given the rest of the node's neighbourhood — it equals
        1 - 1/deg(n) * sum over neighbours of (deg(n) - 1 - common_count).

        Args:
            g: A bipartite graph.
            nodes: The partition whose redundancy is computed.

        Returns:
            ``{node: redundancy}`` in ``[0, 1]``.
        """
        from networkx.algorithms import bipartite

        if g.number_of_nodes() == 0:
            return {}
        try:
            result = bipartite.node_redundancy(g, nodes=nodes)
            return {n: float(r) for n, r in result.items()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("redundancy failed: %s", exc)
            return {}


# (Callable already imported at top.)
