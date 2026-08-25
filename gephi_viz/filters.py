"""Gephi-style filter system.

Re-implements Gephi's filter panel as a chainable set of :class:`Filter`
subclasses. Each filter takes a ``networkx`` graph and returns a *filtered*
subgraph (always a copy — the input graph is never mutated).

Filter categories:

* **Range filters** — keep nodes/edges whose attribute falls in ``[min, max]``.
* **Topology filters** — restrict to the giant component, k-core, ego network,
  shortest paths, etc.
* **Partition filters** — keep nodes whose categorical attribute is in a value
  list.
* **Edge filters** — by edge type, or "inter" edges crossing partitions.
* **Dynamic filters** — by time range on temporal graphs.

Filters are composed via :class:`FilterChain`.

All filters share the :class:`Filter` interface::

    apply(graph) -> networkx.Graph
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "Filter",
    "DegreeRangeFilter",
    "WeightRangeFilter",
    "EdgeWeightRangeFilter",
    "PropertyValueRangeFilter",
    "GiantComponentFilter",
    "ConnectedComponentsFilter",
    "KCoreFilter",
    "EgoNetworkFilter",
    "ShortestPathFilter",
    "MutualEdgeFilter",
    "ParallelEdgeFilter",
    "PartitionFilter",
    "EqualPropertyFilter",
    "EdgeTypeFilter",
    "InterEdgesFilter",
    "TimeRangeFilter",
    "FilterChain",
]


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------
class Filter(ABC):
    """Abstract base class for all Gephi-style filters.

    Each subclass must implement :meth:`apply`, which returns a *new*
    ``networkx`` graph (the input is never mutated).
    """

    name: str = "Filter"

    @abstractmethod
    def apply(self, graph: Any) -> Any:
        """Return the filtered subgraph.

        Args:
            graph: Input ``networkx`` graph (mutated never).

        Returns:
            A new ``networkx.Graph`` / ``DiGraph`` / ``MultiGraph`` containing
            only the nodes / edges that survived the filter.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Range filters
# ---------------------------------------------------------------------------
class DegreeRangeFilter(Filter):
    """Keep nodes whose degree falls in ``[min_degree, max_degree]``.

    Args:
        min_degree: Minimum (inclusive) degree.
        max_degree: Maximum (inclusive) degree.
        mode: ``'in'``, ``'out'`` or ``'total'`` degree (relevant for
            directed graphs; ignored for undirected).
    """

    name = "Degree Range"

    def __init__(self, min_degree: int = 0, max_degree: int = 10**9,
                 mode: str = "total") -> None:
        if mode not in {"in", "out", "total"}:
            raise ValueError(f"mode must be one of in|out|total, got {mode!r}")
        self.min_degree = int(min_degree)
        self.max_degree = int(max_degree)
        self.mode = mode

    def apply(self, graph: Any) -> Any:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        if self.mode == "in" and graph.is_directed():
            degrees = dict(graph.in_degree())
        elif self.mode == "out" and graph.is_directed():
            degrees = dict(graph.out_degree())
        else:
            degrees = dict(graph.degree())
        keep = [n for n, d in degrees.items()
                if self.min_degree <= d <= self.max_degree]
        return graph.subgraph(keep).copy()


class WeightRangeFilter(Filter):
    """Alias of :class:`EdgeWeightRangeFilter` for backward compatibility."""

    name = "Weight Range"

    def __init__(self, min_weight: float = 0.0, max_weight: float = float("inf")) -> None:
        self.min_weight = float(min_weight)
        self.max_weight = float(max_weight)

    def apply(self, graph: Any) -> Any:
        return EdgeWeightRangeFilter(self.min_weight, self.max_weight).apply(graph)


class EdgeWeightRangeFilter(Filter):
    """Keep edges whose ``weight`` attribute is in ``[min, max]``.

    Edges without a ``weight`` attribute are treated as weight ``1.0``.

    Args:
        min_weight: Minimum (inclusive) edge weight.
        max_weight: Maximum (inclusive) edge weight.
    """

    name = "Edge Weight Range"

    def __init__(self, min_weight: float = 0.0, max_weight: float = float("inf")) -> None:
        self.min_weight = float(min_weight)
        self.max_weight = float(max_weight)

    def apply(self, graph: Any) -> Any:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_edges() == 0:
            return graph.copy() if graph is not None else graph
        out = graph.__class__()
        out.add_nodes_from(graph.nodes(data=True))
        for u, v, data in graph.edges(data=True):
            w = float(data.get("weight", 1.0))
            if self.min_weight <= w <= self.max_weight:
                out.add_edge(u, v, **data)
        return out


