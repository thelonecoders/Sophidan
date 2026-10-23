"""REST endpoints for the ``/api/proxy`` resource.

Provides listing, refresh, single-proxy testing, chain building, and
pool statistics for the proxy subsystem.

ProxyPool facade contract (contract #4) — every handler calls the real
facade method (no ``hasattr`` guards faking success):

* ``list_proxies() -> list[dict]``
* ``refresh(sources=None, target_count=None, progress_cb=None)``
* ``test_proxy(addr) -> dict``
* ``build_chain(ids) -> dict``
* ``stats()``

A missing pool yields a real 503; ``test_url`` is validated against
SSRF (http/https only, no private / loopback / link-local targets —
the proxy address itself may of course be a LAN host).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import ipaddress
import logging
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from web.routes._common import (
    accepted_kwargs,
    as_int,
    bad_request,
    error_response,
    json_safe,
    service_unavailable,
)

logger = logging.getLogger(__name__)

proxy_bp = Blueprint("proxy", __name__, url_prefix="/api/proxy")

# Hostname suffixes / names that must never be used as a test target.
_BLOCKED_TEST_HOSTS = {
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata.google.internal",
}
_BLOCKED_TEST_SUFFIXES = (".local", ".internal", ".localhost")


def _state() -> "Any":
    """Return the shared :class:`ServerState` singleton."""
    from web.server import ServerState

    return ServerState()


def _serialize_proxy(p: Any) -> dict[str, Any]:
    """Best-effort serializer for a proxy object / dict."""
    if isinstance(p, dict):
        data = dict(p)
    else:
        to_dict = getattr(p, "to_dict", None)
        if callable(to_dict):
            data = to_dict()
        elif hasattr(p, "__dict__"):
            data = {k: v for k, v in vars(p).items() if not k.startswith("_")}
        else:
            data = {"value": str(p)}
    data.pop("_sa_instance_state", None)
    return json_safe(data)


def validate_test_url(url: str) -> str:
    """Validate ``test_url`` against SSRF and return the cleaned URL.

    Rules:
      * scheme must be ``http`` or ``https``;
      * hostname must be present and not obviously internal
        (``localhost``, ``*.local``, ``*.internal``, ...);
      * literal-IP hosts must not be private / loopback / link-local /
        reserved / multicast.

    The *proxy address* may legitimately be a LAN host — only the URL
    the proxy will fetch is restricted.
    """
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("test_url must use http or https")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("test_url must include a hostname")
    if host in _BLOCKED_TEST_HOSTS or \
            any(host.endswith(sfx) for sfx in _BLOCKED_TEST_SUFFIXES):
        raise ValueError("test_url must not target internal hosts")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return url  # DNS name — public resolution assumed
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        raise ValueError(
            "test_url must not target private or reserved addresses")
    return url


@proxy_bp.route("/", methods=["GET"])
def list_proxies():
    """List proxies with optional filters.

    Query params:
        country:  ISO country code filter.
        protocol: ``http``, ``https``, ``socks4``, ``socks5``.
        healthy:  ``1`` to return only healthy proxies.
        page:     1-indexed page number (facade returns the full list;
                  pagination is applied here).
        per_page: Page size (max 100).
    """
    try:
        page = as_int(request.args.get("page"), 1, name="page", minimum=1)
        per_page = as_int(request.args.get("per_page"), 20, name="per_page",
                          minimum=1, maximum=100)
    except ValueError as exc:
        return bad_request(str(exc))
    country = request.args.get("country")
    protocol = request.args.get("protocol")
    healthy = request.args.get("healthy", type=int)

    pool = _state().proxy_pool
    if pool is None:
        return service_unavailable("ProxyPool")

    try:
        # Contract: list_proxies() -> list[dict]
        proxies = pool.list_proxies() or []
    except AttributeError as exc:
        # Facade method not available on this pool build → 503.
        logger.warning("ProxyPool.list_proxies unavailable: %s", exc)
        return service_unavailable("ProxyPool.list_proxies")
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "list_proxies", exc)

    records = [_serialize_proxy(p) for p in proxies]
    if country:
        records = [r for r in records
                   if str(r.get("country", "")).lower() == country.lower()]
    if protocol:
        records = [r for r in records
                   if str(r.get("protocol", "")).lower() == protocol.lower()]
    if healthy:
        records = [r for r in records if r.get("is_healthy", r.get("healthy"))]

    total = len(records)
    start = (page - 1) * per_page
    return jsonify({
        "proxies": records[start:start + per_page],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page if per_page else 0,
    })


@proxy_bp.route("/refresh", methods=["POST"])
def refresh():
    """Scrape fresh proxies and health-check the pool.

    Body (optional): ``{"sources": [str]?, "target_count": int?}``.
    """
    pool = _state().proxy_pool
    if pool is None:
        return service_unavailable("ProxyPool")

    payload = request.get_json(silent=True) or {}
    sources = payload.get("sources")
    if sources is not None and (
            not isinstance(sources, list)
            or not all(isinstance(s, str) for s in sources)):
        return bad_request("sources must be a list of strings")
    target_count = None
    if payload.get("target_count") is not None:
        try:
            target_count = as_int(payload.get("target_count"),
                                  name="target_count", minimum=1)
        except ValueError as exc:
            return bad_request(str(exc))

    wanted = {"sources": sources, "target_count": target_count}
    try:
        # Contract: refresh(sources=None, target_count=None, progress_cb=None)
        result = pool.refresh(**accepted_kwargs(pool.refresh, wanted))
    except AttributeError as exc:
        logger.warning("ProxyPool.refresh unavailable: %s", exc)
        return service_unavailable("ProxyPool.refresh")
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "refresh", exc, status=503,
                              error="pool_unavailable")

    if isinstance(result, dict):
        body = dict(result)
    elif isinstance(result, (tuple, list)) and len(result) == 2:
        body = {"added": result[0], "healthy": result[1]}
    elif isinstance(result, int):
        body = {"added": result}
    else:
        body = {"result": json_safe(result)}
    body.setdefault("sources", sources)
    return jsonify(json_safe(body))


@proxy_bp.route("/test", methods=["POST"])
def test_proxy():
    """Test a single proxy by address (or host + port).

    Body: ``{"address": "host:port"}`` or ``{"host": str, "port": int,
    "protocol": str?}``; optional ``test_url`` (validated against SSRF).
    Returns latency and status for the proxy.
    """
    payload = request.get_json(silent=True) or {}
    address = payload.get("address")
    host = payload.get("host")
    port = payload.get("port")
    if not address:
        if not host or port is None:
            return bad_request("address (host:port) or host + port required")
        try:
            port = as_int(port, name="port", minimum=1, maximum=65535)
        except ValueError as exc:
            return bad_request(str(exc))
        protocol = (payload.get("protocol") or "http").strip().lower()
        address = f"{protocol}://{host}:{port}" \
            if "://" not in str(host) else f"{host}:{port}"

    test_url = payload.get("test_url", "https://httpbin.org/ip")
    try:
        test_url = validate_test_url(test_url)
    except ValueError as exc:
        return bad_request(str(exc))

    pool = _state().proxy_pool
    if pool is None:
        return service_unavailable("ProxyPool")

    try:
        # Contract: test_proxy(addr) -> dict; ``test_url`` is only
        # forwarded when the facade declares the parameter.
        supported = accepted_kwargs(
            pool.test_proxy, {"addr": address, "test_url": test_url})
        if supported:
            result = pool.test_proxy(**supported)
        else:
            result = pool.test_proxy(address)
    except AttributeError as exc:
        logger.warning("ProxyPool.test_proxy unavailable: %s", exc)
        return service_unavailable("ProxyPool.test_proxy")
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "test_proxy", exc, status=503,
                              error="pool_unavailable")

    return jsonify(json_safe(result))


@proxy_bp.route("/chain", methods=["POST"])
def build_chain():
    """Build a proxy chain from a list of proxy ids/addresses.

    Body: ``{"proxy_ids": [...]}``. Returns the chain descriptor.
    """
    pool = _state().proxy_pool
    payload = request.get_json(silent=True) or {}
    proxy_ids = payload.get("proxy_ids") or []
    if not isinstance(proxy_ids, list) or not proxy_ids:
        return bad_request("proxy_ids (non-empty list) is required")

    if pool is None:
        return service_unavailable("ProxyPool")

    try:
        # Contract: build_chain(ids) -> dict
        chain = pool.build_chain(proxy_ids)
    except ValueError as exc:
        logger.warning("build_chain rejected: %s", exc)
        return bad_request("invalid proxy_ids")
    except AttributeError as exc:
        logger.warning("ProxyPool.build_chain unavailable: %s", exc)
        return service_unavailable("ProxyPool.build_chain")
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "build_chain", exc, status=503,
                              error="pool_unavailable")

    return jsonify(json_safe(chain))


@proxy_bp.route("/stats", methods=["GET"])
def stats():
    """Return pool statistics (counts by country, protocol, health)."""
    pool = _state().proxy_pool
    if pool is None:
        return service_unavailable("ProxyPool")

    try:
        data = pool.stats()
    except Exception as exc:  # pragma: no cover - defensive
        return error_response(logger, "stats", exc, status=503,
                              error="pool_unavailable")

    return jsonify(json_safe(data))
