"""Shortest paths, network distances, and maximum-flow algorithms.

The :class:`PathsAndFlows` class wraps every relevant :mod:`networkx`
function for path enumeration, eccentricity / diameter / radius,
and max-flow / min-cut / disjoint-path algorithms with consistent
defensive behaviour:

- All path/distance methods that require a *connected* graph silently
  restrict to the largest connected (or weakly connected) component.
- Flow methods (:meth:`maximum_flow`, :meth:`minimum_cut`,
  :meth:`edmonds_karp`, :meth:`ford_fulkerson`) all accept the same
  ``capacity='capacity'`` keyword.
- :meth:`ford_fulkerson` is implemented manually in pure Python because
  the legacy ``nx.ford_fulkerson`` was deprecated in networkx 3.x.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

__all__ = ["PathsAndFlows"]

logger = logging.getLogger(__name__)


class PathsAndFlows:
    """Stateless collection of path / distance / flow algorithms."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _connected_view(g: Any) -> Any:
        """Return ``g`` restricted to its largest connected component."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return g
        if g.is_directed():
            comps = nx.weakly_connected_components(g)
            if not comps or all(len(c) == 1 for c in comps) and g.number_of_edges() == 0:
                return g
            largest = max(comps, key=len)
            return g.subgraph(largest).copy()
        else:
            if nx.is_connected(g):
                return g
            largest = max(nx.connected_components(g), key=len)
            return g.subgraph(largest).copy()

    # ------------------------------------------------------------------
    # Single-source / single-target shortest paths
    # ------------------------------------------------------------------
    @staticmethod
    def shortest_path(
        g: Any,
        source: Optional[Any] = None,
        target: Optional[Any] = None,
        weight: Optional[str] = None,
        method: str = "dijkstra",
    ) -> Union[List[Any], Dict[Any, List[Any]]]:
        """Return the shortest path (or all paths from ``source``).

        Args:
            g: A networkx graph.
            source: Source node (``None`` = all sources).
            target: Target node (``None`` = all targets).
            weight: Edge-attribute name used as cost (``None`` = hop count).
            method: ``'dijkstra'`` (default) or ``'bellman-ford'``.

        Returns:
            A list of nodes ``[source, …, target]`` if both endpoints
            are given; otherwise ``{target: path}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return [] if source is not None and target is not None else {}
        try:
            return nx.shortest_path(g, source=source, target=target, weight=weight, method=method)
        except nx.NetworkXNoPath:
            logger.debug("shortest_path: no path between %r and %r.", source, target)
            return []
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("shortest_path failed: %s", exc)
            return [] if source is not None and target is not None else {}

    @staticmethod
    def all_shortest_paths(
        g: Any,
        source: Any,
        target: Any,
        weight: Optional[str] = None,
        method: str = "dijkstra",
    ) -> List[List[Any]]:
        """Return *every* shortest path between ``source`` and ``target``.

        Args:
            g: A networkx graph.
            source: Source node.
            target: Target node.
            weight: Edge-attribute name.
            method: ``'dijkstra'`` or ``'bellman-ford'``.

        Returns:
            A list of paths (each path is a list of nodes).
        """
        import networkx as nx

        if g.number_of_nodes() == 0 or source not in g or target not in g:
            return []
        try:
            return [list(p) for p in nx.all_shortest_paths(
                g, source=source, target=target, weight=weight, method=method,
            )]
        except nx.NetworkXNoPath:
            logger.debug("all_shortest_paths: no path between %r and %r.", source, target)
            return []
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("all_shortest_paths failed: %s", exc)
            return []

    @staticmethod
    def shortest_path_length(
        g: Any,
        source: Optional[Any] = None,
        target: Optional[Any] = None,
        weight: Optional[str] = None,
    ) -> Union[int, Dict[Any, Union[int, Dict[Any, int]]]]:
        """Return shortest-path lengths.

        Args:
            g: A networkx graph.
            source: Source node (``None`` = all sources).
            target: Target node (``None`` = all targets).
            weight: Edge-attribute name.

        Returns:
            An int if both endpoints given, otherwise nested dict.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return 0 if source is not None and target is not None else {}
        try:
            length = nx.shortest_path_length(g, source=source, target=target, weight=weight)
            if isinstance(length, int):
                return int(length)
            # Convert defaultdict-like to plain dict (recursively).
            return dict(length) if source is not None and target is None else {
                k: dict(v) for k, v in length.items()
            }
        except nx.NetworkXNoPath:
            logger.debug("shortest_path_length: no path.")
            return 0 if source is not None and target is not None else {}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("shortest_path_length failed: %s", exc)
            return 0 if source is not None and target is not None else {}

    @staticmethod
    def average_shortest_path_length(
        g: Any,
        weight: Optional[str] = None,
        method: Optional[str] = None,
    ) -> float:
        """Return the average shortest-path length over all node pairs.

        Args:
            g: A networkx graph. Disconnected graphs use the largest
                connected (or weakly connected) component.
            weight: Edge-attribute name.
            method: ``'dijkstra'``, ``'bellman-ford'``, ``'floyd-warshall'``.

        Returns:
            A float (number of edges, or sum of weights if ``weight``
            given). ``0.0`` on error.
        """
        import networkx as nx

        if g.number_of_nodes() < 2:
            return 0.0
        sub = PathsAndFlows._connected_view(g)
        if sub.number_of_nodes() < 2:
            return 0.0
        try:
            return float(nx.average_shortest_path_length(sub, weight=weight, method=method))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("average_shortest_path_length failed: %s", exc)
            return 0.0

    # ------------------------------------------------------------------
    # Eccentricity / diameter / radius / center / periphery
    # ------------------------------------------------------------------
    @staticmethod
    def eccentricity(
        g: Any,
        v: Optional[Union[Any, List[Any]]] = None,
        sp: Optional[Dict[Any, List[Any]]] = None,
    ) -> Dict[Any, int]:
        """Return eccentricity (max shortest-path distance from each node).

        Args:
            g: A networkx graph. Disconnected → largest CC.
            v: Restrict to this node / list of nodes.
            sp: Pre-computed shortest-path dict.

        Returns:
            ``{node: eccentricity}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        sub = PathsAndFlows._connected_view(g)
        try:
            result = nx.eccentricity(sub, v=v, sp=sp)
            return {n: int(e) for n, e in result.items()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("eccentricity failed: %s", exc)
            return {}

    @staticmethod
    def diameter(g: Any) -> int:
        """Return the graph diameter (largest eccentricity).

        Disconnected graphs use the largest connected component.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return 0
        sub = PathsAndFlows._connected_view(g)
        if sub.number_of_nodes() < 2:
            return 0
        try:
            return int(nx.diameter(sub))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("diameter failed: %s", exc)
            return 0

    @staticmethod
    def radius(g: Any) -> int:
        """Return the graph radius (smallest eccentricity).

        Disconnected graphs use the largest connected component.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return 0
        sub = PathsAndFlows._connected_view(g)
        if sub.number_of_nodes() < 2:
            return 0
        try:
            return int(nx.radius(sub))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("radius failed: %s", exc)
            return 0

    @staticmethod
    def center(g: Any, e: Optional[Dict[Any, int]] = None) -> List[Any]:
        """Return the center of the graph (nodes with eccentricity == radius)."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        sub = PathsAndFlows._connected_view(g)
        try:
            return list(nx.center(sub, e=e))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("center failed: %s", exc)
            return []

    @staticmethod
    def periphery(g: Any, e: Optional[Dict[Any, int]] = None) -> List[Any]:
        """Return the periphery (nodes with eccentricity == diameter)."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        sub = PathsAndFlows._connected_view(g)
        try:
            return list(nx.periphery(sub, e=e))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("periphery failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # All-pairs
    # ------------------------------------------------------------------
    @staticmethod
    def all_pairs_shortest_path(
        g: Any,
        cutoff: Optional[int] = None,
    ) -> Dict[Any, Dict[Any, List[Any]]]:
        """Return all-pairs shortest paths.

        Args:
            g: A networkx graph.
            cutoff: Maximum path length to return.

        Returns:
            ``{source: {target: path}}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        try:
            return {s: dict(t_map) for s, t_map in nx.all_pairs_shortest_path(g, cutoff=cutoff)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("all_pairs_shortest_path failed: %s", exc)
            return {}

    @staticmethod
    def has_path(g: Any, source: Any, target: Any) -> bool:
        """Return ``True`` if a path exists from ``source`` to ``target``."""
        import networkx as nx

        if g.number_of_nodes() == 0 or source not in g or target not in g:
            return False
        try:
            return bool(nx.has_path(g, source, target))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("has_path failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Flow algorithms
    # ------------------------------------------------------------------
    @staticmethod
    def maximum_flow(
        g: Any,
        s: Any,
        t: Any,
        capacity: str = "capacity",
    ) -> Tuple[int, Dict[Any, Dict[Any, int]]]:
        """Return the maximum flow from ``s`` to ``t``.

        Args:
            g: A networkx graph (must have ``capacity`` edge attribute;
                missing capacities default to ∞).
            s: Source node.
            t: Sink node.
            capacity: Edge attribute name.

        Returns:
            ``(flow_value, flow_dict)``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0 or s not in g or t not in g:
            return 0, {}
        try:
            val, flow = nx.maximum_flow(g, s, t, capacity=capacity)
            return int(val), {u: dict(v) for u, v in flow.items()}
        except nx.NetworkXUnbounded:
            logger.warning("maximum_flow: unbounded (infinite capacities).")
            return 0, {}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("maximum_flow failed: %s", exc)
            return 0, {}

    @staticmethod
    def minimum_cut(
        g: Any,
        s: Any,
        t: Any,
        capacity: str = "capacity",
    ) -> Tuple[int, List[Set[Any]]]:
        """Return the minimum s-t cut.

        Args:
            g: A networkx graph.
            s: Source node.
            t: Sink node.
            capacity: Edge attribute name.

        Returns:
            ``(cut_value, [reachable, non_reachable])``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0 or s not in g or t not in g:
            return 0, [set(), set()]
        try:
            val, (reachable, non_reachable) = nx.minimum_cut(g, s, t, capacity=capacity)
            return int(val), [set(reachable), set(non_reachable)]
        except nx.NetworkXUnbounded:
            logger.warning("minimum_cut: unbounded (infinite capacities).")
            return 0, [set(), set()]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("minimum_cut failed: %s", exc)
            return 0, [set(), set()]

    @staticmethod
    def edge_disjoint_paths(
        g: Any,
        s: Any,
        t: Any,
        flow_func: Optional[Callable] = None,
    ) -> int:
        """Return the number of edge-disjoint paths from ``s`` to ``t``."""
        import networkx as nx

        if g.number_of_nodes() == 0 or s not in g or t not in g:
            return 0
        try:
            result = nx.edge_disjoint_paths(g, s, t, flow_func=flow_func)
            # networkx ≥ 3.x returns a generator; consume it.
            return int(len(list(result)))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("edge_disjoint_paths failed: %s", exc)
            return 0

    @staticmethod
    def node_disjoint_paths(
        g: Any,
        s: Any,
        t: Any,
        flow_func: Optional[Callable] = None,
    ) -> int:
        """Return the number of node-disjoint paths from ``s`` to ``t``."""
        import networkx as nx

        if g.number_of_nodes() == 0 or s not in g or t not in g:
            return 0
        try:
            result = nx.node_disjoint_paths(g, s, t, flow_func=flow_func)
            # networkx ≥ 3.x returns a generator; consume it.
            return int(len(list(result)))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("node_disjoint_paths failed: %s", exc)
            return 0

    @staticmethod
    def edmonds_karp(
        g: Any,
        s: Any,
        t: Any,
        capacity: str = "capacity",
    ) -> Tuple[int, Dict[Any, Dict[Any, int]]]:
        """Return the maximum s-t flow using Edmonds-Karp (BFS augmenting paths).

        Args:
            g: A networkx graph.
            s: Source node.
            t: Sink node.
            capacity: Edge attribute name.

        Returns:
            ``(flow_value, flow_dict)``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0 or s not in g or t not in g:
            return 0, {}
        try:
            from networkx.algorithms.flow import edmonds_karp

            val, flow = nx.maximum_flow(g, s, t, capacity=capacity, flow_func=edmonds_karp)
            return int(val), {u: dict(v) for u, v in flow.items()}
        except nx.NetworkXUnbounded:
            logger.warning("edmonds_karp: unbounded (infinite capacities).")
            return 0, {}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("edmonds_karp failed: %s", exc)
            return 0, {}

    @staticmethod
    def ford_fulkerson(
        g: Any,
        s: Any,
        t: Any,
        capacity: str = "capacity",
    ) -> Tuple[int, Dict[Any, Dict[Any, int]]]:
        """Return the maximum s-t flow using a pure-Python Ford-Fulkerson.

        ``networkx.ford_fulkerson`` was deprecated and removed in
        networkx 3.x; this is a faithful reimplementation using BFS
        augmenting paths (Edmonds-Karp is the asymptotically better
        variant — exposed separately via :meth:`edmonds_karp`).

        Args:
            g: A networkx graph. Edges use ``capacity`` (default 1 if
                missing) as flow capacity.
            s: Source node.
            t: Sink node.

        Returns:
            ``(flow_value, flow_dict)`` where ``flow_dict`` has shape
            ``{u: {v: flow}}``.
        """
        if g.number_of_nodes() == 0 or s not in g or t not in g:
            return 0, {}

        # Build a residual graph. For each undirected edge we add two
        # directed arcs with the same capacity.
        residual: Dict[Tuple[Any, Any], float] = {}
        adj: Dict[Any, set] = {n: set() for n in g.nodes()}
        for u, v, d in g.edges(data=True):
            cap = float(d.get(capacity, 1.0)) if d else 1.0
            residual[(u, v)] = residual.get((u, v), 0.0) + cap
            residual[(v, u)] = residual.get((v, u), 0.0)
            adj[u].add(v)
            adj[v].add(u)

        flow_value = 0.0
        while True:
            # BFS for an augmenting path.
            parent: Dict[Any, Any] = {s: None}
            q = deque([s])
            found = False
            while q:
                u = q.popleft()
                if u == t:
                    found = True
                    break
                for v in adj[u]:
                    if v not in parent and residual.get((u, v), 0.0) > 0:
                        parent[v] = u
                        q.append(v)
            if not found:
                break
            # Bottleneck along the path s -> ... -> t.
            path_flow = float("inf")
            v = t
            while parent[v] is not None:
                u = parent[v]
                path_flow = min(path_flow, residual[(u, v)])
                v = u
            # Update residual capacities.
            v = t
            while parent[v] is not None:
                u = parent[v]
                residual[(u, v)] -= path_flow
                residual[(v, u)] = residual.get((v, u), 0.0) + path_flow
                v = u
            flow_value += path_flow

        # Build the flow_dict in networkx-compatible shape: flow on each
        # original edge equals (original capacity) - (residual capacity).
        # The residual dict also contains backward arcs (v, u) added by
        # the algorithm — those are *not* part of the original graph and
        # are skipped.
        flow_dict: Dict[Any, Dict[Any, int]] = {n: {} for n in g.nodes()}
        for u, v, d in g.edges(data=True):
            cap = float(d.get(capacity, 1.0)) if d else 1.0
            used = cap - residual.get((u, v), 0.0)
            flow_dict[u][v] = max(0, int(round(used)))
        return int(round(flow_value)), flow_dict

    # ------------------------------------------------------------------
    # Enumeration / heuristic search
    # ------------------------------------------------------------------
    @staticmethod
    def all_simple_paths(
        g: Any,
        source: Any,
        target: Any,
        cutoff: Optional[int] = None,
    ) -> Iterator[List[Any]]:
        """Yield every simple path from ``source`` to ``target``.

        Args:
            g: A networkx graph.
            source: Source node.
            target: Target node.
            cutoff: Maximum path length.

        Yields:
            Lists of nodes (paths).
        """
        import networkx as nx

        if g.number_of_nodes() == 0 or source not in g or target not in g:
            return
        try:
            yield from nx.all_simple_paths(g, source=source, target=target, cutoff=cutoff)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("all_simple_paths failed: %s", exc)

    @staticmethod
    def astar_path(
        g: Any,
        source: Any,
        target: Any,
        heuristic: Optional[Callable[[Any, Any], float]] = None,
        weight: str = "weight",
    ) -> List[Any]:
        """Return the A* shortest path from ``source`` to ``target``.

        Args:
            g: A networkx graph.
            source: Source node.
            target: Target node.
            heuristic: Admissible heuristic ``h(node, target) -> float``
                (default: zero — i.e. Dijkstra).
            weight: Edge-attribute name used as cost.

        Returns:
            A list of nodes ``[source, …, target]``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0 or source not in g or target not in g:
            return []
        try:
            return list(nx.astar_path(g, source=source, target=target,
                                      heuristic=heuristic, weight=weight))
        except nx.NetworkXNoPath:
            logger.debug("astar_path: no path between %r and %r.", source, target)
            return []
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("astar_path failed: %s", exc)
            return []
