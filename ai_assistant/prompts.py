"""Curated prompt templates for academic paper analysis.

This module exposes a :class:`PromptTemplates` container with named prompt
templates covering the most common AI-assisted research workflows: summarizing
papers and topics, extracting keywords and entities, generating literature
reviews, critiquing papers, brainstorming research questions, augmenting
partial bibliographic citations, and identifying research gaps.

Every template is a ``string.Template`` so it can be formatted with
:meth:`PromptTemplates.format`. The :meth:`format` method tolerates both
``$var`` and ``${var}`` substitution syntax and ignores unknown keyword
arguments (extra kwargs are silently dropped).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import string
from typing import Any, Dict

logger = logging.getLogger(__name__)


class PromptTemplates:
    """Curated collection of prompt templates for academic AI workflows.

    Each attribute is a :class:`string.Template` instance with documented
    substitution variables. Use :meth:`format` to render a template safely
    (missing variables fall back to an empty string; unknown variables raise
    nothing).
    """

    # ------------------------------------------------------------------
    # Single-paper summarization
    # ------------------------------------------------------------------
    SUMMARIZE_PAPER: string.Template = string.Template(
        """You are a meticulous academic research assistant. Produce a structured
summary of the paper below.

PAPER TITLE: $title
AUTHORS: $authors
YEAR: $year
ABSTRACT: $abstract
FULL TEXT (or excerpts):
$body

Return your answer as Markdown with these sections (omit any section that
cannot be answered from the text):

## Abstract
<2-3 sentence restatement of the core contribution>

## Key Findings
- <finding 1>
- <finding 2>
- ...

## Methodology
<brief description of data, methods, and experimental setup>

## Limitations
<honest critique of sample size, scope, threats to validity>

## Future Work
<concrete open questions or next steps suggested by the authors>
"""
    )
    """Variables: ``$title``, ``$authors``, ``$year``, ``$abstract``, ``$body``."""

    # ------------------------------------------------------------------
    # Topic synthesis
    # ------------------------------------------------------------------
    SUMMARIZE_TOPIC: string.Template = string.Template(
        """You are a domain expert synthesizing $n_papers academic papers about
the topic: "$topic".

PAPERS:
$papers_list

Produce a synthesis that:
1. States the consensus view across the corpus.
2. Identifies 2-3 sub-themes or research threads.
3. Notes methodological trends.
4. Calls out disagreements or contradictory findings.
5. Ends with 2-3 directions for future work.

Answer in well-structured Markdown.
"""
    )
    """Variables: ``$n_papers``, ``$topic``, ``$papers_list``."""

    # ------------------------------------------------------------------
    # Keyword extraction
    # ------------------------------------------------------------------
    EXTRACT_KEYWORDS: string.Template = string.Template(
        """Extract 5 to 15 keywords from the text below. For each keyword provide
a relevance score in the range [0, 1].

TEXT:
$text

Return your answer as a JSON array of objects with "keyword" and "score"
fields, e.g.:
[{{"keyword": "transformer architecture", "score": 0.95}}, ...]
"""
    )
    """Variables: ``$text``."""

    # ------------------------------------------------------------------
    # Entity extraction
    # ------------------------------------------------------------------
    EXTRACT_ENTITIES: string.Template = string.Template(
        """Identify named entities in the text below. Return JSON with these keys:
- authors: list of {{"name": str, "affiliation": str}}
- institutions: list of str
- methods: list of str
- datasets: list of {{"name": str, "url": str?}}

TEXT:
$text

Return ONLY the JSON object, no commentary.
"""
    )
    """Variables: ``$text``."""

    # ------------------------------------------------------------------
    # Literature review generation
    # ------------------------------------------------------------------
    GENERATE_LITERATURE_REVIEW: string.Template = string.Template(
        """Generate a flowing academic literature review from the supplied papers.

STYLE: $style
TOPIC (optional): $topic
N PAPERS: $n_papers

PAPERS (each item has title, authors, year, abstract):
$papers_json

Write the review in third person, academic register. Group papers thematically
rather than listing them one by one. Use inline citations in (Author, Year)
form. Length: 600-1000 words. Conclude with a short paragraph on gaps.
"""
    )
    """Variables: ``$style``, ``$topic``, ``$n_papers``, ``$papers_json``."""

    # ------------------------------------------------------------------
    # Paper critique
    # ------------------------------------------------------------------
    CRITIQUE_PAPER: string.Template = string.Template(
        """Critically evaluate the paper below as a peer reviewer.

PAPER TITLE: $title
AUTHORS: $authors
YEAR: $year
ABSTRACT: $abstract
BODY EXCERPTS:
$body

Provide a structured critique in Markdown:

## Strengths
- <strength 1>
- <strength 2>

## Weaknesses
- <weakness 1>
- <weakness 2>

## Implications
- <theoretical>
- <practical>
- <methodological>
"""
    )
    """Variables: ``$title``, ``$authors``, ``$year``, ``$abstract``, ``$body``."""

    # ------------------------------------------------------------------
    # Chat system prompt
    # ------------------------------------------------------------------
    CHAT_SYSTEM: string.Template = string.Template(
        """You are the Academic Research Suite (ARS) assistant, an AI helper
embedded in a desktop research tool. Your job is to help researchers:

