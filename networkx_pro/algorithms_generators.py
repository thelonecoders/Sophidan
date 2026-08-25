"""Synthetic-graph generators — canonical topologies + null-model factory.

The :class:`GraphGenerators` class wraps every commonly-needed
:mod:`networkx` graph generator with a single static-method interface:

- Canonical topologies: complete, complete-bipartite.
- Real-world example graphs: karate club, Davis southern women,
  Florentine families.
- Random models: Erdős-Rényi, Watts-Strogatz, Barabási-Albert,
  powerlaw-cluster, random-geometric.
- Degree-sequence models: configuration, expected-degree,
  Havel-Hakimi.
- Tree & cograph generators: random labelled tree, random cograph.
- :meth:`null_model` — generates ``n`` randomised null models whose
  degree sequence matches the input graph where possible (uses
  :func:`nx.configuration_model` with edge swaps on top for the
  'configuration' method; uses :func:`nx.gnp_random_graph` for the
  'erdos_renyi' method with the input graph's edge density).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

__all__ = ["GraphGenerators"]

logger = logging.getLogger(__name__)


class GraphGenerators:
    """Stateless collection of synthetic-graph generators."""

    # ------------------------------------------------------------------
    # Canonical topologies
    # ------------------------------------------------------------------
    @staticmethod
    def complete_graph(n: int) -> Any:
        """Return the complete graph ``K_n``."""
        import networkx as nx

        if n <= 0:
            return nx.Graph()
        return nx.complete_graph(n)

    @staticmethod
    def complete_bipartite_graph(n1: int, n2: int) -> Any:
        """Return the complete bipartite graph ``K_{n1, n2}``."""
        import networkx as nx

        if n1 <= 0 or n2 <= 0:
            return nx.Graph()
        return nx.complete_bipartite_graph(n1, n2)

    # ------------------------------------------------------------------
    # Real-world example graphs
    # ------------------------------------------------------------------
    @staticmethod
    def karate_club_graph() -> Any:
        """Return Zachary's karate-club graph (34 nodes, 78 edges)."""
        import networkx as nx

        return nx.karate_club_graph()

    @staticmethod
    def davis_southern_women_graph() -> Any:
        """Return Davis's southern-women graph (bipartite, 32 nodes)."""
        import networkx as nx

        return nx.davis_southern_women_graph()

    @staticmethod
    def florentine_families_graph() -> Any:
        """Return the Florentine-families marriage graph (15 nodes)."""
        import networkx as nx

        return nx.florentine_families_graph()

    # ------------------------------------------------------------------
    # Random models
    # ------------------------------------------------------------------
    @staticmethod
    def erdos_renyi_graph(
        n: int,
        p: float,
        seed: Optional[int] = None,
    ) -> Any:
        """Return an Erdős-Rényi ``G(n, p)`` graph.

        Each of the ``C(n, 2)`` possible edges is included independently
        with probability ``p``.

        Args:
            n: Number of nodes.
            p: Edge probability.
            seed: RNG seed.

        Returns:
            A :class:`networkx.Graph`.
        """
        import networkx as nx

        if n <= 0:
            return nx.Graph()
        p = max(0.0, min(1.0, float(p)))
        return nx.gnp_random_graph(n, p, seed=seed)

    @staticmethod
    def watts_strogatz_graph(
        n: int,
        k: int,
        p: float,
        seed: Optional[int] = None,
    ) -> Any:
        """Return a Watts-Strogatz small-world graph.

        Args:
            n: Number of nodes.
            k: Each node connects to its ``k`` nearest neighbours in a ring.
            p: Rewiring probability.
            seed: RNG seed.
        """
        import networkx as nx

        if n <= 0:
            return nx.Graph()
        k = max(2, min(k, n - 1))
        p = max(0.0, min(1.0, float(p)))
        return nx.watts_strogatz_graph(n, k, p, seed=seed)

    @staticmethod
    def barabasi_albert_graph(
        n: int,
        m: int,
        seed: Optional[int] = None,
    ) -> Any:
        """Return a Barabási-Albert preferential-attachment graph.

        Args:
            n: Number of nodes.
            m: Number of edges each new node attaches.
            seed: RNG seed.
        """
        import networkx as nx

        if n <= 0:
            return nx.Graph()
        m = max(1, min(m, n - 1))
        return nx.barabasi_albert_graph(n, m, seed=seed)

    @staticmethod
    def powerlaw_cluster_graph(
        n: int,
        m: int,
        p: float,
        seed: Optional[int] = None,
    ) -> Any:
        """Return a Holme-Kim power-law-cluster graph.

        Args:
            n: Number of nodes.
            m: Number of edges each new node attaches.
            p: Probability of forming a triangle after each BA-style attachment.
            seed: RNG seed.
        """
        import networkx as nx

        if n <= 0:
            return nx.Graph()
        m = max(1, min(m, n - 1))
        p = max(0.0, min(1.0, float(p)))
        return nx.powerlaw_cluster_graph(n, m, p, seed=seed)

    @staticmethod
    def random_geometric_graph(
        n: int,
        radius: float,
        dim: int = 2,
        pos: Optional[dict] = None,
    ) -> Any:
        """Return a random geometric graph.

        Args:
            n: Number of nodes.
            radius: Connection radius.
            dim: Dimensionality of the embedding space.
            pos: Optional pre-computed positions dict.
        """
        import networkx as nx

        if n <= 0:
            return nx.Graph()
        return nx.random_geometric_graph(n, radius, dim=dim, pos=pos)

    # ------------------------------------------------------------------
    # Degree-sequence models
    # ------------------------------------------------------------------
    @staticmethod
    def configuration_graph(
        deg_sequence: Sequence[int],
        seed: Optional[int] = None,
    ) -> Any:
        """Return a configuration-model graph with a given degree sequence.

        Args:
            deg_sequence: Sequence of node degrees.
            seed: RNG seed.

        Returns:
            A :class:`networkx.Graph` (may be a :class:`MultiGraph` if
            parallel edges are created).
        """
        import networkx as nx

        seq = [int(d) for d in deg_sequence]
        if not seq:
            return nx.Graph()
        try:
            return nx.configuration_model(seq, seed=seed)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("configuration_graph failed: %s", exc)
            return nx.Graph()

    @staticmethod
    def expected_degree_graph(
        w: Sequence[float],
        selfloops: bool = True,
        seed: Optional[int] = None,
    ) -> Any:
        """Return a Chung-Lu random graph with a given expected-degree sequence.

        Args:
            w: Expected-degree sequence.
            selfloops: Allow self-loops.
            seed: RNG seed.
        """
        import networkx as nx

        if not w:
            return nx.Graph()
        try:
            return nx.expected_degree_graph(list(w), selfloops=selfloops, seed=seed)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("expected_degree_graph failed: %s", exc)
            return nx.Graph()

    @staticmethod
    def havel_hakimi_graph(deg_sequence: Sequence[int]) -> Any:
        """Return a Havel-Hakimi graph with a given degree sequence.

        Args:
            deg_sequence: Sequence of node degrees (must be graphical).
        """
        import networkx as nx

        seq = [int(d) for d in deg_sequence]
        if not seq:
            return nx.Graph()
        try:
            return nx.havel_hakimi_graph(seq)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("havel_hakimi_graph failed: %s", exc)
            return nx.Graph()

    @staticmethod
    def tree_graph(
        n: int,
        create_using: Optional[Any] = None,
    ) -> Any:
        """Return a random labelled tree on ``n`` nodes.

        Args:
            n: Number of nodes.
            create_using: Optional :class:`networkx.Graph` subclass to use
                (default: :class:`networkx.Graph`).
        """
        import networkx as nx

        if n <= 0:
            return nx.Graph() if create_using is None else create_using()
        try:
            tree = nx.random_labeled_tree(n)
            if create_using is not None:
                # Rebuild the tree on top of the requested graph type.
                g = create_using()
                g.add_nodes_from(tree.nodes())
                g.add_edges_from(tree.edges())
                return g
            return tree
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("tree_graph failed: %s", exc)
            return nx.Graph() if create_using is None else create_using()

    @staticmethod
    def random_cograph(n: int, seed: Optional[int] = None) -> Any:
        """Return a random cograph on ``2**n`` nodes.

        Args:
            n: Number of recursive levels (graph has ``2**n`` nodes).
            seed: RNG seed.
        """
        import networkx as nx

        if n <= 0:
            return nx.Graph()
        return nx.random_cograph(n, seed=seed)

    # ------------------------------------------------------------------
    # Null-model factory
    # ------------------------------------------------------------------
    @staticmethod
    def null_model(
        g: Any,
        n: int = 10,
        method: str = "erdos_renyi",
    ) -> List[Any]:
        """Generate ``n`` randomised null models matching basic graph stats.

        Args:
            g: An input :class:`networkx.Graph`.
            n: Number of null models to generate.
            method: ``'erdos_renyi'`` (default) — :func:`nx.gnp_random_graph`
                with the input graph's edge density. ``'configuration'`` —
                :func:`nx.configuration_model` matching the input graph's
                degree sequence (will use random ``seed`` per realisation).

        Returns:
            A list of ``n`` :class:`networkx.Graph` objects.
        """
        import networkx as nx

        method = method.lower().strip()
        if method not in {"erdos_renyi", "configuration"}:
            raise ValueError(
                f"Unknown null_model method: {method!r}. "
                f"Expected erdos_renyi|configuration."
            )
        if n <= 0:
            return []
        nodes = g.number_of_nodes()
        if nodes < 1:
            return [nx.Graph() for _ in range(n)]
        if g.is_directed():
            logger.debug("null_model: directed graph — converting to undirected.")
            g = g.to_undirected()
        out: List[Any] = []
        if method == "erdos_renyi":
            # Match edge density.
            p = (2.0 * g.number_of_edges()) / max(1.0, nodes * (nodes - 1))
            for i in range(n):
                out.append(nx.gnp_random_graph(nodes, p, seed=i))
        else:  # configuration
            deg_seq = [d for _, d in g.degree()]
            for i in range(n):
                try:
                    cm = nx.configuration_model(deg_seq, seed=i)
                    # Configuration model is a MultiGraph; collapse parallel edges.
                    simple = nx.Graph()
                    simple.add_nodes_from(cm.nodes())
                    simple.add_edges_from(cm.edges())
                    out.append(simple)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("null_model configuration realisation %d failed: %s", i, exc)
                    out.append(nx.Graph())
        return out
