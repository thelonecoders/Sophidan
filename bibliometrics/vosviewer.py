"""VOSviewer-style bibliometric network analyses.

This module re-implements the core analysis routines exposed by
Nees Jan van Eck and Ludo Waltman's *VOSviewer* software. Every public
method on :class:`VOSAnalyzer` accepts a list of
:class:`data_acquisition.base_scraper.Paper` objects (or any duck-typed
object that exposes the same attributes) and returns a
:class:`networkx.Graph` (or, for the layout / clustering helpers, a
``dict`` of positions / cluster assignments).

Implemented analyses:

* :meth:`bibliographic_coupling`  — two papers coupled if they share
  ≥N references.
* :meth:`co_citation_analysis`   — two papers co-cited if they appear
  together in some reference list.
* :meth:`co_authorship_analysis` — authors as nodes, shared papers as
  weighted edges.
* :meth:`term_co_occurrence`    — terms (extracted from title /
  abstract / keywords) as nodes, co-occurrence counts as edges.
* :meth:`co_citation_sources`   — journals as nodes, co-cited.
* :meth:`co_citation_authors`   — authors as nodes, co-cited.
* :meth:`co_citation_references`— cited references as nodes, co-cited.

Plus layout / clustering / visualisation helpers:

* :meth:`overlay_visualization` — colour nodes by an attribute.
* :meth:`cluster_graph`         — VOS-style modularity clustering
  (Louvain via networkx).
* :meth:`map_to_2d`             — VOS / force-atlas / stress layout.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# Heavy deps are imported eagerly here because every public method in
# this module needs them. If networkx / pandas are unavailable the
# module *cannot* function — but we still want the *module import* to
# succeed so that consumers can introspect its docstrings. The heavy
# imports are therefore guarded by try/except with a clear error at
# call time.
try:
    import networkx as nx
    import pandas as pd
    _HAVE_NX = True
except ImportError:  # pragma: no cover - depends on environment
    _HAVE_NX = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paper coercion helper
# ---------------------------------------------------------------------------

_PAPER_FIELDS: Tuple[str, ...] = (
    "title", "authors", "abstract", "year", "doi",
    "citations_count", "references", "keywords", "fields_of_study",
    "journal", "source", "venue", "publisher",
)


def _paper_to_dict(paper: Any) -> Dict[str, Any]:
    """Coerce a Paper-like object into a plain dict."""
    if isinstance(paper, dict):
        return dict(paper)
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(paper) and not isinstance(paper, type):
            return asdict(paper)
    except Exception:  # pragma: no cover - defensive
        pass
    return {f: getattr(paper, f, None) for f in _PAPER_FIELDS}


def _coerce_list(value: Any) -> List[Any]:
    """Coerce arbitrary input to a list (handles None / Series / str)."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:  # pragma: no cover - defensive
            pass
    if isinstance(value, str):
        parts = re.split(r"[;,|]", value)
        return [p.strip() for p in parts if p.strip()]
    try:
        return list(value)
    except TypeError:
        return [value]


