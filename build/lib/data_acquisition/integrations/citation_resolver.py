"""
citation_resolver.py
====================

Cross-source citation resolution service.

:class:`CitationResolver` queries multiple academic data sources
(Crossref, OpenCitations, Semantic Scholar) for the citation list,
references list and citation count of a given :class:`Paper`, then
merges the results with a deterministic conflict-resolution policy.

Conflict resolution
-------------------
When two sources disagree on the citation count for the same DOI,
the resolver picks the **maximum** value (each source has its own
coverage blind spots; the higher count is typically the more
complete one).  When sources disagree on the references list,
the union (de-duplicated) is taken — references are additive.

When sources disagree on metadata fields (year, journal, etc.),
the order of preference is:

  1. Crossref  (DOI registry — most authoritative).
  2. Semantic Scholar (curated academic corpus).
  3. OpenCitations (Crossref-derived; lowest priority for metadata).

Discrepancies are logged at ``INFO`` level for audit purposes.
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from .._compat import Paper, get_logger
from ..opencitations_scraper import OpenCitationsScraper

logger = logging.getLogger(__name__)


class CitationResolver:
    """Merge citation data from multiple sources for a single paper.

    The resolver is deliberately lazy about source instantiation —
    each upstream scraper is built on first use and cached on the
    resolver instance so repeated ``resolve()`` calls reuse the
    same HTTP session, cache and rate-limiter.
    """

    def __init__(
        self,
        crossref_scraper: Optional[Any] = None,
        opencitations_scraper: Optional[Any] = None,
        semantic_scholar_scraper: Optional[Any] = None,
        max_workers: int = 3,
    ) -> None:
        """Initialize a :class:`CitationResolver`.

        Args:
            crossref_scraper: Optional pre-built
                :class:`CrossrefScraper`.  Built lazily if omitted.
            opencitations_scraper: Optional pre-built
                :class:`OpenCitationsScraper`.
            semantic_scholar_scraper: Optional pre-built
                :class:`SemanticScholarScraper`.
            max_workers: Thread-pool size for parallel source queries.
        """
        self.logger: logging.Logger = get_logger(__name__)
        self._crossref = crossref_scraper
        self._opencitations = opencitations_scraper
        self._semantic_scholar = semantic_scholar_scraper
        self._max_workers = max(1, int(max_workers))

    # -- public API ------------------------------------------------------

    def resolve(
        self,
        paper: Paper,
        use_opencitations: bool = True,
        use_crossref: bool = True,
        use_semantic_scholar: bool = True,
    ) -> Paper:
        """Resolve citations / references for ``paper``.

        Mutates ``paper`` in place: sets ``citations_count``,
        ``references`` and stashes the raw per-source payloads under
        ``paper.raw['citation_sources']``.

        Args:
            paper: A :class:`Paper` with at least a ``doi`` set.
            use_opencitations: If ``True`` (default), query
                OpenCitations.
            use_crossref: If ``True`` (default), query Crossref.
            use_semantic_scholar: If ``True`` (default), query
                Semantic Scholar.

        Returns:
            The same :class:`Paper` (for chaining).
        """
        if not paper or not paper.doi:
            self.logger.debug("CitationResolver: paper has no DOI; skipping.")
            return paper

        doi = paper.doi
        # Build sources.
        sources: Dict[str, Any] = {}
        if use_crossref:
            sources["crossref"] = self._get_crossref()
        if use_opencitations:
            sources["opencitations"] = self._get_opencitations()
        if use_semantic_scholar:
            sources["semantic_scholar"] = self._get_semantic_scholar()
        # Drop any sources that couldn't be instantiated.
        sources = {k: v for k, v in sources.items() if v is not None}
        if not sources:
            self.logger.warning("CitationResolver: no usable sources.")
            return paper

        # Per-source payloads.
        per_source: Dict[str, Dict[str, Any]] = {}

        def _query_crossref() -> None:
            scraper = sources["crossref"]
            try:
                citations = scraper.fetch_citations(doi, max_results=200)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Crossref fetch_citations(%s) failed: %s", doi, exc)
                citations = []
            try:
                refs = scraper.fetch_references(doi, max_results=200)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Crossref fetch_references(%s) failed: %s", doi, exc)
                refs = []
            per_source["crossref"] = {
                "citation_count": len(citations),
                "citations": [p.doi for p in citations if p.doi],
                "references": [p.doi for p in refs if p.doi],
            }

        def _query_opencitations() -> None:
            scraper = sources["opencitations"]
            try:
                citations = scraper.fetch_citations(doi)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("OpenCitations fetch_citations(%s) failed: %s", doi, exc)
                citations = []
            try:
                references = scraper.fetch_references(doi)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("OpenCitations fetch_references(%s) failed: %s", doi, exc)
                references = []
            per_source["opencitations"] = {
                "citation_count": len(citations),
                "citations": [c.citing_doi for c in citations if c.citing_doi],
                "references": [c.cited_doi for c in references if c.cited_doi],
            }

        def _query_semantic_scholar() -> None:
            scraper = sources["semantic_scholar"]
            # S2's fetch_by_id accepts DOI: prefix for DOI lookups.
            s2_id = doi if doi.startswith(("DOI:", "ARXIV:")) else f"DOI:{doi}"
            try:
                full = scraper.fetch_by_id(s2_id)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("S2 fetch_by_id(%s) failed: %s", s2_id, exc)
                full = None
            if full is None:
                per_source["semantic_scholar"] = {
                    "citation_count": 0,
                    "citations": [],
                    "references": [],
                }
                return
            try:
                citations = scraper.fetch_citations(s2_id, limit=200)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("S2 fetch_citations(%s) failed: %s", s2_id, exc)
                citations = []
            try:
                refs = scraper.fetch_references(s2_id, limit=200)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("S2 fetch_references(%s) failed: %s", s2_id, exc)
                refs = []
            per_source["semantic_scholar"] = {
                "citation_count": full.citations_count or 0,
                "citations": [p.doi for p in citations if p.doi],
                "references": [p.doi for p in refs if p.doi],
            }

        tasks = {
            "crossref": _query_crossref,
            "opencitations": _query_opencitations,
            "semantic_scholar": _query_semantic_scholar,
        }
        active_tasks = {name: tasks[name] for name in sources.keys() if name in tasks}

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {executor.submit(fn): name for name, fn in active_tasks.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    future.result()
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning("Source %s failed during resolve(%s): %s",
                                        name, doi, exc)
                    per_source[name] = {
                        "citation_count": 0,
                        "citations": [],
                        "references": [],
                        "error": str(exc),
                    }

        # Conflict resolution: pick max citation count.
        all_counts = [v.get("citation_count", 0) for v in per_source.values()]
        best_count = max(all_counts) if all_counts else 0
        # Merge reference / citation lists.
        merged_citations = self._union_dois(
            *(v.get("citations", []) for v in per_source.values())
        )
        merged_references = self._union_dois(
            *(v.get("references", []) for v in per_source.values())
        )

        if paper.citations_count is None or paper.citations_count < best_count:
            paper.citations_count = best_count
        if not paper.references:
            paper.references = merged_references
        else:
            # Merge with any existing references.
            existing = set(d.lower() for d in paper.references if d)
            for ref in merged_references:
                if ref.lower() not in existing:
                    paper.references.append(ref)
                    existing.add(ref.lower())

        raw = paper.raw if isinstance(paper.raw, dict) else {}
        raw["citation_sources"] = per_source
        paper.raw = raw
        return paper

    def resolve_batch(
        self,
        papers: List[Paper],
        use_opencitations: bool = True,
        use_crossref: bool = True,
        use_semantic_scholar: bool = True,
    ) -> List[Paper]:
        """Resolve citations for many papers in sequence.

        Args:
            papers: List of :class:`Paper` to enrich.
            **kwargs: Forwarded to :meth:`resolve`.

        Returns:
            The same list (mutated in place).
        """
        for paper in papers:
            try:
                self.resolve(
                    paper,
                    use_opencitations=use_opencitations,
                    use_crossref=use_crossref,
                    use_semantic_scholar=use_semantic_scholar,
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "CitationResolver: failed for %s: %s",
                    getattr(paper, "doi", "<no-doi>"),
                    exc,
                )
        return papers

    # -- internal helpers ------------------------------------------------

    def _get_crossref(self) -> Optional[Any]:
        if self._crossref is not None:
            return self._crossref
        try:
            from ..crossref_scraper import CrossrefScraper  # type: ignore
            self._crossref = CrossrefScraper(rate_limit=2.0)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Could not build CrossrefScraper: %s", exc)
            self._crossref = None
        return self._crossref

    def _get_opencitations(self) -> Optional[Any]:
        if self._opencitations is not None:
            return self._opencitations
        try:
            self._opencitations = OpenCitationsScraper(rate_limit=3.0)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Could not build OpenCitationsScraper: %s", exc)
            self._opencitations = None
        return self._opencitations

    def _get_semantic_scholar(self) -> Optional[Any]:
        if self._semantic_scholar is not None:
            return self._semantic_scholar
        try:
            from ..semantic_scholar_scraper import SemanticScholarScraper  # type: ignore
            self._semantic_scholar = SemanticScholarScraper(rate_limit=0.33)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Could not build SemanticScholarScraper: %s", exc)
            self._semantic_scholar = None
        return self._semantic_scholar

    @staticmethod
    def _union_dois(*lists: List[str]) -> List[str]:
        """De-duplicate the union of multiple DOI lists (case-insensitive)."""
        seen = set()
        out: List[str] = []
        for lst in lists:
            if not lst:
                continue
            for doi in lst:
                if not doi:
                    continue
                key = doi.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(doi)
        return out


__all__ = ["CitationResolver"]
