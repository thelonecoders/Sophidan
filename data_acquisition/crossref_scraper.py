"""
crossref_scraper.py
===================

Scraper for the Crossref REST API (``https://api.crossref.org/works``).

Crossref is the canonical metadata registry for scholarly DOIs. The
REST API does not require an API key; providing a "polite email"
(via the ``mailto`` query parameter or ``User-Agent`` header) routes
requests to a higher-rate-limit pool, so it is strongly recommended.

This module exposes :class:`CrossrefScraper`, a
:class:`~data_acquisition.base_scraper.BaseScraper` implementation
that supports:

* Free-text search with cursor-based pagination (``next-cursor``).
* DOI lookup, references-list lookup, and citations lookup.
* Parsing of Funder metadata, license information, and the
  ``reference`` list attached to each work.

The scraper always returns a :class:`ScraperResult` whose ``papers``
list contains :class:`Paper` records normalised across sources.
Source-specific fields not on the :class:`Paper` schema (funders,
license, ISSN, subjects, etc.) are preserved in :attr:`Paper.raw`.
"""
from __future__ import annotations
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
import re
import time
from typing import Any, Dict, List, Optional

from ._compat import BaseScraper, Paper, ScraperResult, get_logger

CROSSREF_BASE_URL = "https://api.crossref.org/works"

# Sort names accepted by Crossref's `sort` parameter.
_VALID_SORTS = {"relevance", "published", "cited", "submitted", "updated", "score"}


