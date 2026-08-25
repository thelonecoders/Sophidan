"""
unpaywall_scraper.py
====================

Scraper / enricher for the **Unpaywall** REST API
(``https://api.unpaywall.org/v2/{doi}``).

Unpaywall is the largest open-access (OA) status database for
scholarly articles with DOIs.  No API key is required — clients
simply identify themselves with an email address, which the
service uses to contact them in case of abuse.

Capabilities
------------
* :meth:`fetch_by_doi` — fetch a single OA location for a DOI.
* :meth:`fetch_by_doi_batch` — parallel lookup over many DOIs.
* :meth:`enrich_paper` — augment an existing :class:`Paper` with
  an :class:`OpenAccessLocation` payload (OA status, best OA URL,
  PDF link, ...).
* :meth:`enrich_papers_batch` — batch version of the above.

The module also exposes the :class:`OpenAccessLocation` dataclass,
which is reused by :mod:`data_acquisition.integrations.oa_finder`
for cross-source OA aggregation.
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
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


@dataclass
class OpenAccessLocation:
    """Normalised representation of Unpaywall's OA payload.

    Attributes:
        doi: The DOI the OA info refers to.
        title: Article title (Unpaywall returns this for context).
        journal: Journal name (Unpaywall ``journal_name``).
        publisher: Publisher name (Unpaywall ``publisher``).
        year: Publication year (Unpaywall ``year``).
        is_oa: Whether an OA version exists.
        oa_status: Unpaywall OA status — one of ``green``, ``gold``,
            ``hybrid``, ``bronze``, ``closed``.
        oa_url: Best OA URL (HTML landing page or PDF).
        pdf_url: Direct PDF link, when available.
        host_type: ``publisher`` or ``repository`` — where the OA
            copy is hosted.
        version: Version label — ``publishedVersion``,
            ``acceptedManuscript`` or ``submittedVersion``.
    """

    doi: Optional[str] = None
    title: Optional[str] = None
    journal: Optional[str] = None
    publisher: Optional[str] = None
    year: Optional[int] = None
    is_oa: bool = False
    oa_status: Optional[str] = None
    oa_url: Optional[str] = None
    pdf_url: Optional[str] = None
    host_type: Optional[str] = None
    version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict of this location."""
        return asdict(self)

    @classmethod
    def from_unpaywall(cls, payload: Mapping[str, Any]) -> "OpenAccessLocation":
        """Build an :class:`OpenAccessLocation` from Unpaywall's response.

        Args:
            payload: The parsed JSON dict returned by the
                ``/v2/{doi}`` endpoint.

        Returns:
            A populated :class:`OpenAccessLocation`.  Always returns
            an object (never ``None``); fields default to ``None``
            when the upstream payload omits them.
        """
        if not isinstance(payload, Mapping):
            return cls()
        best_oa = payload.get("best_oa_location") or {}
        if not isinstance(best_oa, Mapping):
            best_oa = {}
        year_val = payload.get("year")
        try:
            year_int = int(year_val) if year_val is not None else None
        except (TypeError, ValueError):
            year_int = None
        return cls(
            doi=payload.get("doi"),
            title=payload.get("title"),
            journal=payload.get("journal_name"),
            publisher=payload.get("publisher"),
            year=year_int,
            is_oa=bool(payload.get("is_oa", False)),
            oa_status=payload.get("oa_status"),
            oa_url=best_oa.get("url") or best_oa.get("url_for_landing_page"),
            pdf_url=best_oa.get("url_for_pdf"),
            host_type=best_oa.get("host_type"),
            version=best_oa.get("version"),
        )


