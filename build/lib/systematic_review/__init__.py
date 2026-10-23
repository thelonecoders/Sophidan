"""Systematic review module for the Academic Research Suite.

This sub-package implements the full PRISMA 2020 systematic-review
lifecycle — from protocol registration through title/abstract and
full-text screening, risk-of-bias assessment with the standard tools
(Cochrane RoB 2, ROBINS-I, QUADAS-2, Newcastle-Ottawa), structured
data extraction, evidence synthesis (narrative, meta-analytic,
qualitative comparative) and PRISMA flow-diagram / checklist
generation.

Every module is independently importable: heavy third-party
dependencies (matplotlib, pandas, numpy, scipy) are loaded lazily
inside the functions that need them, so ``import systematic_review``
succeeds even in a minimal environment.

Sub-modules
-----------
* :mod:`systematic_review.protocol`         — protocol templates & registration
* :mod:`systematic_review.screening`        — screening stages & manager
* :mod:`systematic_review.risk_of_bias`      — RoB assessment tools
* :mod:`systematic_review.data_extraction`   — structured extraction forms
* :mod:`systematic_review.synthesis`         — synthesis methods + SWiM
* :mod:`systematic_review.prisma_integration` — PRISMA flow & checklist
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

from typing import Any

__version__ = "2.0.0"
__all__: list[str] = [
    "protocol",
    "screening",
    "risk_of_bias",
    "data_extraction",
    "synthesis",
    "prisma_integration",
    "__version__",
]


def __getattr__(name: str) -> Any:
    """Lazily expose sub-module attributes on the package object.

    Implements PEP 562 so that ``from systematic_review import screening``
    only imports the ``screening`` sub-module when it is actually
    requested, keeping ``import systematic_review`` cheap.
    """
    if name in __all__:
        import importlib

        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
