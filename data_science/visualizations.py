"""Matplotlib / seaborn helpers for the Academic Research Suite.

Every public function in :class:`Visualizer` returns a
``matplotlib.figure.Figure`` so the caller can embed it into a Qt widget,
export it to disk, or simply display it. All figures are created with
``constrained_layout=True``; ``tight_layout`` is intentionally never used
in tandem.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Matplotlib font setup (Noto Sans SC + DejaVu Sans fallback for CJK)
# ---------------------------------------------------------------------------

def _configure_fonts() -> None:
    """Configure matplotlib rcParams for CJK-aware font fallback."""
    try:
        import matplotlib
        from matplotlib import font_manager
        preferred = ["Noto Sans SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
                     "Microsoft YaHei", "PingFang SC", "SimHei", "DejaVu Sans"]
        available = {f.name for f in font_manager.fontManager.ttflist}
        family = [f for f in preferred if f in available] or ["DejaVu Sans"]
        matplotlib.rcParams["font.family"] = family
        # Avoid 'tofu' boxes for missing glyphs
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Font configuration failed: %s", exc)


_configure_fonts()


def _figure(figsize=(8, 5)):
    """Create a constrained-layout Figure/Axes pair."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    return fig, ax


class Visualizer:
    """Plotting helpers for publication / citation / network data.

    All methods return ``matplotlib.figure.Figure`` objects. Heavy /
    optional dependencies (``wordcloud``, ``geopandas``, ``networkx``
    for some layouts) are imported lazily inside the methods that need
    them.
    """

    def __init__(self) -> None:
        self.logger = logger

    # ------------------------------------------------------------------
    # Time-series style plots
    # ------------------------------------------------------------------

    def plot_publications_per_year(self, df: pd.DataFrame) -> "Figure":  # type: ignore[name-defined]
        """Bar chart of publications per year.

        Args:
            df: DataFrame with a ``year`` column (or a year-indexed
                Series).

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt
        years = self._extract_year_series(df)
        fig, ax = _figure(figsize=(9, 4.5))
        if years.empty:
            ax.text(0.5, 0.5, "No year data", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        counts = years.value_counts().sort_index()
        ax.bar(counts.index.astype(int), counts.values, color="#3a7ca5")
        ax.set_xlabel("Year")
        ax.set_ylabel("Publications")
        ax.set_title("Publications per Year")
        ax.set_xticks(counts.index.astype(int))
        for tick in ax.get_xticklabels():
            tick.set_rotation(45)
            tick.set_ha("right")
        return fig

    def plot_citation_distribution(self, df: pd.DataFrame) -> "Figure":  # type: ignore[name-defined]
        """Log-scale histogram of citation counts.

        Args:
            df: DataFrame with a ``citations_count`` column.

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt
        col = self._find_column(df, ("citations_count", "citations", "cite_count"))
        fig, ax = _figure(figsize=(8, 4.5))
        if col is None:
            ax.text(0.5, 0.5, "No citation data", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        vals = pd.to_numeric(df[col], errors="coerce").dropna()
        if vals.empty:
            ax.text(0.5, 0.5, "No citation data", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        # Use log10(citations + 1)
        log_vals = np.log1p(vals.clip(lower=0))
        ax.hist(log_vals, bins=30, color="#e07a5f", edgecolor="white")
        ax.set_xscale("log")
        ax.set_xlabel("Citations (log scale)")
        ax.set_ylabel("Frequency")
        ax.set_title("Citation Distribution")
        return fig

    # ------------------------------------------------------------------
    # Top-N bar charts
    # ------------------------------------------------------------------

    def plot_top_authors(self, df: pd.DataFrame, n: int = 20) -> "Figure":  # type: ignore[name-defined]
        """Horizontal bar chart of the top-N authors by publication count.

        Args:
            df: DataFrame with an ``authors`` column (delimited string
                or list).
            n: Number of top authors to display.

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt
        from collections import Counter
        col = self._find_column(df, ("authors", "author"))
        fig, ax = _figure(figsize=(8, max(4, 0.3 * n)))
        if col is None:
            ax.text(0.5, 0.5, "No author data", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        counter: Counter = Counter()
        for v in df[col].dropna():
            if isinstance(v, (list, tuple, set, np.ndarray)):
                parts = list(v)
            else:
                import re
                parts = re.split(r"[;,|]", str(v))
            for p in parts:
                p = p.strip()
                if p:
                    counter[p] += 1
        top = counter.most_common(n)
        if not top:
            ax.text(0.5, 0.5, "No author data", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        names = [t[0] for t in top][::-1]
        counts = [t[1] for t in top][::-1]
        ax.barh(names, counts, color="#81b29a")
        ax.set_xlabel("Publications")
        ax.set_title(f"Top {n} Authors")
        return fig

    def plot_top_journals(self, df: pd.DataFrame, n: int = 20) -> "Figure":  # type: ignore[name-defined]
        """Horizontal bar chart of top-N journals / sources.

        Args:
            df: DataFrame with a ``journal``/``source``/``venue`` column.
            n: Number of top journals to display.

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt
        col = self._find_column(df, ("journal", "source", "venue", "publisher"))
        fig, ax = _figure(figsize=(8, max(4, 0.3 * n)))
        if col is None:
            ax.text(0.5, 0.5, "No journal data", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        vc = df[col].astype(str).replace({"nan": None, "None": None, "": None}).dropna()
        top = vc.value_counts().head(n)
        if top.empty:
            ax.text(0.5, 0.5, "No journal data", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        names = list(top.index)[::-1]
        counts = list(top.values)[::-1]
        ax.barh(names, counts, color="#f2cc8f")
        ax.set_xlabel("Publications")
        ax.set_title(f"Top {n} Journals / Sources")
        return fig

    # ------------------------------------------------------------------
    # Network visualization
    # ------------------------------------------------------------------

    def plot_author_collaboration(self, graph: Any) -> "Figure":  # type: ignore[name-defined]
        """Visualize a co-authorship / collaboration network.

        Args:
            graph: A ``networkx.Graph`` of authors.

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt
        try:
            import networkx as nx
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError("networkx is required for collaboration plots") from exc
        fig, ax = _figure(figsize=(9, 9))
        if graph is None or graph.number_of_nodes() == 0:
            ax.text(0.5, 0.5, "Empty graph", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        # Limit to top authors by degree to keep things readable
        if graph.number_of_nodes() > 200:
            top_nodes = sorted(graph.degree, key=lambda x: x[1], reverse=True)[:200]
            keep = {n for n, _ in top_nodes}
            graph = graph.subgraph(keep).copy()
        degrees = dict(graph.degree())
        if not degrees:
            ax.text(0.5, 0.5, "Empty graph", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        pos = nx.spring_layout(graph, seed=42, k=0.15, iterations=50)
        sizes = [max(20, degrees[n] * 6) for n in graph.nodes()]
        edges = graph.edges()
        weights = [graph[u][v].get("weight", 1) for u, v in edges]
        nx.draw_networkx_edges(graph, pos, ax=ax, alpha=0.25, edge_color="#888")
        nx.draw_networkx_nodes(
            graph, pos, ax=ax, node_size=sizes, node_color="#3a7ca5",
            alpha=0.85,
        )
        # Label only the most connected authors
        top_labels = {n: n for n, _ in sorted(degrees.items(),
                                              key=lambda x: x[1], reverse=True)[:20]}
        nx.draw_networkx_labels(graph, pos, labels=top_labels, ax=ax, font_size=8)
        ax.set_title("Author Collaboration Network")
        ax.set_axis_off()
        return fig

    # ------------------------------------------------------------------
    # Topic & wordcloud visualization
    # ------------------------------------------------------------------

    def plot_topic_distribution(self, topic_model: Any) -> "Figure":  # type: ignore[name-defined]
        """Bar chart of topic prevalence across a corpus.

        Args:
            topic_model: A ``TopicModel``-like object exposing either a
                ``doc_topic_matrix`` attribute or a ``topics`` list.

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt
        fig, ax = _figure(figsize=(9, 5))
        dtm = getattr(topic_model, "doc_topic_matrix", None)
        topics = getattr(topic_model, "topics", None) or []
        if dtm is not None and len(dtm) > 0:
            arr = np.asarray(dtm)
            if arr.ndim == 2 and arr.shape[0] > 0:
                prevalence = arr.sum(axis=0)
                labels = [f"Topic {i}" for i in range(len(prevalence))]
                ax.bar(labels, prevalence, color="#3a7ca5")
                ax.set_ylabel("Aggregated weight")
                ax.set_title("Topic Distribution")
                for tick in ax.get_xticklabels():
                    tick.set_rotation(45)
                    tick.set_ha("right")
                return fig
        # Fallback: list topic top words
        if isinstance(topics, list) and topics:
            labels = [f"Topic {i}" for i in range(len(topics))]
            counts = [len(t.get("words", [])) if isinstance(t, dict) else 0 for t in topics]
            ax.bar(labels, counts, color="#81b29a")
            ax.set_ylabel("# top words")
            ax.set_title("Topic Word Counts")
            for tick in ax.get_xticklabels():
                tick.set_rotation(45)
                tick.set_ha("right")
            return fig
        ax.text(0.5, 0.5, "No topic data", ha="center", va="center",
                transform=ax.transAxes)
        return fig

    def plot_word_cloud(self, texts: Iterable[str]) -> "Figure":  # type: ignore[name-defined]
        """Render a word cloud from a corpus of texts.

        Args:
            texts: Iterable of input strings.

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt
        try:
            from wordcloud import WordCloud
        except Exception as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "wordcloud is required for plot_word_cloud"
            ) from exc
        text = " ".join(t for t in texts if isinstance(t, str))
        fig, ax = _figure(figsize=(9, 5))
        if not text.strip():
            ax.text(0.5, 0.5, "No text to display", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        wc = WordCloud(
            width=900, height=500, background_color="white",
            max_words=200, random_state=42,
        ).generate(text)
        ax.imshow(wc, interpolation="bilinear")
        ax.set_axis_off()
        ax.set_title("Word Cloud")
        return fig

    def plot_geographic_distribution(self, papers: Sequence[Any]) -> "Figure":  # type: ignore[name-defined]
        """Choropleth of publications by country.

        Args:
            papers: Sequence of Paper objects (or dicts) that may expose a
                ``country`` / ``affiliation_country`` attribute.

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt
        try:
            import geopandas as gpd
        except Exception as exc:  # pragma: no cover - optional dep
            raise RuntimeError(
                "geopandas is required for plot_geographic_distribution"
            ) from exc
        # Extract country from each paper
        from collections import Counter
        counter: Counter = Counter()
        for paper in papers:
            d = paper if isinstance(paper, dict) else self._paper_to_dict(paper)
            country = (
                d.get("country")
                or d.get("affiliation_country")
                or d.get("country_code")
            )
            if country:
                counter[str(country).strip()] += 1
        fig, ax = _figure(figsize=(10, 6))
        if not counter:
            ax.text(0.5, 0.5, "No country data", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        try:
            # Use Natural Earth low-res dataset bundled with geopandas
            world = gpd.read_file(gpd.datasets.get_path("naturalearth_lowres")) \
                if hasattr(gpd.datasets, "get_path") else gpd.datasets.get_path("naturalearth_lowres")
            if isinstance(world, str):
                world = gpd.read_file(world)
        except Exception:
            try:
                world = gpd.read_file("naturalearth_lowres")
            except Exception as exc:
                self.logger.warning("geopandas world dataset unavailable: %s", exc)
                ax.text(0.5, 0.5, "World geometry unavailable",
                        ha="center", va="center", transform=ax.transAxes)
                return fig
        # Map counts onto the world
        name_col = "name" if "name" in world.columns else (
            "NAME" if "NAME" in world.columns else None
        )
        iso_col = "iso_a3" if "iso_a3" in world.columns else None
        world["count"] = 0
        for country, c in counter.items():
            mask = (
                (world[name_col].astype(str).str.lower() == country.lower())
                if name_col else pd.Series([False] * len(world))
            ) | (
                (world[iso_col].astype(str).str.upper() == country.upper())
                if iso_col else pd.Series([False] * len(world))
            )
            world.loc[mask, "count"] = c
        world.plot(
            column="count", ax=ax, legend=True,
            cmap="OrRd", missing_kwds={"color": "lightgrey", "label": "No data"},
        )
        ax.set_title("Geographic Distribution of Publications")
        ax.set_axis_off()
        return fig

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_column(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    @staticmethod
    def _extract_year_series(df: Any) -> pd.Series:
        if isinstance(df, pd.Series):
            return df.dropna().astype(int) if df.name == "year" else pd.to_numeric(df, errors="coerce").dropna()
        if isinstance(df, pd.DataFrame):
            col = None
            for c in ("year", "Year", "publication_year"):
                if c in df.columns:
                    col = c
                    break
            if col is None:
                return pd.Series([], dtype=int)
            return pd.to_numeric(df[col], errors="coerce").dropna()
        return pd.Series([], dtype=int)

    @staticmethod
    def _paper_to_dict(paper: Any) -> dict:
        if isinstance(paper, dict):
            return dict(paper)
        try:
            from dataclasses import asdict, is_dataclass
            if is_dataclass(paper) and not isinstance(paper, type):
                return asdict(paper)
        except Exception:
            pass
        out = {}
        for attr in ("title", "authors", "abstract", "year", "doi",
                     "citations_count", "references", "keywords",
                     "fields_of_study", "country", "affiliation_country",
                     "country_code", "journal", "source", "venue"):
            if hasattr(paper, attr):
                out[attr] = getattr(paper, attr)
        return out
