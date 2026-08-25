"""Co-authorship (collaboration) network for academic papers.

The :class:`CollaborationGraph` builds an undirected weighted graph where
nodes are authors and edge weights count the number of joint publications.
Internally the graph is built as a bipartite author↔paper projection
(via :func:`networkx.algorithms.bipartite.projection.collaboration_weighted_projected_graph`
when available), with year / affiliation metadata attached for downstream
queries (emerging collaborations, inter-institutional edges, etc.).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from itertools import combinations
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

import networkx as nx

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd
    from matplotlib.figure import Figure as MplFigure

# Duck-typed Paper helpers (re-used from the sibling module).
try:
    from .network_analyzer import (
        _get_attr,
        _paper_affiliations,
        _paper_authors,
        _paper_id,
        _paper_refs,
        _paper_year,
    )
except ImportError:  # pragma: no cover - standalone fallback
    def _get_attr(obj, name, default=None):  # type: ignore[no-redef]
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def _paper_authors(paper):  # type: ignore[no-redef]
        raw = _get_attr(paper, "authors", []) or []
        out = []
        for a in raw:
            if isinstance(a, str):
                n = a.strip()
            else:
                n = (_get_attr(a, "name") or _get_attr(a, "full_name") or "").strip()
            if n:
                out.append(n)
        return out

    def _paper_year(paper):  # type: ignore[no-redef]
        y = _get_attr(paper, "year") or _get_attr(paper, "publication_year")
        try:
            return int(y) if y is not None and str(y).strip() != "" else None
        except (TypeError, ValueError):
            return None

    def _paper_id(paper):  # type: ignore[no-redef]
        for key in ("doi", "id", "openalex_id"):
            v = _get_attr(paper, key)
            if v:
                return str(v).strip()
        return (_get_attr(paper, "title") or "").strip()

    def _paper_affiliations(paper):  # type: ignore[no-redef]
        aff = _get_attr(paper, "affiliations", []) or []
        out = []
        for a in aff:
            if isinstance(a, str):
                n = a.strip()
            else:
                n = (_get_attr(a, "name") or _get_attr(a, "institution") or "").strip()
            if n:
                out.append(n)
        return out

    def _paper_refs(paper):  # type: ignore[no-redef]
        return []


__all__ = ["CollaborationGraph"]

logger = logging.getLogger(__name__)


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib font/unicode settings."""
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


