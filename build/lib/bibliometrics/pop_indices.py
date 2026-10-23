"""Publish-or-Perish-grade author-level bibliometric indices.

This module re-implements (and substantially extends) the indicator set
exposed by Anne-Wil Harzing's *Publish or Perish* desktop software. Every
public method on :class:`PoPIndices` accepts either a plain ``list`` of
per-paper citation counts or a ``pandas.Series`` and returns a plain
``int`` / ``float`` — there is *no* dependency on Qt, on the database
layer, or on the scraping layer, so the module can be imported in any
headless environment (unit tests, batch jobs, notebooks).

Implemented indicators (all author-level):

================================================  =========================
Indicator                                         Reference
================================================  =========================
``h_index``                                        Hirsch (2005)
``g_index``                                        Egghe (2006)
``i10_index``                                     Google Scholar
``e_index``                                        Zhang (2009)
``contemporary_h_index`` (``hc``)                 Sidiropoulos & Manolopoulos
                                                   (2006)
``age_weighted_citation_rate`` (``AWCR``)         Jin (2007) / PoP
``multi_authored_h_index`` (``hm``)               Schreiber (2008)
``individual_h_index`` (``hi``)                    Batista et al. (2006)
``ar_index``                                       Jin (2007)
``normalized_h_index`` (``m``-quotient)            Hirsch (2005)
``q2_index``                                       PoP extension
``w_index``                                        PoP extension
``h_max_index``                                    PoP extension
================================================  =========================

The :class:`AuthorProfile` dataclass bundles every indicator into a
single object and is constructable directly from a list of
:class:`data_acquisition.base_scraper.Paper` instances via
:meth:`AuthorProfile.from_papers`.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)

# Type alias — citation sequences can be passed as a list of ints or a
# pandas Series. We keep the alias loose (``Any``) to avoid importing
# pandas at module load time (the module must stay importable in
# environments where pandas is absent).
Citations = Union[Sequence[int], Sequence[float], Any]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_sorted_ints(citations: Citations) -> List[int]:
    """Coerce *citations* into a descending-sorted list of ints.

    Accepts lists, tuples, numpy arrays, and pandas Series. ``None``
    values are dropped. Non-numeric entries raise ``ValueError``.

    Args:
        citations: A sequence of per-paper citation counts.

    Returns:
        Sorted-descending list of non-negative integers.
    """
    if citations is None:
        return []
    # pandas Series — use .tolist() to bypass numpy types.
    if hasattr(citations, "tolist"):
        try:
            citations = citations.tolist()
        except Exception:  # pragma: no cover - defensive
            pass
    out: List[int] = []
    for c in citations:
        if c is None:
            continue
        try:
            v = int(c)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError(f"non-numeric citation value: {c!r}") from exc
        if v < 0:
            logger.warning("clamping negative citation count %d to 0", v)
            v = 0
        out.append(v)
    out.sort(reverse=True)
    return out


def _to_ints(citations: Citations) -> List[int]:
    """Same as :func:`_to_sorted_ints` but preserves original order."""
    if citations is None:
        return []
    if hasattr(citations, "tolist"):
        try:
            citations = citations.tolist()
        except Exception:  # pragma: no cover - defensive
            pass
    out: List[int] = []
    for c in citations:
        if c is None:
            out.append(0)
            continue
        try:
            v = int(c)
        except (TypeError, ValueError):
            v = 0
        out.append(max(v, 0))
    return out


def _to_years(years: Optional[Sequence[Any]]) -> List[Optional[int]]:
    """Coerce *years* into a list of ``Optional[int]`` (same length)."""
    if years is None:
        return []
    if hasattr(years, "tolist"):
        try:
            years = years.tolist()
        except Exception:  # pragma: no cover - defensive
            pass
    out: List[Optional[int]] = []
    for y in years:
        if y is None or y == "" :
            out.append(None)
            continue
        try:
            out.append(int(y))
        except (TypeError, ValueError):
            out.append(None)
    return out


def _current_year() -> int:
    """Return the current calendar year (used as ``Y`` for age weighting)."""
    return datetime.now().year


# ---------------------------------------------------------------------------
# PoPIndices
# ---------------------------------------------------------------------------

class PoPIndices:
    """Publish-or-Perish-grade author-level bibliometric indices.

    Every method is a ``@staticmethod`` (or uses no instance state) so
    callers may use the class directly without instantiation::

        >>> PoPIndices.h_index([10, 5, 3, 1, 0])
        3

    …or instantiate it (handy for symmetry with other bibliometric
    classes in this package)::

        >>> idx = PoPIndices()
        >>> idx.compute_all([10, 5, 3, 1, 0])
        {'h_index': 3, 'g_index': 3, ... }
    """

    def __init__(self) -> None:
        self.logger = logger

    # ------------------------------------------------------------------
    # Core Hirsch-family indices
    # ------------------------------------------------------------------

    @staticmethod
    def h_index(citations: Citations) -> int:
        """Compute the Hirsch h-index.

        The h-index is the largest integer ``h`` such that the author
        has ``h`` papers each cited at least ``h`` times.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            The h-index (non-negative integer).
        """
        s = _to_sorted_ints(citations)
        h = 0
        for i, c in enumerate(s, start=1):
            if c >= i:
                h = i
            else:
                break
        return h

    @staticmethod
    def g_index(citations: Citations) -> int:
        """Compute the Egghe g-index.

        The g-index is the largest ``g`` such that the top ``g`` papers
        collectively receive at least ``g**2`` citations.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            The g-index (non-negative integer).
        """
        s = _to_sorted_ints(citations)
        g = 0
        cum = 0
        for i, c in enumerate(s, start=1):
            cum += c
            if cum >= i * i:
                g = i
            else:
                break
        return g

    @staticmethod
    def i10_index(citations: Citations) -> int:
        """Compute Google Scholar's i10-index.

        Counts the number of papers with at least 10 citations.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            The i10-index.
        """
        s = _to_sorted_ints(citations)
        return sum(1 for c in s if c >= 10)

    # ------------------------------------------------------------------
    # Excess & h-core
    # ------------------------------------------------------------------

    @staticmethod
    def h_core(citations: Citations) -> List[int]:
        """Return the citation counts of the papers constituting the h-core.

        The h-core is the set of papers that *exactly* satisfies the
        h-index definition — the top ``h`` papers, each cited at least
        ``h`` times. The returned list is sorted in descending order
        and has length equal to the h-index.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            The citation counts of the h-core papers (descending).
        """
        s = _to_sorted_ints(citations)
        h = PoPIndices.h_index(s)
        return s[:h]

    @staticmethod
    def e_index(citations: Citations) -> float:
        """Compute the Chun-Ting Zhang excess (e) index.

        The e-index quantifies the *excess* citations that lie above
        the h-core — i.e., the citations that would raise the h-index
        if the rank-order constraint were ignored. Formally::

            e = sqrt(sum(c_i - h) for i in 1..h)

        where ``c_i`` is the citation count of the i-th most-cited
        paper and ``h`` is the h-index.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            The e-index (non-negative float). Returns ``0.0`` when
            the h-index is zero.
        """
        s = _to_sorted_ints(citations)
        h = PoPIndices.h_index(s)
        if h == 0:
            return 0.0
        excess = sum(max(c - h, 0) for c in s[:h])
        return math.sqrt(excess)

    # ------------------------------------------------------------------
    # Age-weighted / contemporary indices
    # ------------------------------------------------------------------

    @staticmethod
    def contemporary_h_index(
        citations: Citations,
        years: Sequence[Any],
        decay: float = 0.5,
        current_year: Optional[int] = None,
    ) -> float:
        """Compute the Sidiropoulos & Manolopoulos contemporary h-index (hc).

        Each paper's citation count is weighted by the inverse of its
        age raised to the ``decay`` power::

            c'_i = c_i / (current_year - pub_year_i + 1) ** decay

        Then hc is the h-index of the weighted counts. The original
        paper uses ``decay == 1`` (linear inverse-age weighting); the
        Publish-or-Perish default is ``decay == 0.5`` (square-root
        damping).

        Args:
            citations: Sequence of per-paper citation counts.
            years: Sequence of publication years (same length).
            decay: Exponent applied to the age (default ``0.5``).
            current_year: Override for the current calendar year
                (useful for reproducible tests).

        Returns:
            The contemporary h-index (float, since weights are
            fractional).
        """
        cits = _to_ints(citations)
        yrs = _to_years(years)
        if len(cits) != len(yrs):
            raise ValueError(
                "citations and years must have the same length "
                f"({len(cits)} vs {len(yrs)})"
            )
        cy = current_year if current_year is not None else _current_year()
        weighted = []
        for c, y in zip(cits, yrs):
            if y is None or y <= 0:
                # Unknown year — treat as published this year.
                age = 1
            else:
                age = max(cy - y + 1, 1)
            weighted.append(c / (age ** decay))
        weighted.sort(reverse=True)
        hc = 0.0
        for i, w in enumerate(weighted, start=1):
            if w >= i:
                hc = float(i)
            else:
                break
        return hc

    @staticmethod
    def age_weighted_citation_rate(
        citations: Citations,
        years: Sequence[Any],
        current_year: Optional[int] = None,
    ) -> float:
        """Compute the Age-Weighted Citation Rate (AWCR).

        AWCR distributes each paper's citations across its age (in
        years) and reports the citation rate per paper-year. Following
        Jin (2007) and Publish-or-Perish::

            AWCR = sum(c_i / age_i) / N

        where ``age_i = current_year - pub_year_i + 1`` and ``N`` is
        the number of papers with a known publication year.

        Args:
            citations: Sequence of per-paper citation counts.
            years: Sequence of publication years (same length).
            current_year: Override for the current calendar year.

        Returns:
            The AWCR (non-negative float). Returns ``0.0`` when no
            paper has a known publication year.
        """
        cits = _to_ints(citations)
        yrs = _to_years(years)
        if len(cits) != len(yrs):
            raise ValueError(
                "citations and years must have the same length "
                f"({len(cits)} vs {len(yrs)})"
            )
        cy = current_year if current_year is not None else _current_year()
        num = 0.0
        den = 0
        for c, y in zip(cits, yrs):
            if y is None or y <= 0:
                continue
            age = max(cy - y + 1, 1)
            num += c / age
            den += 1
        if den == 0:
            return 0.0
        return num / den

    # ------------------------------------------------------------------
    # Co-authorship-adjusted indices
    # ------------------------------------------------------------------

    @staticmethod
    def multi_authored_h_index(
        citations: Citations,
        author_counts: Sequence[int],
        m: float = 1.0,
    ) -> float:
        """Compute the Schreiber multi-authored h-index (hm).

        Each paper's citation count is fractionalized by the number
        of co-authors raised to the power ``m``::

            c'_i = c_i / n_i ** m

        where ``n_i`` is the author count of paper ``i``. The hm
        index is then the largest ``h`` such that the sum of the top
        ``h`` fractionalized counts is at least ``h``::

            hm = max { h : sum_{i=1..h} c'_{(i)} >= h }

        The canonical Schreiber (2008) paper uses ``m = 1``.

        Args:
            citations: Sequence of per-paper citation counts.
            author_counts: Sequence of per-paper author counts
                (same length as ``citations``).
            m: Exponent applied to the author count (default ``1.0``).

        Returns:
            The hm-index (float). Returns ``0.0`` when no paper has
            any author information.
        """
        cits = _to_ints(citations)
        if hasattr(author_counts, "tolist"):
            try:
                author_counts = author_counts.tolist()
            except Exception:  # pragma: no cover - defensive
                pass
        if len(cits) != len(author_counts):
            raise ValueError(
                "citations and author_counts must have the same length "
                f"({len(cits)} vs {len(author_counts)})"
            )
        frac = []
        for c, n in zip(cits, author_counts):
            try:
                n_int = max(int(n), 1)
            except (TypeError, ValueError):
                # Unknown author count → treat as single-author.
                n_int = 1
            frac.append(c / (n_int ** m))
        frac.sort(reverse=True)
        hm = 0.0
        cum = 0.0
        for i, f in enumerate(frac, start=1):
            cum += f
            if cum >= i:
                hm = float(i)
            else:
                break
        return hm

    @staticmethod
    def individual_h_index(
        citations: Citations,
        n_papers_total: Union[int, Sequence[int]],
    ) -> float:
        """Compute the Batista et al. individual h-index (hi).

        Normalises the raw h-index for the size of the collaboration
        network behind the h-core::

            hi = h ** 2 / N_a

        where ``N_a`` is the total number of authors credited on the
        ``h`` h-core papers. ``N_a`` may be passed either as a scalar
        (already-aggregated author count) or as a per-paper author
        count sequence — in the latter case the function extracts the
        h-core papers and sums their author counts.

        Args:
            citations: Sequence of per-paper citation counts.
            n_papers_total: Either the total number of authors on the
                h-core papers (scalar ``int``) or a per-paper author
                count sequence (same length as ``citations``).

        Returns:
            The hi-index (float). Returns ``0.0`` when the h-index
            is zero or ``N_a`` is zero.
        """
        s = _to_sorted_ints(citations)
        h = PoPIndices.h_index(s)
        if h == 0:
            return 0.0
        if isinstance(n_papers_total, (list, tuple)):
            if hasattr(n_papers_total, "tolist"):
                try:
                    n_papers_total = n_papers_total.tolist()
                except Exception:  # pragma: no cover - defensive
                    pass
            # Sort author-counts by citation count descending to align
            # with the h-core ordering.
            pairs = sorted(
                zip(_to_ints(citations), n_papers_total),
                key=lambda p: -p[0],
            )
            n_a = 0
            for c, n in pairs[:h]:
                try:
                    n_a += max(int(n), 0)
                except (TypeError, ValueError):
                    pass
        else:
            try:
                n_a = int(n_papers_total)
            except (TypeError, ValueError):
                n_a = 0
        if n_a <= 0:
            return float(h)
        return (h * h) / n_a

    # ------------------------------------------------------------------
    # AR-index (Jin)
    # ------------------------------------------------------------------

    @staticmethod
    def ar_index(
        citations: Citations,
        years: Sequence[Any],
        decay: float = 0.5,
        current_year: Optional[int] = None,
    ) -> float:
        """Compute Jin's AR-index (contemporaneous R-index).

        The AR-index is the square-root of the sum of age-weighted
        citations over the h-core::

            AR = sqrt(sum(c_i / age_i ** decay) for i in h-core)

        with ``age_i = current_year - pub_year_i + 1``.

        Args:
            citations: Sequence of per-paper citation counts.
            years: Sequence of publication years (same length).
            decay: Exponent applied to age (default ``0.5``).
            current_year: Override for the current calendar year.

        Returns:
            The AR-index (non-negative float).
        """
        cits = _to_ints(citations)
        yrs = _to_years(years)
        if len(cits) != len(yrs):
            raise ValueError(
                "citations and years must have the same length "
                f"({len(cits)} vs {len(yrs)})"
            )
        cy = current_year if current_year is not None else _current_year()
        # Pair (citation, age) and sort by citation descending to find
        # the h-core in citation-count order.
        pairs = []
        for c, y in zip(cits, yrs):
            if y is None or y <= 0:
                age = 1
            else:
                age = max(cy - y + 1, 1)
            pairs.append((c, age))
        pairs.sort(key=lambda p: -p[0])
        h = PoPIndices.h_index(cits)
        if h == 0:
            return 0.0
        total = 0.0
        for c, age in pairs[:h]:
            total += c / (age ** decay)
        return math.sqrt(total)

    # ------------------------------------------------------------------
    # m-quotient and PoP-extended simple indices
    # ------------------------------------------------------------------

    @staticmethod
    def normalized_h_index(
        h_index_value: int,
        years_since_first_pub: Union[int, float],
    ) -> float:
        """Compute Hirsch's m-quotient (a.k.a. normalised h-index).

        ``m = h / Y`` where ``Y`` is the number of years elapsed since
        the author's first publication.

        Args:
            h_index_value: The author's h-index.
            years_since_first_pub: Years elapsed since first
                publication (``current_year - first_pub_year``).

        Returns:
            The m-quotient (float). Returns ``0.0`` when the academic
            age is zero or negative.
        """
        try:
            y = float(years_since_first_pub)
        except (TypeError, ValueError):
            return 0.0
        if y <= 0:
            return 0.0
        return float(h_index_value) / y

    @staticmethod
    def q2_index(citations: Citations) -> int:
        """Count papers with at least ``2 * h`` citations.

        Publish-or-Perish exposes this as a "Q2"-style extension: it
        counts the number of papers that exceed twice the h-index
        threshold.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            The Q2 count (non-negative integer).
        """
        s = _to_sorted_ints(citations)
        h = PoPIndices.h_index(s)
        if h == 0:
            return 0
        threshold = 2 * h
        return sum(1 for c in s if c >= threshold)

    @staticmethod
    def w_index(citations: Citations) -> int:
        """Return the citation count of the most-cited paper.

        Publish-or-Perish exposes this as the *w-index* (a.k.a.
        "max citations"). It is simply ``max(citations)``.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            The maximum citation count (non-negative integer).
            Returns ``0`` when the sequence is empty.
        """
        s = _to_sorted_ints(citations)
        if not s:
            return 0
        return s[0]

    @staticmethod
    def h_max_index(citations: Citations) -> float:
        """Compute the theoretical upper-bound h-index (``h_max``).

        ``h_max = sqrt(total_citations)`` — the largest h-index that
        could *possibly* be achieved if every citation were
        distributed evenly across the author's papers. It is a useful
        comparative ceiling for the observed h-index.

        Args:
            citations: Sequence of per-paper citation counts.

        Returns:
            ``sqrt(sum(citations))`` as a float. Returns ``0.0``
            when the sequence is empty.
        """
        s = _to_sorted_ints(citations)
        if not s:
            return 0.0
        total = sum(s)
        return math.sqrt(total)

    # ------------------------------------------------------------------
    # compute_all — single-shot everything
    # ------------------------------------------------------------------

    def compute_all(
        self,
        citations: Citations,
        years: Optional[Sequence[Any]] = None,
        author_counts: Optional[Sequence[int]] = None,
        current_year: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Compute every author-level index in one shot.

        Args:
            citations: Sequence of per-paper citation counts.
            years: Optional sequence of publication years (same
                length as ``citations``). Required for the
                contemporary / age-weighted indices; if ``None`` those
                entries are returned as ``None``.
            author_counts: Optional per-paper author counts. Required
                for ``multi_authored_h_index``; if ``None`` that
                entry is returned as ``None``.
            current_year: Override for the current calendar year
                (useful for reproducible tests).

        Returns:
            Dict with keys for every indicator implemented by this
            class (``h_index``, ``g_index``, ``i10_index``,
            ``e_index``, ``h_core``, ``h_max_index``, ``w_index``,
            ``q2_index``, plus ``contemporary_h_index``,
            ``age_weighted_citation_rate``, ``ar_index`` when
            ``years`` is provided, plus ``multi_authored_h_index``
            when ``author_counts`` is provided).
        """
        cits_list = _to_ints(citations)
        h = PoPIndices.h_index(cits_list)
        out: Dict[str, Any] = {
            "h_index": h,
            "g_index": PoPIndices.g_index(cits_list),
            "i10_index": PoPIndices.i10_index(cits_list),
            "e_index": PoPIndices.e_index(cits_list),
            "h_core": PoPIndices.h_core(cits_list),
            "w_index": PoPIndices.w_index(cits_list),
            "q2_index": PoPIndices.q2_index(cits_list),
            "h_max_index": PoPIndices.h_max_index(cits_list),
            "total_citations": int(sum(cits_list)),
            "n_papers": len(cits_list),
            "max_citations": max(cits_list) if cits_list else 0,
        }
        if years is not None:
            out["contemporary_h_index"] = PoPIndices.contemporary_h_index(
                cits_list, years, current_year=current_year,
            )
            out["age_weighted_citation_rate"] = (
                PoPIndices.age_weighted_citation_rate(
                    cits_list, years, current_year=current_year,
                )
            )
            out["ar_index"] = PoPIndices.ar_index(
                cits_list, years, current_year=current_year,
            )
            yrs = _to_years(years)
            valid_years = [y for y in yrs if y is not None and y > 0]
            if valid_years:
                first_y = min(valid_years)
                last_y = max(valid_years)
                cy = current_year if current_year is not None else _current_year()
                out["first_pub_year"] = first_y
                out["last_pub_year"] = last_y
                out["m_quotient"] = PoPIndices.normalized_h_index(
                    h, cy - first_y + 1,
                )
        if author_counts is not None:
            out["multi_authored_h_index"] = PoPIndices.multi_authored_h_index(
                cits_list, author_counts,
            )
            out["individual_h_index"] = PoPIndices.individual_h_index(
                cits_list, author_counts,
            )
        return out


# ---------------------------------------------------------------------------
# AuthorProfile
# ---------------------------------------------------------------------------

@dataclass
class AuthorProfile:
    """Bundle of every author-level bibliometric indicator.

    Construct an :class:`AuthorProfile` either manually or via
    :meth:`from_papers` which extracts the required citation /
    publication-year / author-count vectors from a list of
    :class:`data_acquisition.base_scraper.Paper` instances.

    Attributes:
        name: Author display name.
        orcid: Optional ORCID iD.
        papers: Number of papers by this author.
        h_index: Hirsch h-index.
        g_index: Egghe g-index.
        e_index: Zhang excess index.
        hc_index: Sidiropoulos contemporary h-index.
        hm_index: Schreiber multi-authored h-index.
        ar_index: Jin AR-index.
        hi_index: Batista individual h-index.
        awcr: Age-weighted citation rate.
        m_quotient: Hirsch m-quotient.
        total_citations: Sum of all citation counts.
        citations_per_paper: Mean citations per paper.
        citations_per_year: Total citations / academic-age.
        first_pub_year: Year of first publication (``None`` if
            unknown).
        last_pub_year: Year of most recent publication (``None``).
    """

    name: str = ""
    orcid: Optional[str] = None
    papers: int = 0
    h_index: int = 0
    g_index: int = 0
    e_index: float = 0.0
    hc_index: float = 0.0
    hm_index: float = 0.0
    ar_index: float = 0.0
    hi_index: float = 0.0
    awcr: float = 0.0
    m_quotient: float = 0.0
    total_citations: int = 0
    citations_per_paper: float = 0.0
    citations_per_year: float = 0.0
    first_pub_year: Optional[int] = None
    last_pub_year: Optional[int] = None
    i10_index: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_papers(
        cls,
        papers: List[Any],
        name: str = "",
        orcid: Optional[str] = None,
        current_year: Optional[int] = None,
    ) -> "AuthorProfile":
        """Build an :class:`AuthorProfile` from a list of ``Paper`` objects.

        The method extracts citation counts, publication years, and
        per-paper author counts (from the ``authors`` list of each
        paper) and delegates to :meth:`PoPIndices.compute_all`.

        Args:
            papers: List of :class:`data_acquisition.base_scraper.Paper`
                objects (duck-typed: any object with attributes
                ``citations_count``, ``year`` and ``authors`` works).
            name: Author display name.
            orcid: Optional ORCID iD.
            current_year: Override for the current calendar year
                (used by the age-weighted indices; useful for tests).

        Returns:
            A populated :class:`AuthorProfile`.
        """
        cits: List[int] = []
        yrs: List[Optional[int]] = []
        author_counts: List[int] = []
        for p in papers:
            try:
                c = int(getattr(p, "citations_count", 0) or 0)
            except (TypeError, ValueError):
                c = 0
            cits.append(max(c, 0))
            y = getattr(p, "year", None)
            try:
                yrs.append(int(y) if y is not None else None)
            except (TypeError, ValueError):
                yrs.append(None)
            authors = getattr(p, "authors", None) or []
            try:
                author_counts.append(len(authors))
            except TypeError:
                author_counts.append(1)

        idx = PoPIndices()
        result = idx.compute_all(
            cits,
            years=yrs if any(y is not None for y in yrs) else None,
            author_counts=author_counts,
            current_year=current_year,
        )

        first_y = result.get("first_pub_year")
        last_y = result.get("last_pub_year")
        cy = current_year if current_year is not None else _current_year()
        academic_age = (
            (cy - first_y + 1) if first_y else 0
        )
        cpp = (
            result["total_citations"] / result["n_papers"]
            if result["n_papers"] else 0.0
        )
        cpy = (
            result["total_citations"] / academic_age
            if academic_age > 0 else 0.0
        )

        return cls(
            name=name,
            orcid=orcid,
            papers=result["n_papers"],
            h_index=result["h_index"],
            g_index=result["g_index"],
            e_index=result["e_index"],
            hc_index=result.get("contemporary_h_index", 0.0),
            hm_index=result.get("multi_authored_h_index", 0.0),
            ar_index=result.get("ar_index", 0.0),
            hi_index=result.get("individual_h_index", 0.0),
            awcr=result.get("age_weighted_citation_rate", 0.0),
            m_quotient=result.get("m_quotient", 0.0),
            total_citations=result["total_citations"],
            citations_per_paper=cpp,
            citations_per_year=cpy,
            first_pub_year=first_y,
            last_pub_year=last_y,
            i10_index=result["i10_index"],
            extra={
                "i10_index": result["i10_index"],
                "w_index": result["w_index"],
                "q2_index": result["q2_index"],
                "h_max_index": result["h_max_index"],
                "h_core": result["h_core"],
            },
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this profile."""
        from dataclasses import asdict
        return asdict(self)
