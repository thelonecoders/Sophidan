"""RIS export: serialise ``Paper`` collections to RIS (``.ris``) records.

RIS is the tag-based bibliographic interchange format understood by
Zotero, EndNote, Mendeley, RefWorks and Citavi (the export wizard's
RIS option was previously advertised but had no backend — audit 4-i
missing-(B)1).  Each paper becomes one record of ``TY  - …`` lines
terminated by ``ER  -``; multi-valued tags (authors, keywords) repeat
their tag once per value.

Record layout (the tags consumed by the export wizard)::

    TY  - JOUR
    AU  - Last, First
    TI  - Title
    JO  - Journal / full periodical title
    VL  - Volume
    IS  - Issue
    SP  - Start page
    EP  - End page
    PY  - 2024
    DO  - 10.xxxx/yyyy
    UR  - https://...
    AB  - Abstract
    KW  - keyword
    ER  -
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ._paper_utils import (
    get_authors,
    get_doi,
    get_keywords,
    get_str,
    get_year,
)

logger = logging.getLogger(__name__)

# Map canonical entry types to RIS reference types (TY tag).
_RIS_TYPES: Dict[str, str] = {
    "article": "JOUR",
    "journal-article": "JOUR",
    "journal": "JOUR",
    "inproceedings": "CONF",
    "conference": "CONF",
    "conference-paper": "CONF",
    "proceedings-article": "CONF",
    "book": "BOOK",
    "book-chapter": "CHAP",
    "incollection": "CHAP",
    "techreport": "RPRT",
    "report": "RPRT",
    "preprint": "GEN",
    "misc": "GEN",
    "dataset": "DATA",
    "thesis": "THES",
    "phdthesis": "THES",
    "mastersthesis": "THES",
}

_PAGE_SPLIT_RE = re.compile(r"[–\-]")


def _ris_line(tag: str, value: Any) -> str:
    """Render one ``TAG  - value`` line (value flattened to one line)."""
    if value is None:
        return ""
    s = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not s:
        return ""
    return f"{tag:<2}  - {s}"


class RisExporter:
    """Serialise ``Paper`` collections to RIS text or ``.ris`` files.

    Usage::

        exporter = RisExporter()
        text = exporter.to_string(papers)
        path = exporter.export(papers, "export.ris")
    """

    def __init__(self, wrap_width: int = 0) -> None:
        """Initialise the exporter.

        Args:
            wrap_width: Reserved for line-wrapping long fields; ``0`` (the
                default and the behaviour every RIS consumer expects) keeps
                each tag on a single physical line.
        """
        self.wrap_width = wrap_width

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def to_string(self, papers: Sequence[Any]) -> str:
        """Serialise ``papers`` to RIS text (records separated by blank lines)."""
        records = [self._render_record(p) for p in (papers or [])]
        records = [r for r in records if r]
        return "\n\n".join(records) + ("\n" if records else "")

    def export(self, papers: Sequence[Any], path: Optional[str] = None) -> str:
        """Write ``papers`` to ``path`` as a RIS file.

        Args:
            papers: Sequence of Paper-like objects (dataclasses, ORM
                ``PaperModel`` rows or plain dicts).
            path: Target ``.ris`` path (parent dirs auto-created).  When
                ``None`` a timestamped file is written to the CWD.

        Returns:
            The absolute path written.
        """
        if path:
            target = str(path)
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = os.path.abspath(f"papers_export_{stamp}.ris")
        text = self.to_string(papers)
        os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
        try:
            with open(os.path.abspath(target), "w", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(text)
        except Exception as exc:
            logger.error("RIS write failed -> %s: %s", target, exc, exc_info=True)
            raise
        logger.info("RIS exported -> %s", os.path.abspath(target))
        return os.path.abspath(target)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _render_record(self, paper: Any) -> str:
        """Render a single paper as one RIS record (``TY`` … ``ER``)."""
        lines: List[str] = []

        entry_type = (get_str(paper, "entry_type") or "").lower().strip()
        lines.append(_ris_line("TY", _RIS_TYPES.get(entry_type, "JOUR")))

        for author in get_authors(paper):
            lines.append(_ris_line("AU", author))

        title = get_str(paper, "title")
        if title:
            lines.append(_ris_line("TI", title))

        journal = get_str(paper, "journal") or get_str(paper, "booktitle")
        if journal:
            lines.append(_ris_line("JO", journal))

        volume = get_str(paper, "volume")
        if volume:
            lines.append(_ris_line("VL", volume))
        number = get_str(paper, "number") or get_str(paper, "issue")
        if number:
            lines.append(_ris_line("IS", number))

        pages = get_str(paper, "pages")
        if pages:
            first = last = ""
            # "12-34", "12–34", "12--34", "12" all tolerated.
            parts = [p.strip() for p in _PAGE_SPLIT_RE.split(pages) if p.strip()]
            if len(parts) >= 2:
                first, last = parts[0], parts[1]
            elif parts:
                first = parts[0]
            if first:
                lines.append(_ris_line("SP", first))
            if last:
                lines.append(_ris_line("EP", last))

        year = get_year(paper)
        if year is not None:
            lines.append(_ris_line("PY", str(year)))

        doi = get_doi(paper)
        if doi:
            lines.append(_ris_line("DO", doi))

        url = get_str(paper, "url")
        if not url and doi:
            url = f"https://doi.org/{doi}"
        if url:
            lines.append(_ris_line("UR", url))

        abstract = get_str(paper, "abstract")
        if abstract:
            lines.append(_ris_line("AB", abstract))

        for keyword in get_keywords(paper):
            lines.append(_ris_line("KW", keyword))

        publisher = get_str(paper, "publisher")
        if publisher:
            lines.append(_ris_line("PB", publisher))

        lines.append("ER  - ")
        return "\n".join(lines)


__all__ = ["RisExporter"]
