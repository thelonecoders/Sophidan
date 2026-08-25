"""
base_scraper.py
===============

Foundation module for the data-acquisition layer of the Academic Research
Suite.

This module defines three building blocks every concrete scraper in
``data_acquisition/`` inherits from or composes:

* :class:`Paper` — a rich, dataclass-based representation of a single
  scientific publication (title, authors, abstract, DOI, citation
  count, references, keywords, identifiers, bibliographic metadata,
  plus the raw payload returned by the upstream API).
* :class:`ScraperResult` — a dataclass capturing the outcome of a
  single ``search`` call: source, original query, total results,
  parsed papers, the raw response payload, timing information and a
  list of non-fatal errors encountered along the way.
* :class:`BaseScraper` — an abstract base class providing shared
  infrastructure: HTTP request execution with retry/back-off via
  ``tenacity``, a token-bucket rate limiter, transparent response
  caching (lazy ``utils.cache.Cache`` integration), proxy rotation
  via an injectable ``ProxyManager``, pagination helper and progress
  signalling through the application-wide ``core.events.EventBus``.

Concrete scrapers implement :meth:`BaseScraper.search` and
:meth:`BaseScraper.fetch_by_id`; everything else (HTTP, retries,
caching, rate limiting, event emission) is provided here so every
source stays consistent.

The module is intentionally free of any Qt import at the top level:
``EventBus`` is loaded lazily inside :meth:`BaseScraper._emit_event`
so the file remains importable in headless / unit-test environments
where ``qtpy`` is unavailable.
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional, Union

import requests

try:  # pragma: no cover - tenacity is a declared dep but import is defensive
    from tenacity import (
        Retrying,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
    )
    _TENACITY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TENACITY_AVAILABLE = False

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional integrations (loaded lazily / defensively)
# ---------------------------------------------------------------------------

def _try_import_cache() -> Optional[Any]:
    """Lazy import of :class:`utils.cache.Cache`.

    Returns the class if importable, otherwise ``None``.  Kept as a
    function (not a module-level constant) so the import happens at
    call time, which lets unit tests monkey-patch the path.
    """
    try:  # pragma: no cover - depends on sibling module being built
        from utils.cache import Cache  # type: ignore
        return Cache
    except Exception:  # noqa: BLE001
        return None


def _try_get_event_bus() -> Optional[Any]:
    """Lazy import of the singleton ``EventBus`` from ``core.events``.

    Returns the bus instance if available, otherwise ``None``.
    """
    try:  # pragma: no cover - depends on sibling module being built
        from core.events import EventBus  # type: ignore
        if hasattr(EventBus, "instance"):
            return EventBus.instance()
        if hasattr(EventBus, "get_instance"):
            return EventBus.get_instance()
        return EventBus()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Paper:
    """A normalized representation of a scientific publication.

    Every scraper in this package maps its source-specific payload
    into a :class:`Paper` so downstream consumers (database layer,
    citation graph builder, reporting tools) only need to know one
    schema.  All fields are optional except :attr:`title`; missing
    information is represented by ``None`` (scalars) or empty lists
    (collections).  The :attr:`raw` field preserves the verbatim
    response from the upstream API for forensic / debugging use.
    """

    title: str = ""
    authors: List[str] = field(default_factory=list)
    abstract: str = ""
    year: Optional[int] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    source: str = ""
    citations_count: Optional[int] = None
    references: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    pdf_url: Optional[str] = None
    issn: Optional[str] = None
    isbn: Optional[str] = None
    publisher: Optional[str] = None
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    language: Optional[str] = None
    paper_type: Optional[str] = None
    fields_of_study: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    # -- serialization ----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary representation.

        Returns:
            A plain ``dict`` mirroring every field of this paper.  The
            :attr:`raw` payload is returned as-is (callers are
            responsible for ensuring it is serializable).
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Paper":
        """Construct a :class:`Paper` from a (possibly partial) mapping.

        Unknown keys are silently dropped so callers may pass a raw
        API payload without pre-filtering.

        Args:
            data: A mapping of field-name -> value.  Missing fields
                default to the dataclass defaults.

        Returns:
            A populated :class:`Paper` instance.
        """
        valid_keys = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in dict(data).items() if k in valid_keys}
        return cls(**filtered)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        author_summary = ", ".join(self.authors[:3])
        if len(self.authors) > 3:
            author_summary += f" + {len(self.authors) - 3} more"
        return (
            f"Paper(title={self.title!r}, authors=[{author_summary}], "
            f"year={self.year}, source={self.source!r})"
        )


@dataclass
class ScraperResult:
    """Outcome of a single ``search`` invocation.

    Attributes:
        source: Short identifier of the originating scraper
            (e.g. ``"arxiv"``, ``"openalex"``).
        query: The original query string passed to the scraper.
        total_results: Total number of matches reported by the upstream
            API (may be larger than ``len(papers)`` when paginating).
        papers: The parsed :class:`Paper` objects returned in this call.
        raw_response: The verbatim parsed response (JSON dict, XML
            string, etc.) for callers that need access to fields the
            scraper chose not to surface.  May be ``None``.
        timestamp: UTC timestamp at which the search was performed.
        elapsed_ms: Wall-clock duration of the entire search in
            milliseconds.
        errors: Non-fatal errors / warnings encountered (timeouts,
            individual page failures, parse errors).  An empty list
            means a clean run.
    """

    source: str = ""
    query: str = ""
    total_results: int = 0
    papers: List[Paper] = field(default_factory=list)
    raw_response: Any = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    elapsed_ms: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict of this result."""
        return {
            "source": self.source,
            "query": self.query,
            "total_results": self.total_results,
            "papers": [p.to_dict() for p in self.papers],
            "raw_response": self.raw_response,
            "timestamp": self.timestamp,
            "elapsed_ms": self.elapsed_ms,
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------

class _TokenBucket:
    """A minimal thread-safe token-bucket rate limiter.

    Tokens refill at ``rate`` tokens per second up to ``capacity``.
    :meth:`acquire` blocks until a token is available.  Used by
    :class:`BaseScraper` to honor per-source rate limits.
    """

    def __init__(self, rate: float, capacity: Optional[float] = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self.rate = float(rate)
        # Default capacity must be at least 1 token so a single-request
        # acquire(1.0) can succeed even when rate < 1 req/s.  Otherwise
        # the bucket could never hold enough tokens for a single request,
        # causing every acquire() to time out.
        if capacity is None:
            capacity = max(rate, 1.0)
        self.capacity = float(capacity)
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0, timeout: float = 60.0) -> bool:
        """Block until ``tokens`` are available or ``timeout`` elapses.

        Args:
            tokens: Number of tokens to consume (default 1).
            timeout: Maximum seconds to wait.  If the bucket cannot be
                served within this window, returns ``False`` without
                consuming tokens.

        Returns:
            ``True`` if the tokens were acquired, ``False`` on timeout.
        """
        deadline = time.monotonic() + timeout
        with self._lock:
            while True:
                now = time.monotonic()
                delta = now - self._last
                self._tokens = min(self.capacity, self._tokens + delta * self.rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                needed = tokens - self._tokens
                wait = needed / self.rate
                if time.monotonic() + wait > deadline:
                    return False
                # Release lock while sleeping; loop will re-check.
                # Use a condvar-like pattern with small sleeps to keep
                # things simple and dependency-free.
                time.sleep(min(wait, 0.25))


# ---------------------------------------------------------------------------
# BaseScraper
# ---------------------------------------------------------------------------

class BaseScraper(ABC):
    """Abstract base class for every data source scraper.

    Subclasses MUST implement :meth:`search` and :meth:`fetch_by_id`.
    They inherit:
      * HTTP request execution with retries + exponential back-off
        (via ``tenacity`` when available, otherwise a manual loop).
      * A per-instance token-bucket rate limiter, configurable via
        :attr:`rate_limit` (requests per second).
      * Optional response caching through :class:`utils.cache.Cache`
        (loaded lazily; absent cache is a no-op).
      * Optional proxy rotation through a ``ProxyManager`` instance
        (any object exposing ``get_proxy() -> Optional[str]``).
      * Progress signalling via the global ``EventBus`` (also lazy).

    Args:
        proxy_manager: Optional proxy manager (duck-typed; must
            implement ``get_proxy()``).  ``None`` disables proxy use.
        rate_limit: Maximum requests per second for this scraper
            (default ``1.0``).
        cache: Optional ``utils.cache.Cache`` instance.  If ``None``
            and a default cache is importable, it is used; otherwise
            caching is disabled.
        timeout: Default per-request timeout in seconds.
        max_retries: Maximum number of retries for transient errors.
        user_agent: Value of the ``User-Agent`` header.
    """

    #: Default User-Agent string; overridden per-subclass if desired.
    DEFAULT_USER_AGENT = (
        "AcademicResearchSuite/0.1 "
        "(+https://github.com/academic-research-suite)"
    )

    #: Subclasses should override with the source's short name.
    SOURCE_NAME: str = "base"

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        rate_limit: float = 1.0,
        cache: Optional[Any] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: Optional[str] = None,
    ) -> None:
        self.proxy_manager = proxy_manager
        self.rate_limit = float(rate_limit)
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self._bucket = _TokenBucket(rate=self.rate_limit)
        self._cache = cache
        self.logger = logging.getLogger(self.__class__.__module__)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent})

    # -- public name / source --------------------------------------------

    @property
    def name(self) -> str:
        """Short, human-readable name of the data source."""
        return self.SOURCE_NAME

    # -- abstract API -----------------------------------------------------

    @abstractmethod
    def search(self, query: str, **kwargs: Any) -> ScraperResult:
        """Search the source for papers matching ``query``.

        Args:
            query: The search string.
            **kwargs: Source-specific options (max_results, filters,
                sort order, ...).

        Returns:
            A populated :class:`ScraperResult`.
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single paper by its source-native identifier.

        Args:
            paper_id: The identifier understood by this source (e.g.
                arXiv ID, PMID, OpenAlex ID, S2 paper ID, DOI...).

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        raise NotImplementedError

    # -- HTTP plumbing ---------------------------------------------------

    def _respect_rate_limit(self, tokens: float = 1.0) -> None:
        """Block until the rate limiter permits the next request.

        Args:
            tokens: Token cost of the next call (default 1 per request).
        """
        if not self._bucket.acquire(tokens=tokens):
            self.logger.warning(
                "Rate-limit acquire timed out; proceeding anyway (source=%s).",
                self.name,
            )

    def _proxies(self) -> Optional[Dict[str, str]]:
        """Return a ``proxies`` dict for ``requests`` if a proxy is set."""
        if self.proxy_manager is None:
            return None
        try:
            addr = self.proxy_manager.get_proxy()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None
        if not addr:
            return None
        if addr.startswith(("http://", "https://", "socks5://", "socks4://")):
            url = addr
        else:
            url = f"http://{addr}"
        return {"http": url, "https": url}

    def _make_request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        data: Optional[Any] = None,
        json_body: Optional[Any] = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
        cache_key: Optional[str] = None,
        use_cache: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        """Perform an HTTP request with retries, rate-limiting and caching.

        Honors the configured token-bucket rate limiter and retries
        transient failures (connection errors, 429/5xx responses)
        using ``tenacity`` with exponential back-off when available,
        falling back to a manual loop otherwise.

        Args:
            method: HTTP method (``"GET"``, ``"POST"`` ...).
            url: Target URL.
            params: Query-string parameters.
            data: Form data.
            json_body: JSON body (mutually exclusive with ``data``).
            headers: Extra headers merged on top of the session
                defaults (``User-Agent``).
            timeout: Per-request timeout override.
            cache_key: If given (and caching is enabled), the response
                body is stored under this key for future reuse.
            use_cache: If ``False``, bypass the cache entirely
                (cache_key is ignored).
            **kwargs: Passed through to ``requests.request``.

        Returns:
            A :class:`requests.Response` instance.

        Raises:
            requests.RequestException: If all retries fail.
        """
        # Cache hit shortcut (GET only, with a key, and not disabled).
        if (
            method.upper() == "GET"
            and use_cache
            and cache_key
            and self._cache is not None
        ):
            try:
                cached = self._cache.get(cache_key)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                cached = None
            if cached is not None:
                self.logger.debug("Cache HIT for %s", cache_key)
                mock = requests.Response()
                mock.status_code = 200
                mock._content = (
                    cached.encode("utf-8")
                    if isinstance(cached, str)
                    else cached
                )
                mock.url = url
                return mock

        # Compose headers.
        merged_headers: Dict[str, str] = {"User-Agent": self.user_agent}
        if headers:
            merged_headers.update(dict(headers))

        request_timeout = timeout if timeout is not None else self.timeout
        proxies = self._proxies()

        def _do_request() -> requests.Response:
            self._respect_rate_limit()
            resp = self._session.request(
                method=method.upper(),
                url=url,
                params=params,
                data=data,
                json=json_body,
                headers=merged_headers,
                timeout=request_timeout,
                proxies=proxies,
                **kwargs,
            )
            # Treat 429 and 5xx as retryable.
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(
                    f"HTTP {resp.status_code} from {url}", response=resp
                )
            resp.raise_for_status()
            return resp

        if _TENACITY_AVAILABLE:
            retryer = Retrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential(multiplier=1, min=1, max=30),
                retry=retry_if_exception_type(
                    (requests.ConnectionError, requests.Timeout, requests.HTTPError)
                ),
                reraise=True,
            )
            response = retryer(_do_request)
        else:  # pragma: no cover - fallback path
            last_err: Optional[Exception] = None
            response = None
            for attempt in range(self.max_retries):
                try:
                    response = _do_request()
                    break
                except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                    last_err = exc
                    sleep_for = min(2 ** attempt, 30)
                    self.logger.warning(
                        "Request to %s failed (attempt %d/%d): %s; sleeping %.1fs",
                        url, attempt + 1, self.max_retries, exc, sleep_for,
                    )
                    time.sleep(sleep_for)
            if response is None:
                assert last_err is not None
                raise last_err

        # Store in cache.
        if (
            method.upper() == "GET"
            and use_cache
            and cache_key
            and self._cache is not None
        ):
            try:
                self._cache.set(cache_key, response.text)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                self.logger.debug("Cache write failed for %s", cache_key)

        return response

    def _handle_response(self, resp: requests.Response) -> Any:
        """Parse a response body into a Python object.

        Tries JSON first, falls back to returning the raw text.  XML
        responses should be parsed explicitly by the scraper (e.g.
        via :mod:`xml.etree.ElementTree`) — this helper only does the
        common JSON / text dispatch.

        Args:
            resp: The :class:`requests.Response` to parse.

        Returns:
            A deserialized Python object (typically ``dict`` or
            ``list`` for JSON, or ``str`` otherwise).
        """
        if resp.status_code >= 400:
            raise requests.HTTPError(
                f"HTTP {resp.status_code}: {resp.text[:200]}", response=resp
            )
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def _paginate(
        self,
        url: str,
        max_pages: int = 5,
        *,
        params: Optional[Mapping[str, Any]] = None,
        page_size: int = 50,
        page_param: str = "page",
        start_page: int = 1,
        results_key: str = "results",
        next_cursor_param: Optional[str] = None,
        next_cursor_field: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Generic paginator over a JSON paginated endpoint.

        Supports two strategies:
          * **Page-number pagination**: increments ``page_param``
            from ``start_page`` up to ``start_page + max_pages - 1``.
          * **Cursor pagination**: if ``next_cursor_param`` and
            ``next_cursor_field`` are set, the cursor value read
            from each response's ``meta`` (or top-level) field is
            used as the next request's ``next_cursor_param`` value
            until it is empty / ``False`` or ``max_pages`` is hit.

        Yields each full JSON page (as a dict).  When the API returns
        a non-dict response (or the ``results_key`` list is empty),
        iteration stops.

        Args:
            url: The endpoint URL.
            max_pages: Hard ceiling on number of requests.
            params: Base query parameters (cloned per page).
            page_size: Value of the ``per_page``/``limit`` parameter.
            page_param: Name of the page-number query parameter.
            start_page: First page number to request.
            results_key: Key under which the list of items lives.
            next_cursor_param: If set, switch to cursor mode using
                this query parameter name.
            next_cursor_field: Dotted path (e.g. ``"meta.next_cursor"``)
                from which to read the next cursor value.

        Yields:
            Each page's parsed JSON dict.
        """
        base_params: Dict[str, Any] = dict(params or {})
        base_params.setdefault("per_page", page_size)
        cursor: Optional[str] = None
        for page_idx in range(max_pages):
            page_params = dict(base_params)
            if next_cursor_param and next_cursor_field:
                if page_idx == 0 and "cursor" in base_params:
                    cursor = base_params["cursor"]
                if not cursor and page_idx > 0:
                    break
                if cursor:
                    page_params[next_cursor_param] = cursor
            else:
                page_params[page_param] = start_page + page_idx
            try:
                resp = self._make_request("GET", url, params=page_params)
            except requests.RequestException as exc:
                self.logger.warning(
                    "Pagination aborted at page %d: %s", page_idx + 1, exc
                )
                break
            data = self._handle_response(resp)
            if not isinstance(data, dict):
                break
            yield data
            items = data.get(results_key) or []
            if not items:
                break
            if next_cursor_param and next_cursor_field:
                cursor = _dotted_get(data, next_cursor_field)
                if not cursor:
                    break
            elif len(items) < page_size:
                break

    # -- event bus -------------------------------------------------------

    def _emit_event(
        self,
        event_name: str,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Emit a progress / status event on the global EventBus.

        Looks up ``core.events.EventBus`` lazily; if the bus or the Qt
        layer is unavailable, the call is silently ignored (logged at
        ``debug``) so headless runs and unit tests are not affected.
        """
        bus = _try_get_event_bus()
        if bus is None:
            return
        body = dict(payload or {})
        body.setdefault("source", self.name)
        body.setdefault("event", event_name)
        # Try a few common method names defensively; whatever the
        # concrete EventBus exposes will be picked up.
        for method_name in ("emit", "publish", "signal", "dispatch"):
            method = getattr(bus, method_name, None)
            if callable(method):
                try:
                    method(event_name, body)
                except Exception:  # noqa: BLE001
                    self.logger.debug(
                        "EventBus.%s failed for %s", method_name, event_name,
                        exc_info=True,
                    )
                return
        self.logger.debug("EventBus has no known emit method; skipping %s", event_name)

    # -- convenience -----------------------------------------------------

    @staticmethod
    def _now_ms() -> int:
        """Return the current epoch time in milliseconds."""
        return int(time.time() * 1000)

    @staticmethod
    def _cache_key(*parts: Any) -> str:
        """Compose a deterministic cache key from arbitrary parts."""
        return "|".join(str(p) for p in parts)


def _dotted_get(obj: Any, dotted: str) -> Any:
    """Look up a nested attribute / key by a dotted path.

    Supports both dict keys and object attributes.  Returns ``None``
    on any missing segment.
    """
    cur: Any = obj
    for part in dotted.split("."):
        if cur is None:
            return None
        if isinstance(cur, Mapping):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur


__all__ = [
    "Paper",
    "ScraperResult",
    "BaseScraper",
]
