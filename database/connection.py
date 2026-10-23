"""Singleton SQLite / Postgres connection manager.

Exposes :class:`DatabaseConnection` — a thread-safe, process-wide accessor
around a single SQLAlchemy ``Engine`` and a :func:`scoped_session` factory.
The connection URL defaults to ``data/ars.db`` (SQLite) but can be overridden
either via the constructor or via the ``ARS_DATABASE_URL`` environment
variable (handy for Postgres deployments).

The class also offers maintenance helpers (:meth:`backup`, :meth:`restore`,
:meth:`vacuum`, :meth:`stats`) that wrap the most common DBA tasks.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

try:  # Heavy / optional dep — kept lazy at module load.
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session, scoped_session, sessionmaker

    _HAS_SQLALCHEMY = True
except Exception as exc:  # pragma: no cover - import guard
    _HAS_SQLALCHEMY = False
    _IMPORT_ERROR: Optional[Exception] = exc
    Engine = None  # type: ignore[assignment, misc]
    Session = None  # type: ignore[assignment, misc]
    scoped_session = None  # type: ignore[assignment, misc]
    sessionmaker = None  # type: ignore[assignment, misc]
    create_engine = None  # type: ignore[assignment, misc]
    event = None  # type: ignore[assignment, misc]
    text = None  # type: ignore[assignment, misc]
    logging.getLogger(__name__).warning(
        "SQLAlchemy unavailable — database.connection in stub mode: %s", exc,
    )

# Import the ORM base / models lazily to avoid an import cycle: the models
# module imports SQLAlchemy but does NOT import connection.py.
logger = logging.getLogger(__name__)

# Repo root (parent of the database/ package) — used as the anchor of last
# resort when the settings layer is unavailable.
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


def _default_db_path() -> Path:
    """Resolve the default SQLite DB path via the settings layer.

    Priority:
      1. ``get_settings().resolve_path("db_path")`` — relative values are
         anchored at the *project root*, never the current working directory.
      2. Fallback: ``<repo root>/data/ars.db``.
    """
    try:  # pragma: no cover - settings is a lightweight, import-safe module
        from config.settings import get_settings

        settings = get_settings()
        raw = getattr(settings, "db_path", None)
        if raw:
            try:
                return settings.resolve_path("db_path")
            except Exception:  # pragma: no cover - defensive
                pass
            p = Path(raw)
            if not p.is_absolute():
                p = _PROJECT_ROOT / p
            return p
    except Exception:  # pragma: no cover - defensive
        pass
    return _PROJECT_ROOT / "data" / "ars.db"


def _build_url(db_path: Optional[Union[str, Path]]) -> str:
    """Build a SQLAlchemy URL from an explicit path or env var.

    Priority:
      1. ``ARS_DATABASE_URL`` env var (full SQLAlchemy URL, e.g. Postgres).
      2. ``db_path`` argument (SQLite file).
      3. ``config.settings`` ``db_path`` resolved against the project root
         (see :func:`_default_db_path`).
      4. Last-resort default ``<repo root>/data/ars.db`` SQLite file.

    Args:
        db_path: Optional path to a SQLite database file.

    Returns:
        A SQLAlchemy connection URL string.
    """
    env_url = os.environ.get("ARS_DATABASE_URL")
    if env_url:
        return env_url
    if db_path is None:
        db_path = _default_db_path()
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


class DatabaseConnection:
    """Thread-safe singleton wrapping a SQLAlchemy engine + session factory.

    The singleton is keyed by the resolved URL so tests that spin up a fresh
    in-memory DB (``sqlite:///:memory:``) do not clobber the production
    instance. ``DatabaseConnection()`` called without arguments returns the
    default singleton, creating it on first use.
    """

    _instances: Dict[str, "DatabaseConnection"] = {}
    _instances_lock = threading.Lock()

    def __new__(cls, db_path: Optional[Union[str, Path]] = None) -> "DatabaseConnection":
        url = _build_url(db_path)
        with cls._instances_lock:
            inst = cls._instances.get(url)
            if inst is None:
                inst = super().__new__(cls)
                inst._initialised = False  # type: ignore[attr-defined]
                cls._instances[url] = inst
            return inst

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        # Hold the CLASS lock across the whole check-and-init sequence: two
        # threads constructing the same URL concurrently must not create two
        # engines (the audit's per-URL singleton race).
        with type(self)._instances_lock:
            if getattr(self, "_initialised", False):
                return
            if not _HAS_SQLALCHEMY:
                raise ImportError(
                    "SQLAlchemy is required for DatabaseConnection but could not be "
                    f"imported: {_IMPORT_ERROR!r}. Install it via "
                    "`pip install SQLAlchemy>=2.0`."
                )
            self._url: str = _build_url(db_path)
            self._db_path: Optional[Path] = (
                Path(self._url.replace("sqlite:///", ""))
                if self._url.startswith("sqlite:///") else None
            )
            self._engine: Engine = self._make_engine(self._url)
            self._session_factory: scoped_session = scoped_session(
                sessionmaker(bind=self._engine, expire_on_commit=False,
                             autoflush=False),
            )
            self._lock = threading.RLock()
            self._initialised = True  # type: ignore[attr-defined]
            logger.info("DatabaseConnection initialised for %s", self._url)

    # ------------------------------------------------------------------
    # Engine construction helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _make_engine(url: str) -> Engine:
        """Create a SQLAlchemy engine tuned for ARS workloads.

        For SQLite we enable ``check_same_thread=False`` so background Qt
        workers / QThreads can share the connection, and we activate
        foreign-key enforcement + WAL journaling for resilience.

        Args:
            url: SQLAlchemy connection URL.

        Returns:
            A configured :class:`Engine`.
        """
        if url.startswith("sqlite"):
            engine = create_engine(
                url, future=True, connect_args={"check_same_thread": False},
            )

            @event.listens_for(engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn, _record):  # noqa: D401
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                # journal_mode=WAL requires exclusive access; if the DB is
                # currently locked (e.g. mid-restore) we leave the existing
                # mode in place rather than failing the connection.
                try:
                    cur.execute("PRAGMA journal_mode=WAL")
                except Exception:  # pragma: no cover - rare race
                    pass
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()

        else:
            engine = create_engine(url, future=True, pool_pre_ping=True)
        return engine

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    @classmethod
    def get_existing(
        cls,
        db_path: Optional[Union[str, Path]] = None,
    ) -> Optional["DatabaseConnection"]:
        """Return the already-created singleton for ``db_path``, or ``None``.

        Unlike the constructor this NEVER creates a new connection — used by
        ``main._shutdown`` to close the live database without lazily (re-)
        creating one during process exit.
        """
        url = _build_url(db_path)
        with cls._instances_lock:
            return cls._instances.get(url)

    @classmethod
    def instance(
        cls,
        db_path: Optional[Union[str, Path]] = None,
    ) -> "DatabaseConnection":
        """Return the singleton for ``db_path`` (creating it if needed)."""
        return cls(db_path)

    @property
    def url(self) -> str:
        """Return the SQLAlchemy connection URL in use."""
        return self._url

    @property
    def db_path(self) -> Optional[Path]:
        """Return the on-disk path for SQLite URLs (``None`` otherwise)."""
        return self._db_path

    def get_engine(self) -> Engine:
        """Return the underlying SQLAlchemy ``Engine``."""
        return self._engine

    def get_session(self) -> Session:
        """Return a thread-local scoped session.

        The session is created lazily and reused within the same thread.
        Callers should prefer the :meth:`get_db` context manager for
        short-lived transactions.
        """
        return self._session_factory()

    @contextmanager
    def get_db(self) -> Iterator[Session]:
        """Context manager that yields a session and auto-closes it.

        Commits on clean exit, rolls back on exception. The scoped session
        is removed at exit so subsequent calls in the same thread get a
        fresh session.

        Yields:
            A :class:`Session` instance.
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            self._session_factory.remove()

    def remove_session(self) -> None:
        """Drop the calling thread's scoped session (public helper).

        Replaces the private ``db._session_factory.remove()`` pattern used
        across the codebase.
        """
        self._session_factory.remove()

    # ------------------------------------------------------------------
    # Schema lifecycle
    # ------------------------------------------------------------------
    def init_db(self) -> None:
        """Create all tables defined on :class:`database.models.Base`.

        Safe to call repeatedly — existing tables are left untouched.
        """
        from database.models import Base  # lazy to avoid cycle
        Base.metadata.create_all(self._engine)
        logger.info("init_db() — all tables ensured on %s", self._url)

    def migrate(self) -> None:
        """Apply pending schema migrations.

        Currently this just runs :meth:`init_db`. The real Alembic migration
        runner will be wired in here once the migrations env is committed —
        for now this is the documented placeholder. A ``DBMigrated`` event
        is published on the global :class:`core.events.EventBus` (best
        effort) so listeners can react to schema updates.
        """
        logger.info("migrate() — delegating to create_all() (Alembic placeholder).")
        self.init_db()
        try:  # best-effort event — never fail a migration on the bus
            from core.events import Event, EventType, get_event_bus

            get_event_bus().publish(
                Event(type=EventType.DBMigrated,
                      payload={"url": self._url}, source="database"),
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("DBMigrated publish failed", exc_info=True)

    def drop_all(self) -> None:
        """Drop every ARS table. Use with caution (mainly in tests)."""
        from database.models import Base  # lazy
        Base.metadata.drop_all(self._engine)
        logger.warning("drop_all() — every ARS table dropped on %s", self._url)

    def reset(self) -> None:
        """Wipe the database: drop every table, then re-create the schema.

        Disposes the connection pool first so stale pooled connections do
        not hold locks during the drop. Used by ``main --reset-db``.
        """
        logger.warning("reset() — wiping database at %s", self._url)
        try:
            self._session_factory.remove()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            self._engine.dispose()
        except Exception:  # pragma: no cover - defensive
            pass
        self.drop_all()
        self.init_db()
        logger.warning("reset() — database schema re-created on %s", self._url)

    def close(self) -> None:
        """Close the connection: dispose the engine pool and deregister.

        Alias of :meth:`dispose` (contract #3). In-flight sessions must be
        released by their owning threads first.
        """
        self.dispose()

    # ------------------------------------------------------------------
    # Paper CRUD — CONTRACT #3 (see worklog "PATCH CONTRACTS")
    # ------------------------------------------------------------------
    _PAPER_FIELD_ALIASES = {
        "citation_count": "citations_count",
        "citations": "citations_count",
        "entry_type": "paper_type",
        "type": "paper_type",
        "container_title": "journal",
        "venue": "journal",
        "link": "url",
    }

    _PAPER_FIELDS = (
        "title", "abstract", "year", "doi", "url", "source",
        "citations_count", "publisher", "journal", "volume", "issue",
        "pages", "language", "paper_type",
    )

    @staticmethod
    def _author_names(data: Any) -> List[str]:
        """Normalise an ``authors`` payload into a list of name strings."""
        if data is None:
            return []
        if isinstance(data, str):
            return [a.strip() for a in data.split(";") if a.strip()] \
                if ";" in data else ([data.strip()] if data.strip() else [])
        names: List[str] = []
        if isinstance(data, dict):
            data = [data]
        if isinstance(data, (list, tuple)):
            for item in data:
                if isinstance(item, str) and item.strip():
                    names.append(item.strip())
                elif isinstance(item, dict):
                    nm = item.get("name") or item.get("full_name") or ""
                    if nm.strip():
                        names.append(nm.strip())
        return names

    def _paper_to_dict(self, paper: Any) -> Dict[str, Any]:
        """Serialise a :class:`PaperModel` to the CONTRACT #3 dict shape.

        Keys: ``id, doi, title, authors (list of names), year, journal,
        abstract, citation_count, source, entry_type`` plus useful extras
        (``url``, ``paper_type``, ``citations_count``, ``keywords``,
        ``created_at``, ``updated_at``).
        """
        authors = [a.name for a in (getattr(paper, "authors", None) or [])
                   if getattr(a, "name", None)]
        keywords = [k.term for k in (getattr(paper, "keywords", None) or [])
                    if getattr(k, "term", None)]
        citations = int(getattr(paper, "citations_count", 0) or 0)
        paper_type = getattr(paper, "paper_type", None)
        created = getattr(paper, "created_at", None)
        updated = getattr(paper, "updated_at", None)
        return {
            "id": paper.id,
            "doi": paper.doi,
            "title": paper.title,
            "authors": authors,
            "year": paper.year,
            "journal": paper.journal,
            "abstract": paper.abstract,
            "citation_count": citations,
            "source": paper.source,
            "entry_type": paper_type,
            # Extra (non-contract) convenience keys:
            "citations_count": citations,
            "paper_type": paper_type,
            "url": paper.url,
            "publisher": getattr(paper, "publisher", None),
            "keywords": keywords,
            "created_at": created.isoformat() if created else None,
            "updated_at": updated.isoformat() if updated else None,
        }

    @staticmethod
    def _title_tokens(text: str) -> set:
        """Lowercased word tokens of a title/abstract (for similarity)."""
        return set(re.findall(r"[a-z0-9]+", (text or "").lower()))

    def list_papers(
        self,
        project_id: Optional[int] = None,
        query: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List papers (optionally filtered by project / substring query).

        Args:
            project_id: Restrict to papers linked to this project.
            query: Case-insensitive substring matched against title,
                abstract, journal and DOI.
            limit: Max rows returned.
            offset: Row offset (for pagination).

        Returns:
            List of CONTRACT #3 paper dicts.
        """
        from database.models import PaperModel, ProjectModel
        with self.get_db() as session:
            q = session.query(PaperModel)
            if project_id is not None:
                q = q.join(PaperModel.projects).filter(
                    ProjectModel.id == project_id,
                )
            if query:
                like = f"%{query}%"
                q = q.filter(
                    PaperModel.title.ilike(like)
                    | PaperModel.abstract.ilike(like)
                    | PaperModel.journal.ilike(like)
                    | PaperModel.doi.ilike(like)
                )
            q = q.order_by(PaperModel.created_at.desc(), PaperModel.id.desc())
            papers = q.offset(max(0, int(offset))).limit(max(1, int(limit))).all()
            return [self._paper_to_dict(p) for p in papers]

    def get_paper(self, paper_id: int) -> Optional[Dict[str, Any]]:
        """Return one paper as a CONTRACT #3 dict, or ``None`` if missing."""
        from database.models import PaperModel
        with self.get_db() as session:
            paper = session.get(PaperModel, int(paper_id))
            if paper is None:
                return None
            return self._paper_to_dict(paper)

    def add_paper(self, data: Dict[str, Any]) -> int:
        """Insert a paper (or return the existing id when the DOI matches).

        Recognises both the model column names and common payload aliases
        (``citation_count`` → ``citations_count``, ``entry_type`` →
        ``paper_type``, …). ``authors`` may be a list of name strings, a
        list of ``{"name": …}`` dicts, or a ``;``-separated string; authors
        and keywords are upserted and linked. Unknown keys are ignored.

        After a successful insert the paper is indexed into the SQLite FTS5
        full-text index and a ``"paper_added"`` event is published on the
        global event bus (both best-effort).

        Args:
            data: Paper payload dict.

        Returns:
            The paper id (existing id when de-duplicated by DOI).
        """
        from database.models import AuthorModel, KeywordModel, PaperModel

        cols: Dict[str, Any] = {}
        for key, value in (data or {}).items():
            key = self._PAPER_FIELD_ALIASES.get(key, key)
            if key in self._PAPER_FIELDS:
                cols[key] = value
        if not str(cols.get("title") or "").strip():
            raise ValueError("add_paper requires a non-empty 'title'")
        doi = (cols.get("doi") or None)
        if isinstance(doi, str):
            doi = doi.strip() or None
            cols["doi"] = doi
        year = cols.get("year")
        if year is not None:
            try:
                cols["year"] = int(year)
            except (TypeError, ValueError):
                cols["year"] = None
        citations = cols.get("citations_count")
        if citations is not None:
            try:
                cols["citations_count"] = int(citations)
            except (TypeError, ValueError):
                cols["citations_count"] = 0
        author_names = self._author_names(data.get("authors"))
        keywords = data.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        keyword_terms = [kw.get("term") if isinstance(kw, dict) else kw
                         for kw in keywords]
        keyword_terms = [str(t).strip() for t in keyword_terms
                         if t and str(t).strip()]

        with self.get_db() as session:
            if doi:
                existing = session.query(PaperModel).filter_by(doi=doi).first()
                if existing is not None:
                    logger.debug("add_paper: DOI %s already present (id=%s)",
                                 doi, existing.id)
                    return existing.id
            paper = PaperModel(**cols)
            for name in author_names:
                author = session.query(AuthorModel).filter_by(name=name).first()
                if author is None:
                    author = AuthorModel(name=name)
                    session.add(author)
                paper.authors.append(author)
            for term in keyword_terms:
                kw = session.query(KeywordModel).filter_by(term=term).first()
                if kw is None:
                    kw = KeywordModel(term=term)
                    session.add(kw)
                paper.keywords.append(kw)
            session.add(paper)
            session.flush()
            paper_id = paper.id

        # Index into FTS + publish event AFTER the transaction committed.
        self._index_paper_by_id(paper_id)
        try:
            from core.events import get_event_bus

            get_event_bus().publish(
                "paper_added",
                {"id": paper_id, "doi": doi, "title": cols["title"]},
                source="database",
            )
        except Exception:  # pragma: no cover - defensive
            logger.debug("paper_added publish failed", exc_info=True)
        logger.info("add_paper: inserted paper id=%s (%s)",
                    paper_id, cols["title"][:60])
        return paper_id

    def _index_paper_by_id(self, paper_id: int) -> None:
        """Best-effort FTS indexing of a freshly inserted paper."""
        try:
            from database.models import PaperModel
            from database.search import FullTextSearch

            with self.get_db() as session:
                paper = session.get(PaperModel, paper_id)
                if paper is not None:
                    FullTextSearch(self).index_paper(paper)
        except Exception as exc:  # pragma: no cover - FTS optional
            logger.debug("FTS indexing skipped for paper %s: %s", paper_id, exc)

    def delete_paper(self, paper_id: int) -> bool:
        """Delete a paper by id. Returns ``True`` if a row was removed."""
        from database.models import PaperModel
        with self.get_db() as session:
            paper = session.get(PaperModel, int(paper_id))
            if paper is None:
                return False
            session.delete(paper)
        try:  # keep the FTS index in sync (best effort)
            from sqlalchemy import text as _text

            from database.search import FullTextSearch

            fts = FullTextSearch(self)
            with self._engine.begin() as conn:
                conn.execute(
                    _text(f"DELETE FROM {fts.TABLE} WHERE paper_id = :pid"),
                    {"pid": int(paper_id)},
                )
        except Exception:  # pragma: no cover - FTS optional
            logger.debug("FTS de-indexing skipped for paper %s", paper_id)
        return True

    def search_papers(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Full-text search over papers (FTS5 with LIKE fallback).

        Args:
            query: Free-text query.
            limit: Max results.

        Returns:
            List of CONTRACT #3 paper dicts, best match first.
        """
        try:
            from database.search import FullTextSearch

            hits = FullTextSearch(self).search(query or "", limit=limit)
            with self.get_db() as session:
                return [self._paper_to_dict(p) for p in hits]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("search_papers FTS failed (%s) — LIKE fallback", exc)
            return self.list_papers(query=query, limit=limit)

    def find_similar_papers(
        self,
        paper_id: int,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return papers similar to ``paper_id``, best match first.

        Similarity scoring: shared keywords (2.0 each), shared authors
        (1.0 each), same journal (1.0), overlapping title/abstract tokens
        (0.5 each, capped) and a small same-era bonus. Papers with a zero
        score are excluded.
        """
        from database.models import PaperModel
        with self.get_db() as session:
            base = session.get(PaperModel, int(paper_id))
            if base is None:
                return []
            base_kw = {k.term.lower() for k in (base.keywords or []) if k.term}
            base_au = {a.name.lower() for a in (base.authors or []) if a.name}
            base_tok = self._title_tokens(base.title) | \
                self._title_tokens(base.abstract or "")
            candidates = (
                session.query(PaperModel)
                .filter(PaperModel.id != int(paper_id))
                .order_by(PaperModel.created_at.desc(), PaperModel.id.desc())
                .limit(1000)
                .all()
            )
            scored: List[tuple] = []
            for cand in candidates:
                score = 0.0
                kw = {k.term.lower() for k in (cand.keywords or []) if k.term}
                score += 2.0 * len(base_kw & kw)
                au = {a.name.lower() for a in (cand.authors or []) if a.name}
                score += 1.0 * len(base_au & au)
                if (base.journal and cand.journal
                        and base.journal.lower() == cand.journal.lower()):
                    score += 1.0
                tok = self._title_tokens(cand.title) | \
                    self._title_tokens(cand.abstract or "")
                score += 0.5 * min(len(base_tok & tok), 10)
                if base.year is not None and cand.year is not None:
                    score += max(0.0, 0.5 - abs(base.year - cand.year) * 0.05)
                if score > 0:
                    scored.append((score, cand))
            scored.sort(key=lambda sc: (-sc[0], sc[1].id))
            return [self._paper_to_dict(p) for _, p in scored[:max(1, int(limit))]]

    def get_papers_by_ids(self, ids: Sequence[int]) -> List[Dict[str, Any]]:
        """Return papers for ``ids`` preserving input order (missing → skipped)."""
        from database.models import PaperModel
        wanted = [int(i) for i in (ids or [])]
        if not wanted:
            return []
        with self.get_db() as session:
            papers = session.query(PaperModel).filter(
                PaperModel.id.in_(wanted),
            ).all()
            by_id = {p.id: self._paper_to_dict(p) for p in papers}
        return [by_id[i] for i in wanted if i in by_id]

    # ------------------------------------------------------------------
    # Backup / restore / maintenance
    # ------------------------------------------------------------------
    def backup(self, path: Union[str, Path]) -> Path:
        """Back up the database to ``path``.

        For SQLite we use the ``VACUUM INTO`` statement (atomic, online
        backup that does not block readers). For other backends we fall
        back to a file copy of the on-disk DB (Postgres users should use
        ``pg_dump`` — but we cannot invoke that here portably).

        Args:
            path: Destination file path.

        Returns:
            The resolved destination :class:`Path`.
        """
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self._url.startswith("sqlite"):
            with self._engine.connect() as conn:
                # VACUUM (INTO) cannot run inside a transaction.
                conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                # Bound parameter — the previous f-string interpolation was
                # both an injection risk and a quoting hazard.
                conn.execute(text("VACUUM INTO :dest"), {"dest": str(dest)})
            logger.info("backup() — SQLite DB backed up to %s", dest)
        else:
            # Fallback: copy the on-disk file if we can find one.
            if self._db_path and self._db_path.exists():
                shutil.copy2(self._db_path, dest)
                logger.info("backup() — DB file copied to %s", dest)
            else:
                raise RuntimeError(
                    "backup() is only implemented for SQLite backends in this "
                    "build; use pg_dump for Postgres.",
                )
        return dest

    def restore(self, path: Union[str, Path]) -> None:
        """Restore the DB from a backup file.

        Replaces the current SQLite file with the contents of ``path`` and
        disposes the engine pool so subsequent connections pick up the new
        file. All in-flight sessions are invalidated.

        .. note::

            This call closes the calling thread's scoped session and the
            engine's connection pool. In a multi-threaded app, other
            threads must release their sessions before this is called —
            otherwise the underlying ``shutil.copy2`` may fail with a
            "database is locked" error on Windows, or succeed but leave
            stale ``-wal`` data on POSIX.

        Args:
            path: Source backup file path.
        """
        src = Path(path)
        if not src.exists():
            raise FileNotFoundError(f"Backup file not found: {src}")
        if not self._url.startswith("sqlite"):
            raise RuntimeError(
                "restore() is only implemented for SQLite backends in this build.",
            )
        if self._db_path is None:
            raise RuntimeError("Cannot restore — db_path is None for non-sqlite URL.")
        # 1. Drop this thread's scoped session (so it releases its conn).
        try:
            self._session_factory.remove()
        except Exception:  # pragma: no cover
            pass
        # 2. Checkpoint the WAL into the main DB file (no-op if not WAL).
        try:
            with self._engine.connect() as conn:
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
        except Exception:  # pragma: no cover
            pass
        # 3. Dispose the engine pool — closes every pooled connection.
        self._engine.dispose()
        # 4. Replace the main DB file. Also delete any stale -wal / -shm
        # files so they do not resurrect pre-restore data on next open.
        shutil.copy2(src, self._db_path)
        for suffix in ("-wal", "-shm"):
            side = self._db_path.with_name(self._db_path.name + suffix)
            if side.exists():
                try:
                    side.unlink()
                except OSError as exc:  # pragma: no cover
                    logger.warning("Could not remove %s: %s", side, exc)
        logger.warning("restore() — DB replaced from %s", src)

    def vacuum(self) -> None:
        """Run ``VACUUM`` to reclaim free pages and defragment the SQLite DB."""
        if not self._url.startswith("sqlite"):
            logger.warning("vacuum() is a no-op on non-SQLite backends.")
            return
        with self._engine.connect() as conn:
            # VACUUM cannot run inside a transaction.
            old_isolation = conn.get_execution_options().get("isolation_level")
            try:
                conn.execution_options(isolation_level="AUTOCOMMIT")
                conn.execute(text("VACUUM"))
            finally:
                if old_isolation is not None:
                    conn.execution_options(isolation_level=old_isolation)
        logger.info("vacuum() — SQLite VACUUM completed.")

    def stats(self) -> Dict[str, Any]:
        """Return a dict of DB-level and table-level statistics.

        Returns:
            Dict with keys: ``url``, ``db_size_bytes``, ``table_counts``,
            ``page_count``, ``page_size``.
        """
        out: Dict[str, Any] = {"url": self._url}
        if self._url.startswith("sqlite") and self._db_path and self._db_path.exists():
            out["db_size_bytes"] = self._db_path.stat().st_size
            with sqlite3.connect(self._db_path) as raw:
                cur = raw.cursor()
                cur.execute("PRAGMA page_count")
                out["page_count"] = cur.fetchone()[0]
                cur.execute("PRAGMA page_size")
                out["page_size"] = cur.fetchone()[0]
            # Table counts via SQLAlchemy.
            from database.models import (
                PaperModel, AuthorModel, ProjectModel, KeywordModel,
                FieldOfStudyModel, SnapshotModel, ProxyModel,
                EmbeddingModel, QueryHistoryModel,
            )
            session = self._session_factory()
            try:
                out["table_counts"] = {
                    "papers": session.query(PaperModel).count(),
                    "authors": session.query(AuthorModel).count(),
                    "projects": session.query(ProjectModel).count(),
                    "keywords": session.query(KeywordModel).count(),
                    "fields_of_study": session.query(FieldOfStudyModel).count(),
                    "snapshots": session.query(SnapshotModel).count(),
                    "proxies": session.query(ProxyModel).count(),
                    "embeddings": session.query(EmbeddingModel).count(),
                    "query_history": session.query(QueryHistoryModel).count(),
                }
            finally:
                self._session_factory.remove()
        else:
            out["db_size_bytes"] = None
            out["note"] = "Detailed stats only available for SQLite backend."
        out["captured_at"] = datetime.now(timezone.utc).isoformat()
        return out

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
    @classmethod
    def reset_singleton(cls) -> None:
        """Drop all cached singletons (mainly useful in tests)."""
        with cls._instances_lock:
            for inst in cls._instances.values():
                try:
                    inst._engine.dispose()
                except Exception:  # pragma: no cover
                    pass
            cls._instances.clear()

    def dispose(self) -> None:
        """Dispose the engine pool and drop this instance from the registry."""
        with self._instances_lock:
            self._engine.dispose()
            self._instances.pop(self._url, None)


__all__ = ["DatabaseConnection"]
