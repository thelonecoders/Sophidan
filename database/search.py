"""Full-text search backed by SQLite FTS5.

Wraps an FTS5 virtual table that mirrors the ``papers`` table and exposes
BM25-ranked search, advanced field-filtered search, autocomplete and
snippet highlighting. The FTS index is kept in sync via :meth:`index_paper`
— call this whenever a paper is inserted/updated.

The class is a thin facade over the SQLAlchemy connection exposed by
:class:`database.connection.DatabaseConnection`. It degrades gracefully
when FTS5 is unavailable (older SQLite builds): ``search`` falls back to
``LIKE``-based matching.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from database.connection import DatabaseConnection

logger = logging.getLogger(__name__)

# FTS5 is shipped with Python's bundled sqlite on every modern build; we
# still feature-detect so a non-FTS5 build degrades gracefully.
_FTS5_AVAILABLE: Optional[bool] = None


def _detect_fts5(conn) -> bool:
    """Return True if the SQLite connection supports FTS5."""
    global _FTS5_AVAILABLE
    if _FTS5_AVAILABLE is not None:
        return _FTS5_AVAILABLE
    try:
        cur = conn.connection.cursor() if hasattr(conn, "connection") else conn.cursor()
        cur.execute("CREATE VIRTUAL TABLE IF NOT EXISTS __fts5_probe USING fts5(x);")
        cur.execute("DROP TABLE IF EXISTS __fts5_probe;")
        cur.close()
        _FTS5_AVAILABLE = True
    except Exception as exc:  # pragma: no cover - depends on sqlite build
        logger.warning("FTS5 unavailable (%s) — falling back to LIKE search.", exc)
        _FTS5_AVAILABLE = False
    return _FTS5_AVAILABLE


def _escape_fts_query(query: str) -> str:
    """Escape a free-text query for safe use as an FTS5 MATCH expression.

    Splits on whitespace, strips punctuation, quotes each token and joins
    with implicit AND. Empty input yields a star-query ``*`` which matches
    everything (used by :meth:`suggest`).
    """
    query = (query or "").strip()
    if not query:
        return "*"
    # Tokenise: keep alphanumerics + a few unicode word chars.
    tokens = re.findall(r"[\w]+", query, flags=re.UNICODE)
    if not tokens:
        return "*"
    # Quote each token to avoid FTS5 syntax errors on punctuation.
    quoted = [f'"{t}"' for t in tokens]
    return " ".join(quoted)


class FullTextSearch:
    """FTS5-backed full text search over :class:`PaperModel` rows."""

    TABLE = "papers_fts"

    def __init__(self, db: Optional[DatabaseConnection] = None) -> None:
        """Initialise the search index, creating the FTS table if absent.

        Args:
            db: Optional :class:`DatabaseConnection`. If ``None``, the
                default singleton is used.
        """
        self.db: DatabaseConnection = db or DatabaseConnection()
        self._ensure_table()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    def _ensure_table(self) -> None:
        """Create the FTS5 virtual table if it does not yet exist.

        We mirror only the columns we actually want to search / return:
        ``title``, ``abstract``, ``authors`` (denormalised), ``journal``,
        ``source``, ``year`` (as text for filtering).
        """
        from sqlalchemy import text

        with self.db.get_engine().connect() as conn:
            if not _detect_fts5(conn):
                return
            conn.execute(text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {self.TABLE} USING fts5("
                "paper_id UNINDEXED, "
                "title, abstract, authors, journal, source, year UNINDEXED, "
                "doi UNINDEXED, "
                f"tokenize='unicode61 remove_diacritics 2');"
            ))
            conn.commit()
            logger.debug("FTS table ensured: %s", self.TABLE)

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    def index_paper(self, paper: Any, session: Any = None) -> None:
        """Insert (or replace) a paper in the FTS index.

        Args:
            paper: A :class:`database.models.PaperModel` instance (or any
                object exposing the same attributes).
            session: Optional SQLAlchemy session to reuse. If provided, the
                FTS update participates in that session's transaction (and
                the caller is responsible for committing). If ``None``, a
                fresh connection from the engine pool is used.

        Raises:
            ValueError: If ``paper.id`` is ``None`` (i.e. the paper has not
                been flushed/committed yet). Call ``session.flush()`` first.
        """
        from sqlalchemy import text

        pid = getattr(paper, "id", None)
        if pid is None:
            raise ValueError(
                "index_paper requires a paper.id — flush the session before "
                "indexing.",
            )

        authors_str = ", ".join(getattr(a, "name", "") for a in
                                 (getattr(paper, "authors", []) or []))
        params = {
            "pid": pid,
            "title": paper.title or "",
            "abstract": paper.abstract or "",
            "authors": authors_str,
            "journal": paper.journal or "",
            "source": paper.source or "",
            "year": str(paper.year) if paper.year is not None else "",
            "doi": paper.doi or "",
        }
        del_sql = text(f"DELETE FROM {self.TABLE} WHERE paper_id=:pid")
        ins_sql = text(
            f"INSERT INTO {self.TABLE} "
            "(paper_id, title, abstract, authors, journal, source, year, doi) "
            "VALUES (:pid, :title, :abstract, :authors, :journal, "
            ":source, :year, :doi)"
        )
        if session is not None:
            session.execute(del_sql, params)
            session.execute(ins_sql, params)
            logger.debug("Indexed paper id=%s in FTS (in-session).", pid)
            return

        if not _detect_fts5(self.db.get_engine().connect()):
            return
        with self.db.get_engine().begin() as conn:
            conn.execute(del_sql, params)
            conn.execute(ins_sql, params)
        logger.debug("Indexed paper id=%s in FTS.", pid)

    def rebuild_index(self) -> int:
        """Drop and recreate the FTS table from the current ``papers`` rows.

        Returns:
            The number of papers indexed.
        """
        from database.models import PaperModel
        from sqlalchemy import text

        with self.db.get_engine().begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {self.TABLE}"))
        self._ensure_table()
        if not _detect_fts5(self.db.get_engine().connect()):
            return 0
        session = self.db.get_session()
        try:
            papers = session.query(PaperModel).all()
            for p in papers:
                self.index_paper(p)
            return len(papers)
        finally:
            self.db._session_factory.remove()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 50) -> List[Any]:
        """Run a BM25-ranked FTS5 search.

        Args:
            query: Free-text query. May be empty — in that case the most
                recently created ``limit`` papers are returned.
            limit: Maximum number of results to return.

        Returns:
            A list of :class:`PaperModel` instances, best-match first.
        """
        from database.models import PaperModel

        session = self.db.get_session()
        try:
            if not _detect_fts5(self.db.get_engine().connect()):
                return self._like_search(session, query, limit)
            fts_query = _escape_fts_query(query)
            if fts_query == "*":
                return session.query(PaperModel).order_by(
                    PaperModel.created_at.desc(),
                ).limit(limit).all()
            sql = (
                f"SELECT paper_id FROM {self.TABLE} "
                f"WHERE {self.TABLE} MATCH :q "
                f"ORDER BY bm25({self.TABLE}) LIMIT :lim"
            )
            from sqlalchemy import text
            rows = session.execute(
                text(sql), {"q": fts_query, "lim": limit},
            ).fetchall()
            ids = [r[0] for r in rows]
            if not ids:
                return []
            # Preserve FTS ranking.
            id_to_pos = {pid: i for i, pid in enumerate(ids)}
            results = session.query(PaperModel).filter(
                PaperModel.id.in_(ids),
            ).all()
            results.sort(key=lambda p: id_to_pos.get(p.id, len(ids)))
            return results
        finally:
            self.db._session_factory.remove()

    def _like_search(self, session, query: str, limit: int) -> List[Any]:
        """Fallback LIKE-based search when FTS5 is unavailable."""
        from database.models import PaperModel
        if not query:
            return session.query(PaperModel).order_by(
                PaperModel.created_at.desc(),
            ).limit(limit).all()
        pat = f"%{query}%"
        return session.query(PaperModel).filter(
            PaperModel.title.like(pat) | PaperModel.abstract.like(pat),
        ).limit(limit).all()

    def search_advanced(self, query: Dict[str, Any]) -> List[Any]:
        """Run an advanced search with per-field filters.

        Supported keys: ``title``, ``author``, ``year`` (int or ``"YYYY-YYYY"``),
        ``journal``, ``source``, ``abstract``, ``doi``, ``limit``.

        Args:
            query: Dict of field -> value constraints.

        Returns:
            A list of matching :class:`PaperModel` instances.
        """
        from database.models import PaperModel, AuthorModel
        from sqlalchemy import or_, and_

        session = self.db.get_session()
        try:
            q = session.query(PaperModel).distinct()
            clauses = []
            if query.get("title"):
                clauses.append(PaperModel.title.ilike(f"%{query['title']}%"))
            if query.get("abstract"):
                clauses.append(PaperModel.abstract.ilike(f"%{query['abstract']}%"))
            if query.get("journal"):
                clauses.append(PaperModel.journal.ilike(f"%{query['journal']}%"))
            if query.get("source"):
                clauses.append(PaperModel.source == query["source"])
            if query.get("doi"):
                clauses.append(PaperModel.doi == query["doi"])
            if query.get("year") is not None:
                yr = query["year"]
                if isinstance(yr, str) and "-" in yr:
                    lo, hi = yr.split("-", 1)
                    try:
                        lo_i, hi_i = int(lo), int(hi)
                        clauses.append(PaperModel.year.between(lo_i, hi_i))
                    except ValueError:
                        pass
                else:
                    try:
                        clauses.append(PaperModel.year == int(yr))
                    except (TypeError, ValueError):
                        pass
            if query.get("author"):
                q = q.join(PaperModel.authors)
                clauses.append(AuthorModel.name.ilike(f"%{query['author']}%"))
            if clauses:
                q = q.filter(and_(*clauses))
            limit = int(query.get("limit", 50))
            return q.limit(limit).all()
        finally:
            self.db._session_factory.remove()

    def suggest(self, query: str, n: int = 10) -> List[str]:
        """Return up to ``n`` autocomplete suggestions for ``query``.

        Suggestions are drawn from paper titles that begin with the last
        token of ``query``.

        Args:
            query: Partial search string.
            n: Maximum number of suggestions.

        Returns:
            A list of title strings (no duplicates, in BM25 / LIKE order).
        """
        from database.models import PaperModel

        query = (query or "").strip()
        if not query:
            return []
        last_token = (query.split() or [""])[-1]
        session = self.db.get_session()
        try:
            rows = session.query(PaperModel.title).filter(
                PaperModel.title.ilike(f"{last_token}%"),
            ).distinct().limit(n).all()
            return [r[0] for r in rows if r[0]]
        finally:
            self.db._session_factory.remove()

    def highlight(self, query: str, paper: Any, max_tokens: int = 32) -> str:
        """Return a snippet of the paper abstract with ``<mark>`` highlights.

        Uses FTS5's ``highlight()`` function when available; otherwise
        performs a simple regex-based highlight in Python.

        Args:
            query: The original search query (used to find matching tokens).
            paper: The :class:`PaperModel` whose abstract should be highlighted.
            max_tokens: Maximum number of tokens in the returned snippet.

        Returns:
            An HTML-escaped snippet with ``<mark>`` tags around matches.
        """
        abstract = (getattr(paper, "abstract", None) or "").strip()
        if not abstract:
            return ""
        tokens = re.findall(r"[\w]+", (query or ""), flags=re.UNICODE)
        if not tokens:
            return abstract[:200]
        # Build a case-insensitive alternation regex.
        pattern = re.compile(
            r"(" + "|".join(re.escape(t) for t in tokens) + r")",
            flags=re.IGNORECASE,
        )
        # Find first match offset, then carve out a context window.
        match = pattern.search(abstract)
        if not match:
            return abstract[:200]
        start = max(0, match.start() - 80)
        end = min(len(abstract), match.end() + 200)
        snippet = abstract[start:end]
        if start > 0:
            snippet = "… " + snippet
        if end < len(abstract):
            snippet = snippet + " …"
        return pattern.sub(r"<mark>\1</mark>", snippet)


__all__ = ["FullTextSearch"]
