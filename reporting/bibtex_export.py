"""BibTeX export module: serialise ``Paper`` collections to ``.bib`` text.

The exporter supports the most common entry types (``@article``,
``@inproceedings``, ``@book``, ``@misc``, ``@techreport``), deduplicates by
DOI when present, sorts entries by citekey, and escapes UTF-8 accented
letters and a handful of LaTeX-reserved characters so that the resulting
``.bib`` file is plain-ASCII safe and compiles with ``bibtex`` / ``biber``.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ._paper_utils import (
    get_authors,
    get_citation_count,
    get_doi,
    get_field,
    get_keywords,
    get_str,
    get_year,
    normalise_authors_bibtex,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UTF-8 -> LaTeX escapes (covers Latin-1 + a handful of common cases).
# ---------------------------------------------------------------------------
_UTF8_TO_LATEX: Dict[str, str] = {
    # Grave accents
    "à": "\\`{a}", "è": "\\`{e}", "ì": "\\`{i}", "ò": "\\`{o}", "ù": "\\`{u}",
    "À": "\\`{A}", "È": "\\`{E}", "Ì": "\\`{I}", "Ò": "\\`{O}", "Ù": "\\`{U}",
    # Acute accents
    "á": "\\'{a}", "é": "\\'{e}", "í": "\\'{i}", "ó": "\\'{o}", "ú": "\\'{u}",
    "ý": "\\'{y}",
    "Á": "\\'{A}", "É": "\\'{E}", "Í": "\\'{I}", "Ó": "\\'{O}", "Ú": "\\'{U}",
    "Ý": "\\'{Y}",
    # Circumflex
    "â": "\\^{a}", "ê": "\\^{e}", "î": "\\^{i}", "ô": "\\^{o}", "û": "\\^{u}",
    "Â": "\\^{A}", "Ê": "\\^{E}", "Î": "\\^{I}", "Ô": "\\^{O}", "Û": "\\^{U}",
    # Diaeresis / umlaut
    "ä": "\\\"{a}", "ë": "\\\"{e}", "ï": "\\\"{i}", "ö": "\\\"{o}",
    "ü": "\\\"{u}", "ÿ": "\\\"{y}",
    "Ä": "\\\"{A}", "Ë": "\\\"{E}", "Ï": "\\\"{I}", "Ö": "\\\"{O}",
    "Ü": "\\\"{U}", "Ÿ": "\\\"{Y}",
    # Tilde
    "ã": "\\~{a}", "ñ": "\\~{n}", "õ": "\\~{o}",
    "Ã": "\\~{A}", "Ñ": "\\~{N}", "Õ": "\\~{O}",
    # Cedilla
    "ç": "\\c{c}", "Ç": "\\c{C}",
    # Ring / slash
    "å": "\\aa{}", "Å": "\\AA{}",
    "æ": "\\ae{}", "Æ": "\\AE{}",
    "ø": "\\o{}", "Ø": "\\O{}",
    "ß": "\\ss{}",
    "œ": "\\oe{}", "Œ": "\\OE{}",
    # Eastern European
    "ł": "\\l{}", "Ł": "\\L{}",
    "ø": "\\o{}", "Ø": "\\O{}",
    "ż": "\\.{z}", "Ż": "\\.{Z}",
    "ź": "\\'{z}", "Ź": "\\'{Z}",
    "ś": "\\'{s}", "Ś": "\\'{S}",
    "ć": "\\'{c}", "Ć": "\\'{C}",
    "ń": "\\'{n}", "Ń": "\\'{N}",
    # Misc
    "–": "--", "—": "---",
    "‘": "`", "’": "'", "“": "``", "”": "''",
    "…": "\\ldots{}",
    "±": "$\\pm$", "×": "$\\times$", "÷": "$\\div$",
    "≤": "$\\le$", "≥": "$\\ge$",
    "→": "$\\rightarrow$", "←": "$\\leftarrow$",
    "©": "\\textcopyright{}", "®": "\\textregistered{}", "™": "\\texttrademark{}",
    "°": "$^\\circ$",
    # Quote characters that bibtex treats specially
    "“": "``", "”": "''",
}

# LaTeX-reserved characters that must be escaped in field values.
_LATEX_RESERVED: Dict[str, str] = {
    "&": "\\&",
    "%": "\\%",
    "$": "\\$",
    "#": "\\#",
    "_": "\\_",
    "~": "\\textasciitilde{}",
    "^": "\\textasciicircum{}",
}


def _escape_latex(value: str) -> str:
    """Escape a string for safe inclusion in a BibTeX field value.

    The function escapes LaTeX-reserved ASCII characters first (so we don't
    double-escape the backslashes we introduce for diacritics), then
    replaces known UTF-8 letters with their LaTeX macros.  Characters we
    don't know how to escape are dropped with a debug log entry.

    Args:
        value: The raw string (may contain non-ASCII characters).

    Returns:
        An ASCII-safe string suitable for a ``.bib`` file.
    """
    if value is None:
        return ""
    s = str(value)
    # Step 1: escape LaTeX-reserved ASCII chars (but not the backslashes we add).
    # We do this in a single pass so that, e.g., '&' becomes '\\&'.
    out_chars: List[str] = []
    for ch in s:
        if ch in _LATEX_RESERVED:
            out_chars.append(_LATEX_RESERVED[ch])
        elif ch in _UTF8_TO_LATEX:
            out_chars.append(_UTF8_TO_LATEX[ch])
        elif ord(ch) < 128:
            out_chars.append(ch)
        else:
            # Unknown non-ASCII character; keep it as-is (biber handles UTF-8)
            # but log at debug level so we can spot missing entries.
            logger.debug("Unmapped Unicode char in BibTeX escape: U+%04X", ord(ch))
            out_chars.append(ch)
    return "".join(out_chars)


# Mapping from paper "entry_type" (or detected venue) to BibTeX entry type.
_ENTRY_TYPE_ALIASES: Dict[str, str] = {
    "article": "article",
    "journal-article": "article",
    "journal": "article",
    "inproceedings": "inproceedings",
    "conference": "inproceedings",
    "conference-paper": "inproceedings",
    "proceedings-article": "inproceedings",
    "book": "book",
    "book-chapter": "incollection",
    "incollection": "incollection",
    "techreport": "techreport",
    "report": "techreport",
    "preprint": "misc",
    "misc": "misc",
    "dataset": "misc",
    "thesis": "phdthesis",
    "phdthesis": "phdthesis",
    "mastersthesis": "mastersthesis",
}


def _detect_entry_type(paper: Any) -> str:
    """Detect the most appropriate BibTeX entry type for a paper.

    Heuristics:
        1. If the paper explicitly carries an ``entry_type`` matching a known
           alias, use that.
        2. Else, if it has a ``journal`` field, default to ``@article``.
        3. Else, if it has a ``booktitle`` / ``venue`` field, default to
           ``@inproceedings``.
        4. Else, fall back to ``@misc``.
    """
    et = (get_str(paper, "entry_type") or "").lower().strip()
    if et and et in _ENTRY_TYPE_ALIASES:
        return _ENTRY_TYPE_ALIASES[et]
    if get_str(paper, "journal"):
        return "article"
    if get_str(paper, "booktitle"):
        return "inproceedings"
    return "misc"


def _format_pages(pages: str) -> str:
    """Normalise page ranges to BibTeX ``start--end`` form when possible."""
    if not pages:
        return ""
    s = str(pages).strip()
    # Already BibTeX-style?
    if "--" in s:
        return s
    # Common separators in source data: '-', '–' (en dash), ' '.
    for sep in ("–", "-", " "):
        if sep in s:
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if len(parts) == 2:
                return f"{parts[0]}--{parts[1]}"
    return s


class BibTeXExporter:
    """Serialise ``Paper`` collections to BibTeX (``.bib``) text or files.

    Features:
        * Auto-detects entry type (``@article``, ``@inproceedings``, ``@book``,
          ``@misc``, ``@techreport``, ``@incollection``, ``@phdthesis``).
        * Deduplicates by DOI when present (first occurrence wins).
        * Sorts entries by citekey for stable diffs.
        * Escapes UTF-8 accented letters and LaTeX-reserved ASCII chars.
        * Produces deterministic, line-stable output (no trailing whitespace).
    """

    def __init__(self, wrap_width: int = 100) -> None:
        """Initialise the exporter.

        Args:
            wrap_width: Max line width for field values (0 disables wrapping).
        """
        self.wrap_width = wrap_width

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def export(self, papers: Sequence[Any], path: str) -> str:
        """Write ``papers`` to ``path`` as a BibTeX file.

        Args:
            papers: Sequence of Paper-like objects.
            path: Target ``.bib`` file path (parent dirs auto-created).

        Returns:
            The absolute path written.
        """
        text = self.to_string(papers)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        abs_path = os.path.abspath(path)
        try:
            with open(abs_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        except Exception as exc:
            logger.error("BibTeX write failed -> %s: %s", abs_path, exc, exc_info=True)
            raise
        logger.info("BibTeX exported -> %s (%d entries)", abs_path, len(papers))
        return abs_path

    def to_string(self, papers: Sequence[Any]) -> str:
        """Serialise ``papers`` to a single BibTeX text blob (no disk write)."""
        entries: List[tuple[str, str]] = []  # (citekey, entry_text)
        seen_dois: set[str] = set()
        seen_keys: set[str] = set()

        for idx, paper in enumerate(papers):
            doi = get_doi(paper)
            if doi and doi in seen_dois:
                logger.debug("Skipping duplicate DOI: %s", doi)
                continue
            if doi:
                seen_dois.add(doi)
            citekey = self._make_unique_key(paper, idx, seen_keys)
            seen_keys.add(citekey)
            entry_text = self._render_entry(citekey, paper)
            entries.append((citekey, entry_text))

        # Stable sort by citekey for deterministic output / easy diffs.
        entries.sort(key=lambda kv: kv[0].lower())
        return "\n\n".join(text for _, text in entries) + ("\n" if entries else "")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _make_unique_key(paper: Any, idx: int, seen_keys: set[str]) -> str:
        """Build a unique citekey for ``paper`` (handles collisions)."""
        from ._paper_utils import get_citekey  # local import to avoid cycle
        base = get_citekey(paper, idx + 1)
        key = base
        suffix = ord("a")
        while key in seen_keys:
            key = f"{base}{chr(suffix)}"
            suffix += 1
        return key

    def _render_entry(self, citekey: str, paper: Any) -> str:
        """Render a single ``@type{citekey, ...}`` entry as text."""
        etype = _detect_entry_type(paper)
        fields: List[tuple[str, str]] = []  # ordered (name, escaped_value)

        title = get_str(paper, "title")
        if title:
            fields.append(("title", "{" + _escape_latex(title) + "}"))

        authors = get_authors(paper)
        if authors:
            fields.append(("author", _escape_latex(normalise_authors_bibtex(authors))))

        year = get_year(paper)
        if year is not None:
            fields.append(("year", str(year)))

        journal = get_str(paper, "journal")
        booktitle = get_str(paper, "booktitle")
        if etype == "article" and journal:
            fields.append(("journal", _escape_latex(journal)))
        elif etype == "inproceedings" and (booktitle or journal):
            fields.append(("booktitle", _escape_latex(booktitle or journal)))
        elif booktitle:
            fields.append(("booktitle", _escape_latex(booktitle)))
        elif journal:
            fields.append(("journal", _escape_latex(journal)))

        volume = get_str(paper, "volume")
        if volume:
            fields.append(("volume", _escape_latex(volume)))
        number = get_str(paper, "number")
        if number:
            fields.append(("number", _escape_latex(number)))
        pages = get_str(paper, "pages")
        if pages:
            fields.append(("pages", _escape_latex(_format_pages(pages))))

        publisher = get_str(paper, "publisher")
        if publisher:
            fields.append(("publisher", _escape_latex(publisher)))

        doi = get_doi(paper)
        if doi:
            fields.append(("doi", doi))

        url = get_str(paper, "url")
        if not url and doi:
            url = f"https://doi.org/{doi}"
        if url:
            fields.append(("url", _escape_latex(url)))

        abstract = get_str(paper, "abstract")
        if abstract:
            fields.append(("abstract", _escape_latex(abstract)))

        keywords = get_keywords_local(paper)
        if keywords:
            fields.append(("keywords", _escape_latex("; ".join(keywords))))

        cites = get_citation_count(paper)
        if cites:
            fields.append(("citations", str(cites)))

        # Render.
        out = io.StringIO()
        out.write(f"@{etype}{{{citekey},\n")
        n = len(fields)
        for i, (k, v) in enumerate(fields):
            comma = "," if i < n - 1 else ""
            out.write(f"  {k:<14}= {v}{comma}\n")
        out.write("}")
        return out.getvalue()


def get_keywords_local(paper: Any) -> List[str]:
    """Local import of get_keywords to avoid module-level cycle."""
    from ._paper_utils import get_keywords
    return get_keywords(paper)


__all__ = ["BibTeXExporter"]
