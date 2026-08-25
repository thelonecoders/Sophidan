"""
doi_lookup.py
=============

DOI-centric resolution helpers backed by the Crossref REST API and
the doi.org content-negotiation endpoint.

This module exposes :class:`DOILookup`, a self-contained helper for
turning DOIs, titles or arbitrary URLs into :class:`Paper` records
and for exporting the resulting records into common bibliographic
formats (BibTeX, RIS, CSL-JSON).

Content negotiation
-------------------
Crossref's content-negotiation endpoint
(``https://api.crossref.org/works/{doi}/transform``) responds with
BibTeX, RIS, CSL-JSON or other formats when the ``Accept`` header
specifies a recognised MIME type. We use this for the format
converters to avoid re-implementing citation formatters. The
classic doi.org landing page also honours the ``Accept`` header
when redirected from ``https://doi.org/{doi}``.

Batch resolution
----------------
:meth:`DOILookup.batch_resolve` resolves a list of DOIs in parallel
using a :class:`concurrent.futures.ThreadPoolExecutor`.
"""
from __future__ import annotations
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import requests

from ._compat import Paper, get_logger

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
DOI_URL_PREFIX = "https://doi.org/"

# Regex for extracting a DOI from a free-form URL or string.
# Crossref DOIs are case-insensitive, alphanumeric + punctuation.
DOI_REGEX = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)\b", re.IGNORECASE)

# Accepted MIME types for Crossref content negotiation.
_MIME_BIBTEX = "application/x-bibtex"
_MIME_RIS = "application/x-research-info-systems"
_MIME_CSL = "application/vnd.citationstyles.csl+json"


