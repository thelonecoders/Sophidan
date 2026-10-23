"""Chart factory producing publication-quality matplotlib ``Figure`` objects.

This module is part of the Academic Research Suite reporting sub-package.
Every public method returns a fresh ``matplotlib.figure.Figure`` configured
with ``constrained_layout=True`` and CJK-aware font fallback.  Heavy
dependencies (matplotlib, numpy, networkx) are imported lazily inside the
methods so that simply importing this module never raises even if a dep is
unavailable.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from ._paper_utils import (
    calculate_h_index,
    get_affiliation_countries,
    get_authors,
    get_citation_count,
    get_field,
    get_keywords,
    get_str,
    get_year,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Matplotlib global setup.  Applied once on first use; safe to call again.
# ---------------------------------------------------------------------------

# Spec: font.sans-serif must start with 'Noto Sans SC' then 'DejaVu Sans'.
# We append a few extra well-known CJK fallbacks after DejaVu Sans so that
# charts still render Chinese / Japanese / Korean text on systems where the
# Noto Sans SC OpenType/variable font fails to load (common on stock Linux).
_FONT_SANS_SERIF = ["Noto Sans SC", "DejaVu Sans", "WenQuanYi Zen Hei", "LXGW WenKai"]
_DPI = 120
_DEFAULT_FIGSIZE: Tuple[float, float] = (8.0, 5.0)

_MPL_INITIALISED = False


def _init_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (idempotent)."""
    global _MPL_INITIALISED
    if _MPL_INITIALISED:
        return
    try:
        import matplotlib  # noqa: WPS433  (lazy import per project standard)
        matplotlib.use("Agg", force=False)
        import matplotlib.pyplot as plt  # noqa: WPS433
        plt.rcParams["font.sans-serif"] = _FONT_SANS_SERIF
        plt.rcParams["axes.unicode_minus"] = False
        plt.rcParams["figure.dpi"] = _DPI
        plt.rcParams["savefig.dpi"] = _DPI
        plt.rcParams["axes.titlesize"] = 12
        plt.rcParams["axes.labelsize"] = 10
        plt.rcParams["xtick.labelsize"] = 9
        plt.rcParams["ytick.labelsize"] = 9
        plt.rcParams["legend.fontsize"] = 9
        _MPL_INITIALISED = True
        logger.debug("matplotlib rcParams initialised: fonts=%s", _FONT_SANS_SERIF)
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("matplotlib init failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Colour palette (subtle blue accent, consistent with PPTX theme).
# ---------------------------------------------------------------------------
DEFAULT_PALETTE: List[str] = [
    "#2E5C8A",  # primary blue
    "#4A90D9",  # secondary blue
    "#7AB8E5",  # light blue
    "#F5A623",  # amber
    "#7ED321",  # green
    "#D0021B",  # red
    "#9013FE",  # purple
    "#50E3C2",  # teal
    "#B8E986",  # light green
    "#F8E71C",  # yellow
]


class ChartGenerator:
    """Factory class that returns styled matplotlib ``Figure`` objects.

    Every method accepts ``papers`` (a list of Paper-like objects; see
    ``reporting._paper_utils`` for the duck-typed contract) and returns a
    standalone ``Figure`` that can be embedded into a PDF / DOCX / PPTX
    report or saved to disk via :meth:`save_all`.
    """

    def __init__(self, palette: Optional[Sequence[str]] = None) -> None:
        """Initialise the generator.

        Args:
            palette: Optional override colour palette (hex strings).  When
                ``None``, the default blue-accent palette is used.
        """
        _init_matplotlib()
        self.palette: List[str] = list(palette) if palette else list(DEFAULT_PALETTE)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _new_figure(figsize: Optional[Tuple[float, float]] = None):
        """Create a new constrained-layout figure (no tight_layout!)."""
        import matplotlib.pyplot as plt  # noqa: WPS433
        size = figsize or _DEFAULT_FIGSIZE
        fig, ax = plt.subplots(figsize=size, constrained_layout=True, dpi=_DPI)
        return fig, ax

    def _cyclic_colour(self, idx: int) -> str:
        return self.palette[idx % len(self.palette)]

    # ------------------------------------------------------------------
    # Publications over time
    # ------------------------------------------------------------------
    def publications_per_year(
        self, papers: Iterable[Any], cumulative: bool = False
    ):
        """Bar chart of publications per year (optionally cumulative).

        Args:
            papers: Iterable of Paper-like objects.
            cumulative: When ``True``, plot the running total instead of
                per-year counts.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        counts: Dict[int, int] = {}
        for p in papers:
            y = get_year(p)
            if y is None:
                continue
            counts[y] = counts.get(y, 0) + 1
        if not counts:
            return self._empty_figure("No publication year data available")

        years = sorted(counts)
        values = [counts[y] for y in years]
        if cumulative:
            running = 0
            cum_values = []
            for v in values:
                running += v
                cum_values.append(running)
            values = cum_values

        fig, ax = self._new_figure(figsize=(9, 4.5))
        ax.bar(years, values, color=self._cyclic_colour(0), edgecolor="white", linewidth=0.5)
        ax.set_xlabel("Year")
        ax.set_ylabel("Number of Publications" + (" (cumulative)" if cumulative else ""))
        ax.set_title("Publications per Year")
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)
        return fig

    # ------------------------------------------------------------------
    # Citation distribution
    # ------------------------------------------------------------------
    def citations_distribution(self, papers: Iterable[Any], log: bool = True):
        """Histogram of citation counts per paper.

        Args:
            papers: Iterable of Paper-like objects.
            log: When ``True``, use a log scale on the y-axis (recommended
                because citation distributions are heavily right-skewed).
        """
        cites = [get_citation_count(p) for p in papers]
        cites = [c for c in cites if c is not None and c >= 0]
        if not cites:
            return self._empty_figure("No citation data available")

        fig, ax = self._new_figure(figsize=(9, 4.5))
        bins = min(40, max(10, int(len(cites) ** 0.5) * 2))
        ax.hist(cites, bins=bins, color=self._cyclic_colour(1), edgecolor="white")
        if log:
            ax.set_yscale("log")
            ax.set_ylabel("Frequency (log scale)")
        else:
            ax.set_ylabel("Frequency")
        ax.set_xlabel("Citations per Paper")
        ax.set_title("Citation Distribution")
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)
        return fig

    # ------------------------------------------------------------------
    # Top authors
    # ------------------------------------------------------------------
    def top_authors(
        self,
        papers: Iterable[Any],
        n: int = 20,
        metric: str = "papers",
    ):
        """Horizontal bar chart of top authors by chosen metric.

        Args:
            papers: Iterable of Paper-like objects.
            n: Number of top authors to show.
            metric: One of ``'papers'``, ``'citations'``, ``'h_index'``.
        """
        if metric not in {"papers", "citations", "h_index"}:
            raise ValueError(f"metric must be 'papers'|'citations'|'h_index', got {metric!r}")
        stats: Dict[str, Dict[str, Any]] = {}
        for p in papers:
            authors = get_authors(p)
            cites = get_citation_count(p)
            for a in authors:
                if a not in stats:
                    stats[a] = {"papers": 0, "citations": 0, "cite_list": []}
                stats[a]["papers"] += 1
                stats[a]["citations"] += cites
                stats[a]["cite_list"].append(cites)
        if not stats:
            return self._empty_figure("No author data available")

        if metric == "papers":
            ranked = sorted(stats.items(), key=lambda kv: kv[1]["papers"], reverse=True)
            values = [v["papers"] for _, v in ranked[:n]]
            label = "Number of Papers"
        elif metric == "citations":
            ranked = sorted(stats.items(), key=lambda kv: kv[1]["citations"], reverse=True)
            values = [v["citations"] for _, v in ranked[:n]]
            label = "Total Citations"
        else:
            ranked = sorted(
                stats.items(),
                key=lambda kv: calculate_h_index(kv[1]["cite_list"]),
                reverse=True,
            )
            values = [calculate_h_index(v["cite_list"]) for _, v in ranked[:n]]
            label = "h-index"

        top_n = ranked[:n]
        names = [k for k, _ in top_n]
        fig, ax = self._new_figure(figsize=(9, max(4.5, 0.32 * len(names) + 1.5)))
        y_pos = list(range(len(names)))[::-1]
        colors = [self._cyclic_colour(i) for i in range(len(names))]
        ax.barh(y_pos, values, color=colors, edgecolor="white", linewidth=0.5)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names)
        ax.set_xlabel(label)
        ax.set_title(f"Top {len(names)} Authors by {label}")
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)
        return fig

    # ------------------------------------------------------------------
    # Top journals / venues
    # ------------------------------------------------------------------
    def top_journals(self, papers: Iterable[Any], n: int = 20):
        """Horizontal bar chart of top journals/venues by paper count."""
        counts: Dict[str, int] = {}
        for p in papers:
            venue = get_str(p, "journal") or get_str(p, "booktitle")
            if not venue:
                continue
            venue = venue.strip()
            counts[venue] = counts.get(venue, 0) + 1
        if not counts:
            return self._empty_figure("No journal/venue data available")
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:n]
        names = [k for k, _ in ranked]
        values = [v for _, v in ranked]
        fig, ax = self._new_figure(figsize=(9, max(4.5, 0.32 * len(names) + 1.5)))
        y_pos = list(range(len(names)))[::-1]
        colors = [self._cyclic_colour(i) for i in range(len(names))]
        ax.barh(y_pos, values, color=colors, edgecolor="white", linewidth=0.5)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names)
        ax.set_xlabel("Number of Papers")
        ax.set_title(f"Top {len(names)} Journals / Venues")
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)
        return fig

    # ------------------------------------------------------------------
    # Topic model
    # ------------------------------------------------------------------
    def topic_distribution(self, topic_model: Any, n_topics: int = 10):
        """Bar chart of topic sizes from a BERTopic / topic model.

        Args:
            topic_model: Any object exposing ``get_topic_info()`` (BERTopic
                convention) or a mapping ``{topic_id: size}``.
            n_topics: Maximum number of topics to plot.
        """
        sizes: Dict[str, int] = {}
        if hasattr(topic_model, "get_topic_info"):
            try:
                info = topic_model.get_topic_info()
                # BERTopic returns a DataFrame with 'Topic' and 'Count' columns.
                if hasattr(info, "iterrows"):
                    for _, row in info.iterrows():
                        topic = row.get("Topic", row.get("Name"))
                        count = int(row.get("Count", 0))
                        if topic is None or topic == -1:
                            continue
                        sizes[str(topic)] = count
                else:
                    sizes = {str(k): int(v) for k, v in info.items()}
            except Exception as exc:
                logger.warning("topic_model.get_topic_info() failed: %s", exc, exc_info=True)
        elif isinstance(topic_model, dict):
            sizes = {str(k): int(v) for k, v in topic_model.items() if k != -1}
        else:
            return self._empty_figure("Unsupported topic_model type")

        if not sizes:
            return self._empty_figure("No topic distribution data available")
        ranked = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:n_topics]
        names = [k for k, _ in ranked]
        values = [v for _, v in ranked]
        fig, ax = self._new_figure(figsize=(9, max(4.5, 0.32 * len(names) + 1.5)))
        y_pos = list(range(len(names)))[::-1]
        colors = [self._cyclic_colour(i) for i in range(len(names))]
        ax.barh(y_pos, values, color=colors, edgecolor="white", linewidth=0.5)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names)
        ax.set_xlabel("Number of Documents")
        ax.set_title(f"Top {len(names)} Topics")
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)
        return fig

    # ------------------------------------------------------------------
    # Network visualisations
    # ------------------------------------------------------------------
    def collaboration_network(self, networkx_graph: Any, max_nodes: int = 200):
        """Draw a co-authorship / collaboration network with spring layout.

        Args:
            networkx_graph: ``networkx.Graph`` (or any object exposing
                ``nodes`` / ``edges``).
            max_nodes: Cap on the number of nodes drawn (largest-degree first)
                to keep the figure readable.
        """
        try:
            import networkx as nx  # noqa: WPS433
        except ImportError as exc:
            logger.error("networkx not installed: %s", exc)
            return self._empty_figure("networkx not installed")
        g = networkx_graph
        if g is None or g.number_of_nodes() == 0:
            return self._empty_figure("Empty collaboration graph")
        # Subsample to max_nodes by degree.
        if g.number_of_nodes() > max_nodes:
            top = sorted(g.degree, key=lambda kv: kv[1], reverse=True)[:max_nodes]
            keep = [n for n, _ in top]
            g = g.subgraph(keep).copy()
        fig, ax = self._new_figure(figsize=(8, 8))
        pos = nx.spring_layout(g, seed=42, k=0.15)
        degrees = [d for _, d in g.degree()]
        max_deg = max(degrees) if degrees else 1
        node_sizes = [30 + 250 * (d / max_deg if max_deg else 0) for d in degrees]
        nx.draw_networkx_nodes(
            g, pos, node_size=node_sizes, node_color=self._cyclic_colour(0),
            alpha=0.85, ax=ax,
        )
        nx.draw_networkx_edges(
            g, pos, alpha=0.25, edge_color="#888888", ax=ax,
        )
        # Label top-10 by degree only to avoid clutter.
        top_labels = {n: str(n) for n, _ in sorted(g.degree, key=lambda kv: kv[1], reverse=True)[:10]}
        nx.draw_networkx_labels(g, pos, labels=top_labels, font_size=7, ax=ax)
        ax.set_title(
            f"Collaboration Network ({g.number_of_nodes()} nodes, {g.number_of_edges()} edges)"
        )
        ax.set_axis_off()
        return fig

    def citation_network(self, networkx_digraph: Any, max_nodes: int = 200):
        """Draw a citation DiGraph with a spring layout and directed edges."""
        try:
            import networkx as nx  # noqa: WPS433
        except ImportError as exc:
            logger.error("networkx not installed: %s", exc)
            return self._empty_figure("networkx not installed")
        g = networkx_digraph
        if g is None or g.number_of_nodes() == 0:
            return self._empty_figure("Empty citation graph")
        if g.number_of_nodes() > max_nodes:
            # Keep the highest in-degree nodes (most cited).
            top = sorted(g.in_degree, key=lambda kv: kv[1], reverse=True)[:max_nodes]
            keep = [n for n, _ in top]
            g = g.subgraph(keep).copy()
        fig, ax = self._new_figure(figsize=(8, 8))
        pos = nx.spring_layout(g, seed=42, k=0.15)
        in_deg = [d for _, d in g.in_degree()]
        max_deg = max(in_deg) if in_deg else 1
        node_sizes = [30 + 250 * (d / max_deg if max_deg else 0) for d in in_deg]
        # Source nodes (in-degree 0) are amber, cited nodes are blue.
        node_colors = [self._cyclic_colour(3) if d == 0 else self._cyclic_colour(0) for d in in_deg]
        nx.draw_networkx_nodes(
            g, pos, node_size=node_sizes, node_color=node_colors, alpha=0.85, ax=ax,
        )
        nx.draw_networkx_edges(
            g, pos, alpha=0.3, edge_color="#888888",
            arrows=True, arrowsize=8, ax=ax,
        )
        top_labels = {n: str(n) for n, _ in sorted(g.in_degree, key=lambda kv: kv[1], reverse=True)[:10]}
        nx.draw_networkx_labels(g, pos, labels=top_labels, font_size=7, ax=ax)
        ax.set_title(
            f"Citation Network ({g.number_of_nodes()} nodes, {g.number_of_edges()} edges)"
        )
        ax.set_axis_off()
        return fig

    # ------------------------------------------------------------------
    # Geographic distribution
    # ------------------------------------------------------------------
    def geographic_distribution(self, papers: Iterable[Any]):
        """Bar chart of papers per affiliation country.

        Requires Paper objects to expose author affiliation country metadata;
        papers without country data are silently skipped.
        """
        counts: Dict[str, int] = {}
        for p in papers:
            countries = get_affiliation_countries(p)
            # De-duplicate per-paper so a paper with 3 US authors counts once.
            seen = set(c.lower() for c in countries)
            for c in seen:
                if not c:
                    continue
                # Preserve original-case key for display.
                display = next((cc for cc in countries if cc.lower() == c), c)
                counts[display] = counts.get(display, 0) + 1
        if not counts:
            return self._empty_figure("No affiliation country data available")
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        names = [k for k, _ in ranked]
        values = [v for _, v in ranked]
        fig, ax = self._new_figure(figsize=(9, max(4.5, 0.32 * len(names) + 1.5)))
        y_pos = list(range(len(names)))[::-1]
        colors = [self._cyclic_colour(i) for i in range(len(names))]
        ax.barh(y_pos, values, color=colors, edgecolor="white", linewidth=0.5)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names)
        ax.set_xlabel("Number of Papers")
        ax.set_title("Geographic Distribution")
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)
        return fig

    # ------------------------------------------------------------------
    # Heatmap: year x field
    # ------------------------------------------------------------------
    def heatmap_year_vs_field(self, papers: Iterable[Any]):
        """Heatmap of paper counts by publication year (rows) and field (cols).

        Fields are derived from each paper's ``fields_of_study`` /
        ``concepts`` attribute (a list of strings or ``{"name": ...}`` dicts).
        """
        try:
            import numpy as np  # noqa: WPS433
        except ImportError as exc:
            logger.error("numpy not installed: %s", exc)
            return self._empty_figure("numpy not installed")
        rows: Dict[int, Dict[str, int]] = {}
        all_fields: set[str] = set()
        for p in papers:
            y = get_year(p)
            if y is None:
                continue
            fields = get_field(p, "fields_of_study", default=[]) or []
            field_names: List[str] = []
            if isinstance(fields, str):
                field_names = [fields.strip()]
            elif isinstance(fields, Iterable):
                for f in fields:
                    if isinstance(f, str) and f.strip():
                        field_names.append(f.strip())
                    elif isinstance(f, dict):
                        n = f.get("name") or f.get("display_name")
                        if n:
                            field_names.append(str(n).strip())
            if not field_names:
                field_names = ["(unspecified)"]
            rows.setdefault(y, {})
            for fn in field_names:
                all_fields.add(fn)
                rows[y][fn] = rows[y].get(fn, 0) + 1
        if not rows:
            return self._empty_figure("No year/field data available")
        years = sorted(rows)
        # Cap to top 12 fields by total count for readability.
        totals: Dict[str, int] = {}
        for y in years:
            for f, c in rows[y].items():
                totals[f] = totals.get(f, 0) + c
        top_fields = [f for f, _ in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:12]]
        matrix = np.zeros((len(years), len(top_fields)), dtype=int)
        for i, y in enumerate(years):
            for j, f in enumerate(top_fields):
                matrix[i, j] = rows[y].get(f, 0)
        fig, ax = self._new_figure(figsize=(max(7, 0.7 * len(top_fields) + 3), max(5, 0.32 * len(years) + 2)))
        im = ax.imshow(matrix, aspect="auto", cmap="Blues")
        ax.set_xticks(range(len(top_fields)))
        ax.set_xticklabels(top_fields, rotation=45, ha="right")
        ax.set_yticks(range(len(years)))
        ax.set_yticklabels(years)
        ax.set_xlabel("Field of Study")
        ax.set_ylabel("Year")
        ax.set_title("Publications: Year vs Field of Study")
        # Add count annotations.
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                v = matrix[i, j]
                if v > 0:
                    color = "white" if v > matrix.max() * 0.6 else "#222222"
                    ax.text(j, i, str(v), ha="center", va="center", fontsize=7, color=color)
        # constrained_layout handles the colorbar spacing automatically.
        fig.colorbar(im, ax=ax, label="Number of Papers", shrink=0.85)
        return fig

    # ------------------------------------------------------------------
    # Bulk save
    # ------------------------------------------------------------------
    def save_all(
        self,
        figures: Iterable[Any],
        output_dir: str,
        format: str = "png",
    ) -> List[str]:
        """Save a list of figures to ``output_dir`` in the chosen format.

        Args:
            figures: Iterable of matplotlib Figure objects.
            output_dir: Target directory (created if missing).
            format: One of ``'png'``, ``'svg'``, ``'pdf'``.

        Returns:
            A list of saved file paths.
        """
        if format not in {"png", "svg", "pdf"}:
            raise ValueError(f"format must be 'png'|'svg'|'pdf', got {format!r}")
        os.makedirs(output_dir, exist_ok=True)
        saved: List[str] = []
        for i, fig in enumerate(figures):
            path = os.path.join(output_dir, f"chart_{i:03d}.{format}")
            try:
                # CRITICAL: never use bbox_inches='tight' with constrained_layout.
                fig.savefig(path, format=format)
                saved.append(path)
                logger.debug("saved chart -> %s", path)
            except Exception as exc:
                logger.error("failed to save figure %d -> %s: %s", i, path, exc, exc_info=True)
            finally:
                try:
                    import matplotlib.pyplot as plt  # noqa: WPS433
                    plt.close(fig)
                except Exception:
                    pass
        return saved

    # ------------------------------------------------------------------
    # Empty-data placeholder
    # ------------------------------------------------------------------
    @staticmethod
    def _empty_figure(message: str):
        """Return a tiny figure that displays a friendly 'no data' message."""
        _init_matplotlib()
        import matplotlib.pyplot as plt  # noqa: WPS433
        fig, ax = plt.subplots(figsize=(6, 2), constrained_layout=True, dpi=_DPI)
        ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=10, color="#888888")
        ax.set_axis_off()
        return fig


__all__ = ["ChartGenerator", "DEFAULT_PALETTE"]
