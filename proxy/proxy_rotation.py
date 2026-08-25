"""Per-request proxy rotation with banlisting + cooldown.

The :class:`ProxyRotator` keeps a registry of proxies and selects one for
each outbound request using a configurable strategy.  Proxies that fail
repeatedly are temporarily banlisted (removed from rotation) for a
configurable cooldown period.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import enum
import logging
import random
import threading
import time
from typing import Callable, Dict, List, Optional

from .proxy_manager import Proxy

logger = logging.getLogger(__name__)


class RotationStrategy(enum.Enum):
    """Supported rotation strategies."""

    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    LEAST_USED = "least_used"
    BEST_LATENCY = "best_latency"
    WEIGHTED_BY_SUCCESS = "weighted_by_success"


class ProxyRotator:
    """Automatically pick a proxy per-request, banlisting bad ones.

    Usage::

        rotator = ProxyRotator(proxies, strategy=RotationStrategy.ROUND_ROBIN)
        p = rotator.next_proxy()
        try:
            resp = requests.get(url, proxies=manager.to_request_dict(p))
            rotator.report_success(p, resp.elapsed.total_seconds() * 1000)
        except Exception as exc:
            rotator.report_failure(p, exc)
    """

    def __init__(
        self,
        proxies: Optional[List[Proxy]] = None,
        strategy: RotationStrategy = RotationStrategy.ROUND_ROBIN,
        ban_threshold: float = 0.5,
        cooldown_sec: float = 300.0,
        min_samples_before_ban: int = 3,
        on_rotate: Optional[Callable[[Optional[Proxy], Optional[Proxy]], None]] = None,
    ) -> None:
        """Initialise the rotator.

        Args:
            proxies: Initial proxy list.
            strategy: Selection strategy.
            ban_threshold: Fail-rate above which a proxy is banlisted.
            cooldown_sec: How long a banlisted proxy stays out of rotation.
            min_samples_before_ban: Minimum (success+fail) before banlisting.
            on_rotate: Optional ``callable(old, new)`` invoked on each
                rotation (called from the calling thread).
        """
        self._lock = threading.RLock()
        self._proxies: List[Proxy] = list(proxies or [])
        self._strategy = strategy if isinstance(strategy, RotationStrategy) else RotationStrategy(strategy)
        self._ban_threshold = float(ban_threshold)
        self._cooldown_sec = float(cooldown_sec)
        self._min_samples = max(1, int(min_samples_before_ban))
        self._on_rotate = on_rotate

        self._rr_cursor = 0
        self._last: Optional[Proxy] = None
        self._usage_count: Dict[str, int] = {}
        self._banlist: Dict[str, float] = {}  # key -> ban_until epoch

    # -- proxy management ----------------------------------------------------
    def add_proxy(self, p: Proxy) -> None:
        """Add ``p`` to the rotation pool."""
        with self._lock:
            if p not in self._proxies:
                self._proxies.append(p)

    def remove_proxy(self, p: Proxy) -> None:
        """Remove ``p`` from the rotation pool."""
        with self._lock:
            if p in self._proxies:
                self._proxies.remove(p)
            self._banlist.pop(self._key(p), None)
            self._usage_count.pop(self._key(p), None)

    def set_strategy(self, strategy: RotationStrategy) -> None:
        """Change the rotation strategy at runtime."""
        with self._lock:
            self._strategy = (
                strategy if isinstance(strategy, RotationStrategy)
                else RotationStrategy(strategy)
            )

    @property
    def on_rotate(self) -> Optional[Callable[[Optional[Proxy], Optional[Proxy]], None]]:
        """Return the current ``on_rotate`` callback."""
        return self._on_rotate

    @on_rotate.setter
    def on_rotate(
        self, cb: Optional[Callable[[Optional[Proxy], Optional[Proxy]], None]]
    ) -> None:
        self._on_rotate = cb

    @property
    def strategy(self) -> RotationStrategy:
        """Return the active strategy."""
        return self._strategy

    @property
    def pool_size(self) -> int:
        """Return the total number of proxies in the pool (incl. banlisted)."""
        with self._lock:
            return len(self._proxies)

    # -- selection -----------------------------------------------------------
    def next_proxy(self) -> Optional[Proxy]:
        """Return the next proxy according to the active strategy.

        Returns ``None`` if no proxy is available (empty pool or all
        banlisted).
        """
        with self._lock:
            available = self._available_proxies()
            if not available:
                logger.warning(
                    "no proxies available (pool=%d, banlisted=%d)",
                    len(self._proxies), len(self._banlist),
                )
                return None
            picked = self._pick(available)
            if picked is not None:
                key = self._key(picked)
                self._usage_count[key] = self._usage_count.get(key, 0) + 1
        old = self._last
        self._last = picked
        if self._on_rotate is not None:
            try:
                self._on_rotate(old, picked)
            except Exception:  # pragma: no cover
                logger.exception("on_rotate callback raised")
        return picked

    # -- feedback ------------------------------------------------------------
    def report_success(self, p: Proxy, latency: float) -> None:
        """Record a successful request through ``p``.

        Clears any ban if the proxy is currently banlisted.
        """
        with self._lock:
            p.success_count += 1
            p.latency_ms = float(latency)
            p.last_check = time.time()
            # Successful request -> clear ban.
            self._banlist.pop(self._key(p), None)

    def report_failure(self, p: Proxy, exc: Optional[BaseException] = None) -> None:
        """Record a failed request through ``p``.

        May ban the proxy if its fail-rate exceeds the threshold.
        """
        with self._lock:
            p.fail_count += 1
            p.last_check = time.time()
            samples = p.success_count + p.fail_count
            if (
                samples >= self._min_samples
                and p.fail_rate > self._ban_threshold
            ):
                self._banlist[self._key(p)] = time.time() + self._cooldown_sec
                logger.warning(
                    "banlisted %s (fail_rate=%.2f, samples=%d) for %ss",
                    p.address, p.fail_rate, samples, self._cooldown_sec,
                )

    def is_banned(self, p: Proxy) -> bool:
        """Return ``True`` if ``p`` is currently banlisted."""
        with self._lock:
            return self._key(p) in self._banlist

    def clear_banlist(self) -> None:
        """Force-clear all bans."""
        with self._lock:
            self._banlist.clear()

    def stats(self) -> Dict[str, object]:
        """Return a small stats dict (pool_size, banlisted, per-strategy usage)."""
        with self._lock:
            return {
                "pool_size": len(self._proxies),
                "available": len(self._available_proxies()),
                "banlisted": len(self._banlist),
                "strategy": self._strategy.value,
                "total_uses": sum(self._usage_count.values()),
            }

    # -- internals -----------------------------------------------------------
    @staticmethod
    def _key(p: Proxy) -> str:
        return f"{p.protocol}://{p.host}:{p.port}"

    def _available_proxies(self) -> List[Proxy]:
        """Return non-banlisted proxies (also prunes expired bans)."""
        now = time.time()
        expired = [k for k, until in self._banlist.items() if until <= now]
        for k in expired:
            self._banlist.pop(k, None)
        return [p for p in self._proxies if self._key(p) not in self._banlist]

    def _pick(self, available: List[Proxy]) -> Optional[Proxy]:
        """Apply the active strategy to ``available`` and return one proxy."""
        if not available:
            return None
        s = self._strategy
        if s is RotationStrategy.RANDOM:
            return random.choice(available)
        if s is RotationStrategy.LEAST_USED:
            return min(
                available,
                key=lambda p: self._usage_count.get(self._key(p), 0),
            )
        if s is RotationStrategy.BEST_LATENCY:
            return min(
                available,
                key=lambda p: (p.latency_ms if p.latency_ms else 1e9),
            )
        if s is RotationStrategy.WEIGHTED_BY_SUCCESS:
            weights = [max(1e-6, p.score) for p in available]
            return random.choices(available, weights=weights, k=1)[0]
        # ROUND_ROBIN (default)
        picked = available[self._rr_cursor % len(available)]
        self._rr_cursor += 1
        return picked
