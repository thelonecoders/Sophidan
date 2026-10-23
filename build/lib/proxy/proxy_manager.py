"""Central proxy registry: data model + thread-safe manager.

Defines the :class:`Proxy` dataclass used everywhere in the suite and the
:class:`ProxyManager` class that stores proxies in-memory, persists them to
SQLite (via :mod:`database.connection` when available, with a local-file
fallback), and emits Qt signals so the UI layer can react.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# --- Optional Qt shim -------------------------------------------------------
try:  # qtpy abstracts PyQt5 / PySide2
    from qtpy.QtCore import QObject, Signal  # type: ignore
    _HAVE_QT = True
except Exception:  # pragma: no cover - headless environments
    logger.debug("qtpy not available; ProxyManager will run without Qt signals.")

    class _StubSignal:
        """Minimal stand-in so signal attributes never raise."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._slots: List[Any] = []

        def connect(self, slot: Any) -> None:
            self._slots.append(slot)

        def emit(self, *args: Any, **kwargs: Any) -> None:
            for slot in list(self._slots):
                try:
                    slot(*args, **kwargs)
                except Exception:  # pragma: no cover - never let a slot kill callers
                    logger.exception("slot raised in stub signal")

    class QObject:  # type: ignore[no-redef]
        """Trivial QObject replacement used when Qt is unavailable."""

    def Signal(*args: Any, **kwargs: Any) -> _StubSignal:  # type: ignore[no-redef]
        return _StubSignal()

    _HAVE_QT = False


VALID_PROTOCOLS = ("http", "https", "socks4", "socks5")
VALID_ANONYMITY = ("transparent", "anonymous", "elite")
VALID_STRATEGIES = ("round_robin", "random", "best", "weighted")


@dataclass
class Proxy:
    """A single proxy server entry.

    Attributes:
        host: IPv4 / IPv6 address or hostname.
        port: TCP port.
        protocol: One of ``http|https|socks4|socks5``.
        username: Optional auth username.
        password: Optional auth password.
        country: ISO country code or full name (filled by geoip lookup).
        anonymity: ``transparent|anonymous|elite``.
        source: Where the proxy was scraped from (URL or label).
        latency_ms: Last measured round-trip in ms (``None`` = untested).
        last_check: Epoch seconds of last health check.
        success_count: Cumulative successful requests.
        fail_count: Cumulative failed requests.
        score: Internal ranking score (higher = better).
    """

    host: str
    port: int
    protocol: str = "http"
    username: Optional[str] = None
    password: Optional[str] = None
    country: Optional[str] = None
    anonymity: str = "anonymous"
    source: Optional[str] = None
    latency_ms: Optional[float] = None
    last_check: Optional[float] = None
    success_count: int = 0
    fail_count: int = 0
    score: float = 0.0

    def __post_init__(self) -> None:
        self.protocol = self.protocol.lower()
        if self.protocol not in VALID_PROTOCOLS:
            raise ValueError(
                f"protocol must be one of {VALID_PROTOCOLS}, got {self.protocol!r}"
            )
        self.anonymity = self.anonymity.lower()
        if self.anonymity not in VALID_ANONYMITY:
            raise ValueError(
                f"anonymity must be one of {VALID_ANONYMITY}, got {self.anonymity!r}"
            )
        if not (1 <= int(self.port) <= 65535):
            raise ValueError(f"port out of range: {self.port}")

    # -- derived properties --------------------------------------------------
    @property
    def address(self) -> str:
        """Return ``host:port``."""
        return f"{self.host}:{self.port}"

    @property
    def url(self) -> str:
        """Return a full URL form ``scheme://[user:pass@]host:port``."""
        auth = ""
        if self.username:
            auth = f"{self.username}:{self.password or ''}@"
        return f"{self.protocol}://{auth}{self.host}:{self.port}"

    @property
    def fail_rate(self) -> float:
        """Fraction of failed requests (``0.0`` if no history)."""
        total = self.success_count + self.fail_count
        return self.fail_count / total if total else 0.0

    @property
    def is_healthy(self) -> bool:
        """``True`` if the proxy looks usable (low fail rate, recent check)."""
        if self.fail_count > self.success_count and (self.fail_count >= 3):
            return False
        if self.last_check is None:
            return True  # untested -> optimistically healthy
        age = time.time() - self.last_check
        if age > 24 * 3600:  # not checked in 24h
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Proxy":
        """Reconstruct a :class:`Proxy` from a dict (ignores unknown keys)."""
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# SQLite helper
# ---------------------------------------------------------------------------
_DB_TABLE = "proxy_pool_cache"
_DB_COLUMNS = (
    "host TEXT NOT NULL",
    "port INTEGER NOT NULL",
    "protocol TEXT NOT NULL",
    "username TEXT",
    "password TEXT",
    "country TEXT",
    "anonymity TEXT",
    "source TEXT",
    "latency_ms REAL",
    "last_check REAL",
    "success_count INTEGER DEFAULT 0",
    "fail_count INTEGER DEFAULT 0",
    "score REAL DEFAULT 0.0",
    "PRIMARY KEY (host, port, protocol)",
)


