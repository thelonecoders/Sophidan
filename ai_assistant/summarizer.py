"""Paper summarization and literature review generation.

The :class:`PaperSummarizer` wraps an :class:`LLMClient` to produce structured
summaries of single papers and small corpora. Every public method returns a
dataclass instance with ``to_markdown()`` and ``to_dict()`` methods so the
output can be rendered to UI, exported as JSON, or piped into reporting tools.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paper protocol
# ---------------------------------------------------------------------------
class Paper(Protocol):
    """Structural type for a paper used by the summarizer."""

    title: str
    abstract: str
    authors: Any
    id: Any
    doi: Any
    year: Any
    full_text: str


def _attr(obj: Any, name: str, default: Any = "") -> Any:
    """Safe attribute access returning ``default`` for missing/None."""
    val = getattr(obj, name, None)
    return default if val is None else val


def _authors_str(paper: Any) -> str:
    """Comma-separated author names from a paper-like object."""
    authors = getattr(paper, "authors", None)
    if authors is None:
        return ""
    if isinstance(authors, str):
        return authors
    names: List[str] = []
    if isinstance(authors, Iterable):
        for a in authors:
            if isinstance(a, str):
                names.append(a)
            elif hasattr(a, "name"):
                names.append(str(a.name))
            else:
                names.append(str(a))
    return ", ".join(names)


def _body_text(paper: Any) -> str:
    """Return the body text of a paper, falling back to the abstract."""
    body = getattr(paper, "full_text", None) or getattr(paper, "body", None)
    if body:
        return str(body)
    return _attr(paper, "abstract", "") or ""


def _paper_id(paper: Any) -> str:
    """Return a stable string id for a paper-like object."""
    for attr in ("id", "doi", "title"):
        val = getattr(paper, attr, None)
        if val:
            return str(val)
    return repr(paper)


def _paper_short_cite(paper: Any) -> str:
    """Short ``Author (Year)`` style citation."""
    authors = _authors_str(paper)
    year = _attr(paper, "year", "")
    if authors and year:
        first = authors.split(",")[0].strip() or "Anon"
        return f"{first} ({year})"
    if authors:
        return authors.split(",")[0].strip()
    return _attr(paper, "title", "Unknown") or "Unknown"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------
@dataclass
class PaperSummary:
    """Structured summary of a single paper.

    Attributes:
        title: Paper title.
        authors: Comma-separated author list.
        year: Publication year (string or int).
        abstract: AI-generated 2-3 sentence abstract.
        key_findings: Bullet list of key findings.
        methodology: Description of data, methods, and experimental setup.
        limitations: Honest critique.
        future_work: Open questions or next steps.
        paper_id: Stable identifier of the source paper.
        raw: Optional raw LLM output for debugging.
    """

    title: str = ""
    authors: str = ""
    year: Any = ""
    abstract: str = ""
    key_findings: List[str] = field(default_factory=list)
    methodology: str = ""
    limitations: str = ""
    future_work: str = ""
    paper_id: str = ""
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "abstract": self.abstract,
            "key_findings": list(self.key_findings),
            "methodology": self.methodology,
            "limitations": self.limitations,
            "future_work": self.future_work,
            "paper_id": self.paper_id,
        }

    def to_markdown(self) -> str:
        """Render the summary as Markdown."""
        lines: List[str] = [f"# {self.title or 'Untitled Paper'}"]
        if self.authors:
            lines.append(f"_Authors:_ {self.authors}")
        if self.year:
            lines.append(f"_Year:_ {self.year}")
        lines.append("")
        lines.append("## Abstract")
        lines.append(self.abstract or "_Not available._")
        lines.append("")
        if self.key_findings:
            lines.append("## Key Findings")
            for kf in self.key_findings:
                lines.append(f"- {kf}")
            lines.append("")
        if self.methodology:
            lines.append("## Methodology")
            lines.append(self.methodology)
            lines.append("")
        if self.limitations:
            lines.append("## Limitations")
            lines.append(self.limitations)
            lines.append("")
        if self.future_work:
            lines.append("## Future Work")
            lines.append(self.future_work)
            lines.append("")
        return "\n".join(lines).strip()


@dataclass
class TopicSummary:
    """Structured synthesis of multiple papers about a topic.

    Attributes:
        topic: The topic string (may be empty when inferred).
        consensus: Consensus view across the corpus.
        sub_themes: Identified sub-themes or research threads.
        methodological_trends: Trends in methods used across papers.
        disagreements: Notable disagreements or contradictions.
        future_directions: Suggested directions for future work.
        paper_ids: IDs of papers included in the synthesis.
    """

    topic: str = ""
    consensus: str = ""
    sub_themes: List[str] = field(default_factory=list)
    methodological_trends: List[str] = field(default_factory=list)
    disagreements: List[str] = field(default_factory=list)
    future_directions: List[str] = field(default_factory=list)
    paper_ids: List[str] = field(default_factory=list)
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "topic": self.topic,
            "consensus": self.consensus,
            "sub_themes": list(self.sub_themes),
            "methodological_trends": list(self.methodological_trends),
            "disagreements": list(self.disagreements),
            "future_directions": list(self.future_directions),
            "paper_ids": list(self.paper_ids),
        }

    def to_markdown(self) -> str:
        """Render the topic summary as Markdown."""
        title = self.topic or "Topic Synthesis"
        lines: List[str] = [f"# Topic Synthesis: {title}"]
        if self.consensus:
            lines.append("## Consensus")
            lines.append(self.consensus)
            lines.append("")
        if self.sub_themes:
            lines.append("## Sub-themes")
            for s in self.sub_themes:
                lines.append(f"- {s}")
            lines.append("")
        if self.methodological_trends:
            lines.append("## Methodological Trends")
            for m in self.methodological_trends:
                lines.append(f"- {m}")
            lines.append("")
        if self.disagreements:
            lines.append("## Disagreements")
            for d in self.disagreements:
                lines.append(f"- {d}")
            lines.append("")
        if self.future_directions:
            lines.append("## Future Directions")
            for f in self.future_directions:
                lines.append(f"- {f}")
            lines.append("")
        return "\n".join(lines).strip()


@dataclass
class ComparisonTable:
    """Side-by-side comparison of multiple papers across dimensions.

    Attributes:
        dimensions: Row labels (e.g. "Methodology", "Dataset").
        papers: List of papers included in the comparison.
        cells: ``rows × cols`` matrix of strings, indexed by dimension then paper.
    """

    dimensions: List[str] = field(default_factory=list)
    papers: List[str] = field(default_factory=list)
    cells: List[List[str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict (rows as objects keyed by dimension)."""
        return {
            "dimensions": list(self.dimensions),
            "papers": list(self.papers),
            "rows": [
                {"dimension": dim, "values": dict(zip(self.papers, row))}
                for dim, row in zip(self.dimensions, self.cells)
            ],
        }

    def to_markdown(self) -> str:
        """Render the comparison as a Markdown table."""
        if not self.papers:
            return "_No papers to compare._"
        header = "| Dimension | " + " | ".join(self.papers) + " |"
        sep = "| --- |" + " --- |" * len(self.papers)
        lines = [header, sep]
        for dim, row in zip(self.dimensions, self.cells):
            cells = [str(c).replace("\n", " ").replace("|", "\\|") for c in row]
            # Pad row to the number of papers.
            while len(cells) < len(self.papers):
                cells.append("")
            lines.append("| " + dim + " | " + " | ".join(cells) + " |")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Summarizer
