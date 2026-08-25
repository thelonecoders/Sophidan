"""
acm_scraper.py
==============

Scraper for the **ACM Digital Library** (https://dl.acm.org).

Unlike most scholarly sources, ACM does NOT expose a public, open
metadata API for arbitrary searches.  This module therefore falls
back to scraping the HTML search results pages using ``beautifulsoup4``
+ ``lxml``, and to the optional ACM citation/BibTeX export endpoint
for richer metadata when an article ID is known.

Capabilities
------------
* :meth:`search` — scrapes ``https://dl.acm.org/action/doSearch``
  for up to ``max_results`` records.
* :meth:`fetch_by_doi` — attempts the ACM landing page first; if
  that fails (anti-bot block, 403, ...), it transparently falls back
  to Crossref via :class:`data_acquisition.crossref_scraper.CrossrefScraper`.
* :meth:`fetch_by_id` — fetches a single article by ACM DL ID and
  optionally pulls its BibTeX record.

Politeness / rate limiting
--------------------------
ACM's terms of service ask automated clients to:

  * identify themselves with a descriptive User-Agent;
  * throttle to roughly one request every **3 seconds**;
  * honour ``robots.txt`` (the doSearch and article pages are
    permitted for academic researchers as of this writing, but
    operators should verify before deployment).

This scraper enforces ``1`` request per ``3`` seconds by default
via :class:`BaseScraper`'s token-bucket.

Graceful degradation
--------------------
ACM employs aggressive anti-bot protection (Cloudflare, browser
fingerprinting).  When the search returns a 403/503 or an obviously
blocked HTML page (no ``<div class="issue-item">`` containers), the
scraper returns an **empty** :class:`ScraperResult` with a single
non-fatal error entry rather than raising — callers can transparently
fall back to other sources.
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

# Lazy / optional imports — bs4 and lxml are declared in requirements.
def _import_bs4() -> Any:
    """Lazy import of BeautifulSoup.

    Returns the ``BeautifulSoup`` class when available, else ``None``.
    """
    try:
        from bs4 import BeautifulSoup  # type: ignore
        return BeautifulSoup
    except Exception:  # noqa: BLE001
        return None


# Regex for ACM DL article IDs (10-digit numbers).
_ACM_ID_RE = re.compile(r"/doi/(?:abs/|full/|pdf/)?(10\.\d{4,9}/[^\s\"?]+)")

# Regex for DOIs in general (used by fetch_by_doi fallback).
_DOI_URL_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")


class ACMDigitalLibraryScraper(BaseScraper):
    """Scraper for the ACM Digital Library (HTML-scraping fallback).

    The scraper inherits the standard :class:`BaseScraper` HTTP
    plumbing (retries, rate-limit, caching, proxy rotation) and
    parses the HTML result list with ``beautifulsoup4``.
    """

    BASE_URL = "https://dl.acm.org/action/doSearch"
    SOURCE_NAME = "acm"

    # Identifies the scraper in server logs.
    DEFAULT_USER_AGENT = (
        "AcademicResearchSuite/2.0 "
        "(ACM DL scraper; +https://github.com/academic-research-suite; "
        "academic research, contact via GitHub)"
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
        """Initialize an :class:`ACMDigitalLibraryScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            rate_limit: Maximum requests per second (default
                ``0.33`` ≈ 1 req / 3 s — polite ACM pace).
            cache: Optional response cache.
            timeout: Per-request timeout in seconds.
            max_retries: Maximum retry attempts.
            user_agent: Optional User-Agent override.
            crossref_scraper: Optional pre-built
                :class:`CrossrefScraper` instance used by
                :meth:`fetch_by_doi` as a fallback.  When ``None``,
                the scraper builds one on demand (also lazy).
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
        """Search ACM DL for records matching ``query``.

        Args:
            query: Free-text search string.
            max_results: Maximum number of papers to return (the
                scraper fetches up to ``max_results // 20 + 1``
                pages of 20 results each).
            **kwargs: Reserved for future use.

        Returns:
            A :class:`ScraperResult`.  May be empty with an error
            entry if ACM blocks the request (graceful degradation).
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        errors: List[str] = []
        BeautifulSoup = _import_bs4()
        if BeautifulSoup is None:
            errors.append(
                "beautifulsoup4 is required for ACM scraping but is "
                "not installed."
            )
            result.errors = errors
            result.elapsed_ms = self._now_ms() - start_ms
            return result

        per_page = 20
        pages = max(1, (max_results + per_page - 1) // per_page)
        raw_html_pages: List[str] = []

        for page_idx in range(pages):
            start_item = page_idx * per_page
            params: Dict[str, Any] = {
                "AllField": query,
                "startPage": page_idx + 1,
                "pageSize": per_page,
            }
            try:
                cache_key = self._cache_key(
                    "acm", "search", query, page_idx + 1
                )
                resp = self._make_request(
                    "GET",
                    self.BASE_URL,
                    params=params,
                    cache_key=cache_key,
                    headers={"Accept": "text/html,application/xhtml+xml"},
                )
                html = resp.text or ""
                raw_html_pages.append(html)
            except Exception as exc:  # noqa: BLE001
                err = f"ACM search request failed at page {page_idx + 1}: {exc}"
                errors.append(err)
                self.logger.warning(err)
                break

            if self._looks_blocked(html):
                err = (
                    "ACM DL returned an anti-bot / blocked response "
                    f"(page {page_idx + 1}); returning partial results."
                )
                errors.append(err)
                self.logger.warning(err)
                break

            soup = BeautifulSoup(html, "lxml")
            items = soup.select("div.issue-item, li.issue-item")
            if not items:
                # No more results.
                break

            for item in items:
                if len(result.papers) >= max_results:
                    break
                paper = self._parse_item(item)
                if paper is not None:
                    result.papers.append(paper)

            result.total_results = len(result.papers)  # ACM HTML doesn't expose total

        result.raw_response = {"pages": raw_html_pages}
        result.errors = errors
        result.timestamp = datetime.now(timezone.utc).isoformat()
        result.elapsed_ms = self._now_ms() - start_ms
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single ACM DL article by its DOI / article ID.

        Tries the ACM DL landing page first; if blocked, falls back
        to Crossref (which has authoritative ACM metadata).

        Args:
            paper_id: ACM article ID (e.g. ``3457147``) or full DOI
                (e.g. ``10.1145/3457147``).

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        if not paper_id:
            return None
        pid = str(paper_id).strip()
        # Normalize to a DOI form if only the numeric suffix was given.
        if pid.isdigit():
            doi = f"10.1145/{pid}"
        elif pid.startswith("10."):
            doi = pid
        else:
            doi = pid
        return self.fetch_by_doi(doi)

    def fetch_by_doi(self, doi: str) -> Optional[Paper]:
        """Fetch an ACM article by DOI, falling back to Crossref.

        Args:
            doi: The DOI string (with or without a ``doi:`` /
                ``https://doi.org/`` prefix).

        Returns:
            A :class:`Paper` or ``None``.
        """
        cleaned = self._clean_doi(doi)
        if not cleaned:
            return None

        # First try the ACM DL landing page directly.
        url = f"https://dl.acm.org/doi/{cleaned}"
        try:
            cache_key = self._cache_key("acm", "doi", cleaned)
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
            self.logger.debug("ACM direct DOI fetch failed (%s); falling back to Crossref.", exc)

        # Fall back to Crossref.
        try:
            scraper = self._get_crossref()
            if scraper is not None:
                paper = scraper.fetch_by_doi(cleaned)
                if paper is not None:
                    if not paper.source:
                        paper.source = self.name
                    # Preserve original ACM DOI URL.
                    if not paper.url:
                        paper.url = url
                    return paper
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Crossref fallback failed for ACM DOI %s: %s", cleaned, exc)
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
        """Heuristic to detect Cloudflare / ACM anti-bot responses.

        Returns ``True`` when the page is suspiciously short, lacks
        the expected ``issue-item`` containers, or contains known
        blocking markers.
        """
        if not html:
            return True
        lower = html.lower()
        if "cloudflare" in lower and "challenge" in lower:
            return True
        if "access denied" in lower or "captcha" in lower:
            return True
        if "enable javascript and cookies" in lower:
            return True
        # Reasonable ACM search page should be at least 5 KB.
        if len(html) < 5000 and "issue-item" not in lower:
            return True
        return False

    def _parse_item(self, item: Any) -> Optional[Paper]:
        """Parse a single ``issue-item`` BeautifulSoup tag into a :class:`Paper`."""
        # Title
        title_el = item.select_one(
            "h3.issue-item__title a, "
            "div.issue-item__title a, "
            "a.issue-item__title, "
            ".issue-item__title a"
        )
        title = (title_el.get_text(strip=True) if title_el else "").strip()
        if not title:
            return None
        href = title_el.get("href") if title_el else ""
        doi = self._extract_doi_from_url(href) if href else None
        url = f"https://dl.acm.org{href}" if href else None

        # Authors
        authors: List[str] = []
        for el in item.select(
            "ul.issue-item__authors li a, "
            "div.issue-item__authors a, "
            ".rlist--inline a"
        ):
            name = el.get_text(strip=True)
            if name:
                # Strip trailing comma / semicolon.
                name = name.rstrip(",;").strip()
                if name:
                    authors.append(name)

        # Abstract — ACM search results don't expose full abstracts,
        # but a teaser snippet is present under ``.issue-item__abstract``.
        abstract = ""
        abstract_el = item.select_one(
            "div.issue-item__abstract, .issue-item__description"
        )
        if abstract_el:
            abstract = abstract_el.get_text(" ", strip=True)

        # Year — usually present in the metadata strip
        # (``.issue-item__detail .issue-item__date``).
        year: Optional[int] = None
        date_el = item.select_one(".issue-item__date, .issue-item__year")
        if date_el:
            date_text = date_el.get_text(strip=True)
            m = re.search(r"(20\d{2}|19\d{2})", date_text)
            if m:
                year = int(m.group(1))

        # Venue / journal
        venue: Optional[str] = None
        venue_el = item.select_one(
            ".issue-item__detail a, .epub-section__title"
        )
        if venue_el:
            venue = venue_el.get_text(strip=True) or None

        pdf_url: Optional[str] = None
        pdf_link = item.select_one("a[href*='/doi/pdf/']")
        if pdf_link:
            pdf_href = pdf_link.get("href") or ""
            if pdf_href:
                pdf_url = f"https://dl.acm.org{pdf_href}"

        raw: Dict[str, Any] = {}
        # Stash the raw HTML of the item (truncated) for debugging.
        try:
            raw["item_html"] = str(item)[:4000]
        except Exception:  # noqa: BLE001
            pass

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
            publisher="ACM",
            journal=venue,
            volume=None,
            issue=None,
            pages=None,
            language=None,
            paper_type=None,
            fields_of_study=[],
            raw=raw,
        )

    def _parse_article_page(self, soup: Any, doi: str) -> Optional[Paper]:
        """Parse a single ACM DL article landing page (HTML)."""
        try:
            title = ""
            title_el = soup.select_one("h1.citation__title, h1.article-title")
            if title_el:
                title = title_el.get_text(strip=True)
            if not title:
                return None

            authors: List[str] = []
            for el in soup.select(
                "ul.rlist--inline li.loa__item-name a, "
                "div.contrib-info a.contrib-name, "
                "a.loa__item-name"
            ):
                name = el.get_text(strip=True)
                if name:
                    authors.append(name)

            abstract = ""
            abstract_el = soup.select_one(
                "div.abstractSection, div.sectionAbstract, div.abstractInFull"
            )
            if abstract_el:
                abstract = abstract_el.get_text(" ", strip=True)

            # Year & venue from the citation metadata block.
            year: Optional[int] = None
            journal: Optional[str] = None
            for el in soup.select("span.citation__detail, div.core-format"):
                text = el.get_text(" ", strip=True)
                m = re.search(r"(20\d{2}|19\d{2})", text)
                if m and year is None:
                    year = int(m.group(1))
                if journal is None:
                    # ACM stores "Journal Name, Volume X, Issue Y"
                    parts = [p.strip() for p in text.split(",")]
                    if parts:
                        journal = parts[0]

            pdf_url: Optional[str] = None
            pdf_link = soup.select_one("a[href*='/doi/pdf/']")
            if pdf_link:
                pdf_href = pdf_link.get("href") or ""
                if pdf_href:
                    pdf_url = f"https://dl.acm.org{pdf_href}"

            return Paper(
                title=title,
                authors=authors,
                abstract=abstract,
                year=year,
                doi=doi,
                url=f"https://dl.acm.org/doi/{doi}",
                source=self.name,
                citations_count=None,
                references=[],
                keywords=[],
                pdf_url=pdf_url,
                issn=None,
                isbn=None,
                publisher="ACM",
                journal=journal,
                volume=None,
                issue=None,
                pages=None,
                language=None,
                paper_type=None,
                fields_of_study=[],
                raw={"landing_url": f"https://dl.acm.org/doi/{doi}"},
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("ACM landing-page parse failed: %s", exc)
            return None

    @staticmethod
    def _extract_doi_from_url(url: str) -> Optional[str]:
        """Extract an ACM DOI (``10.1145/...``) from a relative URL."""
        if not url:
            return None
        m = _ACM_ID_RE.search(url)
        return m.group(1) if m else None


__all__ = ["ACMDigitalLibraryScraper"]
