"""Graph isomorphism — VF2, motif counting, and graph census.

The :class:`Isomorphism` class wraps :mod:`networkx.algorithms.isomorphism`
plus a small amount of additional functionality (graph census, motif
enumeration) not directly provided by networkx.

Notable points:

- :meth:`is_isomorphic` accepts optional ``node_match`` / ``edge_match``
  callables for labelled isomorphism.
- :meth:`could_be_isomorphic` and :meth:`faster_could_be_isomorphic`
  expose the (very fast) degree-sequence pre-checks that networkx
  provides; both are necessary-but-not-sufficient conditions.
- :meth:`is_isomorphic_to` is an alias of :meth:`is_isomorphic`.
- :meth:`vf2_graph_isomorphism` explicitly invokes the VF2 matcher.
- :meth:`graph_census` returns the frequency histogram of every
  distinct induced subgraph shape up to size ``n`` (default 3).
- :meth:`find_motifs` returns the list of distinct subgraph patterns.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from itertools import combinations
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = ["Isomorphism"]

logger = logging.getLogger(__name__)


class Isomorphism:
    """Stateless collection of graph-isomorphism algorithms."""

    # ------------------------------------------------------------------
    # Direct isomorphism tests
    # ------------------------------------------------------------------
    @staticmethod
    def is_isomorphic(
        g1: Any,
        g2: Any,
        node_match: Optional[Callable] = None,
        edge_match: Optional[Callable] = None,
    ) -> bool:
        """Return ``True`` if ``g1`` and ``g2`` are isomorphic.

        Args:
            g1, g2: Networkx graphs (both directed or both undirected).
            node_match: Optional callable for labelled node matching.
            edge_match: Optional callable for labelled edge matching.

        Returns:
            ``True`` / ``False``.
        """
        import networkx as nx

        try:
            return bool(nx.is_isomorphic(g1, g2, node_match=node_match, edge_match=edge_match))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("is_isomorphic failed: %s", exc)
            return False

    @staticmethod
    def could_be_isomorphic(g1: Any, g2: Any) -> bool:
        """Fast necessary-condition check (degree sequence + order + size).

        Returns ``False`` quickly if the two graphs cannot be isomorphic;
        returning ``True`` is *not* a guarantee of isomorphism — only a
        pre-check. Faster than a full isomorphism test by orders of
        magnitude on large graphs.
        """
        import networkx as nx

        try:
            return bool(nx.could_be_isomorphic(g1, g2))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("could_be_isomorphic failed: %s", exc)
            return False

    @staticmethod
    def faster_could_be_isomorphic(g1: Any, g2: Any) -> bool:
        """Even-faster necessary-condition check (degree *set* only).

        Cheap O(V) check used as a coarse pre-filter before
        :meth:`could_be_isomorphic`.
        """
        import networkx as nx

        try:
            return bool(nx.faster_could_be_isomorphic(g1, g2))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("faster_could_be_isomorphic failed: %s", exc)
            return False

    @staticmethod
    def is_isomorphic_to(g1: Any, g2: Any) -> bool:
        """Alias for :meth:`is_isomorphic` (legacy nx name)."""
        return Isomorphism.is_isomorphic(g1, g2)

    @staticmethod
    def vf2_graph_isomorphism(g1: Any, g2: Any) -> bool:
        """Return ``True`` if ``g1`` and ``g2`` are VF2-isomorphic.

        Uses :class:`networkx.algorithms.isomorphism.GraphMatcher`
        (or :class:`DiGraphMatcher` for directed graphs) explicitly.
        """
        from networkx.algorithms import isomorphism as iso

        try:
            if g1.is_directed() and g2.is_directed():
                matcher = iso.DiGraphMatcher(g1, g2)
            elif (not g1.is_directed()) and (not g2.is_directed()):
                matcher = iso.GraphMatcher(g1, g2)
            else:
                # One directed, one undirected: not isomorphic.
                return False
            return bool(matcher.is_isomorphic())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("vf2_graph_isomorphism failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Subgraph census / motif counting
    # ------------------------------------------------------------------
    @staticmethod
    def graph_census(g: Any, n: int = 3) -> Dict[str, int]:
        """Return a frequency histogram of every distinct induced subgraph.

        Enumerates every induced subgraph of size ``2..n``, hashes its
        canonical form (faster_could_be_isomorphic + sorted degree
        sequence), and counts occurrences. Returns a dict keyed by a
        string identifier of the form ``"n|sorted_degrees|edge_count"``.

        Args:
            g: A networkx graph (undirected or directed).
            n: Maximum subgraph size to enumerate (default 3).

        Returns:
            ``{subgraph_signature: count}``.

        Note:
            For large graphs and ``n >= 4`` the enumeration cost is
            ``O(C(N, n))`` and may be prohibitive. Use ``n=3`` for
            typical motif analysis.
        """
        if g is None or g.number_of_nodes() < 2:
            return {}
        n = max(2, min(int(n), 4))
        nodes = list(g.nodes())
        census: Dict[str, int] = {}
        for k in range(2, n + 1):
            for combo in combinations(nodes, k):
                sub = g.subgraph(combo)
                if sub.number_of_nodes() < k:
                    continue
                # Canonical signature: size | sorted degree sequence | edges.
                degrees = sorted(dict(sub.degree()).values())
                sig = f"{k}|{degrees}|{sub.number_of_edges()}"
                census[sig] = census.get(sig, 0) + 1
        return census

    @staticmethod
    def find_motifs(g: Any, n: int = 3) -> List[Any]:
        """Return the list of *distinct* induced subgraphs of size ``n``.

        Each motif is returned as a :class:`networkx.Graph` (or
        :class:`DiGraph`) — the first encountered copy of each distinct
        shape.

        Args:
            g: A networkx graph.
            n: Subgraph size (default 3 — triangles, two-paths, etc.).

        Returns:
            A list of distinct :class:`networkx.Graph` motifs.
        """
        import networkx as nx

        if g is None or g.number_of_nodes() < n:
            return []
        n = max(2, min(int(n), 4))
        nodes = list(g.nodes())
        seen: List[Any] = []
        for combo in combinations(nodes, n):
            sub = g.subgraph(combo).copy()
            if sub.number_of_nodes() < n:
                continue
            # Compare against every seen motif using full isomorphism.
            # (Could be made faster with canonical labelling — kept simple.)
            if any(Isomorphism.is_isomorphic(sub, m) for m in seen):
                continue
            seen.append(sub)
            logger.debug("find_motifs: found new motif #%d (%d edges)",
                         len(seen), sub.number_of_edges())
        return seen