class DOILookup:
    """Resolve DOIs / titles / URLs into :class:`Paper` records."""

    def __init__(
        self,
        polite_email: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """Initialize the DOILookup helper.

        Args:
            polite_email: Optional contact email for Crossref's polite
                pool (improves rate limits).
            timeout: HTTP timeout per request (seconds).
            max_retries: Maximum retries on transient HTTP errors.
        """
        self.logger: logging.Logger = get_logger(__name__)
        self._polite_email = polite_email
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Resolution methods
    # ------------------------------------------------------------------
    def from_doi(self, doi: str) -> Optional[Paper]:
        """Resolve a DOI to a :class:`Paper` via the Crossref API.

        Args:
            doi: The DOI string. URL prefixes (``https://doi.org/``)
                and ``doi:`` prefixes are stripped automatically.

        Returns:
            A :class:`Paper` or ``None`` if the DOI cannot be resolved.
        """
        cleaned = self._clean_doi(doi)
        if not cleaned:
            return None
        url = f"{CROSSREF_WORKS_URL}/{cleaned}"
        try:
            data = self._get_json(url)
        except Exception as exc:
            self.logger.warning("from_doi(%s): %s", doi, exc)
            return None
        message = data.get("message", data) if isinstance(data, dict) else None
        if not message:
            return None
        return self._parse_crossref_work(message)

    def from_title(
        self,
        title: str,
        year: Optional[int] = None,
        author: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Optional[Paper]:
        """Resolve a paper by title using Crossref's bibliographic search.

        Uses Crossref's ``query.bibliographic`` parameter and ranks
        candidates by title similarity. Optionally narrows by year
        (±1 tolerance) and first-author surname.

        Args:
            title: Paper title.
            year: Optional publication year (±1 tolerance applied).
            author: Optional author surname (used as ``query.author``).
            source: Optional container-title (e.g. journal name).

        Returns:
            Best-matching :class:`Paper` or ``None``.
        """
        if not title:
            return None
        params: Dict[str, Any] = {
            "query.bibliographic": title,
            "rows": 5,
        }
        if author:
            params["query.author"] = author
        if source:
            params["query.container-title"] = source
        if self._polite_email:
            params["mailto"] = self._polite_email

        try:
            data = self._get_json(CROSSREF_WORKS_URL, params=params)
        except Exception as exc:
            self.logger.warning("from_title(%s): %s", title[:50], exc)
            return None

        items = (data.get("message", {}) or {}).get("items", []) or []
        if not items:
            return None

        normalised = self._normalise_title(title)
        best: Optional[Dict[str, Any]] = None
        best_score = -1.0
        for item in items:
            item_title = " ".join(item.get("title", []) or [])
            if not item_title:
                continue
            score = self._title_similarity(normalised, self._normalise_title(item_title))
            if year is not None:
                issued = item.get("issued", {}) or {}
                date_parts = issued.get("date-parts") or []
                if date_parts and date_parts[0] and date_parts[0][0] is not None:
                    try:
                        item_year = int(date_parts[0][0])
                        if abs(item_year - year) > 1:
                            score *= 0.5  # heavy penalty
                    except (TypeError, ValueError):
                        pass
                else:
                    score *= 0.8
            if score > best_score:
                best_score = score
                best = item

        if best is None or best_score < 0.3:
            self.logger.info(
                "from_title: no confident match for %r (best_score=%.2f)",
                title[:60],
                best_score,
            )
            return None
        return self._parse_crossref_work(best)

    def from_url(self, url: str) -> Optional[Paper]:
        """Resolve a paper from any URL containing a DOI.

        The URL is scanned for a DOI substring (``10.NNNN/...``) and
        the discovered DOI is passed to :meth:`from_doi`. If the URL
        points directly at a doi.org landing page, no scanning is
        needed.

        Args:
            url: Any URL.

        Returns:
            A :class:`Paper` or ``None``.
        """
        if not url:
            return None
        match = DOI_REGEX.search(url)
        if match:
            return self.from_doi(match.group(1))
        return None

    def batch_resolve(
        self,
        dois: List[str],
        max_workers: int = 10,
    ) -> List[Paper]:
        """Resolve a list of DOIs in parallel.

        Args:
            dois: List of DOI strings (with or without URL prefix).
            max_workers: Thread pool size.

        Returns:
            A list of resolved :class:`Paper` objects. DOIs that
            could not be resolved are silently dropped (a debug log
            message is emitted for each).
        """
        results: List[Paper] = []
        if not dois:
            return results
        max_workers = max(1, min(max_workers, 32))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.from_doi, doi): doi for doi in dois}
            for future in as_completed(futures):
                doi = futures[future]
                try:
                    paper = future.result()
                    if paper is not None:
                        results.append(paper)
                    else:
                        self.logger.debug("Could not resolve DOI: %s", doi)
                except Exception as exc:
                    self.logger.warning("batch_resolve: %s -> %s", doi, exc)
        return results

    # ------------------------------------------------------------------
    # Format converters
    # ------------------------------------------------------------------
    def to_bibtex(self, paper: Paper) -> str:
        """Convert a :class:`Paper` to a BibTeX entry string.

        Uses Crossref content negotiation when the paper has a DOI;
        otherwise falls back to a hand-rolled BibTeX template.
        """
        if paper.doi:
            try:
                return self._content_negotiate(paper.doi, _MIME_BIBTEX).strip()
            except Exception as exc:
                self.logger.debug(
                    "Content-negotiation BibTeX failed for %s: %s", paper.doi, exc
                )
        return self._fallback_bibtex(paper)

    def to_ris(self, paper: Paper) -> str:
        """Convert a :class:`Paper` to an RIS record string."""
        if paper.doi:
            try:
                return self._content_negotiate(paper.doi, _MIME_RIS).strip()
            except Exception as exc:
                self.logger.debug(
                    "Content-negotiation RIS failed for %s: %s", paper.doi, exc
                )
        return self._fallback_ris(paper)

    def to_csl_json(self, paper: Paper) -> Dict[str, Any]:
        """Convert a :class:`Paper` to a CSL-JSON dict.

        Uses Crossref content negotiation when possible.
        """
        if paper.doi:
            try:
                text = self._content_negotiate(paper.doi, _MIME_CSL)
                return json.loads(text)
            except Exception as exc:
                self.logger.debug(
                    "Content-negotiation CSL-JSON failed for %s: %s", paper.doi, exc
                )
        return self._fallback_csl(paper)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_json(
        self, url: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        headers = {"User-Agent": self._user_agent(), "Accept": "application/json"}
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                resp = self._session.get(
                    url, params=params, headers=headers, timeout=self._timeout
                )
                if resp.status_code in (429, 503):
                    delay = 2 ** attempt
                    self.logger.warning(
                        "Crossref returned %d; backing off %ds.", resp.status_code, delay
                    )
                    time.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_exc = exc
                self.logger.debug(
                    "Crossref request attempt %d failed: %s", attempt + 1, exc
                )
                time.sleep(2 ** attempt)
        if last_exc:
            raise last_exc
        raise RuntimeError("Crossref request failed.")

    def _content_negotiate(self, doi: str, mime_type: str) -> str:
        """Fetch a formatted representation via Crossref content negotiation."""
        cleaned = self._clean_doi(doi)
        url = f"https://doi.org/{cleaned}"
        headers = {
            "User-Agent": self._user_agent(),
            "Accept": mime_type,
        }
        for attempt in range(self._max_retries):
            try:
                resp = self._session.get(
                    url, headers=headers, timeout=self._timeout, allow_redirects=True
                )
                if resp.status_code in (429, 503):
                    time.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp.text
            except Exception as exc:
                self.logger.debug(
                    "Content negotiation attempt %d failed (%s): %s",
                    attempt + 1, mime_type, exc,
                )
                time.sleep(2 ** attempt)
        raise RuntimeError(
            f"Content negotiation for DOI {cleaned} ({mime_type}) failed."
        )

    def _user_agent(self) -> str:
        if self._polite_email:
            return f"AcademicResearchSuite/1.0 (mailto:{self._polite_email})"
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
    def _normalise_title(title: str) -> str:
        return re.sub(r"[^a-z0-9 ]+", " ", title.lower()).strip()

    @staticmethod
    def _title_similarity(a: str, b: str) -> float:
        """Cheap Jaccard similarity on token sets."""
        sa = set(a.split())
        sb = set(b.split())
        if not sa or not sb:
            return 0.0
        inter = len(sa & sb)
        union = len(sa | sb)
        return inter / union

    def _parse_crossref_work(self, item: Dict[str, Any]) -> Paper:
        """Map a Crossref work record into a :class:`Paper`."""
        authors: List[str] = []
        for a in item.get("author", []) or []:
            given = (a.get("given") or "").strip()
            family = (a.get("family") or "").strip()
            name = (given + " " + family).strip() or a.get("name", "")
            if name:
                authors.append(name)

        year: Optional[int] = None
        issued = item.get("issued") or {}
        date_parts = issued.get("date-parts") or []
        if date_parts and date_parts[0] and date_parts[0][0] is not None:
            try:
                year = int(date_parts[0][0])
            except (TypeError, ValueError):
                year = None

        abstract = item.get("abstract", "") or ""
        if abstract:
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()

        container = item.get("container-title") or []
        journal = container[0] if container else None

        funders = [
            {
                "name": f.get("name"),
                "doi": f.get("DOI"),
                "award": f.get("award") or [],
            }
            for f in item.get("funder", []) or []
        ]

        licenses = item.get("license") or []
        license_obj = None
        if licenses:
            lic = licenses[0]
            license_obj = {
                "url": lic.get("URL"),
                "version": lic.get("content-version"),
            }

        issns = item.get("ISSN", []) or []
        isbns = item.get("ISBN", []) or []
        subjects = item.get("subject", []) or []

        return Paper(
            title=item.get("title", [""])[0] if item.get("title") else "",
            authors=authors,
            year=year,
            abstract=abstract,
            doi=item.get("DOI"),
            url=item.get("URL"),
            source="Crossref",
            citations_count=int(item.get("is-referenced-by-count", 0) or 0),
            references=[],
            keywords=[],
            pdf_url=None,
            issn=issns[0] if issns else None,
            isbn=isbns[0] if isbns else None,
            publisher=item.get("publisher"),
            journal=journal,
            volume=item.get("volume"),
            issue=item.get("issue"),
            pages=item.get("page"),
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
            },
        )

    # ---- Fallback formatters --------------------------------------------
    @staticmethod
    def _fallback_bibtex(paper: Paper) -> str:
        """Hand-rolled BibTeX entry when Crossref negotiation fails."""
        key_parts: List[str] = []
        if paper.authors:
            last_name = paper.authors[0].split()[-1].lower()
            key_parts.append(re.sub(r"[^a-z]", "", last_name))
        if paper.year:
            key_parts.append(str(paper.year))
        if paper.title:
            word = re.sub(
                r"[^a-z]", "", paper.title.split()[0].lower()
            ) if paper.title else "untitled"
            key_parts.append(word[:3] if word else "unt")
        key = "".join(key_parts) or "untitled"

        lines = [
            f"@article{{{key},",
            f"  title = {{{paper.title}}},",
            f"  author = {{{' and '.join(paper.authors)}}},",
        ]
        if paper.year:
            lines.append(f"  year = {{{paper.year}}},")
        if paper.journal:
            lines.append(f"  journal = {{{paper.journal}}},")
        if paper.publisher:
            lines.append(f"  publisher = {{{paper.publisher}}},")
        if paper.doi:
            lines.append(f"  doi = {{{paper.doi}}},")
        if paper.url:
            lines.append(f"  url = {{{paper.url}}},")
        lines.append("}")
        return "\n".join(lines)

    @staticmethod
    def _fallback_ris(paper: Paper) -> str:
        """Hand-rolled RIS record when Crossref negotiation fails."""
        lines = ["TY  - JOUR", f"TI  - {paper.title}"]
        for a in paper.authors:
            lines.append(f"AU  - {a}")
        if paper.year:
            lines.append(f"PY  - {paper.year}")
        if paper.journal:
            lines.append(f"JO  - {paper.journal}")
        if paper.publisher:
            lines.append(f"PB  - {paper.publisher}")
        if paper.doi:
            lines.append(f"DO  - {paper.doi}")
        if paper.url:
            lines.append(f"UR  - {paper.url}")
        if paper.abstract:
            lines.append(f"AB  - {paper.abstract}")
        lines.append("ER  - ")
        return "\n".join(lines)

    @staticmethod
    def _fallback_csl(paper: Paper) -> Dict[str, Any]:
        """Hand-rolled CSL-JSON dict when Crossref negotiation fails."""
        authors_csl = []
        for a in paper.authors:
            tokens = a.split()
            if len(tokens) >= 2:
                authors_csl.append({
                    "family": tokens[-1],
                    "given": " ".join(tokens[:-1]),
                })
            else:
                authors_csl.append({"literal": a})
        csl: Dict[str, Any] = {
            "type": "article-journal",
            "title": paper.title,
            "author": authors_csl,
        }
        if paper.year:
            issued = {"date-parts": [[paper.year]]}
            csl["issued"] = issued
        if paper.journal:
            csl["container-title"] = paper.journal
        if paper.publisher:
            csl["publisher"] = paper.publisher
        if paper.doi:
            csl["DOI"] = paper.doi
        if paper.url:
            csl["URL"] = paper.url
        if paper.abstract:
            csl["abstract"] = paper.abstract
        return csl


__all__ = ["DOILookup"]
