"""
base_scraper_ext.py
===================

Scraper for the **Bielefeld Academic Search Engine (BASE)** API
(``https://api.base-search.net/``).

BASE is one of the world's largest aggregators of open-access
documents (journals, repositories, datasets).  A free academic API
key is obtainable from
**https://www.base-search.net/about/en/about_develop.php**.

Capabilities
------------
* :meth:`search` — full-text search with optional filters for
  publication year, document type, language and country of origin.
* :meth:`fetch_by_id` — single-record lookup by BASE internal ID
  (``dc:identifier``).

Authentication
--------------
The API supports two modes:

  1. **Anonymous**: works at a low rate (~1 req/s).
  2. **Authenticated**: requires an API key obtained from the BASE
     service team, grants a higher rate limit.

Resolution order for the key:

  1. ``api_key`` constructor argument.
  2. ``BASE_API_KEY`` environment variable.
  3. ``config.settings.base_api_key`` (lazy import).

Rate limits
-----------
We default to ``1`` r/s regardless of whether a key is set, to be
polite to the BASE infrastructure.
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from ._compat import BaseScraper, Paper, ScraperResult, get_logger

logger = logging.getLogger(__name__)


def _load_settings() -> Any:
    """Lazily import :mod:`config.settings` and return the module."""
    try:  # pragma: no cover - depends on sibling module being built
        from config import settings  # type: ignore
        return settings
    except Exception:  # noqa: BLE001
        return None


class BASEScraper(BaseScraper):
    """Scraper for the BASE (Bielefeld Academic Search Engine) API."""

    BASE_URL = "https://api.base-search.net/"
    SOURCE_NAME = "base"

    # Recognised document-type filter values exposed by BASE.
    _VALID_TYPES = {"publication", "dataset", "software"}

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        api_key: Optional[str] = None,
        rate_limit: float = 1.0,
        cache: Optional[Any] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: Optional[str] = None,
    ) -> None:
        """Initialize a :class:`BASEScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            api_key: BASE API key (optional — falls back to anonymous
                access when not provided).
            rate_limit: Maximum requests per second.
            cache: Optional response cache.
            timeout: Per-request timeout in seconds.
            max_retries: Maximum retry attempts.
            user_agent: Optional User-Agent override.
        """
        super().__init__(
            proxy_manager=proxy_manager,
            rate_limit=rate_limit,
            cache=cache,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent,
        )
        self.logger: logging.Logger = get_logger(__name__)
        self.api_key: Optional[str] = api_key or self._resolve_api_key()

    # -- BaseScraper interface -------------------------------------------

    def search(
        self,
        query: str,
        max_results: int = 50,
        year: Optional[int] = None,
        type: Optional[str] = None,
        language: Optional[str] = None,
        country: Optional[str] = None,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search BASE for documents matching ``query``.

        Args:
            query: Free-text search string (uses BASE's ``query``
                parameter, which supports Lucene syntax).
            max_results: Maximum number of records to return.
            year: 4-digit publication-year filter.
            type: Document-type filter — one of ``"publication"``,
                ``"dataset"``, ``"software"``.
            language: ISO-639-1 / ISO-639-2 language code (e.g.
                ``"eng"``, ``"ger"``, ``"fra"``).
            country: ISO-3166-1 alpha-2 country code of the
                repository's host country.
            **kwargs: Reserved for future use.

        Returns:
            A populated :class:`ScraperResult`.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        errors: List[str] = []

        # BASE accepts query parameters via the ``?func=perform&query=...``
        # REST endpoint.  Anonymous clients skip the API key entirely.
        params: Dict[str, Any] = {
            "func": "perform",
            "query": query,
            "format": "json",
            "hits": min(max_results, 100),
            "offset": 0,
        }
        if self.api_key:
            params["apikey"] = self.api_key
        if year:
            params["year"] = int(year)
        if type:
            t = (type or "").strip().lower()
            if t in self._VALID_TYPES:
                params["type"] = t
            else:
                self.logger.warning(
                    "Unknown BASE type=%r; expected one of %s",
                    type, sorted(self._VALID_TYPES),
                )
        if language:
            params["lang"] = language
        if country:
            params["country"] = country

        raw_response: Dict[str, Any] = {}
        try:
            cache_key = self._cache_key(
                "base", "search", query, params["hits"], params["offset"]
            )
            resp = self._make_request(
                "GET", self.BASE_URL, params=params, cache_key=cache_key
            )
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("BASE response is not a JSON object")
            raw_response = data

            # BASE returns the total count under ``response.numFound``.
            response_block = data.get("response", {})
            try:
                result.total_results = int(response_block.get("numFound", 0))
            except (TypeError, ValueError):
                result.total_results = 0

            docs = response_block.get("docs", []) or []
            for doc in docs:
                paper = self._parse_doc(doc)
                if paper is not None:
                    result.papers.append(paper)
                    if len(result.papers) >= max_results:
                        break

            # Pagination.
            offset = params["hits"]
            while (
                len(result.papers) < max_results
                and offset < result.total_results
            ):
                params["offset"] = offset
                try:
                    cache_key = self._cache_key(
                        "base", "search", query, params["hits"], offset
                    )
                    resp = self._make_request(
                        "GET", self.BASE_URL, params=params, cache_key=cache_key
                    )
                    data = resp.json()
                except Exception as exc:  # noqa: BLE001
                    err = f"BASE pagination error: {exc}"
                    errors.append(err)
                    self.logger.warning(err)
                    break
                response_block = data.get("response", {})
                docs = response_block.get("docs", []) or []
                if not docs:
                    break
                for doc in docs:
                    if len(result.papers) >= max_results:
                        break
                    paper = self._parse_doc(doc)
                    if paper is not None:
                        result.papers.append(paper)
                offset += params["hits"]

        except Exception as exc:  # noqa: BLE001
            err = f"BASE request failed: {exc}"
            errors.append(err)
            self.logger.error(err, exc_info=True)

        result.raw_response = raw_response
        result.errors = errors
        result.timestamp = datetime.now(timezone.utc).isoformat()
        result.elapsed_ms = self._now_ms() - start_ms
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single BASE record by its internal BASE ID.

        Args:
            paper_id: BASE internal document ID (typically
                    ``<repo-id>:<doc-id>``).

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        if not paper_id:
            return None
        # BASE does not have a dedicated /record/{id} endpoint; the
        # recommended approach is to query the search API with an
        # ``id`` filter.
        params: Dict[str, Any] = {
            "func": "perform",
            "query": f"id:{paper_id}",
            "format": "json",
            "hits": 1,
            "offset": 0,
        }
        if self.api_key:
            params["apikey"] = self.api_key
        try:
            cache_key = self._cache_key("base", "id", paper_id)
            resp = self._make_request(
                "GET", self.BASE_URL, params=params, cache_key=cache_key
            )
            data = resp.json()
            docs = (
                data.get("response", {}).get("docs", [])
                if isinstance(data, dict) else []
            )
            if not docs:
                return None
            return self._parse_doc(docs[0])
        except Exception as exc:  # noqa: BLE001
            self.logger.error("BASE fetch_by_id(%s) failed: %s", paper_id, exc)
            return None

    # -- internal helpers ------------------------------------------------

    def _resolve_api_key(self) -> Optional[str]:
        """Resolve the BASE API key from env var or settings."""
        env = os.environ.get("BASE_API_KEY")
        if env:
            return env
        settings = _load_settings()
        if settings is None:
            return None
        for attr in ("base_api_key", "base_search_api_key"):
            value = getattr(settings, attr, None)
            if value:
                return value
        return None

    def _parse_doc(self, doc: Mapping[str, Any]) -> Optional[Paper]:
        """Convert a BASE Solr document (dict) into a :class:`Paper`.

        BASE returns Solr-style fields where most values are lists
        even when single-valued.  This helper unwraps them.
        """
        if not isinstance(doc, Mapping):
            return None

        def _first(key: str) -> Optional[str]:
            v = doc.get(key)
            if v is None:
                return None
            if isinstance(v, list):
                return v[0] if v else None
            return v

        def _all(key: str) -> List[str]:
            v = doc.get(key)
            if v is None:
                return []
            if isinstance(v, list):
                return [str(x) for x in v if x]
            return [str(v)]

        title = (_first("dc:title") or _first("dctitle") or "").strip()
        if not title:
            # Fall back to the "label" field some repositories expose.
            label = _first("label")
            if not label:
                return None
            title = label.strip()

        authors: List[str] = []
        for a in _all("dc:creator") + _all("author"):
            if a and a not in authors:
                authors.append(a)

        abstract = (_first("dct:description") or _first("dc:description") or "").strip()

        doi = _first("dc:identifier") or _first("doi")
        # If dc:identifier looks like a DOI URL, extract the DOI.
        if doi and isinstance(doi, str):
            for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
                if doi.lower().startswith(prefix):
                    doi = doi[len(prefix):]
                    break

        # Some BASE records store the DOI separately as ``doi``.
        doi = _first("doi") or doi

        year_str = _first("dc:date") or _first("dctdate") or _first("year")
        year: Optional[int] = None
        if isinstance(year_str, str):
            import re
            m = re.search(r"(20\d{2}|19\d{2})", year_str)
            if m:
                year = int(m.group(1))

        # Repository name (the source hosting the document).
        repository = (
            _first("cdl:repository_name")
            or _first("repository_name")
            or _first("inst")
        )

        # Dewey Decimal Classification (DDC).
        ddc_list = _all("dc:subject") or _all("ddc")
        ddc = ddc_list[0] if ddc_list else None

        url = _first("dc:identifier") or _first("url")
        pdf_url = None
        links = _all("link")
        for link in links:
            if isinstance(link, str) and link.lower().endswith(".pdf"):
                pdf_url = link
                break
        if not pdf_url and url and isinstance(url, str) and url.lower().endswith(".pdf"):
            pdf_url = url

        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            year=year,
            doi=doi,
            url=url,
            source=self.name,
            citations_count=None,
            references=[],
            keywords=ddc_list,
            pdf_url=pdf_url,
            issn=_first("dc:source") or None,
            isbn=_first("dc:identifier_isbn") or None,
            publisher=_first("dc:publisher") or None,
            journal=repository,
            volume=None,
            issue=None,
            pages=None,
            language=_first("dc:language") or None,
            paper_type=_first("dc:type") or _first("type") or None,
            fields_of_study=[],
            raw={"ddc": ddc, "repository": repository, **dict(doc)},
        )


__all__ = ["BASEScraper"]
