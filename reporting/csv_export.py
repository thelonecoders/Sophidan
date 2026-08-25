"""CSV export module: flatten ``Paper`` collections to tabular CSV files.

Provides three exporters:
    * :meth:`CSVExporter.export`           — one row per paper (wide format).
    * :meth:`CSVExporter.export_authors`   — one row per author (aggregated).
    * :meth:`CSVExporter.export_citations`— citation edges (citing_doi, cited_doi).

All exports default to UTF-8-with-BOM (``utf-8-sig``) so that Excel on
Windows renders accented letters and CJK glyphs correctly.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import csv
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ._paper_utils import (
    calculate_h_index,
    get_authors,
    get_citation_count,
    get_doi,
    get_field,
    get_keywords,
    get_str,
    get_year,
)

logger = logging.getLogger(__name__)


# Default paper-level columns (ordered).
DEFAULT_PAPER_COLUMNS: List[str] = [
    "doi",
    "title",
    "authors",
    "year",
    "journal",
    "booktitle",
    "volume",
    "number",
    "pages",
    "publisher",
    "url",
    "citations",
    "keywords",
    "abstract",
    "entry_type",
]

# Default author-level columns.
DEFAULT_AUTHOR_COLUMNS: List[str] = [
    "author",
    "paper_count",
    "total_citations",
    "h_index",
    "first_year",
    "last_year",
    "dois",
]


class CSVExporter:
    """Export ``Paper`` collections and their derivatives to CSV files."""

    def __init__(
        self,
        encoding: str = "utf-8-sig",
        quoting: int = csv.QUOTE_MINIMAL,
        escapechar: Optional[str] = "\\",
        lineterminator: str = "\n",
    ) -> None:
        """Initialise the exporter.

        Args:
            encoding: File encoding (``utf-8-sig`` default for Excel compat).
            quoting: ``csv`` quoting level (``csv.QUOTE_MINIMAL`` default).
            escapechar: Character used to escape the quote char when doubling
                is disabled; ``None`` to rely on quote doubling.
            lineterminator: Line terminator to use in the output.
        """
        self.encoding = encoding
        self.quoting = quoting
        self.escapechar = escapechar
        self.lineterminator = lineterminator

    # ------------------------------------------------------------------
    # Paper-level export
    # ------------------------------------------------------------------
    def export(
        self,
        papers: Sequence[Any],
        path: str,
        columns: Optional[List[str]] = None,
    ) -> str:
        """Export ``papers`` to ``path`` as a single CSV (one row per paper).

        Args:
            papers: Sequence of Paper-like objects.
            path: Output file path (parent dirs are auto-created).
            columns: Optional override list of column names.  Defaults to
                :data:`DEFAULT_PAPER_COLUMNS`.

        Returns:
            The absolute path written.
        """
        cols = list(columns) if columns else list(DEFAULT_PAPER_COLUMNS)
        rows = [self._paper_to_row(p, cols) for p in papers]
        return self._write_csv(path, cols, rows)

    def to_dataframe(self, papers: Sequence[Any]) -> Any:
        """Flatten ``papers`` to a ``pandas.DataFrame`` (no disk write).

        List-valued fields (``authors``, ``keywords``) are joined with ``;``
        so that the cell content remains CSV/Excel-friendly.
        """
        try:
            import pandas as pd  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover
            logger.error("pandas not installed: %s", exc)
            raise
        cols = DEFAULT_PAPER_COLUMNS
        rows = [self._paper_to_row(p, cols) for p in papers]
        return pd.DataFrame(rows, columns=cols)

    # ------------------------------------------------------------------
    # Author-level export
    # ------------------------------------------------------------------
    def export_authors(self, papers: Sequence[Any], path: str) -> str:
        """Export an author-level aggregated CSV (one row per author).

        Columns: author, paper_count, total_citations, h_index, first_year,
        last_year, dois.
        """
        agg: Dict[str, Dict[str, Any]] = {}
        for p in papers:
            authors = get_authors(p)
            cites = get_citation_count(p)
            doi = get_doi(p)
            y = get_year(p)
            for a in authors:
                if a not in agg:
                    agg[a] = {
                        "paper_count": 0,
                        "total_citations": 0,
                        "cite_list": [],
                        "years": [],
                        "dois": [],
                    }
                agg[a]["paper_count"] += 1
                agg[a]["total_citations"] += cites
                agg[a]["cite_list"].append(cites)
                if y is not None:
                    agg[a]["years"].append(y)
                if doi:
                    agg[a]["dois"].append(doi)

        rows = []
        for author, data in agg.items():
            years = data["years"]
            rows.append({
                "author": author,
                "paper_count": data["paper_count"],
                "total_citations": data["total_citations"],
                "h_index": calculate_h_index(data["cite_list"]),
                "first_year": min(years) if years else "",
                "last_year": max(years) if years else "",
                "dois": ";".join(data["dois"]),
            })
        # Sort by paper_count desc, then author asc for stable output.
        rows.sort(key=lambda r: (-r["paper_count"], r["author"]))
        return self._write_csv(path, DEFAULT_AUTHOR_COLUMNS, rows)

    # ------------------------------------------------------------------
    # Citation edges export
    # ------------------------------------------------------------------
    def export_citations(self, papers: Sequence[Any], path: str) -> str:
        """Export citation edges as a CSV (columns: citing_doi, cited_doi).

        Each paper's ``cited_by`` / ``references_doi`` attribute is iterated;
        only edges with both ends resolvable to a DOI are emitted.
        """
        citing_by_doi: Dict[str, str] = {}
        for p in papers:
            doi = get_doi(p)
            if doi:
                # Prefer the title as the human-readable label, fall back to DOI.
                citing_by_doi[doi] = get_str(p, "title") or doi
        rows: List[Dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for p in papers:
            citing_doi = get_doi(p)
            if not citing_doi:
                continue
            cited_refs = get_field(p, "cited_by", default=[]) or []
            if isinstance(cited_refs, str):
                cited_refs = [c.strip() for c in cited_refs.replace(",", ";").split(";") if c.strip()]
            elif not isinstance(cited_refs, (list, tuple)):
                cited_refs = []
            for ref in cited_refs:
                if isinstance(ref, dict):
                    ref_doi = ref.get("doi") or ref.get("cited_doi") or ref.get("DOI")
                else:
                    ref_doi = str(ref).strip()
                if not ref_doi:
                    continue
                # Strip URL prefix.
                for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
                    if ref_doi.lower().startswith(prefix.lower()):
                        ref_doi = ref_doi[len(prefix):]
                        break
                ref_doi = ref_doi.lower().strip()
                if not ref_doi:
                    continue
                edge = (citing_doi, ref_doi)
                if edge in seen:
                    continue
                seen.add(edge)
                rows.append({"citing_doi": citing_doi, "cited_doi": ref_doi})
        return self._write_csv(path, ["citing_doi", "cited_doi"], rows)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _paper_to_row(self, paper: Any, columns: List[str]) -> Dict[str, Any]:
        """Convert a single Paper-like object to a flat row dict."""
        row: Dict[str, Any] = {}
        for col in columns:
            if col == "authors":
                authors = get_authors(paper)
                row[col] = "; ".join(authors)
            elif col == "keywords":
                kws = get_keywords(paper)
                row[col] = "; ".join(kws)
            elif col == "citations":
                row[col] = get_citation_count(paper)
            elif col == "year":
                y = get_year(paper)
                row[col] = y if y is not None else ""
            elif col == "doi":
                row[col] = get_doi(paper)
            else:
                v = get_str(paper, col)
                row[col] = v
        return row

    def _write_csv(
        self,
        path: str,
        columns: List[str],
        rows: Sequence[Dict[str, Any]],
    ) -> str:
        """Write ``rows`` to ``path`` and return the absolute path."""
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        abs_path = os.path.abspath(path)
        try:
            with open(abs_path, "w", encoding=self.encoding, newline="") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=columns,
                    quoting=self.quoting,
                    escapechar=self.escapechar,
                    lineterminator=self.lineterminator,
                )
                writer.writeheader()
                for row in rows:
                    # Coerce all values to strings; None -> "".
                    out = {k: ("" if row.get(k) is None else row.get(k)) for k in columns}
                    writer.writerow(out)
        except Exception as exc:
            logger.error("CSV write failed -> %s: %s", abs_path, exc, exc_info=True)
            raise
        logger.info("CSV exported -> %s (%d rows)", abs_path, len(rows))
        return abs_path


__all__ = ["CSVExporter", "DEFAULT_PAPER_COLUMNS", "DEFAULT_AUTHOR_COLUMNS"]
