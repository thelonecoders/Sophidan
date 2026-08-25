"""Multigraph analysis — parallel-edge aware centrality and projection.

The :class:`MultiGraphAnalysis` class provides operations specific to
:class:`networkx.MultiGraph` and :class:`MultiDiGraph`:

- :meth:`multi_degree_centrality` — degree centrality summing across
  every parallel edge.
- :meth:`aggregate_to_simple` — collapse parallel edges into a single
  weighted edge using ``sum`` / ``max`` / ``mean`` / a custom callable.
- :meth:`parallel_edge_count` — count of edges between two nodes.
- :meth:`multi_pagerank` — PageRank that incorporates parallel-edge
  multiplicity as edge weight.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

__all__ = ["MultiGraphAnalysis"]

logger = logging.getLogger(__name__)


class MultiGraphAnalysis:
    """Stateless operations on :class:`networkx.MultiGraph` / :class:`MultiDiGraph`."""

    # ------------------------------------------------------------------
    # Degree
    # ------------------------------------------------------------------
    @staticmethod
    def multi_degree_centrality(g: Any) -> Dict[Any, float]:
        """Return degree centrality for a MultiGraph (counts parallel edges).

        For multigraphs, the degree counts each parallel edge separately.

        Args:
            g: A :class:`networkx.MultiGraph` or :class:`MultiDiGraph`.

        Returns:
            ``{node: degree / (n - 1)}``.
        """
        if g.number_of_nodes() == 0:
            return {}
        denom = max(1, g.number_of_nodes() - 1)
        return {n: g.degree(n) / denom for n in g.nodes()}

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------
    @staticmethod
    def aggregate_to_simple(
        g: Any,
        weight_fn: Any = "sum",
    ) -> Any:
        """Collapse parallel edges into a single weighted edge.

        Args:
            g: A :class:`networkx.MultiGraph` or :class:`MultiDiGraph`.
            weight_fn: One of ``'sum'`` (default), ``'max'``, ``'mean'``,
                ``'count'``, or a callable ``(list_of_weights) -> float``.

        Returns:
            A :class:`networkx.Graph` (or :class:`DiGraph`) whose edge
            attribute ``weight`` holds the aggregated parallel-edge weight.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return nx.DiGraph() if g.is_directed() else nx.Graph()

        # Resolve the aggregator.
        builtin = {
            "sum": sum,
            "max": max,
            "mean": lambda xs: float(sum(xs)) / len(xs) if xs else 0.0,
            "count": lambda xs: float(len(xs)),
        }
        if isinstance(weight_fn, str):
            if weight_fn not in builtin:
                raise ValueError(
                    f"Unknown weight_fn: {weight_fn!r}. "
                    f"Expected sum|max|mean|count or a callable."
                )
            aggregator: Callable = builtin[weight_fn]
        elif callable(weight_fn):
            aggregator = weight_fn
        else:
            raise TypeError(
                f"weight_fn must be a string or callable, got {type(weight_fn)}."
            )

        out = nx.DiGraph() if g.is_directed() else nx.Graph()
        out.add_nodes_from(g.nodes(data=True))
        # Iterate over each (u, v, key, data) — accumulate weights.
        edge_weights: Dict[tuple, list] = {}
        edge_data: Dict[tuple, dict] = {}
        for u, v, data in g.edges(data=True):
            w = float(data.get("weight", 1.0)) if data else 1.0
            key = (u, v)
            edge_weights.setdefault(key, []).append(w)
            # Preserve the first-encountered non-weight attrs for the merged edge.
            if key not in edge_data:
                edge_data[key] = {k: val for k, val in (data or {}).items() if k != "weight"}
        for (u, v), weights in edge_weights.items():
            agg = float(aggregator(weights))
            attrs = dict(edge_data[(u, v)])
            attrs["weight"] = agg
            attrs["parallel_edge_count"] = len(weights)
            out.add_edge(u, v, **attrs)
        return out

    # ------------------------------------------------------------------
    # Parallel-edge count
    # ------------------------------------------------------------------
    @staticmethod
    def parallel_edge_count(g: Any, u: Any, v: Any) -> int:
        """Return the number of parallel edges between ``u`` and ``v``.

        Args:
            g: A :class:`networkx.MultiGraph` / :class:`MultiDiGraph`.
            u, v: Nodes.

        Returns:
            An int (number of parallel edges).
        """
        if g.number_of_nodes() == 0:
            return 0
        # ``g.number_of_edges(u, v)`` returns the count on MultiGraphs.
        try:
            return int(g.number_of_edges(u, v))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("parallel_edge_count failed: %s", exc)
            return 0

    # ------------------------------------------------------------------
    # Multi-edge-aware PageRank
    # ------------------------------------------------------------------
    @staticmethod
    def multi_pagerank(
        g: Any,
        alpha: float = 0.85,
        personalization: Optional[Dict[Any, float]] = None,
        max_iter: int = 100,
        tol: float = 1e-06,
        nstart: Optional[Dict[Any, float]] = None,
        dangling: Optional[Dict[Any, float]] = None,
    ) -> Dict[Any, float]:
        """PageRank on a MultiGraph — counts each parallel edge separately.

        The function collapses parallel edges using a ``"count"`` weight
        (i.e. an edge that appears ``k`` times contributes ``k`` to its
        PageRank mass), then runs :func:`networkx.pagerank` on the
        resulting weighted simple graph.

        Args:
            g: A :class:`networkx.MultiGraph` (or :class:`MultiDiGraph`).
            alpha: Damping factor (default 0.85).
            personalization: Optional per-node bias.
            max_iter: Maximum iterations.
            tol: Convergence tolerance.
            nstart: Optional starting vector.
            dangling: Dangling-node redistribution.

        Returns:
            ``{node: pagerank_score}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        simple = MultiGraphAnalysis.aggregate_to_simple(g, weight_fn="count")
        try:
            return dict(nx.pagerank(
                simple, alpha=alpha, personalization=personalization,
                max_iter=max_iter, tol=tol, nstart=nstart,
                weight="weight", dangling=dangling,
            ))
        except nx.PowerIterationFailedConvergence as exc:
            logger.warning("multi_pagerank did not converge: %s", exc)
            n = simple.number_of_nodes()
            return {node: 1.0 / n for node in simple.nodes()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("multi_pagerank failed: %s", exc)
            return {}
