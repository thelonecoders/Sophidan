"""
springer_scraper.py
===================

Scraper for the Springer Nature Metadata API
(``https://api.springernature.com/meta/v2/json``).

Springer Nature exposes a free (registration-required) metadata API for
the full corpus of Springer-hosted journal articles, book chapters and
conference proceedings — covering *Nature*, *Springer*, *BioMed
Central*, *Palgrave Macmillan* and *Apress* imprints.

Capabilities
------------
* :meth:`search` — full-text search across titles, abstracts and
  metadata, with optional filters for publication-year range,
  journal name, content type and open-access status.
* :meth:`fetch_by_doi` — single-record lookup by DOI.
* :meth:`fetch_by_id` — single-record lookup by Springer PII
  (Publisher Item Identifier, e.g. ``s00521-023-08534-4``).

Authentication
--------------
A free API key can be obtained from
**https://dev.springernature.com**.  The key is supplied as the
``api_key`` query parameter on every request.  The scraper accepts
the key via:

  1. The ``api_key`` constructor argument (highest precedence).
  2. The ``SPRINGER_API_KEY`` environment variable.
  3. ``config.settings.springer_api_key`` (lazy import, if the
     project's central settings object is available).

Without a key, the scraper is non-functional and ``search`` will
return an empty :class:`ScraperResult` with an explanatory error.

Rate limits
-----------
Springer enforces ~25 requests/second on standard keys; we default
to ``5`` r/s to be polite.
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
    """Lazily import :mod:`config.settings` and return the module.

    Returns ``None`` when the module is unavailable (headless / unit
    tests) so the scraper can fall back to env-var resolution.
    """
    try:  # pragma: no cover - depends on sibling module being built
        from config import settings  # type: ignore
        return settings
    except Exception:  # noqa: BLE001
        return None


class SpringerScraper(BaseScraper):
    """Scraper for the Springer Nature Metadata API v2 (JSON)."""

    BASE_URL = "https://api.springernature.com/meta/v2/json"
    SOURCE_NAME = "springer"

    # Recognised ``type`` filter values exposed by the API.
    _VALID_TYPES = {"Journal", "Paper", "Chapter", "Book", "Proceeding", "Protocol"}

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
        """Initialize a :class:`SpringerScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            api_key: Springer Nature API key.  If ``None``, the
                scraper resolves the key from the
                ``SPRINGER_API_KEY`` env var or
                ``config.settings.springer_api_key`` (lazy import).
            rate_limit: Requests per second (default ``5``).
            cache: Optional response cache.
            timeout: Per-request timeout in seconds.
            max_retries: Maximum retry attempts on transient errors.
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
        journal: Optional[str] = None,
        type: Optional[str] = None,
        openaccess: Optional[bool] = None,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search Springer Nature for records matching ``query``.

        Args:
            query: Free-text search string (uses Springer's
                ``q`` parameter; supports field qualifiers like
                ``title:"machine learning"`` and boolean ``AND`` /
                ``OR`` operators).
            max_results: Maximum number of papers to return (capped
                at 100 per page).
            year_from: Inclusive publication-year lower bound.
            year_to: Inclusive publication-year upper bound.
            journal: Journal name (Springer's ``journal:`` filter).
            type: Content type filter — one of ``"Journal"``,
                ``"Paper"``, ``"Chapter"``, ``"Book"``,
                ``"Proceeding"``, ``"Protocol"``.
            openaccess: If ``True`` restricts to open-access content;
                ``False`` to closed-access; ``None`` for no filter.
            **kwargs: Reserved for future use.

        Returns:
            A populated :class:`ScraperResult`.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        errors: List[str] = []

        if not self.api_key:
            err = (
                "Springer API key missing — register at "
                "https://dev.springernature.com and set SPRINGER_API_KEY."
            )
            self.logger.warning(err)
            errors.append(err)
            result.errors = errors
            result.elapsed_ms = self._now_ms() - start_ms
            return result

        # Build the composite ``q`` value.
        q_parts: List[str] = []
        if query and query.strip():
            q_parts.append(query.strip())
        if year_from or year_to:
            lo = year_from if year_from else 1900
            hi = year_to if year_to else 2100
            q_parts.append(f"date:{lo}-{hi}")
        if journal:
            q_parts.append(f'journal:"{journal.strip()}"')
        if type and type in self._VALID_TYPES:
            q_parts.append(f"type:{type}")
        if openaccess is not None:
            q_parts.append("openaccess:true" if openaccess else "openaccess:false")
        composite_q = " AND ".join(q_parts) if q_parts else "*"

        params: Dict[str, Any] = {
            "api_key": self.api_key,
            "q": composite_q,
            "p": 1,                          # page number (1-based)
            "p_s": min(max_results, 100),    # page size
        }

        raw_response: Dict[str, Any] = {}
        try:
            cache_key = self._cache_key(
                "springer", "search", composite_q, params["p"], params["p_s"]
            )
            resp = self._make_request(
                "GET", self.BASE_URL, params=params, cache_key=cache_key
            )
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("Springer response is not a JSON object")
            raw_response = data

            total_str = data.get("total") or data.get("result", [{}])[0].get("total", "0")
            try:
                total_results = int(str(total_str).replace(",", ""))
            except (TypeError, ValueError):
                total_results = 0
            result.total_results = total_results

            records = data.get("records") or []
            for record in records[:max_results]:
                paper = self._parse_record(record)
                if paper is not None:
                    result.papers.append(paper)

            # Follow-on pages if needed.
            page = 1
            while len(result.papers) < max_results and len(records) >= params["p_s"]:
                page += 1
                params["p"] = page
                try:
                    cache_key = self._cache_key(
                        "springer", "search", composite_q, page, params["p_s"]
                    )
                    resp = self._make_request(
                        "GET", self.BASE_URL, params=params, cache_key=cache_key
                    )
                    data = resp.json()
                    records = data.get("records") or []
                except Exception as exc:  # noqa: BLE001
                    err = f"Pagination error at page {page}: {exc}"
                    errors.append(err)
                    self.logger.warning(err)
                    break
                for record in records:
                    if len(result.papers) >= max_results:
                        break
                    paper = self._parse_record(record)
                    if paper is not None:
                        result.papers.append(paper)

        except Exception as exc:  # noqa: BLE001
            err = f"Springer request failed: {exc}"
            errors.append(err)
            self.logger.error(err, exc_info=True)

        result.raw_response = raw_response
        result.errors = errors
        result.timestamp = datetime.now(timezone.utc).isoformat()
        result.elapsed_ms = self._now_ms() - start_ms
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single Springer record by its PII.

        The Springer PII (Publisher Item Identifier) is a string like
        ``s00521-023-08534-4``.  The DOI prefix can also be supplied;
        the method delegates to :meth:`fetch_by_doi` in that case.

        Args:
            paper_id: Springer PII or DOI.

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        if not paper_id:
            return None
        pid = paper_id.strip()
        if pid.lower().startswith("10.") and "/" in pid:
            return self.fetch_by_doi(pid)
        # Use the PII as the q filter.
        result = self.search(
            query=f'pii:"{pid}"',
            max_results=1,
        )
        if result.papers:
            return result.papers[0]
        return None

    def fetch_by_doi(self, doi: str) -> Optional[Paper]:
        """Fetch a single Springer record by DOI.

        Args:
            doi: The DOI string (with or without a ``doi:`` /
                ``https://doi.org/`` prefix).

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        if not doi:
            return None
        cleaned = self._clean_doi(doi)
        result = self.search(query=f'doi:"{cleaned}"', max_results=1)
        if result.papers:
            return result.papers[0]
        return None

    # -- internal helpers ------------------------------------------------

    def _resolve_api_key(self) -> Optional[str]:
        """Resolve the Springer API key from env var or settings."""
        env = os.environ.get("SPRINGER_API_KEY")
        if env:
            return env
        settings = _load_settings()
        if settings is None:
            return None
        for attr in ("springer_api_key", "springer_nature_api_key"):
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

    def _parse_record(self, record: Mapping[str, Any]) -> Optional[Paper]:
        """Convert a Springer JSON record into a :class:`Paper`."""
        if not isinstance(record, Mapping):
            return None
        title = (record.get("title") or "").strip()
        if not title:
            # Some records store the title under "publicationName" or
            # "chapterTitle"; bail out if none of them is present.
            title = (record.get("publicationName") or "").strip()
            if not title:
                return None

        # Authors — may be a list of dicts with a ``creator`` key.
        authors: List[str] = []
        creators = record.get("creators") or []
        if isinstance(creators, list):
            for c in creators:
                if isinstance(c, Mapping):
                    name = c.get("creator") or ""
                    if name:
                        authors.append(str(name))
                elif isinstance(c, str) and c:
                    authors.append(c)

        abstract = (record.get("abstract") or record.get("abstract_p") or "").strip()
        # Strip any leading "Abstract" preamble tag Springer sometimes includes.
        if abstract.lower().startswith("abstract"):
            abstract = abstract[len("abstract"):].lstrip(": \n\t")

        doi = record.get("doi") or None
        url = record.get("url", [None])
        if isinstance(url, list) and url:
            first = url[0]
            if isinstance(first, Mapping):
                url_value: Optional[str] = first.get("value")
            else:
                url_value = str(first) if first else None
        elif isinstance(url, Mapping):
            url_value = url.get("value")
        elif isinstance(url, str):
            url_value = url
        else:
            url_value = None

        # Publication date is normally ``YYYY-MM-DD``; we keep the year.
        year: Optional[int] = None
        pubdate = record.get("publicationDate") or record.get("publicationdate")
        if isinstance(pubdate, str) and pubdate:
            try:
                year = int(pubdate[:4])
            except ValueError:
                year = None

        journal = record.get("publicationName") or record.get("journal") or None
        publisher = record.get("publisher") or None
        issn = record.get("issn") or None
        isbn = record.get("isbn") or None
        volume = record.get("volume") or None
        issue = record.get("number") or record.get("issue") or None
        starting_page = record.get("startingPage")
        ending_page = record.get("endingPage")
        pages: Optional[str] = None
        if starting_page and ending_page:
            pages = f"{starting_page}-{ending_page}"
        elif starting_page:
            pages = str(starting_page)

        # Open-access indicator: Springer exposes ``openaccess`` as
        # ``"true"``/``"false"`` string or boolean; ``url`` may contain
        # a ``pdf`` link.
        oa_flag = record.get("openaccess")
        is_oa = False
        if isinstance(oa_flag, bool):
            is_oa = oa_flag
        elif isinstance(oa_flag, str):
            is_oa = oa_flag.strip().lower() == "true"

        pdf_url: Optional[str] = None
        url_list = record.get("url") or []
        if isinstance(url_list, list):
            for entry in url_list:
                if isinstance(entry, Mapping):
                    fmt = (entry.get("format") or "").lower()
                    if "pdf" in fmt:
                        pdf_url = entry.get("value")
                        break
                elif isinstance(entry, str) and entry.lower().endswith(".pdf"):
                    pdf_url = entry
                    break

        # If we couldn't find an explicit PDF URL but the record is
        # open access, fall back to Springer's document landing page.
        if is_oa and not pdf_url and doi:
            pdf_url = f"https://link.springer.com/article/{doi}"

        keywords: List[str] = []
        subjects = record.get("subject") or record.get("subjects")
        if isinstance(subjects, list):
            keywords = [str(s) for s in subjects if s]
        elif isinstance(subjects, str) and subjects:
            keywords = [subjects]

        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            year=year,
            doi=doi,
            url=url_value,
            source=self.name,
            citations_count=None,
            references=[],
            keywords=keywords,
            pdf_url=pdf_url,
            issn=issn,
            isbn=isbn,
            publisher=publisher,
            journal=journal,
            volume=str(volume) if volume else None,
            issue=str(issue) if issue else None,
            pages=pages,
            language=record.get("language") or None,
            paper_type=record.get("contentType") or None,
            fields_of_study=[],
            raw=dict(record),
        )


__all__ = ["SpringerScraper"]
