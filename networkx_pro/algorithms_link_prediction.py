"""Link-prediction algorithms — Jaccard, Adamic-Adar, Katz, Soundarajan-Hopcroft.

The :class:`LinkPrediction` class wraps every :mod:`networkx` link-prediction
index with a consistent API. Each method takes a :class:`networkx.Graph`
plus an optional ``ebunch`` (an iterable of ``(u, v)`` node pairs to
score) and returns a list of ``(u, v, score)`` tuples.

:meth:`katz_similarity` and :meth:`predict_top_links` are not part of
networkx proper — they are convenience helpers:
``katz_similarity`` computes a global Katz similarity matrix (requires
:mod:`numpy`); ``predict_top_links`` runs any predictor over the
non-edge set and returns the top-N.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["LinkPrediction"]

logger = logging.getLogger(__name__)


class LinkPrediction:
    """Stateless collection of link-prediction indices."""

    # ------------------------------------------------------------------
    # Indices on shared neighbours
    # ------------------------------------------------------------------
    @staticmethod
    def resource_allocation_index(
        g: Any,
        ebunch: Optional[Any] = None,
    ) -> List[Tuple[Any, Any, float]]:
        """Resource-allocation index (1/degree for each shared neighbour).

        Args:
            g: Undirected graph.
            ebunch: Iterable of ``(u, v)`` pairs to score (default: all
                non-edges).

        Returns:
            A list of ``(u, v, score)`` tuples.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        if ebunch is None:
            ebunch = list(nx.non_edges(g))
        try:
            return [(u, v, float(s)) for u, v, s in nx.resource_allocation_index(g, ebunch)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("resource_allocation_index failed: %s", exc)
            return []

    @staticmethod
    def jaccard_coefficient(
        g: Any,
        ebunch: Optional[Any] = None,
    ) -> List[Tuple[Any, Any, float]]:
        """Jaccard similarity = |N(u) ∩ N(v)| / |N(u) ∪ N(v)|.

        Args:
            g: Undirected graph.
            ebunch: Iterable of pairs (default: all non-edges).

        Returns:
            A list of ``(u, v, score)`` tuples.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        if ebunch is None:
            ebunch = list(nx.non_edges(g))
        try:
            return [(u, v, float(s)) for u, v, s in nx.jaccard_coefficient(g, ebunch)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("jaccard_coefficient failed: %s", exc)
            return []

    @staticmethod
    def adamic_adar_index(
        g: Any,
        ebunch: Optional[Any] = None,
    ) -> List[Tuple[Any, Any, float]]:
        """Adamic-Adar index = Σ 1/log(deg(w)) over shared neighbours w.

        Args:
            g: Undirected graph.
            ebunch: Iterable of pairs (default: all non-edges).

        Returns:
            A list of ``(u, v, score)`` tuples.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        if ebunch is None:
            ebunch = list(nx.non_edges(g))
        try:
            return [(u, v, float(s)) for u, v, s in nx.adamic_adar_index(g, ebunch)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("adamic_adar_index failed: %s", exc)
            return []

    @staticmethod
    def preferential_attachment(
        g: Any,
        ebunch: Optional[Any] = None,
    ) -> List[Tuple[Any, Any, float]]:
        """Preferential-attachment score = deg(u) × deg(v).

        Args:
            g: Undirected graph.
            ebunch: Iterable of pairs (default: all non-edges).

        Returns:
            A list of ``(u, v, score)`` tuples.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        if ebunch is None:
            ebunch = list(nx.non_edges(g))
        try:
            return [(u, v, float(s)) for u, v, s in nx.preferential_attachment(g, ebunch)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("preferential_attachment failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Community-aware indices (require a 'community' node attribute)
    # ------------------------------------------------------------------
    @staticmethod
    def cn_soundarajan_hopcroft(
        g: Any,
        ebunch: Optional[Any] = None,
        community: str = "community",
    ) -> List[Tuple[Any, Any, float]]:
        """Common-neighbour Soundarajan-Hopcroft index.

        Like common neighbours, but adds a bonus ``+1`` for each shared
        neighbour that belongs to the same community as ``u`` (and ``v``).

        Args:
            g: Undirected graph; nodes must have a ``community`` attribute.
            ebunch: Iterable of pairs (default: all non-edges).
            community: Name of the node attribute holding the community id.

        Returns:
            A list of ``(u, v, score)`` tuples.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        if ebunch is None:
            ebunch = list(nx.non_edges(g))
        try:
            return [(u, v, float(s)) for u, v, s in
                    nx.cn_soundarajan_hopcroft(g, ebunch, community=community)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("cn_soundarajan_hopcroft failed: %s", exc)
            return []

    @staticmethod
    def ra_index_soundarajan_hopcroft(
        g: Any,
        ebunch: Optional[Any] = None,
        community: str = "community",
    ) -> List[Tuple[Any, Any, float]]:
        """Resource-allocation variant of Soundarajan-Hopcroft.

        Args:
            g: Undirected graph with ``community`` node attribute.
            ebunch: Iterable of pairs.
            community: Name of the community node attribute.

        Returns:
            A list of ``(u, v, score)`` tuples.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        if ebunch is None:
            ebunch = list(nx.non_edges(g))
        try:
            return [(u, v, float(s)) for u, v, s in
                    nx.ra_index_soundarajan_hopcroft(g, ebunch, community=community)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("ra_index_soundarajan_hopcroft failed: %s", exc)
            return []

    @staticmethod
    def within_inter_cluster(
        g: Any,
        ebunch: Optional[Any] = None,
        delta: float = 0.001,
        community: str = "community",
    ) -> List[Tuple[Any, Any, float]]:
        """Within-inter-cluster ratio score (Soundarajan-Hopcroft 2009).

        Returns the resource-allocation score scaled by the ratio of
        within-community to inter-community shared neighbours, with
        ``delta`` preventing zero-division.

        Args:
            g: Undirected graph with ``community`` node attribute.
            ebunch: Iterable of pairs.
            delta: Small constant preventing zero division.
            community: Community attribute name.

        Returns:
            A list of ``(u, v, score)`` tuples.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        if ebunch is None:
            ebunch = list(nx.non_edges(g))
        try:
            return [(u, v, float(s)) for u, v, s in
                    nx.within_inter_cluster(g, ebunch, delta=delta, community=community)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("within_inter_cluster failed: %s", exc)
            return []

    @staticmethod
    def common_neighbor_centrality(
        g: Any,
        ebunch: Optional[Any] = None,
        alpha: float = 0.8,
    ) -> List[Tuple[Any, Any, float]]:
        """Common-neighbour + centrality hybrid index.

        ``score = alpha × CN(u, v) + (1 - alpha) × (n - 1 - d(u, v))``
        where ``CN`` is the common-neighbour count and ``d`` is the
        geodesic distance.

        Args:
            g: Undirected graph.
            ebunch: Iterable of pairs.
            alpha: Mixing parameter (0 = pure centrality, 1 = pure CN).

        Returns:
            A list of ``(u, v, score)`` tuples.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        if ebunch is None:
            ebunch = list(nx.non_edges(g))
        try:
            return [(u, v, float(s)) for u, v, s in
                    nx.common_neighbor_centrality(g, ebunch, alpha=alpha)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("common_neighbor_centrality failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Global similarity
    # ------------------------------------------------------------------
    @staticmethod
    def katz_similarity(
        g: Any,
        alpha: float = 0.005,
        beta: float = 1.0,
        max_iter: int = 1000,
    ) -> Dict[Any, Dict[Any, float]]:
        """Return the Katz similarity matrix ``S = β (I - α A)^{-1}``.

        Each entry ``S[u][v]`` is the sum over all paths from ``u`` to
        ``v``, weighted by ``alpha^length * beta``. Requires :mod:`numpy`.

        Args:
            g: A networkx graph.
            alpha: Path-length discount (must be < 1/spectral_radius(A)).
            beta: Constant broadcast term.
            max_iter: Maximum power-iteration steps (only used if
                the direct inverse fails).

        Returns:
            ``{u: {v: score}}``.
        """
        try:
            import numpy as np
        except Exception as exc:  # pragma: no cover - optional dep
            logger.warning("katz_similarity requires numpy: %s", exc)
            return {}

        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        nodes = list(g.nodes())
        n = len(nodes)
        idx = {node: i for i, node in enumerate(nodes)}
        A = nx.to_numpy_array(g, nodelist=nodes)
        try:
            S = beta * np.linalg.inv(np.eye(n) - alpha * A)
        except np.linalg.LinAlgError:
            # Iterative fallback (Neumann series).
            S = np.zeros((n, n))
            term = beta * np.eye(n)
            for _ in range(max_iter):
                S += term
                term = alpha * term @ A
                if np.linalg.norm(term, ord=2) < 1e-9:
                    break
        out: Dict[Any, Dict[Any, float]] = {}
        for u in nodes:
            out[u] = {v: float(S[idx[u], idx[v]]) for v in nodes}
        return out

    # ------------------------------------------------------------------
    # One-shot top-N predictor
    # ------------------------------------------------------------------
    @staticmethod
    def predict_top_links(
        g: Any,
        method: str = "jaccard",
        n: int = 10,
    ) -> List[Tuple[Any, Any, float]]:
        """Predict the top-``n`` missing links using any predictor.

        Runs the chosen predictor over *all* non-edges and returns
        the ``n`` highest-scoring ``(u, v, score)`` tuples. Existing
        edges are excluded.

        Args:
            g: Undirected graph (DiGraphs converted).
            method: One of ``'jaccard'`` (default), ``'adamic_adar'``,
                ``'preferential_attachment'``, ``'resource_allocation'``,
                ``'common_neighbor_centrality'``.

        Returns:
            A list of ``(u, v, score)`` tuples sorted descending by
            score. Zero-score predictions are filtered out (except for
            preferential_attachment, which has no canonical baseline).
        """
        method = method.lower().strip()
        predictors = {
            "jaccard": LinkPrediction.jaccard_coefficient,
            "adamic_adar": LinkPrediction.adamic_adar_index,
            "preferential_attachment": LinkPrediction.preferential_attachment,
            "resource_allocation": LinkPrediction.resource_allocation_index,
            "common_neighbor_centrality": LinkPrediction.common_neighbor_centrality,
        }
        if method not in predictors:
            raise ValueError(
                f"Unknown method: {method!r}. "
                f"Expected one of {list(predictors)}."
            )
        try:
            preds = predictors[method](g, ebunch=None)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("predict_top_links(%s) failed: %s", method, exc)
            return []
        if method != "preferential_attachment":
            preds = [p for p in preds if p[2] > 0]
        preds.sort(key=lambda x: -x[2])
        return preds[:n]
