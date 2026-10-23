"""
google_scholar_scraper.py
========================

Google Scholar scraper built on top of the ``scholarly`` library.

The ``scholarly`` package (https://github.com/scholarly-python-package/scholarly)
provides a Pythonic wrapper around Google Scholar's web interface.
**Important runtime note:** ``scholarly`` uses Selenium under the hood
for anti-bot bypass when filling publication details, fetching author
profiles or retrieving citation lists — features that Google Scholar
loads dynamically via JavaScript. As a consequence this scraper has
heavier system requirements than the pure-REST scrapers in this
package: a working Chrome / Chromium binary plus a matching
``chromedriver`` must be available on the host when those
Selenium-backed features are invoked. Basic ``search_pubs`` queries
work without Selenium, but Google will rate-limit / cookie-wall them
aggressively, which is why proxy support is mandatory in practice.

The scraper integrates with the project's :class:`ProxyManager` (from
``proxy.proxy_manager``) so that rotating proxies can be supplied to
``scholarly`` via ``scholarly.use_proxy(...)``. If Google Scholar
blocks the request (cookies / captchas), the scraper degrades
gracefully — it returns any partial results collected before the
block and records the failure in the returned
:class:`ScraperResult`'s ``errors`` list.
"""
from __future__ import annotations
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
from typing import Any, Dict, List, Optional

from ._compat import BaseScraper, Paper, ScraperResult, get_logger

# Optional dependency: scholarly
try:
    from scholarly import scholarly, ProxyGenerator  # type: ignore
    try:  # newer scholarly exposes MaxTriesExceededException under _proxy_generator
        from scholarly._proxy_generator import (  # type: ignore
            MaxTriesExceededException,
        )
    except Exception:  # pragma: no cover
        class MaxTriesExceededException(Exception):  # type: ignore[no-redef]
            """Fallback exception used when scholarly is unavailable/old."""
    SCHOLARLY_AVAILABLE = True
except ImportError:  # pragma: no cover
    SCHOLARLY_AVAILABLE = False
    scholarly = None  # type: ignore
    ProxyGenerator = None  # type: ignore

    class MaxTriesExceededException(Exception):  # type: ignore[no-redef]
        """Fallback exception used when scholarly is unavailable."""

# Optional: ProxyManager from sibling agent
try:
    from proxy.proxy_manager import ProxyManager  # type: ignore
    _PROXY_MANAGER_AVAILABLE = True
except ImportError:  # pragma: no cover
    ProxyManager = None  # type: ignore
    _PROXY_MANAGER_AVAILABLE = False


