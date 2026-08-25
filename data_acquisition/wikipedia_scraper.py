"""
wikipedia_scraper.py
====================

Scraper for the **Wikipedia REST / Action API**
(``https://en.wikipedia.org/w/api.php``).

While not an academic source per se, Wikipedia articles frequently
contain scholarly citations (DOIs, arXiv IDs, URLs) in their
references sections.  This scraper:

* Searches Wikipedia for articles matching a topic.
* Fetches a full page (summary + content + categories + extracted
  citation strings).
* Extracts DOI / arXiv / URL citation strings from the article body
  via :meth:`extract_citations`.
* Discovers academic identifiers mentioned in Wikipedia articles on
  a topic via :meth:`find_academic_papers`.

Authentication
--------------
None required — Wikipedia's API is fully open.  Polite clients set
a descriptive User-Agent (which :class:`BaseScraper` does by
default).  Rate limit defaults to ``3`` r/s.
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from ._compat import BaseScraper, Paper, ScraperResult, get_logger

logger = logging.getLogger(__name__)


@dataclass
class WikipediaArticle:
    """Normalised representation of a Wikipedia article.

    Attributes:
        title: Wikipedia page title (used in URLs as the last
            path segment).
        url: Canonical Wikipedia URL.
        summary: Lead-section / first-paragraph summary text.
        content: Optional full-page extract (HTML or plain text
            depending on the API endpoint used).
        categories: List of Wikipedia category names (without the
            ``Category:`` prefix).
        references: List of raw reference strings extracted from the
            article's ``<ref>`` tags / Reference section.
    """

    title: str = ""
    url: str = ""
    summary: str = ""
    content: str = ""
    categories: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict of this article."""
        return asdict(self)


# Regex patterns for academic identifiers — used by extract_citations.
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>\]\)]+)", re.IGNORECASE)
_ARXIV_RE = re.compile(
    r"\b(?:arXiv:)?(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+/[A-Z]{2}\d{7}(?:v\d+)?)\b"
)
_PUBMED_RE = re.compile(r"\b(?:PMID:?\s*)(\d{6,9})\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s\"<>\]\)]+")