- Find, summarize, and compare academic papers.
- Synthesize literature reviews and identify research gaps.
- Explain bibliometric, network, and topic-modeling analyses.
- Suggest search queries, citation graph queries, and visualizations.
- Format results as Markdown when helpful.

Be concise, accurate, and honest about uncertainty. When you reference a
specific paper, cite it by (Author, Year). If asked to use a tool you do not
have access to (e.g. live scraping), explain the limitation and suggest a
fallback. The current user context is:

USER PROJECT: $project
USER FOCUS TOPIC: $topic
"""
    )
    """Variables: ``$project``, ``$topic``."""

    # ------------------------------------------------------------------
    # Research question generation
    # ------------------------------------------------------------------
    RESEARCH_QUESTIONS: string.Template = string.Template(
        """Based on the corpus summary below, generate 5 novel, non-trivial
research questions that a graduate student could pursue. Each question must:
- Be specific and falsifiable.
- Reference at least one cited paper.
- Identify a measurable outcome.

CORPUS SUMMARY:
$corpus_summary

PAPERS REFERENCED:
$papers_list

Return as a numbered Markdown list with a one-sentence rationale per question.
"""
    )
    """Variables: ``$corpus_summary``, ``$papers_list``."""

    # ------------------------------------------------------------------
    # Bibliographic augmentation
    # ------------------------------------------------------------------
    BIBLIOGRAPHIC_AUGMENT: string.Template = string.Template(
        """A user has supplied a partial bibliographic citation. Fill in the
missing fields using your knowledge of the academic literature, and flag any
field you cannot confidently populate.

KNOWN FIELDS:
$known_fields

MISSING FIELDS:
$missing_fields

Return JSON with keys: title, authors, year, journal, volume, issue, pages,
doi, publisher. Use null for any field you cannot determine. Add a
"confidence" sub-object mapping field name to a [0, 1] score.
"""
    )
    """Variables: ``$known_fields``, ``$missing_fields``."""

    # ------------------------------------------------------------------
    # Research gap identification
    # ------------------------------------------------------------------
    IDENTIFY_RESEARCH_GAPS: string.Template = string.Template(
        """Identify 3 to 5 concrete research gaps on the topic: "$topic".

Consider these dimensions:
1. Methodological gaps (e.g. lack of causal inference, weak baselines).
2. Data gaps (e.g. under-represented populations, missing modalities).
3. Theoretical gaps (e.g. unexplained phenomena, conflicting results).
4. Application gaps (e.g. domain transfer failures).
5. Reproducibility gaps.

For each gap, cite at least one anchor paper if available.

ANCHOR PAPERS:
$papers_list

Return as Markdown headings (## Gap 1, etc.), each followed by 2-3 sentences.
"""
    )
    """Variables: ``$topic``, ``$papers_list``."""

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    @classmethod
    def names(cls) -> list[str]:
        """Return the sorted list of public template attribute names."""
        return sorted(
            name
            for name in vars(cls)
            if name.isupper()
            and not name.startswith("_")
            and isinstance(getattr(cls, name), string.Template)
        )

    @classmethod
    def get(cls, name: str) -> string.Template:
        """Look up a template by attribute name.

        Args:
            name: Attribute name (e.g. ``"SUMMARIZE_PAPER"``).

        Returns:
            The :class:`string.Template` instance.

        Raises:
            AttributeError: If no such template exists.
        """
        attr = name.upper()
        try:
            tmpl = getattr(cls, attr)
        except AttributeError as exc:
            raise AttributeError(f"No prompt template named {name!r}") from exc
        if not isinstance(tmpl, string.Template):
            raise AttributeError(f"{name!r} is not a prompt template")
        return tmpl

    @classmethod
    def format(cls, template: Any, **kwargs: Any) -> str:
        """Render a template by name or instance with safe substitution.

        Args:
            template: Either a template attribute name (``"SUMMARIZE_PAPER"``)
                or a :class:`string.Template` instance.
            **kwargs: Substitution variables. Unknown placeholders are left
                as-is; missing variables are replaced with an empty string.

        Returns:
            The rendered prompt string.

        Raises:
            AttributeError: If ``template`` is a string that does not match
                a known template.
        """
        if isinstance(template, str):
            tmpl = cls.get(template)
        elif isinstance(template, string.Template):
            tmpl = template
        else:
            raise TypeError(
                f"template must be a name or string.Template, got {type(template).__name__}"
            )
        # safe_substitute keeps unknown placeholders as-is, but we want them
        # to silently drop missing kwargs to an empty string instead.
        placeholder_map: Dict[str, str] = {}
        for key, val in kwargs.items():
            placeholder_map[key] = "" if val is None else str(val)
        # Identify variables the template actually references so we don't
        # pollute the substitution namespace.
        referenced = _template_identifiers(tmpl.template)
        sub_map = {k: placeholder_map.get(k, "") for k in referenced}
        # Also include any explicitly provided kwargs not in the template
        # (no-op, but explicit).
        for k, v in placeholder_map.items():
            sub_map.setdefault(k, v)
        return tmpl.safe_substitute(sub_map)


def _template_identifiers(text: str) -> list[str]:
    """Return the list of ``$var`` / ``${var}`` identifiers in ``text``."""
    import re

    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
    names: list[str] = []
    seen: set[str] = set()
    for m in pattern.finditer(text):
        name = m.group(1) or m.group(2)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


__all__ = ["PromptTemplates"]