class PropertyValueRangeFilter(Filter):
    """Keep nodes whose numeric ``attribute`` lies in ``[min, max]``.

    Nodes missing the attribute are dropped.

    Args:
        attribute: Node attribute name.
        min_value: Minimum (inclusive).
        max_value: Maximum (inclusive).
    """

    name = "Property Value Range"

    def __init__(self, attribute: str, min_value: float = float("-inf"),
                 max_value: float = float("inf")) -> None:
        self.attribute = str(attribute)
        self.min_value = float(min_value)
        self.max_value = float(max_value)

    def apply(self, graph: Any) -> Any:
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        keep: List[Any] = []
        for node, data in graph.nodes(data=True):
            v = data.get(self.attribute)
            if v is None:
                continue
            try:
                v_f = float(v)
            except (TypeError, ValueError):
                continue
            if self.min_value <= v_f <= self.max_value:
                keep.append(node)
        return graph.subgraph(keep).copy()


# ---------------------------------------------------------------------------
# Topology filters
# ---------------------------------------------------------------------------
class GiantComponentFilter(Filter):
    """Keep only the largest connected component of the graph."""

    name = "Giant Component"

    def apply(self, graph: Any) -> Any:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        if graph.is_directed():
            comps = list(nx.weakly_connected_components(graph))
        else:
            comps = list(nx.connected_components(graph))
        if not comps:
            return graph.__class__()
        largest = max(comps, key=len)
        return graph.subgraph(largest).copy()


class ConnectedComponentsFilter(Filter):
    """Keep only connected components with at least ``min_size`` nodes.

    Args:
        min_size: Minimum component size (inclusive).
    """

    name = "Connected Components"

    def __init__(self, min_size: int = 10) -> None:
        self.min_size = int(min_size)

    def apply(self, graph: Any) -> Any:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        if graph.is_directed():
            comps = list(nx.weakly_connected_components(graph))
        else:
            comps = list(nx.connected_components(graph))
        keep: Set[Any] = set()
        for comp in comps:
            if len(comp) >= self.min_size:
                keep.update(comp)
        return graph.subgraph(keep).copy()


class KCoreFilter(Filter):
    """Keep only nodes in the ``k``-core of the graph.

    Args:
        k: Minimum core number.
    """

    name = "K-Core"

    def __init__(self, k: int = 2) -> None:
        self.k = int(k)

    def apply(self, graph: Any) -> Any:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        if graph.is_directed():
            graph = graph.to_undirected()
        try:
            core = nx.k_core(graph, k=self.k)
        except ValueError as exc:
            logger.warning("k-core failed (%s); returning empty graph", exc)
            return graph.__class__()
        return core.copy()


class EgoNetworkFilter(Filter):
    """Keep only the N-step neighbourhood of ``ego_node`` (inclusive).

    Args:
        ego_node: The center node.
        radius: Hop radius (1 = direct neighbours).
    """

    name = "Ego Network"

    def __init__(self, ego_node: Any, radius: int = 1) -> None:
        self.ego_node = ego_node
        self.radius = int(radius)

    def apply(self, graph: Any) -> Any:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        if self.ego_node not in graph:
            logger.warning("Ego node %r not in graph; returning empty graph.",
                           self.ego_node)
            return graph.__class__()
        ego = nx.ego_graph(graph, self.ego_node, radius=self.radius)
        return ego.copy()


class ShortestPathFilter(Filter):
    """Keep only nodes that lie on any shortest path from ``source`` to ``target``.

    Args:
        source: Source node id.
        target: Target node id.
    """

    name = "Shortest Path"

    def __init__(self, source: Any, target: Any) -> None:
        self.source = source
        self.target = target

    def apply(self, graph: Any) -> Any:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        if self.source not in graph or self.target not in graph:
            logger.warning("Shortest-path endpoints missing (%r, %r).",
                           self.source, self.target)
            return graph.__class__()
        try:
            # All shortest paths between source and target.
            paths = list(nx.all_shortest_paths(graph, source=self.source,
                                               target=self.target))
        except (nx.NetworkXNoPath, nx.NetworkXError) as exc:
            logger.warning("No shortest path between %r and %r (%s).",
                           self.source, self.target, exc)
            return graph.__class__()
        keep: Set[Any] = set()
        for p in paths:
            keep.update(p)
        return graph.subgraph(keep).copy()


