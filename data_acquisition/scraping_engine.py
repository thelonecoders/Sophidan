"""
scraping_engine.py
==================

High-level orchestration facade for multi-source academic data
acquisition.

:class:`ScrapingEngine` registers individual scrapers (any subclass
of :class:`BaseScraper`) and exposes:

* :meth:`search_all` — fan a query out across multiple sources in
  parallel, then merge and de-duplicate the results.
* :meth:`search_advanced` — same as :meth:`search_all` but with
  per-source filter translation (e.g. ``year_lo`` → Crossref
  ``from-pub-date``, → DBLP ``year``).
* :meth:`export_results` — export a :class:`ScraperResult` to CSV,
  JSON, BibTeX or XLSX.

Qt signals
----------
The engine inherits from ``QObject`` (via the ``qtpy`` shim that
abstracts PyQt5 / PySide2). It emits:

* ``scrape_started(str)`` — the query string.
* ``progress(int, str)`` — percent complete and a human-readable status.
* ``scrape_completed(ScraperResult)`` — the merged result.
* ``scrape_error(str)`` — error message when a source fails (the
  engine continues with the remaining sources).

EventBus / TaskQueue integration
-------------------------------
When the project's :class:`core.events.EventBus` is available,
every signal above is also published as a topic event so non-Qt
subscribers can react. When :class:`core.task_queue.TaskQueue` is
available, :meth:`search_all` can be enqueued as a background task
via :meth:`search_all_async`.
"""
from __future__ import annotations
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from ._compat import BaseScraper, Paper, ScraperResult, get_logger
from .doi_lookup import DOILookup

# Qt: use the qtpy shim so PyQt5 / PySide2 are interchangeable.
try:
    from qtpy.QtCore import QObject, Signal  # type: ignore
    _QT_AVAILABLE = True
