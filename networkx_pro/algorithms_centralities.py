"""Node-centralities — full NetworkX exposure of every centrality measure.

The :class:`Centralities` class is a stateless collection of static methods
that wrap :mod:`networkx` centrality functions with consistent behaviour:

- Every method takes a :class:`networkx.Graph` (or :class:`DiGraph`) as its
  first argument and returns a ``{node: score}`` mapping.
- Every method lazy-imports :mod:`networkx` (and numpy/scipy for the
  ``*_numpy`` variants) so the module is importable in environments that
  only have networkx installed.
- DiGraph vs Graph is handled automatically: methods that require an
  undirected graph (e.g. :meth:`current_flow_closeness_centrality`) will
  silently convert a DiGraph via ``.to_undirected()``.
- The convenience aggregator :meth:`all_centralities` runs every applicable
  centrality in one shot and returns ``{metric_name: {node: score}}``.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

__all__ = ["Centralities"]

logger = logging.getLogger(__name__)


class Centralities:
    """Stateless wrapper exposing every node-centrality measure in networkx."""

    # ------------------------------------------------------------------
    # Degree family
    # ------------------------------------------------------------------
    @staticmethod
    def degree_centrality(g: Any) -> Dict[Any, float]:
        """Return degree centrality for every node.

        Args:
            g: A :class:`networkx.Graph` (or :class:`DiGraph` — for directed
                graphs this is the *total* degree = in + out).

        Returns:
            ``{node: degree_centrality}``. The denominator is ``n-1`` so
            scores are normalised into ``[0, 1]`` for simple graphs.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if g.is_directed():
            # Sum of in-degree and out-degree, normalised by (n-1).
            return {n: (g.in_degree(n) + g.out_degree(n)) / max(1, (g.number_of_nodes() - 1))
                    for n in g.nodes()}
        return dict(nx.degree_centrality(g))

    @staticmethod
    def in_degree_centrality(g: Any) -> Dict[Any, float]:
        """Return in-degree centrality for every node (DiGraph only)."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if not g.is_directed():
            logger.debug("in_degree_centrality called on undirected graph — returning degree_centrality.")
            return dict(nx.degree_centrality(g))
        return dict(nx.in_degree_centrality(g))

    @staticmethod
    def out_degree_centrality(g: Any) -> Dict[Any, float]:
        """Return out-degree centrality for every node (DiGraph only)."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if not g.is_directed():
            logger.debug("out_degree_centrality called on undirected graph — returning degree_centrality.")
            return dict(nx.degree_centrality(g))
        return dict(nx.out_degree_centrality(g))

    # ------------------------------------------------------------------
    # Geodesic family
    # ------------------------------------------------------------------
    @staticmethod
    def closeness_centrality(
        g: Any,
        u: Optional[Any] = None,
        distance: Optional[str] = None,
        wf_improved: bool = True,
    ) -> Dict[Any, float]:
        """Return (optionally Wasserman-Faust improved) closeness centrality.

        Args:
            g: A networkx graph.
            u: If given, compute only for this node and return a single float
                wrapped in a dict — otherwise for every node.
            distance: Edge attribute to use as distance (default = hop count).
            wf_improved: Apply Wasserman-Faust normalisation for disconnected
                graphs.

        Returns:
            ``{node: score}`` (or ``{u: score}`` if ``u`` was supplied).
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        try:
            return dict(nx.closeness_centrality(
                g, u=u, distance=distance, wf_improved=wf_improved,
            ))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("closeness_centrality failed: %s", exc)
            return {}

    @staticmethod
    def betweenness_centrality(
        g: Any,
        k: Optional[int] = None,
        normalized: bool = True,
        weight: Optional[str] = None,
        endpoints: bool = False,
        seed: Optional[int] = None,
    ) -> Dict[Any, float]:
        """Return betweenness centrality (optionally approximated via k samples).

        Args:
            g: A networkx graph.
            k: Sample size for approximation (``None`` = exact computation).
            normalized: Divide by ``2 / ((n-1)(n-2))`` (undirected) or
                ``1 / ((n-1)(n-2))`` (directed).
            weight: Edge attribute to use as path cost (``None`` = hop count).
            endpoints: Include endpoints in the shortest path count.
            seed: RNG seed for the ``k``-sample approximation.

        Returns:
            ``{node: betweenness_score}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        try:
            return dict(nx.betweenness_centrality(
                g, k=k, normalized=normalized, weight=weight,
                endpoints=endpoints, seed=seed,
            ))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("betweenness_centrality failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Spectral family
    # ------------------------------------------------------------------
    @staticmethod
    def eigenvector_centrality(
        g: Any,
        max_iter: int = 100,
        tol: float = 1e-06,
        weight: Optional[str] = None,
        nstart: Optional[Dict[Any, float]] = None,
    ) -> Dict[Any, float]:
        """Return eigenvector centrality via power iteration."""
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        try:
            return dict(nx.eigenvector_centrality(
                g, max_iter=max_iter, tol=tol, weight=weight, nstart=nstart,
            ))
        except nx.PowerIterationFailedConvergence as exc:
            logger.warning("eigenvector_centrality did not converge: %s", exc)
            return {n: 0.0 for n in g.nodes()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("eigenvector_centrality failed: %s", exc)
            return {}

    @staticmethod
    def eigenvector_centrality_numpy(
        g: Any,
        weight: Optional[str] = None,
    ) -> Dict[Any, float]:
        """Return eigenvector centrality via numpy / scipy eigen-decomposition.

        Faster and numerically more stable than power iteration for medium graphs but
        requires :mod:`numpy` and :mod:`scipy`.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        try:
            return dict(nx.eigenvector_centrality_numpy(g, weight=weight))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("eigenvector_centrality_numpy failed: %s", exc)
            return {}

    @staticmethod
    def katz_centrality(
        g: Any,
        alpha: float = 0.1,
        beta: float = 1.0,
        max_iter: int = 1000,
        tol: float = 1e-06,
        weight: Optional[str] = None,
    ) -> Dict[Any, float]:
        """Return Katz centrality (a PageRank / eigenvector generalisation).

        Args:
            g: A networkx graph.
            alpha: Discount factor (must be < 1/lambda_max of the adjacency
                matrix for convergence).
            beta: Constant broadcast term (scalar or per-node dict).
            max_iter: Maximum power-iteration steps.
            tol: Convergence tolerance on the L1 residual.
            weight: Edge attribute to use as weight.

        Returns:
            ``{node: score}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        try:
            return dict(nx.katz_centrality(
                g, alpha=alpha, beta=beta, max_iter=max_iter,
                tol=tol, weight=weight,
            ))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("katz_centrality failed: %s", exc)
            return {}

    @staticmethod
    def pagerank(
        g: Any,
        alpha: float = 0.85,
        personalization: Optional[Dict[Any, float]] = None,
        max_iter: int = 100,
        tol: float = 1e-06,
        nstart: Optional[Dict[Any, float]] = None,
        weight: Optional[str] = "weight",
        dangling: Optional[Dict[Any, float]] = None,
    ) -> Dict[Any, float]:
        """Return PageRank centrality.

        Args:
            g: A networkx graph (directed recommended; undirected graphs are
                treated as bidirectional).
            alpha: Damping factor (typically 0.85).
            personalization: Optional per-node bias dict.
            max_iter: Maximum iterations.
            tol: Convergence tolerance.
            nstart: Optional starting vector.
            weight: Edge attribute to use as edge weight (``"weight"`` by
                default; pass ``None`` for unweighted).
            dangling: How to redistribute dangling-node mass.

        Returns:
            ``{node: pagerank_score}`` summing to ~1.0.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        try:
            return dict(nx.pagerank(
                g, alpha=alpha, personalization=personalization,
                max_iter=max_iter, tol=tol, nstart=nstart,
                weight=weight, dangling=dangling,
            ))
        except nx.PowerIterationFailedConvergence as exc:
            logger.warning("pagerank did not converge: %s", exc)
            # Uniform fallback.
            n = g.number_of_nodes()
            return {node: 1.0 / n for node in g.nodes()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("pagerank failed: %s", exc)
            return {}

    @staticmethod
    def hits(
        g: Any,
        max_iter: int = 100,
        tol: float = 1e-08,
        normalized: bool = True,
    ) -> Tuple[Dict[Any, float], Dict[Any, float]]:
        """Return Kleinberg's HITS scores.

        Args:
            g: A networkx graph (directed recommended).
            max_iter: Maximum iterations.
            tol: Convergence tolerance.
            normalized: Normalise scores to sum to 1.

        Returns:
            ``(hubs, authorities)`` — two ``{node: score}`` dicts.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}, {}
        if not g.is_directed():
            logger.debug("hits() called on undirected graph — converting to directed.")
            g = g.to_directed()
        try:
            hubs, auth = nx.hits(g, max_iter=max_iter, tol=tol, normalized=normalized)
            return dict(hubs), dict(auth)
        except nx.PowerIterationFailedConvergence as exc:
            logger.warning("hits did not converge: %s", exc)
            n = g.number_of_nodes()
            return ({node: 1.0 / n for node in g.nodes()},
                    {node: 1.0 / n for node in g.nodes()})
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("hits failed: %s", exc)
            return {}, {}

    @staticmethod
    def authority_score(g: Any) -> Dict[Any, float]:
        """Shortcut: return only the *authorities* half of HITS."""
        _, auth = Centralities.hits(g)
        return auth

    @staticmethod
    def hub_score(g: Any) -> Dict[Any, float]:
        """Shortcut: return only the *hubs* half of HITS."""
        hubs, _ = Centralities.hits(g)
        return hubs

    # ------------------------------------------------------------------
    # Walk-based family
    # ------------------------------------------------------------------
    @staticmethod
    def harmonic_centrality(
        g: Any,
        source: str = "in",
        distance: Optional[str] = None,
    ) -> Dict[Any, float]:
        """Return harmonic centrality (sum of 1/distance to every other node).

        Args:
            g: A networkx graph.
            source: For directed graphs: ``'in'`` counts incoming paths,
                ``'out'`` counts outgoing paths.
            distance: Edge attribute to use as distance (default = hop count).

        Returns:
            ``{node: score}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        try:
            # networkx ≥ 3.x renamed the kwarg to ``source`` (was nbunch).
            return dict(nx.harmonic_centrality(g, distance=distance, source=source))
        except TypeError:
            # Old networkx signatures: fall back without source.
            return dict(nx.harmonic_centrality(g, distance=distance))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("harmonic_centrality failed: %s", exc)
            return {}

    @staticmethod
    def percolation_centrality(
        g: Any,
        attribute: str = "percolation",
        states: Optional[Any] = None,
    ) -> Dict[Any, float]:
        """Return percolation centrality (centrality weighted by node state).

        Args:
            g: A networkx graph. Each node must have a ``attribute`` key in
                its data dict giving a percolation state in ``[0, 1]``.
                If the attribute is missing on every node, the node degree
                (normalised to ``[0, 1]``) is used as a default proxy so
                the method always returns a meaningful score.
            attribute: Name of the percolation-state node attribute.
            states: Optional (pre-computed) state dict.

        Returns:
            ``{node: score}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        has_any = any(attribute in d for _, d in g.nodes(data=True))
        if not has_any:
            logger.debug(
                "percolation_centrality: attribute %r missing on every node — "
                "using degree (normalised) as a percolation-state proxy.",
                attribute,
            )
            max_deg = max((g.degree(n) for n in g.nodes()), default=1) or 1
            for n in g.nodes():
                g.nodes[n][attribute] = float(g.degree(n)) / float(max_deg)
        else:
            # Ensure every node has the attribute (default 0.0).
            for n, d in g.nodes(data=True):
                if attribute not in d:
                    d[attribute] = 0.0
        try:
            return dict(nx.percolation_centrality(g, attribute=attribute, states=states))
        except ZeroDivisionError:
            # All states are equal → percolation_centrality is undefined.
            logger.debug(
                "percolation_centrality: all states equal — returning 0 for every node."
            )
            return {n: 0.0 for n in g.nodes()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("percolation_centrality failed: %s", exc)
            return {}

    @staticmethod
    def second_order_centrality(g: Any) -> Dict[Any, float]:
        """Return second-order centrality (std-dev of return times in a random walk).

        Requires a *connected* graph — disconnected graphs are restricted
        to their largest connected component first.

        Args:
            g: A networkx graph.

        Returns:
            ``{node: score}`` (lower = more central).
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if g.is_directed():
            # Convert to undirected (second_order_centrality requires undirected).
            g = g.to_undirected()
        if not nx.is_connected(g):
            logger.debug("second_order_centrality: graph disconnected — using largest CC.")
            cc = max(nx.connected_components(g), key=len)
            g = g.subgraph(cc).copy()
        try:
            return dict(nx.second_order_centrality(g))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("second_order_centrality failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Current-flow family (require connected undirected graphs)
    # ------------------------------------------------------------------
    @staticmethod
    def current_flow_closeness_centrality(g: Any) -> Dict[Any, float]:
        """Return current-flow closeness centrality (info centrality).

        Args:
            g: A *connected* :class:`networkx.Graph`. DiGraphs are converted
                to undirected; disconnected graphs are restricted to the
                largest connected component.

        Returns:
            ``{node: score}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if g.is_directed():
            g = g.to_undirected()
        if not nx.is_connected(g):
            logger.debug("current_flow_closeness_centrality: disconnected — using largest CC.")
            cc = max(nx.connected_components(g), key=len)
            g = g.subgraph(cc).copy()
        try:
            return dict(nx.current_flow_closeness_centrality(g))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("current_flow_closeness_centrality failed: %s", exc)
            return {}

    @staticmethod
    def current_flow_betweenness_centrality(
        g: Any,
        normalized: bool = True,
        weight: Optional[str] = None,
        dtype: Any = float,
        solver: str = "lu",
    ) -> Dict[Any, float]:
        """Return current-flow betweenness centrality (random-walk BC).

        Args:
            g: A *connected* undirected graph.
            normalized: Normalise scores.
            weight: Edge attribute to use as conductance.
            dtype: numpy dtype of the linear-system solver.
            solver: ``'lu'`` (default) or ``'cg'``.

        Returns:
            ``{node: score}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if g.is_directed():
            g = g.to_undirected()
        if not nx.is_connected(g):
            logger.debug("current_flow_betweenness_centrality: disconnected — using largest CC.")
            cc = max(nx.connected_components(g), key=len)
            g = g.subgraph(cc).copy()
        try:
            return dict(nx.current_flow_betweenness_centrality(
                g, normalized=normalized, weight=weight, dtype=dtype, solver=solver,
            ))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("current_flow_betweenness_centrality failed: %s", exc)
            return {}

    @staticmethod
    def communicability_centrality(g: Any) -> Dict[Any, float]:
        """Return the per-node Estrada contribution (communicability diagonal).

        For each node ``n`` this is the diagonal entry of the matrix
        ``exp(A)`` where ``A`` is the adjacency matrix — equivalently,
        the sum over all *closed* walks starting and ending at ``n``,
        weighted by ``1 / sqrt(walk_length!)``. Identical in value to
        :meth:`subgraph_centrality` (the two names are mathematical
        aliases in modern networkx).

        Args:
            g: A networkx graph.

        Returns:
            ``{node: score}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        try:
            comm = nx.communicability(g)
            return {n: float(comm[n][n]) for n in g.nodes()}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("communicability_centrality failed: %s", exc)
            return {}

    @staticmethod
    def load_centrality(
        g: Any,
        v: Optional[Any] = None,
        cutoff: Optional[int] = None,
        normalized: bool = True,
        weight: Optional[str] = None,
    ) -> Dict[Any, float]:
        """Return load centrality (number of shortest paths through each node).

        Args:
            g: A networkx graph.
            v: If given, compute only for this node.
            cutoff: Maximum path length to consider.
            normalized: Normalise scores.
            weight: Edge attribute to use as path cost.

        Returns:
            ``{node: score}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        try:
            return dict(nx.load_centrality(
                g, v=v, cutoff=cutoff, normalized=normalized, weight=weight,
            ))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("load_centrality failed: %s", exc)
            return {}

    @staticmethod
    def subgraph_centrality(g: Any) -> Dict[Any, float]:
        """Return subgraph centrality (Estrada 2005).

        Each node's score is the sum of closed walks of all lengths
        starting and ending at the node, weighted by ``1 / k!`` for
        walks of length ``k``.

        Args:
            g: A networkx graph (undirected; DiGraphs are converted).

        Returns:
            ``{node: score}``.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return {}
        if g.is_directed():
            g = g.to_undirected()
        try:
            return dict(nx.subgraph_centrality(g))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("subgraph_centrality failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # One-shot aggregator
    # ------------------------------------------------------------------
    @staticmethod
    def all_centralities(g: Any) -> Dict[str, Dict[Any, float]]:
        """Run every applicable centrality measure in one shot.

        Each metric is wrapped in its own try/except so a single failure
        does not abort the whole batch. The returned dict is keyed by
        metric name; values are ``{node: score}`` dicts.

        Args:
            g: A networkx graph.

        Returns:
            A dict with up to 18 entries:

            ``degree_centrality``, ``in_degree_centrality``,
            ``out_degree_centrality`` (DiGraph only), ``closeness_centrality``,
            ``betweenness_centrality``, ``eigenvector_centrality``,
            ``eigenvector_centrality_numpy``, ``katz_centrality``,
            ``pagerank``, ``authority_score``, ``hub_score``,
            ``harmonic_centrality``, ``percolation_centrality``,
            ``second_order_centrality``, ``current_flow_closeness_centrality``,
            ``current_flow_betweenness_centrality``,
            ``communicability_centrality``, ``load_centrality``,
            ``subgraph_centrality``.
        """
        results: Dict[str, Dict[Any, float]] = {}
        C = Centralities
        # Always-applicable measures.
        for name, fn in [
            ("degree_centrality", C.degree_centrality),
            ("closeness_centrality", C.closeness_centrality),
            ("betweenness_centrality", C.betweenness_centrality),
            ("eigenvector_centrality", C.eigenvector_centrality),
            ("katz_centrality", C.katz_centrality),
            ("pagerank", C.pagerank),
            ("harmonic_centrality", C.harmonic_centrality),
            ("percolation_centrality", C.percolation_centrality),
            ("load_centrality", C.load_centrality),
            ("communicability_centrality", C.communicability_centrality),
            ("subgraph_centrality", C.subgraph_centrality),
        ]:
            try:
                results[name] = fn(g)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("all_centralities: %s failed: %s", name, exc)
                results[name] = {}
        # DiGraph-only measures.
        if g.is_directed():
            for name, fn in [
                ("in_degree_centrality", C.in_degree_centrality),
                ("out_degree_centrality", C.out_degree_centrality),
                ("authority_score", C.authority_score),
                ("hub_score", C.hub_score),
            ]:
                try:
                    results[name] = fn(g)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("all_centralities: %s failed: %s", name, exc)
                    results[name] = {}
        else:
            # HITS is meaningful on directed graphs; for undirected we still
            # attempt it via the to_directed() shim inside hits().
            try:
                hubs, auth = C.hits(g)
                results["hub_score"] = hubs
                results["authority_score"] = auth
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("all_centralities: hits failed: %s", exc)
                results["hub_score"] = {}
                results["authority_score"] = {}
        # Heavy measures that may fail on huge / disconnected graphs.
        for name, fn in [
            ("second_order_centrality", C.second_order_centrality),
            ("current_flow_closeness_centrality", C.current_flow_closeness_centrality),
            ("current_flow_betweenness_centrality", C.current_flow_betweenness_centrality),
            ("eigenvector_centrality_numpy", C.eigenvector_centrality_numpy),
        ]:
            try:
                results[name] = fn(g)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("all_centralities: %s failed: %s", name, exc)
                results[name] = {}
        return results