class MutualEdgeFilter(Filter):
    """Keep only edges that exist in *both* directions (DiGraph → undirected).

    For undirected graphs the filter is the identity.
    """

    name = "Mutual Edges"

    def apply(self, graph: Any) -> Any:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        if not graph.is_directed():
            return graph.copy()
        out = nx.Graph()
        out.add_nodes_from(graph.nodes(data=True))
        seen = set()
        for u, v, data in graph.edges(data=True):
            if (v, u) in graph.edges and (u, v) not in seen and (v, u) not in seen:
                merged = dict(graph[v][u])
                merged.update(data)
                # Use max weight if both directions present.
                w1 = float(data.get("weight", 1.0))
                w2 = float(graph[v][u].get("weight", 1.0))
                merged["weight"] = max(w1, w2)
                out.add_edge(u, v, **merged)
                seen.add((u, v))
                seen.add((v, u))
        return out


class ParallelEdgeFilter(Filter):
    """Keep or remove parallel (multi) edges.

    Args:
        keep: ``True`` keeps only the first edge between any node pair,
            ``False`` removes parallel edges entirely (same effect for
            ``MultiGraph`` — collapsed to a single edge).
        aggregate: When ``keep=True`` and parallel edges exist, how to combine
            weights: ``'sum'`` (default), ``'max'``, ``'min'``, ``'mean'``.
    """

    name = "Parallel Edges"

    def __init__(self, keep: bool = True, aggregate: str = "sum") -> None:
        self.keep = bool(keep)
        if aggregate not in {"sum", "max", "min", "mean"}:
            raise ValueError(f"aggregate must be sum|max|min|mean, got {aggregate!r}")
        self.aggregate = aggregate

    def apply(self, graph: Any) -> Any:
        import networkx as nx  # lazy
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        if not graph.is_multigraph():
            return graph.copy()
        if graph.is_directed():
            out = nx.DiGraph()
        else:
            out = nx.Graph()
        out.add_nodes_from(graph.nodes(data=True))
        seen_pairs: Set[Tuple[Any, Any]] = set()
        for u, v, key, data in graph.edges(keys=True, data=True):
            pair = (u, v) if (u, v) not in seen_pairs and (v, u) not in seen_pairs else None
            if pair is None:
                # Already seen this pair — aggregate if requested.
                if self.keep and out.has_edge(u, v):
                    w1 = float(out[u][v].get("weight", 1.0))
                    w2 = float(data.get("weight", 1.0))
                    out[u][v]["weight"] = self._agg(w1, w2)
                continue
            seen_pairs.add((u, v))
            seen_pairs.add((v, u))
            out.add_edge(u, v, **data)
        return out

    def _agg(self, a: float, b: float) -> float:
        if self.aggregate == "sum":
            return a + b
        if self.aggregate == "max":
            return max(a, b)
        if self.aggregate == "min":
            return min(a, b)
        return (a + b) / 2.0  # mean


# ---------------------------------------------------------------------------
# Partition filters
# ---------------------------------------------------------------------------
class PartitionFilter(Filter):
    """Keep only nodes whose ``attribute`` value is in ``values``.

    Args:
        attribute: Node attribute name (e.g. ``'community'``).
        values: Allowed attribute values.
    """

    name = "Partition"

    def __init__(self, attribute: str, values: Sequence[Any]) -> None:
        self.attribute = str(attribute)
        self.values = set(values)

    def apply(self, graph: Any) -> Any:
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        keep = [n for n, data in graph.nodes(data=True)
                if data.get(self.attribute) in self.values]
        return graph.subgraph(keep).copy()


class EqualPropertyFilter(Filter):
    """Keep only nodes whose ``attribute`` equals ``value`` exactly.

    Args:
        attribute: Node attribute name.
        value: Required attribute value.
    """

    name = "Equal Property"

    def __init__(self, attribute: str, value: Any) -> None:
        self.attribute = str(attribute)
        self.value = value

    def apply(self, graph: Any) -> Any:
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        keep = [n for n, data in graph.nodes(data=True)
                if data.get(self.attribute) == self.value]
        return graph.subgraph(keep).copy()


