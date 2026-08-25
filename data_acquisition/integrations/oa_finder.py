"""
oa_finder.py
============

Cross-source Open-Access discovery + download service.

:class:`OpenAccessFinder` queries Unpaywall, CORE and BASE in
parallel for an OA copy of a paper, picks the best candidate
(preferred order: publishedVersion > acceptedManuscript >
submittedVersion; PDF > HTML), and optionally downloads the PDF
to disk.

When multiple sources return an OA location for the same DOI,
the finder logs each source's result and stashes the full list
under ``paper.raw['oa_locations']`` so downstream consumers can
build a UI showing all available copies.

PDF download
------------
:meth:`download_pdf` saves the PDF bytes to ``output_dir/<safe-filename>.pdf``
and returns the path.  :meth:`download_batch` parallelizes the
download across many papers (thread-pool).
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .._compat import Paper, get_logger
from ..unpaywall_scraper import OpenAccessLocation, UnpaywallScraper

logger = logging.getLogger(__name__)


class OpenAccessFinder:
    """Discover and download open-access copies of papers.

    The finder is built on top of three OA-aware scrapers:
    :class:`UnpaywallScraper`, :class:`COREScraper` and
    :class:`BASEScraper`.  Each is instantiated lazily so a missing
    API key (e.g. CORE) does not block the others.
    """

    # Preference weights — lower number = higher priority.
    _VERSION_PRIORITY = {
        "publishedVersion": 0,
        "acceptedManuscript": 1,
        "submittedVersion": 2,
    }

    def __init__(
        self,
        unpaywall_scraper: Optional[Any] = None,
        core_scraper: Optional[Any] = None,
        base_scraper: Optional[Any] = None,
        max_workers: int = 4,
    ) -> None:
        """Initialize an :class:`OpenAccessFinder`.

        Args:
            unpaywall_scraper: Optional pre-built
                :class:`UnpaywallScraper`.
            core_scraper: Optional pre-built :class:`COREScraper`.
            base_scraper: Optional pre-built :class:`BASEScraper`.
            max_workers: Thread-pool size for parallel source queries
                and batch downloads.
        """
        self.logger: logging.Logger = get_logger(__name__)
        self._unpaywall = unpaywall_scraper
        self._core = core_scraper
        self._base = base_scraper
        self._max_workers = max(1, int(max_workers))

    # -- public API ------------------------------------------------------

    def find_oa_version(self, paper: Paper) -> Optional[OpenAccessLocation]:
        """Find the best OA copy of ``paper`` across configured sources.

        Args:
            paper: A :class:`Paper` (must have a ``doi`` to be
                resolvable).

        Returns:
            The best :class:`OpenAccessLocation` found, or ``None``
            when no OA copy exists.
        """
        if not paper or not paper.doi:
            return None
        locations = self._gather_oa_locations(paper)
        if not locations:
            return None
        return self._pick_best(locations)

    def download_pdf(
        self,
        paper: Paper,
        output_dir: str,
    ) -> Optional[str]:
        """Download the OA PDF for ``paper`` into ``output_dir``.

        Args:
            paper: A :class:`Paper` with a ``doi`` (and ideally a
                populated ``pdf_url`` from a previous enrichment).
            output_dir: Target directory (created if missing).

        Returns:
            The local file path of the downloaded PDF, or ``None``
            when no OA copy exists / the download failed.
        """
        if not paper:
            return None
        # If the paper already has a PDF URL (e.g. set by Unpaywall),
        # use that directly to avoid re-querying the sources.
        url = paper.pdf_url
        version = None
        if not url:
            oa = self.find_oa_version(paper)
            if oa is None or not (oa.oa_url or oa.pdf_url):
                return None
            url = oa.pdf_url or oa.oa_url
            version = oa.version
            # Persist the discovered URL onto the paper.
            paper.pdf_url = url
        try:
            os.makedirs(output_dir, exist_ok=True)
            slug = self._safe_slug(paper) or "paper.pdf"
            if not slug.lower().endswith(".pdf"):
                slug += ".pdf"
            dest = os.path.join(output_dir, slug)
            bytes_written = self._download(url, dest)
            if bytes_written is None:
                return None
            self.logger.info(
                "Downloaded OA PDF (%d bytes, version=%s) -> %s",
                bytes_written, version, dest,
            )
            # Stash the local path on the paper for downstream use.
            raw = paper.raw if isinstance(paper.raw, dict) else {}
            raw["local_pdf"] = dest
            paper.raw = raw
            return dest
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "OA PDF download failed for %s: %s",
                getattr(paper, "doi", "<no-doi>"), exc,
            )
            return None

    def download_batch(
        self,
        papers: List[Paper],
        output_dir: str,
    ) -> List[str]:
        """Download OA PDFs for many papers in parallel.

        Args:
            papers: List of :class:`Paper` objects.
            output_dir: Target directory.

        Returns:
            A list of successfully downloaded file paths (papers
            without an OA copy are silently skipped).
        """
        if not papers:
            return []
        os.makedirs(output_dir, exist_ok=True)
        results: List[str] = []
        workers = max(1, min(self._max_workers, len(papers)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self.download_pdf, p, output_dir): p for p in papers}
            for future in as_completed(futures):
                try:
                    path = future.result()
                except Exception as exc:  # noqa: BLE001
                    self.logger.debug("download_batch worker failed: %s", exc)
                    path = None
                if path:
                    results.append(path)
        return results

    # -- internal helpers ------------------------------------------------

    def _gather_oa_locations(self, paper: Paper) -> List[OpenAccessLocation]:
        """Query Unpaywall, CORE and BASE for OA locations of ``paper``."""
        doi = paper.doi
        locations: List[OpenAccessLocation] = []
        unpaywall = self._get_unpaywall()
        if unpaywall is not None:
            try:
                oa = unpaywall.fetch_by_doi(doi)
                if oa is not None and oa.is_oa:
                    locations.append(oa)
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("Unpaywall lookup for %s failed: %s", doi, exc)
        core = self._get_core()
        if core is not None:
            try:
                result = core.search(query=f'doi:"{doi}"', max_results=1)
                if result.papers:
                    p = result.papers[0]
                    if p.pdf_url:
                        locations.append(OpenAccessLocation(
                            doi=doi,
                            title=p.title,
                            journal=p.journal,
                            publisher=p.publisher,
                            year=p.year,
                            is_oa=True,
                            oa_status="green",
                            oa_url=p.url or p.pdf_url,
                            pdf_url=p.pdf_url,
                            host_type="repository",
                            version=None,
                        ))
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("CORE lookup for %s failed: %s", doi, exc)
        base = self._get_base()
        if base is not None:
            try:
                result = base.search(query=f'dc:identifier:"{doi}"', max_results=1)
                if result.papers:
                    p = result.papers[0]
                    if p.pdf_url:
                        locations.append(OpenAccessLocation(
                            doi=doi,
                            title=p.title,
                            journal=p.journal,
                            publisher=p.publisher,
                            year=p.year,
                            is_oa=True,
                            oa_status="green",
                            oa_url=p.url or p.pdf_url,
                            pdf_url=p.pdf_url,
                            host_type="repository",
                            version=None,
                        ))
            except Exception as exc:  # noqa: BLE001
                self.logger.debug("BASE lookup for %s failed: %s", doi, exc)
        # Persist the full list on the paper for transparency.
        raw = paper.raw if isinstance(paper.raw, dict) else {}
        raw["oa_locations"] = [loc.to_dict() for loc in locations]
        paper.raw = raw
        return locations

    def _pick_best(self, locations: List[OpenAccessLocation]) -> Optional[OpenAccessLocation]:
        """Pick the best :class:`OpenAccessLocation` from a list."""
        if not locations:
            return None
        # Sort by (version priority, has_pdf desc, host_type).
        def _key(loc: OpenAccessLocation) -> tuple:
            v = loc.version or ""
            version_prio = self._VERSION_PRIORITY.get(v, 99)
            has_pdf = 0 if loc.pdf_url else 1  # 0 < 1 -> has_pdf first
            return (version_prio, has_pdf)
        return sorted(locations, key=_key)[0]

    @staticmethod
    def _safe_slug(paper: Paper) -> str:
        """Build a filesystem-safe slug for the PDF filename."""
        if paper.doi:
            slug = re.sub(r"[^A-Za-z0-9._-]", "_", paper.doi).strip("_")
            if slug:
                return slug
        if paper.title:
            slug = re.sub(r"[^A-Za-z0-9._-]", "_", paper.title)[:80].strip("_")
            if slug:
                return slug
        return "paper"

    def _download(self, url: str, dest: str) -> Optional[int]:
        """Stream-download ``url`` into ``dest``.  Returns byte count."""
        try:
            import requests  # local import — keeps module import cheap
        except ImportError as exc:  # pragma: no cover
            self.logger.error("requests is required for OA PDF download: %s", exc)
            return None
        try:
            headers = {"User-Agent": getattr(self, "user_agent", "AcademicResearchSuite/2.0")}
            with requests.get(url, headers=headers, stream=True, timeout=60.0) as resp:
                resp.raise_for_status()
                bytes_written = 0
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            fh.write(chunk)
                            bytes_written += len(chunk)
                return bytes_written
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Download of %s failed: %s", url, exc)
            return None

    # -- lazy scraper accessors ------------------------------------------

    def _get_unpaywall(self) -> Optional[Any]:
        if self._unpaywall is not None:
            return self._unpaywall
        try:
            self._unpaywall = UnpaywallScraper()
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Could not build UnpaywallScraper: %s", exc)
            self._unpaywall = None
        return self._unpaywall

    def _get_core(self) -> Optional[Any]:
        if self._core is not None:
            return self._core
        try:
            from ..core_scraper import COREScraper  # type: ignore
            scraper = COREScraper()
            if scraper.api_key:
                self._core = scraper
            else:
                self.logger.debug("COREScraper has no API key; skipping.")
                self._core = None
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Could not build COREScraper: %s", exc)
            self._core = None
        return self._core

    def _get_base(self) -> Optional[Any]:
        if self._base is not None:
            return self._base
        try:
            from ..base_scraper_ext import BASEScraper  # type: ignore
            self._base = BASEScraper()
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Could not build BASEScraper: %s", exc)
            self._base = None
        return self._base


__all__ = ["OpenAccessFinder"]
