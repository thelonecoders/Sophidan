"""
metadata_enricher.py
====================

Cross-source metadata enrichment service.

:class:`MetadataEnricher` augments :class:`Paper` records with
metadata from a configurable list of upstream sources, applying
deterministic conflict-resolution rules:

* **Field-level merge** — for each :class:`Paper` field, the
  enricer prefers the first source that supplies a non-empty value
  in priority order (Crossref → OpenAlex → Semantic Scholar →
  OpenCitations → Unpaywall → ORCID).
* **Discrepancy logging** — when two sources supply conflicting
  non-empty values for the same field (e.g. different journal
  names), an ``INFO`` log entry is emitted for audit.
* **Raw payloads preserved** — every source's full payload is
  stashed under ``paper.raw['enrich_sources'][<source>]`` so
  downstream consumers can inspect the disagreements.

Conflict resolution policy
--------------------------
The order is: ``crossref`` (most authoritative for DOI-registered
metadata), then ``openalex`` (curated), then ``semantic_scholar``
(graph-curated), then ``opencitations`` (Crossref-derived), then
``unpaywall`` (OA status), then ``orcid`` (author disambiguation).
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .._compat import Paper, get_logger

logger = logging.getLogger(__name__)


class MetadataEnricher:
    """Enrich :class:`Paper` records with metadata from multiple sources."""

    # Default source priority — first occurrence wins for each field.
    DEFAULT_SOURCES: List[str] = [
        "crossref",
        "openalex",
        "semantic_scholar",
        "opencitations",
        "unpaywall",
        "orcid",
    ]

    def __init__(
        self,
        crossref_scraper: Optional[Any] = None,
        openalex_scraper: Optional[Any] = None,
        semantic_scholar_scraper: Optional[Any] = None,
        opencitations_scraper: Optional[Any] = None,
        unpaywall_scraper: Optional[Any] = None,
        orcid_scraper: Optional[Any] = None,
    ) -> None:
        """Initialize a :class:`MetadataEnricher`.

        Args:
            crossref_scraper: Optional pre-built :class:`CrossrefScraper`.
            openalex_scraper: Optional pre-built :class:`OpenAlexScraper`.
            semantic_scholar_scraper: Optional pre-built
                :class:`SemanticScholarScraper`.
            opencitations_scraper: Optional pre-built
                :class:`OpenCitationsScraper`.
            unpaywall_scraper: Optional pre-built
                :class:`UnpaywallScraper`.
            orcid_scraper: Optional pre-built :class:`ORCIDScraper`.
        """
        self.logger: logging.Logger = get_logger(__name__)
        self._scrapers: Dict[str, Any] = {
            "crossref": crossref_scraper,
            "openalex": openalex_scraper,
            "semantic_scholar": semantic_scholar_scraper,
            "opencitations": opencitations_scraper,
            "unpaywall": unpaywall_scraper,
            "orcid": orcid_scraper,
        }
        self._discrepancies: List[Dict[str, Any]] = []

    # -- public API ------------------------------------------------------

    def enrich(
        self,
        paper: Paper,
        sources: Optional[List[str]] = None,
    ) -> Paper:
        """Enrich ``paper`` with metadata from the requested sources.

        Args:
            paper: A :class:`Paper` to enrich (mutated in place).
            sources: Ordered list of source names (defaults to
                :attr:`DEFAULT_SOURCES`).  Sources that fail to load
                are skipped.

        Returns:
            The same :class:`Paper` (for chaining).
        """
        if paper is None:
            return paper
        source_order = sources or self.DEFAULT_SOURCES
        per_source_papers: Dict[str, Paper] = {}
        for source_name in source_order:
            scraper = self._get_scraper(source_name)
            if scraper is None:
                continue
            fetched = self._fetch_from(scraper, source_name, paper)
            if fetched is not None:
                per_source_papers[source_name] = fetched

        if not per_source_papers:
            self.logger.debug(
                "MetadataEnricher: no sources succeeded for DOI=%s",
                getattr(paper, "doi", None),
            )
            return paper

        # Apply field-level merge in priority order.
        for source_name in source_order:
            fetched = per_source_papers.get(source_name)
            if fetched is None:
                continue
            self._merge_fields(paper, fetched, source_name)

        # Stash per-source payloads on paper.raw.
        raw = paper.raw if isinstance(paper.raw, dict) else {}
        raw["enrich_sources"] = {
            src: p.to_dict() for src, p in per_source_papers.items()
        }
        if self._discrepancies:
            raw["enrich_discrepancies"] = list(self._discrepancies)
            self._discrepancies = []
        paper.raw = raw
        return paper

    def enrich_batch(
        self,
        papers: List[Paper],
        sources: Optional[List[str]] = None,
    ) -> List[Paper]:
        """Enrich many papers in sequence.

        Args:
            papers: List of :class:`Paper` to enrich.
            sources: Source-priority list (see :meth:`enrich`).

        Returns:
            The same list (mutated in place).
        """
        for paper in papers:
            try:
                self.enrich(paper, sources=sources)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "MetadataEnricher: failed for %s: %s",
                    getattr(paper, "doi", "<no-doi>"),
                    exc,
                )
        return papers

    # -- internal helpers ------------------------------------------------

    def _get_scraper(self, name: str) -> Optional[Any]:
        """Return the scraper instance for ``name``, building lazily."""
        existing = self._scrapers.get(name)
        if existing is not None:
            return existing
        try:
            if name == "crossref":
                from ..crossref_scraper import CrossrefScraper  # type: ignore
                scraper: Optional[Any] = CrossrefScraper(rate_limit=2.0)
            elif name == "openalex":
                from ..openalex_scraper import OpenAlexScraper  # type: ignore
                scraper = OpenAlexScraper(rate_limit=5.0)
            elif name == "semantic_scholar":
                from ..semantic_scholar_scraper import SemanticScholarScraper  # type: ignore
                scraper = SemanticScholarScraper(rate_limit=0.33)
            elif name == "opencitations":
                from ..opencitations_scraper import OpenCitationsScraper  # type: ignore
                scraper = OpenCitationsScraper(rate_limit=3.0)
            elif name == "unpaywall":
                from ..unpaywall_scraper import UnpaywallScraper  # type: ignore
                scraper = UnpaywallScraper(rate_limit=5.0)
            elif name == "orcid":
                from ..orcid_scraper import ORCIDScraper  # type: ignore
                scraper = ORCIDScraper()
            else:
                self.logger.warning("Unknown source: %r", name)
                scraper = None
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Could not build %s scraper: %s", name, exc)
            scraper = None
        self._scrapers[name] = scraper
        return scraper

    def _fetch_from(
        self,
        scraper: Any,
        source_name: str,
        paper: Paper,
    ) -> Optional[Paper]:
        """Fetch the same paper from one source (by DOI when available)."""
        try:
            if source_name == "opencitations":
                # OpenCitations doesn't return a Paper by default —
                # only metadata + citations.  Wrap into a Paper.
                meta = scraper.fetch_metadata(paper.doi) if paper.doi else {}
                if not meta:
                    return None
                return Paper(
                    title=meta.get("title") or paper.title,
                    authors=paper.authors,
                    abstract=paper.abstract,
                    year=_safe_int(meta.get("year")) or paper.year,
                    doi=paper.doi,
                    url=paper.url,
                    source=source_name,
                    citations_count=paper.citations_count,
                    references=paper.references,
                    keywords=paper.keywords,
                    pdf_url=paper.pdf_url,
                    publisher=paper.publisher,
                    journal=meta.get("journal") or paper.journal,
                    volume=meta.get("volume") or paper.volume,
                    issue=meta.get("issue") or paper.issue,
                    pages=meta.get("page") or paper.pages,
                    language=paper.language,
                    paper_type=meta.get("type") or paper.paper_type,
                    fields_of_study=paper.fields_of_study,
                    raw={"opencitations": meta},
                )
            if source_name == "unpaywall":
                # Unpaywall enriches the OA URL/PDF on paper.
                if not paper.doi:
                    return None
                oa = scraper.fetch_by_doi(paper.doi)
                if oa is None:
                    return None
                return Paper(
                    title=oa.title or paper.title,
                    authors=paper.authors,
                    abstract=paper.abstract,
                    year=oa.year or paper.year,
                    doi=paper.doi,
                    url=oa.oa_url or paper.url,
                    source=source_name,
                    citations_count=paper.citations_count,
                    references=paper.references,
                    keywords=paper.keywords,
                    pdf_url=oa.pdf_url or paper.pdf_url,
                    publisher=oa.publisher or paper.publisher,
                    journal=oa.journal or paper.journal,
                    volume=paper.volume,
                    issue=paper.issue,
                    pages=paper.pages,
                    language=paper.language,
                    paper_type=paper.paper_type,
                    fields_of_study=paper.fields_of_study,
                    raw={"oa": oa.to_dict()},
                )
            if source_name == "orcid":
                # ORCID is author-centric; not useful for paper-level enrichment.
                return None
            # Crossref / OpenAlex / Semantic Scholar: fetch by DOI.
            if not paper.doi:
                return None
            return scraper.fetch_by_doi(paper.doi)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(
                "MetadataEnricher: %s fetch failed for %s: %s",
                source_name, getattr(paper, "doi", "<no-doi>"), exc,
            )
            return None

    def _merge_fields(self, target: Paper, source: Paper, source_name: str) -> None:
        """Merge non-empty fields from ``source`` into ``target``.

        Conflict resolution: ``target`` retains the first non-empty
        value encountered (i.e. highest-priority source); any
        conflicting non-empty value from ``source`` is logged.
        """
        if source is None:
            return
        # Field-by-field merge for scalar / list values.
        self._merge_scalar(target, source, "title", source_name)
        self._merge_scalar(target, source, "abstract", source_name)
        self._merge_scalar(target, source, "doi", source_name)
        self._merge_scalar(target, source, "url", source_name)
        self._merge_scalar(target, source, "pdf_url", source_name)
        self._merge_scalar(target, source, "publisher", source_name)
        self._merge_scalar(target, source, "journal", source_name)
        self._merge_scalar(target, source, "issn", source_name)
        self._merge_scalar(target, source, "isbn", source_name)
        self._merge_scalar(target, source, "volume", source_name)
        self._merge_scalar(target, source, "issue", source_name)
        self._merge_scalar(target, source, "pages", source_name)
        self._merge_scalar(target, source, "language", source_name)
        self._merge_scalar(target, source, "paper_type", source_name)
        self._merge_scalar(target, source, "year", source_name)
        self._merge_scalar(target, source, "citations_count", source_name,
                           prefer_max=True)
        self._merge_list(target, source, "authors", source_name)
        self._merge_list(target, source, "keywords", source_name)
        self._merge_list(target, source, "references", source_name)
        self._merge_list(target, source, "fields_of_study", source_name)

    def _merge_scalar(
        self,
        target: Paper,
        source: Paper,
        field_name: str,
        source_name: str,
        prefer_max: bool = False,
    ) -> None:
        """Merge a single scalar field with conflict logging."""
        target_val = getattr(target, field_name, None)
        source_val = getattr(source, field_name, None)
        if source_val is None or source_val == "":
            return
        if target_val is None or target_val == "":
            setattr(target, field_name, source_val)
            return
        # Both non-empty: handle conflict.
        if target_val == source_val:
            return
        if prefer_max:
            try:
                if isinstance(target_val, int) and isinstance(source_val, int):
                    if source_val > target_val:
                        setattr(target, field_name, source_val)
                    return
            except Exception:  # noqa: BLE001
                pass
        # Log discrepancy (target value preserved).
        discrepancy = {
            "field": field_name,
            "source": source_name,
            "doi": target.doi,
            "existing": str(target_val)[:120],
            "conflicting": str(source_val)[:120],
        }
        self._discrepancies.append(discrepancy)
        self.logger.info(
            "MetadataEnricher: discrepancy for %s.%s (DOI=%s): existing=%r, %s=%r",
            "paper", field_name, target.doi, target_val, source_name, source_val,
        )

    def _merge_list(
        self,
        target: Paper,
        source: Paper,
        field_name: str,
        source_name: str,
    ) -> None:
        """Merge a list field (union, de-duplicated, case-insensitive)."""
        target_list: List[str] = getattr(target, field_name, []) or []
        source_list: List[str] = getattr(source, field_name, []) or []
        if not source_list:
            return
        existing = set(x.lower() if isinstance(x, str) else str(x).lower()
                       for x in target_list)
        for item in source_list:
            key = item.lower() if isinstance(item, str) else str(item).lower()
            if key not in existing:
                target_list.append(item)
                existing.add(key)
        setattr(target, field_name, target_list)


def _safe_int(value: Any) -> Optional[int]:
    """Best-effort cast of ``value`` to ``int`` (returns ``None`` on failure)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["MetadataEnricher"]
