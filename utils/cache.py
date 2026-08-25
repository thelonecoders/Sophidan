"""SQLite-backed disk cache for HTTP responses and scraper results.

This module exposes two classes:

* :class:`Cache` — a thread-safe pickled key/value cache backed by a single
  SQLite database file. Values are pickled with :mod:`pickle` so arbitrary
  Python objects (HTML, dicts, parsed paper metadata) can be stored.
* :class:`TTLCache` — a :class:`Cache` subclass that records a creation
  timestamp on every entry and refuses to return entries older than their TTL.

The default location is ``data/cache/cache.db`` under the project root, but a
custom path can be passed to the constructor.

The module is independently importable — :mod:`sqlite3` is part of the
standard library, so no third-party deps are required.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
import os
import pickle
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH: Path = _PROJECT_ROOT / "data" / "cache" / "cache.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    key           TEXT PRIMARY KEY,
    value         BLOB NOT NULL,
    created_at    REAL NOT NULL,
    ttl           REAL,
    tag           TEXT
);
CREATE INDEX IF NOT EXISTS idx_cache_entries_tag ON cache_entries(tag);
"""


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
class Cache:
    """A thread-safe SQLite-backed key/value cache with pickled values.

    The cache stores ``(key, value, created_at, ttl, tag)`` rows in a single
    SQLite file. Values are pickled before storage; keys must be strings.
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        *,
        table_name: str = "cache_entries",
    ) -> None:
        """Initialize the cache.

        Args:
            db_path: Path to the SQLite database file. Defaults to
                ``data/cache/cache.db`` under the project root.
            table_name: Name of the table to use (allows multiple caches in
                the same database file).
        """
        self.db_path: Path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.table_name: str = table_name
        self._lock = threading.RLock()
        # SQLite connections are not shareable across threads by default;
        # we open a fresh connection per operation under the lock.
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------ schema
    def _connect(self) -> sqlite3.Connection:
        """Open a new SQLite connection with sensible pragmas."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_schema(self) -> None:
        """Create the schema table if it does not yet exist."""
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(_SCHEMA)
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------ public
    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key.

        Args:
            key: The cache key.
            default: Value returned if the key is missing or expired.

        Returns:
            The unpickled value, or ``default`` if absent / expired.
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    f"SELECT value, ttl, created_at FROM {self.table_name} WHERE key = ?",
                    (str(key),),
                )
                row = cur.fetchone()
            finally:
                conn.close()
        if row is None:
            return default
        value_blob, ttl, created_at = row
        if ttl is not None and (time.time() - created_at) > ttl:
            # Entry has expired — purge it lazily.
            self.invalidate(key)
            return default
        try:
            return pickle.loads(value_blob)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to unpickle cache value for key=%r: %s", key, exc)
            return default

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        tag: Optional[str] = None,
    ) -> None:
        """Store a value under ``key``.

        Args:
            key: The cache key.
            value: The Python object to cache (must be picklable).
            ttl: Optional time-to-live in seconds. ``None`` means never expire.
            tag: Optional grouping tag (e.g. ``"arxiv"``) for selective purge.
        """
        blob = pickle.dumps(value)
        created_at = time.time()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    f"""INSERT INTO {self.table_name}
                        (key, value, created_at, ttl, tag)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            value = excluded.value,
                            created_at = excluded.created_at,
                            ttl = excluded.ttl,
                            tag = excluded.tag
                    """,
                    (str(key), blob, created_at, ttl, tag),
                )
                conn.commit()
            finally:
                conn.close()

    def invalidate(self, key: str) -> bool:
        """Delete a single key.

        Args:
            key: The cache key to remove.

        Returns:
            ``True`` if a row was deleted, ``False`` otherwise.
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    f"DELETE FROM {self.table_name} WHERE key = ?", (str(key),)
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def clear(self, tag: Optional[str] = None) -> int:
        """Remove entries from the cache.

        Args:
            tag: If provided, only entries with this tag are removed. If
                ``None``, the entire cache is cleared.

        Returns:
            Number of rows deleted.
        """
        with self._lock:
            conn = self._connect()
            try:
                if tag is None:
                    cur = conn.execute(f"DELETE FROM {self.table_name}")
                else:
                    cur = conn.execute(
                        f"DELETE FROM {self.table_name} WHERE tag = ?", (tag,)
                    )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def size(self) -> int:
        """Return the total number of cached entries (including expired ones)."""
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {self.table_name}")
                row = cur.fetchone()
                return int(row[0]) if row else 0
            finally:
                conn.close()

    def keys(self, tag: Optional[str] = None) -> list[str]:
        """Return all cache keys, optionally filtered by ``tag``."""
        with self._lock:
            conn = self._connect()
            try:
                if tag is None:
                    cur = conn.execute(f"SELECT key FROM {self.table_name}")
                else:
                    cur = conn.execute(
                        f"SELECT key FROM {self.table_name} WHERE tag = ?", (tag,)
                    )
                return [r[0] for r in cur.fetchall()]
            finally:
                conn.close()

    # ------------------------------------------------------------------ context
    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


# ---------------------------------------------------------------------------
# TTLCache
# ---------------------------------------------------------------------------
class TTLCache(Cache):
    """A :class:`Cache` whose entries auto-expire after a default TTL.

    Example:
        >>> cache = TTLCache(default_ttl=60)
        >>> cache.set("foo", 123)
        >>> cache.get("foo")
        123
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        *,
        default_ttl: float = 3600.0,
        table_name: str = "cache_entries",
    ) -> None:
        """Initialize the TTL cache.

        Args:
            db_path: SQLite database path.
            default_ttl: Default time-to-live (seconds) applied when ``set``
                is called without an explicit ``ttl``.
            table_name: Name of the cache table.
        """
        super().__init__(db_path=db_path, table_name=table_name)
        self.default_ttl: float = float(default_ttl)

    def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        tag: Optional[str] = None,
    ) -> None:
        """Store ``value`` with the configured default TTL if none is given.

        Args:
            key: The cache key.
            value: The Python object to cache.
            ttl: Optional override TTL in seconds; defaults to ``default_ttl``.
            tag: Optional grouping tag.
        """
        if ttl is None:
            ttl = self.default_ttl
        super().set(key, value, ttl=ttl, tag=tag)

    def purge_expired(self) -> int:
        """Remove all expired entries and return the count deleted."""
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    f"DELETE FROM {self.table_name} WHERE ttl IS NOT NULL AND (? - created_at) > ttl",
                    (now,),
                )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()


__all__ = ["Cache", "TTLCache"]
