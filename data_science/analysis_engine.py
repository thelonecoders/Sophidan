"""Central data-analysis orchestrator for the Academic Research Suite.

The :class:`AnalysisEngine` consumes ``data_acquisition.base_scraper.Paper``
objects (or pandas DataFrames with the same column schema) and exposes a
unified, high-level API for:

* loading & persisting paper collections (parquet / csv / json),
* computing summary statistics (year range, top journals / authors,
  citation quartiles, per-author h-index),
* cleaning text for downstream NLP,
* dispatching progress / status events through the project's EventBus.

All heavy / optional dependencies (sentence-transformers, bertopic,
statsmodels, etc.) are lazily imported by the sibling modules; this module
itself only requires numpy + pandas + the standard library.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical Paper field set (mirrors data_acquisition.base_scraper.Paper)
# ---------------------------------------------------------------------------

_PAPER_FIELDS: tuple[str, ...] = (
    "title", "authors", "abstract", "year", "doi",
    "citations_count", "references", "keywords", "fields_of_study",
)

# Optional journal / source fields we *may* find on a Paper.
_OPTIONAL_FIELDS: tuple[str, ...] = (
    "journal", "source", "venue", "publisher",
)

# A small built-in stop-word set for the text cleaner (used only when
# remove_stopwords=True is requested explicitly).
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "to", "was", "were", "will", "with", "we", "our", "this",
    "these", "those", "i", "you", "he", "she", "they", "but", "not",
    "abstract", "introduction", "method", "methods", "result", "results",
    "conclusion", "conclusions", "discussion", "figure", "table", "data",
    "study", "paper", "research", "article", "journal", "et", "al",
})


# ---------------------------------------------------------------------------
# EventBus integration (lazy + best-effort)
# ---------------------------------------------------------------------------

_EVENT_BUS: Any = None
_EVENT_BUS_RESOLVED: bool = False


def _resolve_event_bus() -> Any:
    """Resolve the project's EventBus instance/class (if available).

    Returns:
        The EventBus instance/class, or ``None`` if not importable.
    """
    global _EVENT_BUS, _EVENT_BUS_RESOLVED
    if _EVENT_BUS_RESOLVED:
        return _EVENT_BUS
    _EVENT_BUS_RESOLVED = True
    try:
        from core.events import EventBus  # type: ignore
        if isinstance(EventBus, type):
            try:
                # Prefer an existing singleton accessor
                inst = getattr(EventBus, "instance", None)
                if callable(inst):
                    _EVENT_BUS = inst()
                else:
                    _EVENT_BUS = EventBus()
            except Exception:
                _EVENT_BUS = EventBus  # fall back to the class itself
        else:
            _EVENT_BUS = EventBus
    except Exception:
        _EVENT_BUS = None
    return _EVENT_BUS


def _emit(event_name: str, payload: Optional[dict] = None) -> None:
    """Emit an event through the EventBus (best-effort).

    Args:
        event_name: Logical event name (e.g. ``"papers.loaded"``).
        payload: Optional dictionary payload.
    """
    bus = _resolve_event_bus()
    if bus is None:
        logger.debug("[event] %s payload=%s", event_name, payload)
        return
    for attr in ("emit", "publish", "dispatch"):
        fn = getattr(bus, attr, None)
        if callable(fn):
            try:
                fn(event_name, payload)
                return
            except Exception:  # pragma: no cover - defensive
                logger.debug("EventBus.%s failed for %s", attr, event_name)
    logger.debug("[event] %s payload=%s (no emitter)", event_name, payload)


# ---------------------------------------------------------------------------
# Paper <-> dict helpers
# ---------------------------------------------------------------------------

def _paper_to_dict(paper: Any) -> dict:
    """Coerce a Paper-like object into a plain dict."""
    if isinstance(paper, dict):
        return dict(paper)
    if is_dataclass(paper) and not isinstance(paper, type):
        try:
            return asdict(paper)
        except Exception:
            pass
    out = {f: getattr(paper, f, None) for f in _PAPER_FIELDS}
    for opt in _OPTIONAL_FIELDS:
        if hasattr(paper, opt):
            out[opt] = getattr(paper, opt)
    return out


def _coerce_list(value: Any) -> list:
    """Coerce arbitrary input to a Python list (handles delimited strings)."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, str):
        parts = re.split(r"[;,|]", value)
        return [p.strip() for p in parts if p.strip()]
    try:
        return list(value)
    except TypeError:
        return [value]