class GoogleScholarScraper(BaseScraper):
    """Google Scholar scraper wrapping the ``scholarly`` library.

    Inherits from :class:`data_acquisition.base_scraper.BaseScraper`
    (via :mod:`data_acquisition._compat`) so it picks up rate-limiting,
    retry logic and proxy rotation utilities.
    """

    BASE_URL = "https://scholar.google.com"
    SOURCE_NAME = "Google Scholar"

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        polite_email: Optional[str] = None,
        rate_limit: float = 0.5,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        """Initialize the scraper.

        Args:
            proxy_manager: Optional ``ProxyManager`` instance used to
                obtain rotating proxies. If omitted, the scraper runs
                without proxies (and will likely be rate-limited).
            polite_email: Optional email passed to ``scholarly`` for
                the polite pool.
            rate_limit: Maximum requests per second (default 0.5 —
                Google Scholar is aggressive about rate-limiting).
            timeout: Per-request HTTP timeout in seconds.
            max_retries: Maximum retries on transient errors.
        """
        super().__init__(
            proxy_manager=proxy_manager,
            rate_limit=rate_limit,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.logger: logging.Logger = get_logger(__name__)
        self._polite_email = polite_email
        self._registered_proxies: List[Any] = []

        if not SCHOLARLY_AVAILABLE:
            self.logger.warning(
                "The 'scholarly' library is not installed; GoogleScholarScraper "
                "will return empty results. Install it via `pip install scholarly`."
            )
        else:
            try:
                if self._polite_email and hasattr(scholarly, "_mail"):  # type: ignore[arg-type]
                    scholarly._mail = self._polite_email  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - defensive
                self.logger.debug("Could not set polite email on scholarly.", exc_info=True)

    # ------------------------------------------------------------------
    # BaseScraper interface
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        max_results: int = 50,
        year_lo: Optional[int] = None,
        year_hi: Optional[int] = None,
        patent: bool = False,
        citations_only: bool = False,
        **kwargs: Any,
    ) -> ScraperResult:
        """Search Google Scholar for publications.

        Args:
            query: The free-text search string (supports Google
                Scholar's advanced query syntax, e.g. ``"machine
                learning"``).
            max_results: Maximum number of results to return.
            year_lo: Optional lower bound (inclusive) on publication
                year.
            year_hi: Optional upper bound (inclusive) on publication
                year.
            patent: If ``True``, include patents in the result set.
            citations_only: If ``True``, only return papers that have
                at least one citation.
            **kwargs: Reserved for future use.

        Returns:
            A :class:`ScraperResult` whose ``papers`` list contains
            the publications retrieved. If Google Scholar blocked the
            request, ``errors`` is populated but any partial results
            collected before the block are still returned.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        if not SCHOLARLY_AVAILABLE:
            result.errors.append(
                "The 'scholarly' library is not installed. "
                "Run `pip install scholarly` to enable Google Scholar scraping."
            )
            result.elapsed_ms = self._now_ms() - start_ms
            return result

        # Build the scholarly query object.  Only pass the dict form when
        # the caller actually set at least one filter — the old condition
        # included ``or not patent`` which is always True for the default
        # ``patent=False`` and sent the dict on every plain query
        # (audit 4-b, google_scholar #1).
        query_obj: Any = query
        if (
            year_lo is not None
            or year_hi is not None
            or patent
            or citations_only
        ):
            query_obj = {
                "query": query,
                "year_lo": year_lo,
                "year_hi": year_hi,
                "patents": patent,
                "citations_only": citations_only,
            }

        # Configure proxy if available.
        self._apply_proxy()

        try:
            self.logger.info(
                "Searching Google Scholar for %r (max_results=%d)...",
                query,
                max_results,
            )
            search_fn = getattr(
                scholarly,
                "search_pubs_query",
                getattr(scholarly, "search_pubs", None),
            )
            if search_fn is None:  # pragma: no cover - safety net
                raise RuntimeError(
                    "scholarly has no search_pubs/search_pubs_query attribute"
                )

            gen = search_fn(query_obj)
            count = 0
            while count < max_results:
                try:
                    pub = next(gen)
                except StopIteration:
                    break
                except MaxTriesExceededException as exc:
                    self.logger.warning(
                        "Google Scholar blocked requests (MaxTriesExceededException): %s",
                        exc,
                    )
                    result.errors.append(
                        "Google Scholar blocked requests; returning partial results."
                    )
                    break
                except Exception as exc:  # pragma: no cover - per-item resilience
                    self.logger.warning(
                        "Skipping a publication due to error: %s", exc
                    )
                    result.errors.append(f"Skipped publication: {exc}")
                    continue

                try:
                    paper = self._publication_to_paper(pub)
                    result.papers.append(paper)
                    count += 1
                except Exception as exc:  # pragma: no cover - per-item resilience
                    self.logger.warning(
                        "Could not parse publication entry: %s", exc
                    )
                    result.errors.append(f"Unparseable publication: {exc}")
        except MaxTriesExceededException as exc:
            self.logger.warning(
                "Google Scholar is blocking requests (cookies/captcha).", exc_info=True
            )
            result.errors.append(
                "Google Scholar blocked the request (cookies/captcha). "
                "Partial results returned."
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error(
                "Unexpected error while querying Google Scholar: %s",
                exc,
                exc_info=True,
            )
            result.errors.append(f"Unexpected error: {exc}")
        finally:
            self._clear_proxy()

        result.total_results = len(result.papers)
        result.elapsed_ms = self._now_ms() - start_ms
        self.logger.info(
            "Google Scholar query complete. Returning %d papers.",
            result.total_results,
        )
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single publication by Google Scholar cluster ID.

        ``scholarly``'s public API has no ``get_by_id`` helper — the old
        code called one and every lookup returned ``None`` (audit 4-b,
        google_scholar #2).  The method is therefore gated behind
        ``hasattr``: when a future/patched scholarly exposes it, it is
        used; otherwise the call degrades to a publication search on the
        identifier string via ``search_pubs`` (best effort).

        Args:
            paper_id: The Google Scholar cluster ID (numeric) of the
                paper to fetch.

        Returns:
            A :class:`Paper` or ``None`` if the lookup fails.
        """
        if not SCHOLARLY_AVAILABLE:
            self.logger.error("scholarly not available; cannot fetch_by_id.")
            return None
        self._apply_proxy()
        try:
            pub = None
            if hasattr(scholarly, "get_by_id"):
                pub = scholarly.get_by_id(paper_id)  # type: ignore[union-attr]
            else:
                # scholarly has no public get-by-id; best effort is a
                # publications search for the identifier string.
                search_fn = getattr(
                    scholarly, "search_pubs", None
                ) or getattr(scholarly, "search_pubs_query", None)
                if search_fn is not None:
                    pub = next(iter(search_fn(paper_id)), None)
            if not pub:
                return None
            return self._publication_to_paper(pub)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("fetch_by_id(%s): %s", paper_id, exc, exc_info=True)
            return None
        finally:
            self._clear_proxy()

    # ------------------------------------------------------------------
    # Author / citation endpoints
    # ------------------------------------------------------------------
    def fetch_author(self, name: str) -> Optional[Dict[str, Any]]:
        """Look up an author profile by name.

        Args:
            name: Author display name (e.g. ``"Yoshua Bengio"``).

        Returns:
            A dict with keys like ``name``, ``scholar_id``,
            ``affiliation``, ``interests``, ``citedby`` — the
            structure returned by ``scholarly.scholarly.fill(author)``.
            Returns ``None`` if the author cannot be found or if
            ``scholarly`` is unavailable.
        """
        if not SCHOLARLY_AVAILABLE:
            self.logger.error("scholarly not available; cannot fetch author.")
            return None
        self._apply_proxy()
        try:
            search = scholarly.search_author(name)
            author = next(search, None)
            if author is None:
                self.logger.info("No author found for name=%r", name)
                return None
            filled = scholarly.fill(author)
            return dict(filled) if filled else None
        except MaxTriesExceededException:  # pragma: no cover - network
            self.logger.warning("Google Scholar blocked fetch_author(%r).", name)
            return None
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("fetch_author failed: %s", exc, exc_info=True)
            return None
        finally:
            self._clear_proxy()

    def fetch_author_papers(self, author_id: str) -> List[Paper]:
        """Fetch all papers listed on an author's Google Scholar profile.

        Args:
            author_id: The Google Scholar author ID (the ``user=...``
                value in the profile URL).

        Returns:
            A list of :class:`Paper` objects (without filled abstracts
            unless ``scholarly.fill`` succeeds).
        """
        if not SCHOLARLY_AVAILABLE:
            self.logger.error("scholarly not available; cannot fetch author papers.")
            return []
        self._apply_proxy()
        papers: List[Paper] = []
        try:
            author = scholarly.search_author_id(author_id)
            filled = scholarly.fill(author)
            for pub in filled.get("publications", []):
                try:
                    papers.append(self._publication_to_paper(pub, is_author_pub=True))
                except Exception as exc:  # pragma: no cover
                    self.logger.warning("Skipping author pub: %s", exc)
        except MaxTriesExceededException:  # pragma: no cover
            self.logger.warning(
                "Google Scholar blocked fetch_author_papers(%r).", author_id
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("fetch_author_papers failed: %s", exc, exc_info=True)
        finally:
            self._clear_proxy()
        return papers

    def fetch_citations(self, paper_id: Any, max_results: int = 100) -> List[Paper]:
        """Fetch papers citing a given Google Scholar publication.

        Modern ``scholarly`` (>= 1.7) implements ``search_citedby`` as a
        *generator over a filled Publication object* — passing a bare
        cluster-id string raises / yields nothing (audit 4-b,
        google_scholar #3).  The flow therefore accepts either:

          * a filled scholarly Publication (dict) — passed straight to
            ``scholarly.search_citedby(publication)``;
          * a string identifier — resolved to a Publication by a
            ``search_pubs`` lookup first, filled via ``scholarly.fill``
            when available, and only then handed to ``search_citedby``.

        When scholarly exposes none of the needed callables the feature
        degrades gracefully (logged, empty list) instead of raising.

        Args:
            paper_id: A filled scholarly Publication dict **or** a
                Google Scholar cluster ID / publication title string.
            max_results: Maximum number of citing papers to return.

        Returns:
            A list of :class:`Paper` objects representing the citing
            publications.
        """
        if not SCHOLARLY_AVAILABLE:
            self.logger.error("scholarly not available; cannot fetch citations.")
            return []
        search_citedby = getattr(scholarly, "search_citedby", None)
        if not callable(search_citedby):
            self.logger.warning(
                "scholarly.search_citedby is unavailable; fetch_citations "
                "is a no-op for this scholarly version."
            )
            return []
        self._apply_proxy()
        papers: List[Paper] = []
        try:
            publication = paper_id
            if not isinstance(paper_id, dict):
                # Resolve the identifier to a Publication first.
                search_fn = getattr(scholarly, "search_pubs", None) or getattr(
                    scholarly, "search_pubs_query", None
                )
                if not callable(search_fn):
                    self.logger.warning(
                        "scholarly exposes neither search_pubs nor a usable "
                        "search_citedby input; fetch_citations cannot proceed."
                    )
                    return []
                publication = next(iter(search_fn(str(paper_id))), None)
                if publication is None:
                    return []
                fill = getattr(scholarly, "fill", None)
                if callable(fill):
                    try:
                        publication = fill(publication)
                    except Exception:  # pragma: no cover - network
                        pass  # unfilled Publication may still work
            cited_by = search_citedby(publication)
            for i, pub in enumerate(cited_by):
                if i >= max_results:
                    break
                try:
                    papers.append(self._publication_to_paper(pub))
                except Exception as exc:  # pragma: no cover
                    self.logger.warning("Skipping citation: %s", exc)
        except MaxTriesExceededException:  # pragma: no cover
            self.logger.warning(
                "Google Scholar blocked fetch_citations(%r).", paper_id
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.error("fetch_citations failed: %s", exc, exc_info=True)
        finally:
            self._clear_proxy()
        return papers

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _publication_to_paper(
        self,
        pub: Dict[str, Any],
        is_author_pub: bool = False,
    ) -> Paper:
        """Convert a ``scholarly`` publication dict to a :class:`Paper`."""
        bib = pub.get("bib", {}) if isinstance(pub, dict) else {}
        author_list = bib.get("author", []) or []
        if isinstance(author_list, str):
            authors = [a.strip() for a in author_list.split(",") if a.strip()]
        else:
            authors = [str(a).strip() for a in author_list if a]

        year_raw = bib.get("pub_year")
        year: Optional[int] = None
        if year_raw is not None:
            try:
                year = int(year_raw)
            except (TypeError, ValueError):
                year = None

        doi = pub.get("doi") or bib.get("doi")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/"):]

        citations_count = pub.get("num_citations")
        try:
            citations_count_int: Optional[int] = int(citations_count) if citations_count is not None else None
        except (TypeError, ValueError):
            citations_count_int = None

        return Paper(
            title=bib.get("title", "") or "",
            authors=authors,
            year=year,
            abstract=bib.get("abstract", "") or "",
            doi=doi if doi else None,
            url=pub.get("pub_url") or pub.get("eprint_url"),
            source=self.name,
            citations_count=citations_count_int,
            references=[],
            keywords=[],
            pdf_url=pub.get("eprint_url"),
            issn=None,
            isbn=None,
            publisher=bib.get("publisher"),
            journal=bib.get("venue") or bib.get("journal"),
            volume=None,
            issue=None,
            pages=None,
            language=None,
            paper_type="patent" if pub.get("pub_type") == "patent" else None,
            fields_of_study=[],
            raw={
                "scholar_id": pub.get("author_id") or pub.get("cluster_id"),
                "cluster_id": pub.get("cluster_id"),
                "related_url": pub.get("url_related"),
                "is_author_pub": is_author_pub,
                "bib": bib,
            },
        )

    def _apply_proxy(self) -> None:
        """Configure scholarly to use a proxy from the ProxyManager (if any)."""
        if not SCHOLARLY_AVAILABLE or not ProxyGenerator:
            return
        if self.proxy_manager is None:
            return
        try:
            proxy_str = self.proxy_manager.get_proxy()  # type: ignore[attr-defined]
            if not proxy_str:
                self.logger.debug("ProxyManager returned no proxy; running direct.")
                return
            pg = ProxyGenerator()
            target = proxy_str if proxy_str.startswith("http") else f"http://{proxy_str}"
            ok = pg.SingleProxy(http=target, https=target)
            if ok:
                scholarly.use_proxy(pg)
                self._registered_proxies.append(pg)
                self.logger.info("scholarly now using proxy: %s", proxy_str)
            else:
                self.logger.warning("ProxyGenerator rejected proxy %r", proxy_str)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("Failed to apply proxy: %s", exc)

    def _clear_proxy(self) -> None:
        """Remove the proxy configuration from scholarly."""
        if not SCHOLARLY_AVAILABLE:
            return
        try:
            scholarly.use_proxy(None)
        except Exception:  # pragma: no cover - defensive
            pass
        self._registered_proxies.clear()


__all__ = ["GoogleScholarScraper"]
