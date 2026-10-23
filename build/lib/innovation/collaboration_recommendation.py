"""collaboration_recommendation — author-collaboration recommender
for the Academic Research Suite.

Suggests potential collaborators for a given author by combining three
signals:

* **Complementary expertise** — authors whose keyword / field-of-study
  profiles are *complementary* (high Jaccard distance, but both
  well-established) tend to produce interdisciplinary, high-impact
  work.
* **Weak ties** — authors connected through a small number of
  co-authors (Granovetter's "weak ties" hypothesis) are valuable
  bridges between communities.
* **Co-author history** — authors who have already collaborated (and
  especially those with recent successful collaborations) are natural
  candidates for renewed collaboration.

Also exposes:

* :meth:`recommend_institutions` — institution-level collaboration
  suggestions (inferred from author affiliations stored in
  ``raw['affiliations']`` when available, otherwise synthesized from
  journal/publisher fields).
* :meth:`bridge_authors` — finds authors whose expertise spans two
  fields, useful for cross-disciplinary project staffing.
* :meth:`emerging_collaborations` — detects author pairs whose first
  co-authored paper appeared after a year threshold.
* :meth:`visualize_collaboration_network` — renders a force-directed
  graph centered on a focal author (or the top-N most-connected
  authors when no focal author is supplied).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import math
import warnings
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configure_fonts() -> None:
    """Configure matplotlib rcParams for CJK-aware font fallback."""
    try:
        import matplotlib
        from matplotlib import font_manager
        preferred = [
            "Noto Sans SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
            "Microsoft YaHei", "PingFang SC", "SimHei", "DejaVu Sans",
        ]
        available = {f.name for f in font_manager.fontManager.ttflist}
        family = [f for f in preferred if f in available] or ["DejaVu Sans"]
        matplotlib.rcParams["font.family"] = family
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Font configuration failed: %s", exc)


def _safe_year(p: Any) -> Optional[int]:
    """Return ``int(p.year)`` or ``None``."""
    y = getattr(p, "year", None)
    if y is None:
        return None
    try:
        return int(y)
    except (TypeError, ValueError):
        return None


def _author_profile(paper: Any) -> Set[str]:
    """Return the set of keywords + fields-of-study for a paper."""
    kws = {str(k).lower() for k in (getattr(paper, "keywords", []) or []) if k}
    fos = {str(f).lower() for f in (getattr(paper, "fields_of_study", []) or []) if f}
    return kws | fos


def _jaccard(a: Set[str], b: Set[str]) -> float:
    """Jaccard similarity in ``[0, 1]``."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def _cosine_sets(a: Set[str], b: Set[str]) -> float:
    """Cosine similarity between two sets viewed as binary vectors."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / (math.sqrt(len(a)) * math.sqrt(len(b)))  # type: ignore[name-defined]


# ---------------------------------------------------------------------------
# CollaborationRecommender
# ---------------------------------------------------------------------------


class CollaborationRecommender:
    """Recommends author collaborations using a multi-signal score."""

    def __init__(self, papers: Sequence[Any]) -> None:
        """Initialize the recommender.

        Args:
            papers: Sequence of :class:`Paper`-like objects.
        """
        self.papers: List[Any] = list(papers)
        self.logger = logger
        # Pre-compute author -> papers index.
        self._author_papers: Dict[str, List[Any]] = defaultdict(list)
        self._author_profile: Dict[str, Set[str]] = defaultdict(set)
        self._author_affiliations: Dict[str, List[str]] = defaultdict(list)
        self._coauthor_pairs: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        self._build_indices()

    def _build_indices(self) -> None:
        """Build the per-author and co-author indices."""
        for p in self.papers:
            authors = list(getattr(p, "authors", []) or [])
            kws = _author_profile(p)
            for a in authors:
                if not a:
                    continue
                self._author_papers[a].append(p)
                self._author_profile[a] |= kws
                affs = self._extract_affiliations(p)
                if affs:
                    self._author_affiliations[a].extend(affs)
            # Co-author pairs.
            uniq = sorted({a for a in authors if a})
            for i in range(len(uniq)):
                for j in range(i + 1, len(uniq)):
                    self._coauthor_pairs[(uniq[i], uniq[j])].append(
                        _safe_year(p) or 0,
                    )

    def _extract_affiliations(self, p: Any) -> List[str]:
        """Best-effort extraction of institution names from a paper.

        Looks at ``raw['affiliations']`` (a list), then
        ``raw['author_affiliations']`` (a list of dicts with ``'affiliation'``),
        finally falls back to ``p.journal`` and ``p.publisher``.
        """
        raw = getattr(p, "raw", {}) or {}
        affs: List[str] = []
        direct = raw.get("affiliations")
        if isinstance(direct, list):
            affs = [str(a).strip() for a in direct if a]
        if not affs:
            aa = raw.get("author_affiliations")
            if isinstance(aa, list):
                for entry in aa:
                    if isinstance(entry, dict):
                        name = entry.get("affiliation") or entry.get("institution")
                        if name:
                            affs.append(str(name).strip())
                    elif isinstance(entry, str):
                        affs.append(entry.strip())
        if not affs:
            j = getattr(p, "journal", None)
            if j:
                affs.append(str(j))
        return [a for a in affs if a]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def authors(self) -> List[str]:
        """Return the list of known authors."""
        return list(self._author_papers.keys())

    def recommend_collaborators(
        self,
        author: str,
        top_k: int = 10,
        exclude_existing: bool = True,
    ) -> List[Tuple[str, float]]:
        """Recommend potential collaborators for ``author``.

        Score = 0.40 * complementary_expertise
              + 0.25 * weak_tie_strength
              + 0.15 * co_author_history
              + 0.20 * productivity_bonus

        Args:
            author: The focal author name.
            top_k: Number of recommendations.
            exclude_existing: If ``True``, skip authors who have
                already co-authored with ``author``.

        Returns:
            Sorted list of ``(other_author, score)`` tuples.
        """
        author = author.strip()
        if author not in self._author_papers:
            return []
        author_prof = self._author_profile[author]
        author_paper_count = len(self._author_papers[author])
        existing_coauthors: Set[str] = set()
        for (a, b), _ in self._coauthor_pairs.items():
            if a == author:
                existing_coauthors.add(b)
            elif b == author:
                existing_coauthors.add(a)

        scores: List[Tuple[str, float]] = []
        for other, other_prof in self._author_profile.items():
            if other == author:
                continue
            if exclude_existing and other in existing_coauthors:
                continue
            # Complementary expertise: high cosine overlap signals
            # shared domain; we want authors with *some* overlap but
            # also distinct contributions. Use cosine as a "shared
            # vocabulary" proxy.
            cosine = _cosine_sets(author_prof, other_prof)
            # Jaccard distance = 1 - Jaccard, measuring how *different*
            # the profiles are.
            jaccard = _jaccard(author_prof, other_prof)
            complementary = 0.5 * cosine + 0.5 * (1 - jaccard) * (1 if cosine > 0 else 0)
            # Weak tie: shortest path through co-authors (here
            # approximated as 1 / (1 + number of shared co-authors)).
            shared_co = len(self._shared_coauthors(author, other))
            weak_tie = 1.0 / (1.0 + shared_co) if shared_co > 0 else 0.0
            # Co-author history (always 0 if exclude_existing).
            pair_key = tuple(sorted([author, other]))
            history = len(self._coauthor_pairs.get(pair_key, []))
            history_score = min(1.0, history / 5.0) if history > 0 else 0.0
            # Productivity bonus: other author's paper count relative to max.
            other_count = len(self._author_papers[other])
            max_count = max(1, max(
                (len(ps) for ps in self._author_papers.values()), default=1,
            ))
            productivity = other_count / max_count
            score = (
                0.40 * complementary
                + 0.25 * weak_tie
                + 0.15 * history_score
                + 0.20 * productivity
            )
            scores.append((other, float(score)))
        scores.sort(key=lambda kv: -kv[1])
        return scores[:top_k]

    def _shared_coauthors(self, a: str, b: str) -> Set[str]:
        """Return co-authors common to both ``a`` and ``b``."""
        a_co = set()
        for (x, y) in self._coauthor_pairs:
            if x == a:
                a_co.add(y)
            elif y == a:
                a_co.add(x)
        b_co = set()
        for (x, y) in self._coauthor_pairs:
            if x == b:
                b_co.add(y)
            elif y == b:
                b_co.add(x)
        return a_co & b_co

    def recommend_institutions(
        self,
        author: str,
        top_k: int = 5,
    ) -> List[Tuple[str, float]]:
        """Suggest institutions for collaboration.

        Ranks institutions by the aggregate productivity of their
        affiliated authors *minus* any institutions ``author`` is
        already affiliated with.

        Args:
            author: The focal author name.
            top_k: Number of recommendations.

        Returns:
            Sorted list of ``(institution, score)`` tuples.
        """
        author = author.strip()
        own_institutions: Set[str] = set(self._author_affiliations.get(author, []))
        # Build institution -> author -> paper count.
        inst_authors: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for a, affs in self._author_affiliations.items():
            for inst in affs:
                inst_authors[inst][a] = len(self._author_papers.get(a, []))
        # Score institutions: sum of papers across their authors.
        scored: List[Tuple[str, float]] = []
        for inst, author_counts in inst_authors.items():
            if inst in own_institutions:
                continue
            total = sum(author_counts.values())
            n_authors = len(author_counts)
            avg = total / max(1, n_authors)
            # Reward size + average productivity.
            score = 0.5 * min(1.0, total / 50.0) + 0.5 * min(1.0, avg / 10.0)
            scored.append((inst, float(score)))
        scored.sort(key=lambda kv: -kv[1])
        return scored[:top_k]

    def bridge_authors(
        self,
        field_a: str,
        field_b: str,
        top_k: int = 5,
    ) -> List[Tuple[str, float]]:
        """Find authors who could bridge two fields.

        Bridge authors are those with non-trivial expertise in *both*
        fields. Score = harmonic mean of the two field-affinity scores
        to reward balance over specialization.

        Args:
            field_a: First field name (matched against ``keywords``
                and ``fields_of_study``).
            field_b: Second field name.
            top_k: Number of bridge authors.

        Returns:
            Sorted list of ``(author, score)`` tuples.
        """
        fa = field_a.lower()
        fb = field_b.lower()
        scores: List[Tuple[str, float]] = []
        for author, prof in self._author_profile.items():
            has_a = 1.0 if fa in prof else 0.0
            has_b = 1.0 if fb in prof else 0.0
            # Per-paper affinity: fraction of author's papers in each field.
            papers_a = sum(1 for p in self._author_papers[author] if fa in _author_profile(p))
            papers_b = sum(1 for p in self._author_papers[author] if fb in _author_profile(p))
            total_papers = max(1, len(self._author_papers[author]))
            aff_a = (has_a + 0.5 * papers_a / total_papers) / 1.5
            aff_b = (has_b + 0.5 * papers_b / total_papers) / 1.5
            if aff_a <= 0 or aff_b <= 0:
                continue
            bridge = 2 * aff_a * aff_b / (aff_a + aff_b)
            scores.append((author, float(bridge)))
        scores.sort(key=lambda kv: -kv[1])
        return scores[:top_k]

    def compute_strength(self, author_a: str, author_b: str) -> float:
        """Compute the collaboration-strength score between two authors.

        Score = 0.4 * Jaccard(keywords/fields)
              + 0.3 * cosine(keywords/fields)
              + 0.3 * co-author-history decay

        Args:
            author_a: First author.
            author_b: Second author.

        Returns:
            A score in ``[0, 1]``.
        """
        if author_a not in self._author_papers or author_b not in self._author_papers:
            return 0.0
        pa = self._author_profile[author_a]
        pb = self._author_profile[author_b]
        jac = _jaccard(pa, pb)
        cos = _cosine_sets(pa, pb)
        # Co-author history: number of shared papers, weighted by recency.
        pair_key = tuple(sorted([author_a, author_b]))
        years = self._coauthor_pairs.get(pair_key, [])
        history = 0.0
        if years:
            max_year = max(y for y in years if y > 0) if any(y > 0 for y in years) else 0
            for y in years:
                if y <= 0:
                    continue
                # Exponential decay: recent collaborations count more.
                decay = math.exp(-(max_year - y) / 5.0) if max_year > 0 else 1.0
                history += decay
            history = min(1.0, history / 10.0)
        return float(0.4 * jac + 0.3 * cos + 0.3 * history)

    def emerging_collaborations(
        self,
        year_threshold: int = 2020,
        top_k: int = 20,
    ) -> List[Tuple[str, str, float]]:
        """Detect author pairs whose first co-authorship is recent.

        Args:
            year_threshold: First co-authorship year must be ≥ this.
            top_k: Number of pairs to return.

        Returns:
            Sorted list of ``(author_a, author_b, score)`` triples.
        """
        results: List[Tuple[str, str, float]] = []
        for (a, b), years in self._coauthor_pairs.items():
            if not years:
                continue
            first_year = min(y for y in years if y > 0) if any(y > 0 for y in years) else 0
            if first_year < year_threshold:
                continue
            strength = self.compute_strength(a, b)
            # Bonus for being recent.
            recency = max(0.0, min(1.0, (first_year - year_threshold) / 5.0))
            results.append((a, b, float(strength * 0.7 + recency * 0.3)))
        results.sort(key=lambda kv: -kv[2])
        return results[:top_k]

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def visualize_collaboration_network(
        self,
        author: Optional[str] = None,
        top_n: int = 50,
        figsize: Tuple[int, int] = (12, 10),
    ) -> Any:
        """Render a collaboration network graph.

        Args:
            author: Optional focal author; the graph is centered on
                them (1-hop and 2-hop neighbors). If ``None``, the
                top-N most-connected authors in the entire corpus are
                shown.
            top_n: Maximum number of nodes.
            figsize: Figure size.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        import matplotlib.pyplot as plt  # lazy
        try:
            import networkx as nx  # lazy
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("networkx unavailable (%s); aborting viz.", exc)
            fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
            ax.text(0.5, 0.5, "networkx unavailable",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            return fig
        _configure_fonts()

        # Build the co-authorship graph.
        G = nx.Graph()
        edge_weights: Counter = Counter()
        for (a, b), years in self._coauthor_pairs.items():
            w = len(years)
            if w > 0:
                G.add_edge(a, b, weight=w)
                edge_weights[(a, b)] = w

        # Select subgraph.
        if author is not None and author in G:
            ego = nx.ego_graph(G, author, radius=1)
            if len(ego) > top_n:
                # Trim to top-N by degree.
                nodes_to_keep = sorted(
                    ego.nodes(), key=lambda n: -ego.degree(n),
                )[:top_n]
                ego = ego.subgraph(nodes_to_keep).copy()
            sub = ego
            center = author
        else:
            nodes_sorted = sorted(G.nodes(), key=lambda n: -G.degree(n))[:top_n]
            sub = G.subgraph(nodes_sorted).copy()
            center = None

        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
        if len(sub) == 0:
            ax.text(0.5, 0.5, "No collaboration graph to display",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            return fig

        # Layout.
        try:
            pos = nx.spring_layout(sub, k=1.0 / max(1, math.sqrt(len(sub))),
                                    seed=42, iterations=80)
        except Exception:  # pragma: no cover - defensive
            pos = nx.circular_layout(sub)

        # Node sizes by degree.
        degrees = dict(sub.degree())
        max_deg = max(degrees.values()) if degrees else 1
        node_sizes = [
            100 + 900 * (degrees[n] / max_deg) if max_deg > 0 else 200
            for n in sub.nodes()
        ]
        # Node colors: highlight focal author in red.
        node_colors = [
            "tab:red" if n == center else "tab:blue"
            for n in sub.nodes()
        ]

        # Edge widths by weight.
        max_w = max((d.get("weight", 1) for _, _, d in sub.edges(data=True)),
                      default=1)
        edge_widths = [
            1.0 + 4.0 * (d.get("weight", 1) / max_w) if max_w > 0 else 1.0
            for _, _, d in sub.edges(data=True)
        ]

        nx.draw_networkx_edges(sub, pos, ax=ax, alpha=0.30, width=edge_widths)
        nx.draw_networkx_nodes(sub, pos, ax=ax,
                                  node_size=node_sizes,
                                  node_color=node_colors,
                                  edgecolors="black",
                                  linewidths=0.4)
        # Label only the top nodes by degree to avoid clutter.
        label_nodes = sorted(degrees, key=lambda n: -degrees[n])[: min(15, len(sub))]
        labels = {n: n[:20] for n in label_nodes}
        nx.draw_networkx_labels(sub, pos, labels=labels, ax=ax, font_size=7)
        title = f"Collaboration network ({len(sub)} nodes, {sub.number_of_edges()} edges)"
        if center:
            title += f" — centered on '{center}'"
        ax.set_title(title)
        ax.set_axis_off()
        return fig


__all__ = ["CollaborationRecommender"]