except Exception:  # pragma: no cover - fallback for headless environments
    _QT_AVAILABLE = False

    class QObject:  # type: ignore[no-redef]
        """Minimal QObject fallback so the engine is importable without Qt."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    class Signal:  # type: ignore[no-redef]
        """Drop-in replacement for ``qtpy.Signal`` without Qt.

        Implements ``connect`` / ``emit`` / ``disconnect`` on a plain
        Python object so non-Qt callers can still wire up handlers.
        """

        def __init__(self, *arg_types: Any) -> None:
            self._handlers: List[Callable[..., Any]] = []

        def connect(self, handler: Callable[..., Any]) -> Callable[..., Any]:
            if handler not in self._handlers:
                self._handlers.append(handler)
            return handler

        def disconnect(self, handler: Optional[Callable[..., Any]] = None) -> None:
            if handler is None:
                self._handlers.clear()
            elif handler in self._handlers:
                self._handlers.remove(handler)

        def emit(self, *args: Any, **kwargs: Any) -> None:
            for h in list(self._handlers):
                try:
                    h(*args, **kwargs)
                except Exception:  # pragma: no cover - defensive
                    logging.getLogger(__name__).exception("Signal handler raised")


# Optional: core.events.EventBus (sibling agent builds this)
try:
    from core.events import EventBus  # type: ignore
    _EVENT_BUS_AVAILABLE = True
except Exception:  # pragma: no cover
    EventBus = None  # type: ignore
    _EVENT_BUS_AVAILABLE = False

# Optional: core.task_queue.TaskQueue
try:
    from core.task_queue import TaskQueue  # type: ignore
    _TASK_QUEUE_AVAILABLE = True
except Exception:  # pragma: no cover
    TaskQueue = None  # type: ignore
    _TASK_QUEUE_AVAILABLE = False


class ScrapingEngine(QObject):
    """Facade orchestrating multi-source academic data scraping."""

    # Qt signals.
    scrape_started = Signal(str)
    progress = Signal(int, str)
    scrape_completed = Signal(object)  # ScraperResult
    scrape_error = Signal(str)

    def __init__(
        self,
        event_bus: Optional[Any] = None,
        task_queue: Optional[Any] = None,
        max_workers: int = 4,
        proxy_manager: Optional[Any] = None,
    ) -> None:
        """Initialize the engine.

        Args:
            event_bus: Optional ``EventBus`` instance. If omitted and
                :mod:`core.events` is importable, the singleton bus
                from that module is used.
            task_queue: Optional ``TaskQueue`` instance for background
                execution. If omitted and :mod:`core.task_queue` is
                importable, no default queue is bound (callers must
                explicitly pass one to use :meth:`search_all_async`).
            max_workers: Default thread-pool size for fan-out.
            proxy_manager: Optional proxy manager (any object exposing
                ``get_proxy() -> Optional[str]``). When provided, the
                engine forwards it to every registered scraper that
                accepts a ``proxy_manager`` kwarg on construction or
                exposes a ``proxy_manager`` settable attribute. Duck-
                typed so :class:`proxy.proxy_manager.ProxyManager` or
                :class:`proxy.proxy_pool.ProxyPool` both work.
        """
        super().__init__()
        self.logger: logging.Logger = get_logger(__name__)
        self._scrapers: Dict[str, BaseScraper] = {}
        self._max_workers = max_workers
        self._proxy_manager = proxy_manager

        # EventBus resolution.
        if event_bus is not None:
            self._event_bus = event_bus
        elif _EVENT_BUS_AVAILABLE:
            try:
                self._event_bus = (
                    EventBus.get_instance()  # type: ignore[assignment]
                    if hasattr(EventBus, "get_instance")
                    else EventBus()  # type: ignore[assignment]
                )
            except Exception:  # pragma: no cover - defensive
                self._event_bus = None
        else:
            self._event_bus = None

        # TaskQueue (kept by reference; not auto-instantiated).
        self._task_queue = task_queue

        # Wire signals to also publish on the EventBus (if any).
        if self._event_bus is not None:
            self.scrape_started.connect(
                lambda q: self._publish("scrape.started", {"query": q})
            )
            self.progress.connect(
                lambda pct, msg: self._publish(
                    "scrape.progress", {"percent": pct, "message": msg}
                )
            )
            self.scrape_completed.connect(
                lambda r: self._publish("scrape.completed", {"result": r})
            )
            self.scrape_error.connect(
                lambda err: self._publish("scrape.error", {"error": err})
            )

        # v2.0.0 — auto-register the built-in scrapers.  Each scraper
        # is instantiated inside a try/except so a missing dependency
        # (or a missing API key for the v2 sources) does not break the
        # engine.  Only scrapers that successfully instantiate are
        # registered; :meth:`available_scrapers` therefore reflects
        # the *effective* set of usable sources at runtime.
        self._register_default_scrapers()

    # ------------------------------------------------------------------
    # Default scraper registration (added by sub-agent v2-extras)
    # ------------------------------------------------------------------
    def _register_default_scrapers(self) -> None:
        """Auto-register the built-in v1 + v2 scrapers.

        v1 scrapers (arXiv, PubMed, OpenAlex, Semantic Scholar,
        Google Scholar, Crossref, DBLP, ORCID) are always
        registered — they have no hard API-key requirements.

        v2 scrapers that require an API key (Springer, IEEE, CORE,
        BASE — optional) are only registered when their respective
        key is discoverable (env var or ``config.settings``).

        Keyless v2 scrapers (ACM, OpenCitations, Unpaywall — email
        only, SciOpen, Wikipedia) are always registered.
        """
        # ---- v1 scrapers (always-on; no API key required) ----
        v1_specs: List[Dict[str, Any]] = [
            {"name": "arxiv", "module": ".arxiv_scraper", "class": "ArxivScraper",
             "kwargs": {"rate_limit": 0.33}},
            {"name": "pubmed", "module": ".pubmed_scraper", "class": "PubMedScraper",
             "kwargs": {}},
            {"name": "openalex", "module": ".openalex_scraper", "class": "OpenAlexScraper",
             "kwargs": {"rate_limit": 5.0}},
            {"name": "semantic_scholar", "module": ".semantic_scholar_scraper",
             "class": "SemanticScholarScraper", "kwargs": {"rate_limit": 0.33}},
            {"name": "google_scholar", "module": ".google_scholar_scraper",
             "class": "GoogleScholarScraper", "kwargs": {}},
            {"name": "crossref", "module": ".crossref_scraper",
             "class": "CrossrefScraper", "kwargs": {"rate_limit": 5.0}},
            {"name": "dblp", "module": ".dblp_scraper", "class": "DBLPScraper",
             "kwargs": {}},
            {"name": "orcid", "module": ".orcid_scraper", "class": "ORCIDScraper",
             "kwargs": {}},
        ]
        # ---- v2 scrapers (keyless — always-on) ----
        v2_keyless: List[Dict[str, Any]] = [
            {"name": "acm", "module": ".acm_scraper",
             "class": "ACMDigitalLibraryScraper", "kwargs": {"rate_limit": 0.33}},
            {"name": "opencitations", "module": ".opencitations_scraper",
             "class": "OpenCitationsScraper", "kwargs": {"rate_limit": 3.0}},
            {"name": "unpaywall", "module": ".unpaywall_scraper",
             "class": "UnpaywallScraper", "kwargs": {"rate_limit": 5.0}},
            {"name": "sciopen", "module": ".sciopen_scraper",
             "class": "SciOpenScraper", "kwargs": {"rate_limit": 0.33}},
            {"name": "wikipedia", "module": ".wikipedia_scraper",
             "class": "WikipediaScraper", "kwargs": {"rate_limit": 3.0}},
        ]
        # ---- v2 scrapers (API-key required — conditional) ----
        v2_keyed: List[Dict[str, Any]] = [
            {"name": "springer", "module": ".springer_scraper",
             "class": "SpringerScraper", "kwargs": {},
             "needs_key_attr": "api_key"},
            {"name": "ieee", "module": ".ieee_scraper",
             "class": "IEEEXploreScraper", "kwargs": {},
             "needs_key_attr": "api_key"},
            {"name": "core", "module": ".core_scraper",
             "class": "COREScraper", "kwargs": {},
             "needs_key_attr": "api_key"},
            {"name": "base", "module": ".base_scraper_ext",
             "class": "BASEScraper", "kwargs": {},
             "needs_key_attr": "api_key"},
        ]

        for spec in v1_specs + v2_keyless:
            self._try_register(spec)

        for spec in v2_keyed:
            self._try_register(spec, key_required=True,
                               key_attr=spec.get("needs_key_attr", "api_key"))

    def _try_register(
        self,
        spec: Dict[str, Any],
        key_required: bool = False,
        key_attr: str = "api_key",
    ) -> None:
        """Attempt to instantiate and register a scraper from ``spec``.

        Args:
            spec: Dict with ``name``, ``module``, ``class``, ``kwargs``.
            key_required: If ``True``, the scraper is only registered
                when its post-construction ``key_attr`` attribute is
                truthy (i.e. an API key was found).
            key_attr: Name of the attribute to inspect when
                ``key_required`` is ``True``.
        """
        name = spec["name"]
        module_name = spec["module"]
        class_name = spec["class"]
        kwargs: Dict[str, Any] = dict(spec.get("kwargs") or {})
        # Forward the engine's proxy_manager so the scraper inherits it.
        if self._proxy_manager is not None and "proxy_manager" not in kwargs:
            kwargs["proxy_manager"] = self._proxy_manager
        try:
            import importlib
            module = importlib.import_module(module_name, package=__package__)
            scraper_cls = getattr(module, class_name)
            scraper = scraper_cls(**kwargs)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug(
                "Skipping scraper %s (could not instantiate): %s", name, exc,
            )
            return
        if key_required:
            if not getattr(scraper, key_attr, None):
                self.logger.debug(
                    "Skipping scraper %s (no API key found via %s).",
                    name, key_attr,
                )
                return
        try:
            self.register_scraper(name, scraper)
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Failed to register scraper %s: %s", name, exc)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register_scraper(self, name: str, scraper: BaseScraper) -> None:
        """Register a scraper under a logical name.

        Args:
            name: Logical name (e.g. ``"crossref"``).
            scraper: An instance of a :class:`BaseScraper` subclass.
        """
        if not isinstance(scraper, BaseScraper):
            raise TypeError("scraper must be a BaseScraper instance")
        if not name:
            raise ValueError("name must be non-empty")
        self.logger.info("Registering scraper: %s", name)
        # If a proxy_manager is configured, propagate it to the scraper
        # (only when the scraper doesn't already have one set).
        if self._proxy_manager is not None:
            try:
                current = getattr(scraper, "proxy_manager", None)
                if current is None:
                    setattr(scraper, "proxy_manager", self._proxy_manager)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug(
                    "Could not propagate proxy_manager to %s: %s", name, exc,
                )
        self._scrapers[name] = scraper

    def unregister_scraper(self, name: str) -> None:
        """Remove a previously-registered scraper."""
        self._scrapers.pop(name, None)

    def available_scrapers(self) -> List[str]:
        """Return the names of all registered scrapers."""
        return list(self._scrapers.keys())

    def get_scraper(self, name: str) -> Optional[BaseScraper]:
        """Return the scraper registered under ``name`` (or ``None``)."""
        return self._scrapers.get(name)

    @property
    def proxy_manager(self) -> Any:
        """Return the proxy manager (or ``None`` if not configured)."""
        return self._proxy_manager

    @proxy_manager.setter
    def proxy_manager(self, value: Any) -> None:
        """Set the proxy manager and propagate it to all registered scrapers."""
        self._proxy_manager = value
        if value is not None:
            for scraper in self._scrapers.values():
                try:
                    if getattr(scraper, "proxy_manager", None) is None:
                        setattr(scraper, "proxy_manager", value)
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.debug(
                        "Could not propagate proxy_manager: %s", exc,
                    )

    # ------------------------------------------------------------------
    # Fan-out search
    # ------------------------------------------------------------------
    def search_all(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> ScraperResult:
        """Run ``query`` against multiple scrapers in parallel.

        Args:
            query: Search string.
            sources: Optional list of scraper names; defaults to all
                registered scrapers.
            **kwargs: Additional keyword arguments forwarded to each
                scraper's ``search`` method.

        Returns:
            A merged :class:`ScraperResult` with de-duplicated papers.
        """
        target_sources = self._resolve_sources(sources)
        if not target_sources:
            err = "No scrapers registered."
            self.scrape_error.emit(err)
            merged = ScraperResult(source="multi", query=query)
            merged.errors.append(err)
            return merged

        self.scrape_started.emit(query)
        self.logger.info(
            "search_all: query=%r, sources=%s", query, target_sources
        )

        merged = ScraperResult(source="multi", query=query)
        per_source: Dict[str, ScraperResult] = {}

        total = len(target_sources)
        completed = 0
        max_workers = max(1, min(self._max_workers, total))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._invoke_scraper, name, query, kwargs): name
                for name in target_sources
            }
            for future in as_completed(futures):
                name = futures[future]
                completed += 1
                pct = int(100 * completed / total)
                try:
                    sub_result = future.result()
                except Exception as exc:
                    self.logger.warning("Scraper %s raised: %s", name, exc)
                    self.scrape_error.emit(f"[{name}] {exc}")
                    self.progress.emit(pct, f"{name} failed: {exc}")
                    continue
                per_source[name] = sub_result
                if sub_result.errors:
                    for err in sub_result.errors:
                        self.scrape_error.emit(f"[{name}] {err}")
                merged.papers.extend(sub_result.papers)
                merged.errors.extend(f"[{name}] {err}" for err in sub_result.errors)
                self.progress.emit(pct, f"{name}: {len(sub_result.papers)} papers")

        # Deduplicate.
        before = len(merged.papers)
        merged.papers = self._dedupe(merged.papers)
        after = len(merged.papers)
        self.logger.info("search_all merged %d -> %d after dedup.", before, after)

        # Aggregate metadata into raw_response.
        merged.total_results = sum(r.total_results for r in per_source.values())
        merged.raw_response = {
            "sources": target_sources,
            "per_source_counts": {
                name: len(r.papers) for name, r in per_source.items()
            },
            "deduped_count": before - after,
        }
        self.scrape_completed.emit(merged)
        return merged

    def search_all_async(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        callback: Optional[Callable[[ScraperResult], None]] = None,
        **kwargs: Any,
    ) -> Any:
        """Enqueue :meth:`search_all` onto the bound TaskQueue.

        Requires that the engine was constructed with a
        :class:`core.task_queue.TaskQueue` instance.

        Args:
            query: Search string.
            sources: Optional source list.
            callback: Optional callable invoked with the result when
                the background task completes.
            **kwargs: Forwarded to ``search_all``.

        Returns:
            The task id / future returned by the TaskQueue (or
            ``None`` if no TaskQueue is bound).
        """
        if self._task_queue is None:
            self.logger.error(
                "search_all_async called without a bound TaskQueue; "
                "running synchronously."
            )
            result = self.search_all(query, sources, **kwargs)
            if callback:
                callback(result)
            return None
        # Submit using whatever API the TaskQueue exposes.
        if hasattr(self._task_queue, "submit"):
            return self._task_queue.submit(self.search_all, query, sources, **kwargs)
        if hasattr(self._task_queue, "enqueue"):
            return self._task_queue.enqueue(self.search_all, query, sources, **kwargs)
        # Fallback to thread.
        thread = threading.Thread(
            target=self._run_async,
            args=(query, sources, callback, kwargs),
            daemon=True,
        )
        thread.start()
        return thread

    def _run_async(
        self,
        query: str,
        sources: Optional[List[str]],
        callback: Optional[Callable[[ScraperResult], None]],
        kwargs: Dict[str, Any],
    ) -> None:
        """Internal: run search_all on a worker thread."""
        try:
            result = self.search_all(query, sources, **kwargs)
            if callback:
                callback(result)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.exception("Async search failed: %s", exc)
            self.scrape_error.emit(str(exc))

    # ------------------------------------------------------------------
    # Advanced search with filter translation
    # ------------------------------------------------------------------
    def search_advanced(
        self,
        query: str,
        filters: Dict[str, Any],
        sources: Optional[List[str]] = None,
    ) -> ScraperResult:
        """Run a multi-source search with translated per-source filters.

        Args:
            query: Search string.
            filters: Cross-source filter dictionary. Recognised keys
                include ``year_lo``, ``year_hi``, ``year`` (exact),
                ``venue``, ``author``, ``type``,
                ``has_full_text`` (bool), ``has_license`` (bool).
            sources: Optional list of source names.

        Returns:
            A merged :class:`ScraperResult`.
        """
        target_sources = self._resolve_sources(sources)
        self.scrape_started.emit(query)
        merged = ScraperResult(source="multi", query=query)

        total = len(target_sources)
        completed = 0
        max_workers = max(1, min(self._max_workers, total))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for name in target_sources:
                scraper = self._scrapers[name]
                kwargs = self._translate_filters(name, scraper, filters)
                futures[executor.submit(self._invoke_scraper, name, query, kwargs)] = name

            for future in as_completed(futures):
                name = futures[future]
                completed += 1
                pct = int(100 * completed / total)
                try:
                    sub_result = future.result()
                except Exception as exc:
                    self.scrape_error.emit(f"[{name}] {exc}")
                    self.progress.emit(pct, f"{name} failed: {exc}")
                    continue
                merged.papers.extend(sub_result.papers)
                merged.errors.extend(f"[{name}] {err}" for err in sub_result.errors)
                self.progress.emit(pct, f"{name}: {len(sub_result.papers)} papers")

        before = len(merged.papers)
        merged.papers = self._dedupe(merged.papers)
        after = len(merged.papers)
        merged.total_results = before
        merged.raw_response = {"deduped_count": before - after}
        self.scrape_completed.emit(merged)
        return merged

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_results(
        self,
        result: ScraperResult,
        format: str = "csv",
    ) -> Any:
        """Export a :class:`ScraperResult` to a target format.

        Args:
            result: The result to export.
            format: One of ``"csv"``, ``"json"``, ``"bibtex"``,
                ``"xlsx"``.

        Returns:
            ``str`` for ``csv`` / ``json`` / ``bibtex``; ``bytes``
            for ``xlsx``.
        """
        fmt = (format or "").lower()
        if fmt == "csv":
            return self._export_csv(result)
        if fmt == "json":
            return self._export_json(result)
        if fmt == "bibtex":
            return self._export_bibtex(result)
        if fmt == "xlsx":
            return self._export_xlsx(result)
        raise ValueError(f"Unsupported export format: {format!r}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_sources(self, sources: Optional[List[str]]) -> List[str]:
        if not sources:
            return list(self._scrapers.keys())
        missing = [s for s in sources if s not in self._scrapers]
        if missing:
            self.logger.warning("Unknown sources requested: %s", missing)
        return [s for s in sources if s in self._scrapers]

    def _invoke_scraper(
        self,
        name: str,
        query: str,
        kwargs: Dict[str, Any],
    ) -> ScraperResult:
        """Call ``scraper.search(query, **kwargs)`` and normalise output.

        Tolerates scrapers that return a pandas DataFrame or a list
        of dicts instead of a :class:`ScraperResult` (legacy contract).
        """
        scraper = self._scrapers[name]
        try:
            self.logger.info("Invoking %s.search(%r, %s)", name, query, kwargs)
            res = scraper.search(query, **kwargs)
        except TypeError:
            # Scraper exposes the legacy ``execute_query`` signature.
            self.logger.debug(
                "Scraper %s has no search(); falling back to execute_query()", name
            )
            res = scraper.execute_query(query, **kwargs)  # type: ignore[attr-defined]
        except Exception as exc:
            self.logger.warning("Scraper %s raised during search: %s", name, exc)
            raise

        # Normalise: if scraper returned a DataFrame, wrap it.
        if isinstance(res, ScraperResult):
            if not res.source:
                res.source = name
            return res
        try:
            import pandas as pd  # type: ignore
            if isinstance(res, pd.DataFrame):
                papers = self._dataframe_to_papers(res, source=name)
                return ScraperResult(
                    source=name, query=query, papers=papers,
                    total_results=len(papers),
                )
        except Exception:  # pragma: no cover
            pass
        # Fallback: wrap any iterable of dicts.
        if isinstance(res, list):
            papers = [
                p if isinstance(p, Paper) else self._dict_to_paper(p, name)
                for p in res
            ]
            return ScraperResult(
                source=name, query=query, papers=papers,
                total_results=len(papers),
            )
        # Last resort: empty result.
        return ScraperResult(
            source=name, query=query,
            errors=["Unrecognised scraper output."],
        )

    def _translate_filters(
        self,
        source_name: str,
        scraper: BaseScraper,
        filters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Translate a cross-source filter dict to a per-source kwargs dict."""
        kwargs: Dict[str, Any] = {}
        name = source_name.lower()
        year_lo = filters.get("year_lo")
        year_hi = filters.get("year_hi")
        year = filters.get("year")
        venue = filters.get("venue")
        author = filters.get("author")
        has_full_text = filters.get("has_full_text")
        has_license = filters.get("has_license")
        doc_type = filters.get("type")

        if "crossref" in name:
            cr_filters: Dict[str, Any] = {}
            if year_lo:
                cr_filters["from_pub_date"] = f"{year_lo}-01-01"
            if year_hi:
                cr_filters["until_pub_date"] = f"{year_hi}-12-31"
            if venue:
                cr_filters["container_title"] = venue
            if author:
                cr_filters["author"] = author
            if doc_type:
                cr_filters["type"] = doc_type
            if has_full_text is not None:
                cr_filters["has_full_text"] = bool(has_full_text)
            if has_license is not None:
                cr_filters["has_license"] = bool(has_license)
            if cr_filters:
                kwargs["filters"] = cr_filters
        elif "dblp" in name:
            if year is not None:
                kwargs["year"] = year
            elif year_lo is not None and year_hi is not None and year_lo == year_hi:
                kwargs["year"] = year_lo
            if venue:
                kwargs["venue"] = venue
        elif "scholar" in name:
            if year_lo is not None:
                kwargs["year_lo"] = year_lo
            if year_hi is not None:
                kwargs["year_hi"] = year_hi
        elif "openalex" in name:
            # OpenAlex takes filter strings like
            # "from_publication_date:YYYY-MM-DD".
            oa_filters: List[str] = []
            if year_lo:
                oa_filters.append(f"from_publication_date:{year_lo}-01-01")
            if year_hi:
                oa_filters.append(f"to_publication_date:{year_hi}-12-31")
            if venue:
                oa_filters.append(
                    f"primary_location.source.display_name.search:{venue}"
                )
            if oa_filters:
                # Pass through as a string for the OpenAlex scraper to consume.
                kwargs["oa_filter"] = ",".join(oa_filters)
        # Generic pass-through.
        if author and "author" not in kwargs:
            kwargs["author"] = author
        return kwargs

    @staticmethod
    def _dedupe(papers: List[Paper]) -> List[Paper]:
        """De-duplicate a list of papers by DOI (preferred) or normalised title."""
        seen_doi: Dict[str, int] = {}
        seen_title: Dict[str, int] = {}
        out: List[Paper] = []
        for p in papers:
            # DOI-based dedupe (highest priority — papers with the same
            # DOI are always considered duplicates regardless of title).
            if p.doi:
                doi_key = p.doi.lower().strip()
                if doi_key in seen_doi:
                    existing = out[seen_doi[doi_key]]
                    _merge_paper_fields(existing, p)
                    continue
                idx = len(out)
                seen_doi[doi_key] = idx
                out.append(p)
                # Also register the normalised title so that future
                # papers without a DOI but with the same title merge
                # into this entry.
                title_key = re.sub(r"[^a-z0-9 ]", "", (p.title or "").lower()).strip()
                if title_key and title_key not in seen_title:
                    seen_title[title_key] = idx
                continue
            # Title-based dedupe for papers without a DOI.
            normalised = re.sub(r"[^a-z0-9 ]", "", (p.title or "").lower()).strip()
            if normalised in seen_title:
                existing = out[seen_title[normalised]]
                if not existing.doi and p.doi:
                    existing.doi = p.doi
                _merge_paper_fields(existing, p)
                continue
            seen_title[normalised] = len(out)
            out.append(p)
        return out

    @staticmethod
    def _dataframe_to_papers(df: Any, source: str) -> List[Paper]:
        """Convert a pandas DataFrame to a list of :class:`Paper` records."""
        papers: List[Paper] = []
        for _, row in df.iterrows():
            authors_raw = row.get("authors", "")
            if isinstance(authors_raw, str):
                authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
            else:
                authors = list(authors_raw) if authors_raw is not None else []
            citations_val = row.get("citations_count", row.get("citations", None))
            citations_count: Optional[int] = None
            if citations_val is not None and citations_val == citations_val:  # NaN check
                try:
                    citations_count = int(citations_val)
                except (TypeError, ValueError):
                    citations_count = None
            year_val = row.get("year")
            year: Optional[int] = None
            if year_val is not None and year_val == year_val:
                try:
                    year = int(year_val)
                except (TypeError, ValueError):
                    year = None
            papers.append(
                Paper(
                    title=str(row.get("title", "") or ""),
                    authors=authors,
                    year=year,
                    abstract=str(row.get("abstract", "") or ""),
                    doi=row.get("doi") or None,
                    url=row.get("url") or None,
                    source=source,
                    citations_count=citations_count,
                    references=[],
                    keywords=[],
                    pdf_url=None,
                    issn=None,
                    isbn=None,
                    publisher=row.get("publisher") or None,
                    journal=row.get("journal") or row.get("venue") or None,
                    volume=None,
                    issue=None,
                    pages=None,
                    language=None,
                    paper_type=None,
                    fields_of_study=[],
                    raw={},
                )
            )
        return papers

    @staticmethod
    def _dict_to_paper(d: Dict[str, Any], source: str) -> Paper:
        """Coerce a plain dict into a :class:`Paper`."""
        # Accept legacy keys via alias map.
        citations_val = d.get("citations_count", d.get("citations"))
        return Paper(
            title=str(d.get("title", "") or ""),
            authors=list(d.get("authors", [])),
            year=d.get("year"),
            abstract=str(d.get("abstract", "") or ""),
            doi=d.get("doi"),
            url=d.get("url"),
            source=source,
            citations_count=int(citations_val) if citations_val is not None else None,
            references=list(d.get("references", [])),
            keywords=list(d.get("keywords", [])),
            pdf_url=d.get("pdf_url"),
            issn=d.get("issn"),
            isbn=d.get("isbn"),
            publisher=d.get("publisher"),
            journal=d.get("journal") or d.get("venue"),
            volume=d.get("volume"),
            issue=d.get("issue"),
            pages=d.get("pages"),
            language=d.get("language"),
            paper_type=d.get("paper_type") or d.get("type"),
            fields_of_study=list(d.get("fields_of_study", [])),
            raw=d.get("raw", {}) if isinstance(d.get("raw"), dict) else {},
        )

    def _publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """Publish a message on the EventBus if one is bound."""
        if self._event_bus is None:
            return
        try:
            if hasattr(self._event_bus, "publish"):
                self._event_bus.publish(topic, payload)
            elif hasattr(self._event_bus, "emit"):
                self._event_bus.emit(topic, payload)
            elif hasattr(self._event_bus, "post"):
                self._event_bus.post(topic, payload)
        except Exception:  # pragma: no cover - defensive
            self.logger.debug("EventBus publish failed for %s", topic, exc_info=True)

    # ---- Exporters -----------------------------------------------------
    def _paper_to_row(self, paper: Paper) -> Dict[str, Any]:
        return {
            "title": paper.title,
            "authors": "; ".join(paper.authors),
            "year": paper.year,
            "doi": paper.doi,
            "url": paper.url,
            "journal": paper.journal,
            "publisher": paper.publisher,
            "citations_count": paper.citations_count,
            "abstract": paper.abstract,
            "source": paper.source,
            "funders": "; ".join(
                f.get("name", "") for f in (paper.raw.get("funders", []) if paper.raw else [])
                if isinstance(f, dict) and f.get("name")
            ),
            "references_count": len(paper.references),
        }

    def _export_csv(self, result: ScraperResult) -> str:
        import csv
        import io
        out = io.StringIO()
        rows = [self._paper_to_row(p) for p in result.papers]
        if not rows:
            return ""
        writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return out.getvalue()

    def _export_json(self, result: ScraperResult) -> str:
        import dataclasses
        def _default(o: Any) -> Any:
            if dataclasses.is_dataclass(o):
                return dataclasses.asdict(o)
            return str(o)
        payload = {
            "source": result.source,
            "query": result.query,
            "total_results": result.total_results,
            "errors": result.errors,
            "papers": [self._paper_to_row(p) for p in result.papers],
            "metadata": result.raw_response if isinstance(result.raw_response, dict) else None,
        }
        return json.dumps(payload, indent=2, default=_default, ensure_ascii=False)

    def _export_bibtex(self, result: ScraperResult) -> str:
        lookup = DOILookup()
        entries: List[str] = []
        for p in result.papers:
            entries.append(lookup.to_bibtex(p))
        return "\n\n".join(entries)

    def _export_xlsx(self, result: ScraperResult) -> bytes:
        try:
            from openpyxl import Workbook  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openpyxl is required for XLSX export. "
                "Install via `pip install openpyxl`."
            ) from exc
        wb = Workbook()
        ws = wb.active
        ws.title = "Papers"
        rows = [self._paper_to_row(p) for p in result.papers]
        if not rows:
            ws.append(["(no results)"])
        else:
            headers = list(rows[0].keys())
            ws.append(headers)
            for r in rows:
                ws.append([r[h] for h in headers])
        import io
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _merge_paper_fields(target: Paper, source: Paper) -> None:
    """Merge non-empty fields from ``source`` into ``target`` (in place).

    Used by :meth:`ScrapingEngine._dedupe` to enrich an existing
    :class:`Paper` with information supplied by a duplicate from
    another source.
    """
    if source.citations_count is not None and (
        target.citations_count is None
        or (isinstance(source.citations_count, int)
            and isinstance(target.citations_count, int)
            and source.citations_count > target.citations_count)
    ):
        target.citations_count = source.citations_count
    if not target.authors and source.authors:
        target.authors = list(source.authors)
    if not target.abstract and source.abstract:
        target.abstract = source.abstract
    if not target.journal and source.journal:
        target.journal = source.journal
    if not target.publisher and source.publisher:
        target.publisher = source.publisher
    if not target.pdf_url and source.pdf_url:
        target.pdf_url = source.pdf_url
    if not target.issn and source.issn:
        target.issn = source.issn
    if not target.isbn and source.isbn:
        target.isbn = source.isbn
    if not target.volume and source.volume:
        target.volume = source.volume
    if not target.issue and source.issue:
        target.issue = source.issue
    if not target.pages and source.pages:
        target.pages = source.pages
    if not target.language and source.language:
        target.language = source.language
    if not target.paper_type and source.paper_type:
        target.paper_type = source.paper_type
    if not target.fields_of_study and source.fields_of_study:
        target.fields_of_study = list(source.fields_of_study)
    if not target.references and source.references:
        target.references = list(source.references)
    if not target.keywords and source.keywords:
        target.keywords = list(source.keywords)
    # Merge raw payloads.
    if source.raw:
        merged_raw = dict(target.raw) if target.raw else {}
        merged_raw.update(source.raw)
        target.raw = merged_raw


__all__ = ["ScrapingEngine"]
