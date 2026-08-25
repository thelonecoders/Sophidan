"""Knowledge graph module for the Academic Research Suite.

This package provides academic-paper-aware network analysis:

- :class:`network_analyzer.NetworkAnalyzer` — unified graph builder and
  generic centrality / community / topology metrics.
- :class:`citation_graph.CitationGraph` — directed citation network with
  PageRank, HITS authority/hub scores, h-index and chain traversal.
- :class:`collaboration_graph.CollaborationGraph` — co-authorship network
  derived from a bipartite author–paper projection.
- :class:`temporal_network.TemporalNetwork` — dynamic graph with year-tagged
  edges, snapshot / evolution / growth-curve utilities.
- :class:`graph_algorithms.GraphAlgorithms` — pure-function library of
  advanced graph algorithms (k-core, modularity, link prediction, …).

Every public class accepts a list of ``Paper``-like objects (duck typed).
A ``Paper`` is anything that exposes the following attributes::

    id          : str                # stable identifier (DOI preferred)
    title       : str
    year        : int | None
    doi         : str | None
    authors     : list[str]          # names (or objects with a ``name`` attr)
    references : list[str] | None    # identifiers/DOIs of cited works
    affiliations: list[str] | None   # optional, for inter-institutional edges

Modules are designed to be independently importable; heavy optional
dependencies (matplotlib, plotly, leidenalg) are imported lazily.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

from typing import Any

# A ``Paper`` is duck-typed: any object exposing the attributes documented
# in the module docstring. We expose a type alias here so callers can write
# ``from knowledge_graph import Paper`` for documentation purposes.
Paper = Any

__all__ = [
    "Paper",
    "NetworkAnalyzer",
    "CitationGraph",
    "CollaborationGraph",
    "TemporalNetwork",
    "GraphAlgorithms",
]


def __getattr__(name: str):  # pragma: no cover - convenience re-exports
    """Lazy attribute access for the public classes.

    Importing the package should not eagerly import heavy submodules
    (networkx / pandas are fine, but matplotlib / plotly are not). We resolve
    the canonical class names lazily so that ``from knowledge_graph import
    NetworkAnalyzer`` only triggers the import when actually used.
    """
    if name in {"NetworkAnalyzer"}:
        from .network_analyzer import NetworkAnalyzer as _cls
        return _cls
    if name in {"CitationGraph"}:
        from .citation_graph import CitationGraph as _cls
        return _cls
    if name in {"CollaborationGraph"}:
        from .collaboration_graph import CollaborationGraph as _cls
        return _cls
    if name in {"TemporalNetwork"}:
        from .temporal_network import TemporalNetwork as _cls
        return _cls
    if name in {"GraphAlgorithms"}:
        from .graph_algorithms import GraphAlgorithms as _cls
        return _cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
