"""Directed citation network for academic papers.

The :class:`CitationGraph` builds a :class:`networkx.DiGraph` where an edge
``A → B`` means *A cites B*. It exposes the standard bibliometric
operations (top-cited papers, PageRank, HITS authority scores, h-index,
citation chains, co-citations and bibliographic coupling) and a
matplotlib / plotly visualization helper.

All public methods operate on the graph built by :meth:`build`; calling
them before :meth:`build` is a no-op returning empty containers.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Tuple

import networkx as nx

if TYPE_CHECKING:  # pragma: no cover - typing only
    from matplotlib.figure import Figure as MplFigure

# Reuse the duck-typed Paper helpers from the sibling network_analyzer.
# This keeps a single source of truth for paper attribute extraction.
try:
    from .network_analyzer import (
        _get_attr,
        _paper_affiliations,
        _paper_authors,
        _paper_id,
        _paper_refs,
        _paper_year,
    )
except ImportError:  # pragma: no cover - module used standalone
    # Fall back to a minimal re-implementation. Kept inline so this module
    # remains independently importable if the sibling is absent.
    def _get_attr(obj, name, default=None):  # type: ignore[no-redef]
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def _paper_id(paper):  # type: ignore[no-redef]
        for key in ("doi", "id", "openalex_id"):
            v = _get_attr(paper, key)
            if v:
                return str(v).strip()
        return (_get_attr(paper, "title") or "").strip()

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

    def _paper_refs(paper):  # type: ignore[no-redef]
        refs = _get_attr(paper, "references", []) or []
        out = []
        for r in refs:
            if r is None:
                continue
            s = str(r).replace("https://openalex.org/", "").strip()
            if s:
                out.append(s)
        return out

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


__all__ = ["CitationGraph"]

logger = logging.getLogger(__name__)


def _configure_matplotlib() -> None:
    """Apply the project-wide matplotlib font/unicode settings."""
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


class CitationGraph:
    """Build and analyze a directed citation network.

    The graph is stored as ``self.graph`` (a :class:`networkx.DiGraph`).
    Node identifiers are paper IDs (DOI preferred). Each node carries
    attributes ``title``, ``year``, ``doi`` and ``authors`` (list[str]).
    Edges ``A → B`` mean *A cites B* and carry an ``edge_type='citation'``
    attribute.
    """

    def __init__(self) -> None:
        """Initialize an empty citation graph."""
        self.graph: nx.DiGraph = nx.DiGraph()
        self._id_index: Dict[str, str] = {}
        self.logger = logging.getLogger(f"{__name__}.{type(self).__name__}")

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def build(self, papers: Sequence[Any]) -> nx.DiGraph:
        """Construct the directed citation graph from a list of papers.

        Each paper is added as a node identified by its canonical ID
        (DOI preferred — see :func:`_paper_id`). Directed edges
        ``A → B`` are added when paper A's ``references`` list contains
        a normalized identifier matching paper B's ID (or DOI). References
        that point to papers outside the input set are silently ignored
        (they would otherwise become leaf-less stubs).

        Args:
            papers: Sequence of ``Paper``-like objects.

        Returns:
            The constructed :class:`networkx.DiGraph`. Also stored on
            ``self.graph`` for subsequent method calls.
        """
        self.graph = nx.DiGraph()
        self._id_index = {}

        # First pass — add all paper nodes + build the id index.
        for paper in papers:
            pid = _paper_id(paper)
            if not pid:
                self.logger.debug("Skipping paper without identifier: %r", paper)
                continue
            if pid not in self.graph:
                self.graph.add_node(
                    pid,
                    type="paper",
                    title=(_get_attr(paper, "title") or "")[:200],
                    year=_paper_year(paper),
                    doi=_get_attr(paper, "doi"),
                    authors=_paper_authors(paper),
                )
            # Build a lookup so any reference form resolves to the canonical id.
            self._id_index[pid] = pid
            doi = _get_attr(paper, "doi")
            if doi:
                self._id_index[str(doi).strip()] = pid
            oa = _get_attr(paper, "openalex_id")
            if oa:
                self._id_index[str(oa).strip()] = pid

        # Second pass — add citation edges.
        n_edges = 0
        for paper in papers:
            src = _paper_id(paper)
            if not src:
                continue
            for ref in _paper_refs(paper):
                dst = self._id_index.get(ref)
                if dst and dst != src:
                    self.graph.add_edge(src, dst, edge_type="citation")
                    n_edges += 1

        self.logger.info(
            "Citation graph built: %d papers, %d citation edges.",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )
        return self.graph

    # ------------------------------------------------------------------
    # Ranking helpers
    # ------------------------------------------------------------------
    def top_cited(self, n: int = 20) -> List[Tuple[str, int]]:
        """Return the top ``n`` most-cited papers.

        Args:
            n: Number of top papers to return.

        Returns:
            A list of ``(paper_id, in_degree)`` tuples sorted descending by
            in-degree (citation count). Ties are broken by paper id.
        """
        items = [(node, deg) for node, deg in self.graph.in_degree() if deg > 0]
        items.sort(key=lambda x: (-x[1], str(x[0])))
        return items[:n]

    def top_citing(self, n: int = 20) -> List[Tuple[str, int]]:
        """Return the top ``n`` papers that cite the most others.

        Args:
            n: Number of top papers to return.

        Returns:
            A list of ``(paper_id, out_degree)`` tuples sorted descending by
            out-degree (reference count).
        """
        items = [(node, deg) for node, deg in self.graph.out_degree() if deg > 0]
        items.sort(key=lambda x: (-x[1], str(x[0])))
        return items[:n]

    # ------------------------------------------------------------------
    # h-index
    # ------------------------------------------------------------------
    def h_index(self, author: str) -> int:
        """Compute the Hirsch h-index of ``author`` from the citation graph.

        Walks the graph to find every paper authored by ``author`` (matching
        against the ``authors`` node attribute) and counts citations (in-degree)
        for each. The h-index is the largest h such that the author has h
        papers each receiving ≥ h citations.

        Args:
            author: Author name (must match an entry in the ``authors``
                node attribute exactly).

        Returns:
            The integer h-index. Returns ``0`` if the author has no papers.
        """
        citations: List[int] = []
        for node, data in self.graph.nodes(data=True):
            authors = data.get("authors") or []
            if author in authors:
                citations.append(self.graph.in_degree(node))
        if not citations:
            return 0
        citations.sort(reverse=True)
        h = 0
        for i, c in enumerate(citations, start=1):
            if c >= i:
                h = i
            else:
                break
        return h

    # ------------------------------------------------------------------
    # Chain / path traversal
    # ------------------------------------------------------------------
    def citation_chains(self, paper_id: str, depth: int = 3) -> List[List[str]]:
        """Enumerate all ancestor chains of ``paper_id`` up to ``depth`` hops.

        In a citation graph with edges ``A → B`` meaning *A cites B*, the
        ancestors of a paper are the works it (transitively) cites. A *chain*
        is a path ``[paper_id, …, ancestor]`` of length ≤ ``depth`` edges.

        Args:
            paper_id: Source paper identifier.
            depth: Maximum number of citation hops to follow.

        Returns:
            A list of paths (each a list of node ids). An empty list if
            ``paper_id`` is not in the graph or has no ancestors.
        """
        if paper_id not in self.graph:
            self.logger.debug("citation_chains: paper_id %r not in graph.", paper_id)
            return []
        if depth < 1:
            return []
        results: List[List[str]] = []

        def _dfs(node: str, path: List[str], remaining: int) -> None:
            if remaining == 0:
                return
            for child in self.graph.successors(node):  # outgoing = cited works
                new_path = path + [child]
                results.append(new_path)
                _dfs(child, new_path, remaining - 1)

        _dfs(paper_id, [paper_id], depth)
        return results

    def common_citations(self, a: str, b: str) -> Set[str]:
        """Papers that cite *both* ``a`` and ``b`` (co-citation).

        Args:
            a: First paper id.
            b: Second paper id.

        Returns:
            A set of paper ids (predecessors of both ``a`` and ``b``).
        """
        if a not in self.graph or b not in self.graph:
            return set()
        return set(self.graph.predecessors(a)) & set(self.graph.predecessors(b))

    def common_references(self, a: str, b: str) -> Set[str]:
        """Papers cited by *both* ``a`` and ``b`` (bibliographic coupling).

        Args:
            a: First paper id.
            b: Second paper id.

        Returns:
            A set of paper ids (successors of both ``a`` and ``b``).
        """
        if a not in self.graph or b not in self.graph:
            return set()
        return set(self.graph.successors(a)) & set(self.graph.successors(b))

    # ------------------------------------------------------------------
    # Global scores
    # ------------------------------------------------------------------
    def pagerank(self) -> Dict[str, float]:
        """PageRank scores over the citation graph.

        Returns:
            ``{paper_id: score}`` dict. Empty dict if the graph is empty.
        """
        if self.graph.number_of_nodes() == 0:
            return {}
        try:
            return dict(nx.pagerank(self.graph))
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("pagerank failed (%s); returning uniform.", exc)
            n = self.graph.number_of_nodes()
            return {node: 1.0 / n for node in self.graph.nodes()}

    def authority_scores(self) -> Dict[str, float]:
        """HITS authority scores (papers heavily *cited by* hubs).

        Returns:
            ``{paper_id: authority_score}`` dict. Empty dict if the graph
            is empty. If HITS fails to converge, returns uniform scores.
        """
        if self.graph.number_of_nodes() == 0:
            return {}
        try:
            _, authorities = nx.hits(self.graph, max_iter=1000)
            return dict(authorities)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("HITS failed (%s); returning uniform.", exc)
            n = self.graph.number_of_nodes()
            return {node: 1.0 / n for node in self.graph.nodes()}

    # ------------------------------------------------------------------
    # Topology queries
    # ------------------------------------------------------------------
    def find_orphan_papers(self) -> List[str]:
        """Return papers with no incoming AND no outgoing citation edges.

        Returns:
            List of paper ids that are completely isolated in the citation
            graph (neither cite nor cited-by any other node in the dataset).
        """
        return [
            node
            for node, deg in self.graph.degree()
            if deg == 0
        ]

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------
    def visualize(self, interactive: bool = False) -> Any:
        """Render the citation graph as a static or interactive figure.

        Args:
            interactive: When ``False`` (default), returns a
                :class:`matplotlib.figure.Figure` (spring layout, nodes
                colored by authority score, top-cited papers labeled).
                When ``True``, returns a :class:`plotly.graph_objects.Figure`
                with hover tooltips (requires ``plotly`` to be installed).

        Returns:
            A matplotlib Figure or a plotly Figure. For empty graphs the
            matplotlib figure is still returned (with a "no data" title).

        Raises:
            ImportError: If ``interactive=True`` and ``plotly`` is missing.
        """
        if interactive:
            return self._visualize_plotly()
        return self._visualize_matplotlib()

    def _visualize_matplotlib(self):
        import matplotlib.pyplot as plt
        import numpy as np

        _configure_matplotlib()
        G = self.graph
        fig, ax = plt.subplots(figsize=(10, 8), constrained_layout=True)
        if G.number_of_nodes() == 0:
            ax.set_title("Citation graph (no data)")
            ax.set_axis_off()
            return fig

        # Layout — spring for small graphs, kamada-kawai for medium.
        n_nodes = G.number_of_nodes()
        if n_nodes <= 200:
            pos = nx.spring_layout(G, seed=42, k=0.6)
        else:
            # Subsample to keep layout tractable.
            self.logger.info("Large graph (%d nodes) — using largest WCC for layout.", n_nodes)
            wccs = max(nx.weakly_connected_components(G), key=len)
            sub = G.subgraph(wccs)
            pos = nx.kamada_kawai_layout(sub.to_undirected())

        # Authority score → node color.
        auth = self.authority_scores()
        max_auth = max(auth.values()) if auth else 0.0
        in_deg = dict(G.in_degree())
        max_deg = max(in_deg.values()) if in_deg else 0

        node_color = [auth.get(n, 0.0) / max_auth if max_auth > 0 else 0.0 for n in pos]
        node_size = [
            50 + 250 * (in_deg.get(n, 0) / max_deg if max_deg > 0 else 0.0) for n in pos
        ]

        nodes = nx.draw_networkx_nodes(
            G, pos, ax=ax, node_color=node_color, node_size=node_size, cmap=plt.cm.viridis, alpha=0.85
        )
        nx.draw_networkx_edges(G, pos, ax=ax, arrows=True, alpha=0.25, edge_color="#666666")
        # Label the top-cited papers only — keeps the plot readable.
        top_ids = {pid for pid, _ in self.top_cited(n=10)}
        if top_ids:
            labels = {n: (G.nodes[n].get("title") or n)[:25] for n in pos if n in top_ids}
            nx.draw_networkx_labels(G, pos, labels=labels, ax=ax, font_size=7)
        ax.set_title(
            f"Citation graph — {G.number_of_nodes()} papers, {G.number_of_edges()} edges"
        )
        ax.set_axis_off()
        try:
            fig.colorbar(nodes, ax=ax, label="Authority score (normalized)")
        except Exception:  # pragma: no cover - colorbar can fail for single-value arrays
            pass
        return fig

    def _visualize_plotly(self):
        try:
            import plotly.graph_objects as go
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "plotly is required for interactive citation visualization."
            ) from exc

        G = self.graph
        if G.number_of_nodes() == 0:
            fig = go.Figure()
            fig.update_layout(title="Citation graph (no data)")
            return fig

        if G.number_of_nodes() <= 200:
            pos = nx.spring_layout(G, seed=42, k=0.6)
        else:
            wccs = max(nx.weakly_connected_components(G), key=len)
            sub = G.subgraph(wccs)
            pos = nx.kamada_kawai_layout(sub.to_undirected())

        auth = self.authority_scores()
        max_auth = max(auth.values()) if auth else 0.0
        in_deg = dict(G.in_degree())
        max_deg = max(in_deg.values()) if in_deg else 0

        node_x, node_y, node_text, node_size, node_color = [], [], [], [], []
        for n in pos:
            node_x.append(pos[n][0])
            node_y.append(pos[n][1])
            node_text.append(
                f"{(G.nodes[n].get('title') or n)[:60]}<br>in-degree: {in_deg.get(n, 0)}"
            )
            node_size.append(8 + 22 * (in_deg.get(n, 0) / max_deg if max_deg > 0 else 0))
            node_color.append(auth.get(n, 0.0) / max_auth if max_auth > 0 else 0.0)

        edge_x, edge_y = [], []
        for u, v in G.edges():
            if u in pos and v in pos:
                edge_x.extend([pos[u][0], pos[v][0], None])
                edge_y.extend([pos[u][1], pos[v][1], None])

        edge_trace = go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(width=0.5, color="#888"),
            hoverinfo="none",
        )
        node_trace = go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers",
            marker=dict(
                size=node_size,
                color=node_color,
                colorscale="Viridis",
                showscale=True,
                colorbar=dict(title="Authority"),
            ),
            text=node_text,
            hoverinfo="text",
        )
        fig = go.Figure(data=[edge_trace, node_trace])
        fig.update_layout(
            title=f"Citation graph — {G.number_of_nodes()} papers, {G.number_of_edges()} edges",
            showlegend=False,
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            plot_bgcolor="white",
        )
        return fig