def _local_db_path() -> Path:
    """Return path to the fallback local SQLite file (created on demand)."""
    base = Path.home() / ".academic_research_suite"
    base.mkdir(parents=True, exist_ok=True)
    return base / "proxies.db"


def _get_db_connection() -> Optional[sqlite3.Connection]:
    """Return a SQLite connection or ``None`` if unavailable.

    Prefers the shared :mod:`database.connection` helper (lazy import to
    avoid a hard dependency on the database sub-package which may not exist
    yet during early bootstrap).  Falls back to a local SQLite file.
    """
    # 1) Try the project's shared DB connection helper.
    try:
        from database.connection import DatabaseConnection  # type: ignore

        # ``database.connection`` exposes a SQLAlchemy-based singleton;
        # ``raw_connection()`` yields the underlying sqlite3 connection.
        engine = DatabaseConnection().get_engine()
        conn = engine.raw_connection()
        if conn is not None:
            _ensure_table(conn)
            return conn
    except Exception as exc:  # pragma: no cover - bootstrap-time path
        logger.debug("database.connection unavailable, using local DB: %s", exc)

    # 2) Fallback to a local file.
    try:
        conn = sqlite3.connect(str(_local_db_path()), check_same_thread=False)
        _ensure_table(conn)
        return conn
    except Exception:  # pragma: no cover
        logger.exception("failed to open local proxy DB")
        return None


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Create the proxy cache table if missing."""
    try:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {_DB_TABLE} ({', '.join(_DB_COLUMNS)})")
        conn.commit()
    except Exception:  # pragma: no cover - shared DB may already have it
        logger.debug("could not create proxy table (probably already present)")


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class ProxyManager(QObject):
    """Thread-safe registry of :class:`Proxy` objects.

    The manager keeps proxies in memory for O(1) lookup and mirrors state to
    SQLite so proxies survive a restart.  It emits Qt signals (``proxy_added``,
    ``proxy_removed``, ``proxy_rotated``, ``proxy_failed``) so UI widgets can
    react without polling.

    Signals:
        proxy_added(Proxy): emitted with the new proxy.
        proxy_removed(Proxy): emitted with the removed proxy.
        proxy_rotated(Proxy, Proxy): emitted with (old, new) on rotation.
        proxy_failed(Proxy, str): emitted with (proxy, reason).
    """

    proxy_added = Signal(object)  # type: ignore
    proxy_removed = Signal(object)  # type: ignore
    proxy_rotated = Signal(object, object)  # type: ignore
    proxy_failed = Signal(object, str)  # type: ignore

    #: Coalescing window (seconds) before debounced persistence batches
    #: are flushed to SQLite / the ORM table.  Keeps per-request feedback
    #: (``mark_success`` / ``mark_failure``) off the DB hot path (audit A17).
    _FLUSH_DELAY: float = 0.5

    def __init__(self, persist: bool = True) -> None:
        """Initialise the manager.

        Args:
            persist: If True (default), mirror state to SQLite.  Set to
                False for ephemeral / test runs.
        """
        super().__init__()
        self._lock = threading.RLock()
        self._proxies: List[Proxy] = []
        self._index: Dict[str, Proxy] = {}  # key -> Proxy
        self._rr_cursor = 0
        self._last_pick: Optional[Proxy] = None
        self._persist = persist
        # Ban list (audit A14): ``host:port`` -> ban-until epoch.  Bans are
        # protocol-agnostic so ``ban("1.2.3.4:8080")`` from the UI / pool
        # facade matches regardless of how the entry was registered.
        self._banned: Dict[str, float] = {}
        # Debounced write-behind queue (audit A17): ``key -> Proxy`` holding
        # the latest state that still needs persisting.
        self._pending: Dict[str, Proxy] = {}
        self._pending_lock = threading.Lock()
        self._flush_event = threading.Event()
        self._flush_thread: Optional[threading.Thread] = None
        if persist:
            self._load_from_db()

    # -- ban list (A14) ------------------------------------------------------
    @staticmethod
    def _ban_key(addr: Any) -> str:
        """Normalise a ``host:port`` / ``proto://host:port`` / Proxy to
        the protocol-agnostic ban key ``host:port``."""
        if isinstance(addr, Proxy):
            return f"{addr.host}:{addr.port}"
        s = str(addr).strip()
        if "://" in s:  # strip an optional scheme
            s = s.split("://", 1)[1]
        # Strip any credentials component.
        if "@" in s:
            s = s.rsplit("@", 1)[1]
        return s

    def ban(self, addr: Any, minutes: float = 30.0) -> bool:
        """Banlist ``addr`` (``host:port`` / ``proto://host:port`` / Proxy)
        for ``minutes``.  Banned proxies are skipped by :meth:`get_proxy`.

        Returns ``True`` if a ban was (re)applied.
        """
        key = self._ban_key(addr)
        if not key:
            return False
        until = time.time() + max(0.0, float(minutes)) * 60.0
        with self._lock:
            self._banned[key] = until
        logger.info("Banned proxy %s for %ss", key, float(minutes) * 60.0)
        return True

    def unban(self, addr: Any) -> bool:
        """Lift any ban on ``addr``.  Returns ``True`` if a ban existed."""
        key = self._ban_key(addr)
        with self._lock:
            return self._banned.pop(key, None) is not None

    def _prune_banned(self) -> None:
        """Drop expired bans (``until <= now``).  Caller holds the lock."""
        now = time.time()
        expired = [k for k, until in self._banned.items() if until <= now]
        for k in expired:
            self._banned.pop(k, None)

    def is_banned(self, addr: Any) -> bool:
        """Return ``True`` while ``addr``'s cooldown ban is still active."""
        key = self._ban_key(addr)
        with self._lock:
            self._prune_banned()
            until = self._banned.get(key)
        return until is not None and until > time.time()

    def ban_list(self) -> Dict[str, float]:
        """Return a snapshot of active (non-expired) bans."""
        with self._lock:
            self._prune_banned()
            return dict(self._banned)

    # -- key helpers ---------------------------------------------------------
    @staticmethod
    def _key(p: Proxy) -> str:
        return f"{p.protocol}://{p.host}:{p.port}"

    # -- public API ----------------------------------------------------------
    def add_proxy(self, p: Proxy) -> bool:
        """Add ``p`` to the registry. Returns ``True`` if newly inserted."""
        if not isinstance(p, Proxy):
            raise TypeError("add_proxy expects a Proxy instance")
        key = self._key(p)
        with self._lock:
            if key in self._index:
                # merge stats if a record already existed
                existing = self._index[key]
                existing.success_count += p.success_count
                existing.fail_count += p.fail_count
                if p.latency_ms is not None:
                    existing.latency_ms = p.latency_ms
                if p.country:
                    existing.country = p.country
                if p.last_check:
                    existing.last_check = p.last_check
                self._recompute_score(existing)
                self._persist_proxy(existing)
                return False
            self._proxies.append(p)
            self._index[key] = p
            self._persist_proxy(p)
        try:
            self.proxy_added.emit(p)
        except Exception:  # pragma: no cover
            logger.exception("proxy_added slot raised")
        logger.info("Added proxy %s (%s)", p.address, p.protocol)
        return True

    def remove_proxy(self, p: Proxy) -> bool:
        """Remove ``p`` from the registry. Returns ``True`` if removed."""
        key = self._key(p)
        with self._pending_lock:
            self._pending.pop(key, None)
        with self._lock:
            if key not in self._index:
                return False
            self._proxies.remove(self._index[key])
            del self._index[key]
            self._delete_proxy(p)
        try:
            self.proxy_removed.emit(p)
        except Exception:  # pragma: no cover
            logger.exception("proxy_removed slot raised")
        logger.info("Removed proxy %s", p.address)
        return True

    def get_proxy(
        self, strategy: str = "round_robin"
    ) -> Optional[Proxy]:
        """Return a proxy using ``strategy`` or ``None`` if none eligible.

        Only proxies that are healthy (:attr:`Proxy.is_healthy`) and not on
        the cooldown ban list are considered (audit A14); when every entry
        is unhealthy / banned the method returns ``None`` instead of handing
        out a known-bad proxy.

        Args:
            strategy: One of ``round_robin|random|best|weighted``.
        """
        if strategy not in VALID_STRATEGIES:
            raise ValueError(f"strategy must be one of {VALID_STRATEGIES}")
        with self._lock:
            self._prune_banned()
            eligible = [
                p for p in self._proxies
                if p.is_healthy
                and f"{p.host}:{p.port}" not in self._banned
            ]
            if not eligible:
                if self._proxies:
                    logger.debug(
                        "get_proxy: %d proxies registered but none eligible "
                        "(" "unhealthy or banlisted)",
                        len(self._proxies),
                    )
                return None
            old = self._last_pick
            if strategy == "round_robin":
                p = eligible[self._rr_cursor % len(eligible)]
                self._rr_cursor += 1
            elif strategy == "random":
                import random

                p = random.choice(eligible)
            elif strategy == "best":
                p = max(eligible, key=lambda x: x.score)
            else:  # weighted
                p = self._weighted_pick(eligible)
            self._last_pick = p
        if strategy == "round_robin" and old is not None and old is not p:
            try:
                self.proxy_rotated.emit(old, p)
            except Exception:  # pragma: no cover
                logger.exception("proxy_rotated slot raised")
        return p

    def mark_success(self, p: Proxy, latency_ms: float) -> None:
        """Record a successful request through ``p``.

        In-memory state is updated under the lock; the SQLite/ORM write is
        debounced onto a background flusher so per-request bookkeeping never
        blocks on DB I/O inside the manager lock (audit A17).
        """
        with self._lock:
            p.success_count += 1
            p.latency_ms = float(latency_ms)
            p.last_check = time.time()
            self._recompute_score(p)
        self._persist_proxy(p)

    def mark_failure(self, p: Proxy, reason: str = "") -> None:
        """Record a failed request through ``p``.

        Persistence is debounced exactly as in :meth:`mark_success`.
        """
        with self._lock:
            p.fail_count += 1
            p.last_check = time.time()
            self._recompute_score(p)
        self._persist_proxy(p)
        try:
            self.proxy_failed.emit(p, reason or "unknown")
        except Exception:  # pragma: no cover
            logger.exception("proxy_failed slot raised")
        logger.warning("Proxy %s failed: %s", p.address, reason)

    def stats(self) -> Dict[str, Any]:
        """Return aggregate statistics about the registry."""
        with self._lock:
            total = len(self._proxies)
            healthy = sum(1 for p in self._proxies if p.is_healthy)
            succ = sum(p.success_count for p in self._proxies)
            fail = sum(p.fail_count for p in self._proxies)
            by_proto: Dict[str, int] = {}
            for p in self._proxies:
                by_proto[p.protocol] = by_proto.get(p.protocol, 0) + 1
            avg_lat: Optional[float] = None
            lats = [p.latency_ms for p in self._proxies if p.latency_ms]
            if lats:
                avg_lat = sum(lats) / len(lats)
        return {
            "total": total,
            "healthy": healthy,
            "unhealthy": total - healthy,
            "total_success": succ,
            "total_fail": fail,
            "avg_latency_ms": avg_lat,
            "by_protocol": by_proto,
        }

    def to_request_dict(self, p: Proxy) -> Dict[str, str]:
        """Return the ``proxies=`` dict that ``requests`` expects.

        For SOCKS proxies a ``socks5://`` URL is emitted so ``requests`` (with
        ``PySocks`` installed) routes correctly.
        """
        auth = ""
        if p.username:
            auth = f"{p.username}:{p.password or ''}@"
        url = f"{p.protocol}://{auth}{p.host}:{p.port}"
        return {"http": url, "https": url}

    def all_proxies(self) -> List[Proxy]:
        """Return a shallow copy of the registry."""
        with self._lock:
            return list(self._proxies)

    def clear(self) -> None:
        """Remove every proxy (also clears the DB cache)."""
        with self._pending_lock:
            self._pending.clear()
        with self._lock:
            removed = list(self._proxies)
            self._proxies.clear()
            self._index.clear()
            if self._persist:
                conn = _get_db_connection()
                if conn is not None:
                    try:
                        conn.execute(f"DELETE FROM {_DB_TABLE}")
                        conn.commit()
                        conn.close()
                    except Exception:  # pragma: no cover
                        logger.exception("failed to clear proxy DB")
        for p in removed:
            try:
                self.proxy_removed.emit(p)
            except Exception:  # pragma: no cover
                logger.exception("proxy_removed slot raised")

    # -- internals -----------------------------------------------------------
    def _weighted_pick(self, eligible: Optional[List[Proxy]] = None) -> Proxy:
        """Pick a proxy weighted by ``max(1, score)`` from ``eligible``."""
        import random

        pool = eligible if eligible is not None else self._proxies
        weights = [max(1e-6, p.score) for p in pool]
        return random.choices(pool, weights=weights, k=1)[0]

    def _recompute_score(self, p: Proxy) -> None:
        """Recompute ``p.score`` based on success rate + latency."""
        total = p.success_count + p.fail_count
        if total == 0:
            p.score = 0.0
            return
        success_rate = p.success_count / total
        latency = p.latency_ms if p.latency_ms and p.latency_ms > 0 else 1000.0
        # Higher is better. 100 * success_rate / latency scaled.
        p.score = round(success_rate * 1000.0 / latency, 4)

    # -- debounced persistence (A17) -----------------------------------------
    def _persist_proxy(self, p: Proxy) -> None:
        """Queue ``p`` for a coalesced SQLite/ORM write (no-op if disabled).

        Called on the request hot path (``mark_success`` / ``mark_failure`` /
        ``add_proxy``); the actual DB I/O happens in batch on a background
        flusher thread, so callers never block on a commit.
        """
        if not self._persist:
            return
        with self._pending_lock:
            self._pending[self._key(p)] = p
        self._ensure_flusher()

    def _ensure_flusher(self) -> None:
        """Start the daemon flusher thread on first use."""
        if self._flush_thread is not None and self._flush_thread.is_alive():
            self._flush_event.set()
            return
        self._flush_event.set()
        t = threading.Thread(
            target=self._flush_loop, name="ProxyPersistFlusher", daemon=True
        )
        t.start()
        self._flush_thread = t

    def _flush_loop(self) -> None:  # pragma: no cover - thread body
        """Background loop that writes pending proxies in batches."""
        while True:
            self._flush_event.wait()
            self._flush_event.clear()
            # Coalescing window: let bursts of mark_success/mark_failure
            # collapse into a single write (debounce).
            time.sleep(self._FLUSH_DELAY)
            batch = self._take_pending()
            if batch:
                self._persist_batch(batch)

    def _take_pending(self) -> List[Proxy]:
        """Atomically drain the pending queue (latest state per proxy)."""
        with self._pending_lock:
            batch = list(self._pending.values())
            self._pending.clear()
        return batch

    def flush(self) -> int:
        """Force-write all queued proxy state to SQLite/ORM immediately.

        Returns the number of rows written.  Useful in tests and at
        shutdown; the background flusher normally handles this.
        """
        if not self._persist:
            return 0
        batch = self._take_pending()
        if batch:
            self._persist_batch(batch)
        return len(batch)

    def _persist_batch(self, proxies: List[Proxy]) -> None:
        """Upsert a batch of proxies using ONE connection + ONE commit."""
        conn = _get_db_connection()
        if conn is not None:
            try:
                conn.executemany(
                    f"INSERT OR REPLACE INTO {_DB_TABLE} "
                    "(host, port, protocol, username, password, country, anonymity, "
                    " source, latency_ms, last_check, success_count, fail_count, score) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (
                            p.host, int(p.port), p.protocol, p.username,
                            p.password, p.country, p.anonymity, p.source,
                            p.latency_ms, p.last_check, int(p.success_count),
                            int(p.fail_count), float(p.score),
                        )
                        for p in proxies
                    ],
                )
                conn.commit()
            except Exception:  # pragma: no cover
                logger.exception("failed to persist %d proxies", len(proxies))
            finally:
                try:
                    conn.close()
                except Exception:  # pragma: no cover
                    pass
        # A18: also mirror into the canonical ORM ``ProxyModel`` table so
        # both persistence schemas stay in sync.  Best-effort + never
        # raised into the caller (persistence is a cache).
        self._persist_batch_orm(proxies)

    def _persist_batch_orm(self, proxies: List[Proxy]) -> None:
        """Mirror proxies into the ORM ``ProxyModel`` table (best-effort).

        TODO(A18): the proxy subsystem still persists to *two* schemas —
        the raw ``proxy_pool_cache`` table above and the ORM ``proxies``
        table here.  Migrating the reader (``_load_from_db``) onto the ORM
        schema and dropping ``proxy_pool_cache`` is the follow-up;
        until then both are kept in sync from this single flusher.
        """
        try:
            from database.connection import DatabaseConnection  # noqa: WPS433
            from database.models import ProxyModel  # noqa: WPS433
        except Exception:  # pragma: no cover - SQLAlchemy-less environments
            logger.debug("ORM mirror skipped: database models unavailable")
            return
        db = DatabaseConnection.get_existing()
        if db is None:  # never create a DB just to mirror a cache
            return
        try:
            with db.get_db() as session:
                for p in proxies:
                    row = (
                        session.query(ProxyModel)
                        .filter_by(host=p.host, port=int(p.port),
                                   protocol=p.protocol)
                        .one_or_none()
                    )
                    if row is None:
                        row = ProxyModel(host=p.host, port=int(p.port),
                                         protocol=p.protocol)
                        session.add(row)
                    row.country = p.country
                    row.anonymity = p.anonymity
                    row.score = int(round(float(p.score)))
                    row.success_count = int(p.success_count)
                    row.fail_count = int(p.fail_count)
                    if p.last_check:
                        row.last_check = datetime.fromtimestamp(
                            float(p.last_check), tz=timezone.utc
                        ).replace(tzinfo=None)
                # single commit for the whole batch (get_db commits on exit)
        except Exception:  # pragma: no cover
            logger.debug("ORM proxy mirror failed", exc_info=True)

    def _delete_proxy(self, p: Proxy) -> None:
        if not self._persist:
            return
        conn = _get_db_connection()
        if conn is None:
            return
        try:
            conn.execute(
                f"DELETE FROM {_DB_TABLE} WHERE host=? AND port=? AND protocol=?",
                (p.host, int(p.port), p.protocol),
            )
            conn.commit()
        except Exception:  # pragma: no cover
            logger.exception("failed to delete proxy %s", p.address)
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass

    def _load_from_db(self) -> None:
        """Load cached proxies from SQLite at startup."""
        conn = _get_db_connection()
        if conn is None:
            return
        try:
            cur = conn.execute(
                f"SELECT host, port, protocol, username, password, country, anonymity, "
                f"source, latency_ms, last_check, success_count, fail_count, score "
                f"FROM {_DB_TABLE}"
            )
            rows = cur.fetchall()
        except Exception:
            logger.exception("failed to load proxies from DB")
            return
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass
        for row in rows:
            try:
                p = Proxy(
                    host=row[0], port=int(row[1]), protocol=row[2],
                    username=row[3], password=row[4], country=row[5],
                    anonymity=row[6] or "anonymous", source=row[7],
                    latency_ms=row[8], last_check=row[9],
                    success_count=int(row[10] or 0), fail_count=int(row[11] or 0),
                    score=float(row[12] or 0.0),
                )
            except Exception:  # pragma: no cover - bad row
                logger.warning("skipping bad proxy row: %s", row)
                continue
            self._proxies.append(p)
            self._index[self._key(p)] = p
        if rows:
            logger.info("Loaded %d proxies from DB", len(rows))
