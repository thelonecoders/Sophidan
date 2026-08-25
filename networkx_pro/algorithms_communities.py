"""Community-detection algorithms — Louvain, Greedy, LPA, Girvan-Newman, k-clique.

The :class:`CommunityDetection` class is a stateless collection of static
methods that wrap :mod:`networkx.algorithms.community` with consistent
behaviour:

- Every algorithm takes a :class:`networkx.Graph` as its first argument
  and returns a list of node-sets (one set per community). DiGraphs are
  silently converted to undirected where required.
- Quality measures (modularity, partition quality, density) accept
  either the ``list[set]`` output of the algorithms *or* a
  ``{node: community_id}`` mapping.
- :meth:`silhouette_score` requires :mod:`scikit-learn`; it converts
  the graph into a node-embedding via spectral decomposition before
  scoring.
- :meth:`compare_communities` exposes NMI / AMI / ARI / VI (variation
  of information) and requires :mod:`scikit-learn` / :mod:`numpy`.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union

__all__ = ["CommunityDetection"]

logger = logging.getLogger(__name__)


class CommunityDetection:
    """Stateless collection of community-detection algorithms."""

    # ------------------------------------------------------------------
    # Algorithms — return List[Set]
    # ------------------------------------------------------------------
    @staticmethod
    def louvain_communities(
        g: Any,
        resolution: float = 1,
        seed: Optional[int] = None,
    ) -> List[Set[Any]]:
        """Detect communities via Louvain modularity maximisation.

        Args:
            g: Undirected :class:`networkx.Graph` (DiGraphs are converted).
            resolution: Higher values favour smaller communities.
            seed: RNG seed (for reproducibility).

        Returns:
            A list of node-sets.
        """
        from networkx.algorithms.community import louvain_communities

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        try:
            return [set(c) for c in louvain_communities(g, resolution=resolution, seed=seed)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("louvain_communities failed: %s", exc)
            return []

    @staticmethod
    def greedy_modularity_communities(
        g: Any,
        resolution: float = 1,
    ) -> List[Set[Any]]:
        """Detect communities via the Clauset-Newman-Moore greedy agglomeration.

        Args:
            g: Undirected graph.
            resolution: Modularity resolution parameter.

        Returns:
            A list of node-sets.
        """
        from networkx.algorithms.community import greedy_modularity_communities

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        try:
            return [set(c) for c in greedy_modularity_communities(g, resolution=resolution)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("greedy_modularity_communities failed: %s", exc)
            return []

    @staticmethod
    def label_propagation_communities(g: Any) -> List[Set[Any]]:
        """Detect communities via synchronous label propagation.

        Fast (near-linear) but non-deterministic — for reproducibility
        prefer :meth:`asyn_lpa_communities` with a fixed ``seed``.

        Args:
            g: Undirected graph.

        Returns:
            A list of node-sets.
        """
        from networkx.algorithms.community import label_propagation_communities

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        try:
            return [set(c) for c in label_propagation_communities(g)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("label_propagation_communities failed: %s", exc)
            return []

    @staticmethod
    def asyn_lpa_communities(
        g: Any,
        weight: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> List[Set[Any]]:
        """Asynchronous label-propagation community detection.

        Args:
            g: Undirected graph.
            weight: Optional edge-attribute name.
            seed: RNG seed (recommended — LPA is otherwise non-deterministic).

        Returns:
            A list of node-sets.
        """
        from networkx.algorithms.community import asyn_lpa_communities

        if g.number_of_nodes() == 0:
            return []
        if g.is_directed():
            g = g.to_undirected()
        try:
            return [set(c) for c in asyn_lpa_communities(g, weight=weight, seed=seed)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("asyn_lpa_communities failed: %s", exc)
            return []

    @staticmethod
    def girvan_newman(
        g: Any,
        most_valuable_edge: Optional[Any] = None,
    ) -> Iterator[Tuple[Set[Any], ...]]:
        """Yield successive community partitions from Girvan-Newman.

        Each iteration removes the highest-betweenness edge and yields
        the new connected-components partition as a tuple of sets.

        Args:
            g: Undirected graph.
            most_valuable_edge: Optional callable returning the next edge
                to remove (default: ``max(nx.edge_betweenness_centrality)``).

        Yields:
            Successive partitions (tuples of node-sets).
        """
        from networkx.algorithms.community import girvan_newman

        if g.number_of_nodes() == 0:
            return iter(())
        if g.is_directed():
            g = g.to_undirected()
        try:
            yield from girvan_newman(g, most_valuable_edge=most_valuable_edge)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("girvan_newman failed: %s", exc)

    @staticmethod
    def k_clique_communities(
        g: Any,
        k: int,
    ) -> List[Set[Any]]:
        """Detect k-clique percolation communities.

        Args:
            g: Undirected graph.
            k: Clique size to percolate.

        Returns:
            A list of node-sets.
        """
        from networkx.algorithms.community import k_clique_communities

        if g.number_of_nodes() == 0 or k < 2:
            return []
        if g.is_directed():
            g = g.to_undirected()
        try:
            return [set(c) for c in k_clique_communities(g, k)]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("k_clique_communities failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Quality measures
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_partition(
        communities: Union[List[Set[Any]], Dict[Any, int]],
    ) -> List[Set[Any]]:
        if isinstance(communities, dict):
            from collections import defaultdict

            groups: Dict[int, set] = defaultdict(set)
            for node, cid in communities.items():
                groups[int(cid)].add(node)
            return list(groups.values())
        return [set(c) for c in communities]

    @staticmethod
    def modularity(
        g: Any,
        communities: Union[List[Set[Any]], Dict[Any, int]],
        resolution: float = 1,
    ) -> float:
        """Compute the modularity Q of a partition.

        Args:
            g: Undirected graph (DiGraphs are converted).
            communities: Either a ``list[set]`` or ``{node: community_id}``.
            resolution: Modularity resolution parameter.

        Returns:
            A float in ``[-0.5, 1]`` (typically). ``0.0`` on error.
        """
        from networkx.algorithms.community import modularity

        if g.number_of_edges() == 0:
            return 0.0
        if g.is_directed():
            g = g.to_undirected()
        comms = CommunityDetection._normalize_partition(communities)
        try:
            return float(modularity(g, comms, resolution=resolution))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("modularity failed: %s", exc)
            return 0.0

    @staticmethod
    def partition_quality(
        g: Any,
        partition: Union[List[Set[Any]], Dict[Any, int]],
    ) -> Tuple[float, float]:
        """Return (coverage, performance) of a partition.

        Args:
            g: A networkx graph.
            partition: Either a ``list[set]`` or ``{node: community_id}``.

        Returns:
            ``(coverage, performance)`` — each in ``[0, 1]``.
        """
        from networkx.algorithms.community import partition_quality

        if g.number_of_nodes() == 0:
            return 0.0, 0.0
        comms = CommunityDetection._normalize_partition(partition)
        try:
            cov, perf = partition_quality(g, comms)
            return float(cov), float(perf)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("partition_quality failed: %s", exc)
            return 0.0, 0.0

    @staticmethod
    def community_density(
        g: Any,
        communities: Union[List[Set[Any]], Dict[Any, int]],
    ) -> List[float]:
        """Compute the internal edge density of each community.

        Args:
            g: A networkx graph.
            communities: Either a ``list[set]`` or ``{node: community_id}``.

        Returns:
            A list of densities — one per community, in input order.
        """
        import networkx as nx

        if g.number_of_nodes() == 0:
            return []
        comms = CommunityDetection._normalize_partition(communities)
        densities: List[float] = []
        for comm in comms:
            sub = g.subgraph(comm)
            n = sub.number_of_nodes()
            if n < 2:
                densities.append(0.0)
                continue
            densities.append(float(nx.density(sub)))
        return densities

    # ------------------------------------------------------------------
    # Cluster validity / partition comparison
    # ------------------------------------------------------------------
    @staticmethod
    def silhouette_score(
        g: Any,
        communities: Union[List[Set[Any]], Dict[Any, int]],
    ) -> float:
        """Compute the silhouette coefficient for a community partition.

        The graph is first embedded via spectral decomposition
        (top-``min(n_components, n_communities+5)`` eigenvectors of the
        normalised Laplacian) and scikit-learn's silhouette_score is
        computed on the resulting node vectors. Requires
        :mod:`scikit-learn` and :mod:`numpy`.

        Args:
            g: Undirected graph.
            communities: Partition (list-of-sets or {node: cid}).

        Returns:
            A float in ``[-1, 1]``. Returns ``0.0`` when scikit-learn
            is missing or when there are fewer than 2 communities.
        """
        comms = CommunityDetection._normalize_partition(communities)
        if len(comms) < 2:
            logger.debug("silhouette_score: need ≥ 2 communities — returning 0.")
            return 0.0
        try:
            import numpy as np
            from sklearn.metrics import silhouette_score as _sk_silhouette
        except Exception as exc:  # pragma: no cover - optional dep
            logger.warning("silhouette_score requires numpy + scikit-learn: %s", exc)
            return 0.0

        import networkx as nx

        if g.is_directed():
            g = g.to_undirected()
        # Map node -> cluster label.
        node_to_label: Dict[Any, int] = {}
        for cid, comm in enumerate(comms):
            for n in comm:
                node_to_label[n] = cid
        nodes = list(node_to_label.keys())
        if len(nodes) < 2:
            return 0.0
        sub = g.subgraph(nodes)
        n_clusters = len(comms)
        n_components = max(2, min(len(nodes) - 1, n_clusters + 5))
        try:
            embedding = nx.spectral_layout(sub, dim=n_components)
        except Exception:
            # Fall back to a random embedding if spectral fails.
            rng = np.random.default_rng(42)
            embedding = {n: rng.random(n_components) for n in nodes}
        X = np.array([embedding[n] for n in nodes])
        labels = np.array([node_to_label[n] for n in nodes])
        try:
            return float(_sk_silhouette(X, labels))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("silhouette_score computation failed: %s", exc)
            return 0.0

    @staticmethod
    def compare_communities(
        c1: Union[List[Set[Any]], Dict[Any, int]],
        c2: Union[List[Set[Any]], Dict[Any, int]],
        method: str = "nmi",
    ) -> float:
        """Compare two community partitions using a similarity metric.

        Args:
            c1: First partition (``list[set]`` or ``{node: cid}``).
            c2: Second partition.
            method: One of ``'nmi'`` (normalised mutual information,
                default), ``'ami'`` (adjusted mutual information),
                ``'ari'`` (adjusted Rand index), ``'vi'`` (variation
                of information).

        Returns:
            A similarity score. Higher = more similar for nmi/ami/ari
            (max 1); lower = more similar for ``'vi'`` (min 0).
        """
        method = method.lower().strip()
        if method not in {"nmi", "ami", "ari", "vi"}:
            raise ValueError(
                f"Unknown comparison method: {method!r}. "
                f"Expected nmi|ami|ari|vi."
            )
        c1_norm = CommunityDetection._normalize_partition(c1)
        c2_norm = CommunityDetection._normalize_partition(c2)
        # Build aligned node → label dicts.
        label1: Dict[Any, int] = {}
        label2: Dict[Any, int] = {}
        for cid, comm in enumerate(c1_norm):
            for n in comm:
                label1[n] = cid
        for cid, comm in enumerate(c2_norm):
            for n in comm:
                label2[n] = cid
        common = sorted(set(label1.keys()) & set(label2.keys()))
        if len(common) < 2:
            logger.debug("compare_communities: <2 common nodes — returning 0.")
            return 0.0
        l1 = [label1[n] for n in common]
        l2 = [label2[n] for n in common]

        if method == "vi":
            # Variation of information: H(X) + H(Y) - 2 I(X;Y).
            return float(CommunityDetection._variation_of_information(l1, l2))

        try:
            if method == "nmi":
                from sklearn.metrics import normalized_mutual_info_score
                return float(normalized_mutual_info_score(l1, l2))
            if method == "ami":
                from sklearn.metrics import adjusted_mutual_info_score
                return float(adjusted_mutual_info_score(l1, l2))
            if method == "ari":
                from sklearn.metrics import adjusted_rand_score
                return float(adjusted_rand_score(l1, l2))
        except Exception as exc:  # pragma: no cover - optional dep
            logger.warning("compare_communities(%s) requires scikit-learn: %s", method, exc)
            return 0.0
        return 0.0  # pragma: no cover - unreachable

    @staticmethod
    def _variation_of_information(labels1: List[int], labels2: List[int]) -> float:
        """Pure-Python VI implementation (no scikit-learn dependency)."""
        import math
        from collections import Counter

        n = len(labels1)
        if n == 0:
            return 0.0
        p1 = Counter(labels1)
        p2 = Counter(labels2)
        joint = Counter(zip(labels1, labels2))
        h1 = -sum((c / n) * math.log2(c / n) for c in p1.values())
        h2 = -sum((c / n) * math.log2(c / n) for c in p2.values())
        mi = sum(
            (c / n) * math.log2((c / n) / ((p1[a] / n) * (p2[b] / n)))
            for (a, b), c in joint.items()
            if c > 0 and p1[a] > 0 and p2[b] > 0
        )
        return float(h1 + h2 - 2 * mi)
