"""Bibliometric indicators and citation-network statistics.

This module implements standard bibliometric measures used by the Academic
Research Suite: the h-index, i10-index, g-index, per-author and per-journal
aggregates, plus co-citation / co-authorship matrices and a simple
collaboration index. All public functions accept ``data_acquisition.base_scraper.Paper``
objects (or duck-typed objects that expose the same attributes) and return
plain Python types or pandas objects.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import re
from collections import defaultdict
from itertools import combinations
from typing import Any, Iterable, List, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Canonical Paper fields (per project data_acquisition.base_scraper.Paper).
_PAPER_FIELDS: tuple[str, ...] = (
    "title", "authors", "abstract", "year", "doi",
    "citations_count", "references", "keywords", "fields_of_study",
)


def _paper_to_dict(paper: Any) -> dict:
    """Coerce a Paper-like object into a plain dict.

    Accepts dicts, dataclass instances, or duck-typed objects that expose
    the canonical Paper attributes.
    """
    if isinstance(paper, dict):
        return dict(paper)
    try:
        from dataclasses import asdict, is_dataclass

        if is_dataclass(paper) and not isinstance(paper, type):
            return asdict(paper)
    except Exception:  # pragma: no cover - defensive
        pass
    out = {f: getattr(paper, f, None) for f in _PAPER_FIELDS}
    for opt in ("journal", "source", "venue", "publisher"):
        if hasattr(paper, opt):
            out[opt] = getattr(paper, opt)
    return out


def _coerce_list(value: Any) -> list:
    """Coerce arbitrary input to a Python list.

    Handles ``None``, lists, tuples, sets, numpy arrays, and delimited
    strings (``";"``, ``","``, ``"|"``).
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, str):
        parts = re.split(r"[;,|]", value)
        return [p.strip() for p in parts if p.strip()]
    try:
        return list(value)
    except TypeError:
        return [value]


