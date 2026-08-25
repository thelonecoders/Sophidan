"""
ieee_scraper.py
===============

Scraper for the IEEE Xplore Metadata Search API
(``https://ieeexploreapi.ieee.org/api/v1/search/articles``).

IEEE Xplore hosts metadata for IEEE-published journals, magazines,
conference proceedings, standards, books and courses.  Access to the
metadata API requires an API key obtainable from
**https://developer.ieee.org** (free registration).

Capabilities
------------
* :meth:`search` — full-text search with optional filters for
  article type, open-access flag and publication year.
* :meth:`fetch_by_id` — single-record lookup by IEEE article ID.
* :meth:`fetch_by_doi` — single-record lookup by DOI.

Authentication
--------------
The API key is supplied via the ``apikey`` query parameter on every
request.  Resolution order:

  1. ``api_key`` constructor argument.
  2. ``IEEE_API_KEY`` environment variable.
  3. ``config.settings.ieee_api_key`` (lazy import).

Rate limits
-----------
IEEE enforces ~200 calls/day on the free tier (subject to change).
The scraper defaults to ``1`` request per second to be polite.
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


class IEEEXploreScraper(BaseScraper):
    """Scraper for the IEEE Xplore Metadata Search API."""

    BASE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
    SOURCE_NAME = "ieee"

    # Article-type tokens accepted by IEEE's ``article_type`` parameter.
    _VALID_ARTICLE_TYPES = {
        "Conferences",
        "Journals",
        "Magazines",
        "Early Access",
        "Standards",
        "Books",
        "Courses",
    }

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
        """Initialize an :class:`IEEEXploreScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            api_key: IEEE API key.  Falls back to the
                ``IEEE_API_KEY`` env var or
                ``config.settings.ieee_api_key`` when not provided.
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
        article_type: Optional[str] = None,
        open_access: Optional[bool] = None,
        publication_year: Optional[int] = None,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search IEEE Xplore for articles matching ``query``.

        Args:
            query: Free-text search string.
            max_results: Maximum number of records to return (capped
                at 200 per IEEE's per-page limit).
            article_type: Optional filter — one of ``"Conferences"``,
                ``"Journals"``, ``"Magazines"``, ``"Early Access"``,
                ``"Standards"``, ``"Books"``, ``"Courses"``.
            open_access: If ``True`` returns only open-access content;
                ``False`` for closed; ``None`` for no filter.
            publication_year: 4-digit publication year filter.
            **kwargs: Reserved for future use.

        Returns:
            A populated :class:`ScraperResult`.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        errors: List[str] = []

        if not self.api_key:
            err = (
                "IEEE API key missing — register at "
                "https://developer.ieee.org and set IEEE_API_KEY."
            )
            self.logger.warning(err)
            errors.append(err)
            result.errors = errors
            result.elapsed_ms = self._now_ms() - start_ms
            return result

        params: Dict[str, Any] = {
            "apikey": self.api_key,
            "querytext": query,
            "max_records": min(max_results, 200),
            "start_record": 1,
            "sort_field": "relevance",
            "sort_order": "desc",
        }
        if article_type:
            if article_type not in self._VALID_ARTICLE_TYPES:
                self.logger.warning(
                    "Unknown IEEE article_type=%r; expected one of %s",
                    article_type, sorted(self._VALID_ARTICLE_TYPES),
                )
            else:
                params["article_type"] = article_type
        if open_access is not None:
            params["open_access"] = "yes" if open_access else "no"
        if publication_year:
            params["publication_year"] = int(publication_year)

        raw_response: Dict[str, Any] = {}
        try:
            cache_key = self._cache_key(
                "ieee", "search", query, params.get("article_type"),
                params.get("publication_year"), params["start_record"],
            )
            resp = self._make_request(
                "GET", self.BASE_URL, params=params, cache_key=cache_key
            )
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("IEEE response is not a JSON object")
            raw_response = data

            total = data.get("total_records", 0)
            try:
                result.total_results = int(total)
            except (TypeError, ValueError):
                result.total_results = 0

            for record in data.get("articles", []) or []:
                paper = self._parse_article(record)
                if paper is not None:
                    result.papers.append(paper)
                    if len(result.papers) >= max_results:
                        break

            # IEEE's pagination cursor: continue fetching if there's
            # more data and we still need results.
            start_record = params["start_record"] + params["max_records"]
            while (
                len(result.papers) < max_results
                and start_record < result.total_results
            ):
                params["start_record"] = start_record
                try:
                    cache_key = self._cache_key(
                        "ieee", "search", query, params.get("article_type"),
                        params.get("publication_year"), start_record,
                    )
                    resp = self._make_request(
                        "GET", self.BASE_URL, params=params, cache_key=cache_key
                    )
                    data = resp.json()
                except Exception as exc:  # noqa: BLE001
                    err = f"IEEE pagination error: {exc}"
                    errors.append(err)
                    self.logger.warning(err)
                    break
                for record in data.get("articles", []) or []:
                    if len(result.papers) >= max_results:
                        break
                    paper = self._parse_article(record)
                    if paper is not None:
                        result.papers.append(paper)
                start_record += params["max_records"]

        except Exception as exc:  # noqa: BLE001
            err = f"IEEE request failed: {exc}"
            errors.append(err)
            self.logger.error(err, exc_info=True)

        result.raw_response = raw_response
        result.errors = errors
        result.timestamp = datetime.now(timezone.utc).isoformat()
        result.elapsed_ms = self._now_ms() - start_ms
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single IEEE article by its IEEE article ID.

        Args:
            paper_id: IEEE article ID (numeric string).

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        if not paper_id:
            return None
        params: Dict[str, Any] = {
            "apikey": self.api_key,
            "article_number": str(paper_id).strip(),
            "max_records": 1,
        }
        try:
            cache_key = self._cache_key("ieee", "id", paper_id)
            resp = self._make_request(
                "GET", self.BASE_URL, params=params, cache_key=cache_key
            )
            data = resp.json()
            articles = data.get("articles", []) if isinstance(data, dict) else []
            if not articles:
                return None
            return self._parse_article(articles[0])
        except Exception as exc:  # noqa: BLE001
            self.logger.error("IEEE fetch_by_id(%s) failed: %s", paper_id, exc)
            return None

    def fetch_by_doi(self, doi: str) -> Optional[Paper]:
        """Fetch a single IEEE article by DOI.

        Args:
            doi: The DOI string (with or without a ``doi:`` /
                ``https://doi.org/`` prefix).

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        cleaned = self._clean_doi(doi)
        if not cleaned:
            return None
        params: Dict[str, Any] = {
            "apikey": self.api_key,
            "doi": cleaned,
            "max_records": 1,
        }
        try:
            cache_key = self._cache_key("ieee", "doi", cleaned)
            resp = self._make_request(
                "GET", self.BASE_URL, params=params, cache_key=cache_key
            )
            data = resp.json()
            articles = data.get("articles", []) if isinstance(data, dict) else []
            if not articles:
                return None
            return self._parse_article(articles[0])
        except Exception as exc:  # noqa: BLE001
            self.logger.error("IEEE fetch_by_doi(%s) failed: %s", doi, exc)
            return None

    # -- internal helpers ------------------------------------------------

    def _resolve_api_key(self) -> Optional[str]:
        """Resolve the IEEE API key from env var or settings."""
        env = os.environ.get("IEEE_API_KEY")
        if env:
            return env
        settings = _load_settings()
        if settings is None:
            return None
        for attr in ("ieee_api_key", "ieeexplore_api_key"):
            value = getattr(settings, attr, None)
            if value:
                return value
        return None

    @staticmethod
    def _clean_doi(doi: str) -> str:
        """Strip ``doi:`` / ``https://doi.org/`` prefixes from ``doi``."""
        d = (doi or "").strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
            if d.lower().startswith(prefix):
                d = d[len(prefix):]
                break
        return d.strip()

    def _parse_article(self, record: Mapping[str, Any]) -> Optional[Paper]:
        """Convert a single IEEE article JSON record to :class:`Paper`."""
        if not isinstance(record, Mapping):
            return None
        title = (record.get("title") or "").strip()
        if not title:
            return None

        # IEEE returns ``authors.authors`` as a list of dicts with
        # ``full_name`` + ``affiliation`` keys.
        authors: List[str] = []
        affiliations: List[str] = []
        authors_block = record.get("authors", {}).get("authors", [])
        if isinstance(authors_block, list):
            for a in authors_block:
                if not isinstance(a, Mapping):
                    continue
                name = a.get("full_name") or ""
                if name:
                    authors.append(str(name))
                aff = a.get("affiliation") or ""
                if aff:
                    affiliations.append(str(aff))

        abstract = (record.get("abstract") or "").strip()
        doi = record.get("doi") or None
        article_id = record.get("article_number") or None
        url = record.get("html_url") or record.get("pdf_url") or None

        # Publication year — IEEE returns it under various keys.
        year: Optional[int] = None
        for key in ("publication_year", "year", "conference_year"):
            value = record.get(key)
            if isinstance(value, int):
                year = value
                break
            if isinstance(value, str) and value.isdigit():
                year = int(value)
                break

        # Venue — prefer conference name; fall back to journal.
        conference = record.get("conference_name") or None
        if isinstance(conference, Mapping):  # defensive
            conference = conference.get("name")
        journal = (
            record.get("display_publishing_org")
            or record.get("publication_title")
            or record.get("journal")
            or conference
        )
        # ``publication_title`` is the actual IEEE venue name.
        venue = record.get("publication_title") or journal or None

        # Open-access PDF link (when available).
        pdf_url = record.get("pdf_url") or None
        if not pdf_url and record.get("access_type") == "OPEN_ACCESS":
            # IEEE sometimes returns only the html_url for OA papers.
            pdf_url = url

        # Raw fields preserved for downstream use.
        raw = dict(record)
        raw["affiliations"] = affiliations
        raw["ieee_article_id"] = article_id

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
            keywords=[],
            pdf_url=pdf_url,
            issn=record.get("issn") or None,
            isbn=record.get("isbn") or None,
            publisher=record.get("publisher") or None,
            journal=venue,
            volume=record.get("volume") or None,
            issue=record.get("issue") or None,
            pages=(record.get("start_page") or record.get("pages")) or None,
            language=record.get("language") or None,
            paper_type=record.get("content_type") or None,
            fields_of_study=[],
            raw=raw,
        )


__all__ = ["IEEEXploreScraper"]