class UnpaywallScraper(BaseScraper):
    """Scraper / enricher for the Unpaywall REST API."""

    BASE_URL = "https://api.unpaywall.org/v2"
    SOURCE_NAME = "unpaywall"

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        email: Optional[str] = None,
        rate_limit: float = 5.0,
        cache: Optional[Any] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: Optional[str] = None,
    ) -> None:
        """Initialize an :class:`UnpaywallScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            email: Contact email — REQUIRED by Unpaywall's ToS.
                Falls back to ``UNPAYWALL_EMAIL`` env var or
                ``config.settings.unpaywall_email``.
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
        self.email: Optional[str] = email or self._resolve_email()

    # -- BaseScraper interface -------------------------------------------

    def search(self, query: str, **kwargs: Any) -> ScraperResult:
        """Unpaywall does not expose a search endpoint.

        This method exists to satisfy the :class:`BaseScraper`
        contract; callers wanting to look up OA status for a DOI
        should use :meth:`fetch_by_doi` directly.  When called with
        a string that looks like a DOI, it transparently delegates.

        Args:
            query: A DOI string (best practice) — any other value
                will return an empty result with an explanatory
                error.

        Returns:
            A :class:`ScraperResult` containing at most one paper.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        errors: List[str] = []
        cleaned = self._clean_doi(query)
        if not cleaned:
            errors.append(
                "Unpaywall does not expose a search endpoint; pass a DOI."
            )
            result.errors = errors
            result.elapsed_ms = self._now_ms() - start_ms
            return result
        oa_loc = self.fetch_by_doi(cleaned)
        if oa_loc is not None:
            result.papers.append(self._to_paper(oa_loc))
            result.total_results = 1
        result.errors = errors
        result.elapsed_ms = self._now_ms() - start_ms
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single record by DOI (alias for :meth:`fetch_by_doi`).

        Returns a :class:`Paper` (rather than an :class:`OpenAccessLocation`)
        so that this scraper can plug into the standard
        :class:`BaseScraper` contract.
        """
        oa_loc = self.fetch_by_doi(paper_id)
        if oa_loc is None:
            return None
        return self._to_paper(oa_loc)

    # -- OA-specific API -------------------------------------------------

    def fetch_by_doi(self, doi: str) -> Optional[OpenAccessLocation]:
        """Look up the OA status of a single DOI.

        Args:
            doi: The DOI string (with or without a ``doi:`` /
                ``https://doi.org/`` prefix).

        Returns:
            An :class:`OpenAccessLocation` populated from
            Unpaywall's response, or ``None`` if not found / the API
            returned an error.
        """
        cleaned = self._clean_doi(doi)
        if not cleaned:
            return None
        if not self.email:
            self.logger.warning(
                "Unpaywall email missing — set UNPAYWALL_EMAIL to identify "
                "your client (required by the Unpaywall ToS)."
            )
            # Don't hard-fail; Unpaywall may still return a result.
        url = f"{self.BASE_URL}/{cleaned}"
        params: Dict[str, Any] = {"email": self.email or "anonymous@example.com"}
        try:
            cache_key = self._cache_key("unpaywall", "doi", cleaned)
            resp = self._make_request(
                "GET", url, params=params, cache_key=cache_key
            )
            data = resp.json()
            if not isinstance(data, dict):
                return None
            return OpenAccessLocation.from_unpaywall(data)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Unpaywall fetch_by_doi(%s) failed: %s", doi, exc)
            return None

    def fetch_by_doi_batch(
        self,
        dois: List[str],
        max_workers: int = 10,
    ) -> List[OpenAccessLocation]:
        """Look up OA status for many DOIs in parallel.

        Args:
            dois: List of DOI strings.
            max_workers: Thread-pool size (default ``10``).

        Returns:
            A list of :class:`OpenAccessLocation` objects in
            arbitrary order.  DOIs that failed are simply omitted.
        """
        if not dois:
            return []
        workers = max(1, min(max_workers, len(dois)))
        out: List[OpenAccessLocation] = []
        # Temporarily raise the per-scraper rate limit so a batch
        # lookup is not bottlenecked by a single bucket; the underlying
        # _make_request still applies the limit per call.
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self.fetch_by_doi, doi): doi for doi in dois
                }
                for future in as_completed(futures):
                    doi = futures[future]
                    try:
                        oa = future.result()
                    except Exception as exc:  # noqa: BLE001
                        self.logger.debug("Unpaywall batch: %s -> %s", doi, exc)
                        continue
                    if oa is not None:
                        out.append(oa)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Unpaywall batch lookup failed: %s", exc)
        return out

    def enrich_paper(self, paper: Paper) -> Paper:
        """Augment ``paper`` in place with Unpaywall OA info.

        Adds an :class:`OpenAccessLocation` under
        ``paper.raw['oa']`` and sets ``paper.pdf_url`` when one is
        discovered and the paper did not already have one.

        Args:
            paper: A :class:`Paper` to enrich (mutated in place).

        Returns:
            The same :class:`Paper` (for chaining).
        """
        if not paper or not paper.doi:
            return paper
        oa = self.fetch_by_doi(paper.doi)
        if oa is None:
            return paper
        raw = paper.raw if isinstance(paper.raw, dict) else {}
        raw["oa"] = oa.to_dict()
        paper.raw = raw
        if not paper.pdf_url and oa.pdf_url:
            paper.pdf_url = oa.pdf_url
        if not paper.url and oa.oa_url:
            paper.url = oa.oa_url
        if not paper.journal and oa.journal:
            paper.journal = oa.journal
        if not paper.publisher and oa.publisher:
            paper.publisher = oa.publisher
        if not paper.year and oa.year:
            paper.year = oa.year
        return paper

    def enrich_papers_batch(self, papers: List[Paper]) -> List[Paper]:
        """Batch-enrich a list of papers using :meth:`fetch_by_doi_batch`.

        Args:
            papers: List of :class:`Paper` objects to enrich
                (mutated in place).

        Returns:
            The same list (for chaining).
        """
        if not papers:
            return papers
        doi_to_papers: Dict[str, List[Paper]] = {}
        for paper in papers:
            if paper and paper.doi:
                doi_to_papers.setdefault(self._clean_doi(paper.doi), []).append(paper)
        if not doi_to_papers:
            return papers
        oa_results = self.fetch_by_doi_batch(list(doi_to_papers.keys()))
        for oa in oa_results:
            if not oa.doi:
                continue
            key = self._clean_doi(oa.doi)
            for paper in doi_to_papers.get(key, []):
                raw = paper.raw if isinstance(paper.raw, dict) else {}
                raw["oa"] = oa.to_dict()
                paper.raw = raw
                if not paper.pdf_url and oa.pdf_url:
                    paper.pdf_url = oa.pdf_url
                if not paper.url and oa.oa_url:
                    paper.url = oa.oa_url
                if not paper.journal and oa.journal:
                    paper.journal = oa.journal
                if not paper.publisher and oa.publisher:
                    paper.publisher = oa.publisher
                if not paper.year and oa.year:
                    paper.year = oa.year
        return papers

    # -- internal helpers ------------------------------------------------

    def _resolve_email(self) -> Optional[str]:
        """Resolve the contact email from env var or settings."""
        env = os.environ.get("UNPAYWALL_EMAIL")
        if env:
            return env
        settings = _load_settings()
        if settings is None:
            return None
        for attr in ("unpaywall_email", "contact_email", "polite_email"):
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

    @staticmethod
    def _to_paper(oa: OpenAccessLocation) -> Paper:
        """Build a minimal :class:`Paper` from an :class:`OpenAccessLocation`."""
        return Paper(
            title=oa.title or "",
            authors=[],
            abstract="",
            year=oa.year,
            doi=oa.doi,
            url=oa.oa_url,
            source="unpaywall",
            citations_count=None,
            references=[],
            keywords=[],
            pdf_url=oa.pdf_url,
            issn=None,
            isbn=None,
            publisher=oa.publisher,
            journal=oa.journal,
            volume=None,
            issue=None,
            pages=None,
            language=None,
            paper_type=None,
            fields_of_study=[],
            raw={"oa": oa.to_dict()},
        )


__all__ = ["UnpaywallScraper", "OpenAccessLocation"]