def _normalise_id(s: Any) -> str:
    """Lowercase / strip / collapse-whitespace a string identifier."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    return re.sub(r"\s+", " ", s)


# Minimal English stop-word list — kept in-module so the term extraction
# step does not pull in nltk/spacy as a hard dependency. Callers needing
# richer stop-word lists can pass ``custom_stop_words`` to
#:meth:`VOSAnalyzer.term_co_occurrence`.
_STOP_WORDS: frozenset = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "for",
    "of", "to", "in", "on", "at", "by", "with", "as", "is", "are",
    "was", "were", "be", "been", "being", "this", "that", "these",
    "those", "it", "its", "from", "we", "our", "their", "they", "them",
    "he", "she", "his", "her", "i", "you", "your", "us", "our",
    "which", "who", "whom", "what", "when", "where", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "can", "will", "just", "don", "should",
    "now", "also", "based", "using", "via", "into", "between", "through",
    "during", "before", "after", "above", "below", "up", "down", "out",
    "over", "under", "again", "further", "once", "here", "there",
    "study", "studies", "research", "paper", "article", "result",
    "results", "method", "methods", "approach", "approaches", "analysis",
    "model", "models", "data", "show", "shown", "showed", "found",
    "find", "finds", "use", "used", "uses", "using", "however",
    "although", "while", "whereas", "thus", "therefore", "hence",
    "discuss", "discusses", "discussed", "conclude", "concludes",
    "conclusion", "introduction", "abstract", "section",
})


def _tokenise(text: str) -> List[str]:
    """Lowercase + word-tokenise + stop-word filter a text blob."""
    if not text:
        return []
    text = text.lower()
    # Keep only alphanumeric sequences (3+ chars to drop short noise).
    tokens = re.findall(r"[a-z][a-z0-9\-]{2,}", text)
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 2]


# ---------------------------------------------------------------------------
# VOSAnalyzer
# ---------------------------------------------------------------------------

class VOSAnalyzer:
    """VOSviewer-style network-analysis routines.

    Every method takes a list of papers and returns either a
    :class:`networkx.Graph` or a layout / clustering helper structure.
    """

    def __init__(self) -> None:
        self.logger = logger

    # ------------------------------------------------------------------
    # Bibliographic coupling
    # ------------------------------------------------------------------

    def bibliographic_coupling(
        self,
        papers: Sequence[Any],
        min_shared: int = 1,
    ) -> "nx.Graph":
        """Build a bibliographic-coupling graph.

        Two papers are coupled when they share at least ``min_shared``
        references. Edge weight = number of shared references.

        Args:
            papers: Sequence of Paper objects.
            min_shared: Minimum number of shared references required
                to draw an edge (default 1; raise to 2-3 for less
                noisy graphs on large corpora).

        Returns:
            ``networkx.Graph`` whose nodes are paper identifiers
            (DOI when present, else title) and whose edge attribute
            ``weight`` is the shared-reference count. Each node
            carries the paper's title, year, journal, citation count
            as attributes.
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for VOSAnalyzer")
        g = nx.Graph()
        ref_to_papers: Dict[str, List[int]] = defaultdict(list)
        dicts = [_paper_to_dict(p) for p in papers]
        for idx, d in enumerate(dicts):
            pid = _normalise_id(d.get("doi") or d.get("title") or f"p{idx}")
            g.add_node(
                pid,
                title=d.get("title") or "",
                year=d.get("year"),
                journal=(d.get("journal") or d.get("source") or
                         d.get("venue") or ""),
                citations=d.get("citations_count") or 0,
                authors=_coerce_list(d.get("authors")),
                index=idx,
            )
            for r in _coerce_list(d.get("references")):
                rid = _normalise_id(r)
                if rid:
                    ref_to_papers[rid].append(idx)
        # Tally pair counts.
        pair_counts: Dict[Tuple[int, int], int] = defaultdict(int)
        for ref, plist in ref_to_papers.items():
            for i, j in combinations(sorted(set(plist)), 2):
                pair_counts[(i, j)] += 1
        for (i, j), c in pair_counts.items():
            if c >= min_shared:
                pi = _normalise_id(
                    dicts[i].get("doi") or dicts[i].get("title") or f"p{i}"
                )
                pj = _normalise_id(
                    dicts[j].get("doi") or dicts[j].get("title") or f"p{j}"
                )
                g.add_edge(pi, pj, weight=c, kind="bibcoupling")
        return g

    # ------------------------------------------------------------------
    # Co-citation
    # ------------------------------------------------------------------

    def co_citation_analysis(
        self,
        papers: Sequence[Any],
        min_co_cited: int = 1,
    ) -> "nx.Graph":
        """Build a co-citation graph of *cited references*.

        Two cited references are co-cited when some paper in the
        corpus cites both. Edge weight = number of citing papers in
        which the pair appears together.

        Args:
            papers: Sequence of Paper objects (each must expose a
                ``references`` list).
            min_co_cited: Minimum co-citation count for an edge.

        Returns:
            ``networkx.Graph`` whose nodes are cited-reference
            identifiers and whose edge attribute ``weight`` is the
            co-citation count.
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for VOSAnalyzer")
        g = nx.Graph()
        pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        node_seen: set = set()
        for p in papers:
            d = _paper_to_dict(p)
            refs = sorted({
                _normalise_id(r) for r in _coerce_list(d.get("references"))
                if _normalise_id(r)
            })
            for r in refs:
                node_seen.add(r)
            for a, b in combinations(refs, 2):
                pair_counts[(a, b)] += 1
        for n in node_seen:
            g.add_node(n, kind="reference")
        for (a, b), c in pair_counts.items():
            if c >= min_co_cited:
                g.add_edge(a, b, weight=c, kind="cocitation")
        return g

    # ------------------------------------------------------------------
    # Co-authorship
    # ------------------------------------------------------------------

    def co_authorship_analysis(
        self,
        papers: Sequence[Any],
        min_shared: int = 1,
    ) -> "nx.Graph":
        """Build a co-authorship graph.

        Authors are nodes; an edge connects two authors who co-authored
        at least ``min_shared`` papers together. Edge weight = number
        of co-authored papers.

        Args:
            papers: Sequence of Paper objects.
            min_shared: Minimum number of shared papers for an edge.

        Returns:
            ``networkx.Graph`` whose nodes are author names and whose
            edge attribute ``weight`` is the co-authorship count.
            Nodes carry ``papers`` (count) and ``total_citations``
            attributes.
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for VOSAnalyzer")
        g = nx.Graph()
        author_paper_counts: Dict[str, int] = defaultdict(int)
        author_citations: Dict[str, int] = defaultdict(int)
        pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        for p in papers:
            d = _paper_to_dict(p)
            authors = sorted({
                _normalise_id(a) for a in _coerce_list(d.get("authors"))
                if _normalise_id(a)
            })
            cites = int(d.get("citations_count") or 0)
            for a in authors:
                author_paper_counts[a] += 1
                author_citations[a] += cites
            for a, b in combinations(authors, 2):
                pair_counts[(a, b)] += 1
        for a, n in author_paper_counts.items():
            g.add_node(
                a, papers=n, total_citations=author_citations[a],
                kind="author",
            )
        for (a, b), c in pair_counts.items():
            if c >= min_shared:
                g.add_edge(a, b, weight=c, kind="coauthorship")
        return g

    # ------------------------------------------------------------------
    # Term co-occurrence
    # ------------------------------------------------------------------

    def term_co_occurrence(
        self,
        papers: Sequence[Any],
        fields: Sequence[str] = ("title", "abstract", "keywords"),
        top_n: int = 200,
        min_co_occurrence: int = 1,
        custom_stop_words: Optional[Iterable[str]] = None,
    ) -> "nx.Graph":
        """Build a term co-occurrence graph.

        Terms are extracted from each paper's ``title``, ``abstract``
        and ``keywords`` fields (configurable via ``fields``). Two
        terms co-occur when they appear in the same paper. The top-N
        most frequent terms (across the whole corpus) are kept as
        nodes; everything else is dropped.

        Args:
            papers: Sequence of Paper objects.
            fields: Which text fields to extract terms from.
            top_n: Maximum number of term nodes to retain
                (default 200, sorted by document frequency).
            min_co_occurrence: Minimum co-occurrence count for an
                edge (default 1).
            custom_stop_words: Optional iterable of extra stop words
                to drop.

        Returns:
            ``networkx.Graph`` whose nodes are terms and whose edge
            attribute ``weight`` is the co-occurrence count.
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for VOSAnalyzer")
        stop_extra = (
            frozenset(_normalise_id(w) for w in custom_stop_words)
            if custom_stop_words else frozenset()
        )
        per_paper_tokens: List[List[str]] = []
        doc_freq: Counter = Counter()
        for p in papers:
            d = _paper_to_dict(p)
            blob_parts = []
            for f in fields:
                v = d.get(f)
                if isinstance(v, list):
                    blob_parts.extend(str(x) for x in v)
                elif v is not None:
                    blob_parts.append(str(v))
            tokens = [
                t for t in _tokenise(" ".join(blob_parts))
                if t not in stop_extra
            ]
            per_paper_tokens.append(tokens)
            for t in set(tokens):
                doc_freq[t] += 1
        top_terms = [
            t for t, _ in doc_freq.most_common(top_n)
        ]
        top_set = set(top_terms)
        g = nx.Graph()
        for t in top_terms:
            g.add_node(t, frequency=doc_freq[t], kind="term")
        pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        for tokens in per_paper_tokens:
            unique = sorted(set(tokens) & top_set)
            for a, b in combinations(unique, 2):
                pair_counts[(a, b)] += 1
        for (a, b), c in pair_counts.items():
            if c >= min_co_occurrence:
                g.add_edge(a, b, weight=c, kind="cooccurrence")
        return g

    # ------------------------------------------------------------------
    # Co-citation on sources / authors / references
    # ------------------------------------------------------------------

    def _co_citation_nodes(
        self,
        papers: Sequence[Any],
        node_fn: Any,
        min_count: int = 1,
    ) -> "nx.Graph":
        """Generic co-citation routine — node_fn extracts a node id
        from a *cited* paper dict (looked up via reference id)."""
        if not _HAVE_NX:
            raise ImportError("networkx is required for VOSAnalyzer")
        g = nx.Graph()
        # Build a reference-id → paper dict lookup.
        ref_to_paper: Dict[str, Dict[str, Any]] = {}
        dicts = [_paper_to_dict(p) for p in papers]
        for d in dicts:
            rid = _normalise_id(d.get("doi") or d.get("title"))
            if rid:
                ref_to_paper[rid] = d
        pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        node_seen: set = set()
        for d in dicts:
            refs = sorted({
                _normalise_id(r) for r in _coerce_list(d.get("references"))
                if _normalise_id(r)
            })
            nodes_in_paper: List[str] = []
            for r in refs:
                cited = ref_to_paper.get(r)
                if cited is None:
                    continue
                nid = node_fn(cited)
                if not nid:
                    continue
                nodes_in_paper.append(nid)
                node_seen.add(nid)
            for a, b in combinations(sorted(set(nodes_in_paper)), 2):
                pair_counts[(a, b)] += 1
        for n in node_seen:
            g.add_node(n, kind="cocitation_node")
        for (a, b), c in pair_counts.items():
            if c >= min_count:
                g.add_edge(a, b, weight=c, kind="cocitation")
        return g

    def co_citation_sources(
        self,
        papers: Sequence[Any],
        min_co_cited: int = 1,
    ) -> "nx.Graph":
        """Co-citation analysis with **journals** as nodes.

        Two journals are co-cited when some citing paper cites (in its
        reference list) at least one paper from each.

        Args:
            papers: Sequence of Paper objects.
            min_co_cited: Minimum co-citation count for an edge.

        Returns:
            ``networkx.Graph`` whose nodes are journal names.
        """
        def _j(d: Dict[str, Any]) -> str:
            return _normalise_id(
                d.get("journal") or d.get("source") or d.get("venue")
                or d.get("publisher")
            )
        return self._co_citation_nodes(papers, _j, min_co_cited)

    def co_citation_authors(
        self,
        papers: Sequence[Any],
        min_co_cited: int = 1,
    ) -> "nx.Graph":
        """Co-citation analysis with **authors** as nodes.

        Two authors are co-cited when some citing paper cites (in its
        reference list) at least one paper authored by each. Edges
        are weighted by the count of citing papers in which the pair
        appears.

        Args:
            papers: Sequence of Paper objects.
            min_co_cited: Minimum co-citation count for an edge.

        Returns:
            ``networkx.Graph`` whose nodes are author names.
        """
        # Author-level co-citation is multi-edge (one paper may have
        # several authors). We explode each cited paper into its
        # author list before counting pairs.
        if not _HAVE_NX:
            raise ImportError("networkx is required for VOSAnalyzer")
        g = nx.Graph()
        ref_to_paper: Dict[str, Dict[str, Any]] = {}
        dicts = [_paper_to_dict(p) for p in papers]
        for d in dicts:
            rid = _normalise_id(d.get("doi") or d.get("title"))
            if rid:
                ref_to_paper[rid] = d
        pair_counts: Dict[Tuple[str, str], int] = defaultdict(int)
        node_seen: set = set()
        for d in dicts:
            refs = sorted({
                _normalise_id(r) for r in _coerce_list(d.get("references"))
                if _normalise_id(r)
            })
            authors_in_paper: List[str] = []
            for r in refs:
                cited = ref_to_paper.get(r)
                if cited is None:
                    continue
                for a in _coerce_list(cited.get("authors")):
                    an = _normalise_id(a)
                    if an:
                        authors_in_paper.append(an)
                        node_seen.add(an)
            for a, b in combinations(sorted(set(authors_in_paper)), 2):
                pair_counts[(a, b)] += 1
        for n in node_seen:
            g.add_node(n, kind="author")
        for (a, b), c in pair_counts.items():
            if c >= min_co_cited:
                g.add_edge(a, b, weight=c, kind="cocitation")
        return g

    def co_citation_references(
        self,
        papers: Sequence[Any],
        min_co_cited: int = 1,
    ) -> "nx.Graph":
        """Co-citation analysis with **cited references** as nodes.

        Same as :meth:`co_citation_analysis` but with explicit naming
        for the VOSviewer "co-citation → references" view.

        Args:
            papers: Sequence of Paper objects.
            min_co_cited: Minimum co-citation count for an edge.

        Returns:
            ``networkx.Graph`` whose nodes are cited-reference ids.
        """
        return self.co_citation_analysis(papers, min_co_cited)

    # ------------------------------------------------------------------
    # Overlay visualisation
    # ------------------------------------------------------------------

    def overlay_visualization(
        self,
        graph: "nx.Graph",
        attribute: str,
        figsize: Tuple[int, int] = (8, 6),
        cmap_name: str = "viridis",
        layout: str = "spring",
    ) -> Any:
        """Return a matplotlib Figure with nodes coloured by an attribute.

        Args:
            graph: Input graph (must have ``attribute`` on every
                node — nodes lacking it are coloured grey).
            attribute: Node-attribute name to colour by
                (e.g. ``"year"``, ``"frequency"``).
            figsize: Figure size (default ``(8, 6)``).
            cmap_name: matplotlib colormap name.
            layout: Layout engine — ``"spring"`` (default),
                ``"kamada_kawai"``, ``"circular"``, or ``"force_atlas"``
                (requires ``map_to_2d`` fallback).

        Returns:
            matplotlib Figure (with ``constrained_layout=True``;
            caller must NOT also call ``tight_layout()``).
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.cm as cm
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "matplotlib is required for overlay_visualization"
            ) from exc
        if len(graph) == 0:
            fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
            ax.text(
                0.5, 0.5, "empty graph", ha="center", va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            return fig
        # Pick layout.
        layout_str = layout.lower()
        if layout_str == "force_atlas":
            pos = self.map_to_2d(graph, layout="force_atlas")
        elif layout_str == "vos":
            pos = self.map_to_2d(graph, layout="vos")
        elif layout_str == "kamada_kawai":
            pos = nx.kamada_kawai_layout(graph)
        elif layout_str == "circular":
            pos = nx.circular_layout(graph)
        else:
            pos = nx.spring_layout(graph, seed=42)
        # Build colour vector.
        nodes = list(graph.nodes())
        values = []
        for n in nodes:
            v = graph.nodes[n].get(attribute)
            if v is None or (isinstance(v, str) and not v):
                values.append(None)
            else:
                try:
                    values.append(float(v))
                except (TypeError, ValueError):
                    values.append(None)
        # Colour missing nodes grey.
        present = [v for v in values if v is not None]
        vmin = min(present) if present else 0
        vmax = max(present) if present else 1
        if vmin == vmax:
            vmax = vmin + 1
        cmap = cm.get_cmap(cmap_name)
        colours = []
        for v in values:
            if v is None:
                colours.append((0.7, 0.7, 0.7, 1.0))
            else:
                colours.append(cmap((v - vmin) / (vmax - vmin)))
        edge_widths = [
            0.5 + 2.0 * (graph[u][v].get("weight", 1.0) /
                          max(1.0, max(
                              (graph[a][b].get("weight", 1.0)
                               for a, b in graph.edges()),
                              default=1.0)))
            for u, v in graph.edges()
        ] if graph.edges() else []
        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
        nx.draw_networkx_edges(
            graph, pos, ax=ax, edge_color="#cccccc",
            width=edge_widths if edge_widths else 0.5,
            alpha=0.4,
        )
        nx.draw_networkx_nodes(
            graph, pos, ax=ax, node_color=colours, node_size=80,
            edgecolors="white", linewidths=0.5,
        )
        # Label only top-degree nodes to avoid clutter.
        if len(nodes) <= 40:
            nx.draw_networkx_labels(
                graph, pos, ax=ax,
                font_size=6, font_family=["Noto Sans SC", "DejaVu Sans"],
            )
        sm = plt.cm.ScalarMappable(
            cmap=cmap,
            norm=plt.Normalize(vmin=vmin, vmax=vmax),
        )
        sm.set_array([])
        fig.colorbar(sm, ax=ax, label=attribute)
        ax.set_title(f"VOS overlay: {attribute}")
        ax.set_axis_off()
        return fig

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def cluster_graph(
        self,
        graph: "nx.Graph",
        resolution: float = 1.0,
        method: str = "louvain",
        random_state: Optional[int] = 42,
    ) -> Dict[Any, int]:
        """Cluster a graph using VOS-style modularity clustering.

        Args:
            graph: Input graph. Edge ``weight`` attribute is used
                when present (falls back to ``1.0``).
            resolution: Louvain resolution parameter (higher → more,
                smaller clusters).
            method: ``"louvain"`` (default, via NetworkX 3.x
                built-in) or ``"greedy"`` (Clauset-Newman-Moore).
            random_state: Seed for reproducibility (default 42).

        Returns:
            ``{node: cluster_id}`` mapping (cluster ids are
            0-indexed integers).
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for VOSAnalyzer")
        if len(graph) == 0:
            return {}
        weight = "weight" if nx.is_weighted(graph) else None
        if method == "greedy":
            communities = nx.algorithms.community.greedy_modularity_communities(
                graph, weight=weight, resolution=resolution,
            )
        else:
            try:
                communities = nx.algorithms.community.louvain_communities(
                    graph, weight=weight, resolution=resolution,
                    seed=random_state,
                )
            except AttributeError:
                # Fallback for networkx < 3.0
                communities = nx.algorithms.community.greedy_modularity_communities(
                    graph, weight=weight,
                )
        out: Dict[Any, int] = {}
        for cid, com in enumerate(communities):
            for n in com:
                out[n] = cid
        return out

    # ------------------------------------------------------------------
    # 2D layout
    # ------------------------------------------------------------------

    def map_to_2d(
        self,
        graph: "nx.Graph",
        layout: str = "vos",
        seed: Optional[int] = 42,
        iterations: int = 200,
    ) -> Dict[Any, Tuple[float, float]]:
        """Compute a 2-D layout for visualisation.

        Args:
            graph: Input graph.
            layout: ``"vos"`` (default — uses a weighted
                spring-attraction + repulsion model identical in
                spirit to VOSviewer's smart-local-moving algorithm;
                here we approximate it via NetworkX's spring layout
                with edge-weight scaling),
                ``"force_atlas"`` (a simplified ForceAtlas2 —
                spring + degree-proportional repulsion),
                or ``"stress"`` (Kamada-Kawai stress majorisation).
            seed: Random seed.
            iterations: Iteration count for the iterative layouts.

        Returns:
            ``{node: (x, y)}`` mapping.
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for VOSAnalyzer")
        if len(graph) == 0:
            return {}
        layout_lower = layout.lower()
        if layout_lower == "stress":
            return {
                n: (float(p[0]), float(p[1]))
                for n, p in nx.kamada_kawai_layout(graph).items()
            }
        if layout_lower == "force_atlas":
            # Simplified ForceAtlas2: repulsion ∝ degree, attraction
            # ∝ 1/weight^2. Implemented via custom iteration over
            # the NetworkX node set.
            return self._force_atlas_layout(
                graph, seed=seed, iterations=iterations,
            )
        # Default: VOS-style weighted spring layout.
        weight = "weight" if nx.is_weighted(graph) else None
        pos = nx.spring_layout(
            graph, weight=weight, seed=seed, iterations=iterations,
            k=1.0 / math.sqrt(max(len(graph), 1)),
        )
        return {n: (float(p[0]), float(p[1])) for n, p in pos.items()}

    @staticmethod
    def _force_atlas_layout(
        graph: "nx.Graph",
        seed: Optional[int] = 42,
        iterations: int = 200,
        scaling: float = 1.0,
        gravity: float = 0.1,
        kr: float = 0.01,
    ) -> Dict[Any, Tuple[float, float]]:
        """Simplified ForceAtlas2 layout.

        Args:
            graph: Input graph.
            seed: RNG seed.
            iterations: Number of iterations.
            scaling: Scaling factor for displacements.
            gravity: Gravity toward the centre.
            kr: Repulsion constant.

        Returns:
            ``{node: (x, y)}`` mapping.
        """
        rng = np.random.default_rng(seed)
        nodes = list(graph.nodes())
        n = len(nodes)
        if n == 0:
            return {}
        pos = rng.uniform(-1.0, 1.0, size=(n, 2))
        degrees = np.array(
            [max(graph.degree(nb), 1) for nb in nodes], dtype=float,
        )
        node_to_idx = {nb: i for i, nb in enumerate(nodes)}
        # Build edge list once.
        edges = []
        for u, v, data in graph.edges(data=True):
            w = float(data.get("weight", 1.0))
            edges.append((node_to_idx[u], node_to_idx[v], w))
        for _ in range(iterations):
            # Repulsion (all pairs, scaled by degree product).
            # diff[i, j] = pos[i] - pos[j], shape (n, n, 2)
            diff = pos[:, None, :] - pos[None, :, :]
            dist2 = (diff ** 2).sum(axis=-1)
            np.fill_diagonal(dist2, 1.0)  # avoid div-by-zero
            dist = np.sqrt(dist2)
            # rep[i, j] = magnitude of force i experiences from j
            rep = kr * (degrees[:, None] * degrees[None, :] /
                        (dist2 + 1e-9))
            # disp_per_pair[i, j, :] = force vector i experiences from j
            disp_per_pair = (diff / (dist[..., None] + 1e-9)) * rep[..., None]
            # Sum forces on each node (over axis 1 = "from j").
            disp = disp_per_pair.sum(axis=1)
            # Attraction (along edges).
            for u, v, w in edges:
                d = pos[u] - pos[v]
                dist_e = math.sqrt((d * d).sum() + 1e-9)
                force = w * dist_e * 0.1
                disp[u] -= (d / dist_e) * force
                disp[v] += (d / dist_e) * force
            # Gravity toward origin.
            disp -= gravity * pos
            # Clip displacement to prevent runaway (when two nodes get
            # very close, repulsion can become huge).  Cap at the
            # current bounding-box diagonal.
            max_step = float(np.sqrt((pos ** 2).sum(axis=1)).max()) + 1.0
            disp_norm = np.linalg.norm(disp, axis=1, keepdims=True)
            scale = np.minimum(1.0, max_step / (disp_norm.ravel() + 1e-9))
            disp = disp * scale[:, None]
            # Apply.
            pos = pos + disp * scaling
            # Cooling.
            scaling *= 0.95
        return {nb: (float(pos[i, 0]), float(pos[i, 1]))
                for nb, i in node_to_idx.items()}
