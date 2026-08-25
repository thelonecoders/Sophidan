"""REST endpoints for the ``/api/proxy`` resource.

Provides listing, refresh, single-proxy testing, chain building, and
pool statistics for the proxy subsystem.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

proxy_bp = Blueprint("proxy", __name__, url_prefix="/api/proxy")


def _state() -> "Any":
    """Return the shared :class:`ServerState` singleton."""
    from web.server import ServerState

    return ServerState()


def _service_unavailable(name: str):
    """Helper: build a 503 JSON response for a missing backend service."""
    return jsonify({
        "error": "service_unavailable",
        "message": f"{name} is not initialised; backend module not yet wired up.",
    }), 503


def _serialize_proxy(p: Any) -> dict[str, Any]:
    """Best-effort serializer for a proxy object."""
    if isinstance(p, dict):
        data = dict(p)
    elif hasattr(p, "to_dict") and callable(p.to_dict):
        data = p.to_dict()
    elif hasattr(p, "__dict__"):
        data = {k: v for k, v in vars(p).items() if not k.startswith("_")}
    else:
        data = {"value": str(p)}
    data.pop("_sa_instance_state", None)
    return data


@proxy_bp.route("/", methods=["GET"])
def list_proxies():
    """List proxies with optional filters.

    Query params:
        country:  ISO country code filter.
        protocol: ``http``, ``https``, ``socks4``, ``socks5``.
        healthy:  ``1`` to return only healthy proxies.
        page:     1-indexed page number.
        per_page: Page size (max 100).
    """
    state = _state()
    pool = state.proxy_pool
    if pool is None:
        return _service_unavailable("ProxyPool")

    filters = {
        "country": request.args.get("country"),
        "protocol": request.args.get("protocol"),
        "healthy": request.args.get("healthy", type=int),
    }
    page = max(request.args.get("page", default=1, type=int), 1)
    per_page = min(max(request.args.get("per_page", default=20, type=int), 1), 100)

    try:
        if hasattr(pool, "list_proxies"):
            proxies, total = pool.list_proxies(
                page=page, per_page=per_page, **filters,
            )
        else:
            proxies, total = [], 0
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("list_proxies failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify({
        "proxies": [_serialize_proxy(p) for p in proxies],
        "page": page, "per_page": per_page, "total": total,
    })


@proxy_bp.route("/refresh", methods=["POST"])
def refresh():
    """Scrape fresh proxies and health-check the entire pool.

    Body (optional): ``{"sources": [str]?}`` to restrict scraper sources.
    """
    state = _state()
    pool = state.proxy_pool
    if pool is None:
        return _service_unavailable("ProxyPool")

    payload = request.get_json(silent=True) or {}
    sources = payload.get("sources")

    try:
        if hasattr(pool, "refresh"):
            added, healthy = pool.refresh(sources=sources)
        else:
            added, healthy = 0, 0
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("refresh failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify({"added": added, "healthy": healthy,
                    "sources": sources})


@proxy_bp.route("/test", methods=["POST"])
def test_proxy():
    """Test a single proxy by host/port.

    Body: ``{"host": str, "port": int, "protocol": str?,
    "test_url": str?}``. Returns latency and status.
    """
    state = _state()
    pool = state.proxy_pool
    payload = request.get_json(silent=True) or {}
    host = payload.get("host")
    port = payload.get("port")
    if not host or not isinstance(port, int):
        return jsonify({"error": "bad_request",
                        "message": "host (str) and port (int) are required"}), 400

    protocol = payload.get("protocol", "http")
    test_url = payload.get("test_url", "https://httpbin.org/ip")

    if pool is None:
        return _service_unavailable("ProxyPool")

    try:
        if hasattr(pool, "test_proxy"):
            result = pool.test_proxy(host=host, port=port,
                                     protocol=protocol, test_url=test_url)
        else:
            result = {"host": host, "port": port, "status": "unknown",
                      "latency_ms": None}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("test_proxy failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify(result)


@proxy_bp.route("/chain", methods=["POST"])
def build_chain():
    """Build a proxy chain from a list of proxy ids.

    Body: ``{"proxy_ids": [int]}``. Returns the chain descriptor.
    """
    state = _state()
    pool = state.proxy_pool
    payload = request.get_json(silent=True) or {}
    proxy_ids = payload.get("proxy_ids") or []
    if not isinstance(proxy_ids, list) or not proxy_ids:
        return jsonify({"error": "bad_request",
                        "message": "proxy_ids (non-empty list) is required"}), 400

    if pool is None:
        return _service_unavailable("ProxyPool")

    try:
        if hasattr(pool, "build_chain"):
            chain = pool.build_chain(proxy_ids)
        else:
            chain = {"proxy_ids": proxy_ids, "length": len(proxy_ids)}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("build_chain failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify(chain)


@proxy_bp.route("/stats", methods=["GET"])
def stats():
    """Return pool statistics (counts by country, protocol, health)."""
    state = _state()
    pool = state.proxy_pool
    if pool is None:
        return _service_unavailable("ProxyPool")

    try:
        if hasattr(pool, "stats"):
            data = pool.stats()
        else:
            data = {"total": 0, "healthy": 0, "by_country": {},
                    "by_protocol": {}, "avg_latency_ms": None}
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("stats failed: %s", exc)
        return jsonify({"error": "internal_error", "message": str(exc)}), 500

    return jsonify(data)
