"""
dblp_scraper.py
===============

Scraper for the DBLP Computer Science Bibliography REST API
(``https://dblp.org/search/publ/api``).

DBLP exposes a free, no-API-key search interface returning XML (the
default) or JSON when ``&format=json`` is requested. This scraper
uses the XML response format and parses it with the standard library
``xml.etree.ElementTree`` for maximum error tolerance and zero extra
dependencies.

The scraper supports:

* Free-text publication search with optional year / venue filters.
* Author lookup, author-paper listing, venue lookup, and direct
  publication retrieval by DBLP key.
* Author disambiguation via DBLP's PID (Person ID).

All methods return :class:`Paper` records wrapped in
:class:`ScraperResult` (for the main ``search`` entrypoint) or
``list[Paper]`` / ``dict`` (for auxiliary lookups).
"""
from __future__ import annotations
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from ._compat import BaseScraper, Paper, ScraperResult, get_logger

DBLP_BASE_URL = "https://dblp.org/search/publ/api"
DBLP_AUTHOR_URL = "https://dblp.org/search/author/api"
DBLP_VENUE_URL = "https://dblp.org/search/venue/api"


class DBLPScraper(BaseScraper):
    """Scraper for the DBLP publication search API.

    Inherits HTTP plumbing (retries, rate-limiting, proxy rotation,
    caching) from :class:`data_acquisition.base_scraper.BaseScraper`.
    """

    BASE_URL = DBLP_BASE_URL
    SOURCE_NAME = "DBLP"

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        polite_email: Optional[str] = None,
        rate_limit: float = 2.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        cache: Optional[Any] = None,
    ) -> None:
        """Initialize the DBLP scraper.

        Args:
            proxy_manager: Optional proxy manager.
            polite_email: Optional email appended to the User-Agent
                header. DBLP doesn't formally publish a polite pool
                but recommends identifying your script.
            rate_limit: Maximum requests per second (default 2.0 —
                DBLP is conservative).
            timeout: HTTP timeout in seconds.
            max_retries: Maximum number of retries on transient HTTP errors.
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
        year: Optional[int] = None,
        venue: Optional[str] = None,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search DBLP publications.

        Args:
            query: Free-text search string.
            max_results: Maximum number of records to return.
            year: Optional publication year filter.
            venue: Optional venue filter (e.g. ``"ICML"``).
            **kwargs: Reserved for future use.

        Returns:
            A :class:`ScraperResult` containing matching papers.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        params: Dict[str, Any] = {
            "q": query,
            "h": min(max_results, 1000),  # DBLP per-page cap
            "f": 0,
            "format": "xml",
        }

        try:
            xml_text = self._get_text(
                self.BASE_URL,
                params=params,
                cache_key=self._cache_key("dblp_search", query),
            )
        except Exception as exc:
            self.logger.error("DBLP search failed: %s", exc, exc_info=True)
            result.errors.append(str(exc))
            result.elapsed_ms = self._now_ms() - start_ms
            return result

        hits = self._parse_hits(xml_text)
        for hit in hits:
            if len(result.papers) >= max_results:
                break
            if year is not None and hit.get("year") and hit.get("year") != str(year):
                continue
            if venue and (hit.get("venue") or "").lower() != venue.lower():
                continue
            try:
                result.papers.append(self._hit_to_paper(hit))
            except Exception as exc:  # pragma: no cover
                result.errors.append(f"Skipped hit: {exc}")

        # DBLP reports total hits in the response header.
        result.total_results = self._parse_total(xml_text) or len(result.papers)
        result.raw_response = xml_text if len(xml_text) < 20000 else None
        result.elapsed_ms = self._now_ms() - start_ms
        self.logger.info(
            "DBLP query complete. Returning %d papers (total=%d).",
            len(result.papers),
            result.total_results,
        )
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single publication by DBLP key.

        Alias for :meth:`fetch_publication`. The ``paper_id`` is the
        DBLP record key (e.g. ``"conf/icml/Chen20"``) or full DBLP URL.

        Args:
            paper_id: DBLP record key or URL.

        Returns:
            A :class:`Paper` or ``None``.
        """
        return self.fetch_publication(paper_id)

    # ------------------------------------------------------------------
    # Auxiliary endpoints
    # ------------------------------------------------------------------
    def fetch_author(self, name: str) -> Optional[Dict[str, Any]]:
        """Search DBLP for an author by name.

        Args:
            name: Author name (e.g. ``"Jiawei Han"``).

        Returns:
            First matching author dict from DBLP's
            ``/search/author/api`` response, with keys including
            ``url``, ``author_pid``, ``info``. Returns ``None`` if no
            match.
        """
        params = {"q": name, "format": "xml", "h": 5}
        try:
            xml_text = self._get_text(DBLP_AUTHOR_URL, params=params)
        except Exception as exc:
            self.logger.error("DBLP fetch_author(%s): %s", name, exc)
            return None
        authors = self._parse_authors(xml_text)
        if not authors:
            return None
        return authors[0]

    def fetch_author_papers(self, author_pid: str, max_results: int = 200) -> List[Paper]:
        """Fetch all publications of a given author.

        Args:
            author_pid: DBLP person ID (the ``pid`` field, e.g.
                ``"h/JiaweiHan"``) **or** the full author URL.
            max_results: Maximum number of papers to return.

        Returns:
            List of :class:`Paper` records.
        """
        pid = author_pid
        if pid.startswith("http"):
            pid = pid.split("/pid/")[-1].rstrip(".html")
            if pid.endswith(".html"):
                pid = pid[: -len(".html")]

        url = f"https://dblp.org/pid/{pid}.xml"
        try:
            xml_text = self._get_text(url, params={})
        except Exception as exc:
            self.logger.error("DBLP fetch_author_papers(%s): %s", author_pid, exc)
            return []
        return self._parse_author_papers(xml_text, max_results)

    def fetch_venue(self, venue_id: str) -> Optional[Dict[str, Any]]:
        """Look up venue metadata.

        Args:
            venue_id: DBLP venue acronym or full venue URL.

        Returns:
            Venue metadata dict (``url``, ``venue``, ``acronym``,
            ``type``) or ``None`` if not found.
        """
        venue = venue_id
        if venue.startswith("http"):
            venue = venue.split("/db/")[-1] if "/db/" in venue else venue
        params = {"q": venue, "format": "xml", "h": 5}
        try:
            xml_text = self._get_text(DBLP_VENUE_URL, params=params)
        except Exception as exc:
            self.logger.error("DBLP fetch_venue(%s): %s", venue_id, exc)
            return None
        return self._parse_venue(xml_text)

    def fetch_publication(self, key: str) -> Optional[Paper]:
        """Fetch a single publication by DBLP key.

        Args:
            key: DBLP record key (e.g. ``"conf/icml/Chen20"``) **or**
                the full record URL.

        Returns:
            A :class:`Paper` or ``None`` if the record does not exist.
        """
        k = key
        if k.startswith("http"):
            k = k.split("/rec/")[-1]
            if k.endswith(".html"):
                k = k[: -len(".html")]
            if k.endswith(".xml"):
                k = k[: -len(".xml")]

        url = f"https://dblp.org/rec/{k}.xml"
        try:
            xml_text = self._get_text(url, params={})
        except Exception as exc:
            self.logger.error("DBLP fetch_publication(%s): %s", key, exc)
            return None
        hit = self._parse_single_record(xml_text)
        if not hit:
            return None
        return self._hit_to_paper(hit)

    # ------------------------------------------------------------------
    # Internal HTTP + parsing helpers
    # ------------------------------------------------------------------
    def _get_text(
        self, url: str, params: Dict[str, Any], cache_key: Optional[str] = None
    ) -> str:
        """Perform an HTTP GET via the parent's request infrastructure."""
        resp = self._make_request(
            "GET", url, params=params, headers={"Accept": "application/xml"},
            cache_key=cache_key,
        )
        return resp.text

    def _user_agent(self, polite_email: Optional[str]) -> str:
        if polite_email:
            return f"AcademicResearchSuite/1.0 (mailto:{polite_email})"
        return "AcademicResearchSuite/1.0"

    # ---- XML parsing ----------------------------------------------------
    def _parse_hits(self, xml_text: str) -> List[Dict[str, Any]]:
        """Parse a DBLP publication search XML response."""
        hits: List[Dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            self.logger.error("DBLP XML parse error: %s", exc)
            return hits

        for hit_el in root.iter("hit"):
            info_el = hit_el.find("info")
            if info_el is None:
                continue
            hits.append(self._info_to_dict(info_el))
        return hits

    def _parse_total(self, xml_text: str) -> int:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return 0
        for hits_el in root.iter("hits"):
            total = hits_el.get("total")
            if total:
                try:
                    return int(total)
                except ValueError:
                    return 0
        return 0

    def _parse_authors(self, xml_text: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            self.logger.error("DBLP author XML parse error: %s", exc)
            return out
        for hit_el in root.iter("hit"):
            url_el = hit_el.find("url")
            info_el = hit_el.find("info")
            author = {
                "url": url_el.text if url_el is not None else None,
                "author_pid": None,
                "info": self._info_to_dict(info_el) if info_el is not None else {},
            }
            if author["url"]:
                pid = (
                    author["url"].split("/pid/")[-1].rstrip(".html")
                    if "/pid/" in author["url"] else None
                )
                author["author_pid"] = pid
            out.append(author)
        return out

    def _parse_venue(self, xml_text: str) -> Optional[Dict[str, Any]]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            self.logger.error("DBLP venue XML parse error: %s", exc)
            return None
        for hit_el in root.iter("hit"):
            info_el = hit_el.find("info")
            if info_el is None:
                continue
            d = self._info_to_dict(info_el)
            return {
                "url": d.get("url"),
                "venue": d.get("venue"),
                "acronym": d.get("acronym"),
                "type": d.get("type"),
            }
        return None

    def _parse_author_papers(self, xml_text: str, max_results: int) -> List[Paper]:
        papers: List[Paper] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            self.logger.error("DBLP author papers XML parse error: %s", exc)
            return papers

        for r_el in root.iter("r"):
            if len(papers) >= max_results:
                break
            child = list(r_el)[:1]
            if not child:
                continue
            entry_el = child[0]
            fields = {k.tag: (k.text or "") for k in entry_el}
            authors: List[str] = []
            for author_el in entry_el.findall("author"):
                if author_el.text:
                    authors.append(author_el.text)
            year_raw = fields.get("year")
            try:
                year_int = int(year_raw) if year_raw else None
            except ValueError:
                year_int = None

            ee = fields.get("ee") or fields.get("doi")
            papers.append(
                Paper(
                    title=fields.get("title", "").rstrip("."),
                    authors=authors,
                    year=year_int,
                    abstract="",
                    doi=ee,
                    url=ee,
                    source=self.name,
                    citations_count=None,
                    references=[],
                    keywords=[],
                    pdf_url=None,
                    issn=None,
                    isbn=None,
                    publisher=fields.get("publisher"),
                    journal=fields.get("journal") or fields.get("booktitle"),
                    volume=fields.get("volume"),
                    issue=fields.get("number"),
                    pages=fields.get("pages"),
                    language=None,
                    paper_type=entry_el.tag,
                    fields_of_study=[],
                    raw={
                        "dblp_key": entry_el.get("key"),
                    },
                )
            )
        return papers

    def _parse_single_record(self, xml_text: str) -> Optional[Dict[str, Any]]:
        """Parse a single-record DBLP XML response (``/rec/{key}.xml``)."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            self.logger.error("DBLP record XML parse error: %s", exc)
            return None
        info_el = root.find(".//info")
        if info_el is not None:
            return self._info_to_dict(info_el)
        for tag in ("article", "inproceedings", "book", "incollection",
                    "phdthesis", "mastersthesis", "www", "proceedings"):
            el = root.find(f".//{tag}")
            if el is not None:
                fields: Dict[str, Any] = {child.tag: (child.text or "") for child in el}
                return {
                    "title": fields.get("title", "").rstrip("."),
                    "authors": [a.text for a in el.findall("author") if a.text],
                    "year": fields.get("year"),
                    "venue": fields.get("journal") or fields.get("booktitle"),
                    "doi": fields.get("ee") or fields.get("doi"),
                    "url": fields.get("ee"),
                    "type": el.tag,
                    "key": el.get("key"),
                }
        return None

    def _info_to_dict(self, info_el: ET.Element) -> Dict[str, Any]:
        """Convert an ``<info>`` element to a flat dict."""
        d: Dict[str, Any] = {}
        for child in info_el:
            tag = child.tag
            if tag == "authors":
                d["authors"] = [a.text for a in child.findall("author") if a.text]
            elif tag == "author":
                d.setdefault("authors", []).append(child.text or "")
            elif len(child) == 0:
                d[tag] = child.text or ""
            else:
                d[tag] = self._info_to_dict(child)
        return d

    def _hit_to_paper(self, hit: Dict[str, Any]) -> Paper:
        """Convert a DBLP hit dict to a :class:`Paper`."""
        authors = hit.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]

        year_raw = hit.get("year")
        try:
            year_int = int(year_raw) if year_raw else None
        except (TypeError, ValueError):
            year_int = None

        ee = hit.get("doi") or hit.get("ee") or hit.get("url")

        return Paper(
            title=(hit.get("title") or "").rstrip("."),
            authors=list(authors),
            year=year_int,
            abstract="",
            doi=ee,
            url=ee,
            source=self.name,
            citations_count=None,
            references=[],
            keywords=[],
            pdf_url=None,
            issn=None,
            isbn=None,
            publisher=hit.get("publisher"),
            journal=hit.get("venue"),
            volume=hit.get("volume"),
            issue=hit.get("number"),
            pages=hit.get("pages"),
            language=None,
            paper_type=hit.get("type"),
            fields_of_study=[],
            raw={
                "dblp_key": hit.get("key"),
            },
        )


__all__ = ["DBLPScraper"]
