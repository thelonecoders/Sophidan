"""Temporal (dynamic) academic network with year-tagged edges.

The :class:`TemporalNetwork` builds an undirected weighted graph where
each edge carries a ``years`` attribute (list of years in which the edge
was observed). This supports cumulative snapshots (graph as-of-year-X),
evolution analysis, emerging/fading node detection, and time-resolved
centrality.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import os
import tempfile
from itertools import combinations
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

import networkx as nx

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

# Duck-typed Paper helpers.
try:
    from .network_analyzer import (
        _get_attr,
        _paper_affiliations,
        _paper_authors,
        _paper_id,
        _paper_refs,
        _paper_year,
    )
except ImportError:  # pragma: no cover - standalone fallback
    def _get_attr(obj, name, default=None):  # type: ignore[no-redef]
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)

    def _paper_authors(paper):  # type: ignore[no-redef]
        raw = _get_attr(paper, "authors", []) or []
        out = []
        for a in raw:
            if isinstance(a, str):
                n = a.strip()
            else:
                n = (_get_attr(a, "name") or _get_attr(a, "full_name") or "").strip()
            if n:
                out.append(n)
        return out

    def _paper_year(paper):  # type: ignore[no-redef]
        y = _get_attr(paper, "year") or _get_attr(paper, "publication_year")
        try:
            return int(y) if y is not None and str(y).strip() != "" else None
        except (TypeError, ValueError):
            return None

    def _paper_id(paper):  # type: ignore[no-redef]
        for key in ("doi", "id", "openalex_id"):
            v = _get_attr(paper, key)
            if v:
                return str(v).strip()
        return (_get_attr(paper, "title") or "").strip()

    def _paper_refs(paper):  # type: ignore[no-redef]
        return []

    def _paper_affiliations(paper):  # type: ignore[no-redef]
        return []


__all__ = ["TemporalNetwork"]

logger = logging.getLogger(__name__)


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib font/unicode settings."""
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


