"""Meta-analysis sub-package for the Academic Research Suite.

Provides a complete toolkit for systematic-review meta-analysis:

* Effect-size computation for continuous, dichotomous, and time-to-event
  outcomes (Cohen's d, Hedges' g, Glass' Δ, MD, RR, OR, HR, RD, RRR, NNT).
* Pooling engines: inverse-variance fixed, Mantel-Haenszel (OR/RR), Peto,
  DerSimonian-Laird, REML, ML, Paule-Mandel, empirical-Bayes random effects.
* Network meta-analysis (Bucher consistency, design-by-treatment inconsistency,
  node-splitting, SUCRA ranking, league tables, network plots).
* Subgroup & sensitivity analyses (leave-one-out, cumulative, influence,
  Galbraith & radial plots, Q-between).
* Q1-publication-grade forest plots (Cochrane / JAMA / Lancet styles).
* Funnel plots + publication-bias tests (Egger, Begg, Peters, Harbord,
  trim-and-fill, Rosenthal & Orwin fail-safe N, contour-enhanced).
* PRISMA/Cochrane-style narrative report generator.

All submodules are independently importable; heavy dependencies
(``numpy``, ``scipy``, ``pandas``, ``matplotlib``, ``statsmodels``) are
lazy-imported inside the functions that need them so ``import meta_analysis``
never fails on a fresh environment.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

__all__ = [
    "EffectSizeType",
    "EffectSize",
    "ContinuousGroup",
    "EffectSizeCalculator",
    "PoolingMethod",
    "Heterogeneity",
    "MetaAnalysisResult",
    "PoolingEngine",
    "TreatmentComparison",
    "NMAResult",
    "InconsistencyTest",
    "NetworkMetaAnalysis",
    "SubgroupResult",
    "SubgroupAnalysis",
    "SensitivityAnalysis",
    "ForestPlot",
    "FunnelPlot",
    "ContourEnhancedFunnel",
    "MetaAnalysisReport",
]


def __getattr__(name: str):
    """Lazy attribute access (PEP 562).

    Importing the package itself never pulls in numpy / scipy / matplotlib
    / statsmodels — those are loaded only when a concrete class is accessed
    and the relevant submodule is imported on demand.
    """
    if name in {"EffectSizeType", "EffectSize", "ContinuousGroup", "EffectSizeCalculator"}:
        from . import effect_sizes as _es
        return getattr(_es, name)
    if name in {"PoolingMethod", "Heterogeneity", "MetaAnalysisResult", "PoolingEngine"}:
        from . import pooling as _p
        return getattr(_p, name)
    if name in {"TreatmentComparison", "NMAResult", "InconsistencyTest", "NetworkMetaAnalysis"}:
        from . import network_meta as _n
        return getattr(_n, name)
    if name in {"SubgroupResult", "SubgroupAnalysis", "SensitivityAnalysis"}:
        from . import subgroup as _s
        return getattr(_s, name)
    if name == "ForestPlot":
        from .forest_plot import ForestPlot as _cls
        return _cls
    if name in {"FunnelPlot", "ContourEnhancedFunnel"}:
        from . import funnel_plot as _f
        return getattr(_f, name)
    if name == "MetaAnalysisReport":
        from .report import MetaAnalysisReport as _cls
        return _cls
    raise AttributeError(f"module 'meta_analysis' has no attribute {name!r}")