# ---------------------------------------------------------------------------
# Edge filters
# ---------------------------------------------------------------------------
class EdgeTypeFilter(Filter):
    """Keep only edges whose ``type`` attribute is in ``types``.

    Args:
        types: Allowed edge type strings. Edges without a ``type`` attribute
            are dropped (Gephi's default behaviour).
    """

    name = "Edge Type"

    def __init__(self, types: Sequence[str]) -> None:
        self.types = set(types)

    def apply(self, graph: Any) -> Any:
        if graph is None or graph.number_of_edges() == 0:
            return graph.copy() if graph is not None else graph
        out = graph.__class__()
        out.add_nodes_from(graph.nodes(data=True))
        for u, v, data in graph.edges(data=True):
            if data.get("type") in self.types:
                out.add_edge(u, v, **data)
        return out


class InterEdgesFilter(Filter):
    """Keep only edges whose endpoints belong to *different* partitions.

    Args:
        attribute: Node attribute used as the partition key.
    """

    name = "Inter-Partition Edges"

    def __init__(self, attribute: str = "community") -> None:
        self.attribute = str(attribute)

    def apply(self, graph: Any) -> Any:
        if graph is None or graph.number_of_edges() == 0:
            return graph.copy() if graph is not None else graph
        out = graph.__class__()
        out.add_nodes_from(graph.nodes(data=True))
        for u, v, data in graph.edges(data=True):
            pu = graph.nodes[u].get(self.attribute)
            pv = graph.nodes[v].get(self.attribute)
            if pu != pv:
                out.add_edge(u, v, **data)
        return out


# ---------------------------------------------------------------------------
# Dynamic filters
# ---------------------------------------------------------------------------
class TimeRangeFilter(Filter):
    """Keep nodes / edges whose ``time_attr`` falls in ``[start, end]``.

    For nodes the filter checks ``graph.nodes[n][time_attr]``; for edges it
    also checks ``graph[u][v][time_attr]`` if present. Nodes outside the range
    are dropped; edges with an out-of-range timestamp (or an endpoint outside
    the range) are dropped.

    Args:
        start: Start of the time window (inclusive).
        end: End of the time window (inclusive).
        time_attr: Attribute name used as the time stamp (default ``'year'``).
    """

    name = "Time Range"

    def __init__(self, start: Any, end: Any, time_attr: str = "year") -> None:
        self.start = start
        self.end = end
        self.time_attr = str(time_attr)

    def _in_range(self, value: Any) -> bool:
        if value is None:
            return False
        try:
            v = float(value)
            return float(self.start) <= v <= float(self.end)
        except (TypeError, ValueError):
            # Fall back to lexicographic comparison for date strings.
            return str(self.start) <= str(value) <= str(self.end)

    def apply(self, graph: Any) -> Any:
        if graph is None or graph.number_of_nodes() == 0:
            return graph.copy() if graph is not None else graph
        keep_nodes = [n for n, data in graph.nodes(data=True)
                      if self._in_range(data.get(self.time_attr))]
        sub = graph.subgraph(keep_nodes).copy()
        # Further filter edges by their own time attr (if present).
        out = sub.__class__()
        out.add_nodes_from(sub.nodes(data=True))
        for u, v, data in sub.edges(data=True):
            t = data.get(self.time_attr)
            if t is None or self._in_range(t):
                out.add_edge(u, v, **data)
        return out


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------
class FilterChain:
    """Compose multiple filters into a single pipeline.

    Example::

        chain = FilterChain() \\
            .add_filter(DegreeRangeFilter(min_degree=2)) \\
            .add_filter(GiantComponentFilter())
        filtered = chain.apply(graph)
    """

    def __init__(self, filters: Optional[Sequence[Filter]] = None) -> None:
        self.filters: List[Filter] = list(filters) if filters else []

    def add_filter(self, f: Filter) -> "FilterChain":
        """Append a filter to the chain (returns ``self`` for chaining)."""
        if not isinstance(f, Filter):
            raise TypeError(f"Expected Filter, got {type(f).__name__}")
        self.filters.append(f)
        return self

    def apply(self, graph: Any) -> Any:
        """Apply each filter in order; the output of one feeds the next."""
        current = graph
        for f in self.filters:
            try:
                current = f.apply(current)
            except Exception as exc:  # noqa: BLE001
                logger.error("Filter %s failed: %s — skipping.", f.name, exc)
        return current

    def __len__(self) -> int:
        return len(self.filters)

    def __iter__(self):
        return iter(self.filters)
