"""Unified graph builder and generic network-analysis metrics.

The :class:`NetworkAnalyzer` wraps :mod:`networkx` :class:`~networkx.Graph`
and :class:`~networkx.DiGraph` with academic-paper-aware helpers: it can
build a heterogeneous graph (papers + authors + citations) from a list of
``Paper``-like objects and exposes the canonical centrality / community /
topology metrics with consistent error handling and structured logging.

The class is intentionally lightweight: it holds no long-lived state other
than a logger, so a single instance can be reused across many graphs.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import json
import logging
import os
from itertools import combinations
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import networkx as nx

# ---------------------------------------------------------------------------
# Optional / heavy dependencies (imported lazily where used).
# ---------------------------------------------------------------------------
try:  # python-louvain (third-party) — optional, we fall back to nx built-in.
    import community as _community_louvain  # type: ignore[import]

    _HAS_PYTHON_LOUVAIN = True
except Exception:  # pragma: no cover - optional dep
    _community_louvain = None
    _HAS_PYTHON_LOUVAIN = False

try:  # leidenalg — optional, requires igraph
    import leidenalg as _leidenalg  # type: ignore[import]

    _HAS_LEIDEN = True
except Exception:  # pragma: no cover - optional dep
    _leidenalg = None
    _HAS_LEIDEN = False


__all__ = ["NetworkAnalyzer"]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Duck-typed Paper helpers
# ---------------------------------------------------------------------------
def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Return ``obj.<name>`` whether ``obj`` is an object or a dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _paper_id(paper: Any) -> str:
    """Pick the canonical node identifier for a paper.

    Preference order: ``doi`` → ``id`` → ``openalex_id`` → ``title`` (slug).
    Returns an empty string only if *every* source is missing.
    """
    doi = _get_attr(paper, "doi")
    if doi:
        return str(doi).strip()
    pid = _get_attr(paper, "id")
    if pid:
        return str(pid).strip()
    oa = _get_attr(paper, "openalex_id")
    if oa:
        return str(oa).strip()
    title = _get_attr(paper, "title") or ""
    return title.strip()


def _paper_authors(paper: Any) -> List[str]:
    """Normalize an author list to a list of bare name strings."""
    raw = _get_attr(paper, "authors", []) or []
    names: List[str] = []
    for a in raw:
        if a is None:
            continue
        if isinstance(a, str):
            n = a.strip()
        else:
            n = (_get_attr(a, "name") or _get_attr(a, "full_name") or "").strip()
        if n:
            names.append(n)
    return names


def _paper_year(paper: Any) -> Optional[int]:
    y = _get_attr(paper, "year")
    if y is None:
        y = _get_attr(paper, "publication_year")
    try:
        return int(y) if y is not None and str(y).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _paper_refs(paper: Any) -> List[str]:
    refs = _get_attr(paper, "references", []) or []
    out: List[str] = []
    for r in refs:
        if r is None:
            continue
        # OpenAlex URLs → ID
        s = str(r).replace("https://openalex.org/", "").strip()
        if s:
            out.append(s)
    return out


def _paper_affiliations(paper: Any) -> List[str]:
    aff = _get_attr(paper, "affiliations", []) or []
    out: List[str] = []
    for a in aff:
        if a is None:
            continue
        if isinstance(a, str):
            n = a.strip()
        else:
            n = (_get_attr(a, "name") or _get_attr(a, "institution") or "").strip()
        if n:
            out.append(n)
    return out


class NetworkAnalyzer:
    """Wrap networkx with academic-paper-aware graph construction + analysis.

    The analyzer is stateless beyond a logger; every public method takes the
    graph explicitly so the same instance can be reused on many graphs.
    """

    def __init__(self) -> None:
        """Initialize the analyzer (no heavy work, no I/O)."""
        self.logger = logging.getLogger(f"{__name__}.{type(self).__name__}")

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------
    def from_papers(self, papers: Sequence[Any]) -> nx.Graph:
        """Build a unified heterogeneous graph from a list of papers.

        The returned :class:`networkx.Graph` contains two kinds of nodes:

        - ``type == 'paper'``  — identifier is the paper DOI / id (see
          :func:`_paper_id`); attributes: ``title``, ``year``, ``doi``.
        - ``type == 'author'`` — identifier is the bare author name.

        And two kinds of edges:

        - ``type == 'authorship'``  — connects a paper to each of its authors.
        - ``type == 'citation'``   — connects two papers that cite each other
          (the directionality is lost in the unified undirected graph; use
          :class:`citation_graph.CitationGraph` for the directed version).

        Args:
            papers: Sequence of ``Paper``-like objects.

        Returns:
            A populated :class:`networkx.Graph`. Empty input yields an empty
            graph (never ``None``).
        """
        G = nx.Graph()
        n_papers = 0
        n_citation_edges = 0
        # Build a quick DOI/id → node_id index for citation edge resolution.
        id_index: Dict[str, str] = {}

        for paper in papers:
            pid = _paper_id(paper)
            if not pid:
                self.logger.debug("Skipping paper without identifier: %r", paper)
                continue
            # De-duplicate by canonical id.
            if pid not in G:
                G.add_node(
                    pid,
                    type="paper",
                    title=(_get_attr(paper, "title") or "")[:200],
                    year=_paper_year(paper),
                    doi=_get_attr(paper, "doi"),
                )
                id_index[pid] = pid
                if _get_attr(paper, "doi"):
                    id_index[str(_get_attr(paper, "doi")).strip()] = pid
                n_papers += 1

            # Authors.
            for author in _paper_authors(paper):
                if author not in G:
                    G.add_node(author, type="author")
                G.add_edge(pid, author, type="authorship")

        # Citations — second pass, once every paper is indexed.
        for paper in papers:
            src = _paper_id(paper)
            if not src:
                continue
            for ref in _paper_refs(paper):
                dst = id_index.get(ref)
                if dst and dst != src and not G.has_edge(src, dst):
                    G.add_edge(src, dst, type="citation")
                    n_citation_edges += 1

        self.logger.info(
            "Unified graph built: %d papers, %d citation edges, %d nodes total, %d edges total.",
            n_papers,
            n_citation_edges,
            G.number_of_nodes(),
            G.number_of_edges(),
        )
        return G

    # ------------------------------------------------------------------
    # Centrality
    # ------------------------------------------------------------------
    def compute_centrality(
        self,
        graph: nx.Graph,
        method: str = "degree",
    ) -> Dict[Any, float]:
        """Compute a node-centrality vector for ``graph``.

        Args:
            graph: A networkx :class:`Graph` or :class:`DiGraph`.
            method: One of ``'degree'``, ``'betweenness'``, ``'closeness'``,
                ``'pagerank'``, ``'eigenvector'``.

        Returns:
            A ``{node: score}`` dictionary.

        Raises:
            ValueError: If ``method`` is not one of the supported strings.
        """
        method = method.lower().strip()
        self.logger.debug("Computing centrality via %s on %d nodes.", method, graph.number_of_nodes())
        if graph.number_of_nodes() == 0:
            return {}
        try:
            if method == "degree":
                if graph.is_directed():
                    return dict(nx.in_degree_centrality(graph))
                return dict(nx.degree_centrality(graph))
            if method == "betweenness":
                return dict(nx.betweenness_centrality(graph, normalized=True))
            if method == "closeness":
                return dict(nx.closeness_centrality(graph))
            if method == "pagerank":
                return dict(nx.pagerank(graph))
            if method == "eigenvector":
                try:
                    return dict(nx.eigenvector_centrality(graph, max_iter=1000, tol=1e-06))
                except nx.PowerIterationFailedConvergence:
                    self.logger.warning(
                        "Eigenvector centrality did not converge — falling back to "
                        "degree centrality."
                    )
                    return dict(nx.degree_centrality(graph))
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("Centrality computation '%s' failed: %s", method, exc)
            raise
        raise ValueError(
            f"Unknown centrality method: {method!r}. "
            f"Expected one of degree|betweenness|closeness|pagerank|eigenvector."
        )

    # ------------------------------------------------------------------
    # Community detection
    # ------------------------------------------------------------------
    def detect_communities(
        self,
        graph: nx.Graph,
        method: str = "louvain",
    ) -> Dict[Any, int]:
        """Detect communities and return a node → community-id mapping.

        Args:
            graph: Undirected :class:`networkx.Graph`. Directed graphs are
                converted to undirected for community detection.
            method: ``'louvain'``, ``'leiden'``, or ``'girvan_newman'``.

                - ``'louvain'`` uses :func:`networkx.algorithms.community.
                  louvain_communities` (built-in for networkx ≥ 3.2).
                - ``'leiden'`` requires the optional ``leidenalg`` package
                  (with ``python-igraph``); if unavailable, falls back to
                  louvain with a warning.
                - ``'girvan_newman'`` is exact but expensive (O(E²·V)); the
                  first level of the dendrogram is returned.

        Returns:
            ``{node: community_index}`` mapping. Isolated nodes still receive
            a (singleton) community id.
        """
        method = method.lower().strip()
        if graph.is_directed():
            self.logger.info("Converting directed graph to undirected for community detection.")
            graph = graph.to_undirected()

        if graph.number_of_nodes() == 0:
            return {}

        if method == "louvain":
            return self._communities_louvain(graph)
        if method == "leiden":
            if not _HAS_LEIDEN:
                self.logger.warning(
                    "leidenalg not installed — falling back to built-in louvain "
                    "for community detection. Install 'leidenalg' and 'python-igraph' "
                    "to enable Leiden."
                )
                return self._communities_louvain(graph)
            return self._communities_leiden(graph)
        if method == "girvan_newman":
            return self._communities_girvan_newman(graph)
        raise ValueError(
            f"Unknown community method: {method!r}. "
            f"Expected one of louvain|leiden|girvan_newman."
        )

    def _communities_louvain(self, graph: nx.Graph) -> Dict[Any, int]:
        try:
            from networkx.algorithms.community import louvain_communities
        except ImportError as exc:  # pragma: no cover - nx < 3.2
            raise RuntimeError(
                "louvain_communities is unavailable in this networkx version."
            ) from exc
        comms = louvain_communities(graph, seed=42)
        return self._label_communities(comms, graph)

    def _communities_leiden(self, graph: nx.Graph) -> Dict[Any, int]:
        try:
            import igraph as ig  # type: ignore[import]
        except Exception as exc:  # pragma: no cover - optional dep
            raise RuntimeError("python-igraph is required for Leiden.") from exc
        nodes = list(graph.nodes())
        idx = {node: i for i, node in enumerate(nodes)}
        edges = [(idx[u], idx[v]) for u, v in graph.edges()]
        ig_graph = ig.Graph(n=len(nodes), edges=edges, directed=False)
        partition = _leidenalg.find_partition(
            ig_graph, _leidenalg.ModularityVertexPartition, seed=42
        )
        return {nodes[i]: int(membership) for i, membership in enumerate(partition.membership)}

    def _communities_girvan_newman(self, graph: nx.Graph) -> Dict[Any, int]:
        from networkx.algorithms.community import girvan_newman

        # Take the first non-trivial split (level 1 of the dendrogram).
        comms = next(girvan_newman(graph))
        return self._label_communities(list(comms), graph)

    @staticmethod
    def _label_communities(communities: List[set], graph: nx.Graph) -> Dict[Any, int]:
        labels: Dict[Any, int] = {}
        for cid, comm in enumerate(communities):
            for node in comm:
                labels[node] = cid
        # Singleton communities for any leftover isolated nodes.
        next_cid = len(communities)
        for node in graph.nodes():
            if node not in labels:
                labels[node] = next_cid
                next_cid += 1
        return labels

    # ------------------------------------------------------------------
    # Topology: bridges, articulation points, paths
    # ------------------------------------------------------------------
    def find_bridges(self, graph: nx.Graph) -> List[Tuple[Any, Any]]:
        """List bridge edges (removing them disconnects the graph).

        Args:
            graph: Undirected :class:`networkx.Graph`. Directed graphs are
                converted to undirected first.

        Returns:
            A list of ``(u, v)`` tuples.
        """
        if graph.is_directed():
            graph = graph.to_undirected()
        if graph.number_of_nodes() == 0:
            return []
        return list(nx.bridges(graph))

    def find_articulation_points(self, graph: nx.Graph) -> List[Any]:
        """List articulation points (cut vertices) whose removal disconnects.

        Args:
            graph: Undirected :class:`networkx.Graph`. Directed graphs are
                converted to undirected first.

        Returns:
            A list of nodes.
        """
        if graph.is_directed():
            graph = graph.to_undirected()
        if graph.number_of_nodes() == 0:
            return []
        return list(nx.articulation_points(graph))

    def shortest_path(
        self,
        graph: nx.Graph,
        src: Any,
        dst: Any,
    ) -> List[Any]:
        """Return the shortest path from ``src`` to ``dst``.

        Args:
            graph: A networkx graph.
            src: Source node identifier.
            dst: Destination node identifier.

        Returns:
            A list of nodes ``[src, …, dst]``. Returns an empty list if no
            path exists or either endpoint is missing.
        """
        if src not in graph or dst not in graph:
            self.logger.debug("shortest_path: missing endpoint (src=%r dst=%r).", src, dst)
            return []
        try:
            return nx.shortest_path(graph, source=src, target=dst)
        except nx.NetworkXNoPath:
            self.logger.debug("No path between %r and %r.", src, dst)
            return []

    def clustering_coefficient(self, graph: nx.Graph) -> float:
        """Average clustering coefficient of the graph.

        Args:
            graph: Undirected :class:`networkx.Graph`. Directed graphs are
                converted to undirected first.

        Returns:
            A float in ``[0, 1]``. Returns ``0.0`` for empty graphs.
        """
        if graph.is_directed():
            graph = graph.to_undirected()
        if graph.number_of_nodes() == 0:
            return 0.0
        return float(nx.average_clustering(graph))

    def small_world_coefficient(self, graph: nx.Graph, nrand: int = 10) -> float:
        """Compute the small-world coefficient *sigma*.

        ``sigma > 1`` indicates small-world structure (high clustering yet
        short path lengths compared with random graphs of the same size).

        For disconnected graphs the metric is computed on the largest
        connected component (the canonical small-world metrics require a
        connected graph).

        Args:
            graph: Undirected :class:`networkx.Graph`. Directed graphs are
                converted to undirected first.
            nrand: Number of random reference graphs used by networkx.

        Returns:
            The sigma coefficient. Returns ``0.0`` when the metric cannot be
            computed (graph too small, disconnected components, etc.).
        """
        if graph.is_directed():
            graph = graph.to_undirected()
        n = graph.number_of_nodes()
        if n < 4 or graph.number_of_edges() == 0:
            return 0.0
        # nx.sigma / nx.omega require a *connected* graph.
        if not nx.is_connected(graph):
            try:
                largest = max(nx.connected_components(graph), key=len)
                graph = graph.subgraph(largest).copy()
                self.logger.debug(
                    "Graph disconnected — computing small-world coefficient "
                    "on the largest connected component (%d nodes).",
                    graph.number_of_nodes(),
                )
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning("Could not extract largest component: %s", exc)
                return 0.0
        if graph.number_of_nodes() < 4 or graph.number_of_edges() == 0:
            return 0.0
        sigma_exc: Optional[Exception] = None
        try:
            return float(nx.sigma(graph, nrand=nrand))
        except Exception as exc:  # pragma: no cover - defensive
            sigma_exc = exc
            self.logger.debug("sigma() failed (%s); trying omega().", exc)
        try:
            return float(nx.omega(graph, nrand=nrand))
        except Exception as omega_exc:
            self.logger.warning(
                "Could not compute small-world coefficient (sigma=%s, omega=%s). "
                "Graph is probably too small or disconnected.",
                sigma_exc,
                omega_exc,
            )
            return 0.0

    # ------------------------------------------------------------------
    # Import / export
    # ------------------------------------------------------------------
    def export_to(
        self,
        graph: nx.Graph,
        format: str = "graphml",
    ) -> Union[str, bytes]:
        """Serialize ``graph`` to a supported external format.

        Args:
            graph: A networkx graph.
            format: One of ``'graphml'``, ``'gexf'``, ``'json'`` (node-link),
                ``'cytoscape'`` (Cytoscape.js JSON).

        Returns:
            ``str`` for textual formats (graphml, gexf, json, cytoscape).
            ``bytes`` is never returned by the current implementations, but
            the return type is declared as ``str | bytes`` for forward
            compatibility with future binary formats.

        Raises:
            ValueError: If ``format`` is unknown.
        """
        fmt = format.lower().strip()
        self.logger.debug("Exporting graph (%d nodes) to %s.", graph.number_of_nodes(), fmt)
        if fmt == "graphml":
            from io import BytesIO

            buf = BytesIO()
            nx.write_graphml(graph, buf)
            return buf.getvalue().decode("utf-8")
        if fmt == "gexf":
            from io import BytesIO

            buf = BytesIO()
            nx.write_gexf(graph, buf)
            return buf.getvalue().decode("utf-8")
        if fmt == "json":
            return json.dumps(nx.node_link_data(graph), default=str)
        if fmt == "cytoscape":
            return json.dumps(nx.cytoscape_data(graph), default=str)
        raise ValueError(
            f"Unknown export format: {format!r}. "
            f"Expected one of graphml|gexf|json|cytoscape."
        )

    def import_from(self, path: str) -> nx.Graph:
        """Import a graph from a file on disk.

        The format is inferred from the file extension:

        - ``.graphml`` or ``.xml`` → GraphML
        - ``.gexf``               → GEXF
        - ``.json``               → node-link JSON
        - ``.cyjs``               → Cytoscape.js JSON

        Args:
            path: Path to the graph file.

        Returns:
            A :class:`networkx.Graph` (or :class:`DiGraph` if the file
            declares directed edges).

        Raises:
            FileNotFoundError: If ``path`` does not exist.
            ValueError: If the extension is unsupported.
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"Graph file not found: {path}")
        ext = os.path.splitext(path)[1].lower()
        self.logger.info("Importing graph from %s (ext=%s).", path, ext)
        if ext in (".graphml", ".xml"):
            return nx.read_graphml(path)
        if ext == ".gexf":
            return nx.read_gexf(path)
        if ext == ".json":
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return nx.node_link_graph(data, directed=False, multigraph=False)
        if ext == ".cyjs":
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return nx.cytoscape_graph(data)
        raise ValueError(f"Unsupported graph extension: {ext!r} (path={path!r}).")
