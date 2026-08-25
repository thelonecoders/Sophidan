"""
orcid_scraper.py
================

Scraper for the ORCID Public API v3.0
(``https://pub.orcid.org/v3.0/``).

The ORCID Public API is open: no API key is required for public-record
reads. The documented rate limit is **24 requests per second**, which
is well above what this scraper issues by default. Responses are JSON;
ORCID also supports JSON-LD through content negotiation when the
``Accept`` header is set to ``application/ld+json`` — we attempt
JSON-LD first, then fall back to the default ``application/json``
payload.

The scraper exposes:

* :meth:`fetch_orcid_profile` — full record (employments,
  educations, works, funding, peer-reviews).
* :meth:`search_by_name` — search by given/family name.
* :meth:`fetch_works` — extract the publication list as
  :class:`Paper` records.
* :meth:`fetch_employments` — institutional affiliations timeline.

Every public method returns native Python types (``dict`` / ``list`` /
:class:`Paper`), and :meth:`search` (the BaseScraper entrypoint)
wraps a name search into a :class:`ScraperResult`.
"""
from __future__ import annotations
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
from typing import Any, Dict, List, Optional

from ._compat import BaseScraper, Paper, ScraperResult, get_logger

ORCID_BASE_URL = "https://pub.orcid.org/v3.0"


