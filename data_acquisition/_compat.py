"""
_compat.py
==========

Internal compatibility shims for the ``data_acquisition`` package.

This module provides fallback implementations of the shared types
(``Paper``, ``ScraperResult``, ``BaseScraper``) that scrapers depend
on. If ``data_acquisition.base_scraper`` (authored by sibling agent
``1-scraper-a``) is present, the real classes are re-exported.
Otherwise, minimal fallback classes are used so every scraper remains
independently importable during the parallel build phase.

The fallbacks intentionally mirror the sibling's interface so callers
can rely on a single consistent schema.
"""
from __future__ import annotations
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

# ---------------------------------------------------------------------------
# Shared base types
# ---------------------------------------------------------------------------

try:  # pragma: no cover - exercised when sibling module exists
    from .base_scraper import BaseScraper, Paper, ScraperResult  # type: ignore
    _BASE_FROM_SIBLING = True
except ImportError:  # pragma: no cover - exercised during parallel build
    _BASE_FROM_SIBLING = False

    @dataclass
    class Paper:
        """Fallback representation of a scientific publication record.

        Mirrors the sibling agent's :class:`data_acquisition.base_scraper.Paper`
        schema so all downstream consumers see a single shape.
        """

        title: str = ""
        authors: List[str] = field(default_factory=list)
        abstract: str = ""
        year: Optional[int] = None
        doi: Optional[str] = None
        url: Optional[str] = None
        source: str = ""
        citations_count: Optional[int] = None
        references: List[str] = field(default_factory=list)
        keywords: List[str] = field(default_factory=list)
        pdf_url: Optional[str] = None
        issn: Optional[str] = None
        isbn: Optional[str] = None
        publisher: Optional[str] = None
        journal: Optional[str] = None
        volume: Optional[str] = None
        issue: Optional[str] = None
        pages: Optional[str] = None
        language: Optional[str] = None
        paper_type: Optional[str] = None
        fields_of_study: List[str] = field(default_factory=list)
        raw: Dict[str, Any] = field(default_factory=dict)

        def to_dict(self) -> Dict[str, Any]:
            from dataclasses import asdict
            return asdict(self)

        @classmethod
        def from_dict(cls, data: Mapping[str, Any]) -> "Paper":
            valid_keys = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
            filtered = {k: v for k, v in dict(data).items() if k in valid_keys}
            return cls(**filtered)

    @dataclass
    class ScraperResult:
        """Fallback container for the outcome of a scraper invocation."""

        source: str = ""
        query: str = ""
        total_results: int = 0
        papers: List[Paper] = field(default_factory=list)
        raw_response: Any = None
        timestamp: str = field(
            default_factory=lambda: datetime.now(timezone.utc).isoformat()
        )
        elapsed_ms: int = 0
        errors: List[str] = field(default_factory=list)

        def to_dict(self) -> Dict[str, Any]:
            return {
                "source": self.source,
                "query": self.query,
                "total_results": self.total_results,
                "papers": [p.to_dict() if hasattr(p, "to_dict") else p for p in self.papers],
                "raw_response": self.raw_response,
                "timestamp": self.timestamp,
                "elapsed_ms": self.elapsed_ms,
                "errors": list(self.errors),
            }

    class BaseScraper(ABC):  # type: ignore[no-redef]
        """Fallback BaseScraper abstract class used during the build phase."""

        SOURCE_NAME: str = "base"

        def __init__(
            self,
            proxy_manager: Optional[Any] = None,
            rate_limit: float = 1.0,
            cache: Optional[Any] = None,
            timeout: float = 30.0,
            max_retries: int = 3,
            user_agent: Optional[str] = None,
        ) -> None:
            self.proxy_manager = proxy_manager
            self.rate_limit = float(rate_limit)
            self.timeout = float(timeout)
            self.max_retries = int(max_retries)
            self.user_agent = user_agent or "AcademicResearchSuite/0.1"
            self._cache = cache
            self.logger = logging.getLogger(self.__class__.__module__)

        @property
        def name(self) -> str:
            return self.SOURCE_NAME

        @abstractmethod
        def search(self, query: str, **kwargs: Any) -> ScraperResult:
            ...

        @abstractmethod
        def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
            ...


# ---------------------------------------------------------------------------
# Logger helper
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """Return a configured logger.

    Prefers ``utils.logger.setup_logger`` when available so that the
    project's central logging configuration is honoured; falls back to
    ``logging.getLogger`` otherwise, ensuring the module is always
    importable.
    """
    try:
        from utils.logger import setup_logger  # type: ignore
        return setup_logger(name)
    except Exception:  # pragma: no cover - fallback path
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
            )
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger


__all__ = [
    "BaseScraper",
    "Paper",
    "ScraperResult",
    "get_logger",
    "_BASE_FROM_SIBLING",
]


# ---------------------------------------------------------------------------
# v2.0.0 — extra scraper dataclasses (added by sub-agent v2-extras)
# ---------------------------------------------------------------------------
#
# These small dataclasses live in ``_compat`` so the new v2 scrapers can
# import them from a single, always-available location.  When the real
# classes are also defined in their owning modules (e.g.
# :class:`data_acquisition.unpaywall_scraper.OpenAccessLocation`),
# those modules **re-import** them from here to avoid duplication.
#
# Importing these classes here is safe because they depend only on the
# standard library (``dataclasses``, ``typing``).

from dataclasses import dataclass, field as _dc_field  # noqa: E402


@dataclass
class OpenAccessLocation:
    """Normalised open-access location record.

    Mirrors :class:`data_acquisition.unpaywall_scraper.OpenAccessLocation`
    so callers can import it from either module interchangeably.

    Attributes:
        doi: The DOI the OA info refers to.
        title: Article title.
        journal: Journal name.
        publisher: Publisher name.
        year: Publication year.
        is_oa: Whether an OA version exists.
        oa_status: ``green`` | ``gold`` | ``hybrid`` | ``bronze`` | ``closed``.
        oa_url: Best OA URL (HTML landing page or PDF).
        pdf_url: Direct PDF link.
        host_type: ``publisher`` or ``repository``.
        version: ``publishedVersion`` | ``acceptedManuscript`` |
            ``submittedVersion``.
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
        from dataclasses import asdict
        return asdict(self)


@dataclass
class Citation:
    """Normalised OpenCitations citation record.

    Mirrors :class:`data_acquisition.opencitations_scraper.Citation`.

    Attributes:
        citing_doi: DOI of the citing paper.
        cited_doi: DOI of the cited paper.
        creation_date: ISO-8601 creation date of the citing paper.
        author: First-author string of the citing paper.
        journal: Source journal of the citing paper.
        timespan: OpenCitations timespan string.
    """

    citing_doi: Optional[str] = None
    cited_doi: Optional[str] = None
    creation_date: Optional[str] = None
    author: Optional[str] = None
    journal: Optional[str] = None
    timespan: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


@dataclass
class WikipediaArticle:
    """Normalised Wikipedia article record.

    Mirrors :class:`data_acquisition.wikipedia_scraper.WikipediaArticle`.

    Attributes:
        title: Wikipedia page title.
        url: Canonical Wikipedia URL.
        summary: Lead-section summary text.
        content: Optional full-page extract.
        categories: List of Wikipedia category names.
        references: List of raw reference strings.
    """

    title: str = ""
    url: str = ""
    summary: str = ""
    content: str = ""
    categories: List[str] = _dc_field(default_factory=list)
    references: List[str] = _dc_field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)


__all__ += [
    "OpenAccessLocation",
    "Citation",
    "WikipediaArticle",
]
