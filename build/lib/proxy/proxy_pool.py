"""High-level proxy pool facade.

:class:`ProxyPool` ties together the scraper, health-checker, manager and
rotator into one easy-to-use object.  It is the only class most callers need
to import::

    from proxy.proxy_pool import ProxyPool

    pool = ProxyPool()
    pool.refresh_pool(target_count=200)
    workable = pool.get_workable()
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from .proxy_health_check import ProxyCheckResult, ProxyHealthChecker
from .proxy_manager import Proxy, ProxyManager
from .proxy_rotation import ProxyRotator, RotationStrategy
from .proxy_scraper import ProxyScraper

logger = logging.getLogger(__name__)

# UI strategy labels → rotator strategies (proxy_panel chain builder).
_STRATEGY_ALIASES: Dict[str, RotationStrategy] = {
    "round-robin": RotationStrategy.ROUND_ROBIN,
    "round_robin": RotationStrategy.ROUND_ROBIN,
    "roundrobin": RotationStrategy.ROUND_ROBIN,
    "sticky-session": RotationStrategy.ROUND_ROBIN,
    "sticky": RotationStrategy.ROUND_ROBIN,
    "random": RotationStrategy.RANDOM,
    "least-latency": RotationStrategy.BEST_LATENCY,
    "least_latency": RotationStrategy.BEST_LATENCY,
    "best-latency": RotationStrategy.BEST_LATENCY,
    "best_latency": RotationStrategy.BEST_LATENCY,
    "least-used": RotationStrategy.LEAST_USED,
    "least_used": RotationStrategy.LEAST_USED,
    "weighted": RotationStrategy.WEIGHTED_BY_SUCCESS,
    "weighted_by_success": RotationStrategy.WEIGHTED_BY_SUCCESS,
}


class ProxyPool:
    """High-level facade combining scraper + health-check + manager + rotator.

    The pool is fully thread-safe.  Constructing it is cheap; the heavy
    network operations only happen on explicit calls (e.g.
    :meth:`refresh_pool`).
    """

    def __init__(
        self,
        manager: Optional[ProxyManager] = None,
        scraper: Optional[ProxyScraper] = None,
        checker: Optional[ProxyHealthChecker] = None,
        rotator: Optional[ProxyRotator] = None,
        strategy: RotationStrategy = RotationStrategy.ROUND_ROBIN,
    ) -> None:
        """Initialise the pool (creates sensible defaults if missing)."""
        self._lock = threading.RLock()
        self.manager = manager if manager is not None else ProxyManager()
        self.scraper = scraper if scraper is not None else ProxyScraper()
        self.checker = checker if checker is not None else ProxyHealthChecker()
        self.rotator = (
            rotator if rotator is not None else ProxyRotator(strategy=strategy)
        )
        self._refresh_thread: Optional[threading.Thread] = None
        self._refresh_stop = threading.Event()
        self._last_refresh: Optional[float] = None
        self._chain: Optional[Any] = None  # ProxyChain, built lazily
        # A9: seed the rotator from the manager so get_proxy() actually
        # rotates over the loaded registry (previously the rotator stayed
        # empty forever unless refresh_pool() ran).
        self._sync_rotator()

    # -- rotator / manager sync (A9) -----------------------------------------
    def _sync_rotator(self) -> int:
        """Mirror every manager proxy into the rotator pool.

        Called at construction and after every refresh / import / health
        sweep so :meth:`get_proxy` (default strategy path) rotates over the
        full registry instead of an empty pool.
        """
        try:
            return self.rotator.add_proxies(self.manager.all_proxies())
        except Exception:  # pragma: no cover - defensive
            logger.exception("rotator sync failed")
            return 0

    # -- pool refresh --------------------------------------------------------
    def refresh_pool(
        self,
        target_count: int = 200,
        max_workers: Optional[int] = None,
        progress_cb: Optional[Any] = None,
    ) -> int:
        """Scrape fresh proxies, health-check them, keep the healthy ones.

        Args:
            target_count: Stop once this many healthy proxies are found.
            max_workers: Override the health-checker's thread-pool size.
            progress_cb: Optional ``callable(done, total, result)`` for
                health-check progress (forwarded to ``check_batch``).

        Returns:
            Number of healthy proxies now in the pool.
        """
        target_count = max(1, int(target_count))
        logger.info("refresh_pool: scraping sources...")
        scraped = self.scraper.scrape_all_sources()
        if not scraped:
            logger.warning("refresh_pool: scraper returned 0 proxies")
            return len(self.get_workable())

        # Cap the batch we test so we don't spend forever when sources
        # are unusually generous.
        candidates = scraped[: max(target_count * 4, 200)]
        logger.info("refresh_pool: testing %d candidates", len(candidates))

        results = self.checker.check_batch(
            candidates, max_workers=max_workers, progress_cb=progress_cb
        )

        healthy = 0
        with self._lock:
            for res in results:
                if not res.alive:
                    continue
                p = res.proxy
                p.latency_ms = res.latency_ms
                p.last_check = time.time()
                if res.country:
                    p.country = res.country
                if res.anonymity:
                    p.anonymity = res.anonymity
                self.manager.add_proxy(p)
                self.rotator.add_proxy(p)
                healthy += 1
                if healthy >= target_count:
                    break
        self._last_refresh = time.time()
        self._sync_rotator()
        logger.info("refresh_pool: kept %d healthy proxies", healthy)
        return healthy

    # -- facade (PATCH CONTRACT #4) ------------------------------------------
    @staticmethod
    def _proxy_record(p: Proxy) -> Dict[str, Any]:
        """Serialise a proxy for the facade's ``list_proxies()``.

        Adds convenience keys the web/UI layers filter on (``address``,
        ``is_healthy``/``healthy``, ``success_rate``, human-readable
        ``last_check``) and MASKS credentials — the facade output is
        displayed in the UI and returned verbatim by ``/api/proxy``, so
        ``user:pass`` never travels to clients (audit: plaintext creds).
        """
        d = p.to_dict()
        d["address"] = p.address
        d["is_healthy"] = bool(p.is_healthy)
        d["healthy"] = d["is_healthy"]
        total = p.success_count + p.fail_count
        d["success_rate"] = (
            round(100.0 * p.success_count / total, 1) if total else 0.0
        )
        d["last_check_epoch"] = p.last_check
        if isinstance(p.last_check, (int, float)) and p.last_check:
            d["last_check"] = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(p.last_check)
            )
        if p.username:
            d["username"] = "***"
        if p.password:
            d["password"] = "***"
        return d

    def list_proxies(self) -> List[Dict[str, Any]]:
        """Return every registered proxy as a serialisable dict list.

        Contract #4 — consumed by ``web/routes/proxy.py`` and
        ``ui/widgets/proxy_panel.py`` (which expects plain dicts).
        """
        return [self._proxy_record(p) for p in self.manager.all_proxies()]

    def refresh(
        self,
        sources: Optional[List[str]] = None,
        target_count: Optional[int] = None,
        progress_cb: Optional[Any] = None,
        max_workers: Optional[int] = None,
    ) -> int:
        """Contract #4 facade over :meth:`refresh_pool`.

        Args:
            sources: Optional list of source URLs to scrape (defaults to
                the scraper's full catalog; unknown URLs get the raw
                ``ip:port`` parser).
            target_count: Stop once this many healthy proxies were kept.
            progress_cb: ``callable(done, total, result)`` forwarded to the
                health checker.
            max_workers: Optional health-check thread-pool override.

        Returns:
            Number of healthy proxies kept by this sweep.
        """
        kwargs: Dict[str, Any] = {}
        if target_count is not None:
            kwargs["target_count"] = max(1, int(target_count))
        if progress_cb is not None:
            kwargs["progress_cb"] = progress_cb
        if max_workers is not None:
            kwargs["max_workers"] = max(1, int(max_workers))

        old_sources: Optional[Dict[str, Any]] = None
        if sources:
            wanted = [str(s) for s in sources if str(s).strip()]
            current = dict(self.scraper.sources)
            filtered = {u: v for u, v in current.items() if u in set(wanted)}
            for u in wanted:
                if u not in filtered:
                    # Unknown feed: assume a raw ``ip:port`` list over http.
                    filtered[u] = ("http", "raw_iport")
            old_sources = current
            self.scraper.sources = filtered
        try:
            kept = self.refresh_pool(**kwargs)
        finally:
            if old_sources is not None:
                self.scraper.sources = old_sources
        self._sync_rotator()
        return kept

    # -- address helpers -----------------------------------------------------
    @staticmethod
    def _split_address(addr: str) -> tuple[str, str, Optional[str]]:
        """Split ``[proto://]host[:port]`` into ``(host, port, proto)``.

        ``proto`` is ``None`` when the address carried no scheme; ``port``
        is ``""`` when absent.
        """
        s = str(addr).strip()
        proto: Optional[str] = None
        if "://" in s:
            proto, s = s.split("://", 1)
        if "@" in s:  # strip credentials component
            s = s.rsplit("@", 1)[1]
        host, _, port = s.partition(":")
        return host.strip(), port.strip(), proto

    def _find_proxy(self, addr: str) -> Optional[Proxy]:
        """Locate ``addr`` in the manager registry (scheme/port tolerant)."""
        host, port, proto = self._split_address(addr)
        if not host:
            return None
        for p in self.manager.all_proxies():
            if p.host != host:
                continue
            if port and str(p.port) != port:
                continue
            if proto and p.protocol != proto.lower():
                continue
            return p
        return None

    def _proxy_from_address(
        self, addr: str, default_protocol: str = "http"
    ) -> Proxy:
        """Resolve ``addr`` to a registry entry or construct a fresh Proxy.

        Raises:
            ValueError: If the address cannot be parsed (host missing or a
                non-numeric port) — surfaced by the web layer as a 400.
        """
        found = self._find_proxy(addr)
        if found is not None:
            return found
        host, port, proto = self._split_address(addr)
        if not host:
            raise ValueError(f"invalid proxy address: {addr!r}")
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            raise ValueError(f"invalid port in proxy address: {addr!r}")
        return Proxy(
            host=host,
            port=int(port),
            protocol=(proto or default_protocol).lower(),
        )

    # -- testing -------------------------------------------------------------
    def test_proxy(
        self,
        addr: str,
        test_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Contract #4: run a single health check against ``addr``.

        Args:
            addr: ``host:port`` or ``proto://host:port`` (registry entries
                are preferred; unknown addresses are checked as-is).
            test_url: Optional URL the proxy should fetch (SSRF-validated
                upstream by the web layer).
            timeout: Optional per-request timeout override.

        Returns:
            A serialisable dict with ``alive``, ``latency_ms``,
            ``anonymity``, geo info and the proxy's updated success rate.
        """
        proxy = self._proxy_from_address(addr)
        result = self.checker.check_proxy(
            proxy, test_url=test_url, timeout=timeout
        )
        self._apply_check_result(result)
        p = result.proxy
        total = p.success_count + p.fail_count
        return {
            "address": p.address,
            "host": p.host,
            "port": p.port,
            "protocol": p.protocol,
            "alive": bool(result.alive),
            "latency_ms": result.latency_ms,
            "anonymity": result.anonymity,
            "country": result.country,
            "country_code": result.country_code,
            "isp": result.isp,
            "exit_ip": result.exit_ip,
            "error": result.error,
            "success_rate": (
                round(100.0 * p.success_count / total, 1) if total else 0.0
            ),
            "last_check": time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(p.last_check)
            ) if p.last_check else None,
            "checked_at": result.checked_at,
        }

    def _apply_check_result(self, res: ProxyCheckResult) -> None:
        """Fold a health-check outcome back into the manager/rotator.

        The manager owns the counters/score (the rotator shares the same
        ``Proxy`` objects, so mutating in both places would double-count —
        the rotator only gets ban bookkeeping via ``note_success`` /
        ``note_failure``).
        """
        p = res.proxy
        if res.anonymity:
            try:
                p.anonymity = res.anonymity
            except Exception:  # pragma: no cover - invalid value
                pass
        if res.country:
            p.country = res.country
        if res.alive:
            self.manager.mark_success(p, res.latency_ms or 0.0)
            self.rotator.note_success(p)
        else:
            self.manager.mark_failure(p, res.error or "health check failed")
            self.rotator.note_failure(p)

    def health_check_all(
        self,
        max_workers: Optional[int] = None,
        progress_cb: Optional[Any] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Re-test every registered proxy.

        Returns a mapping ``"host:port" -> {latency_ms, alive,
        success_rate, last_check}`` — the shape
        ``ui/widgets/proxy_panel.py`` applies to its table.
        """
        proxies = self.manager.all_proxies()
        if not proxies:
            return {}
        results = self.checker.check_batch(
            proxies, max_workers=max_workers, progress_cb=progress_cb
        )
        out: Dict[str, Dict[str, Any]] = {}
        for res in results:
            self._apply_check_result(res)
            p = res.proxy
            total = p.success_count + p.fail_count
            out[f"{p.host}:{p.port}"] = {
                "alive": bool(res.alive),
                "latency_ms": res.latency_ms,
                "success_rate": (
                    round(100.0 * p.success_count / total, 1) if total else 0.0
                ),
                "last_check": time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(p.last_check)
                ) if p.last_check else None,
            }
        self._sync_rotator()
        return out

    # -- query ---------------------------------------------------------------
    def get_workable(self) -> List[Proxy]:
        """Return proxies that look usable (non-banlisted, recent check)."""
        with self._lock:
            out: List[Proxy] = []
            for p in self.manager.all_proxies():
                if not p.is_healthy:
                    continue
                if self.rotator.is_banned(p):
                    continue
                out.append(p)
            return out

    def get_proxy(self, strategy: Optional[str] = None) -> Optional[Proxy]:
        """Return a single proxy via the rotator (default) or manager.

        The default path rotates through the synced rotator pool; an
        explicit ``strategy`` string delegates to the manager (which now
        honours health + ban filtering).  When the rotator is empty but the
        manager registry is not (proxies added directly, loaded from the
        DB at boot, imported through the manager, ...) the rotator is
        lazily re-synced first so rotation actually happens (audit A9).
        """
        if strategy is None:
            if self.rotator.pool_size == 0:
                self._sync_rotator()
            return self.rotator.next_proxy()
        return self.manager.get_proxy(strategy=strategy)

    def get_proxy_url(self) -> Optional[str]:
        """Contract #4: URL form (``proto://[user:pass@]host:port``) of
        :meth:`get_proxy`, or ``None`` when no proxy is available."""
        p = self.get_proxy()
        if p is None:
            return None
        try:
            return p.url
        except Exception:  # pragma: no cover - defensive
            return f"{p.protocol}://{p.host}:{p.port}"

    # -- chain management ----------------------------------------------------
    def build_chain(self, ids: List[Any]) -> Dict[str, Any]:
        """Contract #4: build a multi-hop chain from ids/addresses.

        Each id may be a registry address (``host:port`` /
        ``proto://host:port``) or a ``Proxy`` instance.  The constructed
        :class:`~proxy.proxy_chain.ProxyChain` is retained on the pool and
        a serialisable descriptor is returned (``web/routes/proxy.py``
        returns it verbatim).

        Raises:
            ValueError: If ``ids`` is empty or any entry is unparseable.
        """
        from .proxy_chain import ProxyChain  # lazy (PySocks optional)

        if not ids:
            raise ValueError("proxy_ids (non-empty list) is required")
        proxies: List[Proxy] = []
        for item in ids:
            if isinstance(item, Proxy):
                proxies.append(item)
                continue
            proxies.append(self._proxy_from_address(str(item)))
        if not proxies:
            raise ValueError("no valid proxies in proxy_ids")
        chain = ProxyChain(proxies)
        with self._lock:
            self._chain = chain
        return {
            "length": len(proxies),
            "chain": [p.address for p in proxies],
            "protocols": [p.protocol for p in proxies],
            "proxies": [self._proxy_record(p) for p in proxies],
        }

    def set_chain(
        self, items: Optional[List[str]] = None, strategy: Optional[str] = None
    ) -> Dict[str, Any]:
        """Contract #4: store the active chain + optional rotation strategy.

        ``items`` are ``host:port`` addresses (as collected by the UI's
        drag-and-drop chain builder); ``strategy`` accepts the panel's
        labels (``Round-robin``, ``Random``, ``Least-latency``,
        ``Weighted``, ``Sticky-session``) or raw strategy values.
        """
        result: Dict[str, Any] = {"length": 0, "addresses": [], "strategy": None}
        if items:
            proxies = [
                item if isinstance(item, Proxy)
                else self._proxy_from_address(str(item))
                for item in items
            ]
            from .proxy_chain import ProxyChain  # lazy (PySocks optional)

            with self._lock:
                self._chain = ProxyChain(proxies)
            result["length"] = len(proxies)
            result["addresses"] = [p.address for p in proxies]
        if strategy:
            key = str(strategy).strip().lower().replace(" ", "-")
            mapped = _STRATEGY_ALIASES.get(key)
            if mapped is not None:
                self.rotator.set_strategy(mapped)
                result["strategy"] = mapped.value
            else:
                result["strategy_warning"] = f"unknown strategy: {strategy!r}"
        return result

    def get_chain(self) -> Optional[List[str]]:
        """Return the addresses of the currently stored chain (or None)."""
        chain = self._chain
        if chain is None:
            return None
        try:
            return [p.address for p in chain.proxies]
        except Exception:  # pragma: no cover - defensive
            return None

    # -- banning -------------------------------------------------------------
    def ban(self, addr: str, minutes: float = 30.0) -> bool:
        """Contract #4: banlist ``addr`` for ``minutes``.

        Applied on both the manager (get_proxy filtering) and the rotator
        (next_proxy filtering); a registry hit also records a failure so
        the score reflects the operator action.
        """
        if not str(addr).strip():
            return False
        banned = self.manager.ban(addr, minutes=minutes)
        proxy = self._find_proxy(str(addr))
        if proxy is not None:
            self.rotator.ban(proxy, seconds=max(0.0, float(minutes)) * 60.0)
            banned = True
        return banned

    def unban(self, addr: str) -> bool:
        """Lift a ban on ``addr`` (manager + rotator)."""
        lifted = self.manager.unban(addr)
        proxy = self._find_proxy(str(addr))
        if proxy is not None:
            self.rotator.remove_ban(proxy)
            lifted = True
        return lifted

    # -- background refresh --------------------------------------------------
    def start_background_refresh(self, interval_min: float = 30.0) -> None:
        """Spawn a daemon thread that calls :meth:`refresh_pool` periodically.

        Args:
            interval_min: Minutes between refresh sweeps.
        """
        if self._refresh_thread and self._refresh_thread.is_alive():
            logger.warning("background refresh already running")
            return
        self._refresh_stop.clear()
        interval_sec = max(60.0, float(interval_min) * 60.0)

        def _loop() -> None:
            logger.info("background refresh started (every %ss)", interval_sec)
            while not self._refresh_stop.wait(timeout=interval_sec):
                try:
                    self.refresh_pool()
                except Exception:  # pragma: no cover
                    logger.exception("background refresh failed")
            logger.info("background refresh stopped")

        t = threading.Thread(target=_loop, name="ProxyPoolRefresh", daemon=True)
        t.start()
        self._refresh_thread = t

    def stop_background_refresh(self) -> None:
        """Signal the background refresh thread to stop."""
        self._refresh_stop.set()

    # -- export / import -----------------------------------------------------
    def export_to_file(
        self, path: str, fmt: str = "txt"
    ) -> int:
        """Export all proxies to ``path`` in ``txt|json|csv`` format.

        Returns the number of proxies written.
        """
        fmt = fmt.lower()
        if fmt not in {"txt", "json", "csv"}:
            raise ValueError(f"format must be txt|json|csv, got {fmt!r}")
        proxies = self.manager.all_proxies()
        if fmt == "txt":
            with open(path, "w", encoding="utf-8") as fh:
                for p in proxies:
                    fh.write(f"{p.protocol}://{p.host}:{p.port}\n")
        elif fmt == "csv":
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow([
                    "host", "port", "protocol", "username", "password",
                    "country", "anonymity", "source", "latency_ms",
                    "last_check", "success_count", "fail_count", "score",
                ])
                for p in proxies:
                    # Credentials are masked: the CSV is a shareable health
                    # snapshot, not a credentials store (audit: plaintext
                    # creds in CSV export).
                    writer.writerow([
                        p.host, p.port, p.protocol,
                        "***" if p.username else "",
                        "***" if p.password else "",
                        p.country or "", p.anonymity,
                        p.source or "", p.latency_ms if p.latency_ms is not None else "",
                        p.last_check if p.last_check is not None else "",
                        p.success_count, p.fail_count, p.score,
                    ])
        else:  # json
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([p.to_dict() for p in proxies], fh, indent=2)
        logger.info("exported %d proxies to %s (%s)", len(proxies), path, fmt)
        return len(proxies)

    def import_from_file(self, path: str) -> int:
        """Import proxies from ``txt|json|csv`` produced by :meth:`export_to_file`.

        Returns the number of proxies imported.
        """
        added = 0
        # Detect format by extension.
        lower = path.lower()
        if lower.endswith(".json"):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for item in data:
                try:
                    self.manager.add_proxy(Proxy.from_dict(item))
                    added += 1
                except Exception:  # pragma: no cover
                    logger.warning("skipping bad entry: %s", item)
        elif lower.endswith(".csv"):
            with open(path, "r", newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    try:
                        row["port"] = int(row["port"])
                        if row.get("latency_ms"):
                            row["latency_ms"] = float(row["latency_ms"])
                        if row.get("last_check"):
                            row["last_check"] = float(row["last_check"])
                        row["success_count"] = int(row.get("success_count") or 0)
                        row["fail_count"] = int(row.get("fail_count") or 0)
                        row["score"] = float(row.get("score") or 0.0)
                        self.manager.add_proxy(Proxy.from_dict(row))
                        added += 1
                    except Exception:  # pragma: no cover
                        logger.warning("skipping bad csv row: %s", row)
        else:  # txt
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    try:
                        if "://" in line:
                            proto, rest = line.split("://", 1)
                        else:
                            proto, rest = "http", line
                        host, _, port = rest.partition(":")
                        self.manager.add_proxy(
                            Proxy(host=host.strip(), port=int(port), protocol=proto)
                        )
                        added += 1
                    except Exception:  # pragma: no cover
                        logger.warning("skipping bad txt line: %s", line)
        logger.info("imported %d proxies from %s", added, path)
        return added

    def import_from(self, sources: Any) -> List[Dict[str, Any]]:
        """Contract #4: import proxies and return the facade snapshot.

        Accepted shapes:
          * ``str``/``os.PathLike`` file path (``.txt``/``.json``/``.csv``)
            — delegated to :meth:`import_from_file`;
          * ``str`` http(s) URL — treated as a scrape source, scraped and
            health-checked via :meth:`refresh`;
          * iterable of addresses (``host:port`` / ``proto://host:port``),
            ``Proxy`` instances or field dicts — added through the manager.

        Returns:
            ``list_proxies()`` (serialisable dicts, credentials masked) so
            ``ui/widgets/proxy_panel.py`` can feed the table directly.
        """
        if sources is None:
            pass
        elif isinstance(sources, os.PathLike):
            self.import_from_file(str(sources))
        elif isinstance(sources, str):
            lowered = sources.strip().lower()
            if lowered.startswith(("http://", "https://")):
                self.refresh(sources=[sources], target_count=50)
            else:
                self.import_from_file(sources)
        elif isinstance(sources, dict):
            try:
                self.manager.add_proxy(Proxy.from_dict(sources))
            except Exception:  # pragma: no cover - bad entry
                logger.warning("import_from: skipping bad dict entry: %s", sources)
        else:  # iterable of addresses / dicts / Proxies
            for item in sources:
                try:
                    if isinstance(item, Proxy):
                        self.manager.add_proxy(item)
                    elif isinstance(item, dict):
                        self.manager.add_proxy(Proxy.from_dict(item))
                    elif isinstance(item, str) and item.strip().lower().startswith(
                        ("http://", "https://")
                    ):
                        self.refresh(sources=[item], target_count=50)
                    else:
                        self.manager.add_proxy(self._proxy_from_address(item))
                except Exception:  # pragma: no cover - bad entry
                    logger.warning("import_from: skipping bad entry: %s", item)
        self._sync_rotator()
        return self.list_proxies()

    # -- diagnostics ---------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        """Return combined stats from manager + rotator."""
        m = self.manager.stats()
        r = self.rotator.stats()
        return {
            "manager": m,
            "rotator": r,
            "last_refresh": self._last_refresh,
        }
