"""REST endpoints for the ``/api/network`` resource.

Wraps the v2.0.0 :mod:`networkx_pro` and :mod:`gephi_viz` packages to
expose centrality, community detection, component analysis, shortest
paths, link prediction, layouts, statistics, filtering, and graph
export via HTTP.

All heavy deps (networkx, numpy, scipy, sklearn) are lazy-imported
inside the handlers so the blueprint registers even when the underlying
modules are unavailable.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

network_bp = Blueprint("network", __name__, url_prefix="/api/network")


def _bad_request(msg: str):
    return jsonify({"error": "bad_request", "message": msg}), 400


def _build_graph(payload: Any) -> Any:
    """Convert a JSON dict (``{"graph": {"nodes": [...], "edges": [...]}}``)
    into a :class:`networkx.Graph`.

    Accepts the node-link format produced by
    ``networkx.readwrite.json_graph.node_link_data``.
    """
    import networkx as nx  # lazy
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    graph_data = payload.get("graph") or payload
    if isinstance(graph_data, str):
        # Treat as JSON-encoded graph.
        import json
        graph_data = json.loads(graph_data)
    if not isinstance(graph_data, dict):
        raise ValueError("graph must be a JSON object")
    if "nodes" in graph_data and "links" in graph_data:
        from networkx.readwrite import json_graph
        return json_graph.node_link_graph(graph_data)
    if "nodes" in graph_data and "edges" in graph_data:
        g = nx.Graph()
        for n in graph_data.get("nodes", []):
            node_id = n.get("id") if isinstance(n, dict) else n
            attrs = {k: v for k, v in (n or {}).items() if k != "id"} if isinstance(n, dict) else {}
            g.add_node(node_id, **attrs)
        for e in graph_data.get("edges", []):
            if isinstance(e, dict):
                src, tgt = e.get("source"), e.get("target")
                if src is None or tgt is None:
                    continue
                attrs = {k: v for k, v in e.items() if k not in ("source", "target")}
                g.add_edge(src, tgt, **attrs)
            elif isinstance(e, (list, tuple)) and len(e) >= 2:
                g.add_edge(e[0], e[1])
        return g
    raise ValueError("graph must contain 'nodes' + 'edges' or 'nodes' + 'links'")


@network_bp.route("/centrality", methods=["POST"])
def centrality():
    """Compute centrality scores.

    Body: ``{"graph": {...}, "method": str}`` where ``method`` is one of
    ``degree``, ``in_degree``, ``out_degree``, ``closeness``,
    ``betweenness``, ``eigenvector``, ``katz``, ``pagerank``, ``hits``,
    ``harmonic``, ``load``, ``subgraph``, ``communicability``,
    ``percolation``, ``second_order``.

    Returns:
        ``{"centrality": {node_id: score, ...}, "method": str}``.
    """
    payload = request.get_json(silent=True) or {}
    method = (payload.get("method") or "degree").strip()
    try:
        g = _build_graph(payload)
    except Exception as exc:
        return _bad_request(str(exc))
    try:
        from networkx_pro.algorithms_centralities import Centralities
        method_map = {
            "degree": Centralities.degree_centrality,
            "in_degree": Centralities.in_degree_centrality,
            "out_degree": Centralities.out_degree_centrality,
            "closeness": Centralities.closeness_centrality,
            "betweenness": Centralities.betweenness_centrality,
            "eigenvector": Centralities.eigenvector_centrality,
            "katz": Centralities.katz_centrality,
            "pagerank": Centralities.pagerank,
            "hits": Centralities.hits,
            "harmonic": Centralities.harmonic_centrality,
            "load": Centralities.load_centrality,
            "subgraph": Centralities.subgraph_centrality,
            "communicability": Centralities.communicability_centrality,
            "percolation": Centralities.percolation_centrality,
            "second_order": Centralities.second_order_centrality,
        }
        fn = method_map.get(method)
        if fn is None:
            return _bad_request(f"unknown method: {method}")
        result = fn(g)
        # HITS returns a tuple (hubs, authorities).
        if isinstance(result, tuple) and len(result) == 2:
            return jsonify({
                "method": method,
                "centrality": {str(k): v for k, v in (result[0] or {}).items()},
                "secondary": {str(k): v for k, v in (result[1] or {}).items()},
            })
        return jsonify({
            "method": method,
            "centrality": {str(k): v for k, v in (result or {}).items()},
        })
    except Exception as exc:
        logger.exception("/api/network/centrality failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@network_bp.route("/community", methods=["POST"])
def community():
    """Detect communities in the supplied graph.

    Body: ``{"graph": {...}, "method": str}`` where ``method`` is one of
    ``louvain``, ``greedy_modularity``, ``label_propagation``,
    ``asyn_lpa``, ``k_clique``, ``girvan_newman``.
    """
    payload = request.get_json(silent=True) or {}
    method = (payload.get("method") or "louvain").strip()
    try:
        g = _build_graph(payload)
    except Exception as exc:
        return _bad_request(str(exc))
    try:
        from networkx_pro.algorithms_communities import CommunityDetection
        method_map = {
            "louvain": CommunityDetection.louvain_communities,
            "greedy_modularity": CommunityDetection.greedy_modularity_communities,
            "label_propagation": CommunityDetection.label_propagation_communities,
            "asyn_lpa": CommunityDetection.asyn_lpa_communities,
            "k_clique": CommunityDetection.k_clique_communities,
            "girvan_newman": CommunityDetection.girvan_newman,
        }
        fn = method_map.get(method)
        if fn is None:
            return _bad_request(f"unknown method: {method}")
        result = fn(g)
        # Girvan-newman returns a generator of tuples-of-sets.
        if hasattr(result, "__iter__") and not isinstance(result, (list, tuple)):
            try:
                result = list(result)
            except TypeError:
                result = []
        communities = [
            [str(n) for n in (c if hasattr(c, "__iter__") else [c])]
            for c in (result or [])
        ]
        return jsonify({"method": method, "communities": communities})
    except Exception as exc:
        logger.exception("/api/network/community failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@network_bp.route("/components", methods=["POST"])
def components():
    """Run component analysis on the supplied graph.

    Body: ``{"graph": {...}}``.

    Returns:
        ``{"components": [...], "articulation_points": [...], "bridges": [...],
        "core_number": {...}, "transitivity": float,
        "average_clustering": float}``.
    """
    payload = request.get_json(silent=True) or {}
    try:
        g = _build_graph(payload)
    except Exception as exc:
        return _bad_request(str(exc))
    try:
        from networkx_pro.algorithms_components import ComponentAnalysis
        comps = [[str(n) for n in s] for s in ComponentAnalysis.connected_components(g)]
        aps = [str(n) for n in ComponentAnalysis.articulation_points(g)]
        bridges = [[str(u), str(v)] for u, v in ComponentAnalysis.bridges(g)]
        core_num = {str(k): v for k, v in ComponentAnalysis.core_number(g).items()}
        return jsonify({
            "components": comps,
            "articulation_points": aps,
            "bridges": bridges,
            "core_number": core_num,
            "transitivity": ComponentAnalysis.transitivity(g),
            "average_clustering": ComponentAnalysis.average_clustering(g),
        })
    except Exception as exc:
        logger.exception("/api/network/components failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@network_bp.route("/paths", methods=["POST"])
def paths():
    """Compute shortest paths between two nodes.

    Body: ``{"graph": {...}, "source": node_id, "target": node_id}``.

    Returns:
        ``{"shortest_path": [...], "length": int, "all_shortest_paths": [...]}``.
    """
    payload = request.get_json(silent=True) or {}
    source = payload.get("source")
    target = payload.get("target")
    if source is None or target is None:
        return _bad_request("source and target are required")
    try:
        g = _build_graph(payload)
    except Exception as exc:
        return _bad_request(str(exc))
    try:
        from networkx_pro.algorithms_paths_flows import PathsAndFlows
        path = PathsAndFlows.shortest_path(g, source, target)
        length = PathsAndFlows.shortest_path_length(g, source, target)
        try:
            all_paths = [list(p) for p in PathsAndFlows.all_shortest_paths(g, source, target)]
        except Exception:
            all_paths = []
        return jsonify({
            "shortest_path": [str(n) for n in (path or [])],
            "length": int(length) if length is not None else None,
            "all_shortest_paths": [[str(n) for n in p] for p in all_paths],
        })
    except Exception as exc:
        logger.exception("/api/network/paths failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@network_bp.route("/link-prediction", methods=["POST"])
def link_prediction():
    """Predict the top-N most likely future edges.

    Body: ``{"graph": {...}, "method": str, "top_n": int?}`` where
    ``method`` is one of ``jaccard``, ``adamic_adar``, ``preferential_attachment``,
    ``resource_allocation``, ``common_neighbor_centrality``, ``katz_similarity``,
    ``predict_top_links``.
    """
    payload = request.get_json(silent=True) or {}
    method = (payload.get("method") or "jaccard").strip()
    top_n = int(payload.get("top_n", 10) or 10)
    try:
        g = _build_graph(payload)
    except Exception as exc:
        return _bad_request(str(exc))
    try:
        from networkx_pro.algorithms_link_prediction import LinkPrediction
        method_map = {
            "jaccard": LinkPrediction.jaccard_coefficient,
            "adamic_adar": LinkPrediction.adamic_adar_index,
            "preferential_attachment": LinkPrediction.preferential_attachment,
            "resource_allocation": LinkPrediction.resource_allocation_index,
            "common_neighbor_centrality": LinkPrediction.common_neighbor_centrality,
            "katz_similarity": LinkPrediction.katz_similarity,
            "predict_top_links": LinkPrediction.predict_top_links,
        }
        fn = method_map.get(method)
        if fn is None:
            return _bad_request(f"unknown method: {method}")
        result = fn(g) if method != "predict_top_links" else fn(g, top_n=top_n)
        preds = []
        for u, v, score in (result or []):
            preds.append({"source": str(u), "target": str(v), "score": float(score)})
        preds = preds[:top_n]
        return jsonify({"method": method, "predictions": preds})
    except Exception as exc:
        logger.exception("/api/network/link-prediction failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@network_bp.route("/layouts", methods=["POST"])
def layouts():
    """Compute 2-D node positions for the supplied graph.

    Body: ``{"graph": {...}, "layout": str}`` where ``layout`` is one of
    ``spring``, ``kamada``, ``circular``, ``shell``, ``spectral``,
    ``force_atlas``, ``stress``.

    Returns:
        ``{"positions": {node_id: [x, y], ...}}``.
    """
    payload = request.get_json(silent=True) or {}
    layout = (payload.get("layout") or "spring").strip()
    try:
        g = _build_graph(payload)
    except Exception as exc:
        return _bad_request(str(exc))
    try:
        if layout == "force_atlas" or layout == "forceatlas2":
            from gephi_viz.layouts import ForceAtlas2
            positions = ForceAtlas2().apply(g, {}, iterations=50)
        elif layout == "stress":
            from gephi_viz.layouts import KamadaKawai
            positions = KamadaKawai().apply(g, {}, iterations=50)
        else:
            import networkx as nx
            fn = {
                "spring": nx.spring_layout,
                "kamada": nx.kamada_kawai_layout,
                "circular": nx.circular_layout,
                "shell": nx.shell_layout,
                "spectral": nx.spectral_layout,
            }.get(layout, nx.spring_layout)
            positions = fn(g)
        return jsonify({
            "layout": layout,
            "positions": {str(k): [float(v[0]), float(v[1])] for k, v in (positions or {}).items()},
        })
    except Exception as exc:
        logger.exception("/api/network/layouts failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@network_bp.route("/stats", methods=["POST"])
def stats():
    """Compute the full Gephi-style network statistics report.

    Body: ``{"graph": {...}}``.
    """
    payload = request.get_json(silent=True) or {}
    try:
        g = _build_graph(payload)
    except Exception as exc:
        return _bad_request(str(exc))
    try:
        from gephi_viz.statistics import NetworkStatistics
        report = NetworkStatistics().compute_all(g)
        data = report.to_dict() if hasattr(report, "to_dict") else {"nodes": g.number_of_nodes(), "edges": g.number_of_edges()}
        return jsonify({"stats": data})
    except Exception as exc:
        logger.exception("/api/network/stats failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@network_bp.route("/filter", methods=["POST"])
def filter_graph():
    """Apply a chain of filters to the supplied graph.

    Body: ``{"graph": {...}, "filters": [{"kind": str, "params": {...}}, ...]}``.

    Returns:
        ``{"filtered": {"nodes": [...], "edges": [...]}}``.
    """
    payload = request.get_json(silent=True) or {}
    try:
        g = _build_graph(payload)
    except Exception as exc:
        return _bad_request(str(exc))
    filters_spec = payload.get("filters") or []
    try:
        from gephi_viz.filters import (
            DegreeRangeFilter, WeightRangeFilter, GiantComponentFilter,
            KCoreFilter, EgoNetworkFilter, FilterChain,
        )
        chain = FilterChain()
        for f in filters_spec:
            if not isinstance(f, dict):
                continue
            kind = f.get("kind") or f.get("name")
            params = f.get("params") or {}
            if kind == "DegreeRange":
                chain.add_filter(DegreeRangeFilter(min_degree=params.get("min", 1),
                                                   max_degree=params.get("max", 10**9)))
            elif kind == "WeightRange":
                chain.add_filter(WeightRangeFilter(min_weight=params.get("min", 0.0),
                                                  max_weight=params.get("max", 10**9)))
            elif kind == "GiantComponent":
                chain.add_filter(GiantComponentFilter())
            elif kind == "KCore":
                chain.add_filter(KCoreFilter(k=params.get("k", 2)))
            elif kind == "EgoNetwork":
                chain.add_filter(EgoNetworkFilter(ego_node=params.get("ego_node")))
            else:
                logger.debug("Skipping unknown filter kind: %s", kind)
        filtered = chain.apply(g)
        from networkx.readwrite import json_graph
        data = json_graph.node_link_data(filtered)
        return jsonify({"filtered": data})
    except Exception as exc:
        logger.exception("/api/network/filter failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502


@network_bp.route("/export", methods=["POST"])
def export():
    """Export the supplied graph in a chosen on-disk format.

    Body: ``{"graph": {...}, "format": str}`` where ``format`` is one of
    ``graphml``, ``gexf``, ``gml``, ``pajek``, ``edgelist``, ``adjlist``,
    ``json``, ``cytoscape``, ``d3``.

    Returns:
        ``{"content": str}`` for textual formats, ``{"data": dict}`` for
        JSON / Cytoscape / D3.
    """
    payload = request.get_json(silent=True) or {}
    fmt = (payload.get("format") or "graphml").strip().lower()
    try:
        g = _build_graph(payload)
    except Exception as exc:
        return _bad_request(str(exc))
    try:
        from networkx_pro.graph_io import GraphIO
        if fmt == "json":
            return jsonify({"format": fmt, "data": GraphIO.to_json(g)})
        if fmt == "cytoscape":
            return jsonify({"format": fmt, "data": GraphIO.to_cytoscape(g)})
        if fmt == "d3":
            return jsonify({"format": fmt, "data": GraphIO.to_d3_force(g)})
        # Textual formats — return the string content directly.
        text_format_map = {
            "graphml": "graphml", "gexf": "gexf", "gml": "gml",
            "pajek": "pajek", "edgelist": "edgelist", "adjlist": "adjlist",
        }
        if fmt not in text_format_map:
            return _bad_request(f"unknown format: {fmt}")
        # Use an in-memory buffer.
        import io
        if fmt in ("graphml", "gexf", "gml", "pajek", "edgelist", "adjlist"):
            # All networkx writers ultimately call .write() with bytes
            # (the networkx 3.x writers always encode their output),
            # so we use BytesIO and decode at the end.
            import networkx as nx
            buf = io.BytesIO()
            writer_map = {
                "graphml":  nx.write_graphml,
                "gexf":     nx.write_gexf,
                "gml":      nx.write_gml,
                "pajek":    nx.write_pajek,
                "edgelist": nx.write_weighted_edgelist,
                "adjlist":  nx.write_adjlist,
            }
            writer_map[fmt](g, buf)
            return jsonify({"format": fmt, "content": buf.getvalue().decode("utf-8", errors="replace")})
        return _bad_request(f"unknown format: {fmt}")
    except Exception as exc:
        logger.exception("/api/network/export failed: %s", exc)
        return jsonify({"error": "analysis_failed", "message": str(exc)}), 502
