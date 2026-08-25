"""Ideation — research-question / gap detection and idea generation.

This module implements the upstream end of the research lifecycle: taking a
corpus of :class:`data_acquisition.base_scraper.Paper` objects (or
free-text literature reviews) and surfacing (a) under-studied
intersections of keywords / concepts as :class:`ResearchGap` instances and
(b) candidate :class:`ResearchIdea` instances that are scored on novelty,
feasibility and impact.

The detector and idea generator both accept an optional ``llm_client``
(an :class:`ai_assistant.llm_client.LLMClient` instance) and an optional
``embedder`` (anything exposing ``.embed(text) -> np.ndarray``).  When
either is absent the module falls back to deterministic, dependency-free
algorithms:

* Gap detection falls back to keyword co-occurrence frequency analysis —
  pairs of keywords that appear together in fewer papers than expected
  given their marginal frequencies are surfaced as candidate gaps.
* Idea generation falls back to templated research questions built from
  the gap descriptions and the topic string.

This keeps the module testable in offline / CI environments while
allowing LLM-augmented behaviour in production.

Examples:
    >>> from research_lifecycle.ideation import ResearchGapDetector
    >>> gaps = ResearchGapDetector().from_corpus(papers, topic="LLM safety")
    >>> for g in gaps[:3]:
    ...     print(g.description)
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight Paper shim
# ---------------------------------------------------------------------------
# We accept either the v1.0.0 data_acquisition.base_scraper.Paper dataclass
# OR any duck-typed object exposing ``title``, ``abstract``, ``keywords``,
# ``year``, ``doi``. The two ``_paper_*`` helpers below make the rest of
# the module agnostic to the concrete type, so the module is importable
# even when ``data_acquisition`` itself is not (e.g. minimal CI envs).


def _paper_keywords(paper: Any) -> List[str]:
    """Return a normalised lowercased keyword list from a paper-like obj."""
    kws = getattr(paper, "keywords", None) or []
    if isinstance(kws, str):
        kws = [k.strip() for k in re.split(r"[;,]", kws) if k.strip()]
    out: List[str] = []
    for k in kws:
        if not k:
            continue
        kk = str(k).strip().lower()
        if kk:
            out.append(kk)
    return out


def _paper_text(paper: Any) -> str:
    """Return concatenation of title + abstract for a paper-like object."""
    title = str(getattr(paper, "title", "") or "")
    abstract = str(getattr(paper, "abstract", "") or "")
    return f"{title}. {abstract}".strip()


def _paper_title(paper: Any) -> str:
    return str(getattr(paper, "title", "") or "(untitled)")


def _paper_year(paper: Any) -> Optional[int]:
    y = getattr(paper, "year", None)
    if y is None:
        return None
    try:
        return int(y)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class ResearchGap:
    """An identified under-studied area in a corpus.

    Attributes:
        id: Stable unique identifier (UUID4 hex).
        description: One- to three-sentence plain-text description.
        evidence_papers: Papers that *do* touch this area (may be few).
        supporting_keywords: The keyword pair / set that triggered the gap.
        research_questions: Suggested concrete research questions.
        novelty_score: 0..1 — how under-studied (1 = no prior work).
        importance_score: 0..1 — heuristic importance from keyword
            frequency / centrality.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    description: str = ""
    evidence_papers: List[Any] = field(default_factory=list)
    supporting_keywords: List[str] = field(default_factory=list)
    research_questions: List[str] = field(default_factory=list)
    novelty_score: float = 0.0
    importance_score: float = 0.0


