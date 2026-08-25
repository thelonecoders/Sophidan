"""
arxiv_scraper.py
================

Scraper for the arXiv public preprint API.

Endpoint: ``http://export.arxiv.org/api/query`` — returns an Atom XML
feed.  No API key is required; the service asks clients to keep
request volume reasonable (the official guideline is "no more than
one request every 3 seconds", which we enforce via the base class's
token-bucket rate limiter, defaulting to ``1`` req / 3s for this
scraper).

Supported features
------------------
* Free-text search across all fields, plus field qualifiers
  (``au:``, ``ti:``, ``cat:`` and date ranges
  ``submittedDate:[YYYYMMDDhhmm TO YYYYMMDDhhmm]``).
* Sort by relevance, date or (proxy for) citations — arXiv does not
  expose citation counts, so ``sort_by='citations'`` falls back to
  the ``lastUpdatedDate`` ordering and a debug log is emitted.
* Single-paper fetch via :meth:`fetch_by_id` using the ``id_list``
  API parameter.
* Optional PDF download (sets ``download_pdf=True`` on ``search``)
  using the ``pdf`` link advertised in each entry.
* Static arXiv taxonomy exposed through :meth:`list_categories` for
  UI dropdowns.
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from .base_scraper import BaseScraper, Paper, ScraperResult

logger = logging.getLogger(__name__)


# Atom + arXiv namespace map used throughout the parser.
_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"
_NS_MAP = {"atom": _ATOM_NS, "arxiv": _ARXIV_NS}

# A condensed taxonomy suitable for UI dropdowns.  Keys are the major
# archives; values map human-friendly subcategory labels to their
# arXiv category codes.  This is intentionally a static snapshot — the
# arXiv API itself does not expose a categories endpoint, so a static
# table is the conventional solution.
_ARXIV_TAXONOMY: Dict[str, Dict[str, str]] = {
    "Computer Science": {
        "Artificial Intelligence": "cs.AI",
        "Computation and Language": "cs.CL",
        "Computer Vision and Pattern Recognition": "cs.CV",
        "Machine Learning": "cs.LG",
        "Robotics": "cs.RO",
        "Software Engineering": "cs.SE",
    },
    "Mathematics": {
        "Algebraic Geometry": "math.AG",
        "Analysis of PDEs": "math.AP",
        "Number Theory": "math.NT",
        "Statistics Theory": "math.ST",
    },
    "Physics": {
        "Astrophysics": "astro-ph",
        "Condensed Matter": "cond-mat",
        "High Energy Physics — Experiment": "hep-ex",
        "High Energy Physics — Theory": "hep-th",
        "Quantum Physics": "quant-ph",
    },
    "Quantitative Biology": {
        "Biomolecules": "q-bio.BM",
        "Cell Behavior": "q-bio.CB",
        "Genomics": "q-bio.GN",
    },
    "Quantitative Finance": {
        "Computational Finance": "q-fin.CP",
        "Economics": "q-fin.EC",
        "Statistical Finance": "q-fin.ST",
    },
    "Statistics": {
        "Applications": "stat.AP",
        "Machine Learning": "stat.ML",
        "Methodology": "stat.ME",
    },
    "Electrical Engineering and Systems Science": {
        "Audio and Speech Processing": "eess.AS",
        "Image and Video Processing": "eess.IV",
        "Signal Processing": "eess.SP",
    },
    "Economics": {
        "Econometrics": "econ.EM",
    },
}


class ArxivScraper(BaseScraper):
    """Scraper for the arXiv public API."""

    BASE_URL = "http://export.arxiv.org/api/query"
    SOURCE_NAME = "arxiv"

    # arXiv asks for ~3s between requests.  Default rate limit ~0.33 r/s.
    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        rate_limit: float = 0.33,
        cache: Optional[Any] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: Optional[str] = None,
        pdf_dir: Optional[str] = None,
    ) -> None:
        """Initialize an :class:`ArxivScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            rate_limit: Requests per second (default ``0.33`` ≈ 1 per 3s).
            cache: Optional response cache.
            timeout: Per-request timeout (seconds).
            max_retries: Maximum retry attempts for transient errors.
            user_agent: Optional User-Agent override.
            pdf_dir: Directory for downloaded PDFs (used when
                ``download_pdf=True`` on :meth:`search`).  Defaults to
                ``./downloads/arxiv``.
        """
        super().__init__(
            proxy_manager=proxy_manager,
            rate_limit=rate_limit,
            cache=cache,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent,
        )
        self.pdf_dir = pdf_dir or os.path.join("downloads", "arxiv")

    # -- query construction ----------------------------------------------

    @staticmethod
    def _build_field_query(
        query: str,
        *,
        author: Optional[str] = None,
        title: Optional[str] = None,
        categories: Optional[List[str]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> str:
        """Compose an arXiv search_query string with optional field qualifiers.

        ``submittedDate`` ranges use the arXiv format
        ``YYYYMMDDhhmm``; callers may pass 4- to 14-digit strings or
        ISO 8601 dates — they are normalized here.

        Args:
            query: Free-text term (searched across all fields).
            author: Optional author name (``au:``).
            title: Optional title fragment (``ti:``).
            categories: Optional list of arXiv category codes
                (``cat:``), OR-combined.
            date_from: Inclusive lower bound.
            date_to: Inclusive upper bound.

        Returns:
            A properly escaped arXiv ``search_query`` value.
        """
        parts: List[str] = []
        if query and query.strip():
            parts.append(f"all:{query.strip()}")
        if author:
            parts.append(f"au:{author.strip()}")
        if title:
            parts.append(f"ti:{title.strip()}")
        if categories:
            cat_expr = " OR ".join(f"cat:{c.strip()}" for c in categories if c)
            if cat_expr:
                parts.append(f"({cat_expr})")
        if date_from or date_to:
            lo = ArxivScraper._normalize_date(date_from) if date_from else "000000000000"
            hi = ArxivScraper._normalize_date(date_to) if date_to else "999999999999"
            parts.append(f"submittedDate:[{lo} TO {hi}]")
        return " AND ".join(parts)

    @staticmethod
    def _normalize_date(s: str) -> str:
        """Normalize an 8-14 digit or ISO date to arXiv's ``YYYYMMDDhhmm``."""
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 12:
            return digits[:12]
        if len(digits) == 8:
            return digits + "0000"
        if len(digits) == 4:
            return digits + "01010000"
        return digits.ljust(12, "0")[:12]

    # -- public API ------------------------------------------------------

    def search(
        self,
        query: str,
        max_results: int = 50,
        sort_by: str = "relevance",
        categories: Optional[List[str]] = None,
        author: Optional[str] = None,
        title: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        download_pdf: bool = False,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search arXiv for papers matching the given query.

        Args:
            query: Free-text query (may be empty if other qualifiers
                are provided).
            max_results: Maximum number of papers to return.
            sort_by: One of ``'relevance'``, ``'date'`` or
                ``'citations'``.  arXiv does not expose citation
                counts, so ``'citations'`` falls back to
                ``lastUpdatedDate`` ordering.
            categories: Optional list of arXiv category codes
                (e.g. ``["cs.AI", "cs.LG"]``).
            author: Optional author filter.
            title: Optional title fragment.
            date_from: Inclusive submission-date lower bound
                (``YYYY-MM-DD`` or ``YYYYMMDDhhmm``).
            date_to: Inclusive submission-date upper bound.
            download_pdf: If ``True``, attempt to download the PDF
                for each returned paper into :attr:`pdf_dir`.
            **kwargs: Reserved for future use.

        Returns:
            A populated :class:`ScraperResult`.
        """
        start_ms = self._now_ms()
        errors: List[str] = []
        search_query = self._build_field_query(
            query,
            author=author,
            title=title,
            categories=categories,
            date_from=date_from,
            date_to=date_to,
        )

        sort_map = {
            "relevance": ("relevance", "ascending"),
            "date": ("submittedDate", "descending"),
            "citations": ("lastUpdatedDate", "descending"),
        }
        sort_key, sort_dir = sort_map.get(sort_by.lower(), sort_map["relevance"])
        if sort_by.lower() == "citations":
            self.logger.debug(
                "arXiv has no citation count; sort_by='citations' falls "
                "back to lastUpdatedDate ordering."
            )

        # arXiv paginates via `start` + `max_results`; cap per-page at 100.
        per_page = min(max_results, 100)
        params: Dict[str, Any] = {
            "search_query": search_query,
            "start": 0,
            "max_results": per_page,
            "sortBy": sort_key,
            "sortOrder": sort_dir,
        }

        papers: List[Paper] = []
        total_results = 0
        raw_response: Optional[ET.Element] = None
        try:
            cache_key = self._cache_key("arxiv", "search", search_query, per_page, sort_key)
            resp = self._make_request(
                "GET", self.BASE_URL, params=params, cache_key=cache_key
            )
            content = resp.text
            root = ET.fromstring(content)
            raw_response = root
            total_results = self._parse_total_results(root)
            entries = root.findall("atom:entry", _NS_MAP)
            self._emit_event(
                "search.started",
                {"query": query, "source": self.name, "total": total_results},
            )
            for entry in entries[:max_results]:
                paper = self._parse_entry(entry)
                if paper is None:
                    continue
                if download_pdf and paper.pdf_url:
                    try:
                        self._download_pdf(paper)
                    except Exception as exc:  # noqa: BLE001
                        msg = f"PDF download failed for {paper.doi or paper.url}: {exc}"
                        errors.append(msg)
                        self.logger.warning(msg)
                papers.append(paper)
                self._emit_event(
                    "search.progress",
                    {
                        "fetched": len(papers),
                        "total": min(total_results, max_results),
                    },
                )
        except requests.RequestException as exc:
            errors.append(f"HTTP error: {exc}")
            self.logger.error("arXiv request failed: %s", exc, exc_info=True)
        except ET.ParseError as exc:
            errors.append(f"XML parse error: {exc}")
            self.logger.error("arXiv XML parse error: %s", exc, exc_info=True)

        self._emit_event("search.finished", {"count": len(papers)})
        return ScraperResult(
            source=self.name,
            query=query,
            total_results=total_results,
            papers=papers,
            raw_response=None if raw_response is None else ET.tostring(raw_response, encoding="unicode"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            elapsed_ms=self._now_ms() - start_ms,
            errors=errors,
        )

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single arXiv paper by its ID (e.g. ``2106.04561``).

        Args:
            paper_id: The arXiv identifier.  The ``arXiv:`` prefix and
                version suffix (``v2``) are stripped automatically.

        Returns:
            A :class:`Paper`, or ``None`` if not found.
        """
        clean_id = paper_id.strip()
        if clean_id.lower().startswith("arxiv:"):
            clean_id = clean_id[6:]
        # strip version suffix
        if "v" in clean_id and clean_id[-2:].startswith("v") and clean_id[-1].isdigit():
            clean_id = clean_id.rsplit("v", 1)[0]
        params = {"id_list": clean_id}
        try:
            cache_key = self._cache_key("arxiv", "id", clean_id)
            resp = self._make_request(
                "GET", self.BASE_URL, params=params, cache_key=cache_key
            )
            root = ET.fromstring(resp.text)
            entries = root.findall("atom:entry", _NS_MAP)
            if not entries:
                return None
            return self._parse_entry(entries[0])
        except (requests.RequestException, ET.ParseError) as exc:
            self.logger.error("fetch_by_id failed for %s: %s", paper_id, exc)
            return None

    def list_categories(self) -> Dict[str, Dict[str, str]]:
        """Return a static mapping of arXiv categories for UI use.

        Returns:
            A nested dict ``{archive: {label: code}}``.
        """
        return {k: dict(v) for k, v in _ARXIV_TAXONOMY.items()}

    # -- parsing ---------------------------------------------------------

    def _parse_total_results(self, root: ET.Element) -> int:
        """Read the ``<opensearch:totalResults>`` element if present."""
        for child in root:
            tag = child.tag
            if tag.endswith("totalResults"):
                try:
                    return int((child.text or "0").strip())
                except ValueError:
                    return 0
        return 0

    def _parse_entry(self, entry: ET.Element) -> Optional[Paper]:
        """Convert a single Atom ``<entry>`` to a :class:`Paper`."""
        def _text(tag_local: str, ns: str = _ATOM_NS) -> str:
            el = entry.find(f"{{{ns}}}{tag_local}")
            return (el.text or "").strip() if el is not None else ""

        title = _text("title").replace("\n", " ").strip()
        if not title:
            return None

        authors: List[str] = []
        for author_el in entry.findall("atom:author", _NS_MAP):
            name_el = author_el.find("atom:name", _NS_MAP)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        abstract = _text("summary").replace("\n", " ").strip()
        published = _text("published")
        year: Optional[int] = None
        if published:
            try:
                year = int(published[:4])
            except ValueError:
                year = None

        doi: Optional[str] = None
        pdf_url: Optional[str] = None
        abs_url: Optional[str] = None
        journal_ref: Optional[str] = None
        primary_category: Optional[str] = None
        categories: List[str] = []

        for link_el in entry.findall("atom:link", _NS_MAP):
            href = link_el.get("href", "")
            rel = link_el.get("rel", "")
            if rel == "related" and "doi.org" in href:
                doi = href.split("doi.org/")[-1]
            elif rel == "enclosure" and link_el.get("type") == "application/pdf":
                pdf_url = href
            elif rel == "alternate":
                abs_url = href

        doi_el = entry.find("arxiv:doi", _NS_MAP)
        if doi_el is not None and doi_el.text:
            doi = doi_el.text.strip()
        journal_el = entry.find("arxiv:journal_ref", _NS_MAP)
        if journal_el is not None and journal_el.text:
            journal_ref = journal_el.text.strip()
        primary_cat_el = entry.find("arxiv:primary_category", _NS_MAP)
        if primary_cat_el is not None:
            primary_category = primary_cat_el.get("term")
        for cat_el in entry.findall("atom:category", _NS_MAP):
            term = cat_el.get("term")
            if term:
                categories.append(term)

        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            year=year,
            doi=doi,
            url=abs_url,
            source=self.name,
            citations_count=None,  # arXiv does not report citations
            references=[],
            keywords=categories,
            pdf_url=pdf_url,
            journal=journal_ref,
            fields_of_study=[primary_category] if primary_category else [],
            raw={"categories": categories},
        )

    # -- PDF download ----------------------------------------------------

    def _download_pdf(self, paper: Paper) -> Optional[str]:
        """Download the PDF for ``paper`` into :attr:`pdf_dir`.

        Args:
            paper: A :class:`Paper` with ``pdf_url`` set.

        Returns:
            The path of the downloaded file, or ``None`` on failure.
        """
        if not paper.pdf_url:
            return None
        os.makedirs(self.pdf_dir, exist_ok=True)
        # Derive a safe filename from the URL path or DOI.
        path = urlparse(paper.pdf_url).path
        slug = os.path.basename(path) or "paper.pdf"
        if not slug.lower().endswith(".pdf"):
            slug += ".pdf"
        dest = os.path.join(self.pdf_dir, slug)
        try:
            resp = self._session.get(paper.pdf_url, timeout=self.timeout, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        fh.write(chunk)
            self.logger.info("Downloaded PDF -> %s", dest)
            return dest
        except requests.RequestException as exc:
            self.logger.warning("Failed to download %s: %s", paper.pdf_url, exc)
            return None


__all__ = ["ArxivScraper"]