# ---------------------------------------------------------------------------
_DEFAULT_DIMENSIONS: Tuple[str, ...] = (
    "Year",
    "Authors",
    "Methodology",
    "Dataset",
    "Key Finding",
    "Limitations",
)


class PaperSummarizer:
    """High-level summarization and review generation for paper corpora."""

    DEFAULT_MAX_TOKENS = 1500

    def __init__(self, llm_client: Any) -> None:
        """Initialize the summarizer.

        Args:
            llm_client: An :class:`LLMClient` (or any object exposing a
                ``complete(prompt, max_tokens=...)`` method).
        """
        self.llm_client = llm_client
        # Lazy import to avoid a hard dependency on prompts at import time.
        try:
            from .prompts import PromptTemplates
            self._templates = PromptTemplates
        except Exception:  # noqa: BLE001 - prompts module is local, must exist
            self._templates = None
        logger.debug("PaperSummarizer initialized.")

    # ------------------------------------------------------------------
    # Single-paper
    # ------------------------------------------------------------------
    def summarize_paper(self, paper: Any) -> PaperSummary:
        """Produce a structured summary of a single paper.

        Args:
            paper: A paper-like object (see :class:`Paper`).

        Returns:
            A :class:`PaperSummary` populated from the LLM response.
        """
        title = _attr(paper, "title", "")
        authors = _authors_str(paper)
        year = _attr(paper, "year", "")
        abstract = _attr(paper, "abstract", "")
        body = _body_text(paper)
        body_excerpt = body[:4000] if body else abstract

        prompt = ""
        if self._templates is not None:
            prompt = self._templates.format(
                "SUMMARIZE_PAPER",
                title=title,
                authors=authors,
                year=str(year),
                abstract=abstract,
                body=body_excerpt,
            )
        else:
            prompt = (
                f"Summarize the paper '{title}' by {authors} ({year}).\n"
                f"Abstract: {abstract}\nBody excerpt: {body_excerpt}\n"
                "Return sections: Abstract, Key Findings, Methodology, "
                "Limitations, Future Work."
            )

        try:
            raw = str(self.llm_client.complete(prompt, max_tokens=self.DEFAULT_MAX_TOKENS))
        except Exception:  # noqa: BLE001 - graceful degradation
            logger.exception("LLM completion failed in summarize_paper; using heuristic.")
            raw = _heuristic_summary(title, authors, year, abstract, body)

        summary = self._parse_paper_summary(raw, paper)
        summary.raw = raw
        return summary

    def _parse_paper_summary(self, raw: str, paper: Any) -> PaperSummary:
        """Parse the LLM output into a :class:`PaperSummary`."""
        sections = _split_sections(raw)

        def section(name: str, *aliases: str) -> str:
            for key in (name, *aliases):
                if not key:
                    continue
                val = sections.get(key.lower())
                if val:
                    return str(val)
            return ""

        findings_text = section("Key Findings", "Findings") or ""
        findings = [ln.lstrip("-*• ").strip() for ln in findings_text.splitlines() if ln.strip()]
        return PaperSummary(
            title=_attr(paper, "title", "") or section("Title"),
            authors=_authors_str(paper) or section("Authors"),
            year=_attr(paper, "year", ""),
            abstract=section("Abstract"),
            key_findings=findings,
            methodology=section("Methodology"),
            limitations=section("Limitations"),
            future_work=section("Future Work", "Future work"),
            paper_id=_paper_id(paper),
        )

    # ------------------------------------------------------------------
    # Topic synthesis
    # ------------------------------------------------------------------
    def summarize_topic(self, papers: Sequence[Any], topic: Optional[str] = None) -> TopicSummary:
        """Synthesize a topic summary across multiple papers.

        Args:
            papers: List of paper-like objects.
            topic: Optional topic label. Inferred from titles when omitted.

        Returns:
            A :class:`TopicSummary` populated from the LLM response.
        """
        if not papers:
            return TopicSummary(topic=topic or "", paper_ids=[])
        topic_str = topic or self._infer_topic(papers)
        papers_list = self._papers_list_block(papers)
        n_papers = len(papers)

        if self._templates is not None:
            prompt = self._templates.format(
                "SUMMARIZE_TOPIC",
                n_papers=str(n_papers),
                topic=topic_str,
                papers_list=papers_list,
            )
        else:
            prompt = (
                f"Synthesize {n_papers} papers on '{topic_str}'.\n{papers_list}\n"
                "Provide consensus, sub-themes, methodological trends, "
                "disagreements, future work."
            )

        try:
            raw = str(self.llm_client.complete(prompt, max_tokens=1500))
        except Exception:  # noqa: BLE001
            logger.exception("LLM completion failed in summarize_topic.")
            raw = ""

        ts = self._parse_topic_summary(raw, topic_str, papers)
        ts.raw = raw
        return ts

    def _parse_topic_summary(
        self, raw: str, topic: str, papers: Sequence[Any]
    ) -> TopicSummary:
        """Parse the topic-synthesis LLM output into a :class:`TopicSummary`."""
        sections = _split_sections(raw)

        def section(name: str, *aliases: str) -> str:
            for key in (name, *aliases):
                if not key:
                    continue
                val = sections.get(key.lower())
                if val:
                    return str(val)
            return ""

        def bullet_list(text: Optional[str]) -> List[str]:
            if not text:
                return []
            return [ln.lstrip("-*• ").strip() for ln in text.splitlines() if ln.strip()]

        # Fallback: if no sections detected, treat the whole text as consensus.
        consensus = section(
            "Consensus", "Synthesis", "Summary", "Overview", "Consensus view"
        ) or raw.strip()

        return TopicSummary(
            topic=topic,
            consensus=consensus,
            sub_themes=bullet_list(
                section("Sub-themes", "Sub themes", "Subthemes", "Threads", "Research threads")
            ),
            methodological_trends=bullet_list(section("Methodological Trends", "Methodology")),
            disagreements=bullet_list(
                section("Disagreements", "Contradictions", "Conflicts")
            ),
            future_directions=bullet_list(
                section("Future Work", "Future work", "Future Directions", "Future directions")
            ),
            paper_ids=[_paper_id(p) for p in papers],
        )

    def _infer_topic(self, papers: Sequence[Any]) -> str:
        """Infer a topic label from a set of papers using the LLM."""
        titles = [_attr(p, "title", "") for p in papers if _attr(p, "title", "")]
        if not titles:
            return "the corpus"
        try:
            prompt = (
                "In one to four words, name the shared research topic of the "
                "following paper titles. Reply with the topic only.\n\n"
                + "\n".join(f"- {t}" for t in titles[:25])
            )
            return str(self.llm_client.complete(prompt, max_tokens=20)).strip().strip('"').replace("\n", " ")
        except Exception:  # noqa: BLE001
            logger.debug("Topic inference failed; returning generic label.")
            return "the corpus"

    # ------------------------------------------------------------------
    # Comparison + timeline
    # ------------------------------------------------------------------
    def compare_papers(self, papers: Sequence[Any]) -> ComparisonTable:
        """Build a markdown comparison table across a set of papers.

        Args:
            papers: List of paper-like objects.

        Returns:
            A :class:`ComparisonTable` populated with per-paper dimensions.
        """
        if not papers:
            return ComparisonTable()
        paper_labels = [_paper_short_cite(p) for p in papers]
        dimensions = list(_DEFAULT_DIMENSIONS)
        cells: List[List[str]] = []

        # Heuristic row extraction (no LLM call needed for basic fields).
        for dim in dimensions:
            row: List[str] = []
            for p in papers:
                row.append(self._cell_for_dimension(p, dim))
            cells.append(row)

        # Optionally enrich the "Key Finding" row with an LLM-generated summary.
        try:
            finding_prompt = (
                "For each paper below, produce a single sentence (<= 30 words) "
                "stating its key finding. Return as a numbered list matching "
                "the input order.\n\n"
                + "\n".join(
                    f"{i+1}. {_attr(p,'title','')}" for i, p in enumerate(papers)
                )
            )
            findings_text = str(self.llm_client.complete(finding_prompt, max_tokens=400))
            findings_lines = [
                ln.lstrip("0123456789.)*- ").strip()
                for ln in findings_text.splitlines()
                if ln.strip() and ln[0].isdigit()
            ]
            if findings_lines:
                idx = dimensions.index("Key Finding") if "Key Finding" in dimensions else -1
                if idx >= 0:
                    cells[idx] = [
                        findings_lines[i] if i < len(findings_lines) else cells[idx][i]
                        for i in range(len(papers))
                    ]
        except Exception:  # noqa: BLE001
            logger.debug("LLM enrichment of comparison table failed; using heuristics.")

        return ComparisonTable(
            dimensions=dimensions,
            papers=paper_labels,
            cells=cells,
        )

    def _cell_for_dimension(self, paper: Any, dimension: str) -> str:
        """Return the heuristic value for a single (paper, dimension) cell."""
        dim = dimension.lower()
        if dim == "year":
            return str(_attr(paper, "year", ""))
        if dim == "authors":
            authors = _authors_str(paper)
            if "," in authors:
                first = authors.split(",")[0].strip()
                return f"{first} et al."
            return authors
        if dim == "methodology":
            abstract = _attr(paper, "abstract", "")
            return _first_sentence(abstract) if abstract else ""
        if dim == "dataset":
            body = _body_text(paper)
            return _extract_dataset(body)
        if dim == "key finding":
            abstract = _attr(paper, "abstract", "")
            return _first_sentence(abstract) if abstract else ""
        if dim == "limitations":
            return ""
        return ""

    def extract_timeline(self, papers: Sequence[Any]) -> List[Dict[str, Any]]:
        """Return a chronological narrative of the supplied papers.

        Args:
            papers: List of paper-like objects with at least ``year`` set.

        Returns:
            A list of dicts (one per paper, sorted by year) with ``year``,
            ``cite``, ``title``, and ``narrative`` keys.
        """
        def year_key(p: Any) -> int:
            y = _attr(p, "year", None)
            try:
                return int(y) if y is not None else 9999
            except (TypeError, ValueError):
                return 9999

        sorted_papers = sorted(papers, key=year_key)
        out: List[Dict[str, Any]] = []
        prev_year: Optional[int] = None
        for p in sorted_papers:
            y = year_key(p)
            narrative = self._timeline_narrative(p, prev_year)
            out.append(
                {
                    "year": _attr(p, "year", ""),
                    "cite": _paper_short_cite(p),
                    "title": _attr(p, "title", ""),
                    "narrative": narrative,
                }
            )
            prev_year = y
        return out

    def _timeline_narrative(self, paper: Any, prev_year: Optional[int]) -> str:
        """Return a one-sentence narrative placing a paper in its time."""
        title = _attr(paper, "title", "")
        abstract = _attr(paper, "abstract", "")
        first_sentence = _first_sentence(abstract) if abstract else ""
        gap = ""
        if prev_year is not None:
            try:
                y = int(_attr(paper, "year", 0))
                if y > prev_year:
                    gap = f"Building on prior work, this {y} contribution "
                elif y == prev_year:
                    gap = f"Concurrently in {y}, "
            except (TypeError, ValueError):
                pass
        sentence = first_sentence or "advances the field."
        return f"{gap}{title}: {sentence}".strip()

    # ------------------------------------------------------------------
    # Literature review generation
    # ------------------------------------------------------------------
    def generate_literature_review(
        self,
        papers: Sequence[Any],
        style: str = "narrative",
        topic: Optional[str] = None,
    ) -> str:
        """Generate a flowing literature review as Markdown.

        Args:
            papers: List of paper-like objects.
            style: ``"narrative"``, ``"systematic"``, or ``"critical"``.
            topic: Optional topic label.

        Returns:
            A Markdown literature review string.
        """
        if not papers:
            return "_No papers supplied for literature review._"

        topic_str = topic or self._infer_topic(papers)
        style = (style or "narrative").lower()
        if style not in ("narrative", "systematic", "critical"):
            logger.warning("Unknown review style %r; defaulting to narrative.", style)
            style = "narrative"

        papers_data = [
            {
                "title": _attr(p, "title", ""),
                "authors": _authors_str(p),
                "year": _attr(p, "year", ""),
                "abstract": _attr(p, "abstract", ""),
            }
            for p in papers
        ]
        papers_json = json.dumps(papers_data, ensure_ascii=False, indent=2)

        if self._templates is not None:
            prompt = self._templates.format(
                "GENERATE_LITERATURE_REVIEW",
                style=style,
                topic=topic_str,
                n_papers=str(len(papers)),
                papers_json=papers_json,
            )
        else:
            prompt = (
                f"Write a {style} literature review ({len(papers)} papers) on "
                f"'{topic_str}'. Papers JSON:\n{papers_json}"
            )

        try:
            review = str(self.llm_client.complete(prompt, max_tokens=2500))
        except Exception:  # noqa: BLE001
            logger.exception("LLM completion failed for literature review; using fallback.")
            review = self._fallback_review(papers, topic_str, style)
        return review.strip()

    def _fallback_review(
        self, papers: Sequence[Any], topic: str, style: str
    ) -> str:
        """Heuristic literature review when the LLM is unavailable."""
        lines: List[str] = [f"# Literature Review: {topic}", ""]
        lines.append(
            f"This {style} review surveys {len(papers)} papers on {topic}."
        )
        lines.append("")
        for p in papers:
            cite = _paper_short_cite(p)
            title = _attr(p, "title", "")
            abstract = _attr(p, "abstract", "")
            lines.append(f"## {cite} — {title}")
            lines.append(_first_sentence(abstract) or "(no abstract available)")
            lines.append("")
        lines.append("## Gaps")
        lines.append("A more detailed gap analysis is unavailable in offline mode.")
        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Key quotes
    # ------------------------------------------------------------------
    def extract_key_quotes(self, paper: Any, n: int = 5) -> List[Tuple[str, str, float]]:
        """Return ``n`` notable quotes from a paper.

        Args:
            paper: A paper-like object with ``full_text`` (or ``abstract``).
            n: Maximum number of quotes to return.

        Returns:
            List of ``(quote, section, relevance)`` tuples. ``section`` is
            best-effort (e.g. ``"abstract"`` or ``"body"``) and ``relevance``
            is a heuristic score in [0, 1].
        """
        if n <= 0:
            return []
        body = _body_text(paper)
        if not body:
            return []
        sentences = _split_sentences(body)
        if not sentences:
            return []
        try:
            embeddings = self.llm_client.embed(sentences)
            embeddings = _coerce_2d(embeddings, len(sentences))
            # Score by average pairwise similarity (centrality).
            sims = embeddings @ embeddings.T
            centrality = sims.mean(axis=1)
        except Exception:  # noqa: BLE001 - fall back to length-based scoring
            logger.debug("Embedding-based quote ranking failed; using length heuristic.")
            centrality = np.array([float(len(s)) for s in sentences], dtype=np.float32)

        # Deduplicate near-identical sentences.
        seen: set[str] = set()
        ranked = sorted(
            enumerate(sentences), key=lambda kv: float(centrality[kv[0]]), reverse=True
        )
        out: List[Tuple[str, str, float]] = []
        max_score = float(centrality.max()) if centrality.size else 1.0
        for idx, sent in ranked:
            key = sent.strip().lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            section = self._section_for(paper, sent)
            relevance = (
                float(centrality[idx]) / max_score
                if max_score > 0
                else 0.0
            )
            out.append((sent.strip(), section, relevance))
            if len(out) >= n:
                break
        return out

    def _section_for(self, paper: Any, sentence: str) -> str:
        """Best-effort section name for a quote."""
        body = _body_text(paper)
        if not body:
            return "unknown"
        if sentence in _attr(paper, "abstract", ""):
            return "abstract"
        return "body"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _papers_list_block(self, papers: Sequence[Any]) -> str:
        """Render a paper list block for prompt context."""
        lines: List[str] = []
        for i, p in enumerate(papers, start=1):
            title = _attr(p, "title", "")
            authors = _authors_str(p)
            year = _attr(p, "year", "")
            abstract = _attr(p, "abstract", "")
            lines.append(
                f"[{i}] {authors} ({year}). {title}. {abstract}".strip()
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pure-function helpers (also exported for tests)
# ---------------------------------------------------------------------------
def _split_sections(markdown: str) -> Dict[str, str]:
    """Split a Markdown LLM response into a ``{section_lower: body}`` map."""
    sections: Dict[str, str] = {}
    current: Optional[str] = None
    buffer: List[str] = []
    for line in markdown.splitlines():
        m = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(buffer).strip()
            current = m.group(1).strip().lower()
            buffer = []
        else:
            if current is None:
                # Pre-section preamble.
                if line.strip():
                    sections.setdefault("__preamble__", "")
                    sections["__preamble__"] += line + "\n"
            else:
                buffer.append(line)
    if current is not None:
        sections[current] = "\n".join(buffer).strip()
    return sections


def _first_sentence(text: str) -> str:
    """Return the first sentence of ``text``."""
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"^(.*?[.!?])(?:\s|$)", cleaned)
    return m.group(1) if m else cleaned