class CollaborationGraph:
    """Co-authorship network with bipartite projection + bibliometric helpers.

    The graph is undirected and weighted. Each author node carries:

    - ``papers``  : list[str]   — ids of papers they authored.
    - ``years``   : list[int]   — publication years.
    - ``affiliations`` : list[str] — union of their affiliation strings.

    Each edge ``(a, b)`` carries:

    - ``weight``   : int — number of shared papers (collaboration strength).
    - ``years``    : list[int] — years of joint papers (sorted).
    - ``papers``   : list[str] — ids of shared papers.
    - ``aff_a`` / ``aff_b`` : affiliation of endpoint a / b at the time of the
      first shared paper (only present when affiliation metadata is supplied).
    """

    def __init__(self) -> None:
        """Initialize an empty collaboration graph."""
        self.graph: nx.Graph = nx.Graph()
        # Side index of {author: list[(paper_id, year, affiliations)]} kept
        # for the affiliation-aware / temporal queries.
        self._author_history: Dict[str, List[Tuple[str, Optional[int], List[str]]]] = {}
        # Paper metadata (id → {year, title, affiliations}) used by edges.
        self._paper_meta: Dict[str, Dict[str, Any]] = {}
        self.logger = logging.getLogger(f"{__name__}.{type(self).__name__}")

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def build(self, papers: Sequence[Any]) -> nx.Graph:
        """Build the co-authorship graph from a list of papers.

        Uses the *bipartite* author↔paper construction: every paper becomes
        a temporary node, every author becomes a node, an author-paper edge
        is added for authorship, then the author side is projected to a
        weighted co-authorship graph (edge weight = # of shared papers).
        Year and affiliation metadata is propagated to edges and nodes.

        Args:
            papers: Sequence of ``Paper``-like objects.

        Returns:
            The weighted :class:`networkx.Graph`. Also stored on
            ``self.graph``.
        """
        # --- 1. Build bipartite graph (paper + author nodes) ---
        B = nx.Graph()
        self._author_history = {}
        self._paper_meta = {}

        for paper in papers:
            pid = _paper_id(paper)
            if not pid:
                self.logger.debug("Skipping paper without identifier.")
                continue
            year = _paper_year(paper)
            authors = _paper_authors(paper)
            affs = _paper_affiliations(paper)
            self._paper_meta[pid] = {
                "year": year,
                "title": (_get_attr(paper, "title") or "")[:200],
                "affiliations": affs,
            }
            # Paper node (bipartite set 0).
            if pid not in B:
                B.add_node(pid, bipartite=0, year=year, title=self._paper_meta[pid]["title"])
            else:
                # Update year if missing.
                if B.nodes[pid].get("year") is None:
                    B.nodes[pid]["year"] = year
            for author in authors:
                if author not in B:
                    B.add_node(
                        author,
                        bipartite=1,
                        papers=[],
                        years=[],
                        affiliations=set(),
                    )
                B.add_edge(author, pid, type="authorship")
                self._author_history.setdefault(author, []).append((pid, year, affs))
                B.nodes[author]["papers"].append(pid)
                if year is not None:
                    B.nodes[author]["years"].append(year)
                B.nodes[author]["affiliations"].update(affs)

        # --- 2. Project to author–author collaboration graph ---
        try:
            from networkx.algorithms.bipartite import (
                collaboration_weighted_projected_graph,
            )

            author_nodes = {n for n, d in B.nodes(data=True) if d.get("bipartite") == 1}
            G = collaboration_weighted_projected_graph(B, author_nodes)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning(
                "Bipartite projection failed (%s); using manual projection.", exc
            )
            G = self._manual_projection(B)

        # --- 3. Enrich edges with year / paper-id metadata ---
        # Clear default empty attrs and re-add metadata we control.
        for u, v, data in G.edges(data=True):
            shared_papers = self._shared_papers(B, u, v)
            shared_years = sorted(
                {
                    self._paper_meta[p]["year"]
                    for p in shared_papers
                    if p in self._paper_meta and self._paper_meta[p]["year"] is not None
                }
            )
            data["weight"] = len(shared_papers) or data.get("weight", 1)
            data["papers"] = shared_papers
            data["years"] = shared_years
            if shared_papers and shared_papers[0] in self._paper_meta:
                affs = self._paper_meta[shared_papers[0]].get("affiliations", [])
                if affs:
                    data["aff_a"] = self._author_affiliation_for(u, shared_papers[0])
                    data["aff_b"] = self._author_affiliation_for(v, shared_papers[0])

        # --- 4. Propagate author node attributes ---
        for node, bdata in B.nodes(data=True):
            if bdata.get("bipartite") != 1:
                continue
            if node in G:
                G.nodes[node]["papers"] = bdata.get("papers", [])
                G.nodes[node]["years"] = sorted(set(bdata.get("years", [])))
                G.nodes[node]["affiliations"] = sorted(bdata.get("affiliations", set()))

        self.graph = G
        self.logger.info(
            "Collaboration graph built: %d authors, %d edges.",
            G.number_of_nodes(),
            G.number_of_edges(),
        )
        return G

    @staticmethod
    def _manual_projection(B: nx.Graph) -> nx.Graph:
        """Fallback O(p · k²) projection when the bipartite helper is absent."""
        G = nx.Graph()
        for paper in {n for n, d in B.nodes(data=True) if d.get("bipartite") == 0}:
            authors = list(B.neighbors(paper))
            for a in authors:
                if a not in G:
                    G.add_node(a)
            for a, b in combinations(authors, 2):
                if G.has_edge(a, b):
                    G[a][b]["weight"] += 1
                else:
                    G.add_edge(a, b, weight=1)
        return G

    @staticmethod
    def _shared_papers(B: nx.Graph, a: str, b: str) -> List[str]:
        """Papers co-authored by ``a`` and ``b`` in the bipartite graph."""
        if a not in B or b not in B:
            return []
        return list(set(B.neighbors(a)) & set(B.neighbors(b)))

    def _author_affiliation_for(self, author: str, paper_id: str) -> Optional[str]:
        """Return the affiliation of ``author`` on ``paper_id`` if known."""
        for pid, _year, affs in self._author_history.get(author, []):
            if pid == paper_id and affs:
                return affs[0]
        return None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def top_collaborators(self, author: str, n: int = 10) -> List[Tuple[str, int]]:
        """Return the top ``n`` collaborators of ``author`` by # shared papers.

        Args:
            author: Author name.
            n: Number of top collaborators to return.

        Returns:
            Sorted list of ``(collaborator, weight)`` tuples. Empty list if
            ``author`` is unknown or has no collaborators.
        """
        if author not in self.graph:
            return []
        items = [
            (nb, data.get("weight", 1))
            for nb, data in self.graph[author].items()
        ]
        items.sort(key=lambda x: (-x[1], str(x[0])))
        return items[:n]

    def shortest_academic_distance(self, a: str, b: str) -> List[str]:
        """Erdős-style shortest collaboration path between two authors.

        Args:
            a: First author name.
            b: Second author name.

        Returns:
            A list ``[a, …, b]`` of author names. Empty list if either is
            unknown, or if they are not connected in the collaboration graph.
        """
        if a not in self.graph or b not in self.graph:
            self.logger.debug("shortest_academic_distance: missing endpoint(s).")
            return []
        try:
            return nx.shortest_path(self.graph, source=a, target=b)
        except nx.NetworkXNoPath:
            return []

    def community_detection(self, method: str = "louvain") -> Dict[str, int]:
        """Detect research groups (communities) in the collaboration graph.

        Args:
            method: Currently only ``'louvain'`` is supported (built-in
                networkx implementation). Unknown methods raise
                :class:`ValueError`.

        Returns:
            ``{author: community_id}`` mapping.
        """
        method = method.lower().strip()
        if method != "louvain":
            raise ValueError(f"Unsupported community method: {method!r}. Only 'louvain' supported.")
        if self.graph.number_of_nodes() == 0:
            return {}
        try:
            from networkx.algorithms.community import louvain_communities
        except ImportError as exc:  # pragma: no cover - nx < 3.2
            raise RuntimeError("louvain_communities requires networkx >= 3.2.") from exc
        comms = louvain_communities(self.graph, seed=42)
        labels: Dict[str, int] = {}
        for cid, comm in enumerate(comms):
            for node in comm:
                labels[node] = cid
        # Isolated nodes.
        next_cid = len(comms)
        for node in self.graph.nodes():
            if node not in labels:
                labels[node] = next_cid
                next_cid += 1
        return labels

    def collaboration_strength(self, a: str, b: str) -> int:
        """Number of shared papers between authors ``a`` and ``b``.

        Args:
            a: First author.
            b: Second author.

        Returns:
            The integer edge weight (0 if they have never co-authored).
        """
        if self.graph.has_edge(a, b):
            return int(self.graph[a][b].get("weight", 1))
        return 0

    def emerging_collaborations(self, year_threshold: int = 2020) -> List[Tuple[str, str, int]]:
        """Find co-author pairs whose first joint paper is at/after a year.

        Useful for spotting newly-formed research relationships.

        Args:
            year_threshold: Cutoff year (inclusive). Only edges whose first
                observed joint publication year is ≥ this value are returned.

        Returns:
            A list of ``(author_a, author_b, first_year)`` tuples sorted by
            ``first_year`` ascending.
        """
        out: List[Tuple[str, str, int]] = []
        for u, v, data in self.graph.edges(data=True):
            years = data.get("years") or []
            if not years:
                continue
            first_year = min(years)
            if first_year >= year_threshold:
                out.append((u, v, first_year))
        out.sort(key=lambda x: (x[2], str(x[0])))
        return out

    def author_centralities(self) -> "pd.DataFrame":
        """Compute per-author centrality metrics as a pandas DataFrame.

        Columns: ``author``, ``degree``, ``weighted_degree``,
        ``betweenness``, ``closeness``, ``eigenvector``, ``papers``,
        ``first_year``, ``last_year``.

        Returns:
            A :class:`pandas.DataFrame` with one row per author.
        """
        import pandas as pd

        G = self.graph
        rows: List[Dict[str, Any]] = []
        if G.number_of_nodes() == 0:
            return pd.DataFrame(
                columns=[
                    "author",
                    "degree",
                    "weighted_degree",
                    "betweenness",
                    "closeness",
                    "eigenvector",
                    "papers",
                    "first_year",
                    "last_year",
                ]
            )
        betw = nx.betweenness_centrality(G, normalized=True, weight="weight")
        close = nx.closeness_centrality(G)
        try:
            eigen = nx.eigenvector_centrality(G, max_iter=1000, tol=1e-06, weight="weight")
        except Exception:  # pragma: no cover - defensive
            eigen = {n: 0.0 for n in G.nodes()}
        for node in G.nodes():
            data = G.nodes[node]
            years = data.get("years") or []
            rows.append(
                {
                    "author": node,
                    "degree": G.degree(node),
                    "weighted_degree": G.degree(node, weight="weight"),
                    "betweenness": float(betw.get(node, 0.0)),
                    "closeness": float(close.get(node, 0.0)),
                    "eigenvector": float(eigen.get(node, 0.0)),
                    "papers": len(data.get("papers", [])),
                    "first_year": min(years) if years else None,
                    "last_year": max(years) if years else None,
                }
            )
        return pd.DataFrame(rows)

    def inter_institutional_edges(self) -> List[Tuple[str, str, str, str]]:
        """List collaboration edges that span different institutions.

        Requires affiliation metadata on at least the first shared paper
        of each edge (populated by :meth:`build` from ``Paper.affiliations``).

        Returns:
            A list of ``(author_a, author_b, aff_a, aff_b)`` tuples where
            ``aff_a != aff_b`` (both non-empty). Edges without affiliation
            metadata are skipped.
        """
        out: List[Tuple[str, str, str, str]] = []
        for u, v, data in self.graph.edges(data=True):
            aff_a = data.get("aff_a")
            aff_b = data.get("aff_b")
            if not aff_a or not aff_b or aff_a == aff_b:
                continue
            out.append((u, v, aff_a, aff_b))
        return out

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------
    def visualize(self, max_nodes: int = 200) -> "MplFigure":
        """Render the collaboration graph as a matplotlib figure.

        Node size ∝ degree, edge width ∝ weight, node color encodes the
        detected community.

        Args:
            max_nodes: For very large graphs, only the top ``max_nodes`` by
                degree are drawn (the rest are dropped to keep the layout
                tractable). Set to a large number to disable.

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt

        _configure_matplotlib()
        G = self.graph
        if G.number_of_nodes() == 0:
            fig, ax = plt.subplots(figsize=(10, 8), constrained_layout=True)
            ax.set_title("Collaboration graph (no data)")
            ax.set_axis_off()
            return fig

        # Subsample by degree for visualization tractability.
        if G.number_of_nodes() > max_nodes:
            top = sorted(G.degree(), key=lambda x: -x[1])[:max_nodes]
            keep = {n for n, _ in top}
            G = G.subgraph(keep).copy()
            self.logger.info(
                "Subsampled collaboration graph to %d highest-degree nodes for visualization.",
                max_nodes,
            )

        # Layout — spring with weights to push strong collaborators together.
        pos = nx.spring_layout(G, seed=42, k=0.6, weight="weight")

        # Communities → colors.
        try:
            comm = self.community_detection(method="louvain")
            n_communities = max(comm.values()) + 1 if comm else 1
            cmap = plt.cm.get_cmap("tab20", max(n_communities, 1))
            colors = [cmap(comm.get(n, 0)) for n in G.nodes()]
        except Exception:  # pragma: no cover - defensive
            colors = "#4c78a8"

        degrees = dict(G.degree(weight="weight"))
        max_deg = max(degrees.values()) if degrees else 1
        # Avoid division by zero for graphs whose edges all have weight 0.
        safe_max = max_deg if max_deg > 0 else 1
        node_sizes = [60 + 600 * (d / safe_max) for d in degrees.values()]
        weights = [G[u][v].get("weight", 1) for u, v in G.edges()]
        max_w = max(weights) if weights else 1
        safe_max_w = max_w if max_w > 0 else 1
        edge_widths = [0.5 + 2.5 * (w / safe_max_w) for w in weights]

        fig, ax = plt.subplots(figsize=(11, 9), constrained_layout=True)
        nx.draw_networkx_edges(G, pos, ax=ax, width=edge_widths, alpha=0.35, edge_color="#888888")
        nx.draw_networkx_nodes(
            G, pos, ax=ax, node_size=node_sizes, node_color=colors, alpha=0.85, linewidths=0.5
        )
        # Label only the highest-degree authors.
        top_labels = {n: n for n, _ in sorted(G.degree(weight="weight"), key=lambda x: -x[1])[:20]}
        nx.draw_networkx_labels(G, pos, labels=top_labels, ax=ax, font_size=7)
        ax.set_title(
            f"Collaboration graph — {self.graph.number_of_nodes()} authors, "
            f"{self.graph.number_of_edges()} edges"
        )
        ax.set_axis_off()
        return fig