class WikipediaScraper(BaseScraper):
    """Scraper for Wikipedia's Action API."""

    BASE_URL = "https://en.wikipedia.org/w/api.php"
    REST_BASE = "https://en.wikipedia.org/api/rest_v1"
    SOURCE_NAME = "wikipedia"

    DEFAULT_USER_AGENT = (
        "AcademicResearchSuite/2.0 "
        "(Wikipedia scraper; +https://github.com/academic-research-suite; "
        "academic research)"
    )

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        rate_limit: float = 3.0,
        cache: Optional[Any] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: Optional[str] = None,
    ) -> None:
        """Initialize a :class:`WikipediaScraper`.

        Args:
            proxy_manager: Optional proxy manager instance.
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
            user_agent=user_agent or self.DEFAULT_USER_AGENT,
        )
        self.logger: logging.Logger = get_logger(__name__)

    # -- BaseScraper interface -------------------------------------------

    def search(self, query: str, max_results: int = 10, **kwargs: Any) -> ScraperResult:
        """Search Wikipedia for articles matching ``query``.

        Args:
            query: Free-text search string.
            max_results: Maximum number of articles to return.
            **kwargs: Reserved for future use.

        Returns:
            A :class:`ScraperResult` whose ``papers`` field is
            intentionally empty (Wikipedia articles are NOT papers)
            and whose ``raw_response`` contains the list of
            :class:`WikipediaArticle` objects as plain dicts.  Use
            :meth:`search_articles` for a typed result instead.
        """
        articles = self.search_articles(query, max_results=max_results)
        start_ms = self._now_ms()
        return ScraperResult(
            source=self.name,
            query=query,
            total_results=len(articles),
            papers=[],
            raw_response={"articles": [a.to_dict() for a in articles]},
            timestamp=datetime.now(timezone.utc).isoformat(),
            elapsed_ms=self._now_ms() - start_ms,
            errors=[],
        )

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Wikipedia doesn't serve :class:`Paper` records.

        This method exists only to satisfy the :class:`BaseScraper`
        contract; it returns a minimal :class:`Paper` populated from
        the article summary if a page with the given title exists.
        """
        article = self.fetch_page(paper_id)
        if article is None:
            return None
        return Paper(
            title=article.title,
            authors=["Wikipedia contributors"],
            abstract=article.summary,
            year=None,
            doi=None,
            url=article.url,
            source=self.name,
            citations_count=None,
            references=article.references,
            keywords=article.categories,
            pdf_url=None,
            issn=None,
            isbn=None,
            publisher="Wikipedia",
            journal=None,
            volume=None,
            issue=None,
            pages=None,
            language="en",
            paper_type="encyclopedia_article",
            fields_of_study=[],
            raw={"article": article.to_dict()},
        )

    # -- Wikipedia-specific API ------------------------------------------

    def search_articles(self, query: str, max_results: int = 10) -> List[WikipediaArticle]:
        """Search Wikipedia for article titles matching ``query``.

        Args:
            query: Free-text search string.
            max_results: Maximum number of articles to return.

        Returns:
            A list of :class:`WikipediaArticle` instances (with only
            ``title`` and ``url`` populated; use :meth:`fetch_page`
            to retrieve full content for one).
        """
        params: Dict[str, Any] = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": min(max_results, 50),
        }
        articles: List[WikipediaArticle] = []
        try:
            cache_key = self._cache_key("wikipedia", "search", query, params["srlimit"])
            resp = self._make_request(
                "GET", self.BASE_URL, params=params, cache_key=cache_key
            )
            data = resp.json()
            if not isinstance(data, dict):
                return articles
            for item in data.get("query", {}).get("search", []) or []:
                title = item.get("title") or ""
                if not title:
                    continue
                articles.append(WikipediaArticle(
                    title=title,
                    url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                    summary=self._strip_html(item.get("snippet") or ""),
                ))
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Wikipedia search(%r) failed: %s", query, exc)
        return articles[:max_results]

    def fetch_page(self, title: str) -> Optional[WikipediaArticle]:
        """Fetch a single Wikipedia page by title.

        Args:
            title: Wikipedia page title (case-sensitive on Wikipedia;
                "Machine learning" and "machine learning" may resolve
                differently).

        Returns:
            A populated :class:`WikipediaArticle` or ``None`` on error.
        """
        if not title:
            return None
        params: Dict[str, Any] = {
            "action": "query",
            "format": "json",
            "prop": "extracts|categories|revisions|extlinks",
            "explaintext": 1,
            "exsectionformat": "plain",
            "cllimit": 50,
            "clshow": "!hidden",
            "ellimit": 100,
            "rvprop": "content",
            "titles": title,
            "redirects": 1,
        }
        try:
            cache_key = self._cache_key("wikipedia", "page", title)
            resp = self._make_request(
                "GET", self.BASE_URL, params=params, cache_key=cache_key
            )
            data = resp.json()
            if not isinstance(data, dict):
                return None
            pages = data.get("query", {}).get("pages", {})
            if not pages:
                return None
            page_id = next(iter(pages))
            page = pages[page_id]
            if page_id == "-1" or page.get("missing") is not None:
                return None

            title_actual = page.get("title") or title
            summary = (page.get("extract") or "").split("\n\n")[0]
            content = page.get("extract") or ""

            categories: List[str] = []
            for c in page.get("categories", []) or []:
                cat = c.get("title", "")
                if cat.startswith("Category:"):
                    cat = cat[len("Category:"):]
                if cat:
                    categories.append(cat.strip())

            references: List[str] = []
            # The extracts API doesn't return <ref> bodies; extlinks gives
            # external links which are the most common "references" on
            # Wikipedia.  Pull raw rev text to extract additional refs.
            for el in page.get("extlinks", []) or []:
                if isinstance(el, Mapping):
                    url = el.get("*") or ""
                else:
                    url = str(el)
                if url:
                    references.append(url)

            # Also extract rev-text <ref> URLs from the wikitext.
            revisions = page.get("revisions") or []
            wikitext = ""
            if revisions and isinstance(revisions[0], Mapping):
                wikitext = revisions[0].get("*") or ""
            if wikitext:
                for ref in self._extract_refs_from_wikitext(wikitext):
                    if ref not in references:
                        references.append(ref)

            return WikipediaArticle(
                title=title_actual,
                url=f"https://en.wikipedia.org/wiki/{title_actual.replace(' ', '_')}",
                summary=self._strip_html(summary),
                content=self._strip_html(content),
                categories=categories,
                references=references,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error("Wikipedia fetch_page(%r) failed: %s", title, exc)
            return None

    def extract_citations(self, article: WikipediaArticle) -> List[str]:
        """Extract academic citation identifiers from a Wikipedia article.

        Args:
            article: A :class:`WikipediaArticle` (uses ``content`` +
                ``references``).

        Returns:
            A de-duplicated list of strings — each entry is a DOI
            (``"10.1234/foo"``), an arXiv ID (``"arXiv:2106.04561"``),
            a PMID (``"PMID:12345678"``) or a URL.
        """
        if article is None:
            return []
        corpus_parts: List[str] = [article.content or "", article.summary or ""]
        corpus_parts.extend(article.references or [])
        corpus = "\n".join(corpus_parts)

        results: List[str] = []
        seen = set()
        for m in _DOI_RE.finditer(corpus):
            doi = m.group(1).rstrip(".,;)]}")
            if doi and doi.lower() not in seen:
                seen.add(doi.lower())
                results.append(doi)
        for m in _ARXIV_RE.finditer(corpus):
            arxiv_id = m.group(1)
            canonical = arxiv_id if arxiv_id.lower().startswith("arxiv:") else f"arXiv:{arxiv_id}"
            if canonical.lower() not in seen:
                seen.add(canonical.lower())
                results.append(canonical)
        for m in _PUBMED_RE.finditer(corpus):
            pmid = f"PMID:{m.group(1)}"
            if pmid.lower() not in seen:
                seen.add(pmid.lower())
                results.append(pmid)
        # URLs (last priority to avoid duplicates with DOI URLs).
        for m in _URL_RE.finditer(corpus):
            url = m.group(0).rstrip(".,;)]}")
            # Skip doi.org URLs — already captured as DOIs.
            if "doi.org/" in url:
                continue
            if url.lower() not in seen:
                seen.add(url.lower())
                results.append(url)
        return results

    def find_academic_papers(self, topic: str, max_articles: int = 5) -> List[str]:
        """Find academic-paper identifiers cited in Wikipedia on ``topic``.

        Args:
            topic: Wikipedia topic to search for.
            max_articles: Maximum number of Wikipedia articles to scan.

        Returns:
            A de-duplicated list of academic identifiers (DOIs,
            arXiv IDs, PMIDs) extracted from the top Wikipedia
            articles on the topic.
        """
        articles = self.search_articles(topic, max_results=max_articles)
        all_citations: List[str] = []
        seen = set()
        for article in articles:
            full = self.fetch_page(article.title)
            if full is None:
                continue
            for citation in self.extract_citations(full):
                if citation.lower() not in seen:
                    seen.add(citation.lower())
                    all_citations.append(citation)
        return all_citations

    # -- internal helpers ------------------------------------------------

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags and entities from ``text``.

        Uses ``re`` rather than bs4 to keep the module dependency-
        free; the snippets returned by the search API are simple
        HTML strings.
        """
        if not text:
            return ""
        out = re.sub(r"<[^>]+>", "", text)
        # Common HTML entities.
        out = (out
               .replace("&amp;", "&")
               .replace("&lt;", "<")
               .replace("&gt;", ">")
               .replace("&quot;", '"')
               .replace("&#39;", "'")
               .replace("&nbsp;", " "))
        return out.strip()

    @staticmethod
    def _extract_refs_from_wikitext(wikitext: str) -> List[str]:
        """Pull URL-like strings out of ``<ref>`` tags in wikitext."""
        if not wikitext:
            return []
        urls: List[str] = []
        # Match <ref ...>...</ref> blocks.
        for ref_block in re.findall(r"<ref[^>]*>(.*?)</ref>", wikitext, flags=re.DOTALL | re.IGNORECASE):
            for url in _URL_RE.findall(ref_block):
                urls.append(url.rstrip(".,;)]}"))
        # Also pick up bare URL tokens in the wikitext.
        for url in _URL_RE.findall(wikitext):
            cleaned = url.rstrip(".,;)]}")
            if cleaned not in urls:
                urls.append(cleaned)
        return urls


__all__ = ["WikipediaScraper", "WikipediaArticle"]
