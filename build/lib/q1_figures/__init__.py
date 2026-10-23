"""Q1 journal-grade figure factory for Academic Research Suite.

The ``q1_figures`` package produces publication-ready matplotlib figures
suitable for submission to top-tier (Q1) journals such as *Nature*,
*Science*, *Cell*, *NEJM*, *Lancet* and *JAMA*.

It provides:

* :mod:`q1_figures.palettes` — journal-grade colour palettes (Nature,
  Science, Cell, NEJM, Lancet, JAMA, scientific, color-blind safe,
  diverging and sequential).
* :mod:`q1_figures.typography` — publication typography (font family,
  font size, line width, etc.) with CJK fallback support.
* :mod:`q1_figures.figure_factory` — the main factory class
  :class:`Q1FigureFactory` for creating pre-styled figures and axes.
* :mod:`q1_figures.multi_panel` — :class:`MultiPanelFigure` and
  :class:`GridLayout` for composite multi-panel figures.
* :mod:`q1_figures.statistical_plots` — box / violin / raincloud /
  volcano / manhattan / QQ / Kaplan-Meier / ROC / PR / calibration /
  Bland-Altman plots.
* :mod:`q1_figures.network_plots` — network / bipartite / circular /
  arc / heatmap / sankey / chord / hive plots.
* :mod:`q1_figures.data_plots` — scatter / line / bar / stacked /
  grouped / heatmap / clustered / density / contour / ridgeline /
  parallel / polar plots.
* :mod:`q1_figures.bibliometric_plots` — Lotka / Bradford / Zipf /
  growth / citation / h-index / impact-factor / collaboration /
  topic-evolution / overlay / co-word plots.

Every module is independently importable (heavy deps imported lazily),
uses ``logging.getLogger(__name__)`` (never ``print``), and respects
the project-wide matplotlib conventions:

* ``constrained_layout=True`` ONLY (never ``tight_layout`` or
  ``bbox_inches='tight'``);
* Font fallback ``['Noto Sans SC', 'DejaVu Sans']``;
* ``axes.unicode_minus = False``.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

__version__ = "2.0.0"

__all__ = [
    "JournalPalettes",
    "Q1Typography",
    "Q1FigureFactory",
    "MultiPanelFigure",
    "GridLayout",
    "StatisticalPlots",
    "Q1NetworkPlots",
    "Q1DataPlots",
    "BibliometricPlots",
    "__version__",
]


# Lazily re-export the public API.  Each sub-module is imported on first
# access; if a heavy dependency is missing at runtime, only that name
# will raise — the rest of the package remains usable.
def __getattr__(name: str):  # PEP 562
    if name == "JournalPalettes":
        from .palettes import JournalPalettes
        return JournalPalettes
    if name == "Q1Typography":
        from .typography import Q1Typography
        return Q1Typography
    if name == "Q1FigureFactory":
        from .figure_factory import Q1FigureFactory
        return Q1FigureFactory
    if name == "MultiPanelFigure" or name == "GridLayout":
        from . import multi_panel
        return getattr(multi_panel, name)
    if name == "StatisticalPlots":
        from .statistical_plots import StatisticalPlots
        return StatisticalPlots
    if name == "Q1NetworkPlots":
        from .network_plots import Q1NetworkPlots
        return Q1NetworkPlots
    if name == "Q1DataPlots":
        from .data_plots import Q1DataPlots
        return Q1DataPlots
    if name == "BibliometricPlots":
        from .bibliometric_plots import BibliometricPlots
        return BibliometricPlots
    raise AttributeError(f"module 'q1_figures' has no attribute {name!r}")
