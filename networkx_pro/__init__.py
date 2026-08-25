"""networkx_pro — full NetworkX algorithm exposure + graph IO + bipartite + multigraph.

This package is a thin, opinionated wrapper around :mod:`networkx` (≥ 3.2)
that exposes the *full* power of the library plus a handful of additions
typically expected from a Gephi-style statistics panel (silhouette score,
community comparison via NMI / AMI / ARI / VI, k-truss, onion layers,
percolation centrality, Estrada's subgraph centrality, current-flow
centralities, link prediction, bipartite projections, multigraph
pagerank, JSON/Cytoscape/D3 exports, etc.).

The package is organised as a collection of *stateless* classes whose
methods accept a :class:`networkx.Graph` (or :class:`DiGraph`,
:class:`MultiGraph`, :class:`MultiDiGraph`) as their first argument.
No method mutates its input graph.

Public classes (lazy-imported on first access):

- :class:`networkx_pro.algorithms_centralities.Centralities` — 20
  centrality measures (degree / in / out / closeness / betweenness /
  eigenvector / eigenvector_numpy / katz / pagerank / hits / authority /
  hub / harmonic / percolation / second_order / current_flow_closeness /
  current_flow_betweenness / communicability / load / subgraph) plus a
  one-shot :meth:`all_centralities` aggregator.
- :class:`networkx_pro.algorithms_communities.CommunityDetection` —
  Louvain, greedy modularity, label propagation (sync/async), Girvan-Newman,
  k-clique, plus modularity / partition quality / density / silhouette /
  NMI / AMI / ARI / VI community comparison.
- :class:`networkx_pro.algorithms_components.ComponentAnalysis` —
  connected / strongly / weakly components, condensation DAG,
  articulation points, bridges, k-core / k-shell / k-crust / k-corona /
  k-truss, core number, onion layers, cliques, max-weight clique,
  triangles, transitivity, average clustering.
- :class:`networkx_pro.algorithms_paths_flows.PathsAndFlows` —
  shortest paths (single / all / all-pairs), diameter / radius /
  eccentricity / center / periphery, max-flow / min-cut / Edmonds-Karp /
  Ford-Fulkerson (manual), edge / node disjoint paths, A*, all simple paths.
- :class:`networkx_pro.algorithms_link_prediction.LinkPrediction` —
  resource allocation, Jaccard, Adamic-Adar, preferential attachment,
  Soundarajan-Hopcroft (CN/RA), within-inter-cluster, common-neighbour
  centrality, Katz similarity, top-N link prediction.
- :class:`networkx_pro.algorithms_isomorphism.Isomorphism` —
  is_isomorphic / could_be_isomorphic / faster_could_be_isomorphic /
  is_isomorphic_to / vf2_graph_isomorphism / graph_census /
  find_motifs (network motifs up to size n).
- :class:`networkx_pro.algorithms_bipartite.BipartiteAnalysis` —
  is_bipartite / sets / density / degrees / projections (simple,
  weighted, collaboration, generic) / clustering / average_clustering /
  redundancy.
- :class:`networkx_pro.algorithms_generators.GraphGenerators` —
  complete / complete_bipartite / karate / davis / florentine /
  Erdős-Rényi / Watts-Strogatz / Barabási-Albert / powerlaw-cluster /
  random-geometric / configuration / expected-degree / Havel-Hakimi /
  random-tree / random-cograph, plus a :meth:`null_model` factory.
- :class:`networkx_pro.graph_io.GraphIO` — read/write GraphML, GEXF,
  GML, Pajek, edgelist, adjlist, JSON (node-link), Cytoscape JSON,
  pyvis Network, d3-force layout dict.
- :class:`networkx_pro.multigraph.MultiGraphAnalysis` — multi-degree
  centrality, parallel-edge aggregation, parallel-edge counting,
  multi-edge-aware PageRank.

Every module is independently importable; heavy optional deps
(numpy, scipy, scikit-learn, pyvis) are imported lazily.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

__all__ = [
    "Centralities",
    "CommunityDetection",
    "ComponentAnalysis",
    "PathsAndFlows",
    "LinkPrediction",
    "Isomorphism",
    "BipartiteAnalysis",
    "GraphGenerators",
    "GraphIO",
    "MultiGraphAnalysis",
]


def __getattr__(name: str):
    """Lazy attribute access for the public classes.

    Importing the package does not eagerly import heavy submodules
    (numpy / scipy / scikit-learn / pyvis). The canonical class names
    are resolved lazily so that ``from networkx_pro import Centralities``
    only triggers the import on first use.
    """
    _mapping = {
        "Centralities": "networkx_pro.algorithms_centralities",
        "CommunityDetection": "networkx_pro.algorithms_communities",
        "ComponentAnalysis": "networkx_pro.algorithms_components",
        "PathsAndFlows": "networkx_pro.algorithms_paths_flows",
        "LinkPrediction": "networkx_pro.algorithms_link_prediction",
        "Isomorphism": "networkx_pro.algorithms_isomorphism",
        "BipartiteAnalysis": "networkx_pro.algorithms_bipartite",
        "GraphGenerators": "networkx_pro.algorithms_generators",
        "GraphIO": "networkx_pro.graph_io",
        "MultiGraphAnalysis": "networkx_pro.multigraph",
    }
    if name in _mapping:
        import importlib

        module = importlib.import_module(_mapping[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
