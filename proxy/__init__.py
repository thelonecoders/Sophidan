"""Proxy suite for the Academic Research Suite.

This package provides a complete proxy management pipeline:

* :class:`proxy.proxy_manager.Proxy` / :class:`proxy.proxy_manager.ProxyManager`
  -- central in-memory + SQLite registry, thread-safe, Qt-signal aware.
* :class:`proxy.proxy_scraper.ProxyScraper` -- scrapes FREE public proxy lists
  from nine well-known sources.
* :class:`proxy.proxy_health_check.ProxyHealthChecker` -- batch + continuous
  health monitoring with geoip lookups.
* :class:`proxy.proxy_chain.ProxyChain` -- multi-hop SOCKS tunneling.
* :class:`proxy.proxy_rotation.ProxyRotator` -- per-request rotation with
  banlist / cooldown strategies.
* :class:`proxy.proxy_pool.ProxyPool` -- high-level facade that wires the
  above components together for one-line usage.

All modules are independently importable.  Heavy / optional third-party
dependencies (``requests``, ``bs4``, ``tenacity``, ``PySocks``) are imported
lazily inside the functions that need them so that ``import proxy.<mod>``
never raises even on a minimal install.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

__all__ = [
    "Proxy",
    "ProxyManager",
    "ProxyScraper",
    "ProxyHealthChecker",
    "ProxyCheckResult",
    "ProxyChain",
    "ProxyChainError",
    "ProxyRotator",
    "RotationStrategy",
    "ProxyPool",
]

# Lazy attribute access -- importing the sub-modules here would defeat the
# "independently importable" requirement if an optional dep is missing.
# Sub-modules are imported on first attribute access via __getattr__ (PEP 562).


def __getattr__(name: str):  # noqa: D401 - PEP 562 module-level __getattr__
    """Lazily import sub-module members to keep ``import proxy`` cheap."""
    if name in {"Proxy", "ProxyManager"}:
        from .proxy_manager import Proxy, ProxyManager  # noqa: WPS433
        return {"Proxy": Proxy, "ProxyManager": ProxyManager}[name]
    if name in {"ProxyScraper"}:
        from .proxy_scraper import ProxyScraper  # noqa: WPS433
        return ProxyScraper
    if name in {"ProxyHealthChecker", "ProxyCheckResult"}:
        from .proxy_health_check import ProxyHealthChecker, ProxyCheckResult  # noqa: WPS433
        return {"ProxyHealthChecker": ProxyHealthChecker, "ProxyCheckResult": ProxyCheckResult}[name]
    if name in {"ProxyChain", "ProxyChainError"}:
        from .proxy_chain import ProxyChain, ProxyChainError  # noqa: WPS433
        return {"ProxyChain": ProxyChain, "ProxyChainError": ProxyChainError}[name]
    if name in {"ProxyRotator", "RotationStrategy"}:
        from .proxy_rotation import ProxyRotator, RotationStrategy  # noqa: WPS433
        return {"ProxyRotator": ProxyRotator, "RotationStrategy": RotationStrategy}[name]
    if name in {"ProxyPool"}:
        from .proxy_pool import ProxyPool  # noqa: WPS433
        return ProxyPool
    raise AttributeError(f"module 'proxy' has no attribute {name!r}")
