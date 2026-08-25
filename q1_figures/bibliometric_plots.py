"""Bibliometric-specific visualizations.

The :class:`BibliometricPlots` class produces matplotlib Figures (not
plain Axes — many of these plots need multi-panel layouts or colourbars
that are easier to manage as standalone Figures) for the classic
bibliometric distributions:

* :meth:`lotka_curve` — productivity distribution (log-log).
* :meth:`bradford_curve` — Bradford's law zones.
* :meth:`zipf_law_plot` — term frequency rank-frequency.
* :meth:`growth_curve` — exponential / logistic growth fit.
* :meth:`citation_distribution` — citation histogram.
* :meth:`h_index_curve` — h-index visualisation.
* :meth:`impact_factor_distribution` — IF per journal.
* :meth:`author_collaboration_heatmap` — co-authorship matrix.
* :meth:`citation_network_graph` — citation network top-N.
* :meth:`topic_evolution_streamgraph` — topic flow over time.
* :meth:`overlay_visualization` — VOSviewer-style overlay.
* :meth:`co_word_map` — co-occurrence map.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .palettes import JournalPalettes

logger = logging.getLogger(__name__)


def _palette(name_or_list: Union[str, Sequence[str]]) -> List[str]:
    if isinstance(name_or_list, str):
        try:
            return JournalPalettes.get(name_or_list)
        except KeyError:
            return JournalPalettes.NATURE
    return list(name_or_list)


def _new_fig(figsize=(6, 4), dpi: int = 120):
    import matplotlib.pyplot as plt
    return plt.subplots(figsize=figsize, constrained_layout=True, dpi=dpi)


class BibliometricPlots:
    """Bibliometric-specific publication-grade figures."""

    # ------------------------------------------------------------------
    # Lotka / Bradford / Zipf
    # ------------------------------------------------------------------
    @staticmethod
    def lotka_curve(author_paper_counts: Sequence[int]):
        """Lotka productivity distribution (log-log)."""
        import numpy as np
        counts = Counter(author_paper_counts)
        xs = np.array(sorted(counts.keys()))
        ys = np.array([counts[x] for x in xs], dtype=float)
        fig, ax = _new_fig()
        colors = JournalPalettes.NATURE
        ax.scatter(xs, ys, s=30, color=colors[0], edgecolors="black",
                   linewidths=0.3)
        # Fit log-log regression
        if len(xs) >= 2:
            log_x = np.log10(xs)
            log_y = np.log10(ys)
            try:
                slope, intercept = np.polyfit(log_x, log_y, 1)
                fit_y = 10 ** (slope * log_x + intercept)
                ax.plot(xs, fit_y, color=colors[3], linestyle="--",
                        linewidth=0.8,
                        label=f"Slope = {slope:.3f}")
                ax.legend(loc="upper right", frameon=False, fontsize=7)
            except Exception as exc:
                logger.debug("Lotka fit skipped: %s", exc)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Number of papers per author")
        ax.set_ylabel("Number of authors")
        ax.set_title("Lotka's Law — Author Productivity Distribution")
        return fig

    @staticmethod
    def bradford_curve(journal_paper_counts: Sequence[int]):
        """Bradford's law zones — cumulative-paper vs journal-rank curve."""
        import numpy as np
        sorted_counts = sorted(journal_paper_counts, reverse=True)
        ranks = np.arange(1, len(sorted_counts) + 1)
        cumulative = np.cumsum(sorted_counts)
        total = cumulative[-1] if len(cumulative) else 1
        # Bradford zones: zone 1 (core) ≈ 1/3 of papers, zone 2 ≈ 2/3,
        # zone 3 = rest.
        zone1 = int(np.searchsorted(cumulative, total / 3.0)) + 1
        zone2 = int(np.searchsorted(cumulative, 2 * total / 3.0)) + 1
        fig, ax = _new_fig()
        colors = JournalPalettes.NATURE
        ax.plot(ranks, cumulative, color=colors[0], linewidth=1.0)
        ax.axvline(zone1, color=colors[2], linestyle="--", linewidth=0.5,
                   label=f"Zone 1 (core, ≤{zone1})")
        ax.axvline(zone2, color=colors[1], linestyle="--", linewidth=0.5,
                   label=f"Zone 2 (≤{zone2})")
        ax.set_xlabel("Journal rank (by paper count)")
        ax.set_ylabel("Cumulative number of papers")
        ax.set_title("Bradford's Law — Journal Productivity Zones")
        ax.legend(loc="lower right", frameon=False, fontsize=7)
        return fig

    @staticmethod
    def zipf_law_plot(term_frequencies: Sequence[Tuple[str, int]]):
        """Zipf's law — term frequency vs rank (log-log)."""
        import numpy as np
        if not term_frequencies:
            fig, ax = _new_fig()
            ax.text(0.5, 0.5, "No term data available", ha="center",
                    va="center", color="#888888")
            return fig
        sorted_terms = sorted(term_frequencies, key=lambda kv: kv[1], reverse=True)
        ranks = np.arange(1, len(sorted_terms) + 1)
        freqs = np.array([f for _, f in sorted_terms], dtype=float)
        fig, ax = _new_fig()
        colors = JournalPalettes.NATURE
        ax.loglog(ranks, freqs, marker="o", markersize=3, linestyle="none",
                   color=colors[0])
        # Fit Zipf's law: f ∝ 1/r
        try:
            log_r = np.log10(ranks)
            log_f = np.log10(freqs)
            slope, intercept = np.polyfit(log_r, log_f, 1)
            fit = 10 ** (slope * log_r + intercept)
            ax.plot(ranks, fit, color=colors[3], linestyle="--",
                    linewidth=0.8, label=f"Slope = {slope:.3f}")
            ax.legend(loc="upper right", frameon=False, fontsize=7)
        except Exception as exc:
            logger.debug("Zipf fit skipped: %s", exc)
        # Label top 5 terms
        for i in range(min(5, len(sorted_terms))):
            ax.annotate(sorted_terms[i][0], (ranks[i], freqs[i]),
                         fontsize=6, ha="left", va="bottom",
                         xytext=(3, 3), textcoords="offset points")
        ax.set_xlabel("Rank")
        ax.set_ylabel("Frequency")
        ax.set_title("Zipf's Law — Term Frequency Distribution")
        return fig

    # ------------------------------------------------------------------
    # Growth / citation / h-index / impact factor
    # ------------------------------------------------------------------
    @staticmethod
    def growth_curve(papers_per_year: Sequence[Tuple[int, int]]):
        """Growth curve with exponential + logistic fits.

        Args:
            papers_per_year: List of ``(year, count)`` tuples.
        """
        import numpy as np
        if not papers_per_year:
            fig, ax = _new_fig()
            ax.text(0.5, 0.5, "No year data available", ha="center",
                    va="center", color="#888888")
            return fig
        years = np.array([y for y, _ in papers_per_year])
        counts = np.array([c for _, c in papers_per_year], dtype=float)
        cumulative = np.cumsum(counts)
        fig, ax = _new_fig(figsize=(7, 4))
        colors = JournalPalettes.NATURE
        ax.plot(years, cumulative, marker="o", markersize=4, linewidth=1.0,
                color=colors[0], label="Cumulative")
        ax.bar(years, counts, alpha=0.3, color=colors[1], label="Per year")
        # Exponential fit (log-linear)
        try:
            mask = counts > 0
            if mask.sum() >= 2:
                log_y = np.log(counts[mask])
                slope, intercept = np.polyfit(years[mask] - years.min(), log_y, 1)
                fit = np.exp(intercept) * np.exp(slope * (years - years.min()))
                ax.plot(years, fit, color=colors[3], linestyle="--",
                        linewidth=0.8,
                        label=f"Exp fit (k={slope:.3f}/yr)")
        except Exception as exc:
            logger.debug("Growth fit skipped: %s", exc)
        ax.set_xlabel("Year")
        ax.set_ylabel("Number of papers")
        ax.set_title("Literature Growth Curve")
        ax.legend(loc="upper left", frameon=False, fontsize=7)
        return fig

    @staticmethod
    def citation_distribution(
        paper_citation_counts: Sequence[int],
        log_scale: bool = True,
    ):
        """Histogram of citations per paper."""
        import numpy as np
        fig, ax = _new_fig()
        colors = JournalPalettes.NATURE
        arr = np.asarray(paper_citation_counts, dtype=float)
        bins = min(50, max(10, int(len(arr) ** 0.5)))
        ax.hist(arr, bins=bins, color=colors[1], edgecolor="white",
                linewidth=0.4)
        if log_scale:
            ax.set_yscale("log")
        ax.set_xlabel("Citations per paper")
        ax.set_ylabel("Number of papers" + (" (log)" if log_scale else ""))
        ax.set_title("Citation Distribution")
        return fig

    @staticmethod
    def h_index_curve(citations_sorted: Sequence[int]):
        """h-index visualisation — citations sorted desc vs rank."""
        import numpy as np
        arr = sorted(citations_sorted, reverse=True)
        ranks = np.arange(1, len(arr) + 1)
        cites = np.array(arr)
        h_index = 0
        for i, c in enumerate(arr, 1):
            if c >= i:
                h_index = i
            else:
                break
        fig, ax = _new_fig()
        colors = JournalPalettes.NATURE
        ax.bar(ranks, cites, color=colors[0], edgecolor="white",
               linewidth=0.4, label="Citations")
        # y = x line for h-index identification
        ax.plot([0, len(arr) + 1], [0, len(arr) + 1], color="black",
                linestyle="--", linewidth=0.5, label="y = x")
        ax.axvline(h_index, color=colors[2], linestyle=":", linewidth=0.8,
                   label=f"h = {h_index}")
        ax.set_xlabel("Rank")
        ax.set_ylabel("Citations")
        ax.set_title(f"h-index Curve (h = {h_index})")
        ax.legend(loc="upper right", frameon=False, fontsize=7)
        return fig

    @staticmethod
    def impact_factor_distribution(
        journals: Sequence[str],
        if_values: Sequence[float],
    ):
        """Bar chart of impact factors per journal (top-N by IF)."""
        import numpy as np
        pairs = sorted(zip(journals, if_values), key=lambda kv: kv[1], reverse=True)
        if not pairs:
            fig, ax = _new_fig()
            ax.text(0.5, 0.5, "No impact factor data available",
                    ha="center", va="center", color="#888888")
            return fig
        names = [n for n, _ in pairs]
        ifs = [v for _, v in pairs]
        fig, ax = _new_fig(figsize=(7, max(3, 0.3 * len(names))))
        colors = JournalPalettes.NATURE
        y_pos = list(range(len(names)))[::-1]
        ax.barh(y_pos, ifs, color=colors[0], edgecolor="white", linewidth=0.4)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, fontsize=7)
        ax.set_xlabel("Impact Factor")
        ax.set_title("Journal Impact Factor Distribution")
        # Annotate the IF on each bar
        for i, v in enumerate(ifs):
            ax.text(v + 0.1, y_pos[i], f"{v:.1f}", va="center", fontsize=6)
        return fig

    # ------------------------------------------------------------------
    # Collaboration / network
    # ------------------------------------------------------------------
    @staticmethod
    def author_collaboration_heatmap(co_authorship_matrix):
        """Heatmap of a co-authorship matrix."""
        import numpy as np
        fig, ax = _new_fig(figsize=(6, 6))
        mat = np.asarray(co_authorship_matrix)
        try:
            cmap = JournalPalettes.as_cmap("viridis")
        except KeyError:
            from matplotlib.cm import viridis as cmap  # type: ignore
        im = ax.imshow(mat, cmap=cmap, aspect="equal")
        n = mat.shape[0]
        ax.set_xticks(range(n))
        ax.set_xticklabels([f"A{i + 1}" for i in range(n)], fontsize=6,
                           rotation=45, ha="right")
        ax.set_yticks(range(n))
        ax.set_yticklabels([f"A{i + 1}" for i in range(n)], fontsize=6)
        fig.colorbar(im, ax=ax, shrink=0.7, label="Co-authorship count")
        ax.set_title("Author Collaboration Heatmap")
        return fig

    @staticmethod
    def citation_network_graph(citation_graph, top_n: int = 50):
        """Visualise a citation network — top-N most-cited nodes."""
        import matplotlib.pyplot as plt
        import networkx as nx
        from .network_plots import Q1NetworkPlots
        # If the graph is large, take the top-N subgraph.
        if citation_graph.number_of_nodes() > top_n:
            try:
                deg = dict(citation_graph.in_degree()) if citation_graph.is_directed() else dict(citation_graph.degree())
                top_nodes = sorted(deg, key=lambda n: deg[n], reverse=True)[:top_n]
                sub = citation_graph.subgraph(top_nodes).copy()
            except Exception as exc:
                logger.debug("Subgraph extraction failed: %s", exc)
                sub = citation_graph
        else:
            sub = citation_graph
        return Q1NetworkPlots.network_figure(
            sub, layout="spring", palette="nature",
            label_top_n=10, figsize=(5, 5), dpi=120,
        )

    # ------------------------------------------------------------------
    # Topic evolution / overlay / co-word
    # ------------------------------------------------------------------
    @staticmethod
    def topic_evolution_streamgraph(
        topic_evolution_data: Dict[str, Sequence[float]],
    ):
        """Streamgraph of topic prevalence over time.

        Args:
            topic_evolution_data: ``{topic_name: [counts_per_year...]}``.
                All arrays must be the same length.
        """
        import numpy as np
        topics = list(topic_evolution_data.keys())
        if not topics:
            fig, ax = _new_fig()
            ax.text(0.5, 0.5, "No topic data available", ha="center",
                    va="center", color="#888888")
            return fig
        n_years = max(len(v) for v in topic_evolution_data.values())
        data_arr = np.zeros((len(topics), n_years))
        for i, t in enumerate(topics):
            arr = np.asarray(topic_evolution_data[t], dtype=float)
            data_arr[i, :len(arr)] = arr
        years = list(range(n_years))
        fig, ax = _new_fig(figsize=(8, 4))
        colors = JournalPalettes.NATURE
        # Streamgraph = stacked area chart, centred vertically.
        totals = data_arr.sum(axis=0)
        half_totals = totals / 2.0
        pos = half_totals.copy()
        neg = half_totals.copy()
        for i, t in enumerate(topics):
            upper = pos + data_arr[i]
            lower = neg - data_arr[i]
            ax.fill_between(years, lower, upper, color=colors[i % len(colors)],
                            alpha=0.7, label=t, linewidth=0.0)
            pos = upper
            neg = lower
        ax.set_xlabel("Year")
        ax.set_ylabel("Topic prevalence (centred)")
        ax.set_title("Topic Evolution Streamgraph")
        ax.legend(loc="best", frameon=False, fontsize=6, ncol=min(3, len(topics)))
        return fig

    @staticmethod
    def overlay_visualization(
        graph,
        attribute: str,
        time_attr: str = "year",
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """VOSviewer-style overlay — node colour encodes an attribute.

        Args:
            graph: NetworkX graph.  Each node must have a ``attribute``
                key in its data dict (e.g. ``'citations'`` or
                ``'year'``).
            attribute: Node attribute to encode as colour.
            time_attr: Optional secondary attribute used for tooltip;
                not directly plotted.
            palette: Palette name (only the first colour is used as
                the low end of a sequential colormap).
        """
        import matplotlib.pyplot as plt
        import networkx as nx
        import numpy as np
        from .network_plots import Q1NetworkPlots
        try:
            cmap = JournalPalettes.as_cmap("viridis")
        except KeyError:
            from matplotlib.cm import viridis as cmap  # type: ignore
        pos = Q1NetworkPlots._layout(graph, "spring")  # noqa: SLF001
        # Get attribute per node
        values = [d.get(attribute, 0) for _, d in graph.nodes(data=True)]
        if not values:
            fig, ax = plt.subplots(figsize=(5, 5), constrained_layout=True,
                                   dpi=120)
            ax.set_axis_off()
            return fig
        vmin, vmax = min(values), max(values)
        deg = dict(graph.degree())
        max_deg = max(deg.values()) if deg else 1
        sizes = [20 + 200 * deg.get(n, 0) / max(max_deg, 1) for n in graph.nodes()]
        fig, ax = plt.subplots(figsize=(6, 6), constrained_layout=True, dpi=120)
        nx.draw_networkx_edges(graph, pos, ax=ax, alpha=0.3, width=0.4,
                                edge_color="#888888")
        nodes = nx.draw_networkx_nodes(
            graph, pos, ax=ax, node_size=sizes,
            node_color=values, cmap=cmap, vmin=vmin, vmax=vmax,
            edgecolors="black", linewidths=0.3,
        )
        # Label top 10 by attribute value
        order = sorted(range(len(values)), key=lambda i: values[i], reverse=True)[:10]
        node_list = list(graph.nodes())
        labels = {node_list[i]: str(node_list[i]) for i in order}
        nx.draw_networkx_labels(graph, pos, labels=labels, ax=ax,
                                 font_size=6, font_color="black")
        sm = plt.cm.ScalarMappable(cmap=cmap,
                                     norm=plt.Normalize(vmin=vmin, vmax=vmax))
        sm.set_array([])
        cb = fig.colorbar(sm, ax=ax, shrink=0.7)
        cb.set_label(attribute, fontsize=8)
        ax.set_axis_off()
        ax.set_title(f"VOSviewer-style overlay ({attribute})")
        return fig

    @staticmethod
    def co_word_map(
        co_occurrence_matrix,
        palette: Union[str, Sequence[str]] = "nature",
        top_n: int = 100,
    ):
        """Co-word map — spring layout sized by frequency, edges by co-occurrence."""
        import matplotlib.pyplot as plt
        import networkx as nx
        import numpy as np
        from .network_plots import Q1NetworkPlots
        mat = np.asarray(co_occurrence_matrix)
        n = mat.shape[0]
        if mat.shape[0] != mat.shape[1]:
            raise ValueError("co_occurrence_matrix must be square")
        G = nx.Graph()
        # Add nodes; node weight = row sum
        for i in range(n):
            G.add_node(i, weight=float(mat[i].sum()))
        # Add edges for non-zero co-occurrences
        for i in range(n):
            for j in range(i + 1, n):
                if mat[i, j] > 0:
                    G.add_edge(i, j, weight=float(mat[i, j]))
        # Top-N by weight
        if G.number_of_nodes() > top_n:
            keep = sorted(G.nodes, key=lambda n_: G.nodes[n_]["weight"],
                           reverse=True)[:top_n]
            G = G.subgraph(keep).copy()
        pos = Q1NetworkPlots._layout(G, "spring")
        weights = [G.nodes[n_]["weight"] for n_ in G.nodes()]
        max_w = max(weights) if weights else 1
        sizes = [50 + 300 * w / max(max_w, 1e-12) for w in weights]
        colors = _palette(palette)
        # Colour by degree-rank
        deg = dict(G.degree())
        sorted_nodes = sorted(G.nodes, key=lambda n_: deg.get(n_, 0), reverse=True)
        color_map = {n_: colors[i % len(colors)] for i, n_ in enumerate(sorted_nodes)}
        node_colors = [color_map[n_] for n_ in G.nodes()]
        fig, ax = plt.subplots(figsize=(6, 6), constrained_layout=True, dpi=120)
        nx.draw_networkx_edges(G, pos, ax=ax, alpha=0.3, width=0.4,
                                edge_color="#888888")
        nx.draw_networkx_nodes(G, pos, ax=ax, node_size=sizes,
                                node_color=node_colors,
                                edgecolors="black", linewidths=0.3)
        # Label top 15 by weight
        top = sorted(G.nodes, key=lambda n_: G.nodes[n_]["weight"], reverse=True)[:15]
        labels = {n_: f"Term {n_}" for n_ in top}
        nx.draw_networkx_labels(G, pos, labels=labels, ax=ax,
                                 font_size=6, font_color="black")
        ax.set_axis_off()
        ax.set_title("Co-word Map")
        return fig
