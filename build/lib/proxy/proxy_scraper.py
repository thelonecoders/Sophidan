"""Scrape FREE public proxy lists from a curated set of online sources.

The :class:`ProxyScraper` understands nine well-known proxy list sources and
normalises everything into :class:`proxy.proxy_manager.Proxy` objects.  Each
source has a dedicated parser; the orchestrator method
:meth:`ProxyScraper.scrape_all_sources` runs them all (optionally in parallel)
and de-duplicates by ``(host, port, protocol)``.

Heavy dependencies (``requests``, ``bs4``, ``lxml``, ``tenacity``) are imported
lazily so the module is import-safe even when those packages are absent.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from .proxy_manager import Proxy

logger = logging.getLogger(__name__)

# Curated source catalog.  Each value is ``(protocol, parser_key)`` where
# ``protocol`` is the default proxy protocol the source advertises and
# ``parser_key`` selects the parser implementation in ``_PARSERS``.
DEFAULT_SOURCES: Dict[str, Tuple[str, str]] = {
    "https://www.proxy-list.download/": ("http", "proxylistdownload"),
    "https://www.socks-proxy.net/": ("socks4", "html_table"),
    "https://www.sslproxies.org/": ("https", "html_table"),
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt": (
        "http",
        "raw_iport",
    ),
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt": (
        "socks4",
        "raw_iport",
    ),
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt": (
        "socks5",
        "raw_iport",
    ),
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt": (
        "http",
        "raw_iport",
    ),
    "https://spys.one/en/": ("http", "spys_one"),
    "https://free-proxy-list.net/": ("http", "html_table"),
}

# Sub-API endpoints used by proxy-list.download (the homepage is just HTML).
_PROXYLISTDOWNLOAD_API = {
    "http": "https://www.proxy-list.download/api/v1/get?type=http",
    "https": "https://www.proxy-list.download/api/v1/get?type=https",
    "socks4": "https://www.proxy-list.download/api/v1/get?type=socks4",
    "socks5": "https://www.proxy-list.download/api/v1/get?type=socks5",
}

_IP_PORT_RE = re.compile(
    r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\D{1,5}(\d{2,5})"
)


def _safe_get(url: str, timeout: float = 15.0) -> Optional[str]:
    """Perform a GET request with retries via ``tenacity`` if available."""
    try:
        import requests  # type: ignore
    except Exception as exc:  # pragma: no cover
        logger.error("requests is required for scraping: %s", exc)
        return None

    def _do() -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }
        resp = requests.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        return resp.text

    try:
        from tenacity import (  # type: ignore
            RetryError,
            Retrying,
            stop_after_attempt,
            wait_exponential,
        )

        retryer = Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            reraise=True,
        )
        try:
            return retryer(_do)
        except RetryError:  # pragma: no cover
            return None
    except Exception:
        # tenacity missing -> single attempt
        try:
            return _do()
        except Exception as exc:
            logger.warning("GET %s failed: %s", url, exc)
            return None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def _parse_raw_iport(text: str, protocol: str, source: str) -> List[Proxy]:
    """Parse lines of ``ip:port``."""
    out: List[Proxy] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _IP_PORT_RE.match(line)
        if not m:
            continue
        host, port = m.group(1), int(m.group(2))
        out.append(Proxy(host=host, port=port, protocol=protocol, source=source))
    return out


def _parse_proxylistdownload(text: str, protocol: str, source: str) -> List[Proxy]:
    """The homepage lists types; we instead query the JSON-ish API.

    The ``text`` arg is unused (the homepage HTML); the parser hits each
    sub-API endpoint and aggregates.
    """
    out: List[Proxy] = []
    for proto, api_url in _PROXYLISTDOWNLOAD_API.items():
        body = _safe_get(api_url)
        if not body:
            continue
        out.extend(_parse_raw_iport(body, proto, api_url))
    return out


def _parse_html_table(text: str, protocol: str, source: str) -> List[Proxy]:
    """Parse the classic ip:port <table> used by sslproxies / free-proxy-list."""
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:  # pragma: no cover
        logger.error("beautifulsoup4 is required for HTML scraping: %s", exc)
        return []
    soup = BeautifulSoup(text, "lxml")
    out: List[Proxy] = []
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        host = cells[0].get_text(strip=True)
        port_str = cells[1].get_text(strip=True)
        if not _IP_PORT_RE.match(f"{host}:{port_str}"):
            continue
        # sslproxies / free-proxy-list put HTTPS support in a later column.
        https_cell = cells[6].get_text(strip=True).lower() if len(cells) > 6 else ""
        proto = "https" if https_cell == "yes" else protocol
        country = cells[2].get_text(strip=True) if len(cells) > 2 else None
        anonymity = "anonymous"
        if len(cells) > 4:
            anon_txt = cells[4].get_text(strip=True).lower()
            if "elite" in anon_txt:
                anonymity = "elite"
            elif "transparent" in anon_txt:
                anonymity = "transparent"
        out.append(
            Proxy(
                host=host,
                port=int(port_str),
                protocol=proto,
                country=country,
                anonymity=anonymity,
                source=source,
            )
        )
    return out


def _parse_spys_one(text: str, protocol: str, source: str) -> List[Proxy]:
    """Best-effort scrape of spys.one (port is JS-obfuscated, so we grab IP
    and known ports via regex)."""
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:  # pragma: no cover
        logger.error("beautifulsoup4 is required for spys.one: %s", exc)
        return []
    soup = BeautifulSoup(text, "lxml")
    out: List[Proxy] = []
    for row in soup.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        txt = " ".join(c.get_text(" ", strip=True) for c in cells)
        m = _IP_PORT_RE.search(txt)
        if not m:
            continue
        host, port = m.group(1), int(m.group(2))
        # spys.one publishes country + anonymity columns too; try to extract.
        anonymity = "anonymous"
        if "elite" in txt.lower():
            anonymity = "elite"
        elif "transparent" in txt.lower():
            anonymity = "transparent"
        country = None
        for c in cells:
            ct = c.get_text(strip=True)
            if len(ct) == 2 and ct.isalpha():
                country = ct
                break
        out.append(
            Proxy(
                host=host,
                port=port,
                protocol=protocol,
                country=country,
                anonymity=anonymity,
                source=source,
            )
        )
    return out


_PARSERS: Dict[str, Callable[[str, str, str], List[Proxy]]] = {
    "raw_iport": _parse_raw_iport,
    "proxylistdownload": _parse_proxylistdownload,
    "html_table": _parse_html_table,
    "spys_one": _parse_spys_one,
}


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------
class ProxyScraper:
    """Scrape FREE public proxy lists from multiple sources.

    Usage::

        scraper = ProxyScraper()
        proxies = scraper.scrape_all_sources()  # blocking, returns List[Proxy]
        future = scraper.scrape_async()        # non-blocking, returns Future
    """

    def __init__(
        self,
        sources: Optional[Dict[str, Tuple[str, str]]] = None,
        max_workers: int = 6,
        rate_limit_sec: float = 0.5,
    ) -> None:
        """Initialise the scraper.

        Args:
            sources: Override the default source catalog.  Maps URL to
                ``(protocol, parser_key)``.
            max_workers: Thread pool size for parallel scraping.
            rate_limit_sec: Minimum delay between requests to the same host.
        """
        self.sources: Dict[str, Tuple[str, str]] = dict(
            sources if sources is not None else DEFAULT_SOURCES
        )
        self.max_workers = max(1, int(max_workers))
        self.rate_limit_sec = max(0.0, float(rate_limit_sec))
        self._last_request: Dict[str, float] = {}
        self._lock = threading.Lock()

    # -- public API ----------------------------------------------------------
    def scrape_all_sources(self) -> List[Proxy]:
        """Scrape every configured source in parallel.

        Returns:
            De-duplicated list of :class:`Proxy` objects.
        """
        results: Dict[str, List[Proxy]] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self.scrape_source, url): url for url in self.sources
            }
            for fut in as_completed(futures):
                url = futures[fut]
                try:
                    proxies = fut.result()
                except Exception:  # pragma: no cover
                    logger.exception("scrape_source failed for %s", url)
                    proxies = []
                results[url] = proxies
                logger.info("source %s yielded %d proxies", url, len(proxies))

        # De-dup by (host, port, protocol)
        seen: Dict[str, Proxy] = {}
        for proxies in results.values():
            for p in proxies:
                key = f"{p.protocol}://{p.host}:{p.port}"
                if key not in seen:
                    seen[key] = p
        merged = list(seen.values())
        logger.info(
            "scrape_all_sources: %d unique proxies from %d sources",
            len(merged),
            len(results),
        )
        return merged

    def scrape_source(self, url: str) -> List[Proxy]:
        """Scrape a single source URL.

        Args:
            url: The source URL (must be in ``self.sources`` unless
                ``protocol`` and ``parser`` are auto-detected).
        """
        protocol, parser_key = self.sources.get(url, ("http", "raw_iport"))
        self._rate_limit(url)
        text = _safe_get(url)
        if text is None:
            logger.warning("no body fetched for %s", url)
            return []
        parser = _PARSERS.get(parser_key, _parse_raw_iport)
        try:
            proxies = parser(text, protocol, url)
        except Exception:  # pragma: no cover
            logger.exception("parser %s crashed on %s", parser_key, url)
            proxies = []
        logger.info("%s parser=%s -> %d proxies", url, parser_key, len(proxies))
        return proxies

    def scrape_async(self):
        """Run :meth:`scrape_all_sources` in a background thread.

        Returns:
            ``concurrent.futures.Future`` resolving to ``List[Proxy]``.
        """
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self.scrape_all_sources)
        # Detach the executor so it doesn't block shutdown of the interpreter.
        # (We keep a reference on the future via its internal state.)
        return future

    # -- internals -----------------------------------------------------------
    def _rate_limit(self, url: str) -> None:
        """Enforce a minimum delay between requests to the same host."""
        if self.rate_limit_sec <= 0:
            return
        host = urlparse(url).netloc
        with self._lock:
            last = self._last_request.get(host, 0.0)
            now = time.time()
            wait = self.rate_limit_sec - (now - last)
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.time()


# Convenience: allow ``list(ProxyScraper())`` style iteration.
def iter_sources(
    sources: Optional[Iterable[str]] = None,
) -> Iterable[Tuple[str, str]]:
    """Yield ``(url, protocol)`` tuples for the given or default sources."""
    catalog = DEFAULT_SOURCES if sources is None else {u: DEFAULT_SOURCES[u] for u in sources if u in DEFAULT_SOURCES}
    for url, (proto, _parser) in catalog.items():
        yield url, proto
