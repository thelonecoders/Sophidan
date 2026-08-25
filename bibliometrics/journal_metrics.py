"""VOSviewer / Journal Citation Reports-style journal-level metrics.

This module implements the journal-level bibliometric indicators exposed
by Clarivate's *Journal Citation Reports* (JCR) and Elsevier's
*SCImago Journal Rank* / *CiteScore* dashboards. Every metric is
computed **from a local corpus** of :class:`Paper` objects — there is no
network call, no JCR subscription, and no Scopus API dependency. The
metrics are therefore *proxies* of the official numbers: they are exact
when ``papers`` is the complete universe of publications and citations
relevant to the journal under study, and they degrade gracefully toward
the official numbers as the local corpus shrinks.

Implemented indicators:

================================  =============================================
Indicator                         Source
================================  =============================================
``impact_factor``                 JCR 2-year Impact Factor
``five_year_impact_factor``        JCR 5-year Impact Factor
``immediacy_index``               JCR Immediacy Index
``eigenfactor_score``             Eigenfactor.org (PageRank over the
                                   citation network)
``article_influence_score``       Eigenfactor.org (per-article
                                   Eigenfactor)
``scimago_journal_rank`` (SJR)    SCImago / Elsevier (prestige-weighted
                                   PageRank)
``source_normalized_impact_per_   SNIP (Leydesdorff & Moed, 2008)
  paper`` (SNIP)
``cite_score``                    Elsevier CiteScore (4-year window,
                                   numerator & denominator aligned)
``journal_h_index``              Braun et al. (2006)
``journal_g_index``              Egghe (2006) applied to a journal
``journal_h5_index``             Google Scholar Metrics 5-year h
``journal_h5_median``            Google Scholar Metrics 5-year median
``journal_quartile``             Q1..Q4 by within-year ranking
================================  =============================================
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

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
    """Coerce a Paper-like object into a plain dict.

    Accepts dicts, dataclass instances, or duck-typed objects.
    """
    if isinstance(paper, dict):
        return dict(paper)
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(paper) and not isinstance(paper, type):
            return asdict(paper)
    except Exception:  # pragma: no cover - defensive
        pass
    return {f: getattr(paper, f, None) for f in _PAPER_FIELDS}


def _as_journal_name(d: Dict[str, Any]) -> Optional[str]:
    """Return the journal/source/venue of a paper dict (or ``None``)."""
    for k in ("journal", "source", "venue", "publisher"):
        v = d.get(k)
        if v:
            return str(v).strip()
    return None


def _as_year(d: Dict[str, Any]) -> Optional[int]:
    y = d.get("year")
    if y is None:
        return None
    try:
        return int(y)
    except (TypeError, ValueError):
        return None


def _as_citations(d: Dict[str, Any]) -> int:
    c = d.get("citations_count")
    if c is None:
        return 0
    try:
        return max(int(c), 0)
    except (TypeError, ValueError):
        return 0


def _normalise_ref_id(r: Any) -> str:
    """Normalise a reference identifier (DOI / title) to lowercase str."""
    if r is None:
        return ""
    s = str(r).strip().lower()
    return s


def _paper_identifier(d: Dict[str, Any]) -> str:
    """Return a stable identifier for a paper dict (DOI > title)."""
    doi = d.get("doi")
    if doi:
        s = str(doi).strip().lower()
        if s:
            return s
    title = d.get("title") or ""
    return str(title).strip().lower()


# ---------------------------------------------------------------------------
# JournalMetrics
# ---------------------------------------------------------------------------

class JournalMetrics:
    """VOSviewer / JCR-style journal-level indicator calculator.

    All public methods accept the *full* list of papers in the corpus
    (not just the journal's own papers) — citation-network-based
    metrics (Eigenfactor, SJR, IF) need the citing side as well as the
    cited side.
    """

    def __init__(self) -> None:
        self.logger = logger

    # ------------------------------------------------------------------
    # Corpus index — built once per call to keep metrics O(N) instead
    # of O(N²).
    # ------------------------------------------------------------------

    @staticmethod
    def _build_index(
        papers: Sequence[Any],
    ) -> Dict[str, Any]:
        """Build the corpus index used by every metric.

        Returns a dict with keys:
            * ``papers`` — list of paper dicts
            * ``by_journal_year`` — ``{(journal, year): [paper_idx, ...]}``
            * ``paper_id_to_idx`` — ``{paper_id: idx}``
            * ``references_by_citing_year`` — ``{citing_year: [ref_id, ...]}``
            * ``journals`` — set of all journal names seen
            * ``years`` — sorted list of all years seen
        """
        dicts = [_paper_to_dict(p) for p in papers]
        by_journal_year: Dict[Tuple[str, int], List[int]] = defaultdict(list)
        paper_id_to_idx: Dict[str, int] = {}
        references_by_citing_year: Dict[int, List[str]] = defaultdict(list)
        journals: set = set()
        years: set = set()
        for idx, d in enumerate(dicts):
            jname = _as_journal_name(d)
            yr = _as_year(d)
            if jname:
                journals.add(jname)
            if yr:
                years.add(yr)
                if jname:
                    by_journal_year[(jname, yr)].append(idx)
            pid = _paper_identifier(d)
            if pid:
                paper_id_to_idx[pid] = idx
            if yr:
                for r in (d.get("references") or []):
                    rid = _normalise_ref_id(r)
                    if rid:
                        references_by_citing_year[yr].append(rid)
        return {
            "papers": dicts,
            "by_journal_year": dict(by_journal_year),
            "paper_id_to_idx": paper_id_to_idx,
            "references_by_citing_year": dict(references_by_citing_year),
            "journals": journals,
            "years": sorted(years),
        }

    # ------------------------------------------------------------------
    # Citation-network helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _citations_to_journal_in_year(
        index: Dict[str, Any],
        journal: str,
        citing_year: int,
        cited_years: Sequence[int],
    ) -> int:
        """Count citations made in ``citing_year`` to any paper published
        in ``journal`` during ``cited_years``.

        The citing side is the union of every paper in the corpus with
        ``year == citing_year``. The cited side is every paper in the
        corpus with ``journal == journal`` and ``year in cited_years``.
        Matches are resolved by paper identifier (DOI / title).
        """
        # Build the set of target paper identifiers.
        target_ids: set = set()
        for y in cited_years:
            for idx in index["by_journal_year"].get((journal, y), []):
                target_ids.add(_paper_identifier(index["papers"][idx]))
        if not target_ids:
            return 0
        # Walk the references of every citing paper in citing_year.
        count = 0
        for ref_id in index["references_by_citing_year"].get(citing_year, []):
            if ref_id in target_ids:
                count += 1
        return count

    @staticmethod
    def _journal_paper_count(
        index: Dict[str, Any],
        journal: str,
        years: Sequence[int],
    ) -> int:
        """Number of papers published in ``journal`` during ``years``."""
        total = 0
        for y in years:
            total += len(index["by_journal_year"].get((journal, y), []))
        return total

    @staticmethod
    def _journal_paper_indices(
        index: Dict[str, Any],
        journal: str,
        years: Optional[Sequence[int]] = None,
    ) -> List[int]:
        """Indices of all papers in ``journal`` (optionally restricted to
        ``years``)."""
        out: List[int] = []
        if years is None:
            keys = [k for k in index["by_journal_year"] if k[0] == journal]
        else:
            keys = [(journal, y) for y in years]
        for k in keys:
            out.extend(index["by_journal_year"].get(k, []))
        return out

    # ------------------------------------------------------------------
    # Impact-factor family
    # ------------------------------------------------------------------

    def impact_factor(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
    ) -> float:
        """Compute the 2-year Journal Impact Factor (IF).

        ``IF(Y) = citations_in_year(Y) to articles published in Y-1 and Y-2
                  / number_of_articles_published_in_Y-1_and_Y-2``

        Args:
            papers: The full corpus of papers (citing + cited).
            journal: Journal name to compute the IF for.
            year: The reporting year (``Y``).

        Returns:
            The 2-year IF (float). Returns ``0.0`` when the journal
            published no articles in the denominator window.
        """
        idx = self._build_index(papers)
        cited_years = (year - 1, year - 2)
        num = self._citations_to_journal_in_year(idx, journal, year, cited_years)
        den = self._journal_paper_count(idx, journal, cited_years)
        if den == 0:
            return 0.0
        return num / den

    def five_year_impact_factor(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
    ) -> float:
        """Compute the 5-year Journal Impact Factor.

        Same as :meth:`impact_factor` but the denominator (and the
        citation-source window) spans ``Y-1 .. Y-5``.

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: The reporting year (``Y``).

        Returns:
            The 5-year IF (float).
        """
        idx = self._build_index(papers)
        cited_years = tuple(range(year - 5, year))
        num = self._citations_to_journal_in_year(idx, journal, year, cited_years)
        den = self._journal_paper_count(idx, journal, cited_years)
        if den == 0:
            return 0.0
        return num / den

    def immediacy_index(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
    ) -> float:
        """Compute the JCR Immediacy Index.

        ``II(Y) = citations_in_year(Y) to articles published_in(Y)
                  / number_of_articles_published_in(Y)``

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: The reporting year (``Y``).

        Returns:
            The immediacy index (float).
        """
        idx = self._build_index(papers)
        num = self._citations_to_journal_in_year(idx, journal, year, [year])
        den = self._journal_paper_count(idx, journal, [year])
        if den == 0:
            return 0.0
        return num / den

    # ------------------------------------------------------------------
    # Eigenfactor family (PageRank over the citation network)
    # ------------------------------------------------------------------

    def _citation_graph(
        self,
        index: Dict[str, Any],
        year_window: Sequence[int],
    ) -> Tuple[List[str], np.ndarray, Dict[str, int]]:
        """Build the paper→paper citation adjacency matrix.

        Only papers whose publication year falls in ``year_window`` are
        kept (Eigenfactor uses a 5-year window). Edge ``i -> j`` means
        paper ``i`` cites paper ``j``.
        """
        window_set = set(year_window)
        nodes: List[str] = []
        node_idx: Dict[str, int] = {}
        for p_idx, d in enumerate(index["papers"]):
            y = _as_year(d)
            if y is None or y not in window_set:
                continue
            pid = _paper_identifier(d)
            if not pid or pid in node_idx:
                continue
            node_idx[pid] = len(nodes)
            nodes.append(pid)
        n = len(nodes)
        if n == 0:
            return nodes, np.zeros((0, 0)), node_idx
        adj = np.zeros((n, n), dtype=np.float64)
        for p_idx, d in enumerate(index["papers"]):
            y = _as_year(d)
            if y is None or y not in window_set:
                continue
            pid = _paper_identifier(d)
            if pid not in node_idx:
                continue
            src = node_idx[pid]
            for r in (d.get("references") or []):
                rid = _normalise_ref_id(r)
                tgt = node_idx.get(rid)
                if tgt is None or tgt == src:
                    continue
                adj[src, tgt] += 1.0
        return nodes, adj, node_idx

    def _pagerank(
        self,
        adj: np.ndarray,
        alpha: float = 0.85,
        max_iter: int = 200,
        tol: float = 1e-6,
    ) -> np.ndarray:
        """Standard power-iteration PageRank over a citation graph."""
        n = adj.shape[0]
        if n == 0:
            return np.zeros(0)
        # Build row-stochastic transition matrix: each paper
        # distributes its "prestige" uniformly across the papers it
        # *cites*.
        out_deg = adj.sum(axis=1)
        # Handle dangling nodes (papers that cite nothing in-window):
        # redistribute their prestige uniformly.
        P = np.zeros_like(adj)
        for i in range(n):
            if out_deg[i] > 0:
                P[i] = adj[i] / out_deg[i]
            else:
                P[i] = 1.0 / n
        # PageRank iteration: r = alpha * P^T r + (1-alpha) * 1/N.
        r = np.full(n, 1.0 / n)
        teleport = np.full(n, (1.0 - alpha) / n)
        for _ in range(max_iter):
            new_r = alpha * (P.T @ r) + teleport
            if np.abs(new_r - r).sum() < tol:
                r = new_r
                break
            r = new_r
        # Normalise so that sum(r) == 1 (Eigenfactor convention).
        s = r.sum()
        if s > 0:
            r = r / s
        return r

    def eigenfactor_score(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
        window: int = 5,
    ) -> float:
        """Compute the Eigenfactor Score for a journal.

        Builds the citation network over the window
        ``[year-window, year-1]`` (Eigenfactor uses the trailing
        5-year window ending the year *before* the reporting year),
        runs PageRank with ``alpha = 0.85`` and dangling-node
        redistribution, then sums the PageRank scores of all papers
        belonging to ``journal``. Per the Eigenfactor convention, the
        total score is multiplied by 100.

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: The reporting year (``Y``).
            window: Number of years in the trailing window
                (default 5).

        Returns:
            The Eigenfactor Score (float, ~0.01-100 scale).
        """
        idx = self._build_index(papers)
        year_window = list(range(year - window, year))
        nodes, adj, node_idx = self._citation_graph(idx, year_window)
        if len(nodes) == 0:
            return 0.0
        pr = self._pagerank(adj)
        score = 0.0
        for pid, p_idx in node_idx.items():
            src_idx = idx["paper_id_to_idx"].get(pid)
            if src_idx is None:
                continue
            d = idx["papers"][src_idx]
            jname = _as_journal_name(d)
            if jname and jname == journal:
                score += pr[p_idx]
        return score * 100.0

    def article_influence_score(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
        window: int = 5,
    ) -> float:
        """Compute the Article Influence Score.

        ``AI = Eigenfactor / (0.01 * num_articles)`` — i.e. the
        per-article Eigenfactor contribution. The AI has roughly the
        same scale as the Impact Factor (mean ≈ 1.0).

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: The reporting year.
            window: Eigenfactor window (default 5).

        Returns:
            The Article Influence Score (float).
        """
        ef = self.eigenfactor_score(papers, journal, year, window=window)
        idx = self._build_index(papers)
        year_window = list(range(year - window, year))
        n = self._journal_paper_count(idx, journal, year_window)
        if n == 0:
            return 0.0
        # Per the Eigenfactor convention, EF is scaled by 100 — so
        # AI = EF / (0.01 * n) keeps AI on the same scale as IF.
        return ef / (0.01 * n)

    # ------------------------------------------------------------------
    # SCImago Journal Rank (SJR) — prestige-weighted iterative
    # ------------------------------------------------------------------

    def scimago_journal_rank(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
        window: int = 3,
        alpha: float = 0.9,
        max_iter: int = 50,
        tol: float = 1e-6,
    ) -> float:
        """Compute the SCImago Journal Rank (SJR) for a journal.

        SJR assigns prestige to journals by running an iterative
        PageRank-like procedure over the journal-level citation
        network: each citation transfers prestige proportional to the
        citing journal's prestige divided by its total citation count.

        This implementation builds a journal × journal citation
        matrix over the trailing ``window`` years, runs the SJR
        iteration, then returns the prestige of ``journal``
        (multiplied by 1000 to match the SCImago scale).

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: The reporting year.
            window: Trailing window in years (default 3, matching
                SCImago's 3-year window).
            alpha: Damping factor (default 0.9).
            max_iter: Maximum iteration count.
            tol: Convergence tolerance.

        Returns:
            The SJR score (float, typically 0.001-15).
        """
        idx = self._build_index(papers)
        year_window = list(range(year - window, year))
        window_set = set(year_window)
        # Build journal × journal citation counts.
        j_count: Dict[str, int] = defaultdict(int)
        j_j_citations: Dict[Tuple[str, str], int] = defaultdict(int)
        for p_idx, d in enumerate(idx["papers"]):
            y = _as_year(d)
            if y is None or y not in window_set:
                continue
            src_j = _as_journal_name(d)
            if not src_j:
                continue
            j_count[src_j] += 1
            for r in (d.get("references") or []):
                rid = _normalise_ref_id(r)
                tgt_pidx = idx["paper_id_to_idx"].get(rid)
                if tgt_pidx is None:
                    continue
                tgt_d = idx["papers"][tgt_pidx]
                tgt_y = _as_year(tgt_d)
                if tgt_y is None or tgt_y not in window_set:
                    continue
                tgt_j = _as_journal_name(tgt_d)
                if not tgt_j or tgt_j == src_j:
                    continue
                j_j_citations[(src_j, tgt_j)] += 1
        journals_list = sorted(j_count.keys())
        n = len(journals_list)
        if n == 0 or journal not in j_count:
            return 0.0
        j_to_pos = {j: i for i, j in enumerate(journals_list)}
        # Transition matrix P[i, j] = citations from i to j / total
        # citations made by i (i.e., column-normalised transposed).
        # SJR convention: prestige flows from citing → cited.
        out_cits = np.zeros(n)
        mat = np.zeros((n, n))
        for (src_j, tgt_j), c in j_j_citations.items():
            i = j_to_pos[src_j]
            j = j_to_pos[tgt_j]
            mat[i, j] = c
            out_cits[i] += c
        # Build column-stochastic P (so that prestige flows cited-side).
        # Each citing journal distributes its prestige across the
        # journals it cites. Dangling (no out-cites) → uniform.
        P = np.zeros_like(mat)
        for i in range(n):
            if out_cits[i] > 0:
                P[i] = mat[i] / out_cits[i]
            else:
                P[i] = 1.0 / n
        # SJR iteration: r = alpha * P^T r + (1-alpha) * uniform.
        r = np.full(n, 1.0 / n)
        teleport = np.full(n, (1.0 - alpha) / n)
        for _ in range(max_iter):
            new_r = alpha * (P.T @ r) + teleport
            if np.abs(new_r - r).sum() < tol:
                r = new_r
                break
            r = new_r
        s = r.sum()
        if s > 0:
            r = r / s
        # Scale: SJR is normalised to a small-number scale (typical
        # values 0.001-15). We multiply by 1000 to bring it onto the
        # familiar SCImago scale (highest ≈ 15).
        return float(r[j_to_pos[journal]]) * 1000.0

    # ------------------------------------------------------------------
    # SNIP (Leydesdorff & Moed)
    # ------------------------------------------------------------------

    def source_normalized_impact_per_paper(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
        window: int = 3,
    ) -> float:
        """Compute the Source-Normalised Impact per Paper (SNIP).

        SNIP normalises the average citations-per-paper of a journal
        by the *citation potential* of its subject field. Here we
        approximate the "subject field" by the set of papers that
        cite the journal's papers in the trailing window — i.e. the
        median citation count across the citing population. The
        indicator is then::

            SNIP = mean_citations_per_journal_paper /
                   median_citations_per_citing_paper

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: The reporting year.
            window: Trailing window (default 3).

        Returns:
            The SNIP score (float, typically 0.5-3).
        """
        idx = self._build_index(papers)
        year_window = list(range(year - window, year))
        # Journal's own papers in the window.
        j_indices = self._journal_paper_indices(idx, journal, year_window)
        if not j_indices:
            return 0.0
        own_cites = [
            _as_citations(idx["papers"][i]) for i in j_indices
        ]
        mean_own = float(np.mean(own_cites)) if own_cites else 0.0
        # Citation potential ≈ median citation count among the citing
        # papers (papers that cite the journal's own papers in window).
        citing_cites: List[int] = []
        for p_idx, d in enumerate(idx["papers"]):
            y = _as_year(d)
            if y is None or y not in set(year_window):
                continue
            cites_any_target = False
            for r in (d.get("references") or []):
                rid = _normalise_ref_id(r)
                tgt_pidx = idx["paper_id_to_idx"].get(rid)
                if tgt_pidx is None:
                    continue
                tgt_d = idx["papers"][tgt_pidx]
                if _as_journal_name(tgt_d) == journal:
                    cites_any_target = True
                    break
            if cites_any_target:
                citing_cites.append(_as_citations(d))
        if not citing_cites:
            return 0.0
        median_citing = float(np.median(citing_cites))
        if median_citing <= 0:
            return 0.0
        return mean_own / median_citing

    # ------------------------------------------------------------------
    # CiteScore (Elsevier) — 4-year aligned numerator & denominator
    # ------------------------------------------------------------------

    def cite_score(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
        window: int = 4,
    ) -> float:
        """Compute the Elsevier CiteScore.

        ``CiteScore(Y) = citations_in_(Y-1..Y-window) to journal's
        articles_published_in_(Y-1..Y-window)
        / number_of_journal_articles_published_in_(Y-1..Y-window)``

        Note the alignment: both numerator and denominator use the
        *same* 4-year window (unlike the Impact Factor which uses a
        2-year lag).

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: The reporting year.
            window: CiteScore window (default 4).

        Returns:
            The CiteScore (float).
        """
        idx = self._build_index(papers)
        window_years = list(range(year - window, year))
        # Citations received in any window-year by any paper of the
        # journal published in any window-year.
        target_ids: set = set()
        for i in self._journal_paper_indices(idx, journal, window_years):
            target_ids.add(_paper_identifier(idx["papers"][i]))
        if not target_ids:
            return 0.0
        num = 0
        for y in window_years:
            for ref_id in idx["references_by_citing_year"].get(y, []):
                if ref_id in target_ids:
                    num += 1
        den = len(target_ids)
        if den == 0:
            return 0.0
        return num / den

    # ------------------------------------------------------------------
    # Hirsch-family indices applied to a journal
    # ------------------------------------------------------------------

    def journal_h_index(
        self,
        papers: Sequence[Any],
        journal: str,
    ) -> int:
        """Compute the Braun et al. journal h-index.

        The journal h-index is the standard Hirsch h-index computed
        over the citation counts of *all* of the journal's papers in
        the corpus.

        Args:
            papers: The full corpus.
            journal: Journal name.

        Returns:
            The journal h-index (int).
        """
        idx = self._build_index(papers)
        cits = [
            _as_citations(idx["papers"][i])
            for i in self._journal_paper_indices(idx, journal)
        ]
        cits.sort(reverse=True)
        h = 0
        for i, c in enumerate(cits, start=1):
            if c >= i:
                h = i
            else:
                break
        return h

    def journal_g_index(
        self,
        papers: Sequence[Any],
        journal: str,
    ) -> int:
        """Compute the journal g-index (Egghe).

        Args:
            papers: The full corpus.
            journal: Journal name.

        Returns:
            The journal g-index (int).
        """
        idx = self._build_index(papers)
        cits = [
            _as_citations(idx["papers"][i])
            for i in self._journal_paper_indices(idx, journal)
        ]
        cits.sort(reverse=True)
        g = 0
        cum = 0
        for i, c in enumerate(cits, start=1):
            cum += c
            if cum >= i * i:
                g = i
            else:
                break
        return g

    def journal_h5_index(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
    ) -> int:
        """Compute the Google Scholar h5-index.

        The h5-index is the Hirsch h-index computed over the journal's
        papers published in the trailing 5-year window ending in
        ``year``.

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: Reporting year (``Y``); h5 uses ``[Y-4, Y]``.

        Returns:
            The h5-index (int).
        """
        idx = self._build_index(papers)
        h5_years = list(range(year - 4, year + 1))
        cits = [
            _as_citations(idx["papers"][i])
            for i in self._journal_paper_indices(idx, journal, h5_years)
        ]
        cits.sort(reverse=True)
        h = 0
        for i, c in enumerate(cits, start=1):
            if c >= i:
                h = i
            else:
                break
        return h

    def journal_h5_median(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
    ) -> int:
        """Compute the Google Scholar h5-median.

        The h5-median is the median citation count of the h5-core
        papers (the top-h5 papers by citation count).

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: Reporting year (``Y``).

        Returns:
            The h5-median (int).
        """
        idx = self._build_index(papers)
        h5_years = list(range(year - 4, year + 1))
        cits = sorted(
            [
                _as_citations(idx["papers"][i])
                for i in self._journal_paper_indices(idx, journal, h5_years)
            ],
            reverse=True,
        )
        h = self.journal_h5_index(papers, journal, year)
        if h == 0:
            return 0
        core = cits[:h]
        if not core:
            return 0
        return int(np.median(core))

    # ------------------------------------------------------------------
    # Quartile
    # ------------------------------------------------------------------

    def journal_quartile(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
        metric: str = "total_citations",
    ) -> str:
        """Assign a JCR-style quartile (Q1..Q4) to a journal.

        The journal is ranked against every other journal in the
        corpus (in the same year) by ``metric``. Journals in the top
        25% receive ``Q1``, next 25% ``Q2``, etc. When the corpus
        contains fewer than four journals, ``Q1`` is returned to the
        top-ranked journal.

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: Reporting year.
            metric: One of ``"total_citations"`` (default),
                ``"impact_factor"``, ``"h5_index"``,
                ``"eigenfactor"``. Determines the ranking variable.

        Returns:
            Quartile label ``"Q1"``, ``"Q2"``, ``"Q3"`` or ``"Q4"``.
            Returns ``"Q4"`` when the journal is not found in the
            corpus.
        """
        idx = self._build_index(papers)
        # Aggregate per-journal metric.
        per_journal: Dict[str, float] = {}
        for jname in idx["journals"]:
            if metric == "total_citations":
                per_journal[jname] = float(sum(
                    _as_citations(idx["papers"][i])
                    for i in self._journal_paper_indices(idx, jname)
                ))
            elif metric == "impact_factor":
                per_journal[jname] = self.impact_factor(papers, jname, year)
            elif metric == "h5_index":
                per_journal[jname] = float(
                    self.journal_h5_index(papers, jname, year)
                )
            elif metric == "eigenfactor":
                per_journal[jname] = self.eigenfactor_score(
                    papers, jname, year,
                )
            else:
                raise ValueError(f"unknown metric: {metric!r}")
        if journal not in per_journal:
            return "Q4"
        ranked = sorted(
            per_journal.items(), key=lambda kv: -kv[1]
        )
        n = len(ranked)
        # Position (1-indexed) of the target journal.
        pos = next(
            i for i, (j, _) in enumerate(ranked) if j == journal
        ) + 1
        if n < 4:
            # With <4 journals, top = Q1, next = Q2, etc.
            q = min(pos, 4)
        else:
            # Quartile boundaries.
            if pos <= n // 4 + (1 if n % 4 else 0):
                q = 1
            elif pos <= n // 2 + (1 if n % 4 >= 2 else 0):
                q = 2
            elif pos <= 3 * n // 4 + (1 if n % 4 >= 3 else 0):
                q = 3
            else:
                q = 4
        return f"Q{q}"

    # ------------------------------------------------------------------
    # All-in-one
    # ------------------------------------------------------------------

    def compute_journal_metrics(
        self,
        papers: Sequence[Any],
        journal: str,
        year: int,
    ) -> Dict[str, Any]:
        """Compute every journal-level indicator in one shot.

        Args:
            papers: The full corpus.
            journal: Journal name.
            year: Reporting year.

        Returns:
            Dict with one key per indicator (``impact_factor``,
            ``five_year_impact_factor``, ``immediacy_index``,
            ``eigenfactor_score``, ``article_influence_score``,
            ``scimago_journal_rank``, ``snip``, ``cite_score``,
            ``journal_h_index``, ``journal_g_index``,
            ``journal_h5_index``, ``journal_h5_median``,
            ``journal_quartile``).
        """
        return {
            "impact_factor": self.impact_factor(papers, journal, year),
            "five_year_impact_factor": self.five_year_impact_factor(
                papers, journal, year,
            ),
            "immediacy_index": self.immediacy_index(papers, journal, year),
            "eigenfactor_score": self.eigenfactor_score(
                papers, journal, year,
            ),
            "article_influence_score": self.article_influence_score(
                papers, journal, year,
            ),
            "scimago_journal_rank": self.scimago_journal_rank(
                papers, journal, year,
            ),
            "snip": self.source_normalized_impact_per_paper(
                papers, journal, year,
            ),
            "cite_score": self.cite_score(papers, journal, year),
            "journal_h_index": self.journal_h_index(papers, journal),
            "journal_g_index": self.journal_g_index(papers, journal),
            "journal_h5_index": self.journal_h5_index(papers, journal, year),
            "journal_h5_median": self.journal_h5_median(papers, journal, year),
            "journal_quartile": self.journal_quartile(papers, journal, year),
        }


# ---------------------------------------------------------------------------
# JournalProfile
# ---------------------------------------------------------------------------

@dataclass
class JournalProfile:
    """Bundle of every journal-level indicator.

    Attributes:
        name: Journal name.
        papers_count: Number of papers in the corpus from this journal.
        total_citations: Sum of citation counts of those papers.
        mean_citations: Mean citations per paper.
        h_index: Braun journal h-index.
        g_index: Journal g-index.
        h5_index: Google Scholar 5-year h-index.
        h5_median: Google Scholar 5-year h-median.
        impact_factor: 2-year JCR IF (for the chosen reporting year).
        five_year_impact_factor: 5-year JCR IF.
        immediacy_index: JCR immediacy index.
        eigenfactor_score: Eigenfactor (×100).
        article_influence_score: Per-article Eigenfactor.
        scimago_journal_rank: SJR (×1000).
        snip: Source-Normalised Impact per Paper.
        cite_score: Elsevier CiteScore.
        quartile: Q1..Q4 label by total-citations ranking.
        first_pub_year: Earliest year the journal published (in corpus).
        last_pub_year: Most recent year.
        extra: Catch-all dict for additional fields.
    """

    name: str = ""
    papers_count: int = 0
    total_citations: int = 0
    mean_citations: float = 0.0
    h_index: int = 0
    g_index: int = 0
    h5_index: int = 0
    h5_median: int = 0
    impact_factor: float = 0.0
    five_year_impact_factor: float = 0.0
    immediacy_index: float = 0.0
    eigenfactor_score: float = 0.0
    article_influence_score: float = 0.0
    scimago_journal_rank: float = 0.0
    snip: float = 0.0
    cite_score: float = 0.0
    quartile: str = "Q4"
    first_pub_year: Optional[int] = None
    last_pub_year: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_papers(
        cls,
        papers: List[Any],
        journal_name: str,
        year: Optional[int] = None,
    ) -> "JournalProfile":
        """Build a :class:`JournalProfile` from a corpus.

        Args:
            papers: The full corpus of papers.
            journal_name: Journal to profile.
            year: Reporting year (defaults to the latest year seen
                in the corpus).

        Returns:
            A populated :class:`JournalProfile`.
        """
        jm = JournalMetrics()
        idx = jm._build_index(papers)
        if year is None:
            years_in_corpus = idx["years"]
            year = max(years_in_corpus) if years_in_corpus else 0
        j_indices = jm._journal_paper_indices(idx, journal_name)
        cits = [_as_citations(idx["papers"][i]) for i in j_indices]
        pub_years = [
            _as_year(idx["papers"][i]) for i in j_indices
        ]
        pub_years = [y for y in pub_years if y]
        metrics = jm.compute_journal_metrics(papers, journal_name, year)
        return cls(
            name=journal_name,
            papers_count=len(j_indices),
            total_citations=int(sum(cits)),
            mean_citations=float(np.mean(cits)) if cits else 0.0,
            h_index=metrics["journal_h_index"],
            g_index=metrics["journal_g_index"],
            h5_index=metrics["journal_h5_index"],
            h5_median=metrics["journal_h5_median"],
            impact_factor=metrics["impact_factor"],
            five_year_impact_factor=metrics["five_year_impact_factor"],
            immediacy_index=metrics["immediacy_index"],
            eigenfactor_score=metrics["eigenfactor_score"],
            article_influence_score=metrics["article_influence_score"],
            scimago_journal_rank=metrics["scimago_journal_rank"],
            snip=metrics["snip"],
            cite_score=metrics["cite_score"],
            quartile=metrics["journal_quartile"],
            first_pub_year=min(pub_years) if pub_years else None,
            last_pub_year=max(pub_years) if pub_years else None,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this profile."""
        from dataclasses import asdict
        return asdict(self)
