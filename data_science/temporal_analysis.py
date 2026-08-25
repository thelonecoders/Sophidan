"""Temporal / longitudinal analysis of publication corpora.

The :class:`TemporalAnalyzer` consumes a list of Paper objects and produces
yearly publication / citation series, topic-evolution overlays, lists of
trending topics & emerging authors, and simple ARIMA forecasts of future
publication volume.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import Any, List, Optional, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_PAPER_FIELDS = (
    "title", "authors", "abstract", "year", "doi",
    "citations_count", "references", "keywords", "fields_of_study",
)


def _paper_to_dict(paper: Any) -> dict:
    """Coerce a Paper-like object to a dict."""
    if isinstance(paper, dict):
        return dict(paper)
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(paper) and not isinstance(paper, type):
            return asdict(paper)
    except Exception:
        pass
    out = {f: getattr(paper, f, None) for f in _PAPER_FIELDS}
    for opt in ("journal", "source", "venue", "publisher"):
        if hasattr(paper, opt):
            out[opt] = getattr(paper, opt)
    return out


def _coerce_authors(value: Any) -> List[str]:
    """Return a list of author names from a Paper authors field."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(a).strip() for a in value if a and str(a).strip()]
    if isinstance(value, np.ndarray):
        return [str(a).strip() for a in value.tolist() if a]
    if isinstance(value, str):
        return [p.strip() for p in re.split(r"[;,|]", value) if p.strip()]
    try:
        return [str(a).strip() for a in list(value) if a]
    except TypeError:
        return [str(value).strip()] if value else []


