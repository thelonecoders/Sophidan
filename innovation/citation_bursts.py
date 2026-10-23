"""citation_bursts — Kleinberg-style burst detection for the
Academic Research Suite.

This module implements Jon Kleinberg's burst-detection automaton
(Kleinberg 2002, "Bursty and Hierarchical Structure in Streams")
adapted for academic-citation data, and exposes a small high-level
:class:`CitationBurstDetector` that applies it to four kinds of
entities — papers, authors, keywords, journals — plus arbitrary
topics produced by an external topic model.

The core algorithm models a temporal stream of integer counts (e.g.
the yearly citation count of a single paper) as the output of a hidden
Markov model whose discrete states represent increasing levels of
"burstiness". A dynamic-programming pass finds the minimum-cost
state sequence and contiguous runs of elevated states are reported
as :class:`Burst` objects.

The implementation is intentionally pure-Python + ``numpy``: it lazily
imports ``pandas`` and ``matplotlib`` only when callers actually need
dataframes or figures, so the module is importable on minimal
installs.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass
class Burst:
    """A single detected burst.

    Attributes:
        entity_id: Stable identifier of the entity that burst (paper DOI,
            author name, keyword string, journal name, topic id).
        entity_name: Human-readable label for display.
        entity_type: ``"paper"`` | ``"author"`` | ``"keyword"`` |
            ``"journal"`` | ``"topic"``.
        start_year: First year of the burst (inclusive).
        end_year: Last year of the burst (inclusive).
        peak_year: Year of maximum intensity inside the burst.
        strength: Peak burst-state level reached (a positive float;
            higher = stronger burst).
        duration: ``end_year - start_year + 1`` (integer years).
        total_burst_score: Sum of per-year state levels over the burst
            interval — useful for ranking bursts of different lengths.
        source: Provenance of the underlying series: ``"data"`` when the
            burst was computed from real per-year citation history,
            ``"synthetic-ramp"`` when a caller explicitly opted into a
            synthesized ramp (``allow_synthetic_ramp=True``).
    """

    entity_id: str = ""
    entity_name: str = ""
    entity_type: str = ""
    start_year: int = 0
    end_year: int = 0
    peak_year: int = 0
    strength: float = 0.0
    duration: int = 0
    total_burst_score: float = 0.0
    source: str = "data"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Core Kleinberg burst-detection automaton
# ---------------------------------------------------------------------------


def _kleinberg_bursts(
    counts: Sequence[float],
    years: Sequence[int],
    s: float = 2.0,
    gamma: float = 1.0,
    threshold: float = 2.0,
) -> List[Burst]:
    """Run Kleinberg's burst-detection automaton on a single series.

    Args:
        counts: Per-time-step non-negative count values (e.g. citations
            *received* each year).
        years: Parallel year labels for each step.
        s: Burst-rate scaling parameter (each state's expected rate is
            ``s``× the previous). Defaults to ``2.0`` as in the paper.
        gamma: Transition-cost multiplier (controls how hard it is to
            *enter* a higher, bursty state). Defaults to ``1.0``.
        threshold: Minimum burst-state level to report a burst (a real
            Kleinberg state index, not a count). Bursts that never
            exceed this level are filtered out.

    Returns:
        A list of :class:`Burst` objects (possibly empty).
    """
    counts = [float(c) for c in counts]
    years = list(years)
    n = len(counts)
    if n == 0:
        return []

    total = float(sum(counts))
    if total <= 0:
        # No activity -> no bursts.
        return []

    # Average rate (base rate of state 0).
    base_rate = total / n
    if base_rate <= 0:
        return []

    # Determine the number of states needed.  We add states until the
    # expected rate of the top state exceeds the maximum observed count
    # — going higher than that adds no information because the
    # emission likelihood would be ~1 for every count value.
    max_count = max(counts)
    max_level = 1
    while base_rate * (s ** max_level) < max_count and max_level < 12:
        max_level += 1
    levels = list(range(max_level + 1))  # 0..max_level
    n_levels = len(levels)

    # Expected rate for each state.
    rates = np.array([base_rate * (s ** lvl) for lvl in levels], dtype=np.float64)
    rates = np.maximum(rates, 1e-9)

    # Transition cost (Kleinberg 2002, eq. 5): entering a HIGHER state —
    # i.e. turning a burst "on" — costs gamma * log(n) per level step;
    # dropping back down is free. Charging upward transitions (not downward
    # ones) prevents spurious state flapping and matches the original paper.
    logn = math.log(max(n, 2)) if n > 1 else 1.0

    def trans_cost(i: int, j: int) -> float:
        if j > i:
            return (j - i) * gamma * logn
        return 0.0

    # Emission cost (negative log-likelihood under Poisson(rates[l])).
    def emit_cost(level: int, count: float) -> float:
        r = rates[level]
        # -log(Poisson(count | r)) = -(count*log(r) - r - lgamma(count+1)).
        if count <= 0:
            # -log(P(0 | r)) = r  (P(0|r)=exp(-r)).
            return float(r)
        try:
            return float(-(count * math.log(r) - r))
        except (ValueError, OverflowError):
            return 1e12

    # DP forward pass: cost[t][l] = min cost of being in state l at time t.
    # The stream is PINNED to state 0 at t=0 (the unbursty state), so any
    # burst must pay its upward transition cost.
    cost = np.full((n, n_levels), np.inf, dtype=np.float64)
    back = np.zeros((n, n_levels), dtype=np.int32)
    cost[0, 0] = emit_cost(0, counts[0])
    for t in range(1, n):
        for j in levels:
            best_cost = math.inf
            best_i = 0
            for i in levels:
                c = cost[t - 1, i] + trans_cost(i, j)
                if c < best_cost:
                    best_cost = c
                    best_i = i
            cost[t, j] = best_cost + emit_cost(j, counts[t])
            back[t, j] = best_i

    # Backtrack the optimal state path.
    path = np.zeros(n, dtype=np.int32)
    path[-1] = int(np.argmin(cost[-1]))
    for t in range(n - 2, -1, -1):
        path[t] = back[t + 1, path[t + 1]]

    # Extract contiguous runs at level >= threshold_level.  Strength
    # is reported as the *rate multiplier* ``s ** level`` (i.e. how many
    # times the baseline rate the burst reached), which makes the
    # ``threshold`` parameter interpretable as "minimum rate multiplier"
    # (e.g. threshold=2.0 with s=2 means: report bursts that reach at
    # least state 1, whose rate is 2x baseline).
    threshold_level: float = 0.0
    if threshold > 0:
        threshold_level = math.log(threshold) / math.log(s) if s > 1 else 0.0

    bursts: List[Burst] = []
    in_burst = False
    start_t = 0
    peak_level = 0  # integer state index of the peak
    peak_year = years[0]
    level_sum = 0.0  # sum of s**level over burst interval
    for t in range(n):
        lvl = int(path[t])
        rate_mult = float(s ** lvl)
        if lvl >= threshold_level:
            if not in_burst:
                in_burst = True
                start_t = t
                peak_level = lvl
                peak_year = years[t]
                level_sum = rate_mult
            else:
                level_sum += rate_mult
                if lvl > peak_level:
                    peak_level = lvl
                    peak_year = years[t]
        else:
            if in_burst:
                bursts.append(
                    _make_burst(
                        years[start_t], years[t - 1], peak_year,
                        float(s ** peak_level), level_sum,
                    )
                )
                in_burst = False
    if in_burst:
        bursts.append(
            _make_burst(
                years[start_t], years[n - 1], peak_year,
                float(s ** peak_level), level_sum,
            )
        )
    return bursts


def _make_burst(
    start_year: int, end_year: int, peak_year: int,
    peak_level: float, level_sum: float,
) -> Burst:
    """Construct a Burst with computed duration."""
    duration = max(1, end_year - start_year + 1)
    return Burst(
        start_year=start_year,
        end_year=end_year,
        peak_year=peak_year,
        strength=float(peak_level),
        duration=duration,
        total_burst_score=float(level_sum),
    )


# ---------------------------------------------------------------------------
# Per-year citation history extraction
# ---------------------------------------------------------------------------


def _normalize_yearly_series(
    val: Any, start_year: Optional[int]
) -> Dict[int, float]:
    """Normalize a per-year citation history into ``{year: count}``.

    Accepts a ``{year: count}`` mapping (any key type) or an ordered list of
    annual counts (Semantic Scholar ``citationCountByYear`` style), which is
    anchored at ``start_year`` when provided. Values are interpreted as
    citations *received* in each year (per-year counts), matching the
    upstream API semantics.
    """
    out: Dict[int, float] = {}
    if isinstance(val, dict):
        for k, v in val.items():
            try:
                y = int(str(k).strip()[:4])
                c = float(v)
            except (TypeError, ValueError):
                continue
            if c >= 0:
                out[y] = c
        return out
    if isinstance(val, (list, tuple)):
        if start_year is None:
            return {}
        try:
            start = int(start_year)
        except (TypeError, ValueError):
            return {}
        for i, v in enumerate(val):
            try:
                c = float(v)
            except (TypeError, ValueError):
                continue
            if c >= 0:
                out[start + i] = c
    return out


def _paper_yearly_citations(paper: Any) -> Dict[int, float]:
    """Extract the paper's real per-year citation history, if provided.

    Checks, in order: ``citations_by_year``, ``citation_count_by_year``
    attributes, then the same keys inside the ``raw`` scraper payload
    (``citationCountByYear`` is Semantic Scholar's spelling). Returns an
    empty dict when no real history exists — callers must NOT fabricate a
    synthetic ramp from the cumulative total by default.
    """
    start_year = getattr(paper, "year", None)
    for attr in ("citations_by_year", "citation_count_by_year"):
        val = getattr(paper, attr, None)
        if val:
            series = _normalize_yearly_series(val, start_year)
            if series:
                return series
    raw = getattr(paper, "raw", None)
    if isinstance(raw, dict):
        for key in (
            "citations_by_year",
            "citation_count_by_year",
            "citationCountByYear",
            "citationsByYear",
        ):
            val = raw.get(key)
            if val:
                series = _normalize_yearly_series(val, start_year)
                if series:
                    return series
    return {}


# ---------------------------------------------------------------------------
# High-level detector
# ---------------------------------------------------------------------------


ENTITY_PAPER = "paper"
ENTITY_AUTHOR = "author"
ENTITY_KEYWORD = "keyword"
ENTITY_JOURNAL = "journal"
ENTITY_TOPIC = "topic"


class CitationBurstDetector:
    """High-level burst detector for academic-citation data.

    Wraps :func:`_kleinberg_bursts` and exposes one method per entity
    type, plus helpers for aggregation, dataframes and visualization.
    """

    def __init__(self, s: float = 2.0, gamma: float = 1.0) -> None:
        """Initialize the detector.

        Args:
            s: Burst-rate scaling parameter passed to the automaton.
            gamma: Transition-cost multiplier passed to the automaton.
        """
        self.s = float(s)
        self.gamma = float(gamma)
        self.logger = logger

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _year_range(papers: Sequence[Any]) -> Optional[Tuple[int, int]]:
        """Return ``(min_year, max_year)`` across ``papers`` or ``None``."""
        years = [int(p.year) for p in papers if p.year is not None]
        if not years:
            return None
        return min(years), max(years)

    @staticmethod
    def _build_year_axis(
        papers: Sequence[Any],
        time_window: int = 1,
    ) -> Tuple[List[int], Dict[int, List[int]]]:
        """Return ``(years, year_to_idx)`` indexed by ``time_window``."""
        yr = CitationBurstDetector._year_range(papers)
        if yr is None:
            return [], {}
        min_y, max_y = yr
        if time_window <= 0:
            time_window = 1
        years = list(range(min_y, max_y + 1, time_window))
        idx = {y: i for i, y in enumerate(years)}
        return years, idx

    @staticmethod
    def _bucket_year(year: Optional[int], time_window: int = 1) -> Optional[int]:
        """Floor a year to the nearest ``time_window`` boundary."""
        if year is None:
            return None
        if time_window <= 1:
            return int(year)
        return (int(year) // time_window) * time_window

    # ------------------------------------------------------------------
    # Public per-entity detection
    # ------------------------------------------------------------------

    def detect_papers(
        self,
        papers: Sequence[Any],
        time_window: int = 1,
        threshold: float = 2.0,
        allow_synthetic_ramp: bool = False,
    ) -> List[Burst]:
        """Detect citation bursts for individual papers from *real* data.

        For each paper we run the automaton on its **per-year citation
        history** — citations received each year — when the paper provides
        one (``citations_by_year`` / ``citation_count_by_year`` attributes,
        or the same keys in the ``raw`` scraper payload such as Semantic
        Scholar's ``citationCountByYear``). Years without data count as
        zero.

        Papers that only expose a *cumulative* citation total (the common
        case for Semantic Scholar / OpenAlex / Crossref list endpoints) are
        **skipped by default** with a logged note: synthesizing a per-year
        ramp from a single cumulative number fabricates temporal structure
        that does not exist in the data and used to make every paper
        "burst". Callers who explicitly want the legacy behaviour can pass
        ``allow_synthetic_ramp=True``; bursts produced that way are clearly
        marked with ``source="synthetic-ramp"``.

        Args:
            papers: Sequence of :class:`Paper`-like objects.
            time_window: Bucket size in years (1 = annual).
            threshold: Minimum burst-state level to report.
            allow_synthetic_ramp: Opt-in to the legacy synthetic linear ramp
                for papers without real per-year history (results are
                labelled ``source="synthetic-ramp"``).

        Returns:
            List of :class:`Burst` objects, one per paper with a
            detected burst.
        """
        years_axis, _ = self._build_year_axis(papers, time_window)
        if not years_axis:
            return []
        # The analysis window must extend to the newest year covered by the
        # papers' per-year citation histories (which can be later than the
        # newest publication year in the corpus).
        histories: Dict[int, Dict[int, float]] = {}
        hist_max_year = 0
        for p in papers:
            if p.year is None:
                continue
            h = _paper_yearly_citations(p)
            if h:
                histories[id(p)] = h
                hist_max_year = max(hist_max_year, max(h.keys()))
        max_year = max(max(years_axis), hist_max_year)

        bursts: List[Burst] = []
        skipped_no_history = 0
        synthetic_used = 0
        for p in papers:
            if p.year is None:
                continue
            pub_year = self._bucket_year(p.year, time_window)
            if pub_year is None or pub_year > max_year:
                continue

            source = "data"
            hist = histories.get(id(p))
            if hist:
                year_labels = list(range(pub_year, max_year + 1, time_window))
                counts = [float(hist.get(y, 0.0)) for y in year_labels]
            elif allow_synthetic_ramp:
                total = float(p.citations_count or 0)
                if total <= 0:
                    continue
                span = max(1, max_year - pub_year + 1)
                weights = np.arange(1, span + 1, dtype=np.float64)
                weights /= weights.sum()
                cumulative = total * np.cumsum(weights)
                counts = np.diff(np.concatenate([[0.0], cumulative]))
                year_labels = list(range(pub_year, max_year + 1, time_window))
                if len(year_labels) < len(counts):
                    counts = counts[: len(year_labels)]
                elif len(year_labels) > len(counts):
                    year_labels = year_labels[: len(counts)]
                source = "synthetic-ramp"
                synthetic_used += 1
            else:
                skipped_no_history += 1
                continue

            if len(counts) < 2:
                continue
            ent_bursts = _kleinberg_bursts(
                counts.tolist() if isinstance(counts, np.ndarray) else counts,
                year_labels,
                s=self.s, gamma=self.gamma, threshold=threshold,
            )
            for b in ent_bursts:
                b.entity_id = p.doi or p.title or ""
                b.entity_name = p.title or b.entity_id
                b.entity_type = ENTITY_PAPER
                b.source = source
            bursts.extend(ent_bursts)

        if skipped_no_history:
            logger.info(
                "detect_papers: skipped %d paper(s) with no per-year citation "
                "history (cumulative totals only) — no synthetic ramp was "
                "fabricated. Pass allow_synthetic_ramp=True to opt in to "
                "labelled synthetic series.",
                skipped_no_history,
            )
        if synthetic_used:
            logger.warning(
                "detect_papers: %d burst(s) derived from explicitly-requested "
                "synthetic ramps (source='synthetic-ramp').",
                synthetic_used,
            )
        return bursts

    def detect_authors(
        self,
        papers: Sequence[Any],
        time_window: int = 1,
        threshold: float = 2.0,
    ) -> List[Burst]:
        """Detect bursts in an author's yearly publication count.

        Args:
            papers: Sequence of :class:`Paper`-like objects.
            time_window: Year bucket size.
            threshold: Minimum burst-state level.

        Returns:
            List of :class:`Burst` objects, one per author that burst.
        """
        years_axis, _ = self._build_year_axis(papers, time_window)
        if not years_axis:
            return []
        # author -> list of (year_bucket)
        author_years: Dict[str, List[int]] = {}
        for p in papers:
            for a in (p.authors or []):
                if not a:
                    continue
                yb = self._bucket_year(p.year, time_window)
                if yb is None:
                    continue
                author_years.setdefault(a, []).append(yb)

        bursts: List[Burst] = []
        for author, ys in author_years.items():
            if not ys:
                continue
            min_y, max_y = min(ys), max(ys)
            axis = list(range(min(min_y, min(years_axis)),
                              max(max_y, max(years_axis)) + 1,
                              time_window))
            counts = [0] * len(axis)
            for y in ys:
                if y in axis:
                    counts[axis.index(y)] += 1
            if sum(counts) < 2 or len(counts) < 2:
                continue
            ent_bursts = _kleinberg_bursts(
                counts, axis,
                s=self.s, gamma=self.gamma, threshold=threshold,
            )
            for b in ent_bursts:
                b.entity_id = author
                b.entity_name = author
                b.entity_type = ENTITY_AUTHOR
            bursts.extend(ent_bursts)
        return bursts

    def detect_keywords(
        self,
        papers: Sequence[Any],
        field: str = "keywords",
        time_window: int = 1,
        threshold: float = 2.0,
    ) -> List[Burst]:
        """Detect bursts in keyword (or fields-of-study) usage.

        Args:
            papers: Sequence of :class:`Paper`-like objects.
            field: ``"keywords"`` or ``"fields_of_study"`` (or any other
                list-valued attribute on :class:`Paper`).
            time_window: Year bucket size.
            threshold: Minimum burst-state level.

        Returns:
            List of :class:`Burst` objects, one per keyword that burst.
        """
        years_axis, _ = self._build_year_axis(papers, time_window)
        if not years_axis:
            return []
        kw_years: Dict[str, List[int]] = {}
        for p in papers:
            values = getattr(p, field, None) or []
            if not values:
                continue
            yb = self._bucket_year(p.year, time_window)
            if yb is None:
                continue
            for v in values:
                if not v:
                    continue
                kw_years.setdefault(str(v), []).append(yb)

        bursts: List[Burst] = []
        for kw, ys in kw_years.items():
            if not ys:
                continue
            min_y, max_y = min(ys), max(ys)
            axis = list(range(min(min_y, min(years_axis)),
                              max(max_y, max(years_axis)) + 1,
                              time_window))
            counts = [0] * len(axis)
            for y in ys:
                if y in axis:
                    counts[axis.index(y)] += 1
            if sum(counts) < 2 or len(counts) < 2:
                continue
            ent_bursts = _kleinberg_bursts(
                counts, axis,
                s=self.s, gamma=self.gamma, threshold=threshold,
            )
            for b in ent_bursts:
                b.entity_id = kw
                b.entity_name = kw
                b.entity_type = ENTITY_KEYWORD
            bursts.extend(ent_bursts)
        return bursts

    def detect_journals(
        self,
        papers: Sequence[Any],
        time_window: int = 1,
        threshold: float = 2.0,
    ) -> List[Burst]:
        """Detect bursts in publications per journal.

        Args:
            papers: Sequence of :class:`Paper`-like objects.
            time_window: Year bucket size.
            threshold: Minimum burst-state level.

        Returns:
            List of :class:`Burst` objects, one per journal that burst.
        """
        years_axis, _ = self._build_year_axis(papers, time_window)
        if not years_axis:
            return []
        j_years: Dict[str, List[int]] = {}
        for p in papers:
            j = getattr(p, "journal", None)
            if not j:
                continue
            yb = self._bucket_year(p.year, time_window)
            if yb is None:
                continue
            j_years.setdefault(j, []).append(yb)
        bursts: List[Burst] = []
        for j, ys in j_years.items():
            if not ys:
                continue
            min_y, max_y = min(ys), max(ys)
            axis = list(range(min(min_y, min(years_axis)),
                              max(max_y, max(years_axis)) + 1,
                              time_window))
            counts = [0] * len(axis)
            for y in ys:
                if y in axis:
                    counts[axis.index(y)] += 1
            if sum(counts) < 2 or len(counts) < 2:
                continue
            ent_bursts = _kleinberg_bursts(
                counts, axis,
                s=self.s, gamma=self.gamma, threshold=threshold,
            )
            for b in ent_bursts:
                b.entity_id = j
                b.entity_name = j
                b.entity_type = ENTITY_JOURNAL
            bursts.extend(ent_bursts)
        return bursts

    def detect_topics(
        self,
        papers: Sequence[Any],
        topic_model: Any,
        time_window: int = 1,
        threshold: float = 2.0,
    ) -> List[Burst]:
        """Detect bursts in topic prevalence over time.

        Args:
            papers: Sequence of :class:`Paper`-like objects.
            topic_model: An object exposing a ``doc_topic_matrix``
                attribute (numpy array of shape
                ``(len(papers), n_topics)``) and a ``topics`` list of
                dicts with ``id`` and ``top_words`` keys, e.g. a
                fitted :class:`data_science.topic_modeler.TopicModel`.
            time_window: Year bucket size.
            threshold: Minimum burst-state level.

        Returns:
            List of :class:`Burst` objects, one per topic that burst.
        """
        years_axis, _ = self._build_year_axis(papers, time_window)
        if not years_axis:
            return []
        doc_topic = getattr(topic_model, "doc_topic_matrix", None)
        if doc_topic is None or len(doc_topic) != len(papers):
            return []
        topics_meta = getattr(topic_model, "topics", []) or []
        n_topics = doc_topic.shape[1]

        # topic_id -> list of (year_bucket, weight)
        topic_yearly: Dict[int, List[float]] = {t: [0.0] * len(years_axis)
                                                for t in range(n_topics)}
        for paper_idx, p in enumerate(papers):
            yb = self._bucket_year(p.year, time_window)
            if yb is None or yb not in years_axis:
                continue
            yi = years_axis.index(yb)
            row = doc_topic[paper_idx]
            for t in range(n_topics):
                topic_yearly[t][yi] += float(row[t])

        bursts: List[Burst] = []
        for t in range(n_topics):
            counts = topic_yearly[t]
            if sum(c for c in counts if c > 0) < 2 or len(counts) < 2:
                continue
            ent_bursts = _kleinberg_bursts(
                counts, years_axis,
                s=self.s, gamma=self.gamma, threshold=threshold,
            )
            meta = topics_meta[t] if t < len(topics_meta) else {}
            label = " ".join(meta.get("top_words", [])[:3]) or f"topic_{t}"
            for b in ent_bursts:
                b.entity_id = str(meta.get("id", t))
                b.entity_name = label
                b.entity_type = ENTITY_TOPIC
            bursts.extend(ent_bursts)
        return bursts

    # ------------------------------------------------------------------
    # Aggregation / DataFrame / visualization
    # ------------------------------------------------------------------

    def aggregate_bursts(self, bursts: Sequence[Burst]) -> Any:
        """Aggregate bursts into a per-entity summary dataframe.

        Args:
            bursts: Sequence of :class:`Burst` objects.

        Returns:
            ``pandas.DataFrame`` with columns ``entity_id``,
            ``entity_name``, ``entity_type``, ``num_bursts``,
            ``max_strength``, ``total_score``, ``earliest_year``,
            ``latest_year``.
        """
        import pandas as pd  # lazy
        if not bursts:
            return pd.DataFrame(
                columns=["entity_id", "entity_name", "entity_type",
                         "num_bursts", "max_strength", "total_score",
                         "earliest_year", "latest_year"],
            )
        rows: List[Dict[str, Any]] = []
        groups: Dict[Tuple[str, str], List[Burst]] = {}
        for b in bursts:
            groups.setdefault((b.entity_id, b.entity_type), []).append(b)
        for (eid, etype), group_bursts in groups.items():
            rows.append({
                "entity_id": eid,
                "entity_name": group_bursts[0].entity_name,
                "entity_type": etype,
                "num_bursts": len(group_bursts),
                "max_strength": max(b.strength for b in group_bursts),
                "total_score": sum(b.total_burst_score for b in group_bursts),
                "earliest_year": min(b.start_year for b in group_bursts),
                "latest_year": max(b.end_year for b in group_bursts),
            })
        return pd.DataFrame(rows).sort_values(
            ["total_score", "max_strength"], ascending=False,
        ).reset_index(drop=True)

    def to_dataframe(self, bursts: Sequence[Burst]) -> Any:
        """Convert a list of bursts into a flat dataframe.

        Args:
            bursts: Sequence of :class:`Burst` objects.

        Returns:
            ``pandas.DataFrame`` with one row per burst.
        """
        import pandas as pd  # lazy
        if not bursts:
            return pd.DataFrame(columns=[
                "entity_id", "entity_name", "entity_type",
                "start_year", "end_year", "peak_year",
                "strength", "duration", "total_burst_score",
            ])
        return pd.DataFrame([b.to_dict() for b in bursts])

    def visualize(
        self,
        bursts: Sequence[Burst],
        figsize: Tuple[int, int] = (12, 8),
    ) -> Any:
        """Render a horizontal-bar timeline of burst periods.

        Bursts are sorted by entity_type / start_year; bar color
        encodes burst strength (yellow → red via a hot colormap).

        Args:
            bursts: Sequence of :class:`Burst` objects.
            figsize: Matplotlib figure size.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        import matplotlib.pyplot as plt  # lazy
        from matplotlib import font_manager  # lazy

        _configure_fonts(font_manager)

        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
        if not bursts:
            ax.text(0.5, 0.5, "No bursts detected", ha="center", va="center",
                    transform=ax.transAxes)
            ax.set_axis_off()
            return fig

        # Sort: by entity_type then start_year then duration.
        sorted_bursts = sorted(
            bursts,
            key=lambda b: (b.entity_type, b.start_year, -b.duration),
        )
        max_strength = max(b.strength for b in sorted_bursts) or 1.0
        # matplotlib >= 3.9 removed plt.cm.get_cmap; use the module-level
        # colormap registry (available since 3.6), with a legacy fallback.
        try:
            import matplotlib as mpl  # lazy
            cmap = mpl.colormaps["YlOrRd"]
        except Exception:  # noqa: BLE001 - very old matplotlib
            cmap = plt.get_cmap("YlOrRd")
        y_positions = []
        labels = []
        for i, b in enumerate(sorted_bursts):
            y = i
            y_positions.append(y)
            labels.append(f"{b.entity_name[:40]} [{b.entity_type}]")
            color = cmap(b.strength / max_strength)
            ax.barh(
                y,
                b.end_year - b.start_year + 1,
                left=b.start_year,
                height=0.7,
                color=color,
                edgecolor="black",
                linewidth=0.4,
            )
            # Mark peak year.
            ax.plot(b.peak_year, y, marker="*", color="black",
                    markersize=8, markeredgecolor="white")

        ax.set_yticks(y_positions)
        ax.set_yticklabels(labels, fontsize=8)
        ax.set_xlabel("Year")
        ax.set_title("Citation bursts timeline")
        ax.invert_yaxis()
        # Colorbar for strength.
        sm = plt.cm.ScalarMappable(
            cmap=cmap,
            norm=plt.Normalize(vmin=0, vmax=max_strength),
        )
        sm.set_array([])
        cbar = fig.colorbar(sm, ax=ax, shrink=0.6, label="Burst strength")
        cbar.ax.yaxis.set_tick_params(labelsize=8)
        return fig


# ---------------------------------------------------------------------------
# Matplotlib font configuration (CJK-aware, matches data_science.visualizations)
# ---------------------------------------------------------------------------


def _configure_fonts(font_manager: Any) -> None:
    """Configure matplotlib rcParams for CJK-aware font fallback.

    Args:
        font_manager: The ``matplotlib.font_manager`` module (passed in
            by callers to avoid a second lazy import).
    """
    try:
        import matplotlib
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


__all__ = [
    "Burst",
    "CitationBurstDetector",
    "ENTITY_PAPER",
    "ENTITY_AUTHOR",
    "ENTITY_KEYWORD",
    "ENTITY_JOURNAL",
    "ENTITY_TOPIC",
]