class Bibliometrics:
    """Bibliometric indicator calculator.

    Provides the h-index, i10-index, g-index, per-author aggregates,
    per-journal metrics (impact-factor proxy, h5-index, half-life), the
    collaboration index, and co-citation / co-authorship matrices.
    """

    def __init__(self) -> None:
        self.logger = logger

    # ------------------------------------------------------------------
    # Static indicator helpers
    # ------------------------------------------------------------------

    @staticmethod
    def h_index(citations: Sequence[int]) -> int:
        """Compute the Hirsch h-index.

        The h-index is the largest integer ``h`` such that the author has
        ``h`` papers each cited at least ``h`` times.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            The h-index.
        """
        s = sorted((int(c) for c in citations if c is not None), reverse=True)
        h = 0
        for i, c in enumerate(s, start=1):
            if c >= i:
                h = i
            else:
                break
        return h

    @staticmethod
    def i10_index(citations: Sequence[int]) -> int:
        """Compute Google's i10-index.

        Number of papers with at least 10 citations.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            The i10-index.
        """
        return sum(1 for c in citations if c is not None and int(c) >= 10)

    @staticmethod
    def g_index(citations: Sequence[int]) -> int:
        """Compute the g-index.

        The g-index is the largest ``g`` such that the top ``g`` papers
        collectively receive at least ``g**2`` citations.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            The g-index.
        """
        s = sorted((int(c) for c in citations if c is not None), reverse=True)
        g = 0
        cum = 0
        for i, c in enumerate(s, start=1):
            cum += c
            if cum >= i * i:
                g = i
            else:
                break
        return g

    # ------------------------------------------------------------------
    # Per-author / per-journal
    # ------------------------------------------------------------------

    def author_metrics(self, papers: List[Any]) -> dict:
        """Compute per-author bibliometric indicators.

        Args:
            papers: List of Paper objects.

        Returns:
            Dict keyed by author name. Each value contains:
            ``h_index``, ``i10_index``, ``g_index``, ``total_citations``,
            ``papers``, ``avg_citations``, ``h_index_per_year``,
            ``first_year``, ``last_year``.
        """
        author_cites: dict[str, List[int]] = defaultdict(list)
        author_years: dict[str, set[int]] = defaultdict(set)
        for paper in papers:
            d = _paper_to_dict(paper)
            authors = _coerce_list(d.get("authors"))
            try:
                cites = int(d.get("citations_count") or 0)
            except (TypeError, ValueError):
                cites = 0
            year = d.get("year")
            try:
                year = int(year) if year is not None else None
            except (TypeError, ValueError):
                year = None
            for a in authors:
                if not isinstance(a, str) or not a.strip():
                    continue
                a = a.strip()
                author_cites[a].append(cites)
                if year is not None:
                    author_years[a].add(year)
        out: dict[str, dict] = {}
        for author, clist in author_cites.items():
            h = self.h_index(clist)
            yrs = author_years.get(author)
            span = (max(yrs) - min(yrs) + 1) if yrs else 1
            out[author] = {
                "h_index": h,
                "i10_index": self.i10_index(clist),
                "g_index": self.g_index(clist),
                "total_citations": int(sum(clist)),
                "papers": len(clist),
                "avg_citations": float(np.mean(clist)) if clist else 0.0,
                "h_index_per_year": (h / span) if span else 0.0,
                "first_year": min(yrs) if yrs else None,
                "last_year": max(yrs) if yrs else None,
            }
        return out

    def journal_metrics(self, papers: List[Any]) -> pd.DataFrame:
        """Compute per-journal metrics.

        Args:
            papers: List of Paper objects (must expose ``journal`` /
                ``source`` / ``venue`` / ``publisher`` if available).

        Returns:
            DataFrame indexed by journal, with columns ``papers``,
            ``total_citations``, ``mean_citations`` (IF proxy),
            ``h5_index`` (over the last 5 publication years), and
            ``half_life`` (citation-weighted median age).
        """
        records: List[dict] = []
        for paper in papers:
            d = _paper_to_dict(paper)
            journal = (
                d.get("journal")
                or d.get("source")
                or d.get("venue")
                or d.get("publisher")
            )
            if not journal:
                continue
            try:
                cites = int(d.get("citations_count") or 0)
            except (TypeError, ValueError):
                cites = 0
            try:
                year = int(d.get("year") or 0)
            except (TypeError, ValueError):
                year = 0
            records.append(
                {"journal": str(journal), "citations": cites, "year": year}
            )
        cols = ["journal", "papers", "total_citations",
                "mean_citations", "h5_index", "half_life"]
        if not records:
            return pd.DataFrame(columns=cols).set_index("journal")
        df = pd.DataFrame(records)
        rows = []
        for journal, g in df.groupby("journal"):
            cites = g["citations"].tolist()
            years = g["year"].tolist()
            h5 = self._h5_index(cites, years)
            half_life = self._half_life(cites, years)
            rows.append({
                "journal": journal,
                "papers": len(g),
                "total_citations": int(sum(cites)),
                "mean_citations": float(np.mean(cites)) if cites else 0.0,
                "h5_index": h5,
                "half_life": half_life,
            })
        return pd.DataFrame(rows).set_index("journal").sort_values(
            "total_citations", ascending=False
        )

    @staticmethod
    def _h5_index(cites: Sequence[int], years: Sequence[int]) -> int:
        """Compute h5-index: h-index over the last 5 publication years."""
        if not cites or not years:
            return 0
        valid_years = [int(y) for y in years if y]
        if not valid_years:
            return 0
        max_year = max(valid_years)
        cutoff = max_year - 4
        recent = [int(c) for c, y in zip(cites, years) if y and int(y) >= cutoff]
        if not recent:
            return 0
        return Bibliometrics.h_index(recent)

    @staticmethod
    def _half_life(cites: Sequence[int], years: Sequence[int]) -> float:
        """Approximate citation half-life in years.

        Computed as the citation-weighted median of (max_year - year)
        across the journal's papers. Falls back to an unweighted median
        when citation counts are unavailable.
        """
        if not cites or not years:
            return 0.0
        ys = [int(y) for y in years if y]
        if len(ys) < 2:
            return 0.0
        max_year = ys[-1]
        weighted_ages: List[int] = []
        for c, y in zip(cites, years):
            if y:
                weighted_ages.extend([max_year - int(y)] * max(int(c or 0), 0))
        if not weighted_ages:
            ages = [max_year - y for y in ys]
            return float(np.median(ages))
        return float(np.median(weighted_ages))

    # ------------------------------------------------------------------
    # Collaboration metrics
    # ------------------------------------------------------------------

    def collaboration_index(self, papers: List[Any]) -> float:
        """Compute the collaboration index.

        Defined as the average number of authors per paper
        (total authorships / total papers). Single-author papers
        contribute 1 to the numerator.

        Args:
            papers: List of Paper objects.

        Returns:
            The collaboration index (>= 0).
        """
        if not papers:
            return 0.0
        total_authors = 0
        n_papers = 0
        for paper in papers:
            d = _paper_to_dict(paper)
            authors = _coerce_list(d.get("authors"))
            if authors:
                total_authors += len(authors)
                n_papers += 1
        if n_papers == 0:
            return 0.0
        return total_authors / n_papers

    def co_citation_matrix(self, papers: List[Any]) -> pd.DataFrame:
        """Build a symmetric co-citation count matrix.

        Two cited identifiers X and Y are co-cited whenever some paper in
        the dataset cites both. We scan every paper's ``references`` list
        and increment the (X, Y) entry for every co-occurring pair.

        Args:
            papers: List of Paper objects (each must expose a
                ``references`` list of cited identifiers).

        Returns:
            Symmetric DataFrame indexed by cited identifier with integer
            co-citation counts. Returns an empty DataFrame if no
            references are present.
        """
        pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        ids_seen: set[str] = set()
        for paper in papers:
            d = _paper_to_dict(paper)
            refs = _coerce_list(d.get("references"))
            refs = sorted({str(r).strip() for r in refs if r and str(r).strip()})
            ids_seen.update(refs)
            for a, b in combinations(refs, 2):
                pair_counts[(a, b)] += 1
        ids = sorted(ids_seen)
        if not ids:
            return pd.DataFrame()
        mat = pd.DataFrame(0, index=ids, columns=ids, dtype=int)
        for (a, b), c in pair_counts.items():
            mat.loc[a, b] = c
            mat.loc[b, a] = c
        return mat

    def co_authorship_matrix(self, papers: List[Any]) -> pd.DataFrame:
        """Build a symmetric co-authorship count matrix.

        Args:
            papers: List of Paper objects.

        Returns:
            Symmetric DataFrame indexed by author name with integer
            co-authorship counts. Returns an empty DataFrame if no
            authors are present.
        """
        pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        authors_seen: set[str] = set()
        for paper in papers:
            d = _paper_to_dict(paper)
            authors = _coerce_list(d.get("authors"))
            authors = sorted({
                str(a).strip() for a in authors
                if a and str(a).strip()
            })
            authors_seen.update(authors)
            for a, b in combinations(authors, 2):
                pair_counts[(a, b)] += 1
        authors = sorted(authors_seen)
        if not authors:
            return pd.DataFrame()
        mat = pd.DataFrame(0, index=authors, columns=authors, dtype=int)
        for (a, b), c in pair_counts.items():
            mat.loc[a, b] = c
            mat.loc[b, a] = c
        return mat
