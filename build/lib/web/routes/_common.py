"""Shared helpers for the web route blueprints.

This module intentionally has no hard framework dependencies beyond
Flask (imported lazily inside the helpers that need it) so that every
route module can share validation / serialisation logic without
introducing import cycles.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import datetime as _dt
import logging
import math
from decimal import Decimal
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

# Upper bound on how many papers a single request will pull from the
# database in one call (the DatabaseConnection contract exposes
# ``list_papers(limit=..., offset=...)`` but no COUNT, so pagination is
# computed client-side over one bounded scan).
MAX_PAPER_SCAN = 10_000


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def service_unavailable(name: str):
    """503 JSON response for a missing backend service."""
    from flask import jsonify

    return jsonify({
        "error": "service_unavailable",
        "message": f"{name} is not initialised; backend module not yet wired up.",
    }), 503


def bad_request(message: str):
    """400 JSON response with a client-safe message."""
    from flask import jsonify

    return jsonify({"error": "bad_request", "message": message}), 400


def not_found(message: str):
    """404 JSON response."""
    from flask import jsonify

    return jsonify({"error": "not_found", "message": message}), 404


def error_response(logger_: logging.Logger, context: str, exc: BaseException,
                   status: int = 500, error: str = "internal_error"):
    """Log ``exc`` server-side and return a generic JSON error (no leak).

    Exception detail is never echoed to the client; only the request
    path context is logged so operators can correlate via server logs.
    """
    from flask import jsonify

    logger_.exception("%s failed: %s", context, exc)
    return jsonify({
        "error": error,
        "message": "the request could not be completed; see server logs for details",
    }), status


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def as_int(value: Any, default: Any = None, *, name: str = "value",
           minimum: int | None = None, maximum: int | None = None) -> int:
    """Coerce ``value`` to ``int`` or raise :class:`ValueError`.

    Route handlers catch :class:`ValueError` and map it to a 400
    response (``bad_request``) so that bad integer casts never surface
    as 500s.

    Args:
        value: Raw value (JSON scalar or query-string fragment).
        default: Returned when ``value`` is ``None``. If ``default`` is
            also ``None`` a missing value raises.
        name: Field name used in client-safe error messages.
        minimum / maximum: Optional inclusive bounds.
    """
    if value is None:
        if default is None:
            raise ValueError(f"{name} is required")
        return int(default)
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer") from None
    if isinstance(value, float) and not float(value).is_integer():
        raise ValueError(f"{name} must be an integer")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return result


def as_int_arg(args: Mapping[str, Any], key: str, default: int | None = None,
               *, minimum: int | None = None, maximum: int | None = None) -> int:
    """Read an integer query parameter, raising ``ValueError`` on garbage."""
    raw = args.get(key)
    if raw is None or raw == "":
        if default is None:
            raise ValueError(f"{key} is required")
        return int(default)
    return as_int(raw, name=key, minimum=minimum, maximum=maximum)


def accepted_kwargs(func: Callable[..., Any], kwargs: Mapping[str, Any]) -> dict:
    """Filter ``kwargs`` down to the named parameters ``func`` declares.

    Signature-aware injection (contract #1): extra keyword arguments are
    only forwarded when the callee explicitly declares them, so calls
    keep working against both the pre-contract and post-contract engine
    signatures without leaking unexpected kwargs into ``**filters``.
    """
    import inspect

    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):  # pragma: no cover - builtins etc.
        return {}
    params = sig.parameters
    out: dict = {}
    for key, value in kwargs.items():
        param = params.get(key)
        if param is not None and param.kind in (
            param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY,
        ):
            out[key] = value
    return out


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #
def json_safe(obj: Any) -> Any:
    """Recursively convert ``obj`` into JSON-serialisable primitives.

    Handles ``datetime``/``date``/``time`` (ISO-8601 strings),
    ``Decimal``, ``bytes``, sets/tuples, mappings with non-string keys,
    and objects exposing ``to_dict()`` — so Paper-like records and
    analysis results can cross the JSON boundary untouched.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    if isinstance(obj, _dt.timedelta):
        return obj.total_seconds()
    if isinstance(obj, (bytes, bytearray)):
        try:
            return bytes(obj).decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            return bytes(obj).hex()
    if isinstance(obj, Mapping):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (set, frozenset, tuple, list)):
        return [json_safe(v) for v in obj]
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return json_safe(to_dict())
    if hasattr(obj, "__dict__"):
        return json_safe({
            k: v for k, v in vars(obj).items() if not k.startswith("_")
        })
    return str(obj)


def serialize_paper(paper: Any) -> dict[str, Any]:
    """Best-effort conversion of a paper-like object to a JSON dict.

    Accepts plain dicts (the canonical ``DatabaseConnection`` contract
    returns dicts), objects exposing ``to_dict()`` (e.g.
    ``data_acquisition.base_scraper.Paper``), or generic objects.
    """
    if isinstance(paper, dict):
        data = dict(paper)
    else:
        to_dict = getattr(paper, "to_dict", None)
        if callable(to_dict):
            data = dict(to_dict())
        elif hasattr(paper, "__dict__"):
            data = {k: v for k, v in vars(paper).items() if not k.startswith("_")}
        else:
            data = {"value": str(paper)}
    data.pop("_sa_instance_state", None)
    return data


def serialize_papers(papers: Any) -> list[dict[str, Any]]:
    """Serialise an iterable of paper-like objects."""
    return [json_safe(serialize_paper(p)) for p in (papers or [])]


def normalize_papers_payload(papers: Any) -> list[dict[str, Any]]:
    """Coerce a JSON ``papers`` payload into a list of plain dicts."""
    out: list[dict[str, Any]] = []
    for p in (papers or []):
        if isinstance(p, dict):
            out.append(p)
        elif hasattr(p, "to_dict"):
            out.append(p.to_dict())
        elif hasattr(p, "__dict__"):
            out.append({k: v for k, v in vars(p).items() if not k.startswith("_")})
    return out


def temp_file_path(suffix: str) -> str:
    """Create a secure temp file and return its path (caller deletes).

    Replacement for the unsafe ``tempfile.mktemp`` pattern: the name is
    created atomically by the OS, closing the TOCTOU race.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        return tmp.name


def safe_remove(path: str) -> None:
    """Best-effort ``os.remove`` that never raises."""
    import os

    try:
        os.remove(path)
    except OSError:  # pragma: no cover - defensive
        pass


__all__ = [
    "MAX_PAPER_SCAN",
    "service_unavailable",
    "bad_request",
    "not_found",
    "error_response",
    "as_int",
    "as_int_arg",
    "accepted_kwargs",
    "json_safe",
    "serialize_paper",
    "serialize_papers",
    "normalize_papers_payload",
    "temp_file_path",
    "safe_remove",
]
