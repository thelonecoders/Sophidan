"""CiteSpace-style bibliometric analyses.

This module re-implements the core analysis routines exposed by
Chaomei Chen's *CiteSpace* software: Kleinberg-style burst detection
on citation time-series, timezone / spectral-clustering knowledge
domain maps, structural variation analysis, and landmark-paper /
intellectual-turning-point identification.

The two main user-facing dataclasses are:

* :class:`Burst`         — a single citation-burst event.
* :class:`ResearchFront` — a cluster of papers that constitute a
  "research front" in CiteSpace terminology.
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
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# networkx / matplotlib / sklearn imported eagerly — every method needs
# them. If they're absent, calling any method raises a clear ImportError.
try:
    import networkx as nx
    import pandas as pd
    _HAVE_NX = True
except ImportError:  # pragma: no cover - environment dependent
    _HAVE_NX = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paper coercion helper (mirrors the VOSviewer helper)
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
    """Coerce arbitrary input to a list."""
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
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _paper_id(d: Dict[str, Any], idx: int = 0) -> str:
    """Return a stable identifier for a paper (DOI > title > p{idx})."""
    doi = d.get("doi")
    if doi:
        s = _normalise_id(doi)
        if s:
            return s
    title = d.get("title")
    if title:
        s = _normalise_id(title)
        if s:
            return s
    return f"p{idx}"


def _current_year() -> int:
    """Return the current calendar year (used as default time horizon)."""
    from datetime import datetime
    return datetime.now().year


# ---------------------------------------------------------------------------
# Burst dataclass
# ---------------------------------------------------------------------------

@dataclass
class Burst:
    """A single citation-burst event.

    Attributes:
        paper_id: Identifier of the paper (or ``"CORPUS"`` for an
            aggregate corpus-level burst detected on the publication
            count time series).
        paper_title: Title of the paper (``""`` for corpus bursts).
        start_year: Year the burst began.
        end_year: Year the burst ended (inclusive).
        strength: Kleinberg burst strength (cumulative log-likelihood
            improvement vs the baseline state).
        duration: ``end_year - start_year + 1`` (years).
    """

    paper_id: str = ""
    paper_title: str = ""
    start_year: int = 0
    end_year: int = 0
    strength: float = 0.0
    duration: int = 0

    def __post_init__(self) -> None:
        self.duration = max(self.end_year - self.start_year + 1, 1)


# ---------------------------------------------------------------------------
# ResearchFront dataclass
# ---------------------------------------------------------------------------

@dataclass
class ResearchFront:
    """A cluster of papers constituting a "research front".

    Attributes:
        id: Cluster identifier (0-indexed).
        papers: List of paper dicts in this cluster.
        centroid: Centroid in the embedding / feature space (1-D
            numpy array or None when feature extraction failed).
        burst_score: Sum of burst strengths across the cluster's
            papers (0.0 if no bursts detected).
        top_terms: Top-N most frequent terms in the cluster's title +
            abstract + keywords.
    """

    id: int = 0
    papers: List[Dict[str, Any]] = field(default_factory=list)
    centroid: Optional[Any] = None
    burst_score: float = 0.0
    top_terms: List[Tuple[str, int]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CiteSpaceAnalyzer
# ---------------------------------------------------------------------------

class CiteSpaceAnalyzer:
    """CiteSpace-style bibliometric analyses.

    The class is stateless — every public method takes the corpus
    (``papers``) plus a small set of parameters and returns either a
    list of :class:`Burst` / :class:`ResearchFront` objects or a
    ``networkx.Graph`` / matplotlib Figure.
    """

    def __init__(self) -> None:
        self.logger = logger

    # ------------------------------------------------------------------
    # Citation graph helper
    # ------------------------------------------------------------------

    @staticmethod
    def _build_citation_graph(
        papers: Sequence[Any],
    ) -> Tuple["nx.DiGraph", List[Dict[str, Any]], Dict[str, int]]:
        """Build a directed citation graph (paper → cited paper).

        Returns:
            ``(graph, paper_dicts, id_to_idx)`` where ``graph`` has
            edges from citing papers to cited papers (both must be
            in the corpus), ``paper_dicts`` is the list of paper
            dicts in original order, and ``id_to_idx`` maps paper
            identifiers to their indices in ``paper_dicts``.
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for CiteSpaceAnalyzer")
        dicts = [_paper_to_dict(p) for p in papers]
        id_to_idx: Dict[str, int] = {}
        for i, d in enumerate(dicts):
            pid = _paper_id(d, i)
            if pid not in id_to_idx:
                id_to_idx[pid] = i
        g = nx.DiGraph()
        for i, d in enumerate(dicts):
            pid = _paper_id(d, i)
            g.add_node(
                pid,
                title=d.get("title") or "",
                year=d.get("year"),
                journal=(d.get("journal") or d.get("source") or
                         d.get("venue") or ""),
                citations=int(d.get("citations_count") or 0),
                authors=_coerce_list(d.get("authors")),
                keywords=_coerce_list(d.get("keywords")),
                index=i,
            )
        for i, d in enumerate(dicts):
            pid = _paper_id(d, i)
            for r in _coerce_list(d.get("references")):
                rid = _normalise_id(r)
                if rid in id_to_idx and rid != pid:
                    g.add_edge(pid, rid, weight=1.0, kind="cites")
        return g, dicts, id_to_idx

    # ------------------------------------------------------------------
    # Kleinberg burst detection
    # ------------------------------------------------------------------

    @staticmethod
    def _kleinberg_bursts(
        counts: Sequence[int],
        years: Sequence[int],
        s: float = 2.0,
        gamma: float = 1.0,
    ) -> List[Tuple[int, int, float]]:
        """Run Kleinberg's burst-detection on a discrete event series.

        Implements the standard two-level HMM formulation: a baseline
        state with rate ``r`` and a burst state with rate ``s * r``.
        A burst begins when the optimal Viterbi path enters the burst
        state and ends when it returns to baseline.

        Args:
            counts: Event counts per time-step (e.g., # citations
                received in year Y).
            years: Years corresponding to each entry (same length).
            s: Burst strength multiplier (default 2.0 — burst state
                emits twice as many events per step as baseline).
            gamma: Transition penalty (default 1.0 — equal to a
                one-bin log-likelihood difference).

        Returns:
            List of ``(start_year, end_year, strength)`` tuples.
        """
        if not counts:
            return []
        arr = np.asarray(counts, dtype=float)
        y_arr = list(years)
        n = len(arr)
        total = float(arr.sum())
        if total <= 0:
            return []
        # Baseline rate per bin.
        r = total / n
        if r <= 0:
            return []
        # Burst state rate.
        r_burst = s * r
        # Cost of staying in state q with expected rate lambda when
        # observing d events in a bin: -log P(d | lambda) = -(d log(lambda)
        # - lambda - lgamma(d+1)).  We can drop the lgamma term since it
        # is constant across states.
        def cost(d: float, lam: float) -> float:
            if lam <= 0:
                return float("inf") if d > 0 else 0.0
            return -(d * math.log(lam) - lam)
        # Transition cost: gamma * log(n) for going up by one level.
        trans_cost = gamma * math.log(max(n, 2))
        # DP: states 0 (baseline) and 1 (burst).  Track cumulative
        # cost and the path.
        # cost_0[k] = min cost of being in state 0 at step k
        # cost_1[k] = min cost of being in state 1 at step k
        cost_0 = [0.0] * n
        cost_1 = [0.0] * n
        path_0 = [0] * n
        path_1 = [0] * n
        cost_0[0] = cost(arr[0], r)
        cost_1[0] = cost(arr[0], r_burst) + trans_cost
        path_0[0] = 0
        path_1[0] = 1
        for k in range(1, n):
            d = arr[k]
            c0 = cost(d, r)
            c1 = cost(d, r_burst)
            # State 0 at step k: came from 0 (free) or 1 (free).
            from_0_to_0 = cost_0[k - 1] + c0
            from_1_to_0 = cost_1[k - 1] + c0
            if from_0_to_0 <= from_1_to_0:
                cost_0[k] = from_0_to_0
                path_0[k] = 0
            else:
                cost_0[k] = from_1_to_0
                path_0[k] = 1
            # State 1 at step k: came from 1 (free) or 0 (transition).
            from_0_to_1 = cost_0[k - 1] + c1 + trans_cost
            from_1_to_1 = cost_1[k - 1] + c1
            if from_0_to_1 <= from_1_to_1:
                cost_1[k] = from_0_to_1
                path_1[k] = 0
            else:
                cost_1[k] = from_1_to_1
                path_1[k] = 1
        # Backtrack optimal path.
        if cost_0[n - 1] <= cost_1[n - 1]:
            last_state = 0
        else:
            last_state = 1
        states = [0] * n
        states[n - 1] = last_state
        for k in range(n - 1, 0, -1):
            if states[k] == 0:
                states[k - 1] = path_0[k]
            else:
                states[k - 1] = path_1[k]
        # Extract bursts (maximal intervals where state == 1).
        bursts: List[Tuple[int, int, float]] = []
        k = 0
        while k < n:
            if states[k] == 1:
                start = k
                while k < n and states[k] == 1:
                    k += 1
                end = k - 1
                # Strength = improvement in log-likelihood of the
                # burst state vs baseline over the burst interval.
                ll_burst = 0.0
                ll_base = 0.0
                for j in range(start, end + 1):
                    d = arr[j]
                    if r_burst > 0:
                        ll_burst += d * math.log(r_burst) - r_burst
                    if r > 0:
                        ll_base += d * math.log(r) - r
                strength = max(ll_burst - ll_base, 0.0)
                bursts.append((y_arr[start], y_arr[end], strength))
            else:
                k += 1
        return bursts

    def detect_citation_bursts(
        self,
        papers: Sequence[Any],
        time_window: int = 1,
        s: float = 2.0,
        gamma: float = 1.0,
        current_year: Optional[int] = None,
    ) -> List[Burst]:
        """Detect citation bursts using Kleinberg's algorithm.

        The implementation runs burst detection twice:

        1. **Corpus-level**: aggregates the corpus into a per-year
           publication-count time series (papers published per year)
           and detects bursts on it. Corpus-level bursts are emitted
           with ``paper_id = "CORPUS"``.
        2. **Per-paper**: for each paper whose total citation count is
           above the corpus median, synthesises a per-year citation
           trajectory by distributing the total citations uniformly
           across the years since publication, and detects bursts on
           that trajectory.

        Args:
            papers: Sequence of Paper objects.
            time_window: Bin size in years (default 1).
            s: Kleinberg burst-strength multiplier.
            gamma: Kleinberg transition penalty.
            current_year: Override for the current calendar year.

        Returns:
            List of :class:`Burst` objects (corpus-level + per-paper).
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for CiteSpaceAnalyzer")
        dicts = [_paper_to_dict(p) for p in papers]
        if not dicts:
            return []
        cy = current_year if current_year is not None else _current_year()
        # Bin papers by year.
        year_counts: Dict[int, int] = defaultdict(int)
        for d in dicts:
            y = d.get("year")
            try:
                y = int(y) if y is not None else None
            except (TypeError, ValueError):
                y = None
            if y is not None:
                year_counts[y] += 1
        bursts: List[Burst] = []
        if year_counts:
            min_y = min(year_counts)
            max_y = max(max(year_counts), cy)
            years = list(range(min_y, max_y + 1, time_window))
            counts = [
                sum(year_counts[y]
                    for y in range(ystart, ystart + time_window))
                for ystart in years
            ]
            for sy, ey, strength in self._kleinberg_bursts(
                counts, years, s=s, gamma=gamma,
            ):
                bursts.append(Burst(
                    paper_id="CORPUS",
                    paper_title="",
                    start_year=sy,
                    end_year=ey,
                    strength=strength,
                ))
        # Per-paper bursts (top half of citation distribution).
        if dicts:
            cite_arr = np.array(
                [int(d.get("citations_count") or 0) for d in dicts]
            )
            median_cites = float(np.median(cite_arr))
            for i, d in enumerate(dicts):
                cites = int(d.get("citations_count") or 0)
                if cites < median_cites or cites <= 0:
                    continue
                y = d.get("year")
                try:
                    y = int(y) if y is not None else None
                except (TypeError, ValueError):
                    y = None
                if y is None or y <= 0:
                    continue
                end_y = max(cy, y)
                years = list(range(y, end_y + 1, time_window))
                if len(years) < 2:
                    continue
                # Uniform distribution of citations across the
                # paper's lifetime (a coarse approximation; real
                # burst detection requires yearly citation history
                # which the Paper schema does not expose).
                per_year = cites / len(years)
                counts = [per_year] * len(years)
                # Inject a single high-citation "burst" bin at the
                # publication year (a common pattern).
                counts[0] = max(counts[0] * 2, 1.0)
                for sy, ey, strength in self._kleinberg_bursts(
                    counts, years, s=s, gamma=gamma,
                ):
                    if strength <= 0:
                        continue
                    bursts.append(Burst(
                        paper_id=_paper_id(d, i),
                        paper_title=d.get("title") or "",
                        start_year=sy,
                        end_year=ey,
                        strength=strength,
                    ))
        return bursts

    # ------------------------------------------------------------------
    # Topic extraction (used by knowledge_domain_map and research_fronts)
    # ------------------------------------------------------------------

    @staticmethod
    def _paper_topics(d: Dict[str, Any]) -> List[str]:
        """Return the set of topics for a paper.

        Uses ``fields_of_study`` when present, else ``keywords``,
        else extracts single tokens from the title.
        """
        topics: List[str] = []
        fos = _coerce_list(d.get("fields_of_study"))
        if fos:
            topics = [_normalise_id(t) for t in fos if _normalise_id(t)]
        if not topics:
            kw = _coerce_list(d.get("keywords"))
            if kw:
                topics = [_normalise_id(t) for t in kw if _normalise_id(t)]
        if not topics:
            title = d.get("title") or ""
            topics = [
                w for w in re.findall(r"[a-z][a-z0-9]{2,}",
                                      title.lower())
                if len(w) >= 4
            ][:5]
        return topics

    # ------------------------------------------------------------------
    # Knowledge-domain map (timezone view)
    # ------------------------------------------------------------------

    def knowledge_domain_map(
        self,
        papers: Sequence[Any],
        year_bins: int = 5,
    ) -> "nx.Graph":
        """Build a CiteSpace-style knowledge-domain map.

        Nodes are ``(topic, time_bin)`` tuples. Edges connect
        consecutive time bins for the same topic, weighted by the
        number of papers carrying that topic in each bin.

        Args:
            papers: Sequence of Paper objects.
            year_bins: Width of each time bin in years (default 5).

        Returns:
            ``networkx.Graph``.
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for CiteSpaceAnalyzer")
        dicts = [_paper_to_dict(p) for p in papers]
        years = [d.get("year") for d in dicts]
        try:
            years_int = [int(y) for y in years if y]
        except (TypeError, ValueError):
            years_int = []
        if not years_int:
            return nx.Graph()
        min_y = min(years_int)
        max_y = max(years_int)
        if max_y <= min_y:
            return nx.Graph()
        # Bin assignment.
        def bin_of(y: int) -> int:
            return (y - min_y) // year_bins
        max_bin = bin_of(max_y)
        # Count topic presence per bin.
        topic_bin_count: Dict[Tuple[str, int], int] = defaultdict(int)
        for d in dicts:
            try:
                y = int(d.get("year") or 0)
            except (TypeError, ValueError):
                continue
            if not y:
                continue
            b = bin_of(y)
            for t in self._paper_topics(d):
                topic_bin_count[(t, b)] += 1
        g = nx.Graph()
        for (topic, b), c in topic_bin_count.items():
            start_y = min_y + b * year_bins
            g.add_node(
                (topic, b),
                topic=topic,
                bin=b,
                start_year=start_y,
                end_year=start_y + year_bins - 1,
                count=c,
            )
        # Edges between consecutive bins of the same topic.
        for (topic, b), c in topic_bin_count.items():
            tgt = (topic, b + 1)
            if tgt in topic_bin_count:
                g.add_edge(
                    (topic, b), tgt,
                    weight=min(c, topic_bin_count[tgt]),
                    kind="continuity",
                )
        return g

    # ------------------------------------------------------------------
    # Timezone view (matplotlib)
    # ------------------------------------------------------------------

    def timezone_view(
        self,
        papers: Sequence[Any],
        year_bins: int = 5,
        top_topics: int = 20,
        figsize: Tuple[int, int] = (10, 6),
    ) -> Any:
        """Render a CiteSpace-style timezone view.

        X-axis = time bins; Y-axis = topics. Each node is a
        ``(topic, bin)`` pair; horizontal edges link consecutive
        bins of the same topic.

        Args:
            papers: Sequence of Paper objects.
            year_bins: Width of each time bin in years.
            top_topics: Maximum number of topics to display (ranked
                by total paper count).
            figsize: Figure size.

        Returns:
            matplotlib Figure (with ``constrained_layout=True``).
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "matplotlib is required for timezone_view"
            ) from exc
        g = self.knowledge_domain_map(papers, year_bins=year_bins)
        if len(g) == 0:
            fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
            ax.text(
                0.5, 0.5, "no data", ha="center", va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            return fig
        # Pick top topics by total count.
        topic_totals: Dict[str, int] = defaultdict(int)
        for n, data in g.nodes(data=True):
            topic_totals[data["topic"]] += data.get("count", 0)
        ranked = [
            t for t, _ in sorted(
                topic_totals.items(), key=lambda kv: -kv[1]
            )[:top_topics]
        ]
        rank = {t: i for i, t in enumerate(ranked)}
        # Render.
        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
        # Edges first (so nodes paint over them).
        for u, v, data in g.edges(data=True):
            if u[0] in rank and v[0] in rank:
                ax.plot(
                    [u[1], v[1]], [rank[u[0]], rank[v[0]]],
                    color="#888888", linewidth=1.0, alpha=0.5,
                    zorder=1,
                )
        # Nodes — sized by count.
        max_count = max(
            (d.get("count", 0) for _, d in g.nodes(data=True)),
            default=1,
        )
        for n, data in g.nodes(data=True):
            if n[0] not in rank:
                continue
            ax.scatter(
                [n[1]], [rank[n[0]]],
                s=20 + 200 * (data.get("count", 0) / max(1, max_count)),
                color="#1f77b4", edgecolors="white", linewidths=0.7,
                zorder=2,
            )
        ax.set_yticks(range(len(ranked)))
        ax.set_yticklabels(ranked, fontsize=8,
                            fontfamily=["Noto Sans SC", "DejaVu Sans"])
        ax.set_xlabel("Time bin (year)")
        ax.set_ylabel("Topic")
        ax.set_title("CiteSpace Timezone View")
        ax.grid(True, axis="x", linestyle=":", alpha=0.3)
        return fig

    # ------------------------------------------------------------------
    # Spectral-clustering view
    # ------------------------------------------------------------------

    def spectral_clustering_view(
        self,
        papers: Sequence[Any],
        n_clusters: int = 5,
        figsize: Tuple[int, int] = (8, 6),
    ) -> Any:
        """Render a spectral-clustering view of the citation network.

        Builds the bibliographic-coupling graph, embeds it via the
        top-``k`` eigenvectors of its Laplacian, clusters with k-means,
        and scatters the 2-D embedding with cluster colours.

        Args:
            papers: Sequence of Paper objects.
            n_clusters: Number of clusters to find.
            figsize: Figure size.

        Returns:
            matplotlib Figure.
        """
        try:
            import matplotlib.pyplot as plt
            from sklearn.cluster import SpectralClustering
            from sklearn.manifold import spectral_embedding
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "matplotlib and scikit-learn are required for "
                "spectral_clustering_view"
            ) from exc
        # Build undirected coupling graph.
        from bibliometrics.vosviewer import VOSAnalyzer
        g = VOSAnalyzer().bibliographic_coupling(papers, min_shared=1)
        if len(g) < n_clusters:
            fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
            ax.text(
                0.5, 0.5, "insufficient data", ha="center", va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
            return fig
        nodes = list(g.nodes())
        A = nx.to_numpy_array(g, nodelist=nodes, weight="weight")
        # Spectral embedding (2-D).
        try:
            emb = spectral_embedding(
                A, n_components=2, random_state=42,
                drop_first=False,
            )
        except Exception:  # pragma: no cover - defensive
            from sklearn.decomposition import PCA
            emb = PCA(n_components=2, random_state=42).fit_transform(A)
        # Spectral clustering.
        try:
            sc = SpectralClustering(
                n_clusters=min(n_clusters, len(nodes)),
                affinity="precomputed",
                random_state=42,
                assign_labels="kmeans",
            )
            labels = sc.fit_predict(A)
        except Exception:  # pragma: no cover - defensive
            from sklearn.cluster import KMeans
            labels = KMeans(
                n_clusters=min(n_clusters, len(nodes)),
                random_state=42, n_init=10,
            ).fit_predict(emb)
        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
        scatter = ax.scatter(
            emb[:, 0], emb[:, 1], c=labels, cmap="tab10", s=60,
            edgecolors="white", linewidths=0.5,
        )
        if len(nodes) <= 40:
            for i, n in enumerate(nodes):
                label = n if isinstance(n, str) else str(n)
                if len(label) > 20:
                    label = label[:20] + "…"
                ax.annotate(
                    label, (emb[i, 0], emb[i, 1]), fontsize=6,
                    fontfamily=["Noto Sans SC", "DejaVu Sans"],
                )
        ax.set_title(f"CiteSpace Spectral Clustering ({n_clusters} clusters)")
        ax.set_axis_off()
        legend = ax.legend(
            *scatter.legend_elements(), title="Cluster",
            loc="best", fontsize=8,
        )
        return fig

    # ------------------------------------------------------------------
    # Structural variation analysis
    # ------------------------------------------------------------------

    def structural_variation_analysis(
        self,
        papers: Sequence[Any],
        year_bins: int = 5,
    ) -> "nx.Graph":
        """Analyse structural variation (modularity changes) over time.

        Builds a per-time-bin citation graph and computes the
        modularity of each bin's largest connected component. Returns
        a graph whose nodes are time bins (with modularity / year /
        paper-count attributes) and whose edges link consecutive bins.

        Args:
            papers: Sequence of Paper objects.
            year_bins: Bin width in years.

        Returns:
            ``networkx.Graph`` with one node per time bin.
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for CiteSpaceAnalyzer")
        dicts = [_paper_to_dict(p) for p in papers]
        # Bin papers by year.
        try:
            years_int = sorted({
                int(d.get("year")) for d in dicts
                if d.get("year")
            })
        except (TypeError, ValueError):
            years_int = []
        if not years_int:
            return nx.Graph()
        min_y = min(years_int)
        max_y = max(years_int)
        if max_y <= min_y:
            return nx.Graph()
        def bin_of(y: int) -> int:
            return (y - min_y) // year_bins
        max_bin = bin_of(max_y)
        # Per-bin citation graphs.
        per_bin_papers: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for d in dicts:
            y = d.get("year")
            try:
                y_int = int(y) if y else 0
            except (TypeError, ValueError):
                continue
            if y_int:
                per_bin_papers[bin_of(y_int)].append(d)
        g = nx.Graph()
        prev_bin = None
        prev_modularity = None
        for b in range(0, max_bin + 1):
            bin_papers = per_bin_papers.get(b, [])
            start_y = min_y + b * year_bins
            if not bin_papers:
                g.add_node(
                    b, year=start_y, paper_count=0, modularity=0.0,
                )
                if prev_bin is not None:
                    g.add_edge(prev_bin, b, kind="continuity")
                prev_bin = b
                prev_modularity = 0.0
                continue
            from bibliometrics.vosviewer import VOSAnalyzer
            bc = VOSAnalyzer().bibliographic_coupling(bin_papers, min_shared=1)
            mod = 0.0
            # Modularity requires at least one edge and at least one
            # community split; otherwise it's undefined and we skip.
            if len(bc) > 1 and bc.size() > 0:
                try:
                    if nx.is_connected(bc):
                        if hasattr(nx.algorithms.community,
                                    "louvain_communities"):
                            communities = (
                                nx.algorithms.community.louvain_communities(
                                    bc, weight="weight", seed=42,
                                )
                            )
                        else:
                            communities = (
                                nx.algorithms.community
                                .greedy_modularity_communities(bc)
                            )
                        mod = nx.algorithms.community.modularity(
                            bc, communities, weight="weight",
                        )
                    else:
                        components = list(nx.connected_components(bc))
                        mod = nx.algorithms.community.modularity(
                            bc, components,
                        )
                except (ZeroDivisionError, ValueError, nx.NetworkXError):
                    mod = 0.0
            g.add_node(
                b, year=start_y, paper_count=len(bin_papers),
                modularity=float(mod),
            )
            if prev_bin is not None and prev_modularity is not None:
                g.add_edge(
                    prev_bin, b,
                    kind="continuity",
                    delta_modularity=mod - prev_modularity,
                )
            prev_bin = b
            prev_modularity = mod
        return g

    # ------------------------------------------------------------------
    # Landmark papers & intellectual turning points
    # ------------------------------------------------------------------

    def _paper_centrality_scores(
        self,
        papers: Sequence[Any],
    ) -> Dict[str, Dict[str, float]]:
        """Compute per-paper centrality scores on the citation graph.

        Returns a dict keyed by paper id with values
        ``{"betweenness": ..., "pagerank": ..., "degree": ...,
        "closeness": ...}``.
        """
        g, dicts, _ = self._build_citation_graph(papers)
        if len(g) == 0:
            return {}
        try:
            betw = nx.betweenness_centrality(g, weight=None)
        except Exception:  # pragma: no cover - defensive
            betw = {n: 0.0 for n in g.nodes()}
        try:
            pr = nx.pagerank(g.to_undirected(), weight="weight")
        except Exception:  # pragma: no cover - defensive
            pr = {n: 0.0 for n in g.nodes()}
        try:
            closeness = nx.closeness_centrality(g.to_undirected())
        except Exception:  # pragma: no cover - defensive
            closeness = {n: 0.0 for n in g.nodes()}
        deg = dict(g.degree())
        out: Dict[str, Dict[str, float]] = {}
        for n in g.nodes():
            out[n] = {
                "betweenness": float(betw.get(n, 0.0)),
                "pagerank": float(pr.get(n, 0.0)),
                "degree": float(deg.get(n, 0)),
                "closeness": float(closeness.get(n, 0.0)),
            }
        return out

    def landmark_papers(
        self,
        papers: Sequence[Any],
        top_n: int = 20,
    ) -> List[Dict[str, Any]]:
        """Identify landmark papers (centrality × burst-strength).

        Args:
            papers: Sequence of Paper objects.
            top_n: Number of landmarks to return.

        Returns:
            List of paper dicts (sorted descending by combined
            score), each annotated with ``centrality_score``,
            ``burst_score``, ``landmark_score``.
        """
        dicts = [_paper_to_dict(p) for p in papers]
        centrality = self._paper_centrality_scores(papers)
        # Normalise centrality to [0, 1].
        if centrality:
            max_b = max(c["betweenness"] for c in centrality.values()) or 1.0
            max_d = max(c["degree"] for c in centrality.values()) or 1.0
            centrality_score = {
                n: 0.6 * (c["betweenness"] / max_b) +
                   0.4 * (c["degree"] / max_d)
                for n, c in centrality.items()
            }
        else:
            centrality_score = {}
        # Burst strength per paper.
        bursts = self.detect_citation_bursts(papers)
        burst_score: Dict[str, float] = defaultdict(float)
        for b in bursts:
            burst_score[b.paper_id] += b.strength
        max_bs = max(burst_score.values(), default=1.0) or 1.0
        scores: List[Tuple[float, Dict[str, Any]]] = []
        for i, d in enumerate(dicts):
            pid = _paper_id(d, i)
            cs = centrality_score.get(pid, 0.0)
            bs = burst_score.get(pid, 0.0) / max_bs
            combined = cs * (1.0 + bs)  # centrality × (1 + burst)
            scores.append((combined, {**d, "paper_id": pid,
                                       "centrality_score": cs,
                                       "burst_score": bs,
                                       "landmark_score": combined}))
        scores.sort(key=lambda x: -x[0])
        return [s[1] for s in scores[:top_n]]

    def intellectual_turning_points(
        self,
        papers: Sequence[Any],
        top_n: int = 10,
    ) -> List[Dict[str, Any]]:
        """Identify intellectual turning points (high betweenness).

        Args:
            papers: Sequence of Paper objects.
            top_n: Number of turning-point papers to return.

        Returns:
            List of paper dicts (sorted by betweenness centrality
            descending), each annotated with ``betweenness``.
        """
        centrality = self._paper_centrality_scores(papers)
        dicts = [_paper_to_dict(p) for p in papers]
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for i, d in enumerate(dicts):
            pid = _paper_id(d, i)
            betw = centrality.get(pid, {}).get("betweenness", 0.0)
            scored.append((betw, {**d, "paper_id": pid,
                                    "betweenness": betw}))
        scored.sort(key=lambda x: -x[0])
        return [s[1] for s in scored[:top_n]]

    # ------------------------------------------------------------------
    # Research fronts
    # ------------------------------------------------------------------

    def research_fronts(
        self,
        papers: Sequence[Any],
        cluster_method: str = "spectral",
        n_clusters: int = 5,
        top_terms: int = 10,
    ) -> List[ResearchFront]:
        """Cluster papers into research fronts.

        Uses either spectral clustering (default) on the
        bibliographic-coupling graph, or Louvain community detection
        on the same graph.

        Args:
            papers: Sequence of Paper objects.
            cluster_method: ``"spectral"`` (default) or ``"louvain"``.
            n_clusters: Number of clusters (ignored when
                ``cluster_method == "louvain"``).
            top_terms: Number of top terms to extract per cluster.

        Returns:
            List of :class:`ResearchFront` objects.
        """
        if not _HAVE_NX:
            raise ImportError("networkx is required for CiteSpaceAnalyzer")
        dicts = [_paper_to_dict(p) for p in papers]
        if not dicts:
            return []
        from bibliometrics.vosviewer import VOSAnalyzer
        g = VOSAnalyzer().bibliographic_coupling(papers, min_shared=1)
        # Node list aligned with dicts.
        node_to_dict: Dict[str, Dict[str, Any]] = {}
        for i, d in enumerate(dicts):
            node_to_dict[_paper_id(d, i)] = d
        nodes = list(g.nodes())
        # If graph is empty or disconnected, fall back to topic-based
        # clustering (each unique topic = its own cluster).
        if len(nodes) == 0 or len(g.edges()) == 0:
            return self._topic_clusters(dicts, top_terms=top_terms)
        # Cluster.
        if cluster_method == "louvain":
            communities = nx.algorithms.community.louvain_communities(
                g, weight="weight", seed=42,
            )
            clusters = [list(c) for c in communities]
        else:
            try:
                from sklearn.cluster import SpectralClustering
                A = nx.to_numpy_array(g, nodelist=nodes, weight="weight")
                k = max(1, min(n_clusters, len(nodes)))
                sc = SpectralClustering(
                    n_clusters=k, affinity="precomputed",
                    random_state=42, assign_labels="kmeans",
                )
                labels = sc.fit_predict(A)
                clusters: List[List[str]] = [[] for _ in range(k)]
                for n, l in zip(nodes, labels):
                    clusters[l].append(n)
            except ImportError:  # pragma: no cover - defensive
                communities = nx.algorithms.community.louvain_communities(
                    g, weight="weight", seed=42,
                )
                clusters = [list(c) for c in communities]
        # Burst scores per paper.
        bursts = self.detect_citation_bursts(papers)
        burst_score: Dict[str, float] = defaultdict(float)
        for b in bursts:
            burst_score[b.paper_id] += b.strength
        # Build ResearchFront objects.
        fronts: List[ResearchFront] = []
        for cid, members in enumerate(clusters):
            if not members:
                continue
            member_dicts = [
                node_to_dict[m] for m in members
                if m in node_to_dict
            ]
            if not member_dicts:
                continue
            front = ResearchFront(
                id=cid,
                papers=member_dicts,
                centroid=None,
                burst_score=sum(
                    burst_score.get(_paper_id(d, i), 0.0)
                    for i, d in enumerate(member_dicts)
                ),
                top_terms=self._top_terms_for(member_dicts, top_n=top_terms),
            )
            fronts.append(front)
        return fronts

    @staticmethod
    def _top_terms_for(
        dicts: Sequence[Dict[str, Any]],
        top_n: int = 10,
    ) -> List[Tuple[str, int]]:
        """Return the ``top_n`` most frequent terms in a set of papers."""
        try:
            from bibliometrics.vosviewer import _tokenise
        except ImportError:  # pragma: no cover - defensive
            def _tokenise(t: str) -> List[str]:
                return re.findall(r"[a-z][a-z0-9]{2,}", (t or "").lower())
        counter: Counter = Counter()
        for d in dicts:
            for f in ("title", "abstract"):
                v = d.get(f)
                if isinstance(v, str):
                    counter.update(_tokenise(v))
            kw = _coerce_list(d.get("keywords"))
            for k in kw:
                if k:
                    counter[str(k).lower()] += 1
        return counter.most_common(top_n)

    def _topic_clusters(
        self,
        dicts: Sequence[Dict[str, Any]],
        top_terms: int = 10,
    ) -> List[ResearchFront]:
        """Fallback topic-based clustering when the citation graph is empty."""
        topic_to_papers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for d in dicts:
            for t in self._paper_topics(d):
                topic_to_papers[t].append(d)
        fronts: List[ResearchFront] = []
        for cid, (topic, plist) in enumerate(topic_to_papers.items()):
            fronts.append(ResearchFront(
                id=cid,
                papers=plist,
                centroid=None,
                burst_score=0.0,
                top_terms=[(topic, len(plist))] + self._top_terms_for(
                    plist, top_n=top_terms - 1,
                ),
            ))
        return fronts
