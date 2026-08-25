"""AI-assisted academic writing helper.

The :class:`WritingAssistant` wraps an optional
:class:`ai_assistant.llm_client.LLMClient` to provide higher-level
writing operations:

* :meth:`outline` — generate a markdown outline from a topic / sections
  list / corpus.
* :meth:`draft_section` — draft prose for a single outline item with
  in-text citations to supporting papers.
* :meth:`improve_prose` — paraphrase + shorten for a target journal
  style (``nature`` / ``ieee`` / ``apa`` / ``chicago``).
* :meth:`check_grammar` — deterministic checks for sentence length,
  passive voice, and hedging language.
* :meth:`generate_abstract` — structured abstract (≤ ``max_words``).
* :meth:`generate_title` — five alternative title candidates in a
  specified style.
* :meth:`format_citation` / :meth:`format_bibliography` — single-paper
  and bibliography-level citation formatting (APA / IEEE / MLA /
  Chicago / Nature).
* :meth:`paraphrase` — single-paragraph paraphrase.
* :meth:`summarize_for_imrad` — I / M / R / D sections dict.

Every method falls back to deterministic templates if no LLM client is
supplied (or if the LLM call fails), so the assistant is fully usable
in offline / CI environments.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Paper shim (duck-typed)
# ---------------------------------------------------------------------------
def _authors_str(paper: Any) -> str:
    """Return a comma-joined author string from a paper-like object."""
    a = getattr(paper, "authors", None) or []
    if isinstance(a, str):
        return a
    return ", ".join(str(x) for x in a)


def _paper_title(paper: Any) -> str:
    return str(getattr(paper, "title", "") or "")


def _paper_year(paper: Any) -> Optional[int]:
    y = getattr(paper, "year", None)
    try:
        return int(y) if y is not None else None
    except (TypeError, ValueError):
        return None


def _paper_journal(paper: Any) -> str:
    return str(getattr(paper, "journal", "") or "")


def _paper_doi(paper: Any) -> str:
    return str(getattr(paper, "doi", "") or "")


def _paper_volume(paper: Any) -> str:
    return str(getattr(paper, "volume", "") or "")


def _paper_issue(paper: Any) -> str:
    return str(getattr(paper, "issue", "") or "")


def _paper_pages(paper: Any) -> str:
    return str(getattr(paper, "pages", "") or "")


def _paper_abstract(paper: Any) -> str:
    return str(getattr(paper, "abstract", "") or "")


# ---------------------------------------------------------------------------
# Author-formatting helpers (shared across citation styles)
# ---------------------------------------------------------------------------
def _split_author(author: str) -> tuple:
    """Return ``(last, first_initials)`` for a single author string.

    Handles both "Last, First M." and "First M. Last" forms.
    """
    a = (author or "").strip().rstrip(".")
    if "," in a:
        last, rest = a.split(",", 1)
        last = last.strip()
        initials = " ".join(f"{p[0]}." for p in rest.split() if p)
        return last, initials
    parts = a.split()
    if len(parts) >= 2:
        last = parts[-1]
        initials = " ".join(f"{p[0]}." for p in parts[:-1] if p)
        return last, initials
    return a, ""


def _format_authors_apa(authors: List[str]) -> str:
    """APA: 'Last, F. M., & Last2, F. M.'"""
    out: List[str] = []
    for a in authors:
        last, inits = _split_author(a)
        out.append(f"{last}, {inits}" if inits else last)
    if len(out) == 1:
        return out[0]
    if len(out) <= 20:
        return ", ".join(out[:-1]) + ", & " + out[-1]
    return ", ".join(out[:20]) + ", . . . " + out[-1]


def _format_authors_ieee(authors: List[str]) -> str:
    """IEEE: 'F. M. Last, F. M. Last2, and F. M. Last3'"""
    out: List[str] = []
    for a in authors:
        last, inits = _split_author(a)
        out.append(f"{inits} {last}" if inits else last)
    if len(out) == 1:
        return out[0]
    if len(out) <= 6:
        return ", ".join(out[:-1]) + ", and " + out[-1]
    return ", ".join(out[:6]) + ", et al."


def _format_authors_mla(authors: List[str]) -> str:
    """MLA: 'Last, First M., et al.' (3+ authors) or 'Last, First M., and First M. Last2.'"""
    if not authors:
        return ""
    if len(authors) == 1:
        last, inits = _split_author(authors[0])
        return f"{last}, {inits}" if inits else last
    if len(authors) == 2:
        last1, inits1 = _split_author(authors[0])
        last2, inits2 = _split_author(authors[1])
        a1 = f"{last1}, {inits1}" if inits1 else last1
        a2 = f"{inits2} {last2}" if inits2 else last2
        return f"{a1}, and {a2}"
    last1, inits1 = _split_author(authors[0])
    a1 = f"{last1}, {inits1}" if inits1 else last1
    return f"{a1}, et al."


def _format_authors_chicago(authors: List[str]) -> str:
    """Chicago notes-style: 'First M. Last and First M. Last2'."""
    out: List[str] = []
    for a in authors:
        last, inits = _split_author(a)
        out.append(f"{inits} {last}" if inits else last)
    if len(out) == 1:
        return out[0]
    if len(out) <= 10:
        return ", ".join(out[:-1]) + " and " + out[-1]
    return ", ".join(out[:10]) + ", et al."


def _format_authors_nature(authors: List[str]) -> str:
    """Nature: 'Last, F. M. et al.' (5+ authors → et al.)."""
    out: List[str] = []
    for a in authors:
        last, inits = _split_author(a)
        out.append(f"{last}, {inits}" if inits else last)
    if not out:
        return ""
    if len(out) <= 5:
        if len(out) == 1:
            return out[0]
        return ", ".join(out[:-1]) + " & " + out[-1]
    return out[0] + " et al."


# ---------------------------------------------------------------------------
# WritingAssistant
# ---------------------------------------------------------------------------
class WritingAssistant:
    """AI-assisted academic writing helper with deterministic fallbacks.

    The assistant supports both LLM-augmented and template-based modes
    and degrades gracefully when the LLM call fails — every public
    method always returns a string (or list of strings) of the
    documented shape.
    """

    # Map journal-style name → target sentence length (approx).
    _STYLE_TARGET_WORDS = {
        "nature": 25,
        "ieee": 20,
        "apa": 22,
        "chicago": 24,
    }

    # Common hedging / passive markers used by :meth:`check_grammar`.
    _HEDGES = (
        "might", "may", "could", "possibly", "perhaps", "arguably",
        "appears to", "seems to", "tends to", "likely",
        "it is possible that", "it seems that",
    )
    _PASSIVE_RX = re.compile(
        r"\b(?:is|are|was|were|be|been|being)\s+\w+(?:ed|en)\b",
        re.IGNORECASE,
    )

    def __init__(self, llm_client: Any = None) -> None:
        """Initialise the assistant.

        Args:
            llm_client: Optional :class:`ai_assistant.llm_client.LLMClient`
                used to enhance every output. When ``None`` (default)
                deterministic templates are used everywhere.
        """
        self.llm_client = llm_client

    # ------------------------------------------------------------------
    # Outline
    # ------------------------------------------------------------------
    def outline(
        self,
        topic: str,
        sections: Optional[Sequence[str]] = None,
        papers: Optional[Sequence[Any]] = None,
    ) -> str:
        """Generate a markdown outline for ``topic``.

        Args:
            topic: The topic / research question.
            sections: Optional explicit list of section headings; if
                omitted, the IMRaD structure is used (with extensions).
            papers: Optional corpus used to seed subsections (top 3 by
                citation count, when available).

        Returns:
            A multi-line markdown string.
        """
        sections = list(sections) if sections else [
            "Introduction",
            "Background and Related Work",
            "Methods",
            "Results",
            "Discussion",
            "Conclusion",
            "References",
        ]
        if self.llm_client is not None:
            llm_out = self._llm_outline(topic, sections, papers)
            if llm_out:
                return llm_out

        lines = [f"# Outline: {topic}", ""]
        for i, s in enumerate(sections, 1):
            lines.append(f"## {i}. {s}")
            if s.lower().startswith("intro"):
                lines.append(f"- Motivate {topic}.")
                lines.append("- State the research question and contribution.")
                lines.append("- Roadmap of the paper.")
            elif "background" in s.lower() or "related" in s.lower():
                if papers:
                    top = self._top_papers(papers, 3)
                    for p in top:
                        lines.append(f"- Discuss {_paper_title(p)} ({_paper_year(p)}).")
                else:
                    lines.append("- Survey prior approaches.")
                    lines.append("- Identify the gap this work addresses.")
            elif "method" in s.lower():
                lines.append("- Data sources and sample.")
                lines.append("- Analytical approach.")
                lines.append("- Validity / sensitivity checks.")
            elif "result" in s.lower():
                lines.append("- Descriptive findings.")
                lines.append("- Main estimates with effect sizes.")
                lines.append("- Sensitivity analyses.")
            elif "discussion" in s.lower():
                lines.append("- Interpret findings in light of prior work.")
                lines.append("- Limitations.")
                lines.append("- Theoretical / practical implications.")
            elif "conclusion" in s.lower():
                lines.append("- Summarise contribution.")
                lines.append("- Future work.")
            elif "reference" in s.lower():
                lines.append("- Full bibliography in chosen citation style.")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _llm_outline(
        self,
        topic: str,
        sections: Sequence[str],
        papers: Optional[Sequence[Any]],
    ) -> str:
        """LLM-driven outline; returns '' on any failure."""
        if self.llm_client is None:
            return ""
        try:
            paper_lines = ""
            if papers:
                paper_lines = "\n".join(
                    f"- {_paper_title(p)} ({_paper_year(p)})"
                    for p in self._top_papers(papers, 5)
                )
            prompt = (
                "Generate a detailed Markdown outline for a research "
                f"paper on '{topic}'. Use the following top-level "
                f"sections: {list(sections)}. Under each section include "
                f"3-5 bullet subsections.\n\nRelated papers:\n{paper_lines}\n"
            )
            resp = self.llm_client.complete(prompt, max_tokens=1200)
            return resp.strip()
        except Exception:  # noqa: BLE001
            logger.exception("LLM outline failed; falling back to template.")
            return ""

    # ------------------------------------------------------------------
    # Draft a section
    # ------------------------------------------------------------------
    def draft_section(
        self,
        section_heading: str,
        outline_item: str,
        supporting_papers: Sequence[Any],
        word_count: int = 500,
    ) -> str:
        """Draft prose for a single outline item.

        Args:
            section_heading: Section title (e.g. ``"Background"``).
            outline_item: Bullet text from :meth:`outline` describing
                what to write.
            supporting_papers: Papers to cite inline.
            word_count: Target word count.

        Returns:
            Markdown-formatted prose with inline citations.
        """
        if self.llm_client is not None:
            llm_out = self._llm_draft_section(
                section_heading, outline_item, supporting_papers, word_count
            )
            if llm_out:
                return llm_out
        # Fallback: structured template.
        lines = [f"## {section_heading}", ""]
        lines.append(f"{outline_item.strip()}. ")
        if supporting_papers:
            lines.append(
                "Prior work in this area has examined the issue from "
                "several angles. "
            )
            for i, p in enumerate(supporting_papers[:5], 1):
                cite = self._inline_cite(p, style="apa")
                lines.append(
                    f"In particular, {cite} {_paper_year(p)} found that "
                    f"{(_paper_abstract(p) or 'results were inconclusive')[:160]} "
                )
            lines.append("Taken together, these studies motivate the present work.")
        # Pad to roughly word_count.
        target = max(50, int(word_count))
        filler = (
            "The following discussion situates the contribution in the broader "
            "literature and motivates the methodological choices taken below. "
        )
        body = " ".join(lines)
        while len(body.split()) < target:
            body += filler
        return body[: int(target * 7)]

    def _llm_draft_section(
        self,
        section_heading: str,
        outline_item: str,
        supporting_papers: Sequence[Any],
        word_count: int,
    ) -> str:
        if self.llm_client is None:
            return ""
        try:
            paper_lines = "\n".join(
                f"- {_paper_title(p)} ({_paper_year(p)}): "
                f"{_paper_abstract(p)[:160]}"
                for p in supporting_papers[:5]
            )
            prompt = (
                f"Draft the '{section_heading}' section of an academic paper "
                f"in about {word_count} words. The section should cover: "
                f"{outline_item}. Use APA in-text citations.\n\n"
                f"Supporting papers:\n{paper_lines}\n"
            )
            return self.llm_client.complete(prompt, max_tokens=1500).strip()
        except Exception:  # noqa: BLE001
            logger.exception("LLM draft_section failed; falling back to template.")
            return ""

    # ------------------------------------------------------------------
    # Improve prose
    # ------------------------------------------------------------------
    def improve_prose(
        self,
        text: str,
        journal_style: str = "nature",
    ) -> str:
        """Paraphrase + shorten ``text`` for ``journal_style``.

        Args:
            text: Input text.
            journal_style: One of ``nature``/``ieee``/``apa``/``chicago``.

        Returns:
            Improved text.
        """
        journal_style = (journal_style or "nature").lower()
        if journal_style not in self._STYLE_TARGET_WORDS:
            logger.warning("Unknown journal style %r; defaulting to nature.", journal_style)
            journal_style = "nature"
        if self.llm_client is not None:
            try:
                prompt = (
                    f"Rewrite the following text in the style of a "
                    f"{journal_style} journal article. Use concise "
                    f"sentences (~{self._STYLE_TARGET_WORDS[journal_style]} "
                    f"words each), active voice, and remove hedging.\n\n{text}\n"
                )
                resp = self.llm_client.complete(prompt, max_tokens=1500).strip()
                if resp:
                    return resp
            except Exception:  # noqa: BLE001
                logger.exception("LLM improve_prose failed; applying heuristic.")
        # Heuristic: split sentences; truncate any sentence > target words.
        target = self._STYLE_TARGET_WORDS[journal_style]
        sentences = re.split(r"(?<=[\.\!\?])\s+", text)
        out: List[str] = []
        for s in sentences:
            words = s.split()
            if len(words) > target * 1.5:
                # Truncate at the first clause break.
                m = re.split(r",|;|—", s)
                if m:
                    s = m[0].strip() + "."
            # Replace hedging.
            for h in self._HEDGES:
                s = re.sub(rf"\b{re.escape(h)}\b", "", s, flags=re.IGNORECASE)
            s = re.sub(r"\s{2,}", " ", s).strip()
            if s:
                out.append(s)
        return " ".join(out)

    # ------------------------------------------------------------------
    # Grammar checks (deterministic, no LLM)
    # ------------------------------------------------------------------
    def check_grammar(self, text: str) -> List[dict]:
        """Run deterministic grammar checks.

        Each returned dict has keys:
            ``{"type": str, "sentence": str, "issue": str, "suggestion": str}``.

        Detected issues:

        * ``long_sentence`` — sentences > 35 words.
        * ``passive_voice`` — sentences containing common passive
          constructions.
        * ``hedging`` — sentences containing hedging language.
        """
        out: List[dict] = []
        if not text:
            return out
        sentences = re.split(r"(?<=[\.\!\?])\s+", text.strip())
        for s in sentences:
            s_clean = s.strip()
            if not s_clean:
                continue
            n_words = len(s_clean.split())
            if n_words > 35:
                out.append({
                    "type": "long_sentence",
                    "sentence": s_clean,
                    "issue": f"Sentence has {n_words} words (>35).",
                    "suggestion": "Split into two or more sentences.",
                })
            if self._PASSIVE_RX.search(s_clean):
                # Confirm it's really a passive construction by checking
                # for a past-participle ending.
                m = self._PASSIVE_RX.search(s_clean)
                if m:
                    out.append({
                        "type": "passive_voice",
                        "sentence": s_clean,
                        "issue": f"Possible passive construction: '{m.group(0)}'.",
                        "suggestion": "Consider active voice.",
                    })
            low = s_clean.lower()
            for h in self._HEDGES:
                if h in low:
                    out.append({
                        "type": "hedging",
                        "sentence": s_clean,
                        "issue": f"Hedging language: '{h}'.",
                        "suggestion": "Remove or strengthen the claim.",
                    })
                    break  # one hedge report per sentence
        return out

    # ------------------------------------------------------------------
    # Abstract & title generation
    # ------------------------------------------------------------------
    def generate_abstract(
        self,
        paper: Any,
        max_words: int = 250,
    ) -> str:
        """Generate a structured abstract for ``paper``.

        Args:
            paper: A paper-like object.
            max_words: Maximum word count.

        Returns:
            A single-paragraph or structured abstract.
        """
        if self.llm_client is not None:
            try:
                prompt = (
                    "Generate a structured abstract for the following "
                    f"paper in at most {max_words} words. Use Background, "
                    "Methods, Results, Conclusions subheadings.\n\n"
                    f"Title: {_paper_title(paper)}\n"
                    f"Abstract (existing): {_paper_abstract(paper)}\n"
                )
                resp = self.llm_client.complete(prompt, max_tokens=600).strip()
                if resp:
                    return self._trim_to_words(resp, max_words)
            except Exception:  # noqa: BLE001
                logger.exception("LLM abstract failed; using template.")
        # Fallback: derive a structured abstract from existing fields.
        title = _paper_title(paper)
        abstract = _paper_abstract(paper)
        year = _paper_year(paper) or ""
        background = (
            f"This study, titled '{title}', addresses an open question "
            f"in the field"
            + (f" as of {year}" if year else "")
            + "."
        )
        methods = (
            "We employed a mixed-methods design combining quantitative "
            "extraction and qualitative thematic synthesis."
        )
        results = abstract[:400] if abstract else (
            "Results indicate meaningful patterns consistent with the prior "
            "literature."
        )
        conclusions = (
            "We discuss implications for theory and practice and identify "
            "avenues for future research."
        )
        text = (
            f"Background: {background}\n"
            f"Methods: {methods}\n"
            f"Results: {results}\n"
            f"Conclusions: {conclusions}"
        )
        return self._trim_to_words(text, max_words)

    def generate_title(
        self,
        paper: Any,
        style: str = "descriptive",
    ) -> List[str]:
        """Generate 5 alternative title candidates.

        Args:
            paper: Paper-like object.
            style: One of ``"descriptive"``, ``"declarative"``,
                ``"interrogative"``.

        Returns:
            A list of 5 title strings.
        """
        style = (style or "descriptive").lower()
        if style not in ("descriptive", "declarative", "interrogative"):
            logger.warning("Unknown title style %r; defaulting to descriptive.", style)
            style = "descriptive"
        if self.llm_client is not None:
            try:
                prompt = (
                    f"Generate 5 alternative academic paper titles in the "
                    f"'{style}' style for the following paper. Return one "
                    f"title per line.\n\nTitle: {_paper_title(paper)}\n"
                    f"Abstract: {_paper_abstract(paper)}\n"
                )
                resp = self.llm_client.complete(prompt, max_tokens=400)
                lines = [ln.strip().lstrip("0123456789.-) ") for ln in resp.splitlines()]
                lines = [ln for ln in lines if ln]
                if len(lines) >= 3:
                    return lines[:5]
            except Exception:  # noqa: BLE001
                logger.exception("LLM title failed; using templates.")
        # Fallback: templated titles.
        title = _paper_title(paper) or "the topic"
        year = _paper_year(paper)
        year_str = f"({year})" if year else ""
        topic_short = title.split(":")[0].strip()[:60] or "the topic"
        if style == "declarative":
            return [
                f"{topic_short} Improves Outcomes {year_str}",
                f"{topic_short} Transforms Current Practice {year_str}",
                f"We Show That {topic_short} Yields Robust Effects",
                f"{topic_short} Delivers Measurable Benefits",
                f"Towards Evidence-Based {topic_short}",
            ]
        if style == "interrogative":
            return [
                f"Does {topic_short} Matter for Practice?",
                f"How Does {topic_short} Shape Outcomes?",
                f"Why Is {topic_short} Important Now?",
                f"Can {topic_short} Inform Future Research?",
                f"What Role Does {topic_short} Play in the Field?",
            ]
        # descriptive
        return [
            f"{title}",
            f"A Study of {topic_short}",
            f"{topic_short}: A Comprehensive Review",
            f"An Empirical Investigation of {topic_short} {year_str}",
            f"{topic_short} {year_str}: Methods, Results, and Implications",
        ]

    # ------------------------------------------------------------------
    # Citation formatting
    # ------------------------------------------------------------------
    def format_citation(
        self,
        paper: Any,
        style: str = "apa",
    ) -> str:
        """Format a single-paper reference in the chosen style.

        Args:
            paper: Paper-like object.
            style: One of ``"apa"``, ``"ieee"``, ``"mla"``, ``"chicago"``,
                ``"nature"``.
        """
        style = (style or "apa").lower()
        authors = (getattr(paper, "authors", None) or [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(",") if a.strip()]
        title = _paper_title(paper)
        year = _paper_year(paper) or "n.d."
        journal = _paper_journal(paper)
        vol = _paper_volume(paper)
        issue = _paper_issue(paper)
        pages = _paper_pages(paper)
        doi = _paper_doi(paper)

        if style == "apa":
            auth = _format_authors_apa(authors) or "Anonymous"
            ref = f"{auth} ({year}). {title}."
            if journal:
                ref += f" *{journal}*"
                if vol:
                    ref += f", *{vol}*"
                    if issue:
                        ref += f"({issue})"
                if pages:
                    ref += f", {pages}"
                ref += "."
            else:
                ref += "."
            if doi:
                ref += f" https://doi.org/{doi}"
            return ref
        if style == "ieee":
            auth = _format_authors_ieee(authors) or "Anonymous"
            ref = f'{auth}, "{title},"'
            if journal:
                ref += f" *{journal}*"
                if vol:
                    ref += f", vol. {vol}"
                if issue:
                    ref += f", no. {issue}"
                if pages:
                    ref += f", pp. {pages}"
            ref += f", {year}."
            if doi:
                ref += f" doi: {doi}"
            return ref
        if style == "mla":
            auth = _format_authors_mla(authors) or "Anonymous"
            ref = f'{auth}. "{title}."'
            if journal:
                ref += f" *{journal}*"
                if vol:
                    ref += f", vol. {vol}"
                if issue:
                    ref += f", no. {issue}"
                if year:
                    ref += f", {year}"
                if pages:
                    ref += f", pp. {pages}"
            ref += "."
            if doi:
                ref += f" {doi}"
            return ref
        if style == "chicago":
            auth = _format_authors_chicago(authors) or "Anonymous"
            ref = f'{auth}. "{title}."'
            if journal:
                ref += f" *{journal}*"
                if vol:
                    ref += f" {vol}"
                if issue:
                    ref += f", no. {issue}"
            ref += f" ({year})"
            if pages:
                ref += f": {pages}"
            ref += "."
            if doi:
                ref += f" https://doi.org/{doi}"
            return ref
        if style == "nature":
            auth = _format_authors_nature(authors) or "Anonymous"
            ref = f"{auth} {title}."
            if journal:
                ref += f" *{journal}*"
                if vol:
                    ref += f" {vol}"
                if pages:
                    ref += f", {pages}"
            ref += f" ({year})."
            if doi:
                ref += f" doi: {doi}"
            return ref
        logger.warning("Unknown citation style %r; defaulting to APA.", style)
        return self.format_citation(paper, style="apa")

    def format_bibliography(
        self,
        papers: Sequence[Any],
        style: str = "apa",
    ) -> str:
        """Format a list of papers into a single bibliography string.

        The bibliography is sorted alphabetically by first-author
        surname (APA / Chicago / Nature) or by order of citation (IEEE /
        MLA — here simply the input order).
        """
        entries = [self.format_citation(p, style=style) for p in papers]
        if style in ("apa", "chicago", "nature"):
            entries = sorted(entries, key=lambda s: s.lower())
        return "\n".join(entries)

    # ------------------------------------------------------------------
    # Paraphrase
    # ------------------------------------------------------------------
    def paraphrase(self, text: str) -> str:
        """Paraphrase a single paragraph.

        Falls back to a deterministic synonym substitution if no LLM
        client is supplied.
        """
        if self.llm_client is not None:
            try:
                prompt = (
                    "Paraphrase the following academic passage while "
                    "preserving meaning and citations. Keep the same "
                    "register.\n\n" + text + "\n"
                )
                resp = self.llm_client.complete(prompt, max_tokens=1000).strip()
                if resp:
                    return resp
            except Exception:  # noqa: BLE001
                logger.exception("LLM paraphrase failed; using heuristic.")
        # Heuristic synonym substitution.
        syn = {
            "show": "demonstrate",
            "shows": "demonstrates",
            "use": "employ",
            "uses": "employs",
            "important": "significant",
            "big": "substantial",
            "small": "modest",
            "many": "numerous",
            "find": "identify",
            "finds": "identifies",
            "findings": "results",
            "result": "outcome",
            "results": "outcomes",
            "study": "investigation",
            "studies": "investigations",
            "however": "nevertheless",
            "also": "additionally",
            "because": "since",
            "so": "therefore",
            "very": "notably",
            "really": "substantially",
        }
        words = re.split(r"(\b)", text)
        out: List[str] = []
        for w in words:
            out.append(syn.get(w.lower(), w))
        return "".join(out)

    # ------------------------------------------------------------------
    # IMRaD summary
    # ------------------------------------------------------------------
    def summarize_for_imrad(self, paper: Any) -> Dict[str, str]:
        """Summarise a paper into I/M/R/D sections.

        Returns a dict with keys ``"Introduction"``, ``"Methods"``,
        ``"Results"``, ``"Discussion"``.
        """
        abstract = _paper_abstract(paper)
        title = _paper_title(paper)
        year = _paper_year(paper)
        if self.llm_client is not None:
            try:
                prompt = (
                    "Summarise the following paper into four short "
                    "paragraphs labelled Introduction, Methods, Results, "
                    "Discussion.\n\n"
                    f"Title: {title}\nAbstract: {abstract}\n"
                )
                resp = self.llm_client.complete(prompt, max_tokens=800)
                # Parse paragraphs by header.
                result: Dict[str, str] = {}
                for label in ("Introduction", "Methods", "Results", "Discussion"):
                    m = re.search(
                        rf"(?:^|\n)\**{label}\**[:\-]?\s*(.+?)(?=\n\**(?:Introduction|Methods|Results|Discussion)\**|$)",
                        resp, re.IGNORECASE | re.DOTALL,
                    )
                    if m:
                        result[label] = m.group(1).strip()
                if len(result) == 4:
                    return result
            except Exception:  # noqa: BLE001
                logger.exception("LLM IMRaD summary failed; using template.")
        # Fallback: deterministic split.
        parts = re.split(
            r"\b(?:background|introduction)\b|\bmethods?\b|\bresults?\b|\bconclusions?\b|\bdiscussion\b",
            abstract, flags=re.IGNORECASE,
        )
        parts = [p.strip() for p in parts if p.strip()]
        return {
            "Introduction": (
                parts[0] if parts else f"This paper, titled '{title}', "
                f"addresses a question in the field"
                + (f" as of {year}." if year else ".")
            ),
            "Methods": parts[1] if len(parts) > 1 else (
                "The authors describe the study design, data sources, "
                "and analytical approach."
            ),
            "Results": parts[2] if len(parts) > 2 else (
                "Key results are reported in the abstract."
            ),
            "Discussion": parts[3] if len(parts) > 3 else (
                "The authors discuss implications and limitations."
            ),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _trim_to_words(text: str, max_words: int) -> str:
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]).rstrip(".") + "."

    @staticmethod
    def _top_papers(
        papers: Sequence[Any], n: int
    ) -> List[Any]:
        """Return top-``n`` papers by citation count (when available)."""
        def _cite_key(p: Any) -> int:
            c = getattr(p, "citations_count", None)
            try:
                return int(c) if c is not None else 0
            except (TypeError, ValueError):
                return 0
        return sorted(papers, key=_cite_key, reverse=True)[:n]

    def _inline_cite(self, paper: Any, style: str = "apa") -> str:
        """Return an in-text citation, e.g. ``(Smith et al., 2024)``."""
        authors = (getattr(paper, "authors", None) or [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(",") if a.strip()]
        year = _paper_year(paper) or "n.d."
        if not authors:
            auth = "Anonymous"
        elif len(authors) == 1:
            last, _ = _split_author(authors[0])
            auth = last
        elif len(authors) <= 5:
            last, _ = _split_author(authors[0])
            auth = f"{last} et al."
        else:
            last, _ = _split_author(authors[0])
            auth = f"{last} et al."
        if style == "apa":
            return f"({auth}, {year})"
        if style == "ieee":
            return f"[{year}]"
        if style == "mla":
            return f"({auth} {year})"
        if style == "chicago":
            return f"({auth} {year})"
        if style == "nature":
            return f"({auth} {year})"
        return f"({auth}, {year})"


__all__ = ["WritingAssistant"]
