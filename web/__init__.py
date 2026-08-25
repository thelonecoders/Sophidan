"""Local Flask web server package for the Academic Research Suite.

Provides an optional HTTP/WebSocket API that mirrors the desktop UI's
capabilities. Activated via ``python main.py --web``.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

__all__: list[str] = ["create_app", "run_server", "ServerState"]


def __getattr__(name: str):  # PEP 562 lazy attribute access
    if name in {"create_app", "run_server", "ServerState"}:
        from .server import create_app, run_server, ServerState  # noqa: F401

        return {"create_app": create_app, "run_server": run_server,
                "ServerState": ServerState}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
