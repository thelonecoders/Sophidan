"""
opencitations_scraper.py
========================

Scraper / enricher for the **OpenCitations COCI** API
(``https://opencitations.net/index/coci/api/v1/``).

OpenCitations is a non-profit infrastructure providing open citation
data harvested from Crossref, PubMed Central and other sources.
**No API key is required** — the COCI endpoint is fully open data.

Capabilities
------------
* :meth:`fetch_citations` — list DOIs that cite a given DOI.
* :meth:`fetch_references` — list DOIs that a given DOI cites.
* :meth:`fetch_citation_count` — total citation count for a DOI.
* :meth:`fetch_metadata` — raw COCI metadata for a DOI.
* :meth:`enrich_paper_citations` — attach citation list to a
  :class:`Paper` (mutates in place).

The :class:`Citation` dataclass normalises the upstream COCI record
into a small, stable shape suitable for citation-graph builders.
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from ._compat import BaseScraper, Paper, ScraperResult, get_logger

logger = logging.getLogger(__name__)


@dataclass
class Citation:
    """Normalised OpenCitations citation record.

    Attributes:
        citing_doi: DOI of the citing paper (the one that *makes*
            the citation).
        cited_doi: DOI of the cited paper (the one *being cited*).
        creation_date: ISO-8601 date string of the citing paper's
            creation/issue date.
        author: First-author string of the citing paper, if known.
        journal: Source journal of the citing paper.
        timespan: OpenCitations "timespan" string describing how
            long after publication of the cited paper the citation
            occurred (e.g. ``"P5Y"``).
    """

    citing_doi: Optional[str] = None
    cited_doi: Optional[str] = None
    creation_date: Optional[str] = None
    author: Optional[str] = None
    journal: Optional[str] = None
    timespan: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict of this citation."""
        return asdict(self)

    @classmethod
    def from_coci(cls, payload: Mapping[str, Any]) -> "Citation":
        """Build a :class:`Citation` from a COCI record dict.

        Args:
            payload: A single record from the COCI API response
                (one entry from the ``/references`` or
                ``/citations`` JSON array).

        Returns:
            A populated :class:`Citation`.
        """
        if not isinstance(payload, Mapping):
            return cls()
        return cls(
            citing_doi=payload.get("citing") or payload.get("citing_doi"),
            cited_doi=payload.get("cited") or payload.get("cited_doi"),
            creation_date=payload.get("creation") or payload.get("creation_date"),
            author=payload.get("author") or payload.get("first_author"),
            journal=payload.get("journal") or payload.get("source_title"),
            timespan=payload.get("timespan"),
        )