class CrossrefScraper(BaseScraper):
    """Scraper for the Crossref REST API.

    Inherits HTTP plumbing (retries, rate-limiting, proxy rotation,
    caching) from :class:`data_acquisition.base_scraper.BaseScraper`.
    """

    BASE_URL = CROSSREF_BASE_URL
    SOURCE_NAME = "Crossref"

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        polite_email: Optional[str] = None,
        rate_limit: float = 8.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        cache: Optional[Any] = None,
    ) -> None:
        """Initialize the Crossref scraper.

        Args:
            proxy_manager: Optional proxy manager.
            polite_email: Optional contact email used for Crossref's
                "polite pool" (higher rate limits).
            rate_limit: Maximum requests per second (default 8 —
                Crossref's polite-pool ceiling).
            timeout: HTTP timeout in seconds.
            max_retries: Maximum number of retries on transient errors.
            cache: Optional ``utils.cache.Cache`` instance.
        """
        super().__init__(
            proxy_manager=proxy_manager,
            rate_limit=rate_limit,
            timeout=timeout,
            max_retries=max_retries,
            cache=cache,
            user_agent=self._user_agent(polite_email),
        )
        self.logger: logging.Logger = get_logger(__name__)
        self._polite_email = polite_email

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        max_results: int = 50,
        filters: Optional[Dict[str, Any]] = None,
        sort: str = "relevance",
        **kwargs: Any,
    ) -> ScraperResult:
        """Search Crossref for works matching ``query``.

        Args:
            query: Free-text search string (Crossref's
                ``query.bibliographic`` parameter is used).
            max_results: Maximum number of records to return.
            filters: Optional Crossref filter dictionary. Keys may
                include ``from_pub_date``, ``until_pub_date``,
                ``type``, ``container_title``, ``author``,
                ``has_full_text``, ``has_license``. Unknown keys are
                passed through unchanged.
            sort: Sort order — one of ``"relevance"``,
                ``"published"``, ``"cited"``.
            **kwargs: Reserved for future use.

        Returns:
            A :class:`ScraperResult` containing the parsed papers.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        sort = sort if sort in _VALID_SORTS else "relevance"

        params: Dict[str, Any] = {
            "query.bibliographic": query,
            "rows": min(max_results, 100),
            "sort": sort,
        }
        if self._polite_email:
            params["mailto"] = self._polite_email
        if filters:
            params["filter"] = self._encode_filters(filters)

        cursor = "*"
        collected = 0
        data: Dict[str, Any] = {}
        while collected < max_results:
            params["cursor"] = cursor
            try:
                resp = self._make_request(
                    "GET", self.BASE_URL, params=params, cache_key=self._cache_key("crossref_search", query, cursor)
                )
                data = self._handle_response(resp)
            except Exception as exc:
                self.logger.error(
                    "Crossref request failed: %s", exc, exc_info=True
                )
                result.errors.append(str(exc))
                break

            message = data.get("message", {})
            items = message.get("items", []) or []
            if not items:
                break

            for item in items:
                if collected >= max_results:
                    break
                try:
                    result.papers.append(self._parse_work(item))
                    collected += 1
                except Exception as exc:  # pragma: no cover
                    self.logger.warning("Skipping malformed Crossref item: %s", exc)
                    result.errors.append(f"Skipped item: {exc}")

            cursor = message.get("next-cursor")
            if not cursor:
                break

        result.total_results = data.get("message", {}).get(
            "total-results", len(result.papers)
        ) if isinstance(data, dict) else len(result.papers)
        result.raw_response = data if isinstance(data, dict) else None
        result.elapsed_ms = self._now_ms() - start_ms
        self.logger.info(
            "Crossref query complete. Returning %d papers (total matches=%d).",
            len(result.papers),
            result.total_results,
        )
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single work by DOI.

        Alias for :meth:`fetch_by_doi`. The ``paper_id`` is the DOI.

        Args:
            paper_id: The DOI string (with or without a ``https://doi.org/`` prefix).

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        return self.fetch_by_doi(paper_id)

    # ------------------------------------------------------------------
    # Direct lookups
    # ------------------------------------------------------------------
    def fetch_by_doi(self, doi: str) -> Optional[Paper]:
        """Fetch a single work by DOI.

        Args:
            doi: The DOI string (with or without a ``https://doi.org/`` prefix).

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        cleaned = self._clean_doi(doi)
        if not cleaned:
            return None
        url = f"{self.BASE_URL}/{cleaned}"
        try:
            resp = self._make_request(
                "GET", url, cache_key=self._cache_key("crossref_doi", cleaned)
            )
            data = self._handle_response(resp)
        except Exception as exc:
            self.logger.error("Crossref fetch_by_doi(%s) failed: %s", doi, exc)
            return None
        item = data.get("message", data) if isinstance(data, dict) else None
        if not item:
            return None
        return self._parse_work(item)

    def fetch_references(self, doi: str, max_results: int = 100) -> List[Paper]:
        """Fetch the references list of a work.

        Crossref returns a ``reference`` array on each work. Each
        reference may or may not contain a DOI; entries without a DOI
        are returned as minimal :class:`Paper` records populated from
        the unstructured citation text.

        Args:
            doi: DOI of the citing work.
            max_results: Maximum number of references to return.

        Returns:
            A list of :class:`Paper` objects.
        """
        paper = self.fetch_by_doi(doi)
        if not paper:
            return []
        refs = paper.references
        out: List[Paper] = []
        for ref in refs[:max_results]:
            if ref.startswith("10."):
                try:
                    full = self.fetch_by_doi(ref)
                    if full:
                        out.append(full)
                        continue
                except Exception:
                    pass
            out.append(Paper(doi=None, title=ref, source=self.name))
        return out

    def fetch_citations(self, doi: str, max_results: int = 100) -> List[Paper]:
        """Fetch works citing the given DOI.

        Crossref exposes this through ``filter=reference:DOI``.

        Args:
            doi: The DOI whose citations should be retrieved.
            max_results: Maximum number of citing works to return.

        Returns:
            A list of citing :class:`Paper` objects.
        """
        cleaned = self._clean_doi(doi)
        if not cleaned:
            return []
        params: Dict[str, Any] = {
            "filter": f"reference:{cleaned}",
            "rows": min(max_results, 100),
            "sort": "published",
        }
        if self._polite_email:
            params["mailto"] = self._polite_email

        cursor = "*"
        out: List[Paper] = []
        while len(out) < max_results:
            params["cursor"] = cursor
            try:
                resp = self._make_request("GET", self.BASE_URL, params=params)
                data = self._handle_response(resp)
            except Exception as exc:
                self.logger.error("Crossref fetch_citations(%s): %s", doi, exc)
                break
            message = data.get("message", {})
            items = message.get("items", []) or []
            if not items:
                break
            for item in items:
                if len(out) >= max_results:
                    break
                try:
                    out.append(self._parse_work(item))
                except Exception as exc:  # pragma: no cover
                    self.logger.warning("Skipping citation: %s", exc)
            cursor = message.get("next-cursor")
            if not cursor:
                break
        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _user_agent(self, polite_email: Optional[str]) -> str:
        if polite_email:
            return f"AcademicResearchSuite/1.0 (mailto:{polite_email})"
        return "AcademicResearchSuite/1.0"

    @staticmethod
    def _clean_doi(doi: str) -> str:
        if not doi:
            return ""
        d = doi.strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
            if d.lower().startswith(prefix):
                d = d[len(prefix):]
                break
        return d.strip()

    @staticmethod
    def _encode_filters(filters: Dict[str, Any]) -> str:
        """Translate a friendly filter dict into Crossref's ``filter`` syntax."""
        mapping = {
            "from_pub_date": "from-pub-date",
            "until_pub_date": "until-pub-date",
            "container_title": "container-title",
            "has_full_text": "has-full-text",
            "has_license": "has-license",
            "type": "type",
            "author": "author",
            "publisher": "publisher-name",
        }
        parts: List[str] = []
        for key, value in filters.items():
            ck = mapping.get(key, key.replace("_", "-"))
            if isinstance(value, bool):
                v = "true" if value else "false"
            else:
                v = str(value)
            parts.append(f"{ck}:{v}")
        return ",".join(parts)

    def _parse_work(self, item: Dict[str, Any]) -> Paper:
        """Convert a Crossref work record into a :class:`Paper`."""
        authors: List[str] = []
        for a in item.get("author", []) or []:
            given = (a.get("given") or "").strip()
            family = (a.get("family") or "").strip()
            name = (given + " " + family).strip() or a.get("name", "")
            if name:
                authors.append(name)

        # Year
        year: Optional[int] = None
        issued = item.get("issued") or {}
        date_parts = issued.get("date-parts") or []
        if date_parts and date_parts[0] and date_parts[0][0] is not None:
            try:
                year = int(date_parts[0][0])
            except (TypeError, ValueError):
                year = None

        doi = item.get("DOI")
        url = item.get("URL") or item.get("url")

        abstract = item.get("abstract", "") or ""
        if abstract:
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()

        # Container title (venue → journal)
        container = item.get("container-title") or []
        journal = container[0] if container else None

        publisher = item.get("publisher")

        # Volume / issue / pages
        volume = item.get("volume")
        issue = item.get("issue")
        page = item.get("page")

        # ISSN / ISBN (first of each)
        issns = item.get("ISSN", []) or []
        issn = issns[0] if issns else None
        isbns = item.get("ISBN", []) or []
        isbn = isbns[0] if isbns else None

        # References
        references: List[str] = []
        for ref in item.get("reference", []) or []:
            rdoi = ref.get("DOI")
            if rdoi:
                references.append(rdoi)
            else:
                unstructured = ref.get("unstructured") or ref.get("article-title")
                if unstructured:
                    references.append(unstructured)

        # Funders (preserved in raw)
        funders = [
            {
                "name": f.get("name"),
                "doi": f.get("DOI"),
                "award": f.get("award") or [],
            }
            for f in item.get("funder", []) or []
        ]

        # License (preserved in raw)
        licenses = item.get("license") or []
        license_obj = None
        if licenses:
            lic = licenses[0]
            license_obj = {
                "url": lic.get("URL"),
                "version": lic.get("content-version"),
                "start": lic.get("start", {}).get("date-time")
                if isinstance(lic.get("start"), dict) else lic.get("start"),
            }

        is_referenced_by = item.get("is-referenced-by-count", 0) or 0
        subjects = item.get("subject", []) or []

        return Paper(
            title=item.get("title", [""])[0] if item.get("title") else "",
            authors=authors,
            year=year,
            abstract=abstract,
            doi=doi,
            url=url,
            source=self.name,
            citations_count=int(is_referenced_by),
            references=references,
            keywords=[],
            pdf_url=None,
            issn=issn,
            isbn=isbn,
            publisher=publisher,
            journal=journal,
            volume=volume,
            issue=issue,
            pages=page,
            language=item.get("language"),
            paper_type=item.get("type"),
            fields_of_study=list(subjects),
            raw={
                "type": item.get("type"),
                "issn_list": issns,
                "isbn_list": isbns,
                "funders": funders,
                "license": license_obj,
                "subject": subjects,
                "reference_count": item.get("references-count", 0),
                "score": item.get("score"),
            },
        )


__all__ = ["CrossrefScraper"]