class TemporalAnalyzer:
    """Longitudinal analysis of publication corpora.

    Produces yearly publication / citation series, topic-evolution
    overlays, trending-topic lists, emerging-author detection, and
    ARIMA-based forecasts.
    """

    def __init__(self, papers: List[Any]) -> None:
        """Initialize the analyzer.

        Args:
            papers: List of Paper objects.
        """
        self.papers: List[dict] = [_paper_to_dict(p) for p in papers]
        self.logger = logger
        self._df: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def df(self) -> pd.DataFrame:
        """Lazily build a tidy DataFrame of papers."""
        if self._df is None:
            records = []
            for p in self.papers:
                rec = {
                    "year": pd.to_numeric(p.get("year"), errors="coerce"),
                    "citations_count": pd.to_numeric(
                        p.get("citations_count"), errors="coerce"
                    ),
                    "authors": _coerce_authors(p.get("authors")),
                    "title": p.get("title") or "",
                    "abstract": p.get("abstract") or "",
                    "keywords": _coerce_authors(p.get("keywords")),
                    "doi": p.get("doi"),
                }
                records.append(rec)
            df = pd.DataFrame(records)
            df = df.dropna(subset=["year"]).copy()
            df["year"] = df["year"].astype(int)
            df["citations_count"] = df["citations_count"].fillna(0).astype(int)
            self._df = df
        return self._df

    # ------------------------------------------------------------------
    # Basic yearly series
    # ------------------------------------------------------------------

    def publications_per_year(self) -> pd.Series:
        """Return a Series of publication counts indexed by year."""
        df = self.df
        if df.empty:
            return pd.Series(dtype=int)
        s = df.groupby("year").size().sort_index()
        s.name = "publications"
        return s

    def citations_per_year(self) -> pd.Series:
        """Return a Series of total citations indexed by year."""
        df = self.df
        if df.empty:
            return pd.Series(dtype=int)
        s = df.groupby("year")["citations_count"].sum().sort_index()
        s.name = "citations"
        return s

    # ------------------------------------------------------------------
    # Topic evolution
    # ------------------------------------------------------------------

    def topic_evolution(
        self, num_topics: int = 10, year_bins: int = 5
    ) -> dict:
        """Estimate topic prevalence over time.

        Bins papers into ``year_bins``-year intervals, fits a topic model
        on the entire corpus, then computes the mean topic weight per bin.

        Args:
            num_topics: Number of topics to extract.
            year_bins: Width (in years) of each time bin.

        Returns:
            Dict with keys:
            ``bin_edges`` (list of years),
            ``topics`` (list of topic dicts, each containing ``id`` and
            ``top_words``),
            ``matrix`` (``np.ndarray`` of shape ``(n_bins, n_topics)``).
        """
        df = self.df
        if df.empty:
            return {"bin_edges": [], "topics": [], "matrix": np.zeros((0, 0))}
        # Lazy import to avoid circular dependency
        from .topic_modeler import TopicModeler, _paper_to_text  # type: ignore

        modeler = TopicModeler(method="nmf", n_top_words=10)
        topic_model = modeler.fit(list(df.itertuples(index=False, name="Paper")),
                                  num_topics=num_topics)
        dtm = topic_model.doc_topic_matrix
        if dtm is None or dtm.shape[0] != len(df):
            return {"bin_edges": [], "topics": [], "matrix": np.zeros((0, 0))}

        years = df["year"].to_numpy()
        y_min = int(years.min())
        y_max = int(years.max())
        edges = list(range(y_min, y_max + 2, max(1, year_bins)))
        if len(edges) < 2:
            edges = [y_min, y_max + 1]
        n_bins = len(edges) - 1
        n_topics = dtm.shape[1]
        matrix = np.zeros((n_bins, n_topics), dtype=np.float32)
        counts = np.zeros(n_bins, dtype=np.int64)
        for i in range(len(df)):
            y = int(years[i])
            b = min(n_bins - 1, max(0, (y - y_min) // max(1, year_bins)))
            matrix[b] += dtm[i]
            counts[b] += 1
        # Normalize per bin
        for b in range(n_bins):
            if counts[b] > 0:
                matrix[b] = matrix[b] / counts[b]
        topics = [
            {"id": t.get("id", i), "top_words": t.get("top_words", [])}
            for i, t in enumerate(topic_model.topics)
        ]
        return {
            "bin_edges": edges,
            "topics": topics,
            "matrix": matrix,
        }

    def trending_topics(self, window: int = 3) -> List[dict]:
        """Identify topics whose prevalence has accelerated recently.

        Compares the mean topic weight in the last ``window`` years
        against the prior window of equal length, then ranks by relative
        growth.

        Args:
            window: Number of years defining the "recent" window.

        Returns:
            List of dicts: ``topic_id``, ``top_words``,
            ``recent_mean``, ``prior_mean``, ``growth`` (relative change).
        """
        df = self.df
        if df.empty:
            return []
        from .topic_modeler import TopicModeler  # type: ignore

        modeler = TopicModeler(method="nmf", n_top_words=10)
        topic_model = modeler.fit(list(df.itertuples(index=False, name="Paper")),
                                  num_topics=10)
        dtm = topic_model.doc_topic_matrix
        if dtm is None or dtm.shape[0] != len(df):
            return []
        years = df["year"].to_numpy()
        y_max = int(years.max())
        recent_start = y_max - window + 1
        prior_start = recent_start - window
        recent_mask = years >= recent_start
        prior_mask = (years >= prior_start) & (years < recent_start)
        out: List[dict] = []
        for t in range(dtm.shape[1]):
            recent_mean = float(dtm[recent_mask, t].mean()) if recent_mask.any() else 0.0
            prior_mean = float(dtm[prior_mask, t].mean()) if prior_mask.any() else 0.0
            growth = (
                (recent_mean - prior_mean) / prior_mean
                if prior_mean > 0 else (1.0 if recent_mean > 0 else 0.0)
            )
            out.append({
                "topic_id": topic_model.topics[t].get("id", t) if t < len(topic_model.topics) else t,
                "top_words": (
                    topic_model.topics[t].get("top_words", [])
                    if t < len(topic_model.topics) else []
                ),
                "recent_mean": recent_mean,
                "prior_mean": prior_mean,
                "growth": growth,
            })
        out.sort(key=lambda x: x["growth"], reverse=True)
        return out

    def emerging_authors(self, year_threshold: int = 2020) -> List[dict]:
        """Detect authors whose first publication is at or after ``year_threshold``.

        Args:
            year_threshold: Inclusive cut-off year defining "emerging".

        Returns:
            List of dicts: ``author``, ``first_year``, ``papers``,
            ``total_citations``, ``avg_citations``.
        """
        df = self.df
        if df.empty:
            return []
        first_year: dict[str, int] = {}
        paper_count: Counter = Counter()
        cite_sum: dict[str, int] = defaultdict(int)
        for _, row in df.iterrows():
            for a in row["authors"]:
                if not a:
                    continue
                paper_count[a] += 1
                cite_sum[a] += int(row["citations_count"])
                y = int(row["year"])
                if a not in first_year or y < first_year[a]:
                    first_year[a] = y
        out: List[dict] = []
        for a, fy in first_year.items():
            if fy >= year_threshold:
                pc = paper_count[a]
                tc = cite_sum[a]
                out.append({
                    "author": a,
                    "first_year": fy,
                    "papers": pc,
                    "total_citations": tc,
                    "avg_citations": (tc / pc) if pc else 0.0,
                })
        out.sort(key=lambda x: (-x["papers"], -x["total_citations"], x["author"]))
        return out

    # ------------------------------------------------------------------
    # Forecasting
    # ------------------------------------------------------------------

    def forecast(self, years_ahead: int = 3) -> pd.Series:
        """Forecast future publication volume with ARIMA.

        Args:
            years_ahead: Number of years to forecast.

        Returns:
            A pandas Series indexed by year, containing both the
            observed values and the forecast horizon. If statsmodels is
            unavailable, falls back to a linear-trend extrapolation.
        """
        s = self.publications_per_year()
        if s.empty or len(s) < 3:
            return s
        try:
            from statsmodels.tsa.arima.model import ARIMA
            # Convert year index to a year-start DatetimeIndex so that
            # statsmodels recognizes a proper temporal frequency and
            # the forecast horizon attaches to real future years.
            ts = s.astype(float).copy()
            try:
                ts.index = pd.date_range(
                    start=f"{int(ts.index.min())}-01-01",
                    periods=len(ts), freq="YS",
                )
            except Exception:  # pragma: no cover - defensive
                pass
            order = (1, 1, 1) if len(ts) >= 8 else (0, 1, 1)
            try:
                model = ARIMA(ts, order=order)
                fit = model.fit()
                forecast_vals = fit.forecast(steps=years_ahead)
                vals = np.asarray(forecast_vals, dtype=float)
                if not np.all(np.isfinite(vals)):
                    raise ValueError("Non-finite forecast values")
            except Exception as exc:
                self.logger.warning(
                    "ARIMA fit failed (%s); falling back to linear trend", exc
                )
                vals = self._linear_forecast(s, years_ahead)
        except Exception as exc:  # pragma: no cover - optional dep
            self.logger.warning(
                "statsmodels unavailable (%s); using linear trend", exc
            )
            vals = self._linear_forecast(s, years_ahead)
        last_year = int(s.index.max())
        future_index = [last_year + i + 1 for i in range(years_ahead)]
        combined = pd.concat([
            s,
            pd.Series(vals, index=future_index, name="publications"),
        ])
        combined.name = "publications"
        return combined

    @staticmethod
    def _linear_forecast(s: pd.Series, years_ahead: int) -> np.ndarray:
        """Simple linear-regression extrapolation."""
        x = np.arange(len(s), dtype=float)
        y = s.to_numpy(dtype=float)
        # Fit y = a * x + b
        if len(x) >= 2:
            a, b = np.polyfit(x, y, 1)
        else:
            a, b = 0.0, float(y.mean()) if len(y) else 0.0
        future_x = np.arange(len(s), len(s) + years_ahead, dtype=float)
        return a * future_x + b

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def visualize(self, metric: str = "publications") -> "Figure":  # type: ignore[name-defined]
        """Plot the requested yearly metric.

        Args:
            metric: ``"publications"`` or ``"citations"``.

        Returns:
            A :class:`matplotlib.figure.Figure`.
        """
        import matplotlib.pyplot as plt
        metric = metric.lower()
        if metric == "citations":
            s = self.citations_per_year()
            title = "Citations per Year"
            color = "#e07a5f"
        else:
            s = self.publications_per_year()
            title = "Publications per Year"
            color = "#3a7ca5"
        fig, ax = plt.subplots(figsize=(9, 4.5), constrained_layout=True)
        if s.empty:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes)
            return fig
        ax.plot(s.index.astype(int), s.values, marker="o", color=color)
        ax.set_xlabel("Year")
        ax.set_ylabel(metric.capitalize())
        ax.set_title(title)
        return fig
