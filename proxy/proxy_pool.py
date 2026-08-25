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
import threading
import time
from typing import Any, Dict, List, Optional

from .proxy_health_check import ProxyCheckResult, ProxyHealthChecker
from .proxy_manager import Proxy, ProxyManager
from .proxy_rotation import ProxyRotator, RotationStrategy
from .proxy_scraper import ProxyScraper

logger = logging.getLogger(__name__)


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
        logger.info("refresh_pool: kept %d healthy proxies", healthy)
        return healthy

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
        """Return a single proxy via the manager's ``get_proxy``."""
        if strategy is None:
            # Use the rotator's strategy if available, else round_robin.
            p = self.rotator.next_proxy()
            return p
        return self.manager.get_proxy(strategy=strategy)

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
                    writer.writerow([
                        p.host, p.port, p.protocol, p.username or "",
                        p.password or "", p.country or "", p.anonymity,
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
