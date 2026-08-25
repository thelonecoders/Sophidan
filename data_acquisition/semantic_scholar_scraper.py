"""
semantic_scholar_scraper.py
===========================

Scraper for the Semantic Scholar Graph API
(``https://api.semanticscholar.org/graph/v1``).

Capabilities
------------
* :meth:`search` — full-text search over the corpus with optional
  ``year`` and ``venue`` filters and selectable field projection.
* :meth:`fetch_by_id` — single-paper lookup accepting any S2-supported
  identifier (``CORPUS_ID:``, ``DOI:``, ``ARXIV:``, ``PMID:``,
  ``PMCID:``, ``ACL:``, ``MAG:"``) by delegating to ``/paper/{id}``.
* :meth:`fetch_references` / :meth:`fetch_citations` — for building
  citation graphs.
* :meth:`fetch_authors` / :meth:`fetch_author_papers` — author
  exploration.

Rate limiting
-------------
Semantic Scholar allows ~100 requests / 5 minutes (≈ 0.33 req/s) for
unauthenticated clients and substantially more for API-key holders.
We default to ``0.33`` r/s and react to ``HTTP 429`` with the same
exponential back-off provided by :class:`BaseScraper`.

API key handling
----------------
The API key is read from :mod:`config.settings` lazily.  The
project reuses ``settings.ai_api_key`` as the Semantic Scholar key
because the project's central settings object already maps it to
"third-party AI / data API keys" — document this clearly in your
deployment notes.  A direct ``api_key`` constructor argument takes
precedence for tests / overrides.
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

import requests

from .base_scraper import BaseScraper, Paper, ScraperResult

logger = logging.getLogger(__name__)


def _load_settings() -> Any:
    """Lazily import :mod:`config.settings` and return the module.

    Returns ``None`` if the module is unavailable (e.g. in unit tests).
    The function is intentionally tiny so callers can short-circuit on
    a missing config without leaking the import error.
    """
    try:  # pragma: no cover - depends on sibling module being built
        from config import settings  # type: ignore
        return settings
    except Exception:  # noqa: BLE001
        return None


class SemanticScholarScraper(BaseScraper):
    """Scraper for the Semantic Scholar Graph API."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    SOURCE_NAME = "semantic_scholar"

    #: Default field projection used by :meth:`search` when the caller
    #: does not pass an explicit ``fields`` list.
    DEFAULT_SEARCH_FIELDS: List[str] = [
        "paperId",
        "title",
        "abstract",
        "year",
        "authors",
        "citationCount",
        "referenceCount",
        "externalIds",
        "url",
        "venue",
        "publicationTypes",
        "publicationDate",
        "journal",
        "openAccessPdf",
        "fieldsOfStudy",
        "tldr",
    ]

    #: Default fields used by :meth:`fetch_by_id`.
    DEFAULT_PAPER_FIELDS: List[str] = DEFAULT_SEARCH_FIELDS + [
        "references.externalIds",
        "references.title",
        "references.year",
        "references.authors",
    ]

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        rate_limit: float = 0.33,
        cache: Optional[Any] = None,
        timeout: float = 30.0,
        max_retries: int = 4,
        user_agent: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        """Initialize a :class:`SemanticScholarScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            rate_limit: Requests per second (default ``0.33`` ≈ 100/5min).
            cache: Optional response cache.
            timeout: Per-request timeout.
            max_retries: Maximum retry attempts.
            user_agent: Optional User-Agent override.
            api_key: Semantic Scholar API key.  If ``None``, the
                scraper attempts to load it from
                ``config.settings.ai_api_key`` (see module docstring).
        """
        super().__init__(
            proxy_manager=proxy_manager,
            rate_limit=rate_limit,
            cache=cache,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent,
        )
        self.api_key = api_key or self._resolve_api_key()

    # -- public API ------------------------------------------------------

    def search(
        self,
        query: str,
        max_results: int = 50,
        fields: Optional[List[str]] = None,
        year: Optional[str] = None,
        venue: Optional[str] = None,
        publication_types: Optional[List[str]] = None,
        fields_of_study: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search Semantic Scholar for papers.

        Args:
            query: Free-text search string.
            max_results: Maximum number of papers to return.
            fields: Optional list of S2 fields to request.  Defaults
                to :attr:`DEFAULT_SEARCH_FIELDS`.
            year: Year filter, e.g. ``"2019-2023"`` or ``"2021"``.
            venue: Venue filter (e.g. ``"Nature"``).
            publication_types: Optional list (e.g. ``["JournalArticle"]``).
            fields_of_study: Optional list of fields-of-study filters.
            **kwargs: Reserved.

        Returns:
            A populated :class:`ScraperResult`.
        """
        start_ms = self._now_ms()
        errors: List[str] = []
        papers: List[Paper] = []
        raw_response: Dict[str, Any] = {}

        # Newer S2 endpoints: /paper/search supports `query`, `year`,
        # `venue`, `fields`, `publicationTypes`, `fieldsOfStudy`.
        endpoint = f"{self.BASE_URL}/paper/search"
        requested_fields = fields or self.DEFAULT_SEARCH_FIELDS

        params: Dict[str, Any] = {
            "query": query,
            "limit": min(max_results, 100),
            "fields": ",".join(requested_fields),
        }
        if year:
            params["year"] = year
        if venue:
            params["venue"] = venue
        if publication_types:
            params["publicationTypes"] = ",".join(publication_types)
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)

        total = 0
        offset = 0
        try:
            self._emit_event("search.started", {"query": query})
            while len(papers) < max_results:
                params["offset"] = offset
                cache_key = self._cache_key(
                    "s2", "search", query, params.get("year"), params.get("venue"), offset
                )
                resp = self._make_request(
                    "GET",
                    endpoint,
                    params=params,
                    cache_key=cache_key,
                    headers=self._auth_headers(),
                )
                data = resp.json()
                if not isinstance(data, dict):
                    break
                total = int(data.get("total", total) or total)
                items = data.get("data", []) or []
                if not items:
                    break
                raw_response.setdefault("pages", []).append(
                    {"offset": offset, "count": len(items)}
                )
                for item in items:
                    paper = self._parse_paper(item)
                    if paper is not None:
                        papers.append(paper)
                        self._emit_event(
                            "search.progress",
                            {"fetched": len(papers), "total": min(total, max_results)},
                        )
                        if len(papers) >= max_results:
                            break
                offset += len(items)
                if offset >= total:
                    break
        except requests.RequestException as exc:
            errors.append(f"HTTP error: {exc}")
            self.logger.error("Semantic Scholar request failed: %s", exc, exc_info=True)
        except ValueError as exc:
            errors.append(f"JSON decode error: {exc}")
            self.logger.error("Semantic Scholar JSON error: %s", exc, exc_info=True)

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
        """Fetch a single paper by S2-supported identifier.

        Args:
            paper_id: One of:
              - S2 paper ID (40-hex char),
              - ``CORPUS_ID:215416146``,
              - ``DOI:10.1234/foo``,
              - ``ARXIV:2106.04561``,
              - ``PMID:12345678``,
              - ``PMCID:PMC1234567``,
              - ``ACL:W19-1234``,
              - ``MAG:1234567890``.

        Returns:
            A :class:`Paper` or ``None`` if not found.
        """
        pid = paper_id.strip() or ""
        try:
            cache_key = self._cache_key("s2", "paper", pid)
            resp = self._make_request(
                "GET",
                f"{self.BASE_URL}/paper/{pid}",
                params={"fields": ",".join(self.DEFAULT_PAPER_FIELDS)},
                cache_key=cache_key,
                headers=self._auth_headers(),
            )
            data = resp.json()
            if not isinstance(data, dict):
                return None
            return self._parse_paper(data)
        except (requests.RequestException, ValueError) as exc:
            self.logger.error("S2 fetch_by_id(%s) failed: %s", paper_id, exc)
            return None

    def fetch_references(self, paper_id: str, limit: int = 100) -> List[Paper]:
        """Fetch the references of a paper.

        Args:
            paper_id: The S2-supported paper identifier (see :meth:`fetch_by_id`).
            limit: Maximum number of references to return.

        Returns:
            A list of :class:`Paper` objects representing the
            references.  Empty list on failure.
        """
        return self._fetch_graph(paper_id, "references", limit)

    def fetch_citations(self, paper_id: str, limit: int = 100) -> List[Paper]:
        """Fetch the citations of a paper (papers that cite it).

        Args:
            paper_id: The S2-supported paper identifier.
            limit: Maximum number of citations to return.

        Returns:
            A list of :class:`Paper` objects.  Each entry corresponds
            to a citing paper.
        """
        return self._fetch_graph(paper_id, "citations", limit)

    def fetch_authors(self, author_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single author record by S2 author ID.

        Args:
            author_id: The Semantic Scholar author ID (digits).

        Returns:
            The raw author JSON dict, or ``None`` on failure.
        """
        try:
            cache_key = self._cache_key("s2", "author", author_id)
            resp = self._make_request(
                "GET",
                f"{self.BASE_URL}/author/{author_id}",
                params={
                    "fields": ",".join(
                        [
                            "authorId",
                            "name",
                            "affiliations",
                            "homepage",
                            "paperCount",
                            "citationCount",
                            "hIndex",
                        ]
                    )
                },
                cache_key=cache_key,
                headers=self._auth_headers(),
            )
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            self.logger.error("S2 fetch_authors(%s) failed: %s", author_id, exc)
            return None

    def fetch_author_papers(self, author_id: str, limit: int = 100) -> List[Paper]:
        """Fetch the papers written by an author.

        Args:
            author_id: The Semantic Scholar author ID.
            limit: Maximum number of papers to return.

        Returns:
            A list of :class:`Paper` objects.
        """
        papers: List[Paper] = []
        offset = 0
        try:
            while len(papers) < limit:
                cache_key = self._cache_key(
                    "s2", "author_papers", author_id, offset
                )
                resp = self._make_request(
                    "GET",
                    f"{self.BASE_URL}/author/{author_id}/papers",
                    params={
                        "fields": ",".join(self.DEFAULT_SEARCH_FIELDS),
                        "offset": offset,
                        "limit": min(100, limit - len(papers)),
                    },
                    cache_key=cache_key,
                    headers=self._auth_headers(),
                )
                data = resp.json()
                items = data.get("data", []) if isinstance(data, dict) else []
                if not items:
                    break
                for item in items:
                    paper = self._parse_paper(item)
                    if paper is not None:
                        papers.append(paper)
                offset += len(items)
                if len(items) < min(100, limit):
                    break
        except (requests.RequestException, ValueError) as exc:
            self.logger.error("S2 fetch_author_papers(%s) failed: %s", author_id, exc)
        return papers[:limit]

    # -- internal helpers ------------------------------------------------

    def _fetch_graph(self, paper_id: str, kind: str, limit: int) -> List[Paper]:
        """Fetch references or citations for a paper.

        Args:
            paper_id: The S2 paper ID.
            kind: ``"references"`` or ``"citations"``.
            limit: Maximum items.

        Returns:
            A list of :class:`Paper`.
        """
        papers: List[Paper] = []
        offset = 0
        # For citations, the actual paper is nested under "citingPaper";
        # for references, under "citedPaper".
        nested_key = "citingPaper" if kind == "citations" else "citedPaper"
        try:
            while len(papers) < limit:
                cache_key = self._cache_key("s2", kind, paper_id, offset)
                resp = self._make_request(
                    "GET",
                    f"{self.BASE_URL}/paper/{paper_id}/{kind}",
                    params={
                        "fields": ",".join(self.DEFAULT_SEARCH_FIELDS),
                        "offset": offset,
                        "limit": min(100, limit - len(papers)),
                    },
                    cache_key=cache_key,
                    headers=self._auth_headers(),
                )
                data = resp.json()
                items = data.get("data", []) if isinstance(data, dict) else []
                if not items:
                    break
                for item in items:
                    sub = item.get(nested_key, item)
                    if not isinstance(sub, dict):
                        continue
                    paper = self._parse_paper(sub)
                    if paper is not None:
                        papers.append(paper)
                offset += len(items)
                if len(items) < min(100, limit):
                    break
        except (requests.RequestException, ValueError) as exc:
            self.logger.error("S2 %s(%s) failed: %s", kind, paper_id, exc)
        return papers[:limit]

    def _auth_headers(self) -> Dict[str, str]:
        """Return the ``x-api-key`` header when an API key is configured."""
        if self.api_key:
            return {"x-api-key": self.api_key}
        return {}

    def _resolve_api_key(self) -> Optional[str]:
        """Look up the Semantic Scholar key from ``config.settings``.

        The project reuses ``settings.ai_api_key`` as the S2 key — see
        the module docstring for rationale.
        """
        settings = _load_settings()
        if settings is None:
            return None
        for attr in ("s2_api_key", "semantic_scholar_api_key", "ai_api_key"):
            value = getattr(settings, attr, None)
            if value:
                return value
        return None

    # -- parsing ---------------------------------------------------------

    def _parse_paper(self, item: Mapping[str, Any]) -> Optional[Paper]:
        """Convert a Semantic Scholar paper JSON object to :class:`Paper`."""
        if not isinstance(item, Mapping):
            return None
        title = (item.get("title") or "").strip()
        if not title:
            return None

        authors: List[str] = []
        for a in item.get("authors", []) or []:
            name = a.get("name") if isinstance(a, Mapping) else None
            if name:
                authors.append(name)

        external_ids = item.get("externalIds") or {}
        doi: Optional[str] = None
        if isinstance(external_ids, Mapping):
            doi = external_ids.get("DOI")

        open_access_pdf = item.get("openAccessPdf") or {}
        pdf_url = None
        if isinstance(open_access_pdf, Mapping):
            pdf_url = open_access_pdf.get("url")

        journal = item.get("journal") or {}
        volume = journal.get("volume") if isinstance(journal, Mapping) else None
        issue = journal.get("issue") if isinstance(journal, Mapping) else None
        pages = journal.get("pages") if isinstance(journal, Mapping) else None
        journal_name = journal.get("name") if isinstance(journal, Mapping) else None

        pub_types = item.get("publicationTypes") or []
        paper_type = pub_types[0] if isinstance(pub_types, list) and pub_types else None

        fields_of_study = item.get("fieldsOfStudy") or []
        if not isinstance(fields_of_study, list):
            fields_of_study = []

        references: List[str] = []
        ref_block = item.get("references")
        if isinstance(ref_block, list):
            for ref in ref_block:
                if not isinstance(ref, Mapping):
                    continue
                inner = ref.get("citedPaper") or ref
                ext = inner.get("externalIds") if isinstance(inner, Mapping) else None
                if isinstance(ext, Mapping) and ext.get("DOI"):
                    references.append(f"DOI:{ext['DOI']}")
                elif isinstance(inner, Mapping) and inner.get("paperId"):
                    references.append(inner["paperId"])

        return Paper(
            title=title,
            authors=authors,
            abstract=(item.get("abstract") or "").strip(),
            year=item.get("year"),
            doi=doi,
            url=item.get("url"),
            source=self.name,
            citations_count=item.get("citationCount"),
            references=references,
            keywords=[],
            pdf_url=pdf_url,
            issn=None,
            isbn=None,
            publisher=None,
            journal=journal_name,
            volume=str(volume) if volume else None,
            issue=str(issue) if issue else None,
            pages=str(pages) if pages else None,
            language=None,
            paper_type=paper_type,
            fields_of_study=list(fields_of_study),
            raw=dict(item),
        )


__all__ = ["SemanticScholarScraper"]