class TemporalNetwork:
    """Year-resolved academic network supporting cumulative slicing.

    The graph is built by :meth:`build` and stored on ``self.graph``.
    Edges carry a ``years`` list attribute. Nodes carry a ``first_year``
    attribute (the earliest year they were observed in).

    By default the temporal network is a co-authorship network (edge
    between two authors = co-authored a paper that year); pass
    ``mode='citation'`` to :meth:`build` to instead build a temporal
    citation network (edge between two papers = citation observed that
    year).
    """

    def __init__(self) -> None:
        """Initialize an empty temporal network."""
        self.graph: nx.Graph = nx.Graph()
        self._edge_years: Dict[Tuple[Any, Any], List[int]] = {}
        self._node_years: Dict[Any, List[int]] = {}
        self.logger = logging.getLogger(f"{__name__}.{type(self).__name__}")

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def build(
        self,
        papers: Sequence[Any],
        mode: str = "collaboration",
    ) -> nx.Graph:
        """Build the temporal network.

        Args:
            papers: Sequence of ``Paper``-like objects.
            mode: ``'collaboration'`` (default) builds a co-authorship
                network with edges between two authors weighted by the
                number of joint publications; ``'citation'`` builds an
                undirected paper-to-paper network where edges represent
                a citation relation (the original directionality is
                dropped for temporal slicing).

        Returns:
            The constructed :class:`networkx.Graph`. Each edge carries
            ``years`` (sorted list of years observed) and ``weight``
            (# observations); each node carries ``first_year``,
            ``last_year``, and ``years`` (all years observed).
        """
        mode = mode.lower().strip()
        if mode not in ("collaboration", "citation"):
            raise ValueError(f"Unknown temporal mode: {mode!r}.")

        self.graph = nx.Graph()
        self._edge_years = {}
        self._node_years = {}

        if mode == "collaboration":
            for paper in papers:
                authors = _paper_authors(paper)
                year = _paper_year(paper)
                if year is None or len(authors) < 2:
                    # Single-author or undated papers contribute only node
                    # presence (so the node can be tracked for first_year).
                    for author in authors:
                        self._register_node(author, year)
                    continue
                for author in authors:
                    self._register_node(author, year)
                for a, b in combinations(authors, 2):
                    if a == b:
                        continue
                    self._register_edge(a, b, year)
        else:  # citation
            # Build an id index for cited papers that exist in the input set.
            id_index: Dict[str, str] = {}
            for paper in papers:
                pid = _paper_id(paper)
                if pid:
                    id_index[pid] = pid
                    doi = _get_attr(paper, "doi")
                    if doi:
                        id_index[str(doi).strip()] = pid
            for paper in papers:
                src = _paper_id(paper)
                year = _paper_year(paper)
                if not src:
                    continue
                if year is not None:
                    self._register_node(src, year)
                for ref in _paper_refs(paper):
                    dst = id_index.get(ref)
                    if dst and dst != src:
                        # For temporal slicing we use the citing paper's year
                        # (the moment the edge appeared).
                        if year is not None:
                            self._register_node(dst, year)
                            self._register_edge(src, dst, year)

        # Materialize the networkx graph from the registered observations.
        for node, years in self._node_years.items():
            self.graph.add_node(
                node,
                first_year=min(years),
                last_year=max(years),
                years=sorted(set(years)),
            )
        for (u, v), years in self._edge_years.items():
            ys = sorted(set(years))
            self.graph.add_edge(u, v, years=ys, weight=len(ys))

        self.logger.info(
            "Temporal %s network built: %d nodes, %d edges (years %s–%s).",
            mode,
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
            self._min_year(),
            self._max_year(),
        )
        return self.graph

    def _register_node(self, node: Any, year: Optional[int]) -> None:
        if year is None:
            return
        self._node_years.setdefault(node, []).append(year)

    def _register_edge(self, u: Any, v: Any, year: int) -> None:
        # Canonicalize the unordered edge key.
        key = (u, v) if str(u) <= str(v) else (v, u)
        self._edge_years.setdefault(key, []).append(year)

    # ------------------------------------------------------------------
    # Slicing
    # ------------------------------------------------------------------
    def _min_year(self) -> Optional[int]:
        if not self._node_years:
            return None
        return min(min(y) for y in self._node_years.values())

    def _max_year(self) -> Optional[int]:
        if not self._node_years:
            return None
        return max(max(y) for y in self._node_years.values())

    def snapshot(self, year: int) -> nx.Graph:
        """Return the cumulative graph *as-of* ``year`` (inclusive).

        The snapshot contains every node whose ``first_year <= year`` and
        every edge whose earliest observed year is ≤ ``year``. Edge weights
        are recomputed from the count of years ≤ ``year``.

        Args:
            year: Cutoff year.

        Returns:
            A new :class:`networkx.Graph`.
        """
        G = nx.Graph()
        for node, data in self.graph.nodes(data=True):
            if (data.get("first_year") or 10**9) <= year:
                G.add_node(node, **data)
        for u, v, data in self.graph.edges(data=True):
            years = data.get("years", [])
            kept = [y for y in years if y <= year]
            if kept:
                G.add_edge(u, v, years=kept, weight=len(kept))
        return G

    def evolution(
        self,
        start_year: int,
        end_year: int,
        step: int = 1,
    ) -> List[Tuple[int, nx.Graph, Dict[str, float]]]:
        """Generate a sequence of cumulative snapshots with metrics.

        Args:
            start_year: First year to include.
            end_year: Last year (inclusive).
            step: Year step (defaults to 1).

        Returns:
            A list of ``(year, graph, metrics)`` tuples where ``metrics``
            is a dict with keys: ``nodes``, ``edges``, ``density``,
            ``avg_degree``, ``clustering``.
        """
        seq: List[Tuple[int, nx.Graph, Dict[str, float]]] = []
        for year in range(start_year, end_year + 1, step):
            G = self.snapshot(year)
            metrics = self._metrics(G)
            seq.append((year, G, metrics))
        return seq

    def growth_curve(self) -> "pd.DataFrame":
        """Compute network growth metrics over every observed year.

        Returns:
            A :class:`pandas.DataFrame` with columns ``year``, ``nodes``,
            ``edges``, ``density``, ``avg_degree``, ``new_nodes``,
            ``new_edges``. Sorted ascending by year.
        """
        import pandas as pd

        rows: List[Dict[str, Any]] = []
        prev_nodes = prev_edges = 0
        if self._min_year() is None or self._max_year() is None:
            return pd.DataFrame(columns=["year", "nodes", "edges", "density", "avg_degree", "new_nodes", "new_edges"])
        for year in range(self._min_year(), self._max_year() + 1):  # type: ignore[arg-type]
            G = self.snapshot(year)
            n_nodes = G.number_of_nodes()
            n_edges = G.number_of_edges()
            density = nx.density(G) if n_nodes > 1 else 0.0
            avg_degree = (2 * n_edges / n_nodes) if n_nodes > 0 else 0.0
            rows.append(
                {
                    "year": year,
                    "nodes": n_nodes,
                    "edges": n_edges,
                    "density": float(density),
                    "avg_degree": float(avg_degree),
                    "new_nodes": n_nodes - prev_nodes,
                    "new_edges": n_edges - prev_edges,
                }
            )
            prev_nodes, prev_edges = n_nodes, n_edges
        return pd.DataFrame(rows)

    def emerging_nodes(self, year: int, lookback: int = 3) -> List[Any]:
        """Nodes that first appeared in ``[year-lookback+1, year]``.

        Args:
            year: Reference year.
            lookback: Window length (in years, inclusive of ``year``).

        Returns:
            List of nodes (sorted by first appearance year, then by id).
        """
        low = year - lookback + 1
        out: List[Tuple[int, Any]] = []
        for node, data in self.graph.nodes(data=True):
            fy = data.get("first_year")
            if fy is not None and low <= fy <= year:
                out.append((fy, node))
        out.sort(key=lambda x: (x[0], str(x[1])))
        return [node for _, node in out]

    def fading_nodes(self, year: int, lookback: int = 3) -> List[Any]:
        """Nodes whose last observed activity is in ``[year-lookback+1, year]``.

        A "fading" node is one that has not been seen after the window — i.e.
        it has not been active in the lookback window but exists in the
        network before that window.

        Actually we report nodes whose last activity falls inside the window,
        i.e., they likely "went quiet" recently.

        Args:
            year: Reference year.
            lookback: Window length.

        Returns:
            List of nodes (sorted by last-activity year, then by id).
        """
        low = year - lookback + 1
        out: List[Tuple[int, Any]] = []
        for node, data in self.graph.nodes(data=True):
            ly = data.get("last_year")
            if ly is not None and low <= ly <= year:
                out.append((ly, node))
        out.sort(key=lambda x: (x[0], str(x[1])))
        return [node for _, node in out]

    def temporal_centrality(self, node: Any, metric: str = "degree") -> "pd.Series":
        """Compute the per-year centrality of ``node`` over time.

        Args:
            node: The node identifier.
            metric: ``'degree'`` (default), ``'betweenness'``,
                ``'closeness'``, or ``'pagerank'``.

        Returns:
            A :class:`pandas.Series` indexed by year with the centrality
            value. Years where the node is absent get a value of ``0.0``.
        """
        import pandas as pd

        if self._min_year() is None or self._max_year() is None:
            return pd.Series([], dtype=float, name=metric)
        if node not in self.graph:
            self.logger.debug("temporal_centrality: node %r not in graph.", node)
            return pd.Series([], dtype=float, name=metric)

        metric = metric.lower().strip()
        records: Dict[int, float] = {}
        for year in range(self._min_year(), self._max_year() + 1):  # type: ignore[arg-type]
            G = self.snapshot(year)
            if G.number_of_nodes() == 0 or node not in G:
                records[year] = 0.0
                continue
            try:
                if metric == "degree":
                    records[year] = float(G.degree(node))
                elif metric == "betweenness":
                    records[year] = float(
                        nx.betweenness_centrality(G, normalized=True).get(node, 0.0)
                    )
                elif metric == "closeness":
                    records[year] = float(nx.closeness_centrality(G, u=node))
                elif metric == "pagerank":
                    records[year] = float(nx.pagerank(G).get(node, 0.0))
                else:
                    raise ValueError(
                        f"Unknown metric: {metric!r}. "
                        "Expected degree|betweenness|closeness|pagerank."
                    )
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("Centrality %s failed for year %s (%s).", metric, year, exc)
                records[year] = 0.0
        return pd.Series(records, name=metric).sort_index()

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------
    def visualize_evolution(
        self,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
        step: int = 1,
        output_path: Optional[str] = None,
        fps: int = 2,
    ) -> str:
        """Animate the network's evolution as a GIF.

        Args:
            start_year: First year (defaults to the earliest observed).
            end_year: Last year (defaults to the latest observed).
            step: Year step (defaults to 1).
            output_path: Path to write the GIF. If ``None``, a temporary
                file is created and its path is returned.
            fps: Frames per second for the GIF.

        Returns:
            Path to the generated ``.gif`` file. Requires the ``imageio``
            package (already listed in the project's optional deps via
            Pillow / imageio).

        Raises:
            RuntimeError: If the temporal network is empty.
            ImportError: If ``imageio`` is not installed.
        """
        import matplotlib.pyplot as plt

        try:
            import imageio.v2 as imageio  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "imageio is required for visualize_evolution. "
                "Install with `pip install imageio`."
            ) from exc

        _configure_matplotlib()
        if self.graph.number_of_nodes() == 0:
            raise RuntimeError("Cannot visualize an empty temporal network.")

        start = start_year or self._min_year()
        end = end_year or self._max_year()
        if start is None or end is None or end < start:
            raise RuntimeError("Invalid year range for visualize_evolution.")

        # Pre-compute a stable layout using the final snapshot so nodes
        # don't "jump" between frames.
        final_G = self.snapshot(end)
        try:
            pos = nx.spring_layout(final_G, seed=42, k=0.6)
        except Exception:  # pragma: no cover - defensive
            pos = {n: (0.0, 0.0) for n in final_G.nodes()}

        frames: List[Any] = []
        tmp_dir = tempfile.mkdtemp(prefix="temporal_net_")
        try:
            for year in range(start, end + 1, step):
                G = self.snapshot(year)
                fig, ax = plt.subplots(figsize=(9, 7), constrained_layout=True)
                if G.number_of_nodes() == 0:
                    ax.set_title(f"Year {year} (no data yet)")
                    ax.set_axis_off()
                else:
                    degrees = dict(G.degree())
                    max_deg = max(degrees.values()) if degrees else 1
                    # Avoid division by zero for snapshots that have nodes but no edges.
                    safe_max = max_deg if max_deg > 0 else 1
                    node_sizes = [40 + 500 * (degrees.get(n, 0) / safe_max) for n in G.nodes()]
                    nx.draw_networkx_edges(G, pos, ax=ax, alpha=0.25, edge_color="#888888")
                    nx.draw_networkx_nodes(
                        G, pos, ax=ax, node_size=node_sizes, node_color="#4c78a8", alpha=0.85
                    )
                    ax.set_title(
                        f"Year {year} — {G.number_of_nodes()} nodes, "
                        f"{G.number_of_edges()} edges"
                    )
                    ax.set_axis_off()
                frame_path = os.path.join(tmp_dir, f"frame_{year}.png")
                fig.savefig(frame_path)
                plt.close(fig)
                frames.append(imageio.imread(frame_path))
            if output_path is None:
                fd, output_path = tempfile.mkstemp(prefix="temporal_evolution_", suffix=".gif")
                os.close(fd)
            imageio.mimsave(output_path, frames, fps=fps)
            self.logger.info("Evolution GIF written to %s.", output_path)
            return output_path
        finally:
            # Best-effort cleanup of intermediate frames.
            for f in os.listdir(tmp_dir):
                try:
                    os.remove(os.path.join(tmp_dir, f))
                except OSError:  # pragma: no cover - defensive
                    pass
            try:
                os.rmdir(tmp_dir)
            except OSError:  # pragma: no cover - defensive
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _metrics(G: nx.Graph) -> Dict[str, float]:
        n_nodes = G.number_of_nodes()
        n_edges = G.number_of_edges()
        density = nx.density(G) if n_nodes > 1 else 0.0
        avg_degree = (2 * n_edges / n_nodes) if n_nodes > 0 else 0.0
        try:
            clustering = float(nx.average_clustering(G)) if n_nodes > 0 else 0.0
        except Exception:  # pragma: no cover - defensive
            clustering = 0.0
        return {
            "nodes": float(n_nodes),
            "edges": float(n_edges),
            "density": float(density),
            "avg_degree": float(avg_degree),
            "clustering": float(clustering),
        }
