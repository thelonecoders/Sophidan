"""Proxy health checking + geoip enrichment.

The :class:`ProxyHealthChecker` tests proxies against a target URL (default
``https://httpbin.org/ip``) to measure latency, detect anonymity level, and
look up the proxy's geographic location via ip-api.com.

Heavy deps (``requests``) are imported lazily so the module is import-safe.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .proxy_manager import Proxy

logger = logging.getLogger(__name__)

_DEFAULT_TEST_URL = "https://httpbin.org/get"  # echoes request headers + origin
_GEOIP_URL = "http://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city,isp,query"
_GEOIP_CACHE_TTL = 6 * 3600  # 6 hours

# Request headers whose presence indicates the proxy announced itself.
_FORWARDING_HEADERS = (
    "via", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
    "forwarded", "proxy-connection", "x-real-ip",
)


@dataclass
class ProxyCheckResult:
    """Outcome of a single proxy health check.

    Attributes:
        proxy: The :class:`Proxy` that was tested.
        alive: True if the proxy answered the test request.
        latency_ms: Round-trip time in ms or ``None``.
        anonymity: Detected anonymity level (``transparent|anonymous|elite``).
        country: Geoip country (filled via ip-api.com).
        country_code: ISO country code.
        isp: ISP name reported by ip-api.
        exit_ip: The IP that the target saw (proxy exit IP).
        error: Error message if the check failed.
        checked_at: Epoch seconds of the check.
    """

    proxy: Proxy
    alive: bool = False
    latency_ms: Optional[float] = None
    anonymity: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    isp: Optional[str] = None
    exit_ip: Optional[str] = None
    error: Optional[str] = None
    checked_at: float = field(default_factory=time.time)


class ProxyHealthChecker:
    """Test proxies against a target URL and enrich with geoip data."""

    def __init__(
        self,
        test_url: str = _DEFAULT_TEST_URL,
        timeout: float = 10.0,
        max_workers: int = 50,
    ) -> None:
        """Initialise the checker.

        Args:
            test_url: URL used to validate the proxy.
            timeout: Per-request timeout in seconds.
            max_workers: Default thread-pool size for :meth:`check_batch`.
        """
        self.test_url = test_url
        self.timeout = timeout
        self.max_workers = max(1, int(max_workers))
        self._geoip_cache: Dict[str, Dict[str, Any]] = {}
        self._geoip_lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()
        # Learned public IP of *this* machine (for transparency detection).
        self._client_ip: Optional[str] = None
        self._client_ip_ts: float = 0.0

    # -- single check --------------------------------------------------------
    def check_proxy(
        self,
        p: Proxy,
        test_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> ProxyCheckResult:
        """Test a single proxy.

        Args:
            p: Proxy to test.
            test_url: Override the default test URL.
            timeout: Override the default timeout.
        """
        try:
            import requests  # type: ignore
        except Exception as exc:  # pragma: no cover
            return ProxyCheckResult(proxy=p, alive=False, error=f"requests missing: {exc}")

        url = test_url or self.test_url
        to = timeout if timeout is not None else self.timeout
        proxies_arg = self._build_requests_proxies(p)
        start = time.time()
        try:
            resp = requests.get(
                url, proxies=proxies_arg, timeout=to,
                headers={"User-Agent": "AcademicResearchSuite/1.0"},
            )
            elapsed = (time.time() - start) * 1000.0
            resp.raise_for_status()
        except Exception as exc:
            return ProxyCheckResult(proxy=p, alive=False, error=str(exc))

        exit_ip = None
        header_echo: Optional[Dict[str, Any]] = None
        anonymity = "anonymous"
        try:
            body = resp.json()
            if isinstance(body, dict):
                origin = body.get("origin", "") or ""
                exit_ip = origin.split(",")[0].strip() if origin else None
                # Header-echo endpoints (/get, /headers) show what the
                # target actually received — the basis of the anonymity
                # classification below.
                echo = body.get("headers")
                if isinstance(echo, dict) and echo:
                    header_echo = echo
        except Exception:
            # Non-JSON endpoint -> still alive.
            pass

        try:
            anonymity = self._detect_anonymity(
                p, exit_ip,
                headers=header_echo,
                client_ip=self._client_public_ip(),
            )
        except Exception:  # pragma: no cover - defensive
            anonymity = self._detect_anonymity(p, exit_ip)

        geo = self.geoip_lookup(exit_ip) if exit_ip else {}
        return ProxyCheckResult(
            proxy=p,
            alive=True,
            latency_ms=round(elapsed, 2),
            anonymity=anonymity,
            country=geo.get("country"),
            country_code=geo.get("countryCode"),
            isp=geo.get("isp"),
            exit_ip=exit_ip,
        )

    def _client_public_ip(self, ttl: float = 3600.0) -> Optional[str]:
        """Best-effort public IP of this machine (cached for ``ttl``).

        Used to detect *transparent* proxies: if the target's echoed headers
        or origin contain this IP, the proxy is leaking the client address.
        """
        now = time.time()
        if self._client_ip and now - self._client_ip_ts < ttl:
            return self._client_ip
        try:
            import requests  # type: ignore
        except Exception:  # pragma: no cover
            return None
        for url in ("https://api.ipify.org", "https://httpbin.org/ip"):
            try:
                r = requests.get(url, timeout=5.0)
                r.raise_for_status()
                if "json" in (r.headers.get("Content-Type") or ""):
                    data = r.json()
                    ip = (data.get("origin") or data.get("ip") or "")
                    ip = str(ip).split(",")[0].strip()
                else:
                    ip = r.text.strip()
                if ip:
                    self._client_ip = ip
                    self._client_ip_ts = now
                    return ip
            except Exception:  # pragma: no cover - network optional
                continue
        return None

    # -- batch ---------------------------------------------------------------
    def check_batch(
        self,
        proxies: List[Proxy],
        max_workers: Optional[int] = None,
        progress_cb: Optional[Any] = None,
    ) -> List[ProxyCheckResult]:
        """Check a batch of proxies in parallel.

        Args:
            proxies: List of proxies to test.
            max_workers: Override the default pool size.
            progress_cb: Optional ``callable(done, total, result)`` invoked
                after each completion (called from worker threads).
        """
        workers = max(1, int(max_workers or self.max_workers))
        results: List[ProxyCheckResult] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.check_proxy, p): p for p in proxies}
            done = 0
            total = len(proxies)
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                except Exception as exc:  # pragma: no cover
                    res = ProxyCheckResult(proxy=futures[fut], alive=False, error=str(exc))
                results.append(res)
                done += 1
                if progress_cb is not None:
                    try:
                        progress_cb(done, total, res)
                    except Exception:  # pragma: no cover
                        logger.exception("progress_cb raised")
        logger.info(
            "check_batch: %d/%d alive", sum(1 for r in results if r.alive), len(results)
        )
        return results

    # -- continuous monitor --------------------------------------------------
    def continuous_monitor(
        self,
        proxies_provider: Any,
        interval_sec: float = 300.0,
        on_result: Optional[Any] = None,
    ) -> None:
        """Spawn a background thread that re-checks proxies periodically.

        Args:
            proxies_provider: A callable returning ``List[Proxy]`` (e.g.
                ``manager.all_proxies``).
            interval_sec: Seconds between sweeps.
            on_result: Optional ``callable(result)`` invoked after each check.
        """
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.warning("continuous_monitor already running")
            return
        self._monitor_stop.clear()

        def _loop() -> None:
            logger.info("proxy monitor started (interval=%ss)", interval_sec)
            while not self._monitor_stop.wait(timeout=interval_sec):
                try:
                    proxies = list(proxies_provider() or [])
                except Exception:  # pragma: no cover
                    logger.exception("proxies_provider raised")
                    continue
                if not proxies:
                    continue
                for res in self.check_batch(proxies):
                    if on_result is not None:
                        try:
                            on_result(res)
                        except Exception:  # pragma: no cover
                            logger.exception("on_result raised")
            logger.info("proxy monitor stopped")

        t = threading.Thread(target=_loop, name="ProxyHealthMonitor", daemon=True)
        t.start()
        self._monitor_thread = t

    def stop_monitor(self) -> None:
        """Signal the background monitor to stop."""
        self._monitor_stop.set()

    # -- geoip ---------------------------------------------------------------
    def geoip_lookup(self, ip: Optional[str]) -> Dict[str, Any]:
        """Look up geographic info for ``ip`` using ip-api.com (no key).

        Results are cached for ``_GEOIP_CACHE_TTL`` seconds.
        """
        if not ip:
            return {}
        now = time.time()
        with self._geoip_lock:
            cached = self._geoip_cache.get(ip)
            if cached and now - cached["_ts"] < _GEOIP_CACHE_TTL:
                return {k: v for k, v in cached.items() if k != "_ts"}

        try:
            import requests  # type: ignore

            resp = requests.get(_GEOIP_URL.format(ip=ip), timeout=8.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("geoip lookup failed for %s: %s", ip, exc)
            return {}

        if not isinstance(data, dict) or data.get("status") != "success":
            return {}
        data.setdefault("_ts", now)
        with self._geoip_lock:
            self._geoip_cache[ip] = data
        return {k: v for k, v in data.items() if k != "_ts"}

    # -- internals -----------------------------------------------------------
    @staticmethod
    def _build_requests_proxies(p: Proxy) -> Dict[str, str]:
        """Build the ``proxies=`` dict that ``requests`` expects.

        For SOCKS proxies the URL uses the ``socks5://`` / ``socks4://``
        scheme (requires ``PySocks`` to be installed in the environment).
        """
        auth = ""
        if p.username:
            auth = f"{p.username}:{p.password or ''}@"
        url = f"{p.protocol}://{auth}{p.host}:{p.port}"
        # ``requests`` keys are 'http' and 'https' for the matching schemes.
        return {"http": url, "https": url}

    @staticmethod
    def _detect_anonymity(
        p: Proxy,
        exit_ip: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        client_ip: Optional[str] = None,
    ) -> str:
        """Header-echo anonymity classification (audit 4-i).

        Priority:
          1. *transparent* — the target saw the client's real public IP,
             either as the request origin (``exit_ip == client_ip``) or
             echoed inside ``X-Forwarded-For`` / ``Forwarded`` /
             ``X-Real-IP``;
          2. *anonymous* — forwarding headers (``Via`` / ``X-Forwarded-*``)
             are present but the client IP is NOT leaked;
          3. *elite* — no forwarding headers at all (SOCKS hops always
             fall here; they never inject HTTP headers).

        Falls back to the legacy heuristic when no header echo is available
        (non-JSON test endpoints): ``socks`` → elite, unknown origin →
        anonymous, missing origin → transparent.
        """
        if not exit_ip:
            return "transparent"
        if headers:
            hdrs = {str(k).lower(): str(v) for k, v in headers.items()}
            # 1) client IP leak?
            if client_ip:
                if exit_ip == client_ip:
                    return "transparent"
                for key in ("x-forwarded-for", "forwarded", "x-real-ip"):
                    value = hdrs.get(key, "")
                    if value and client_ip in value:
                        return "transparent"
            # 2) proxy announced itself without leaking the client IP?
            if any(hdrs.get(key) for key in _FORWARDING_HEADERS):
                return "anonymous"
            # 3) nothing forwarded at all.
            return "elite"
        # Legacy heuristic (no header echo available).
        if p.protocol.startswith("socks"):
            return "elite"
        return "anonymous"
