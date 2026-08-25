"""Gephi-style interactive network visualization for the Academic Research Suite.

The :mod:`gephi_viz` package re-implements a Gephi-grade visualization pipeline
on top of :mod:`networkx` + :mod:`matplotlib` + :mod:`qtpy`:

* :mod:`gephi_viz.layouts`        — pure-Python layout algorithms
  (ForceAtlas2, OpenOrd, Yifan Hu, Fruchterman–Reingold, Kamada–Kawai,
  circular, grid, radial, hierarchical, geographic, plus a pipeline).
* :mod:`gephi_viz.filters`        — Gephi's filter system (range / topology /
  partition / edge / dynamic filters + :class:`FilterChain`).
* :mod:`gephi_viz.statistics`     — the "Statistics" panel: centrality,
  modularity, diameter, HITS, PageRank, etc., wrapped in a
  :class:`NetworkStatsReport`.
* :mod:`gephi_viz.partition`     — partition coloring from node attributes,
  communities or clustering, with multiple palettes.
* :mod:`gephi_viz.ranking`        — ranking-based node sizing / coloring /
  edge widths / label selection.
* :mod:`gephi_viz.preview`        — publication-grade rendering (matplotlib,
  pyvis, plotly, Cytoscape.js; SVG/PDF/PNG export).
* :mod:`gephi_viz.interactive_canvas`
                                  — a Qt-embedded interactive canvas with pan,
  zoom, tooltips, context menus, and a layout/partition/ranking toolbar.

Every submodule is independently importable and uses lazy imports for the
heavy numerical / plotting backends (numpy, scipy, networkx, matplotlib,
plotly, pyvis) so the package can be inspected on headless machines.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

__all__ = [
    "layouts",
    "filters",
    "statistics",
    "partition",
    "ranking",
    "preview",
    "interactive_canvas",
]
