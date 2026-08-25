"""
core_scraper.py
===============

Scraper for the **CORE** aggregator API v3
(``https://api.core.ac.uk/v3/``).

CORE is the world's largest aggregator of open-access research
papers, indexing metadata *and* full-text content from thousands of
repositories worldwide.  An API key is required and can be obtained
from **https://core.ac.uk/services/api** (free academic tier).

Capabilities
------------
* :meth:`search` — full-text or metadata search across CORE's
  open-access corpus, with optional year-range, repository and
  document-type filters.  Pass ``fulltext=True`` (via ``type``) to
  execute a full-text query (CORE supports both modes).
* :meth:`fetch_by_id` — fetch a single work by its CORE ID.
* :meth:`fetch_works` — list works belonging to a specific
  repository.

Authentication
--------------
The API key is supplied as an HTTP ``Authorization: Bearer <key>``
header on every request.  Resolution order:

  1. ``api_key`` constructor argument.
  2. ``CORE_API_KEY`` environment variable.
  3. ``config.settings.core_api_key`` (lazy import).

Rate limits
-----------
CORE allows ~10 requests/second on standard keys; we default to
``5`` r/s to be safe.
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


class COREScraper(BaseScraper):
    """Scraper for the CORE API v3 (open-access aggregator)."""

    BASE_URL = "https://api.core.ac.uk/v3"
    SOURCE_NAME = "core"

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        api_key: Optional[str] = None,
        rate_limit: float = 5.0,
        cache: Optional[Any] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: Optional[str] = None,
    ) -> None:
        """Initialize a :class:`COREScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            api_key: CORE API key.  Falls back to ``CORE_API_KEY``
                env var or ``config.settings.core_api_key``.
            rate_limit: Maximum requests per second (default ``5``).
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
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        repository: Optional[str] = None,
        type: Optional[str] = None,
        fulltext: bool = False,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search CORE's open-access corpus for ``query``.

        Args:
            query: Free-text search string.
            max_results: Maximum number of papers to return.
            year_from: Inclusive publication-year lower bound.
            year_to: Inclusive publication-year upper bound.
            repository: CORE repository ID (numeric string) —
                restricts results to the given repository.
            type: Document-type filter.  Accepts ``"publication"``,
                ``"dataset"``, ``"software"`` (case-insensitive).
            fulltext: If ``True``, perform a full-text search
                instead of metadata-only.
            **kwargs: Reserved for future use.

        Returns:
            A populated :class:`ScraperResult`.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        errors: List[str] = []

        if not self.api_key:
            err = (
                "CORE API key missing — register at "
                "https://core.ac.uk/services/api and set CORE_API_KEY."
            )
            self.logger.warning(err)
            errors.append(err)
            result.errors = errors
            result.elapsed_ms = self._now_ms() - start_ms
            return result

        endpoint = f"{self.BASE_URL}/search/works"
        # CORE v3 expects a JSON POST body.
        q_parts: List[str] = []
        if query and query.strip():
            # CORE uses Lucene-like syntax; quoted strings preserve multi-word phrases.
            if " " in query.strip() and not query.strip().startswith('"'):
                q_parts.append(f'title:(""{query.strip()}") OR abstract:(""{query.strip()}") OR fullText:(""{query.strip()}")')
            else:
                q_parts.append(query.strip())
        else:
            q_parts.append("*")

        if year_from or year_to:
            lo = year_from if year_from else 1900
            hi = year_to if year_to else 2100
            q_parts.append(f"year_published:[{lo} TO {hi}]")
        if repository:
            q_parts.append(f"repository.id:{repository}")
        if type:
            t = type.strip().lower()
            if t in ("publication", "dataset", "software"):
                q_parts.append(f"documentType:{t}")
        body: Dict[str, Any] = {
            "q": " AND ".join(q_parts) if len(q_parts) > 1 else q_parts[0],
            "limit": min(max_results, 100),
            "offset": 0,
        }
        if fulltext:
            # Hint CORE to also search the full text.
            body["search_type"] = "fullText"

        headers = self._auth_headers()
        headers["Content-Type"] = "application/json"

        raw_response: Dict[str, Any] = {}
        try:
            cache_key = self._cache_key("core", "search", body["q"], body["limit"], body["offset"])
            resp = self._make_request(
                "POST", endpoint, json_body=body, headers=headers, cache_key=cache_key
            )
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("CORE response is not a JSON object")
            raw_response = data

            total = data.get("totalHits") or data.get("count") or 0
            try:
                result.total_results = int(total)
            except (TypeError, ValueError):
                result.total_results = 0

            results = data.get("results") or []
            for record in results:
                paper = self._parse_work(record)
                if paper is not None:
                    result.papers.append(paper)
                    if len(result.papers) >= max_results:
                        break

            # Pagination via offset.
            offset = body["limit"]
            while (
                len(result.papers) < max_results
                and offset < result.total_results
            ):
                body["offset"] = offset
                try:
                    cache_key = self._cache_key(
                        "core", "search", body["q"], body["limit"], offset
                    )
                    resp = self._make_request(
                        "POST", endpoint, json_body=body, headers=headers, cache_key=cache_key
                    )
                    data = resp.json()
                except Exception as exc:  # noqa: BLE001
                    err = f"CORE pagination error: {exc}"
                    errors.append(err)
                    self.logger.warning(err)
                    break
                results = data.get("results") or []
                if not results:
                    break
                for record in results:
                    if len(result.papers) >= max_results:
                        break
                    paper = self._parse_work(record)
                    if paper is not None:
                        result.papers.append(paper)
                offset += body["limit"]

        except Exception as exc:  # noqa: BLE001
            err = f"CORE request failed: {exc}"
            errors.append(err)
            self.logger.error(err, exc_info=True)

        result.raw_response = raw_response
        result.errors = errors
        result.timestamp = datetime.now(timezone.utc).isoformat()
        result.elapsed_ms = self._now_ms() - start_ms
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single CORE work by its CORE ID.

        Args:
            paper_id: The CORE work ID (numeric string).

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        if not paper_id:
            return None
        endpoint = f"{self.BASE_URL}/works/{str(paper_id).strip()}"
        try:
            cache_key = self._cache_key("core", "id", paper_id)
            resp = self._make_request(
                "GET", endpoint, headers=self._auth_headers(), cache_key=cache_key
            )
            data = resp.json()
            if not isinstance(data, dict):
                return None
            return self._parse_work(data)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("CORE fetch_by_id(%s) failed: %s", paper_id, exc)
            return None

    def fetch_works(self, repository_id: str, max_results: int = 50) -> ScraperResult:
        """List works belonging to a CORE repository.

        Args:
            repository_id: CORE repository ID (numeric string).
            max_results: Maximum number of papers to return.

        Returns:
            A :class:`ScraperResult`.
        """
        return self.search(
            query="*",
            max_results=max_results,
            repository=repository_id,
        )

    # -- internal helpers ------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        """Return the ``Authorization: Bearer <key>`` header."""
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def _resolve_api_key(self) -> Optional[str]:
        """Resolve the CORE API key from env var or settings."""
        env = os.environ.get("CORE_API_KEY")
        if env:
            return env
        settings = _load_settings()
        if settings is None:
            return None
        for attr in ("core_api_key", "core_ac_uk_api_key"):
            value = getattr(settings, attr, None)
            if value:
                return value
        return None

    def _parse_work(self, record: Mapping[str, Any]) -> Optional[Paper]:
        """Convert a CORE work JSON record into a :class:`Paper`."""
        if not isinstance(record, Mapping):
            return None
        title = (record.get("title") or "").strip()
        if not title:
            return None

        authors: List[str] = []
        for a in record.get("authors", []) or []:
            if isinstance(a, Mapping):
                name = a.get("name") or ""
                if name:
                    authors.append(str(name))
            elif isinstance(a, str) and a:
                authors.append(a)

        abstract = (record.get("abstract") or "").strip()
        # CORE sometimes returns a list of abstracts; join them.
        if not abstract and isinstance(record.get("abstracts"), list):
            abstract = " ".join(
                a if isinstance(a, str) else (a.get("abstract") or "")
                for a in record["abstracts"]
                if a
            ).strip()

        doi = record.get("doi") or record.get("doi_string") or None
        year: Optional[int] = None
        y = record.get("year_published") or record.get("year")
        if isinstance(y, int):
            year = y
        elif isinstance(y, str) and y.isdigit():
            year = int(y)

        # CORE's download URL points to the publisher-hosted PDF or
        # to the full-text stored in CORE itself.
        download_url = (
            record.get("download_url")
            or record.get("source_fulltext_urls")
            or None
        )
        if isinstance(download_url, list):
            download_url = download_url[0] if download_url else None
        if isinstance(download_url, Mapping):
            download_url = download_url.get("url")

        full_text = record.get("fullText") or None
        repository = None
        repo_block = record.get("repository") or {}
        if isinstance(repo_block, Mapping):
            repository = repo_block.get("name")
        elif isinstance(repo_block, str):
            repository = repo_block

        # CORE sometimes provides a list of "source" repositories.
        if not repository:
            sources = record.get("sources") or []
            if isinstance(sources, list) and sources:
                first = sources[0]
                if isinstance(first, Mapping):
                    repository = first.get("name")

        raw = dict(record)
        if full_text:
            raw["full_text"] = full_text[:5000]  # truncate to keep memory sane

        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            year=year,
            doi=doi,
            url=record.get("url") or download_url,
            source=self.name,
            citations_count=None,
            references=[],
            keywords=[],
            pdf_url=download_url,
            issn=None,
            isbn=None,
            publisher=record.get("publisher") or None,
            journal=record.get("journal") or repository,
            volume=record.get("volume") or None,
            issue=record.get("issue") or None,
            pages=record.get("start_page") or None,
            language=record.get("language", {}).get("code") if isinstance(record.get("language"), Mapping) else record.get("language"),
            paper_type=record.get("documentType") or record.get("type") or None,
            fields_of_study=[],
            raw=raw,
        )


__all__ = ["COREScraper"]
