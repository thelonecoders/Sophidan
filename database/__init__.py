"""Database package for Academic Research Suite.

Re-exports the :class:`DatabaseConnection` singleton manager and the
:class:`FullTextSearch` facade (both degrade gracefully — the module stays
importable even when SQLAlchemy is not installed, exposing ``None`` for the
unavailable symbols).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

__all__ = ["DatabaseConnection", "FullTextSearch"]

try:  # pragma: no cover - depends on environment
    from database.connection import DatabaseConnection
except Exception as exc:  # pragma: no cover - SQLAlchemy missing
    DatabaseConnection = None  # type: ignore[assignment, misc]

try:  # pragma: no cover - depends on environment
    from database.search import FullTextSearch
except Exception as exc:  # pragma: no cover - SQLAlchemy missing
    FullTextSearch = None  # type: ignore[assignment, misc]
