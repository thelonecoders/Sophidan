"""HTTP route blueprints for the Academic Research Suite web API.

Each blueprint covers a domain area (papers, projects, scraping, etc.).
All heavy backend modules are imported lazily inside request handlers so
that the package itself remains importable even when downstream modules
have not yet been installed/wired up.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _safe_import(module: str, attr: str):
    """Import a blueprint, returning a placeholder on failure.

    Backend dependencies (database, scraping engine, ...) may not yet be
    wired up during early development. We avoid hard failures at import
    time so the Flask app can still boot and serve ``/api/health``.

    Args:
        module: Dotted module path, e.g. ``"web.routes.papers"``.
        attr:   Attribute name to pull from the module, e.g. ``"papers_bp"``.

    Returns:
        The blueprint object, or ``None`` if the import failed.
    """
    import importlib

    try:
        mod = importlib.import_module(module)
        return getattr(mod, attr)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not import %s.%s: %s", module, attr, exc)
        return None


papers_bp = _safe_import("web.routes.papers", "papers_bp")
projects_bp = _safe_import("web.routes.projects", "projects_bp")
scraping_bp = _safe_import("web.routes.scraping", "scraping_bp")
analytics_bp = _safe_import("web.routes.analytics", "analytics_bp")
ai_bp = _safe_import("web.routes.ai", "ai_bp")
proxy_bp = _safe_import("web.routes.proxy", "proxy_bp")
export_bp = _safe_import("web.routes.export", "export_bp")
ws_bp = _safe_import("web.routes.websocket", "ws_bp")

# v2.0.0 — added by v2-ui-web
bibliometrics_bp = _safe_import("web.routes.bibliometrics", "bibliometrics_bp")
network_bp = _safe_import("web.routes.network_analysis", "network_bp")
sr_bp = _safe_import("web.routes.sr", "sr_bp")
ma_bp = _safe_import("web.routes.ma", "ma_bp")
figures_bp = _safe_import("web.routes.q1_figures", "figures_bp")
innovation_bp = _safe_import("web.routes.innovation", "innovation_bp")
lifecycle_bp = _safe_import("web.routes.research_lifecycle", "lifecycle_bp")

# Real blueprints that successfully loaded — used by ``create_app``.
ALL_BLUEPRINTS = [
    bp for bp in (
        papers_bp, projects_bp, scraping_bp, analytics_bp,
        ai_bp, proxy_bp, export_bp, ws_bp,
        # v2.0.0 — added by v2-ui-web
        bibliometrics_bp, network_bp, sr_bp, ma_bp,
        figures_bp, innovation_bp, lifecycle_bp,
    ) if bp is not None
]

__all__ = [
    "papers_bp",
    "projects_bp",
    "scraping_bp",
    "analytics_bp",
    "ai_bp",
    "proxy_bp",
    "export_bp",
    "ws_bp",
    # v2.0.0 — added by v2-ui-web
    "bibliometrics_bp",
    "network_bp",
    "sr_bp",
    "ma_bp",
    "figures_bp",
    "innovation_bp",
    "lifecycle_bp",
    "ALL_BLUEPRINTS",
]
