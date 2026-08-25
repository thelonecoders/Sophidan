"""
pubmed_scraper.py
=================

Scraper for the NCBI PubMed database via the E-utilities interface.

Endpoints used:
  * ``https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi``
    — returns a list of PMIDs matching a query.
  * ``https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi``
    — returns the full ``PubmedArticleSet`` XML for a list of PMIDs.
  * ``https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi``
    — PMC Open-Access web service, used for full-text retrieval.

NCBI does NOT require an API key, but identifying your tool/email via
the ``tool`` and ``email`` parameters raises the rate limit (from 3
req/s to 10 req/s with a key).  This scraper defaults to ``3`` req/s
and is configurable via ``rate_limit``.
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from .base_scraper import BaseScraper, Paper, ScraperResult

logger = logging.getLogger(__name__)

_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_PMC_OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"

_PUBMED_XML_NS = {
    "pm": "http://www.ncbi.nlm.nih.gov/pubmed",
    # The fetch endpoint sometimes uses the bare namespace without a prefix.
}


def _local(tag: str) -> str:
    """Return the local name of a possibly namespace-qualified tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _findall_local(elem: ET.Element, name: str) -> List[ET.Element]:
    """Find all direct children of ``elem`` whose local-name matches."""
    return [c for c in elem if _local(c.tag) == name]


def _find_local(elem: ET.Element, name: str) -> Optional[ET.Element]:
    """Find the first direct child of ``elem`` whose local-name matches."""
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _text(elem: Optional[ET.Element]) -> str:
    """Return stripped text content or ``""`` if ``elem`` is ``None``."""
    if elem is None or elem.text is None:
        return ""
    return elem.text.strip()


