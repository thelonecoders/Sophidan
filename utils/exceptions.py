"""Exception hierarchy for Academic Research Suite.

All exceptions raised by application code derive from :class:`ARSError`, which
exposes a :meth:`ARSError.to_dict` method so the UI can render structured
error information. Every exception also carries an optional ``cause`` field
that mirrors :pep:`678`-style exception metadata without requiring Python 3.11+.

This module is independently importable and has no third-party dependencies.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ARSError(Exception):
    """Base class for every exception raised by the suite.

    Attributes:
        message: Human-readable error description.
        cause: Optional underlying exception that triggered this one.
        details: Arbitrary structured context for the UI (free-form dict).
    """

    def __init__(
        self,
        message: str = "",
        *,
        cause: Optional[BaseException] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Human-readable error description.
            cause: The exception that caused this one, if any.
            details: Free-form structured context (e.g. URL, status code).
        """
        super().__init__(message)
        self.message: str = message
        self.cause: Optional[BaseException] = cause
        self.details: Dict[str, Any] = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation for UI display.

        Returns:
            Dict with ``type``, ``message``, ``cause`` (string repr) and
            ``details`` keys.
        """
        return {
            "type": self.__class__.__name__,
            "message": self.message,
            "cause": repr(self.cause) if self.cause else None,
            "details": self.details,
        }

    def __str__(self) -> str:  # pragma: no cover - trivial
        base = self.message or self.__class__.__name__
        if self.cause:
            return f"{base} (caused by: {self.cause!r})"
        return base


# ---------------------------------------------------------------------------
# Concrete subclasses — grouped by subsystem
# ---------------------------------------------------------------------------
class ScraperError(ARSError):
    """Raised when a scraper fails to retrieve or parse data."""


class ProxyError(ARSError):
    """Raised for general proxy-related failures."""


class ProxyChainError(ProxyError):
    """Raised when a proxy chain cannot be constructed or used."""


class ProxyRotationError(ProxyError):
    """Raised when no healthy proxy is available for rotation."""


class DatabaseError(ARSError):
    """Raised on database connection, query or migration failures."""


class AIError(ARSError):
    """Raised when an AI/LLM provider call fails."""


class ExportError(ARSError):
    """Raised when an export/report generation step fails."""


class ConfigError(ARSError):
    """Raised on configuration load/save/validation failures."""


class AnalysisError(ARSError):
    """Raised when a data-science / analysis step fails."""


__all__ = [
    "ARSError",
    "ScraperError",
    "ProxyError",
    "ProxyChainError",
    "ProxyRotationError",
    "DatabaseError",
    "AIError",
    "ExportError",
    "ConfigError",
    "AnalysisError",
]
