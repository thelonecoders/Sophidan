"""
sciopen_scraper.py
==================

Scraper for the **Sciopen.com** open-access aggregator.

This module is the legal alternative to Sci-Hub.  It searches a
catalog of **only open-access** papers indexed from various OA
repositories (DOAJ, PubMed Central OA subset, arXiv, etc.).  No API
key is required; the scraper simply scrapes the public search
HTML using ``beautifulsoup4`` + ``lxml``.

.. note::
    The Sciopen.com service is a third-party OA aggregator and is
    not affiliated with the Academic Research Suite.  Operators
    should verify the service's ToS before deploying at scale.
    This scraper is intentionally conservative: it throttles to
    ~1 req / 3s, identifies itself with a descriptive User-Agent
    and gracefully returns empty results when blocked.

Capabilities
------------
* :meth:`search` — full-text search for open-access papers.
* :meth:`fetch_by_id` — single-record lookup by DOI (uses the
  site's ``/doi/`` path; falls back to Crossref when blocked).
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from ._compat import BaseScraper, Paper, ScraperResult, get_logger

logger = logging.getLogger(__name__)


def _import_bs4() -> Any:
    """Lazy import of BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
        return BeautifulSoup
    except Exception:  # noqa: BLE001
        return None


_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")


class SciOpenScraper(BaseScraper):
    """Scraper for the Sciopen.com open-access aggregator.

    Only used for **open-access** content.  Use Unpaywall, CORE or
    BASE if you need programmatic access to OA metadata; this
    scraper is intended as a discovery tool when an end-user
    searches Sciopen directly through the UI.
    """

    BASE_URL = "https://www.sciopen.com"
    SEARCH_PATH = "/search"
    SOURCE_NAME = "sciopen"

    DEFAULT_USER_AGENT = (
        "AcademicResearchSuite/2.0 "
        "(Sciopen OA scraper; +https://github.com/academic-research-suite; "
        "academic research, OA only)"
    )

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        rate_limit: float = 0.33,
        cache: Optional[Any] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: Optional[str] = None,
        crossref_scraper: Optional[Any] = None,
    ) -> None:
        """Initialize a :class:`SciOpenScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            rate_limit: Maximum requests per second (default
                ``0.33`` ≈ 1 req / 3 s — polite).
            cache: Optional response cache.
            timeout: Per-request timeout in seconds.
            max_retries: Maximum retry attempts.
            user_agent: Optional User-Agent override.
            crossref_scraper: Optional pre-built
                :class:`CrossrefScraper` instance used by
                :meth:`fetch_by_id` as a fallback.
        """
        super().__init__(
            proxy_manager=proxy_manager,
            rate_limit=rate_limit,
            cache=cache,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent or self.DEFAULT_USER_AGENT,
        )
        self.logger: logging.Logger = get_logger(__name__)
        self._crossref = crossref_scraper

    # -- BaseScraper interface -------------------------------------------

    def search(
        self,
        query: str,
        max_results: int = 50,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search Sciopen for open-access papers matching ``query``.

        Args:
            query: Free-text search string.
            max_results: Maximum number of papers to return.
            **kwargs: Reserved for future use.

        Returns:
            A :class:`ScraperResult`.  Empty (with a single non-fatal
            error) when blocked or when bs4 is unavailable.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        errors: List[str] = []
        BeautifulSoup = _import_bs4()
        if BeautifulSoup is None:
            errors.append(
                "beautifulsoup4 is required for Sciopen scraping but is "
                "not installed."
            )
            result.errors = errors
            result.elapsed_ms = self._now_ms() - start_ms
            return result

        url = f"{self.BASE_URL}{self.SEARCH_PATH}"
        params: Dict[str, Any] = {"q": query, "page": 1, "pageSize": 20}
        raw_pages: List[str] = []

        try:
            while len(result.papers) < max_results:
                cache_key = self._cache_key(
                    "sciopen", "search", query, params["page"]
                )
                resp = self._make_request(
                    "GET", url, params=params, cache_key=cache_key,
                    headers={"Accept": "text/html,application/xhtml+xml"},
                )
                html = resp.text or ""
                raw_pages.append(html)

                if self._looks_blocked(html):
                    errors.append(
                        f"Sciopen returned a blocked / empty response at "
                        f"page {params['page']}; returning partial results."
                    )
                    break

                soup = BeautifulSoup(html, "lxml")
                items = soup.select(
                    "div.search-result-item, div.article-item, li.search-result"
                )
                if not items:
                    break
                for item in items:
                    if len(result.papers) >= max_results:
                        break
                    paper = self._parse_item(item)
                    if paper is not None:
                        result.papers.append(paper)
                params["page"] += 1
                # Stop after a sane number of pages even if more exist.
                if params["page"] > 10:
                    break
        except Exception as exc:  # noqa: BLE001
            err = f"Sciopen request failed: {exc}"
            errors.append(err)
            self.logger.error(err, exc_info=True)

        result.raw_response = {"pages": raw_pages}
        result.errors = errors
        result.timestamp = datetime.now(timezone.utc).isoformat()
        result.elapsed_ms = self._now_ms() - start_ms
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single Sciopen paper by DOI.

        Tries the Sciopen landing page first; falls back to Crossref
        if blocked.

        Args:
            paper_id: The DOI string.

        Returns:
            A :class:`Paper` or ``None``.
        """
        cleaned = self._clean_doi(paper_id)
        if not cleaned:
            return None
        url = f"{self.BASE_URL}/doi/{cleaned}"
        try:
            cache_key = self._cache_key("sciopen", "doi", cleaned)
            resp = self._make_request(
                "GET", url, cache_key=cache_key,
                headers={"Accept": "text/html,application/xhtml+xml"},
            )
            html = resp.text or ""
            if not self._looks_blocked(html):
                BeautifulSoup = _import_bs4()
                if BeautifulSoup is not None:
                    soup = BeautifulSoup(html, "lxml")
                    paper = self._parse_article_page(soup, doi=cleaned)
                    if paper is not None:
                        return paper
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Sciopen fetch_by_id(%s) failed: %s", paper_id, exc)

        # Fall back to Crossref (always OA via Crossref if it has the DOI).
        try:
            scraper = self._get_crossref()
            if scraper is not None:
                paper = scraper.fetch_by_doi(cleaned)
                if paper is not None:
                    if not paper.source:
                        paper.source = self.name
                    return paper
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Crossref fallback failed for %s: %s", cleaned, exc)
        return None

    # -- internal helpers ------------------------------------------------

    def _get_crossref(self) -> Optional[Any]:
        """Return a Crossref scraper instance (built lazily)."""
        if self._crossref is not None:
            return self._crossref
        try:
            from .crossref_scraper import CrossrefScraper  # type: ignore
            self._crossref = CrossrefScraper(
                proxy_manager=self.proxy_manager,
                rate_limit=2.0,
                cache=self._cache,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Could not build Crossref fallback: %s", exc)
            self._crossref = None
        return self._crossref

    @staticmethod
    def _clean_doi(doi: str) -> str:
        """Strip ``doi:`` / ``https://doi.org/`` prefixes from ``doi``."""
        d = (doi or "").strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
            if d.lower().startswith(prefix):
                d = d[len(prefix):]
                break
        return d.strip()

    @staticmethod
    def _looks_blocked(html: str) -> bool:
        """Heuristic: detect blocked / empty / Cloudflare responses."""
        if not html:
            return True
        lower = html.lower()
        if "cloudflare" in lower and "challenge" in lower:
            return True
        if "access denied" in lower or "captcha" in lower:
            return True
        if "no results found" in lower:
            return True
        return False

    def _parse_item(self, item: Any) -> Optional[Paper]:
        """Parse a search-result HTML node into a :class:`Paper`."""
        title_el = item.select_one("h3 a, h2 a, .title a, a.title-link")
        title = (title_el.get_text(strip=True) if title_el else "").strip()
        if not title:
            return None
        href = title_el.get("href") if title_el else ""
        url = href
        if href and not href.startswith("http"):
            url = f"{self.BASE_URL}{href}"
        doi: Optional[str] = None
        m = _DOI_RE.search(href or "")
        if m:
            doi = m.group(0)

        authors: List[str] = []
        for el in item.select(".authors a, .author-list a"):
            name = el.get_text(strip=True).rstrip(",;")
            if name:
                authors.append(name)

        abstract = ""
        abs_el = item.select_one(".abstract, .description")
        if abs_el:
            abstract = abs_el.get_text(" ", strip=True)

        year: Optional[int] = None
        year_el = item.select_one(".year, .date")
        if year_el:
            m = re.search(r"(20\d{2}|19\d{2})", year_el.get_text())
            if m:
                year = int(m.group(1))

        pdf_url: Optional[str] = None
        pdf_link = item.select_one("a[href$='.pdf'], a.pdf-link")
        if pdf_link:
            pdf_href = pdf_link.get("href") or ""
            if pdf_href:
                pdf_url = (
                    pdf_href if pdf_href.startswith("http")
                    else f"{self.BASE_URL}{pdf_href}"
                )

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
            issn=None,
            isbn=None,
            publisher=None,
            journal=None,
            volume=None,
            issue=None,
            pages=None,
            language=None,
            paper_type=None,
            fields_of_study=[],
            raw={},
        )

    def _parse_article_page(self, soup: Any, doi: str) -> Optional[Paper]:
        """Parse a Sciopen article landing page."""
        try:
            title_el = soup.select_one("h1.article-title, h1.title, h1")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                return None
            authors: List[str] = []
            for el in soup.select(".authors a, .author-list a, .contributors a"):
                name = el.get_text(strip=True).rstrip(",;")
                if name:
                    authors.append(name)
            abstract_el = soup.select_one(".abstract, .abstract-content")
            abstract = abstract_el.get_text(" ", strip=True) if abstract_el else ""
            pdf_url: Optional[str] = None
            pdf_link = soup.select_one("a[href$='.pdf'], a.pdf-link")
            if pdf_link:
                pdf_href = pdf_link.get("href") or ""
                if pdf_href:
                    pdf_url = (
                        pdf_href if pdf_href.startswith("http")
                        else f"{self.BASE_URL}{pdf_href}"
                    )
            return Paper(
                title=title,
                authors=authors,
                abstract=abstract,
                year=None,
                doi=doi,
                url=f"{self.BASE_URL}/doi/{doi}",
                source=self.name,
                citations_count=None,
                references=[],
                keywords=[],
                pdf_url=pdf_url,
                issn=None,
                isbn=None,
                publisher=None,
                journal=None,
                volume=None,
                issue=None,
                pages=None,
                language=None,
                paper_type=None,
                fields_of_study=[],
                raw={"landing_url": f"{self.BASE_URL}/doi/{doi}"},
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Sciopen landing-page parse failed: %s", exc)
            return None


__all__ = ["SciOpenScraper"]