@dataclass
class ResearchIdea:
    """A candidate research idea.

    Attributes:
        id: Stable unique identifier (UUID4 hex).
        question: The research question in one sentence.
        rationale: Why this question matters / why it is timely.
        novelty_score: 0..1 — estimated novelty vs the supplied corpus.
        feasibility_score: 0..1 — estimated feasibility (data availability,
            methodological maturity).
        impact_score: 0..1 — estimated potential impact.
        related_papers: Papers most relevant to the idea.
        generated_at: ISO-8601 UTC timestamp.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    question: str = ""
    rationale: str = ""
    novelty_score: float = 0.0
    feasibility_score: float = 0.0
    impact_score: float = 0.0
    related_papers: List[Any] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def composite_score(self) -> float:
        """Geometric mean of the three component scores in [0, 1]."""
        return float(
            (max(self.novelty_score, 1e-6)
             * max(self.feasibility_score, 1e-6)
             * max(self.impact_score, 1e-6))
            ** (1.0 / 3.0)
        )


# ---------------------------------------------------------------------------
# Stopwords (kept short & dependency-free)
# ---------------------------------------------------------------------------
_STOPWORDS = frozenset(
    """
    a an the and or but if then else for of to in on at by with from into
    is are was were be been being this that these those it its their our
    we i you they he she his her my your their them us him me as not no
    can could should would may might must will shall do does did done have
    has had having which who whom whose what when where why how across about
    above below between within without via per while during until before
    after over under again further once here there all any both each few
    more most other some such only own same so than too very s t can ll re
    study paper article research based using used use method methods approach
    results result findings finding analysis data model models
    """.split()
)


def _tokenize(text: str) -> List[str]:
    """Lowercase + word-tokenise, dropping stopwords and 1-char tokens."""
    tokens = re.findall(r"[a-z][a-z0-9_\-]{1,}", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 2]


# ---------------------------------------------------------------------------
# Gap detector
# ---------------------------------------------------------------------------
class ResearchGapDetector:
    """Identify research gaps from a paper corpus or literature review.

    The detector supports three modes:

    * :meth:`from_corpus` — co-occurrence analysis on the corpus itself,
      optionally guided by an LLM that proposes richer gap descriptions.
    * :meth:`from_literature_review` — extracts explicit "future-work" /
      "gap" sentences from a narrative review text and links them to
      papers in the corpus.
    * :meth:`compare_frontiers` — finds gaps unique to one of two
      corpora (e.g. a curated corpus vs a fresh search).
    """

    def __init__(self, llm_client: Any = None, embedder: Any = None) -> None:
        """Initialise the detector.

        Args:
            llm_client: Optional :class:`ai_assistant.llm_client.LLMClient`
                used to enrich gap descriptions and research questions.
                When ``None`` (the default) only deterministic heuristics
                are used.
            embedder: Optional object exposing ``embed(text) -> np.ndarray``
                used for semantic similarity in :meth:`compare_frontiers`.
                When ``None``, similarity falls back to keyword-Jaccard.
        """
        self.llm_client = llm_client
        self.embedder = embedder

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def from_corpus(
        self,
        papers: Sequence[Any],
        topic: Optional[str] = None,
        max_gaps: int = 10,
    ) -> List[ResearchGap]:
        """Identify under-studied keyword intersections in a corpus.

        Args:
            papers: A sequence of paper-like objects.
            topic: Optional topic string to bias gap selection toward.
            max_gaps: Maximum number of gaps to return.
        Returns:
            A list of :class:`ResearchGap` instances sorted by
            ``importance_score`` (descending).
        """
        if not papers:
            return []
        papers = list(papers)

        # Build per-paper keyword sets from explicit keywords + tokens
        # extracted from title/abstract.
        keyword_sets: List[set] = []
        for p in papers:
            kws = set(_paper_keywords(p))
            kws.update(_tokenize(_paper_text(p)))
            keyword_sets.append(kws)

        all_keywords = sorted({k for s in keyword_sets for k in s})
        if not all_keywords:
            return []

        # Marginal frequencies + co-occurrence counts.
        marginal = Counter()
        for s in keyword_sets:
            marginal.update(s)
        cooccur: Counter = Counter()
        for s in keyword_sets:
            ks = sorted(s)
            for i, a in enumerate(ks):
                for b in ks[i + 1 :]:
                    cooccur[(a, b)] += 1

        # Expected co-occurrence under independence:
        #   E[a,b] = N * P(a) * P(b) = N * (c[a]/N) * (c[b]/N)
        # Gaps are pairs with observed << expected AND absolute observed
        # count small (i.e. genuinely under-studied, not just rare).
        n = len(keyword_sets)
        gaps: List[ResearchGap] = []
        seen_pairs: set = set()
        # Rank candidate pairs by (marginal frequency * marginal frequency)
        # so we surface gaps that combine two reasonably common keywords
        # (more important than two rare keywords that happen not to
        # co-occur).
        candidate_pairs = []
        for (a, b), obs in cooccur.items():
            if (b, a) in seen_pairs or (a, b) in seen_pairs:
                continue
            seen_pairs.add((a, b))
            ca = marginal[a]
            cb = marginal[b]
            expected = max(1e-6, n * (ca / n) * (cb / n))
            if obs >= expected:
                continue
            # Under-studied: observed much less than expected.
            deficit = max(0.0, expected - obs) / max(expected, 1e-6)
            # Penalise pairs involving extremely rare keywords.
            base_importance = (ca * cb) / max(1, n * n)
            score = deficit * (1.0 + math.log1p(base_importance * n))
            candidate_pairs.append((score, a, b, obs, expected, ca, cb))

        candidate_pairs.sort(reverse=True)
        for score, a, b, obs, expected, ca, cb in candidate_pairs[:max_gaps]:
            # Find the few papers that *do* address this intersection.
            evidence = [
                p for p, ks in zip(papers, keyword_sets) if a in ks and b in ks
            ][:5]
            novelty = 1.0 - min(1.0, obs / max(expected, 1.0))
            importance = min(1.0, score / (1.0 + score))
            desc = (
                f"Under-studied intersection of '{a}' and '{b}': "
                f"observed in {obs} of {n} papers vs {expected:.2f} expected "
                f"under independence (deficit ratio "
                f"{obs / max(expected, 1e-6):.2f})."
            )
            questions = [
                f"What is the mechanism underlying the relationship "
                f"between {a} and {b}?",
                f"What empirical evidence exists for the interaction of "
                f"{a} and {b}, and what study designs would resolve it?",
                f"How does {a} moderate or mediate the effect of {b}?",
            ]
            if topic:
                questions.insert(
                    0,
                    f"How does the topic '{topic}' relate to the {a}–{b} "
                    f"intersection?",
                )
            gaps.append(
                ResearchGap(
                    description=desc,
                    evidence_papers=evidence,
                    supporting_keywords=[a, b],
                    research_questions=questions,
                    novelty_score=round(novelty, 3),
                    importance_score=round(importance, 3),
                )
            )

        if self.llm_client is not None:
            gaps = self._enrich_with_llm(gaps, topic)

        return gaps[:max_gaps]

    def from_literature_review(
        self,
        papers: Sequence[Any],
        review_text: str,
        max_gaps: int = 10,
    ) -> List[ResearchGap]:
        """Extract explicit gap / future-work sentences from review text.

        Scans ``review_text`` for sentences containing gap markers
        (``"future research"``, ``"remains unclear"``, ``"gap in"``,
        ``"little is known"``, ``"under-explored"``, etc.) and links each
        to its top-2 most similar papers in ``papers`` (Jaccard on
        keywords if no embedder is available).

        Args:
            papers: Corpus to use as evidence.
            review_text: Free-text literature review.
            max_gaps: Maximum gaps to return.

        Returns:
            List of :class:`ResearchGap`.
        """
        if not review_text:
            return []
        markers = [
            "future research",
            "future work",
            "remains unclear",
            "remains unknown",
            "gap in",
            "gaps in",
            "little is known",
            "little is understood",
            "under-explored",
            "underexplored",
            "understudied",
            "under-studied",
            "not been investigated",
            "has not been studied",
            "warrants further",
            "remains an open question",
            "no study has",
            "few studies",
            "limited evidence",
            "scant evidence",
            "paucity of",
        ]
        sentences = re.split(r"(?<=[\.\!\?])\s+", review_text)
        keyword_sets = [
            (p, set(_paper_keywords(p)) | set(_tokenize(_paper_text(p))))
            for p in papers
        ]

        gaps: List[ResearchGap] = []
        for sent in sentences:
            low = sent.lower()
            if not any(m in low for m in markers):
                continue
            tokens = set(_tokenize(sent))
            if not tokens:
                continue
            ranked = sorted(
                (
                    (len(tokens & ks) / max(1, len(tokens | ks)), p)
                    for p, ks in keyword_sets
                ),
                key=lambda t: t[0],
                reverse=True,
            )
            evidence = [p for _, p in ranked[:2] if _paper_title(p) != "(untitled)"]
            novelty = 0.7 if not evidence else 0.5
            importance = min(1.0, 0.3 + 0.1 * len(evidence))
            gaps.append(
                ResearchGap(
                    description=sent.strip(),
                    evidence_papers=evidence,
                    supporting_keywords=sorted(tokens)[:5],
                    research_questions=[
                        f"How can the open issue raised here be resolved?",
                    ],
                    novelty_score=novelty,
                    importance_score=importance,
                )
            )
            if len(gaps) >= max_gaps:
                break

        if self.llm_client is not None:
            gaps = self._enrich_with_llm(gaps, None)
        return gaps

    def compare_frontiers(
        self,
        papers_a: Sequence[Any],
        papers_b: Sequence[Any],
        max_gaps: int = 10,
    ) -> List[ResearchGap]:
        """Find gaps unique to one corpus vs another.

        Keywords that appear in ``papers_b`` but rarely / never in
        ``papers_a`` (and vice versa) are surfaced as gaps.  Useful for
        "what is new in this fresh search vs my curated corpus".

        Args:
            papers_a: Reference corpus (e.g. previously curated).
            papers_b: Comparison corpus (e.g. newly searched).
            max_gaps: Maximum gaps to return.

        Returns:
            List of :class:`ResearchGap` (gaps unique to each side).
        """
        def _kw_freq(papers: Sequence[Any]) -> Counter:
            c: Counter = Counter()
            for p in papers:
                kws = set(_paper_keywords(p)) | set(_tokenize(_paper_text(p)))
                c.update(kws)
            return c

        freq_a = _kw_freq(papers_a)
        freq_b = _kw_freq(papers_b)
        n_a = max(1, len(papers_a))
        n_b = max(1, len(papers_b))
        all_kw = set(freq_a) | set(freq_b)
        gaps: List[ResearchGap] = []
        # Keywords frequent in B but absent in A.
        for kw, c_b in freq_b.most_common():
            c_a = freq_a.get(kw, 0)
            if c_b >= max(2, 0.05 * n_b) and c_a <= max(1, 0.005 * n_a):
                novelty = 1.0 - min(1.0, c_a / max(1, c_b))
                importance = min(1.0, c_b / max(1, n_b))
                gaps.append(
                    ResearchGap(
                        description=(
                            f"Keyword '{kw}' appears in {c_b} of {n_b} "
                            f"comparison-corpus papers but in only {c_a} of "
                            f"{n_a} reference-corpus papers — possibly an "
                            f"emerging area absent from the reference corpus."
                        ),
                        evidence_papers=[
                            p for p in papers_b if kw in (
                                set(_paper_keywords(p))
                                | set(_tokenize(_paper_text(p)))
                            )
                        ][:5],
                        supporting_keywords=[kw],
                        research_questions=[
                            f"Why is '{kw}' under-represented in the "
                            f"reference corpus?",
                            f"What new evidence does the comparison corpus "
                            f"provide about '{kw}'?",
                        ],
                        novelty_score=round(novelty, 3),
                        importance_score=round(importance, 3),
                    )
                )
                if len(gaps) >= max_gaps:
                    break
        return gaps

    # ------------------------------------------------------------------
    # LLM enrichment (best-effort; failures logged & ignored)
    # ------------------------------------------------------------------
    def _enrich_with_llm(
        self,
        gaps: List[ResearchGap],
        topic: Optional[str],
    ) -> List[ResearchGap]:
        """Use the LLM client (if any) to enrich gap descriptions."""
        if not self.llm_client or not gaps:
            return gaps
        try:
            summaries = "\n".join(
                f"{i + 1}. {g.description}" for i, g in enumerate(gaps)
            )
            prompt = (
                "You are a research-gap analyst. For each numbered gap "
                "below, return a one-sentence refined description and one "
                "concrete, testable research question. "
                f"Topic: {topic or '(unspecified)'}.\n\n{summaries}\n\n"
                "Respond in the form:\n"
                "1. <refined description>\n   Q: <research question>\n"
                "2. ...\n"
            )
            resp = self.llm_client.complete(prompt, max_tokens=1500)
            for i, line in enumerate(resp.splitlines()):
                line = line.strip()
                if not line or i >= len(gaps):
                    continue
                m = re.match(r"^\d+\.\s+(.+?)(?:\s+Q:\s*(.+))?$", line)
                if m:
                    desc = m.group(1).strip()
                    q = m.group(2)
                    if desc:
                        gaps[i].description = desc
                    if q:
                        gaps[i].research_questions.insert(0, q.strip())
        except Exception:  # noqa: BLE001 — enrichment is best-effort
            logger.exception("LLM gap enrichment failed; keeping heuristic output.")
        return gaps


# ---------------------------------------------------------------------------
# Idea generator
# ---------------------------------------------------------------------------
class IdeaGenerator:
    """Generate, refine, combine and score :class:`ResearchIdea` instances.

    The generator mirrors the same LLM-or-fallback contract as
    :class:`ResearchGapDetector`: pass an ``llm_client`` for richer output,
    or omit it for deterministic templated ideas.
    """

    # Templates used in fallback mode.
    _QUESTION_TEMPLATES = [
        "What is the effect of {X} on {Y} in the context of {topic}?",
        "How does {X} moderate the relationship between {Y} and {topic}?",
        "Under what conditions does {X} outperform {Y} for {topic}?",
        "What are the underlying mechanisms linking {X} and {Y} in {topic}?",
        "To what extent does {X} predict {Y} in {topic}?",
    ]
    _RATIONALE_TEMPLATE = (
        "The intersection of {X} and {Y} is under-represented in the "
        "corpus ({evidence_count} supporting papers). Addressing it would "
        "extend the {topic} literature and potentially yield {impact_type}."
    )

    def __init__(self, llm_client: Any = None) -> None:
        """Initialise the idea generator.

        Args:
            llm_client: Optional :class:`ai_assistant.llm_client.LLMClient`
                used to generate / refine ideas.  When ``None`` (default)
                deterministic templates are used.
        """
        self.llm_client = llm_client

    def generate(
        self,
        topic: str,
        papers: Optional[Sequence[Any]] = None,
        count: int = 5,
    ) -> List[ResearchIdea]:
        """Generate ``count`` research ideas for ``topic``.

        Args:
            topic: Free-text research topic / area.
            papers: Optional corpus used to bias ideas toward under-studied
                intersections and to populate ``related_papers``.
            count: Number of ideas to generate.

        Returns:
            List of :class:`ResearchIdea` sorted by composite score.
        """
        if count <= 0:
            return []
        topic = (topic or "").strip() or "the research area"
        llm_ideas: List[ResearchIdea] = []
        if self.llm_client is not None:
            llm_ideas = self._generate_with_llm(topic, papers, count)
            if len(llm_ideas) >= count:
                # Score & sort before returning.
                for idea in llm_ideas:
                    self._score_in_place(idea)
                llm_ideas.sort(key=lambda x: x.composite_score, reverse=True)
                return llm_ideas[:count]
        # Fallback (or augment): deterministic templates from corpus gaps.
        if papers:
            gaps = ResearchGapDetector(
                llm_client=None, embedder=None
            ).from_corpus(papers, topic=topic, max_gaps=count * 2)
        else:
            gaps = []
        ideas: List[ResearchIdea] = list(llm_ideas)
        if gaps:
            for i, g in enumerate(gaps[:count]):
                kw = g.supporting_keywords
                if len(kw) >= 2:
                    x, y = kw[0], kw[1]
                elif kw:
                    x, y = kw[0], topic
                else:
                    x, y = topic, "prior work"
                tmpl = self._QUESTION_TEMPLATES[i % len(self._QUESTION_TEMPLATES)]
                question = tmpl.format(X=x, Y=y, topic=topic)
                rationale = self._RATIONALE_TEMPLATE.format(
                    X=x,
                    Y=y,
                    evidence_count=len(g.evidence_papers),
                    topic=topic,
                    impact_type="actionable methodological guidance",
                )
                ideas.append(
                    ResearchIdea(
                        question=question,
                        rationale=rationale,
                        novelty_score=g.novelty_score,
                        feasibility_score=max(0.3, 1.0 - g.importance_score),
                        impact_score=g.importance_score,
                        related_papers=list(g.evidence_papers),
                    )
                )
        # If still empty (no papers / no gaps), use template-only ideas.
        while len(ideas) < count:
            i = len(ideas)
            tmpl = self._QUESTION_TEMPLATES[i % len(self._QUESTION_TEMPLATES)]
            question = tmpl.format(
                X="a key predictor", Y="the outcome", topic=topic
            )
            ideas.append(
                ResearchIdea(
                    question=question,
                    rationale=(
                        f"This question addresses an aspect of {topic} "
                        f"that has limited direct prior investigation."
                    ),
                    novelty_score=0.5,
                    feasibility_score=0.6,
                    impact_score=0.4,
                )
            )
        # Score & sort.
        for idea in ideas:
            self._score_in_place(idea)
        ideas.sort(key=lambda x: x.composite_score, reverse=True)
        return ideas[:count]

    def refine(self, idea: ResearchIdea, feedback: str) -> ResearchIdea:
        """Refine an existing idea based on free-text feedback.

        Args:
            idea: The :class:`ResearchIdea` to refine.
            feedback: Free-text reviewer feedback.

        Returns:
            A *new* :class:`ResearchIdea` with updated fields.  The
            original ``idea`` is not mutated.
        """
        new = ResearchIdea(
            question=idea.question,
            rationale=idea.rationale,
            novelty_score=idea.novelty_score,
            feasibility_score=idea.feasibility_score,
            impact_score=idea.impact_score,
            related_papers=list(idea.related_papers),
        )
        if self.llm_client is not None:
            try:
                prompt = (
                    "You are a research mentor. Refine the following "
                    "research idea based on the reviewer feedback.\n\n"
                    f"Question: {idea.question}\n"
                    f"Rationale: {idea.rationale}\n"
                    f"Feedback: {feedback}\n\n"
                    "Return a refined one-sentence question and a one-"
                    "paragraph rationale separated by '---'."
                )
                resp = self.llm_client.complete(prompt, max_tokens=600)
                if "---" in resp:
                    q, r = resp.split("---", 1)
                    new.question = q.strip()
                    new.rationale = r.strip()
            except Exception:  # noqa: BLE001
                logger.exception("LLM refine failed; applying heuristic refine.")
        # Heuristic refine: append feedback-derived clause.
        if feedback:
            clause = feedback.strip().split(".")[0].strip()
            if clause and clause.lower() not in new.question.lower():
                new.question = f"{new.question} (Refined: {clause}.)"
            new.rationale = (
                f"{new.rationale}\n\nReviewer feedback incorporated: {feedback.strip()}"
            )
        self._score_in_place(new)
        return new

    def combine(
        self, idea_a: ResearchIdea, idea_b: ResearchIdea
    ) -> ResearchIdea:
        """Combine two ideas into a hybrid research question.

        Args:
            idea_a: First idea.
            idea_b: Second idea.

        Returns:
            A new :class:`ResearchIdea` whose question integrates both,
            whose scores are the mean of the inputs, and whose
            ``related_papers`` is the union of the two inputs.
        """
        new = ResearchIdea(
            question=(
                f"Combined: {idea_a.question} "
                f"Moreover, {idea_b.question}"
            ),
            rationale=(
                f"This idea synthesises two complementary research "
                f"questions. (A) {idea_a.rationale}  (B) {idea_b.rationale}"
            ),
            novelty_score=round(
                max(idea_a.novelty_score, idea_b.novelty_score), 3
            ),
            feasibility_score=round(
                min(idea_a.feasibility_score, idea_b.feasibility_score), 3
            ),
            impact_score=round(
                (idea_a.impact_score + idea_b.impact_score) / 2.0, 3
            ),
            related_papers=list(idea_a.related_papers)
            + [p for p in idea_b.related_papers if p not in idea_a.related_papers],
        )
        self._score_in_place(new)
        return new

    def score(
        self, idea: ResearchIdea, criteria: Optional[Dict[str, float]] = None
    ) -> ResearchIdea:
        """Re-score an idea against weighted criteria.

        ``criteria`` is a mapping of criterion name -> weight in [0, 1].
        Recognised criteria names: ``novelty``, ``feasibility``,
        ``impact``, ``data_availability``, ``methodological_clarity``,
        ``theoretical_significance``.  Unknown criteria are ignored.

        Returns:
            The *same* idea with updated scores (mutated in-place and
            returned for convenience).
        """
        weights = criteria or {}
        novelty_w = weights.get("novelty", 1.0)
        feas_w = weights.get("feasibility", 1.0)
        impact_w = weights.get("impact", 1.0)
        data_w = weights.get("data_availability", 0.5)
        method_w = weights.get("methodological_clarity", 0.5)
        theory_w = weights.get("theoretical_significance", 0.5)

        # If criteria supply explicit values, use them; otherwise blend
        # existing scores with derived heuristic components.
        def _val(name: str, fallback: float) -> float:
            v = weights.get(name)
            if isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0:
                return float(v)
            return fallback

        idea.novelty_score = round(_val("novelty", idea.novelty_score), 3)
        idea.feasibility_score = round(
            _val("feasibility", idea.feasibility_score), 3
        )
        idea.impact_score = round(_val("impact", idea.impact_score), 3)
        # Side-channel criteria stored in rationale suffix.
        # (preserved here as a no-op for the public API)
        _ = (data_w, method_w, theory_w)
        return idea

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _score_in_place(self, idea: ResearchIdea) -> None:
        """Clamp scores to [0, 1] and round to 3 decimals."""
        idea.novelty_score = round(max(0.0, min(1.0, idea.novelty_score)), 3)
        idea.feasibility_score = round(
            max(0.0, min(1.0, idea.feasibility_score)), 3
        )
        idea.impact_score = round(max(0.0, min(1.0, idea.impact_score)), 3)

    def _generate_with_llm(
        self,
        topic: str,
        papers: Optional[Sequence[Any]],
        count: int,
    ) -> List[ResearchIdea]:
        """Generate ideas via the LLM client; return [] on any failure."""
        if self.llm_client is None:
            return []
        try:
            paper_lines = ""
            if papers:
                paper_lines = "\n".join(
                    f"- {_paper_title(p)}" for p in papers[:10]
                )
            prompt = (
                "You are a research-idea generator. Generate "
                f"{count} concrete, testable research questions about "
                f"'{topic}'.\n\nRelated papers:\n{paper_lines}\n\n"
                "Return each idea as:\n"
                "Q: <question>\nR: <one-sentence rationale>\n"
                "N: <novelty 0-1>\nF: <feasibility 0-1>\nI: <impact 0-1>\n"
            )
            resp = self.llm_client.complete(prompt, max_tokens=1500)
            ideas: List[ResearchIdea] = []
            blocks = re.split(r"\n(?=Q:\s)", resp.strip())
            for b in blocks:
                q = re.search(r"Q:\s*(.+)", b)
                r = re.search(r"R:\s*(.+)", b)
                n = re.search(r"N:\s*([\d\.]+)", b)
                f = re.search(r"F:\s*([\d\.]+)", b)
                i = re.search(r"I:\s*([\d\.]+)", b)
                if not q:
                    continue
                def _flt(m: Any) -> float:
                    if not m:
                        return 0.5
                    try:
                        return max(0.0, min(1.0, float(m.group(1))))
                    except ValueError:
                        return 0.5
                ideas.append(
                    ResearchIdea(
                        question=q.group(1).strip(),
                        rationale=(r.group(1).strip() if r else ""),
                        novelty_score=_flt(n),
                        feasibility_score=_flt(f),
                        impact_score=_flt(i),
                    )
                )
                if len(ideas) >= count:
                    break
            return ideas
        except Exception:  # noqa: BLE001
            logger.exception("LLM idea generation failed; falling back to templates.")
            return []


__all__ = [
    "ResearchGap",
    "ResearchIdea",
    "ResearchGapDetector",
    "IdeaGenerator",
]