class OpenCitationsScraper(BaseScraper):
    """Scraper for the OpenCitations COCI API."""

    BASE_URL = "https://opencitations.net/index/coci/api/v1"
    SOURCE_NAME = "opencitations"

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        rate_limit: float = 3.0,
        cache: Optional[Any] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: Optional[str] = None,
    ) -> None:
        """Initialize an :class:`OpenCitationsScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            rate_limit: Maximum requests per second (default ``3`` —
                OpenCitations asks clients to be polite).
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

    # -- BaseScraper interface -------------------------------------------

    def search(self, query: str, **kwargs: Any) -> ScraperResult:
        """OpenCitations does not expose a free-text search endpoint.

        When ``query`` looks like a DOI, this method delegates to
        :meth:`fetch_metadata` and returns a single-paper
        :class:`ScraperResult` whose ``raw_response`` contains the
        COCI metadata plus the citation list.

        Args:
            query: A DOI string.

        Returns:
            A :class:`ScraperResult` with at most one paper.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        cleaned = self._clean_doi(query)
        if not cleaned:
            result.errors.append(
                "OpenCitations does not expose a free-text search; pass a DOI."
            )
            result.elapsed_ms = self._now_ms() - start_ms
            return result
        meta = self.fetch_metadata(cleaned)
        if not meta:
            result.elapsed_ms = self._now_ms() - start_ms
            return result
        citations = self.fetch_citations(cleaned)
        paper = Paper(
            title=meta.get("title") or "",
            authors=[],
            abstract="",
            year=_safe_int(meta.get("year")),
            doi=cleaned,
            url=f"https://opencitations.net/index/coci?id={cleaned}",
            source=self.name,
            citations_count=len(citations),
            references=[c.citing_doi for c in citations if c.citing_doi],
            keywords=[],
            pdf_url=None,
            issn=None,
            isbn=None,
            publisher=None,
            journal=meta.get("journal") or meta.get("source_title"),
            volume=meta.get("volume"),
            issue=meta.get("issue"),
            pages=meta.get("page"),
            language=None,
            paper_type=meta.get("type"),
            fields_of_study=[],
            raw={
                "opencitations": meta,
                "citations": [c.to_dict() for c in citations],
            },
        )
        result.papers.append(paper)
        result.total_results = 1
        result.raw_response = meta
        result.elapsed_ms = self._now_ms() - start_ms
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single record by DOI.

        Returns a :class:`Paper` (rather than a dict) so this scraper
        can plug into the standard :class:`BaseScraper` contract.
        """
        result = self.search(paper_id)
        if result.papers:
            return result.papers[0]
        return None

    # -- COCI-specific API -----------------------------------------------

    def fetch_citations(self, doi: str) -> List[Citation]:
        """Fetch the list of DOIs that cite ``doi``.

        Args:
            doi: The DOI string whose citations should be retrieved.

        Returns:
            A list of :class:`Citation` records.  Empty on error or
            when the DOI is unknown to COCI.
        """
        cleaned = self._clean_doi(doi)
        if not cleaned:
            return []
        url = f"{self.BASE_URL}/citations/{cleaned}"
        try:
            cache_key = self._cache_key("opencitations", "citations", cleaned)
            resp = self._make_request(
                "GET", url, cache_key=cache_key,
                headers={"Accept": "application/json"},
            )
            data = resp.json()
            if isinstance(data, list):
                return [Citation.from_coci(item) for item in data]
            if isinstance(data, dict) and "citations" in data:
                return [Citation.from_coci(item) for item in data["citations"]]
            return []
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("OpenCitations fetch_citations(%s) failed: %s", doi, exc)
            return []

    def fetch_references(self, doi: str) -> List[Citation]:
        """Fetch the list of DOIs cited by ``doi``.

        Args:
            doi: The DOI string whose references should be retrieved.

        Returns:
            A list of :class:`Citation` records.  Empty on error.
        """
        cleaned = self._clean_doi(doi)
        if not cleaned:
            return []
        url = f"{self.BASE_URL}/references/{cleaned}"
        try:
            cache_key = self._cache_key("opencitations", "references", cleaned)
            resp = self._make_request(
                "GET", url, cache_key=cache_key,
                headers={"Accept": "application/json"},
            )
            data = resp.json()
            if isinstance(data, list):
                return [Citation.from_coci(item) for item in data]
            if isinstance(data, dict) and "references" in data:
                return [Citation.from_coci(item) for item in data["references"]]
            return []
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("OpenCitations fetch_references(%s) failed: %s", doi, exc)
            return []

    def fetch_citation_count(self, doi: str) -> int:
        """Return the total number of citations recorded for ``doi``.

        Args:
            doi: The DOI to look up.

        Returns:
            Integer count.  ``0`` when the DOI is unknown to COCI or
            an error occurred.
        """
        citations = self.fetch_citations(doi)
        return len(citations)

    def fetch_metadata(self, doi: str) -> Dict[str, Any]:
        """Fetch raw COCI metadata for a DOI.

        Args:
            doi: The DOI string to look up.

        Returns:
            A dict with COCI's metadata fields (``title``, ``year``,
            ``journal``, ``volume``, ``issue``, ``page``, etc.).
            Empty dict on error.
        """
        cleaned = self._clean_doi(doi)
        if not cleaned:
            return {}
        url = f"{self.BASE_URL}/metadata/{cleaned}"
        try:
            cache_key = self._cache_key("opencitations", "metadata", cleaned)
            resp = self._make_request(
                "GET", url, cache_key=cache_key,
                headers={"Accept": "application/json"},
            )
            data = resp.json()
            if isinstance(data, list):
                # COCI returns a list with a single entry.
                return data[0] if data else {}
            if isinstance(data, dict):
                return data
            return {}
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("OpenCitations fetch_metadata(%s) failed: %s", doi, exc)
            return {}

    def enrich_paper_citations(self, paper: Paper) -> Paper:
        """Attach citation list and citation count to ``paper``.

        Mutates ``paper`` in place:

          * ``paper.citations_count`` is set if it was previously
            ``None`` or zero.
          * ``paper.references`` is populated with citing DOIs (so
            it reflects the inbound citation network — this is
            deliberately distinct from Crossref's ``references``
            which are outbound).
          * ``paper.raw['opencitations']`` contains the raw COCI
            metadata dict.

        Args:
            paper: A :class:`Paper` with a ``doi`` field set.

        Returns:
            The same :class:`Paper` (for chaining).
        """
        if not paper or not paper.doi:
            return paper
        meta = self.fetch_metadata(paper.doi)
        citations = self.fetch_citations(paper.doi)
        raw = paper.raw if isinstance(paper.raw, dict) else {}
        raw["opencitations"] = meta
        raw["citations"] = [c.to_dict() for c in citations]
        paper.raw = raw
        if not paper.citations_count or paper.citations_count == 0:
            paper.citations_count = len(citations)
        if not paper.references:
            paper.references = [c.citing_doi for c in citations if c.citing_doi]
        return paper

    # -- internal helpers ------------------------------------------------

    @staticmethod
    def _clean_doi(doi: str) -> str:
        """Strip ``doi:`` / ``https://doi.org/`` prefixes from ``doi``."""
        d = (doi or "").strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
            if d.lower().startswith(prefix):
                d = d[len(prefix):]
                break
        return d.strip()


def _safe_int(value: Any) -> Optional[int]:
    """Best-effort cast of ``value`` to ``int`` (returns ``None`` on failure)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["OpenCitationsScraper", "Citation"]