class ORCIDScraper(BaseScraper):
    """Scraper for the ORCID Public API v3.0.

    Inherits HTTP plumbing (retries, rate-limiting, proxy rotation,
    caching) from :class:`data_acquisition.base_scraper.BaseScraper`.
    """

    BASE_URL = ORCID_BASE_URL
    SOURCE_NAME = "ORCID"

    def __init__(
        self,
        proxy_manager: Optional[Any] = None,
        polite_email: Optional[str] = None,
        rate_limit: float = 8.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        cache: Optional[Any] = None,
    ) -> None:
        """Initialize the ORCID scraper.

        Args:
            proxy_manager: Optional proxy manager.
            polite_email: Optional email used to identify the client
                to ORCID (recommended for the polite pool).
            rate_limit: Maximum requests per second (default 8.0,
                well below the 24 req/s limit).
            timeout: HTTP timeout per request, in seconds.
            max_retries: Maximum retries on transient HTTP errors.
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
    def search(self, query: str, max_results: int = 50, **kwargs: Any) -> ScraperResult:
        """Search ORCID by free-text query (delegates to search_by_name).

        Args:
            query: Search query. If the string contains a space, the
                first token is treated as the given name and the last
                token as the family name.
            max_results: Maximum number of profile matches to return.
            **kwargs: Reserved for future use.

        Returns:
            A :class:`ScraperResult`. Each :class:`Paper` in the
            result wraps an ORCID profile summary; use
            :meth:`fetch_orcid_profile` for the full record.
        """
        start_ms = self._now_ms()
        result = ScraperResult(source=self.name, query=query)
        matches = self.search_by_name(query, max_results=max_results)
        for m in matches:
            orcid_id = m.get("orcid_id") or m.get("orcid") or m.get("id")
            if not orcid_id:
                continue
            given = (m.get("given_names") or m.get("given-names") or "").strip()
            family = (m.get("family_names") or m.get("family-names") or "").strip()
            name = (given + " " + family).strip() or m.get("name", "")
            result.papers.append(
                Paper(
                    title=f"ORCID profile: {name}",
                    authors=[name] if name else [],
                    year=None,
                    abstract="",
                    doi=None,
                    url=f"https://orcid.org/{orcid_id}",
                    source=self.name,
                    citations_count=None,
                    references=[],
                    keywords=[],
                    pdf_url=None,
                    issn=None,
                    isbn=None,
                    publisher=None,
                    journal=None,
                    volume=None,
                    issue=None,
                    pages=None,
                    language=None,
                    paper_type="profile",
                    fields_of_study=[],
                    raw={"orcid_id": orcid_id, "profile_summary": m},
                )
            )
        result.total_results = len(result.papers)
        result.elapsed_ms = self._now_ms() - start_ms
        self.logger.info(
            "ORCID search complete. Returning %d profile(s).", result.total_results
        )
        return result

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch an ORCID profile as a :class:`Paper`.

        The ``paper_id`` is interpreted as an ORCID iD. Returns a
        :class:`Paper` whose ``raw`` dict carries the full profile.

        Args:
            paper_id: The ORCID iD.

        Returns:
            A :class:`Paper` wrapping the profile, or ``None``.
        """
        clean_id = self._clean_orcid_id(paper_id)
        if not clean_id:
            return None
        profile = self.fetch_orcid_profile(clean_id)
        if not profile:
            return None
        person = profile.get("person", {}) or {}
        name_obj = person.get("name", {}) or {}
        given = (name_obj.get("given-names", {}).get("value") or "") if isinstance(name_obj.get("given-names"), dict) else (name_obj.get("given-names") or "")
        family = (name_obj.get("family-names", {}).get("value") or "") if isinstance(name_obj.get("family-names"), dict) else (name_obj.get("family-names") or "")
        name = (given + " " + family).strip()
        return Paper(
            title=f"ORCID profile: {name}",
            authors=[name] if name else [],
            year=None,
            abstract="",
            doi=None,
            url=f"https://orcid.org/{clean_id}",
            source=self.name,
            citations_count=None,
            references=[],
            keywords=[],
            pdf_url=None,
            issn=None,
            isbn=None,
            publisher=None,
            journal=None,
            volume=None,
            issue=None,
            pages=None,
            language=None,
            paper_type="profile",
            fields_of_study=[],
            raw={"orcid_id": clean_id, "profile": profile},
        )

    # ------------------------------------------------------------------
    # Profile-level endpoints
    # ------------------------------------------------------------------
    def fetch_orcid_profile(self, orcid_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the full ORCID profile record.

        Args:
            orcid_id: The 16-digit ORCID iD (with or without dashes).

        Returns:
            A dict containing the parsed profile with the keys
            ``person``, ``activities``, ``employments``,
            ``educations``, ``works``, ``fundings``, ``peer_reviews``.
            Returns ``None`` if the record is not found.
        """
        clean_id = self._clean_orcid_id(orcid_id)
        if not clean_id:
            return None
        try:
            data = self._request_json(
                f"{self.BASE_URL}/{clean_id}/record",
                cache_key=self._cache_key("orcid_profile", clean_id),
            )
        except Exception as exc:
            self.logger.error("ORCID fetch_orcid_profile(%s): %s", orcid_id, exc)
            return None

        profile: Dict[str, Any] = {
            "orcid_id": clean_id,
            "person": data.get("person", {}),
            "activities": data.get("activities-summary", {}),
        }
        profile["employments"] = self.fetch_employments(clean_id) or []
        profile["educations"] = self._fetch_educations(clean_id) or []
        profile["works"] = self.fetch_works(clean_id) or []
        profile["fundings"] = self._fetch_fundings(clean_id) or []
        profile["peer_reviews"] = self._fetch_peer_reviews(clean_id) or []
        return profile

    def search_by_name(self, name: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """Search the ORCID registry by name.

        Args:
            name: Author name. If a multi-token string is supplied,
                the first token is treated as the given name and the
                last as the family name.
            max_results: Maximum number of results to return.

        Returns:
            A list of dicts (one per match) with keys such as
            ``orcid_id``, ``given_names``, ``family_names``, ``name``.
        """
        tokens = name.strip().split()
        if len(tokens) >= 2:
            q = f"given-names:{tokens[0]}+AND+family-name:{tokens[-1]}"
        else:
            q = f"given-and-family-names:{name.strip()}"
        params = {"q": q}
        try:
            data = self._request_json(f"{self.BASE_URL}/search/", params=params)
        except Exception as exc:
            self.logger.error("ORCID search_by_name(%s): %s", name, exc)
            return []
        results = data.get("result", []) or []
        expanded: List[Dict[str, Any]] = []
        for item in results[:max_results]:
            orcid_id = item.get("orcid-identifier", {}).get("path")
            given = item.get("orcid-identifier", {}).get("given-names", "")
            family = item.get("orcid-identifier", {}).get("family-name", "")
            summary = {
                "orcid_id": orcid_id,
                "given_names": given,
                "family_names": family,
                "name": (given + " " + family).strip() if (given or family) else "",
            }
            expanded.append(summary)
        return expanded

    def fetch_works(self, orcid_id: str) -> List[Paper]:
        """Fetch the publication list (works) of an ORCID profile.

        Args:
            orcid_id: ORCID iD.

        Returns:
            A list of :class:`Paper` records. The ORCID ``title`` is
            mapped to :attr:`Paper.title`, the ``publication-date`` is
            mapped to :attr:`Paper.year`, and any external IDs (DOI,
            ISBN, etc.) are stored in :attr:`Paper.raw`.
        """
        clean_id = self._clean_orcid_id(orcid_id)
        if not clean_id:
            return []
        try:
            data = self._request_json(
                f"{self.BASE_URL}/{clean_id}/works",
                cache_key=self._cache_key("orcid_works", clean_id),
            )
        except Exception as exc:
            self.logger.error("ORCID fetch_works(%s): %s", orcid_id, exc)
            return []

        works_group = data.get("group", []) or data.get("works", []) or []
        papers: List[Paper] = []
        for group in works_group:
            work_summaries = group.get("work-summary", []) if isinstance(group, dict) else []
            if not work_summaries:
                if isinstance(group, dict) and "work-summary" not in group:
                    work_summaries = [group]
            for work in work_summaries:
                try:
                    papers.append(self._work_to_paper(work, clean_id))
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.warning("Skipping malformed ORCID work: %s", exc)
        return papers

    def fetch_employments(self, orcid_id: str) -> List[Dict[str, Any]]:
        """Fetch the employment (affiliations) timeline for an ORCID.

        Args:
            orcid_id: ORCID iD.

        Returns:
            A list of dicts with keys ``organization``, ``role_title``,
            ``department``, ``start_date``, ``end_date``.
        """
        clean_id = self._clean_orcid_id(orcid_id)
        if not clean_id:
            return []
        try:
            data = self._request_json(
                f"{self.BASE_URL}/{clean_id}/employments",
                cache_key=self._cache_key("orcid_employments", clean_id),
            )
        except Exception as exc:
            self.logger.error("ORCID fetch_employments(%s): %s", orcid_id, exc)
            return []
        out: List[Dict[str, Any]] = []
        groups = data.get("affiliation-group", []) or []
        for g in groups:
            for s in g.get("summaries", []) or []:
                summary = s.get("employment-summary", {}) if isinstance(s, dict) else {}
                if not summary:
                    continue
                out.append(self._summarize_affiliation(summary))
        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _request_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        cache_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Perform a retrying GET against the ORCID API via BaseScraper."""
        resp = self._make_request(
            "GET", url, params=params, headers=self._headers(),
            cache_key=cache_key,
        )
        if resp.status_code >= 400:
            self.logger.warning("ORCID HTTP %d: %s", resp.status_code, resp.text[:200])
        try:
            return resp.json()
        except ValueError:
            self.logger.warning("ORCID response was non-JSON: %s", resp.text[:200])
            return {}

    def _headers(self) -> Dict[str, str]:
        return {"User-Agent": self.user_agent, "Accept": "application/json"}

    def _user_agent(self, polite_email: Optional[str]) -> str:
        ua = "AcademicResearchSuite/1.0"
        if polite_email:
            ua += f" (mailto:{polite_email})"
        return ua

    @staticmethod
    def _clean_orcid_id(orcid_id: str) -> str:
        if not orcid_id:
            return ""
        s = orcid_id.strip()
        if s.startswith("http"):
            s = s.split("/orcid.org/")[-1] if "/orcid.org/" in s else s.split("/")[-1]
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) != 16:
            return ""
        return f"{digits[0:4]}-{digits[4:8]}-{digits[8:12]}-{digits[12:16]}"

    def _work_to_paper(self, work: Dict[str, Any], orcid_id: str) -> Paper:
        """Convert an ORCID work-summary dict to a :class:`Paper`."""
        title_obj = work.get("title", {}) or {}
        title = title_obj.get("title", {}).get("value", "") if isinstance(title_obj, dict) else ""

        # Publication date → year
        year: Optional[int] = None
        pub_date = work.get("publication-date") or {}
        year_raw = pub_date.get("year", {})
        if isinstance(year_raw, dict):
            year_val = year_raw.get("value")
        else:
            year_val = year_raw
        if year_val:
            try:
                year = int(year_val)
            except (TypeError, ValueError):
                year = None

        # External IDs → DOI, URL
        ext_ids = work.get("external-ids", {}).get("external-id", []) or []
        doi: Optional[str] = None
        url: Optional[str] = None
        for ext in ext_ids:
            ext_type = ext.get("external-id-type")
            ext_val = ext.get("external-id-value")
            ext_url = ext.get("external-id-url") or {}
            if isinstance(ext_url, dict):
                ext_url = ext_url.get("value")
            if ext_type == "doi" and ext_val:
                doi = ext_val
            if ext_url and not url:
                url = ext_url
        if not url and doi:
            url = f"https://doi.org/{doi}"

        # Journal/venue
        journal_obj = work.get("journal-title", {})
        journal = journal_obj.get("value", "") if isinstance(journal_obj, dict) else None

        # Citation info
        citation = work.get("citation", {}) or {}
        citation_value = citation.get("citation-value", "") if isinstance(citation, dict) else ""

        return Paper(
            title=title,
            authors=[],  # ORCID work-summary doesn't include authors
            year=year,
            abstract="",
            doi=doi,
            url=url,
            source=self.name,
            citations_count=None,
            references=[],
            keywords=[],
            pdf_url=None,
            issn=None,
            isbn=None,
            publisher=None,
            journal=journal or None,
            volume=None,
            issue=None,
            pages=None,
            language=None,
            paper_type=work.get("type"),
            fields_of_study=[],
            raw={
                "orcid_id": orcid_id,
                "orcid_put_code": work.get("put-code"),
                "external_ids": ext_ids,
                "citation": citation_value,
                "citation_type": citation.get("citation-type") if isinstance(citation, dict) else None,
                "publication_date": pub_date,
            },
        )

    def _summarize_affiliation(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Reduce an ORCID employment-summary to a flat dict."""
        org = summary.get("organization", {}) or {}
        org_name = (org.get("name", {}) or {}).get("value", "") if isinstance(org.get("name"), dict) else org.get("name")
        address = org.get("address", {}) or {}
        city = address.get("city", {}).get("value") if isinstance(address.get("city"), dict) else address.get("city")
        country = address.get("country", {}).get("value") if isinstance(address.get("country"), dict) else address.get("country")

        def _date(d: Dict[str, Any]) -> Optional[str]:
            if not isinstance(d, dict):
                return None
            year = (d.get("year", {}) or {}).get("value") if isinstance(d.get("year"), dict) else d.get("year")
            month = (d.get("month", {}) or {}).get("value") if isinstance(d.get("month"), dict) else d.get("month")
            day = (d.get("day", {}) or {}).get("value") if isinstance(d.get("day"), dict) else d.get("day")
            if not year:
                return None
            return "-".join(str(x) for x in (year, month, day) if x)

        def _field(d: Any) -> Optional[str]:
            if isinstance(d, dict):
                return d.get("value")
            return d

        return {
            "organization": org_name,
            "city": city,
            "country": country,
            "role_title": _field(summary.get("role-title")),
            "department": _field(summary.get("department-name")),
            "start_date": _date(summary.get("start-date") or {}),
            "end_date": _date(summary.get("end-date") or {}),
        }

    # Aliases for fetch_orcid_profile to keep things tidy.
    def _fetch_educations(self, orcid_id: str) -> List[Dict[str, Any]]:
        try:
            data = self._request_json(
                f"{self.BASE_URL}/{orcid_id}/educations",
                cache_key=self._cache_key("orcid_educations", orcid_id),
            )
        except Exception as exc:
            self.logger.warning("ORCID _fetch_educations(%s): %s", orcid_id, exc)
            return []
        out: List[Dict[str, Any]] = []
        for g in data.get("affiliation-group", []) or []:
            for s in g.get("summaries", []) or []:
                summary = s.get("education-summary", {}) if isinstance(s, dict) else {}
                if summary:
                    out.append(self._summarize_affiliation(summary))
        return out

    def _fetch_fundings(self, orcid_id: str) -> List[Dict[str, Any]]:
        try:
            data = self._request_json(
                f"{self.BASE_URL}/{orcid_id}/fundings",
                cache_key=self._cache_key("orcid_fundings", orcid_id),
            )
        except Exception as exc:
            self.logger.warning("ORCID _fetch_fundings(%s): %s", orcid_id, exc)
            return []
        out: List[Dict[str, Any]] = []
        for g in data.get("group", []) or []:
            for s in g.get("funding-summary", []) or []:
                if isinstance(s, dict):
                    out.append({
                        "title": (s.get("title", {}).get("title", {}).get("value", "") if isinstance(s.get("title"), dict) else ""),
                        "funder": s.get("organization", {}).get("name", {}).get("value") if isinstance(s.get("organization"), dict) else None,
                        "start_date": s.get("start-date", {}).get("year", {}).get("value") if isinstance(s.get("start-date"), dict) else None,
                        "end_date": s.get("end-date", {}).get("year", {}).get("value") if isinstance(s.get("end-date"), dict) else None,
                        "amount": s.get("amount", {}).get("value") if isinstance(s.get("amount"), dict) else None,
                    })
        return out

    def _fetch_peer_reviews(self, orcid_id: str) -> List[Dict[str, Any]]:
        try:
            data = self._request_json(
                f"{self.BASE_URL}/{orcid_id}/peer-reviews",
                cache_key=self._cache_key("orcid_peer_reviews", orcid_id),
            )
        except Exception as exc:
            self.logger.warning("ORCID _fetch_peer_reviews(%s): %s", orcid_id, exc)
            return []
        out: List[Dict[str, Any]] = []
        for g in data.get("group", []) or []:
            for s in g.get("peer-review-summary", []) or []:
                if isinstance(s, dict):
                    out.append({
                        "reviewer_role": s.get("reviewer-role"),
                        "review_type": s.get("review-type"),
                        "review_completion_date": s.get("review-completion-date"),
                        "convening_organization": s.get("convening-organization", {}).get("name", {}).get("value") if isinstance(s.get("convening-organization"), dict) else None,
                    })
        return out


__all__ = ["ORCIDScraper"]