class AnalysisEngine:
    """Central data-analysis orchestrator.

    The AnalysisEngine consumes Paper dataclass instances (or pandas
    DataFrames) and exposes a unified API for computing summary
    statistics, cleaning text, and persisting datasets. All long-running
    operations emit progress events through the project's EventBus.
    """

    def __init__(self, event_bus: Any = None) -> None:
        """Initialize the engine.

        Args:
            event_bus: Optional EventBus instance. If omitted, the
                engine attempts to resolve ``core.events.EventBus``
                lazily.
        """
        global _EVENT_BUS, _EVENT_BUS_RESOLVED
        self.logger = logger
        self._papers: List[dict] = []
        if event_bus is not None:
            _EVENT_BUS = event_bus
            _EVENT_BUS_RESOLVED = True

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_papers(self, papers: Iterable[Any]) -> int:
        """Load a sequence of Paper objects.

        Args:
            papers: Iterable of Paper dataclass instances or dicts.

        Returns:
            The number of papers loaded.
        """
        self._papers = [_paper_to_dict(p) for p in papers]
        self.logger.info("Loaded %d papers", len(self._papers))
        _emit("papers.loaded", {"count": len(self._papers)})
        return len(self._papers)

    def load_from_dataframe(self, df: pd.DataFrame) -> int:
        """Load papers from a pandas DataFrame.

        Args:
            df: DataFrame whose columns include (a subset of) the
                canonical Paper fields.

        Returns:
            The number of papers loaded.
        """
        records: List[dict] = []
        for _, row in df.iterrows():
            rec: dict = {}
            for col in _PAPER_FIELDS:
                if col in df.columns:
                    val = row[col]
                    rec[col] = None if pd.isna(val) else val
                else:
                    rec[col] = None
            for opt in _OPTIONAL_FIELDS:
                if opt in df.columns:
                    val = row[opt]
                    rec[opt] = None if pd.isna(val) else val
            records.append(rec)
        self._papers = records
        self.logger.info("Loaded %d papers from DataFrame", len(self._papers))
        _emit("papers.loaded",
              {"count": len(self._papers), "source": "dataframe"})
        return len(self._papers)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the loaded papers to a pandas DataFrame.

        Returns:
            A DataFrame with one row per paper. List-valued fields are
            serialized to delimited strings so the DataFrame is
            export-safe.
        """
        if not self._papers:
            return pd.DataFrame(columns=list(_PAPER_FIELDS))
        records = []
        for p in self._papers:
            rec = {}
            for f in _PAPER_FIELDS:
                v = p.get(f)
                if isinstance(v, (list, tuple, set)):
                    rec[f] = "; ".join(str(x) for x in v)
                else:
                    rec[f] = v
            for opt in _OPTIONAL_FIELDS:
                if opt in p:
                    rec[opt] = p[opt]
            records.append(rec)
        return pd.DataFrame(records)

    def save(self, path: str, format: str = "parquet") -> None:
        """Save the loaded papers to disk.

        Args:
            path: Destination file path.
            format: One of ``"parquet"``, ``"csv"``, ``"json"``.

        Raises:
            ValueError: If the format is unsupported.
        """
        df = self.to_dataframe()
        fmt = format.lower()
        _emit("papers.saving", {"path": path, "format": fmt, "count": len(df)})
        if fmt == "parquet":
            try:
                df.to_parquet(path, index=False)
            except Exception as exc:
                # Fall back to CSV if parquet backend missing
                self.logger.warning(
                    "Parquet export failed (%s); falling back to CSV", exc
                )
                fallback = path.rsplit(".", 1)[0] + ".csv"
                df.to_csv(fallback, index=False)
                _emit("papers.saved", {"path": fallback, "format": "csv",
                                       "count": len(df)})
                return
        elif fmt == "csv":
            df.to_csv(path, index=False)
        elif fmt == "json":
            df.to_json(path, orient="records", force_ascii=False, indent=2)
        else:
            raise ValueError(f"Unsupported format: {format}")
        self.logger.info("Saved %d papers -> %s (%s)", len(df), path, fmt)
        _emit("papers.saved", {"path": path, "format": fmt, "count": len(df)})

    def load(self, path: str) -> int:
        """Load papers from a previously saved file (parquet/csv/json).

        Args:
            path: Source file path.

        Returns:
            Number of papers loaded.
        """
        _emit("papers.loading", {"path": path})
        if path.endswith(".parquet"):
            try:
                df = pd.read_parquet(path)
            except Exception as exc:
                self.logger.warning(
                    "Parquet read failed (%s); trying CSV", exc
                )
                df = pd.read_csv(path)
        elif path.endswith(".csv"):
            df = pd.read_csv(path)
        elif path.endswith(".json"):
            df = pd.read_json(path, orient="records")
        else:
            # Best-effort by extension
            df = pd.read_csv(path)
        return self.load_from_dataframe(df)

    # ------------------------------------------------------------------
    # Text cleaning
    # ------------------------------------------------------------------

    # Patterns applied in order to strip common LaTeX fragments.
    _LATEX_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"\$\$[^$]*\$\$"), " "),
        (re.compile(r"\$[^$]*\$"), " "),
        (re.compile(r"\\[a-zA-Z]+\*?(?:\{[^{}]*\})?"), " "),
        (re.compile(r"\\[(),;!\[\]]"), " "),
        (re.compile(r"[{}\\]"), " "),
    ]

    @classmethod
    def clean_text(
        cls,
        text: str,
        lowercase: bool = False,
        remove_stopwords: bool = False,
    ) -> str:
        """Clean text for analysis: strip LaTeX, normalize unicode.

        Args:
            text: Input text.
            lowercase: If True, lower-case the result.
            remove_stopwords: If True, drop a small built-in stop-word set.

        Returns:
            Cleaned text.
        """
        if not isinstance(text, str):
            text = "" if text is None else str(text)
        # Unicode normalization (NFKC maps ligatures + compatibility chars)
        text = unicodedata.normalize("NFKC", text)
        for pattern, repl in cls._LATEX_PATTERNS:
            text = pattern.sub(repl, text)
        text = re.sub(r"\s+", " ", text).strip()
        if lowercase:
            text = text.lower()
        if remove_stopwords:
            tokens = [t for t in text.split() if t not in _STOPWORDS]
            text = " ".join(tokens)
        return text

    # ------------------------------------------------------------------
    # Summary statistics
    # ------------------------------------------------------------------

    def summary_stats(self) -> dict:
        """Compute summary statistics for the loaded corpus.

        Returns:
            A dict with keys: ``count``, ``year_range``,
            ``top_journals``, ``top_authors``, ``citation_stats``
            (mean/median/std/min/max/q1/q3/iqr/sum), and
            ``h_index_per_author``.
        """
        if not self._papers:
            return {}
        df = self.to_dataframe()
        stats: dict = {"count": len(df)}

        # Year range
        years = pd.to_numeric(df.get("year"), errors="coerce").dropna()
        if not years.empty:
            stats["year_range"] = {
                "min": int(years.min()),
                "max": int(years.max()),
            }
        else:
            stats["year_range"] = None

        # Top journals / sources / venues
        journal_col: Optional[str] = None
        for opt in _OPTIONAL_FIELDS:
            if opt in df.columns:
                journal_col = opt
                break
        top_journals: List[dict] = []
        if journal_col:
            vc = df[journal_col].dropna().astype(str)
            vc = vc[~vc.str.lower().isin({"", "nan", "none", "null"})]
            if not vc.empty:
                top_journals = [
                    {"journal": j, "count": int(c)}
                    for j, c in vc.value_counts().head(10).items()
                ]
        stats["top_journals"] = top_journals

        # Top authors
        author_counter: Counter = Counter()
        for authors in df.get("authors", pd.Series(dtype=object)):
            if isinstance(authors, str):
                for a in re.split(r"[;,]", authors):
                    a = a.strip()
                    if a:
                        author_counter[a] += 1
        stats["top_authors"] = [
            {"author": a, "count": int(c)}
            for a, c in author_counter.most_common(10)
        ]

        # Citation statistics
        cites = pd.to_numeric(
            df.get("citations_count"), errors="coerce"
        ).dropna()
        if not cites.empty:
            q1 = float(cites.quantile(0.25))
            q3 = float(cites.quantile(0.75))
            stats["citation_stats"] = {
                "mean": float(cites.mean()),
                "median": float(cites.median()),
                "std": float(cites.std(ddof=0)) if len(cites) > 1 else 0.0,
                "min": float(cites.min()),
                "max": float(cites.max()),
                "q1": q1,
                "q3": q3,
                "iqr": q3 - q1,
                "sum": float(cites.sum()),
            }
        else:
            stats["citation_stats"] = None

        # Per-author h-index
        stats["h_index_per_author"] = self._author_h_indices(df)
        _emit("stats.computed", {"count": stats["count"]})
        return stats

    def _author_h_indices(self, df: pd.DataFrame) -> List[dict]:
        """Compute the h-index for each author across their papers."""
        author_cites: dict[str, List[int]] = defaultdict(list)
        for _, row in df.iterrows():
            authors_raw = row.get("authors")
            if not isinstance(authors_raw, str):
                continue
            authors = [a.strip() for a in re.split(r"[;,]", authors_raw) if a.strip()]
            if not authors:
                continue
            try:
                c = int(row.get("citations_count") or 0)
            except (TypeError, ValueError):
                c = 0
            for a in authors:
                author_cites[a].append(c)
        out = []
        for author, clist in author_cites.items():
            h = self._h_index(clist)
            out.append({
                "author": author,
                "h_index": h,
                "papers": len(clist),
                "total_citations": int(sum(clist)),
            })
        out.sort(key=lambda x: (-x["h_index"], -x["papers"], x["author"]))
        return out

    @staticmethod
    def _h_index(citations: Sequence[int]) -> int:
        """Compute the h-index of a citation list."""
        s = sorted((int(c) for c in citations), reverse=True)
        h = 0
        for i, c in enumerate(s, start=1):
            if c >= i:
                h = i
            else:
                break
        return h
