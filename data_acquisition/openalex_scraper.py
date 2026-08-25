"""
openalex_scraper.py
===================

Scraper for the OpenAlex REST API (``https://api.openalex.org``).

OpenAlex is a fully-open catalog of the global research system.  The
API requires no API key; providing a ``mailto`` address moves the
client into the "polite pool" which has higher rate limits and is
recommended by the project.

Features
--------
* Full-text ``search`` over works with optional filter dict
  (publication_year, author, institution, concept, venue, type,
  is_oa, has_doi, ...).
* Cursor-based pagination for fetching more than 200 results.
* Convenience fetchers for authors, institutions, venues, concepts.
* Single-record :meth:`fetch_by_id` lookup by OpenAlex ID (e.g.
  ``W2741809807``) or by DOI URL (``https://doi.org/10.1234/...``).
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional

import requests

from .base_scraper import BaseScraper, Paper, ScraperResult

logger = logging.getLogger(__name__)


class OpenAlexScraper(BaseScraper):
    """Scraper for the OpenAlex REST API."""

    BASE_URL = "https://api.openalex.org"
    SOURCE_NAME = "openalex"

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        rate_limit: float = 10.0,
        cache: Optional[Any] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: Optional[str] = None,
        mailto: str = "ars_user@example.com",
    ) -> None:
        """Initialize an :class:`OpenAlexScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            rate_limit: Requests per second (default ``10.0``, polite
                pool ceiling).
            cache: Optional response cache.
            timeout: Per-request timeout.
            max_retries: Maximum retry attempts.
            user_agent: Optional User-Agent override.
            mailto: ``mailto`` query parameter; moves the client into
                the polite pool (higher rate limit).
        """
        super().__init__(
            proxy_manager=proxy_manager,
            rate_limit=rate_limit,
            cache=cache,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent,
        )
        self.mailto = mailto

    # -- public API ------------------------------------------------------

    def search(
        self,
        query: str,
        max_results: int = 50,
        filters: Optional[Mapping[str, Any]] = None,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search OpenAlex for works matching ``query``.

        Args:
            query: Free-text search string.
            max_results: Maximum number of papers to return.
            filters: Optional dict of OpenAlex filter keys mapped to
                values.  Examples::

                    {
                        "publication_year": 2023,
                        "author": "John Smith",
                        "institution": "MIT",
                        "concept": "Machine learning",
                        "venue": "Nature",
                        "type": "journal-article",
                        "is_oa": True,
                        "has_doi": True,
                    }
            **kwargs: Reserved.

        Returns:
            A populated :class:`ScraperResult`.
        """
        start_ms = self._now_ms()
        errors: List[str] = []
        papers: List[Paper] = []
        raw_response: Dict[str, Any] = {}

        params: Dict[str, Any] = {
            "search": query,
            "per_page": min(max_results, 200),
            "mailto": self.mailto,
            "select": ",".join(
                [
                    "id",
                    "doi",
                    "title",
                    "publication_year",
                    "authorships",
                    "cited_by_count",
                    "abstract_inverted_index",
                    "referenced_works",
                    "primary_location",
                    "type",
                    "language",
                    "concepts",
                    "keywords",
                    "biblio",
                    "open_access",
                ]
            ),
        }

        oa_filters = self._build_filters(filters or {})
        if oa_filters:
            params["filter"] = oa_filters

        cursor = "*"
        total = 0
        try:
            self._emit_event("search.started", {"query": query})
            while cursor and len(papers) < max_results:
                params["cursor"] = cursor
                cache_key = self._cache_key(
                    "openalex", "search", query, params.get("filter", ""), cursor
                )
                resp = self._make_request(
                    "GET",
                    f"{self.BASE_URL}/works",
                    params=params,
                    cache_key=cache_key,
                )
                data = resp.json()
                total = int(data.get("meta", {}).get("count", total) or total)
                raw_response.setdefault("pages", []).append(
                    {
                        "cursor": cursor,
                        "count": len(data.get("results", [])),
                    }
                )
                for item in data.get("results", []):
                    paper = self._parse_work(item)
                    if paper is not None:
                        papers.append(paper)
                        self._emit_event(
                            "search.progress",
                            {"fetched": len(papers), "total": min(total, max_results)},
                        )
                        if len(papers) >= max_results:
                            break
                next_cursor = data.get("meta", {}).get("next_cursor")
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
        except requests.RequestException as exc:
            errors.append(f"HTTP error: {exc}")
            self.logger.error("OpenAlex request failed: %s", exc, exc_info=True)
        except ValueError as exc:
            errors.append(f"JSON decode error: {exc}")
            self.logger.error("OpenAlex JSON parse error: %s", exc, exc_info=True)

        self._emit_event("search.finished", {"count": len(papers)})
        return ScraperResult(
            source=self.name,
            query=query,
            total_results=total,
            papers=papers[:max_results],
            raw_response=raw_response,
            timestamp=datetime.now(timezone.utc).isoformat(),
            elapsed_ms=self._now_ms() - start_ms,
            errors=errors,
        )

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single OpenAlex work by its ID.

        Args:
            paper_id: OpenAlex work ID (``W2741809807``) or full URL,
                or a DOI URL (``https://doi.org/...``) which OpenAlex
                resolves via the ``/works/doi:`` prefix.

        Returns:
            A :class:`Paper` or ``None``.
        """
        path = self._normalize_work_id(paper_id)
        try:
            cache_key = self._cache_key("openalex", "work", path)
            resp = self._make_request(
                "GET",
                f"{self.BASE_URL}/works/{path}",
                params={"mailto": self.mailto},
                cache_key=cache_key,
            )
            data = resp.json()
            return self._parse_work(data)
        except (requests.RequestException, ValueError) as exc:
            self.logger.error("OpenAlex fetch_by_id(%s) failed: %s", paper_id, exc)
            return None

    def fetch_authors(self, name: str) -> List[Dict[str, Any]]:
        """Search the ``/authors`` endpoint by name.

        Args:
            name: Author display name (or substring).

        Returns:
            A list of author dicts (raw OpenAlex payloads).
        """
        return self._search_entity("authors", name)

    def fetch_institutions(self, name: str) -> List[Dict[str, Any]]:
        """Search the ``/institutions`` endpoint by name."""
        return self._search_entity("institutions", name)

    def fetch_venues(self, name: str) -> List[Dict[str, Any]]:
        """Search the ``/venues`` endpoint by name."""
        return self._search_entity("venues", name)

    def fetch_concepts(self, name: str) -> List[Dict[str, Any]]:
        """Search the ``/concepts`` endpoint by name.

        Note: the ``/concepts`` endpoint is deprecated by OpenAlex but
        remains available; we keep this for legacy callers.
        """
        return self._search_entity("concepts", name)

    # -- helpers ---------------------------------------------------------

    def _search_entity(self, entity: str, name: str) -> List[Dict[str, Any]]:
        """Generic search over an OpenAlex entity endpoint."""
        params = {"search": name, "mailto": self.mailto, "per_page": 25}
        try:
            cache_key = self._cache_key("openalex", entity, name)
            resp = self._make_request(
                "GET",
                f"{self.BASE_URL}/{entity}",
                params=params,
                cache_key=cache_key,
            )
            data = resp.json()
            return data.get("results", []) or []
        except (requests.RequestException, ValueError) as exc:
            self.logger.error("OpenAlex %s search failed: %s", entity, exc)
            return []

    def _normalize_work_id(self, paper_id: str) -> str:
        """Normalize an OpenAlex identifier for use in a URL path."""
        pid = paper_id.strip()
        if pid.startswith("https://doi.org/"):
            return "doi:" + pid[len("https://doi.org/") :]
        if pid.startswith("doi:"):
            return pid
        if pid.startswith("https://openalex.org/"):
            return pid[len("https://openalex.org/") :]
        # Bare ID like W2741809807 — use as-is.
        return pid

    def _build_filters(self, filters: Mapping[str, Any]) -> str:
        """Translate a Python dict of filters into an OpenAlex filter string.

        OpenAlex filter syntax uses ``key:value`` joined by ``,``.
        Boolean ``True`` becomes ``true``, ``False`` -> ``false``.
        Date ranges can be passed as ``"2020-2023"`` strings.
        """
        out: List[str] = []
        for k, v in filters.items():
            if v is None:
                continue
            if isinstance(v, bool):
                out.append(f"{k}:{'true' if v else 'false'}")
            elif isinstance(v, (list, tuple)):
                joined = "|".join(str(x) for x in v if x is not None)
                if joined:
                    out.append(f"{k}:{joined}")
            else:
                out.append(f"{k}:{v}")
        return ",".join(out)

    def _parse_work(self, item: Mapping[str, Any]) -> Optional[Paper]:
        """Convert an OpenAlex ``work`` JSON object to a :class:`Paper`."""
        if not isinstance(item, Mapping):
            return None
        title = (item.get("title") or "").strip()
        if not title:
            return None

        authors: List[str] = []
        for authorship in item.get("authorships", []) or []:
            author_obj = authorship.get("author") or {}
            name = author_obj.get("display_name") or ""
            if name:
                authors.append(name)

        abstract = self._reconstruct_abstract(item.get("abstract_inverted_index"))

        doi = item.get("doi") or ""
        if doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/") :]

        primary_location = item.get("primary_location") or {}
        source_obj = primary_location.get("source") or {}
        pdf_url = None
        best_oa = primary_location.get("best_oa_location") or {}
        if isinstance(best_oa, Mapping):
            pdf_url = best_oa.get("pdf_url")
        if not pdf_url:
            for loc_field in ("locations", "locations_count"):
                # OpenAlex doesn't expose a "best_oa_location" under
                # primary_location reliably; also check open_access.
                pass
        open_access = item.get("open_access") or {}
        if not pdf_url and isinstance(open_access, Mapping):
            oa_url = open_access.get("oa_url")
            if oa_url:
                pdf_url = oa_url

        issn: Optional[str] = None
        if isinstance(source_obj, Mapping):
            issns = source_obj.get("issn") or []
            if issns:
                issn = issns[0]

        biblio = item.get("biblio") or {}
        volume = biblio.get("volume") if isinstance(biblio, Mapping) else None
        issue = biblio.get("issue") if isinstance(biblio, Mapping) else None
        first_page = biblio.get("first_page") if isinstance(biblio, Mapping) else None
        last_page = biblio.get("last_page") if isinstance(biblio, Mapping) else None
        pages: Optional[str] = None
        if first_page and last_page and first_page != last_page:
            pages = f"{first_page}-{last_page}"
        elif first_page:
            pages = str(first_page)

        keywords: List[str] = []
        for kw in item.get("keywords", []) or []:
            name = kw.get("keyword") or kw.get("display_name") or ""
            if name:
                keywords.append(name)
        for concept in item.get("concepts", []) or []:
            display = concept.get("display_name") or ""
            if display:
                keywords.append(display)

        references = [
            r.replace("https://openalex.org/", "")
            for r in (item.get("referenced_works") or [])
        ]

        work_id = item.get("id") or ""
        if work_id.startswith("https://openalex.org/"):
            work_id = work_id[len("https://openalex.org/") :]

        fields_of_study: List[str] = []
        for concept in item.get("concepts", []) or []:
            level = concept.get("level")
            if level == 0:  # top-level concepts only
                display = concept.get("display_name") or ""
                if display:
                    fields_of_study.append(display)

        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            year=item.get("publication_year"),
            doi=doi or None,
            url=work_id and f"https://openalex.org/{work_id}" or None,
            source=self.name,
            citations_count=item.get("cited_by_count"),
            references=references,
            keywords=keywords,
            pdf_url=pdf_url,
            issn=issn,
            isbn=None,
            publisher=source_obj.get("host_organization_name") if isinstance(source_obj, Mapping) else None,
            journal=source_obj.get("display_name") if isinstance(source_obj, Mapping) else None,
            volume=str(volume) if volume else None,
            issue=str(issue) if issue else None,
            pages=pages,
            language=item.get("language"),
            paper_type=item.get("type"),
            fields_of_study=fields_of_study,
            raw=dict(item),
        )

    @staticmethod
    def _reconstruct_abstract(inverted_index: Optional[Mapping[str, List[int]]]) -> str:
        """Rebuild an abstract string from OpenAlex's inverted-index form.

        Args:
            inverted_index: A mapping of word -> list of token positions.

        Returns:
            The reconstructed abstract (whitespace-joined).
        """
        if not inverted_index:
            return ""
        total = 0
        for positions in inverted_index.values():
            total = max(total, max(positions) + 1 if positions else 0)
        if total == 0:
            return ""
        tokens: List[str] = [""] * total
        for word, positions in inverted_index.items():
            for pos in positions:
                if 0 <= pos < total:
                    tokens[pos] = word
        return " ".join(t for t in tokens if t)


__all__ = ["OpenAlexScraper"]
