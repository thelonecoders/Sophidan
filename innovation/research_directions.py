"""research_directions — strategic research-direction recommender for
the Academic Research Suite.

Converts signals from the rest of the :mod:`innovation` package
(gaps from :mod:`research_lifecycle.ideation`, frontier regions from
:mod:`innovation.frontier_mapping`, forecasts from
:mod:`innovation.trend_forecasting`) into *concrete, scored, runnable*
research directions — each with a title, motivation, expected impact,
novelty / feasibility scores, supporting papers, suggested
collaborators and an estimated duration.

When an LLM client is supplied (e.g.
:class:`ai_assistant.llm_client.LLMClient`), the recommender uses it
to generate richer narrative descriptions; when not, it falls back to
deterministic template-based generation, so the module is fully
functional in offline / echo mode.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import math
import re
import warnings
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass
class ResearchDirection:
    """A concrete research-direction recommendation.

    Attributes:
        title: Short title.
        description: 1-3 sentence description.
        motivation: Why this direction matters now.
        expected_impact: Expected scientific / societal impact (free text).
        novelty_score: Novelty in ``[0, 1]`` (1 = very novel).
        feasibility_score: Feasibility in ``[0, 1]`` (1 = highly feasible).
        supporting_papers: List of :class:`Paper`-like objects that
            motivate this direction.
        keywords: Top keywords characterizing the direction.
        estimated_duration_months: Estimated project duration.
        suggested_collaborators: Suggested author names.
    """

    title: str = ""
    description: str = ""
    motivation: str = ""
    expected_impact: str = ""
    novelty_score: float = 0.0
    feasibility_score: float = 0.0
    supporting_papers: List[Any] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    estimated_duration_months: int = 12
    suggested_collaborators: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        d = asdict(self)
        d["supporting_papers"] = [
            (p.to_dict() if hasattr(p, "to_dict") else p)
            for p in self.supporting_papers
        ]
        return d


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


def _top_keywords(papers: Sequence[Any], top_n: int = 5) -> List[str]:
    """Return the top-N most common keywords across ``papers``."""
    from collections import Counter
    c: Counter = Counter()
    for p in papers:
        for k in (getattr(p, "keywords", []) or []):
            if k:
                c[str(k)] += 1
    return [k for k, _ in c.most_common(top_n)]


def _top_authors(papers: Sequence[Any], top_n: int = 3) -> List[str]:
    """Return the top-N most-prolific authors across ``papers``."""
    from collections import Counter
    c: Counter = Counter()
    for p in papers:
        for a in (getattr(p, "authors", []) or []):
            if a:
                c[str(a)] += 1
    return [a for a, _ in c.most_common(top_n)]


# ---------------------------------------------------------------------------
# ResearchDirectionRecommender
# ---------------------------------------------------------------------------


class ResearchDirectionRecommender:
    """Recommends concrete research directions from heterogeneous signals."""

    DEFAULT_DURATION_MONTHS = 12

    def __init__(
        self,
        papers: Sequence[Any],
        llm_client: Any = None,
    ) -> None:
        """Initialize the recommender.

        Args:
            papers: Sequence of :class:`Paper`-like objects used as the
                background corpus for collaborator / supporting-paper
                selection.
            llm_client: Optional LLM client (any object exposing a
                ``complete(prompt: str) -> str`` or
                ``chat(messages) -> str`` API, e.g.
                :class:`ai_assistant.llm_client.LLMClient`). When
                ``None``, deterministic template-based generation is
                used.
        """
        self.papers: List[Any] = list(papers)
        self.llm_client = llm_client
        self.logger = logger

    # ------------------------------------------------------------------
    # LLM helpers
    # ------------------------------------------------------------------

    def _llm_complete(self, prompt: str) -> str:
        """Call the LLM (if any) to complete a prompt; else return ''."""
        if self.llm_client is None:
            return ""
        try:
            if hasattr(self.llm_client, "complete"):
                return str(self.llm_client.complete(prompt) or "")
            if hasattr(self.llm_client, "chat"):
                return str(
                    self.llm_client.chat(
                        [{"role": "user", "content": prompt}],
                    ) or "",
                )
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("LLM call failed (%s); falling back to templates.", exc)
        return ""

    # ------------------------------------------------------------------
    # Public recommend_directions
    # ------------------------------------------------------------------

    def recommend_directions(
        self,
        topic: str,
        count: int = 5,
    ) -> List[ResearchDirection]:
        """Generate concrete research directions for a topic.

        Uses the background corpus to find under-explored sub-areas,
        combines that with template-based (or LLM-augmented) narrative
        generation, and returns at most ``count`` directions sorted by
        a composite novelty × feasibility score.

        Args:
            topic: Topic string to focus on.
            count: Maximum number of directions.

        Returns:
            List of :class:`ResearchDirection`.
        """
        if not self.papers:
            return []
        topic_lower = topic.lower()
        matching = [
            p for p in self.papers
            if topic_lower in [str(k).lower() for k in (getattr(p, "keywords", []) or [])]
            or topic_lower in [str(f).lower() for f in (getattr(p, "fields_of_study", []) or [])]
            or topic_lower in (getattr(p, "title", "") or "").lower()
        ]
        if not matching:
            matching = list(self.papers)
        # Find under-explored keyword combinations within matching papers.
        gaps = self._detect_sub_area_gaps(matching, topic)
        if not gaps:
            # Fallback: take top-N supporting papers by citation count.
            supporting = sorted(
                matching,
                key=lambda p: -(getattr(p, "citations_count", 0) or 0),
            )[:5]
            gaps = [{
                "title": f"Novel investigation of {topic}",
                "motivation": (
                    f"The corpus contains {len(matching)} papers on '{topic}', "
                    "suggesting an active but heterogeneous area."
                ),
                "papers": supporting,
                "keywords": _top_keywords(matching, 3) or [topic],
                "novelty": 0.5,
                "feasibility": 0.6,
            }]
        directions: List[ResearchDirection] = []
        for gap in gaps[:count]:
            direction = self._build_direction(topic, gap)
            directions.append(direction)
        directions.sort(
            key=lambda d: -(d.novelty_score * 0.5 + d.feasibility_score * 0.5),
        )
        return directions

    def _detect_sub_area_gaps(
        self,
        papers: Sequence[Any],
        topic: str,
    ) -> List[Dict[str, Any]]:
        """Detect under-explored sub-areas by keyword co-occurrence analysis."""
        from collections import Counter
        if not papers:
            return []
        # Pair all keywords; count how many papers cover each pair.
        pair_counts: Counter = Counter()
        single_counts: Counter = Counter()
        for p in papers:
            kws = sorted({str(k).lower() for k in (getattr(p, "keywords", []) or []) if k})
            for kw in kws:
                single_counts[kw] += 1
            for i in range(len(kws)):
                for j in range(i + 1, len(kws)):
                    pair_counts[(kws[i], kws[j])] += 1
        if not pair_counts:
            return []
        # Find pairs that are RARE given their individual frequencies.
        # Expected: p(a) * p(b) * N; observed: pair_counts[(a,b)].
        n = len(papers)
        gaps: List[Dict[str, Any]] = []
        seen_topics: set = set()
        for (a, b), obs in pair_counts.most_common():
            p_a = single_counts[a] / n
            p_b = single_counts[b] / n
            expected = p_a * p_b * n
            # An "under-explored" pair is one with observed < expected * 0.5
            # (significantly fewer co-occurrences than chance would predict).
            if expected < 0.5 or obs > expected * 0.5:
                continue
            # Gather supporting papers (those with EITHER keyword, ordered
            # by recency).
            supp = sorted(
                [p for p in papers
                 if a in [str(k).lower() for k in (getattr(p, "keywords", []) or [])]
                 or b in [str(k).lower() for k in (getattr(p, "keywords", []) or [])]],
                key=lambda p: -(_safe_year(p) or 0),
            )[:5]
            key = f"{a}+{b}"
            if key in seen_topics:
                continue
            seen_topics.add(key)
            # Novelty: 1 - (observed / expected), clipped to [0, 1].
            novelty = float(max(0.0, min(1.0, 1.0 - obs / max(expected, 0.5))))
            # Feasibility: based on availability of supporting papers.
            feasibility = float(min(1.0, len(supp) / 5.0))
            title = f"Bridge {a} and {b} in {topic}"
            motivation = (
                f"Keywords '{a}' and '{b}' co-occur in only {obs} of "
                f"{n} papers on '{topic}' ({expected:.1f} expected by chance), "
                f"suggesting an under-explored intersection."
            )
            gaps.append({
                "title": title,
                "motivation": motivation,
                "papers": supp,
                "keywords": [a, b],
                "novelty": novelty,
                "feasibility": feasibility,
            })
            if len(gaps) >= 10:
                break
        return gaps

    def _build_direction(
        self,
        topic: str,
        gap: Dict[str, Any],
    ) -> ResearchDirection:
        """Build a :class:`ResearchDirection` from a gap dict."""
        title = gap.get("title", f"Research on {topic}")
        motivation = gap.get("motivation", "")
        supporting = gap.get("papers", [])
        keywords = gap.get("keywords", []) or [topic]
        novelty = float(gap.get("novelty", 0.5))
        feasibility = float(gap.get("feasibility", 0.5))

        # LLM-augmented description & expected impact (if client available).
        description = self._generate_description(topic, gap)
        expected_impact = self._generate_impact(topic, gap)

        # Estimated duration: longer for more novel directions.
        duration = int(6 + novelty * 18)  # 6-24 months
        # Suggested collaborators: top authors of supporting papers.
        suggested = _top_authors(supporting, 3)

        return ResearchDirection(
            title=title,
            description=description,
            motivation=motivation,
            expected_impact=expected_impact,
            novelty_score=novelty,
            feasibility_score=feasibility,
            supporting_papers=supporting,
            keywords=keywords,
            estimated_duration_months=duration,
            suggested_collaborators=suggested,
        )

    def _generate_description(self, topic: str, gap: Dict[str, Any]) -> str:
        """Generate a 1-3 sentence description, via LLM if available."""
        keywords = gap.get("keywords", [])
        papers = gap.get("papers", [])
        motivation = gap.get("motivation", "")
        if self.llm_client is not None:
            prompt = (
                f"You are a senior research advisor. A gap analysis on the "
                f"topic '{topic}' identified an under-explored direction with "
                f"keywords {keywords}. Motivation: {motivation}\n"
                f"Write a 1-3 sentence concrete research-direction description."
            )
            text = self._llm_complete(prompt)
            if text:
                return text.strip()
        # Template-based fallback.
        kw_str = ", ".join(keywords[:3]) if keywords else topic
        n_supp = len(papers)
        return (
            f"Investigate the intersection of {kw_str} within {topic}. "
            f"Build on {n_supp} existing paper(s) and develop new methods or "
            f"empirical studies that explicitly combine these threads. "
            f"Target outputs: 1-2 publications in 12-18 months."
        )

    def _generate_impact(self, topic: str, gap: Dict[str, Any]) -> str:
        """Generate an expected-impact statement."""
        if self.llm_client is not None:
            prompt = (
                f"In one sentence, describe the expected scientific / societal "
                f"impact of a research project on '{topic}' focused on "
                f"keywords {gap.get('keywords', [])}."
            )
            text = self._llm_complete(prompt)
            if text:
                return text.strip()
        novelty = gap.get("novelty", 0.5)
        if novelty >= 0.7:
            qualifier = "high-impact, paradigm-shifting"
        elif novelty >= 0.4:
            qualifier = "moderate-impact, community-advancing"
        else:
            qualifier = "incremental, consolidating"
        return (
            f"Expected impact: a {qualifier} contribution to the {topic} "
            "community with potential for cross-disciplinary follow-on work."
        )

    # ------------------------------------------------------------------
    # Converters from other signals
    # ------------------------------------------------------------------

    def from_gaps(
        self,
        gaps: Sequence[Any],
    ) -> List[ResearchDirection]:
        """Convert :class:`ResearchGap` objects into research directions.

        Args:
            gaps: Sequence of objects with ``title``, ``description``,
                ``supporting_papers`` (optional), and ``keywords``
                (optional) attributes (or matching dict keys).

        Returns:
            List of :class:`ResearchDirection`.
        """
        directions: List[ResearchDirection] = []
        for gap in gaps:
            title = self._get_attr(gap, "title") or self._get_attr(gap, "description") or "Untitled gap"
            description = self._get_attr(gap, "description", "")
            supporting = self._get_attr(gap, "supporting_papers", []) or []
            keywords = self._get_attr(gap, "keywords", []) or []
            novelty = float(self._get_attr(gap, "novelty_score", 0.5) or 0.5)
            feasibility = float(self._get_attr(gap, "feasibility_score", 0.5) or 0.5)
            direction = ResearchDirection(
                title=title,
                description=description,
                motivation=self._get_attr(gap, "motivation", "") or description,
                expected_impact=self._generate_impact(
                    ", ".join(keywords[:2]) or "research",
                    {"keywords": keywords, "novelty": novelty},
                ),
                novelty_score=novelty,
                feasibility_score=feasibility,
                supporting_papers=list(supporting),
                keywords=list(keywords),
                estimated_duration_months=int(6 + novelty * 18),
                suggested_collaborators=_top_authors(supporting, 3),
            )
            directions.append(direction)
        return directions

    def from_frontier(
        self,
        frontiers: Sequence[Any],
    ) -> List[ResearchDirection]:
        """Convert :class:`FrontierRegion` objects into directions.

        Args:
            frontiers: Sequence of :class:`FrontierRegion`-like objects.

        Returns:
            List of :class:`ResearchDirection`.
        """
        directions: List[ResearchDirection] = []
        for fr in frontiers:
            title = f"Explore frontier: {', '.join(self._get_attr(fr, 'keywords', [])[:3]) or self._get_attr(fr, 'id', 'frontier')}"
            keywords = self._get_attr(fr, "keywords", []) or []
            supporting = self._get_attr(fr, "representative_papers", []) or []
            novelty = float(self._get_attr(fr, "novelty_score", 0.5) or 0.5)
            growth = float(self._get_attr(fr, "growth_rate", 0.0) or 0.0)
            feasibility = float(min(1.0, 0.5 + growth * 0.5))
            direction = ResearchDirection(
                title=title,
                description=(
                    f"Pursue research in an emerging frontier region "
                    f"(novelty={novelty:.2f}, growth={growth:.2f}). "
                    f"Build on {len(supporting)} representative paper(s)."
                ),
                motivation=(
                    f"This frontier was identified as a sparse but growing "
                    f"sub-area with keywords: {keywords}."
                ),
                expected_impact=self._generate_impact(
                    ", ".join(keywords[:2]) or "frontier",
                    {"keywords": keywords, "novelty": novelty},
                ),
                novelty_score=novelty,
                feasibility_score=feasibility,
                supporting_papers=list(supporting),
                keywords=list(keywords),
                estimated_duration_months=int(6 + novelty * 18),
                suggested_collaborators=_top_authors(supporting, 3),
            )
            directions.append(direction)
        return directions

    def from_trends(
        self,
        trends: Sequence[Any],
    ) -> List[ResearchDirection]:
        """Convert :class:`Forecast` objects into directions.

        Args:
            trends: Sequence of :class:`Forecast`-like objects (with
                ``topic``, ``method``, ``r2``, ``mae``, and forecast
                series).

        Returns:
            List of :class:`ResearchDirection`.
        """
        directions: List[ResearchDirection] = []
        for fc in trends:
            topic = self._get_attr(fc, "topic", "trend") or "trend"
            method = self._get_attr(fc, "method", "") or ""
            r2 = float(self._get_attr(fc, "r2", 0.0) or 0.0)
            mae = float(self._get_attr(fc, "mae", 0.0) or 0.0)
            hist = self._get_attr(fc, "historical_data", None)
            forecast = self._get_attr(fc, "forecast_data", None)
            try:
                last_hist = float(list(hist.values())[-1]) if hist is not None and len(hist) > 0 else 0.0
                avg_fc = float(np.mean(list(forecast.values()))) if forecast is not None and len(forecast) > 0 else 0.0
            except Exception:  # pragma: no cover - defensive
                last_hist, avg_fc = 0.0, 0.0
            growth = (avg_fc - last_hist) / max(last_hist, 1.0) if last_hist else 0.0
            title = f"Ride the growth trend of '{topic}'"
            description = (
                f"Forecast for '{topic}' (method={method}, R²={r2:.2f}, "
                f"MAE={mae:.2f}) predicts {growth:+.1%} growth over the "
                f"forecast horizon."
            )
            motivation = (
                f"Trend analysis indicates a {'rising' if growth > 0 else 'declining'} "
                f"trajectory for '{topic}'."
            )
            direction = ResearchDirection(
                title=title,
                description=description,
                motivation=motivation,
                expected_impact=self._generate_impact(
                    topic, {"keywords": [topic], "novelty": 0.4},
                ),
                novelty_score=0.4,
                feasibility_score=float(min(1.0, max(0.0, r2))),
                supporting_papers=[],
                keywords=[topic],
                estimated_duration_months=12,
                suggested_collaborators=[],
            )
            directions.append(direction)
        return directions

    def combine_signals(
        self,
        gaps: Optional[Sequence[Any]] = None,
        frontiers: Optional[Sequence[Any]] = None,
        trends: Optional[Sequence[Any]] = None,
        top_n: int = 10,
    ) -> List[ResearchDirection]:
        """Integrate signals from gaps, frontiers and trends.

        Each signal source contributes directions which are then merged,
        de-duplicated by keyword overlap, and re-scored.

        Args:
            gaps: Optional sequence of :class:`ResearchGap`.
            frontiers: Optional sequence of :class:`FrontierRegion`.
            trends: Optional sequence of :class:`Forecast`.
            top_n: Maximum number of merged directions.

        Returns:
            Sorted list of :class:`ResearchDirection`.
        """
        combined: List[ResearchDirection] = []
        if gaps:
            combined.extend(self.from_gaps(gaps))
        if frontiers:
            combined.extend(self.from_frontier(frontiers))
        if trends:
            combined.extend(self.from_trends(trends))
        # Deduplicate by Jaccard similarity on keywords (keep highest-scoring).
        deduped: List[ResearchDirection] = []
        for d in combined:
            is_dup = False
            for existing in deduped:
                jac = _jaccard(set(d.keywords), set(existing.keywords))
                if jac >= 0.5:
                    # Replace if new direction scores higher.
                    if (d.novelty_score + d.feasibility_score >
                            existing.novelty_score + existing.feasibility_score):
                        deduped.remove(existing)
                        deduped.append(d)
                    is_dup = True
                    break
            if not is_dup:
                deduped.append(d)
        deduped.sort(
            key=lambda d: -(d.novelty_score * 0.5 + d.feasibility_score * 0.5),
        )
        return deduped[:top_n]

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(
        self,
        direction: ResearchDirection,
        criteria: Optional[Dict[str, float]] = None,
    ) -> ResearchDirection:
        """Re-score a direction under user-supplied weighting.

        Args:
            direction: The direction to re-score.
            criteria: Optional dict with weights for ``"novelty"``,
                ``"feasibility"``, ``"impact"`` (default equal weights).
                Updates ``novelty_score`` and ``feasibility_score`` in
                place; ``impact`` is stored on
                ``expected_impact`` (prefixed).

        Returns:
            The (mutated) :class:`ResearchDirection`.
        """
        criteria = criteria or {}
        w_novelty = float(criteria.get("novelty", 1.0))
        w_feasibility = float(criteria.get("feasibility", 1.0))
        w_impact = float(criteria.get("impact", 1.0))
        total_w = w_novelty + w_feasibility + w_impact or 1.0
        # Re-normalize the existing novelty/feasibility.
        # Impact weight is recorded as a prefix on expected_impact.
        composite = (
            w_novelty * direction.novelty_score
            + w_feasibility * direction.feasibility_score
            + w_impact * 0.5  # default mid-impact if not separately measured
        ) / total_w
        # Re-scale novelty & feasibility proportionally to composite.
        if composite > 0:
            scale = composite / max(direction.novelty_score + direction.feasibility_score, 0.001)
            direction.novelty_score = float(min(1.0, direction.novelty_score * scale))
            direction.feasibility_score = float(min(1.0, direction.feasibility_score * scale))
        impact_prefix = f"[impact weight={w_impact:.2f}] "
        if not direction.expected_impact.startswith("[impact"):
            direction.expected_impact = impact_prefix + direction.expected_impact
        return direction

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def visualize_roadmap(
        self,
        directions: Sequence[ResearchDirection],
        figsize: Tuple[int, int] = (14, 8),
    ) -> Any:
        """Render a Gantt-style roadmap of research directions.

        Each direction is drawn as a horizontal bar; bar length is the
        direction's estimated duration; bar color encodes the composite
        novelty × feasibility score (yellow → green).

        Args:
            directions: Sequence of :class:`ResearchDirection`.
            figsize: Figure size.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        import matplotlib.pyplot as plt  # lazy
        _configure_fonts()
        if not directions:
            fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
            ax.text(0.5, 0.5, "No directions to visualize",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            return fig
        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
        cmap = plt.cm.get_cmap("YlGn")
        for i, d in enumerate(directions):
            composite = (d.novelty_score + d.feasibility_score) / 2.0
            color = cmap(composite)
            ax.barh(
                i, d.estimated_duration_months,
                left=0, height=0.6,
                color=color, edgecolor="black", linewidth=0.4,
            )
            # Truncate title for readability.
            label = d.title if len(d.title) <= 60 else d.title[:57] + "..."
            ax.text(
                d.estimated_duration_months + 0.3, i,
                f"  {label}  (N={d.novelty_score:.2f}, F={d.feasibility_score:.2f})",
                va="center", fontsize=8,
            )
        ax.set_yticks(range(len(directions)))
        ax.set_yticklabels([f"D{i+1}" for i in range(len(directions))], fontsize=8)
        ax.set_xlabel("Duration (months)")
        ax.set_title("Research direction roadmap")
        ax.invert_yaxis()
        ax.grid(True, axis="x", alpha=0.3)
        return fig

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
        """Get an attribute or dict-key, falling back to ``default``."""
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)


# ---------------------------------------------------------------------------
# Helpers exposed at module level
# ---------------------------------------------------------------------------


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets in ``[0, 1]``."""
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


__all__ = [
    "ResearchDirection",
    "ResearchDirectionRecommender",
]
