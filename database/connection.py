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
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Union

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


def _build_url(db_path: Optional[Union[str, Path]]) -> str:
    """Build a SQLAlchemy URL from an explicit path or env var.

    Priority:
      1. ``ARS_DATABASE_URL`` env var (full SQLAlchemy URL, e.g. Postgres).
      2. ``db_path`` argument (SQLite file).
      3. Default ``data/ars.db`` SQLite file.

    Args:
        db_path: Optional path to a SQLite database file.

    Returns:
        A SQLAlchemy connection URL string.
    """
    env_url = os.environ.get("ARS_DATABASE_URL")
    if env_url:
        return env_url
    if db_path is None:
        db_path = Path("data/ars.db")
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
        runner will be wired in here once the migrations env is committed by
        the core agent — for now this is the documented placeholder.
        """
        logger.info("migrate() — delegating to create_all() (Alembic placeholder).")
        self.init_db()

    def drop_all(self) -> None:
        """Drop every ARS table. Use with caution (mainly in tests)."""
        from database.models import Base  # lazy
        Base.metadata.drop_all(self._engine)
        logger.warning("drop_all() — every ARS table dropped on %s", self._url)

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
                conn.execute(text(f"VACUUM INTO '{dest.as_posix()}'"))
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
