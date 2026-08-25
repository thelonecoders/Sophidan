"""Extended bibliometric analyses for the Academic Research Suite.

The ``bibliometrics`` package provides Publish-or-Perish-grade
author-level indices (:mod:`bibliometrics.pop_indices`), VOSviewer /
JCR-style journal-level metrics (:mod:`bibliometrics.journal_metrics`),
VOSviewer-style network analyses (:mod:`bibliometrics.vosviewer`),
CiteSpace-style burst detection and knowledge-domain maps
(:mod:`bibliometrics.citespace`), and Sci2 / Leydesdorff-style
scientogram building (:mod:`bibliometrics.scientogram`).

Every module is independently importable — the package's
``__init__`` does not eagerly import submodules, so consumers can
introspect ``bibliometrics`` without paying the cost of (e.g.)
matplotlib / scikit-learn. Use :func:`quick_stats` for a one-call
summary of an author's h-index / g-index / e-index / i10-index from a
plain list of citation counts.

Example:
    >>> from bibliometrics import quick_stats
    >>> quick_stats([10, 5, 3, 1, 0, 0, 1, 2, 0, 4])
    {'h_index': 3, 'g_index': 4, 'i10_index': 1, 'e_index': 3.162..., ...}
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence

logger = logging.getLogger(__name__)

__version__ = "2.0.0"

__all__ = [
    # Submodules — imported lazily on access via __getattr__.
    "pop_indices",
    "journal_metrics",
    "vosviewer",
    "citespace",
    "scientogram",
    # Re-exported entry points (lazy).
    "PoPIndices",
    "AuthorProfile",
    "JournalMetrics",
    "JournalProfile",
    "VOSAnalyzer",
    "CiteSpaceAnalyzer",
    "Burst",
    "ResearchFront",
    "ScientogramBuilder",
    # Smoke-test helper.
    "quick_stats",
]


# ---------------------------------------------------------------------------
# Lazy submodule + symbol re-exports (so ``import bibliometrics`` is cheap)
# ---------------------------------------------------------------------------

# Map of attribute-name → (module path, attribute name in that module).
_LAZY_IMPORTS: Dict[str, tuple] = {
    "PoPIndices":       ("bibliometrics.pop_indices", "PoPIndices"),
    "AuthorProfile":    ("bibliometrics.pop_indices", "AuthorProfile"),
    "JournalMetrics":   ("bibliometrics.journal_metrics", "JournalMetrics"),
    "JournalProfile":   ("bibliometrics.journal_metrics", "JournalProfile"),
    "VOSAnalyzer":      ("bibliometrics.vosviewer", "VOSAnalyzer"),
    "CiteSpaceAnalyzer":("bibliometrics.citespace", "CiteSpaceAnalyzer"),
    "Burst":            ("bibliometrics.citespace", "Burst"),
    "ResearchFront":    ("bibliometrics.citespace", "ResearchFront"),
    "ScientogramBuilder":("bibliometrics.scientogram", "ScientogramBuilder"),
}

# Submodule names handled directly by importlib.
_SUBMODULES = frozenset({
    "pop_indices",
    "journal_metrics",
    "vosviewer",
    "citespace",
    "scientogram",
})


def __getattr__(name: str) -> Any:
    """Lazy-import submodules and re-exported symbols on first access.

    Raises:
        AttributeError: If ``name`` is not part of ``__all__``.
    """
    import importlib
    if name in _SUBMODULES:
        return importlib.import_module(f"bibliometrics.{name}")
    if name in _LAZY_IMPORTS:
        mod_path, attr_name = _LAZY_IMPORTS[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr_name)
    raise AttributeError(
        f"module 'bibliometrics' has no attribute {name!r}"
    )


def __dir__() -> list:
    """Return the list of public attributes (for ``dir(bibliometrics)``)."""
    return sorted(set(__all__) | set(globals().keys()))


# ---------------------------------------------------------------------------
# Smoke-test helper
# ---------------------------------------------------------------------------

def quick_stats(
    citations: Sequence[int],
    years: Optional[Sequence[int]] = None,
    author_counts: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """One-call summary of author-level bibliometric indices.

    Thin wrapper around
    :meth:`bibliometrics.pop_indices.PoPIndices.compute_all` — kept at
    package level so callers can sanity-check the installation with a
    single ``from bibliometrics import quick_stats`` import.

    Args:
        citations: Sequence of per-paper citation counts.
        years: Optional sequence of publication years.
        author_counts: Optional per-paper author counts.

    Returns:
        Dict with one key per indicator (``h_index``, ``g_index``,
        ``i10_index``, ``e_index``, ``h_core``, ``h_max_index``,
        ``w_index``, ``q2_index``, plus contemporary / age-weighted /
        AR indices when ``years`` is provided and the
        ``multi_authored_h_index`` when ``author_counts`` is provided).

    Example:
        >>> from bibliometrics import quick_stats
        >>> stats = quick_stats([10, 5, 3, 1, 0, 0, 1, 2, 0, 4])
        >>> stats["h_index"], stats["g_index"], stats["i10_index"]
        (3, 4, 1)
    """
    from bibliometrics.pop_indices import PoPIndices
    return PoPIndices().compute_all(
        citations, years=years, author_counts=author_counts,
    )