class PubMedScraper(BaseScraper):
    """Scraper for NCBI PubMed via E-utilities."""

    SOURCE_NAME = "pubmed"

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        rate_limit: float = 3.0,
        cache: Optional[Any] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        user_agent: Optional[str] = None,
        tool: str = "AcademicResearchSuite",
        email: str = "ars_user@example.com",
    ) -> None:
        """Initialize a :class:`PubMedScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
            rate_limit: Requests per second (default ``3.0``, NCBI's
                unauthenticated ceiling).
            cache: Optional response cache.
            timeout: Per-request timeout (PubMed fetches can be slow).
            max_retries: Maximum retry attempts.
            user_agent: Optional User-Agent override.
            tool: ``tool`` parameter sent to E-utilities.
            email: ``email`` parameter sent to E-utilities.
        """
        super().__init__(
            proxy_manager=proxy_manager,
            rate_limit=rate_limit,
            cache=cache,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent,
        )
        self.tool = tool
        self.email = email

    # -- public API ------------------------------------------------------

    def search(
        self,
        query: str,
        max_results: int = 50,
        mindate: Optional[str] = None,
        maxdate: Optional[str] = None,
        journal: Optional[str] = None,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search PubMed for papers matching ``query``.

        Args:
            query: PubMed search syntax (e.g. ``"machine learning"[Title/Abstract]``).
            max_results: Maximum number of papers to return.
            mindate: Inclusive publication-date lower bound
                (``YYYY/MM/DD``).
            maxdate: Inclusive publication-date upper bound.
            journal: Restrict to a specific journal title.
            **kwargs: Reserved.

        Returns:
            A populated :class:`ScraperResult`.
        """
        start_ms = self._now_ms()
        errors: List[str] = []
        papers: List[Paper] = []
        raw_response: Dict[str, Any] = {}

        # Step 1: esearch to get PMIDs.
        try:
            pmids, total = self._esearch(
                query,
                max_results=max_results,
                mindate=mindate,
                maxdate=maxdate,
                journal=journal,
            )
            raw_response["pmids"] = pmids
            raw_response["total"] = total
        except requests.RequestException as exc:
            errors.append(f"esearch HTTP error: {exc}")
            self.logger.error("PubMed esearch failed: %s", exc, exc_info=True)
            return ScraperResult(
                source=self.name,
                query=query,
                total_results=0,
                papers=[],
                raw_response=raw_response,
                timestamp=datetime.now(timezone.utc).isoformat(),
                elapsed_ms=self._now_ms() - start_ms,
                errors=errors,
            )

        if not pmids:
            return ScraperResult(
                source=self.name,
                query=query,
                total_results=total,
                papers=[],
                raw_response=raw_response,
                timestamp=datetime.now(timezone.utc).isoformat(),
                elapsed_ms=self._now_ms() - start_ms,
                errors=errors,
            )

        self._emit_event("search.started", {"query": query, "total": total})

        # Step 2: efetch full records in chunks of <=200 PMIDs.
        chunk_size = 200
        for i in range(0, len(pmids), chunk_size):
            chunk = pmids[i : i + chunk_size]
            try:
                xml_text = self._efetch(chunk)
                chunk_papers = self._parse_article_set(xml_text)
                papers.extend(chunk_papers[: max_results - len(papers)])
                raw_response.setdefault("articles", []).extend(
                    p.raw for p in chunk_papers
                )
                self._emit_event(
                    "search.progress",
                    {"fetched": len(papers), "total": min(total, max_results)},
                )
                if len(papers) >= max_results:
                    break
            except requests.RequestException as exc:
                msg = f"efetch HTTP error (chunk {i}): {exc}"
                errors.append(msg)
                self.logger.error(msg, exc_info=True)
            except ET.ParseError as exc:
                msg = f"efetch XML parse error (chunk {i}): {exc}"
                errors.append(msg)
                self.logger.error(msg, exc_info=True)

        self._emit_event("search.finished", {"count": len(papers)})
        return ScraperResult(
            source=self.name,
            query=query,
            total_results=total,
            papers=papers,
            raw_response=raw_response,
            timestamp=datetime.now(timezone.utc).isoformat(),
            elapsed_ms=self._now_ms() - start_ms,
            errors=errors,
        )

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single PubMed record by PMID.

        Args:
            paper_id: The PMID (digits only; the ``PMID:`` prefix is
                tolerated).

        Returns:
            A :class:`Paper`, or ``None`` if not found.
        """
        pmid = paper_id.strip()
        if pmid.upper().startswith("PMID:"):
            pmid = pmid[5:].strip()
        try:
            xml_text = self._efetch([pmid])
            papers = self._parse_article_set(xml_text)
            return papers[0] if papers else None
        except (requests.RequestException, ET.ParseError) as exc:
            self.logger.error("PubMed fetch_by_id(%s) failed: %s", paper_id, exc)
            return None

    def fetch_full_text(self, pmid: str) -> Optional[str]:
        """Fetch the full text for a PMID via the PMC OA web service.

        Args:
            pmid: The PubMed identifier.

        Returns:
            The full text as a string (XML or extracted plain text),
            or ``None`` if the article is not in PMC OA or the request
            fails.
        """
        try:
            cache_key = self._cache_key("pubmed", "fulltext", pmid)
            resp = self._make_request(
                "GET",
                _PMC_OA_URL,
                params={"id": pmid},
                cache_key=cache_key,
            )
            root = ET.fromstring(resp.text)
            for record in root.findall("record"):
                oa_status = record.get("availability", "")
                if oa_status.lower() in ("oa", "openaccess"):
                    # Prefer the PDF link; fall back to tgz/XML.
                    for link in record.findall("link"):
                        fmt = link.get("format", "").lower()
                        if fmt in ("pdf", "xml", "tgz"):
                            url = link.get("href", "")
                            if url:
                                try:
                                    pdf_resp = self._session.get(
                                        url, timeout=self.timeout
                                    )
                                    pdf_resp.raise_for_status()
                                    # PMC OA tgz/xml returns raw bytes; for
                                    # PDF we just return the text preview.
                                    try:
                                        return pdf_resp.text
                                    except UnicodeDecodeError:
                                        return pdf_resp.content.decode(
                                            "utf-8", errors="replace"
                                        )
                                except requests.RequestException as exc:
                                    self.logger.warning(
                                        "PMC OA fetch failed for %s: %s", pmid, exc
                                    )
                                    return None
        except (requests.RequestException, ET.ParseError) as exc:
            self.logger.warning("fetch_full_text(%s) failed: %s", pmid, exc)
            return None
        return None

    # -- E-utilities helpers ---------------------------------------------

    def _esearch(
        self,
        query: str,
        max_results: int = 50,
        mindate: Optional[str] = None,
        maxdate: Optional[str] = None,
        journal: Optional[str] = None,
    ) -> tuple[List[str], int]:
        """Run ``esearch.fcgi`` and return (pmids, total_count)."""
        full_query = query
        if journal:
            full_query = f'({full_query}) AND "{journal}"[Journal]'
        params: Dict[str, Any] = {
            "db": "pubmed",
            "term": full_query,
            "retmax": max_results,
            "retmode": "xml",
            "tool": self.tool,
            "email": self.email,
        }
        if mindate:
            params["mindate"] = mindate.replace("/", "/")
            params["datetype"] = "pdat"
        if maxdate:
            params["maxdate"] = maxdate.replace("/", "/")
            params["datetype"] = "pdat"
        cache_key = self._cache_key("pubmed", "esearch", full_query, max_results)
        resp = self._make_request(
            "GET", _ESEARCH_URL, params=params, cache_key=cache_key
        )
        root = ET.fromstring(resp.text)
        total = 0
        total_el = _find_local(root, "Count")
        if total_el is not None:
            try:
                total = int(_text(total_el))
            except ValueError:
                total = 0
        id_list_el = _find_local(root, "IdList")
        pmids: List[str] = []
        if id_list_el is not None:
            for id_el in _findall_local(id_list_el, "Id"):
                pmids.append(_text(id_el))
        return pmids, total

    def _efetch(self, pmids: List[str]) -> str:
        """Run ``efetch.fcgi`` for the given PMIDs; return raw XML text."""
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
            "tool": self.tool,
            "email": self.email,
        }
        cache_key = self._cache_key("pubmed", "efetch", "|".join(pmids))
        resp = self._make_request(
            "GET", _EFETCH_URL, params=params, cache_key=cache_key
        )
        return resp.text

    # -- XML parsing -----------------------------------------------------

    def _parse_article_set(self, xml_text: str) -> List[Paper]:
        """Parse a ``PubmedArticleSet`` XML document into :class:`Paper`s."""
        root = ET.fromstring(xml_text)
        papers: List[Paper] = []
        # Each article may be wrapped in <PubmedArticle> or <PubmedBookArticle>.
        for article in root.iter():
            if _local(article.tag) not in ("PubmedArticle", "PubmedBookArticle"):
                continue
            paper = self._parse_article(article)
            if paper is not None:
                papers.append(paper)
        return papers

    def _parse_article(self, article: ET.Element) -> Optional[Paper]:
        """Parse a single ``PubmedArticle`` element."""
        medline = _find_local(article, "MedlineCitation")
        if medline is None:
            return None
        pmid_el = _find_local(medline, "PMID")
        pmid = _text(pmid_el) if pmid_el is not None else ""

        article_el = _find_local(medline, "Article")
        if article_el is None:
            return None

        title_el = _find_local(article_el, "ArticleTitle")
        title = _text(title_el).rstrip(".")
        if not title:
            return None

        authors: List[str] = []
        author_list_el = _find_local(article_el, "AuthorList")
        if author_list_el is not None:
            for author_el in _findall_local(author_list_el, "Author"):
                last = _text(_find_local(author_el, "LastName"))
                fore = _text(_find_local(author_el, "ForeName"))
                collective = _text(_find_local(author_el, "CollectiveName"))
                if last and fore:
                    authors.append(f"{last}, {fore}")
                elif last:
                    authors.append(last)
                elif collective:
                    authors.append(collective)

        abstract_parts: List[str] = []
        abstract_el = _find_local(article_el, "Abstract")
        if abstract_el is not None:
            for ab_text in _findall_local(abstract_el, "AbstractText"):
                label = ab_text.get("Label", "")
                txt = _text(ab_text)
                if label:
                    abstract_parts.append(f"{label}: {txt}")
                else:
                    abstract_parts.append(txt)
        abstract = " ".join(abstract_parts)

        # Year — try <ArticleDate><Year>, else <Journal><PubDate><Year>.
        year: Optional[int] = None
        article_date_el = _find_local(article_el, "ArticleDate")
        if article_date_el is not None:
            yel = _find_local(article_date_el, "Year")
            if yel is not None:
                try:
                    year = int(_text(yel))
                except ValueError:
                    year = None
        if year is None:
            journal_el = _find_local(article_el, "Journal")
            if journal_el is not None:
                issue_el = _find_local(journal_el, "JournalIssue")
                if issue_el is not None:
                    pubdate_el = _find_local(issue_el, "PubDate")
                    if pubdate_el is not None:
                        yel = _find_local(pubdate_el, "Year")
                        if yel is not None:
                            try:
                                year = int(_text(yel))
                            except ValueError:
                                medline_date = _text(_find_local(pubdate_el, "MedlineDate"))
                                if medline_date and medline_date[:4].isdigit():
                                    year = int(medline_date[:4])

        # DOI, journal, volume, issue, pages, ISSN.
        doi: Optional[str] = None
        issn: Optional[str] = None
        journal_title: Optional[str] = None
        volume: Optional[str] = None
        issue: Optional[str] = None
        pages: Optional[str] = None
        publisher: Optional[str] = None

        journal_el = _find_local(article_el, "Journal")
        if journal_el is not None:
            title_el2 = _find_local(journal_el, "Title")
            if title_el2 is not None:
                journal_title = _text(title_el2)
            issn_el = _find_local(journal_el, "ISSN")
            if issn_el is not None:
                issn = _text(issn_el)
            issue_el = _find_local(journal_el, "JournalIssue")
            if issue_el is not None:
                vol_el = _find_local(issue_el, "Volume")
                if vol_el is not None:
                    volume = _text(vol_el)
                iss_el = _find_local(issue_el, "Issue")
                if iss_el is not None:
                    issue = _text(iss_el)
                pubdate_el = _find_local(issue_el, "PubDate")
                # (year already handled above)

        # ELocationID may carry a DOI.
        for eloc in _findall_local(article_el, "ELocationID"):
            if eloc.get("EIdType") == "doi":
                doi = _text(eloc) or doi

        pagination_el = _find_local(article_el, "Pagination")
        if pagination_el is not None:
            medline_pgs = _find_local(pagination_el, "MedlinePgn")
            if medline_pgs is not None:
                pages = _text(medline_pgs)

        # MeSH terms + keywords.
        keywords: List[str] = []
        mesh_list = _find_local(medline, "MeshHeadingList")
        if mesh_list is not None:
            for mesh in _findall_local(mesh_list, "MeshHeading"):
                descriptor = _find_local(mesh, "DescriptorName")
                if descriptor is not None and descriptor.text:
                    keywords.append(descriptor.text.strip())
        keyword_list = _find_local(medline, "KeywordList")
        if keyword_list is not None:
            for kw in _findall_local(keyword_list, "Keyword"):
                if kw.text:
                    keywords.append(kw.text.strip())

        # Grants (for provenance / funding analysis).
        grants: List[str] = []
        grants_el = _find_local(article_el, "GrantList")
        if grants_el is not None:
            for grant in _findall_local(grants_el, "Grant"):
                grant_id_el = _find_local(grant, "GrantID")
                agency_el = _find_local(grant, "Agency")
                if grant_id_el is not None and _text(grant_id_el):
                    grants.append(_text(grant_id_el))
                elif agency_el is not None and _text(agency_el):
                    grants.append(_text(agency_el))

        # Publication type.
        paper_type: Optional[str] = None
        pub_type_list = _find_local(article_el, "PublicationTypeList")
        if pub_type_list is not None:
            pt = _find_local(pub_type_list, "PublicationType")
            if pt is not None and pt.text:
                paper_type = pt.text.strip()

        # Publisher — found under <Publisher> in book articles; absent
        # for normal journal articles.  Be defensive.
        publisher_el = _find_local(article_el, "Publisher")
        if publisher_el is not None:
            publisher = _text(publisher_el)

        # Language.
        language: Optional[str] = None
        lang_el = _find_local(article_el, "Language")
        if lang_el is not None:
            language = _text(lang_el)

        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None

        # Preserve a compact raw payload.
        raw = {
            "pmid": pmid,
            "grants": grants,
            "mesh_terms": keywords[:],
        }

        return Paper(
            title=title,
            authors=authors,
            abstract=abstract,
            year=year,
            doi=doi,
            url=url,
            source=self.name,
            citations_count=None,
            references=[],
            keywords=keywords,
            pdf_url=None,
            issn=issn,
            isbn=None,
            publisher=publisher,
            journal=journal_title,
            volume=volume,
            issue=issue,
            pages=pages,
            language=language,
            paper_type=paper_type,
            fields_of_study=[],
            raw=raw,
        )


__all__ = ["PubMedScraper"]