def _split_sentences(text: str) -> List[str]:
    """Naive sentence splitter that tolerates abbreviations poorly."""
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 25]


def _extract_dataset(text: str) -> str:
    """Best-effort dataset name extraction from a paper body."""
    if not text:
        return ""
    m = re.search(r"\b(?:dataset|corpus)\s*[:\-]?\s*([A-Za-z0-9][\w\-\s,]{2,60})", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _coerce_2d(arr: Any, expected_rows: int) -> "np.ndarray":
    """Coerce an array to shape ``(expected_rows, dim)``."""
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 1:
        a = a.reshape(1, -1)
    if a.shape[0] != expected_rows:
        # Tile or truncate — best-effort only.
        a = a.reshape(expected_rows, -1) if a.size % expected_rows == 0 else a
    return a


def _heuristic_summary(
    title: str, authors: str, year: Any, abstract: str, body: str
) -> str:
    """Produce a fallback summary when the LLM is unavailable."""
    findings = []
    if abstract:
        findings.append(_first_sentence(abstract))
    if body:
        sentences = _split_sentences(body)
        findings.extend(sentences[:3])
    return (
        f"# {title}\n\n"
        f"_Authors:_ {authors}\n\n_Year:_ {year}\n\n"
        "## Abstract\n"
        f"{abstract or '(no abstract available)'}\n\n"
        "## Key Findings\n"
        + "\n".join(f"- {f}" for f in findings[:5])
        + "\n\n## Methodology\n"
        "(LLM unavailable — methodology not extracted.)\n\n"
        "## Limitations\n"
        "(LLM unavailable — limitations not extracted.)\n\n"
        "## Future Work\n"
        "(LLM unavailable — future work not extracted.)"
    )


__all__ = [
    "PaperSummary",
    "TopicSummary",
    "ComparisonTable",
    "PaperSummarizer",
    "Paper",
]
