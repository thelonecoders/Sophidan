"""data_acquisition — multi-source academic data acquisition layer.

Convenience re-exports of the shared building blocks so callers can use
``from data_acquisition import Paper, ScrapingEngine`` as well as the
canonical submodule paths.  Every export is best-effort: a missing
optional dependency never breaks ``import data_acquisition``.
"""

from __future__ import annotations

__all__ = []

try:  # pragma: no cover - always available in the bundled build
    from .base_scraper import BaseScraper, Paper, ScraperResult

    __all__ += ["BaseScraper", "Paper", "ScraperResult"]
except Exception:  # noqa: BLE001 - defensive
    pass

try:  # pragma: no cover - depends on optional sibling modules
    from .scraping_engine import ScrapingEngine

    __all__ += ["ScrapingEngine"]
except Exception:  # noqa: BLE001 - defensive
    pass
