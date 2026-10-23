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
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ._paper_utils import (
    calculate_h_index,
    get_authors,
    get_citation_count,
    get_cited_dois,
    get_doi,
    get_field,
    get_keywords,
    get_str,
    get_year,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Excel formula-injection guard (audit 4-i): cells beginning with ``=``,
# ``+``, ``-``, ``@``, TAB or CR would be executed/interpreted by Excel &
# friends when the CSV is opened.  Neutralise with a leading apostrophe and
# strip control characters that break row structure.
# ---------------------------------------------------------------------------
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitize_csv_value(value: Any) -> Any:
    """Return a CSV/Excel-safe version of ``value``.

    Rules:
      * ``None`` → ``""``; ints/floats are passed through untouched
        (numeric cells are never formula-interpreted);
      * CR / LF / TAB characters are replaced with spaces (they corrupt
        rows and can smuggle formula payloads onto continuation lines);
      * a remaining leading ``=`` / ``+`` / ``-`` / ``@`` is neutralised by
        prefixing an apostrophe (Excel renders the text verbatim without
        evaluating it).
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return value
    s = str(value)
    if any(ch in s for ch in ("\r", "\n", "\t")):
        s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    if s[:1] in _FORMULA_PREFIXES:
        s = "'" + s
    return s


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
        delimiter: str = ",",
    ) -> None:
        """Initialise the exporter.

        Args:
            encoding: File encoding (``utf-8-sig`` default for Excel compat).
            quoting: ``csv`` quoting level (``csv.QUOTE_MINIMAL`` default).
            escapechar: Character used to escape the quote char when doubling
                is disabled; ``None`` to rely on quote doubling.
            lineterminator: Line terminator to use in the output.
            delimiter: Field separator (``,`` default; ``\t`` for TSV).
        """
        self.encoding = encoding
        self.quoting = quoting
        self.escapechar = escapechar
        self.lineterminator = lineterminator
        self.delimiter = delimiter

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

        Each paper's cited references are resolved via
        :func:`._paper_utils.get_cited_dois`, which understands the raw
        ``cited_by`` / ``cited_dois`` string/list forms *and* the ORM's
        ``PaperModel.references`` (a list of ``ReferenceModel`` objects
        exposing ``.cited_doi``) — previously the canonical ORM shape
        produced a header-only file (audit 4-i A13).  Only edges with both
        ends resolvable to a DOI are emitted.
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
            for ref_doi in get_cited_dois(p):
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
                    delimiter=self.delimiter,
                    quoting=self.quoting,
                    escapechar=self.escapechar,
                    lineterminator=self.lineterminator,
                )
                writer.writeheader()
                for row in rows:
                    # Coerce all values to strings, neutralise Excel formula
                    # injection and strip row-breaking control characters.
                    out = {k: sanitize_csv_value(row.get(k)) for k in columns}
                    writer.writerow(out)
        except Exception as exc:
            logger.error("CSV write failed -> %s: %s", abs_path, exc, exc_info=True)
            raise
        logger.info("CSV exported -> %s (%d rows)", abs_path, len(rows))
        return abs_path


# ---------------------------------------------------------------------------
# Module-level contract wrappers (PATCH CONTRACT #6).
# ``web/routes/export.py`` and ``ui/dialogs/export_wizard.py`` import these
# from either the ``reporting`` package or ``reporting.csv_export``.
# ---------------------------------------------------------------------------
def _default_export_path(extension: str) -> str:
    """Timestamped default output path in the CWD when ``path=None``."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.abspath(f"papers_export_{stamp}.{extension}")


def export_csv(
    papers: Sequence[Any],
    path: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> str:
    """Contract #6: export ``papers`` to CSV and return the written path.

    A ``.tsv`` target switches the field delimiter to a tab (the web layer
    hands the same function a ``.tsv`` path for TSV exports).
    """
    target = path or _default_export_path("csv")
    delimiter = "\t" if str(target).lower().endswith(".tsv") else ","
    exporter = CSVExporter(delimiter=delimiter)
    return exporter.export(papers, target, columns=columns)


def export_xlsx(
    papers: Sequence[Any],
    path: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> str:
    """Contract #6: export ``papers`` to a real ``.xlsx`` workbook.

    Uses ``openpyxl`` (already a declared dependency); every cell goes
    through the same formula-injection guard as the CSV writer.  Raises
    ``ImportError`` when openpyxl is unavailable.
    """
    try:
        from openpyxl import Workbook  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - optional dep
        logger.error("openpyxl not installed: %s", exc)
        raise
    target = path or _default_export_path("xlsx")
    cols = list(columns) if columns else list(DEFAULT_PAPER_COLUMNS)
    exporter = CSVExporter()
    os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "papers"
    ws.append([c.replace("_", " ").title() for c in cols])
    for p in papers:
        row = exporter._paper_to_row(p, cols)
        ws.append([sanitize_csv_value(row.get(c)) for c in cols])
    abs_path = os.path.abspath(target)
    try:
        wb.save(abs_path)
    except Exception as exc:
        logger.error("XLSX write failed -> %s: %s", abs_path, exc, exc_info=True)
        raise
    logger.info("XLSX exported -> %s (%d rows)", abs_path, len(papers))
    return abs_path


__all__ = [
    "CSVExporter",
    "DEFAULT_PAPER_COLUMNS",
    "DEFAULT_AUTHOR_COLUMNS",
    "sanitize_csv_value",
    "export_csv",
    "export_xlsx",
]
