"""Graph IO — every common format + JSON/Cytoscape/D3 exports.

The :class:`GraphIO` class wraps every :mod:`networkx` read/write function
for the common on-disk graph formats (GraphML, GEXF, GML, Pajek, edgelist,
adjlist) plus two JavaScript-friendly JSON serialisations:

- :meth:`to_json` / :meth:`from_json` — node-link JSON, the canonical
  D3.js / cytoscape.js interchange format.
- :meth:`to_cytoscape` / :meth:`from_cytoscape` — Cytoscape Web JSON
  (elements → nodes/edges with explicit ``data`` payloads).
- :meth:`to_pyvis` — returns a :class:`pyvis.network.Network` (lazy
  import; raises a helpful error if pyvis is not installed).
- :meth:`to_d3_force` — returns a dict ready to drop into a d3-force
  simulation (``{nodes: [...], links: [...]}``).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

__all__ = ["GraphIO"]

logger = logging.getLogger(__name__)


class GraphIO:
    """Stateless wrappers for every common graph-file format."""

    # ------------------------------------------------------------------
    # GraphML
    # ------------------------------------------------------------------
    @staticmethod
    def read_graphml(path: str) -> Any:
        """Read a GraphML file from disk.

        Args:
            path: Path to a ``.graphml`` (or ``.xml``) file.

        Returns:
            A :class:`networkx.Graph` (or :class:`DiGraph`).
        """
        import networkx as nx

        try:
            return nx.read_graphml(path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("read_graphml(%s) failed: %s", path, exc)
            raise

    @staticmethod
    def write_graphml(g: Any, path: str) -> None:
        """Write ``g`` to ``path`` in GraphML format.

        Args:
            g: A networkx graph.
            path: Destination path.
        """
        import networkx as nx

        try:
            nx.write_graphml(g, path)
            logger.debug("Wrote GraphML to %s (%d nodes).", path, g.number_of_nodes())
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("write_graphml(%s) failed: %s", path, exc)
            raise

    # ------------------------------------------------------------------
    # GEXF
    # ------------------------------------------------------------------
    @staticmethod
    def read_gexf(path: str) -> Any:
        """Read a GEXF file from disk (Gephi's native format)."""
        import networkx as nx

        try:
            return nx.read_gexf(path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("read_gexf(%s) failed: %s", path, exc)
            raise

    @staticmethod
    def write_gexf(g: Any, path: str) -> None:
        """Write ``g`` to ``path`` in GEXF format."""
        import networkx as nx

        try:
            nx.write_gexf(g, path)
            logger.debug("Wrote GEXF to %s (%d nodes).", path, g.number_of_nodes())
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("write_gexf(%s) failed: %s", path, exc)
            raise

    # ------------------------------------------------------------------
    # GML
    # ------------------------------------------------------------------
    @staticmethod
    def read_gml(path: str) -> Any:
        """Read a GML file from disk."""
        import networkx as nx

        try:
            return nx.read_gml(path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("read_gml(%s) failed: %s", path, exc)
            raise

    @staticmethod
    def write_gml(g: Any, path: str) -> None:
        """Write ``g`` to ``path`` in GML format."""
        import networkx as nx

        try:
            nx.write_gml(g, path)
            logger.debug("Wrote GML to %s (%d nodes).", path, g.number_of_nodes())
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("write_gml(%s) failed: %s", path, exc)
            raise

    # ------------------------------------------------------------------
    # Pajek
    # ------------------------------------------------------------------
    @staticmethod
    def read_pajek(path: str) -> Any:
        """Read a Pajek ``.net`` file from disk."""
        import networkx as nx

        try:
            return nx.read_pajek(path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("read_pajek(%s) failed: %s", path, exc)
            raise

    @staticmethod
    def write_pajek(g: Any, path: str) -> None:
        """Write ``g`` to ``path`` in Pajek format."""
        import networkx as nx

        try:
            nx.write_pajek(g, path)
            logger.debug("Wrote Pajek to %s (%d nodes).", path, g.number_of_nodes())
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("write_pajek(%s) failed: %s", path, exc)
            raise

    # ------------------------------------------------------------------
    # Edge list
    # ------------------------------------------------------------------
    @staticmethod
    def read_edgelist(
        path: str,
        delimiter: Optional[str] = None,
        create_using: Optional[Any] = None,
    ) -> Any:
        """Read an edge-list file.

        Each line is ``u<delimiter>v`` (optionally with extra columns
        parsed as edge attributes by networkx).

        Args:
            path: Path to the edge-list file.
            delimiter: Column separator (``None`` = whitespace).
            create_using: Graph subclass to use (default: :class:`Graph`).
        """
        import networkx as nx

        try:
            return nx.read_edgelist(path, delimiter=delimiter, create_using=create_using)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("read_edgelist(%s) failed: %s", path, exc)
            raise

    @staticmethod
    def write_edgelist(g: Any, path: str) -> None:
        """Write ``g`` to ``path`` as an edge list."""
        import networkx as nx

        try:
            nx.write_edgelist(g, path)
            logger.debug("Wrote edgelist to %s (%d edges).", path, g.number_of_edges())
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("write_edgelist(%s) failed: %s", path, exc)
            raise

    # ------------------------------------------------------------------
    # Adjacency list
    # ------------------------------------------------------------------
    @staticmethod
    def read_adjlist(path: str) -> Any:
        """Read an adjacency-list file."""
        import networkx as nx

        try:
            return nx.read_adjlist(path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("read_adjlist(%s) failed: %s", path, exc)
            raise

    @staticmethod
    def write_adjlist(g: Any, path: str) -> None:
        """Write ``g`` to ``path`` as an adjacency list."""
        import networkx as nx

        try:
            nx.write_adjlist(g, path)
            logger.debug("Wrote adjlist to %s (%d nodes).", path, g.number_of_nodes())
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("write_adjlist(%s) failed: %s", path, exc)
            raise

    # ------------------------------------------------------------------
    # JSON (node-link format — D3.js / cytoscape.js compatible)
    # ------------------------------------------------------------------
    @staticmethod
    def to_json(g: Any) -> str:
        """Serialize ``g`` to a JSON string in node-link format.

        This is the canonical interchange format for D3.js
        (``d3.force``) and cytoscape.js.

        Args:
            g: A networkx graph.

        Returns:
            A JSON string with keys ``"nodes"`` and ``"links"``.
        """
        import networkx as nx

        try:
            data = nx.node_link_data(g)
            return json.dumps(data, default=str)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("to_json failed: %s", exc)
            raise

    @staticmethod
    def from_json(s: str) -> Any:
        """Deserialize a JSON string (in node-link format) into a graph."""
        import networkx as nx

        try:
            data = json.loads(s)
            return nx.node_link_graph(data)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("from_json failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Cytoscape Web JSON
    # ------------------------------------------------------------------
    @staticmethod
    def to_cytoscape(g: Any) -> Dict[str, Any]:
        """Serialize ``g`` to a Cytoscape Web JSON dict.

        Args:
            g: A networkx graph.

        Returns:
            ``{"data": [...], "directed": bool, "multigraph": bool}``
            with ``data`` a list of ``{"data": {...}}`` entries — the
            canonical Cytoscape.js elements shape.
        """
        import networkx as nx

        try:
            data = nx.cytoscape_data(g)
            return data
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("to_cytoscape failed: %s", exc)
            raise

    @staticmethod
    def from_cytoscape(d: Dict[str, Any]) -> Any:
        """Deserialize a Cytoscape Web JSON dict into a networkx graph."""
        import networkx as nx

        try:
            return nx.cytoscape_graph(d)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("from_cytoscape failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # pyvis (lazy)
    # ------------------------------------------------------------------
    @staticmethod
    def to_pyvis(g: Any) -> Any:
        """Return a :class:`pyvis.network.Network` initialised from ``g``.

        Requires the optional :mod:`pyvis` package (HTML-network
        visualisation). Raises ``ImportError`` with a helpful message
        if pyvis is not installed.
        """
        try:
            from pyvis.network import Network
        except Exception as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "pyvis is required for GraphIO.to_pyvis() — install with "
                "`pip install pyvis`."
            ) from exc
        net = Network(notebook=False, directed=g.is_directed())
        try:
            for n, data in g.nodes(data=True):
                # pyvis expects str node ids; coerce non-str to str.
                net.add_node(str(n), label=str(n), **dict(data))
            for u, v, data in g.edges(data=True):
                net.add_edge(str(u), str(v), **dict(data))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("to_pyvis population failed: %s", exc)
            raise
        return net

    # ------------------------------------------------------------------
    # D3-force layout dict
    # ------------------------------------------------------------------
    @staticmethod
    def to_d3_force(g: Any) -> Dict[str, Any]:
        """Return a dict ready to drop into a d3-force simulation.

        The structure is::

            {
              "nodes": [{"id": "<node>", **attrs}, ...],
              "links": [{"source": "<u>", "target": "<v>", **attrs}, ...],
            }

        ``id``, ``source``, ``target`` are coerced to strings — d3-force
        requires them to be either strings or integers.

        Args:
            g: A networkx graph.

        Returns:
            A dict with ``"nodes"`` and ``"links"`` keys.
        """
        nodes = []
        for n, data in g.nodes(data=True):
            entry = {"id": str(n), **{k: v for k, v in dict(data).items()}}
            nodes.append(entry)
        links = []
        for u, v, data in g.edges(data=True):
            entry = {
                "source": str(u),
                "target": str(v),
                **{k: v for k, v in dict(data).items()},
            }
            links.append(entry)
        return {"nodes": nodes, "links": links}
