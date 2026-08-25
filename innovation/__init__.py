"""innovation — novel research-intelligence capabilities for the
Academic Research Suite (v2.0.0).

This package bundles a set of analytical modules that go *beyond* the
v1.0.0 baseline (basic AI assistant + topic modeling) and *beyond* what
existing off-the-shelf tools (Connected Papers, Inciteful, VOSviewer,
CiteSpace, Publish-or-Perish, Elicit) offer:

* :mod:`innovation.citation_bursts` — Kleinberg-style burst detection
  for papers / authors / keywords / journals / topics, with timeline
  visualization.
* :mod:`innovation.frontier_mapping` — knowledge-frontier mapping via
  embedding-density, topic-model-boundary, and citation-velocity
  approaches, plus temporal frontier tracking.
* :mod:`innovation.trend_forecasting` — ARIMA / Prophet / linear /
  exponential forecasts of topic prevalence, citation growth, author
  productivity and field-level trends.
* :mod:`innovation.paper_recommendation` — semantic paper recommender
  with MMR diversification, bridge-paper detection, trend-aware
  recommendation, and natural-language explanations.
* :mod:`innovation.collaboration_recommendation` — author-collaboration
  recommender using complementary expertise, weak ties, co-authorship
  history and emerging-collaboration detection.
* :mod:`innovation.novelty_scoring` — paper / topic novelty scores
  (Uzzi atypicality, Funk & Owen-Smith disruption index, percentile
  ranking).
* :mod:`innovation.research_directions` — strategic research-direction
  recommender that converts gaps, frontiers, and forecasts into
  concrete, scored research directions with Gantt-style roadmaps.

Every submodule is independently importable (lazy imports throughout),
runs on the v1.0.0 :class:`data_acquisition.base_scraper.Paper`
dataclass, and produces matplotlib figures using ``constrained_layout``
with CJK-aware font fallback.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

__all__ = [
    "citation_bursts",
    "frontier_mapping",
    "trend_forecasting",
    "paper_recommendation",
    "collaboration_recommendation",
    "novelty_scoring",
    "research_directions",
]
