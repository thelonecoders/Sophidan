"""trend_forecasting — research-trend forecasting for the Academic
Research Suite.

Provides :class:`TrendForecaster`, which exposes ARIMA / Prophet /
linear / exponential forecasts over:

* topic prevalence (paper count per year mentioning a keyword),
* citation growth of an individual paper,
* author productivity (papers per year),
* field-level publication trends.

Each :meth:`TrendForecaster.forecast_*` method returns a
:class:`Forecast` dataclass carrying the historical series, the
forecast series, confidence intervals, fit quality metrics (MAE / R²),
the method used, and helper visualization methods.

Heavy dependencies (``statsmodels``, ``prophet``, ``pandas``,
``matplotlib``) are imported lazily so the module loads cleanly on
minimal installs and degrades gracefully to linear regression when
ARIMA / Prophet are unavailable.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import math
import warnings
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

logger = logging.getLogger(__name__)

# Many forecasting backends emit noisy warnings on tiny inputs; we
# silence them here because the module falls back to simpler models
# automatically.
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*Prophet.*")
warnings.filterwarnings("ignore", message=".*overflow.*")
warnings.filterwarnings("ignore", message=".*Maximum Likelihood optimization failed.*")
warnings.filterwarnings("ignore", message=".*ConvergenceWarning.*")
warnings.filterwarnings("ignore", message=".*No frequency.*")


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass
class Forecast:
    """Result of a forecasting run.

    Attributes:
        topic: Topic / entity identifier this forecast is for.
        historical_data: Annual historical counts (indexed by year).
        forecast_data: Forecast annual counts (indexed by year).
        confidence_intervals: DataFrame indexed by forecast year with
            ``lower`` and ``upper`` columns.
        method: ``"arima"`` | ``"prophet"`` | ``"linear"`` |
            ``"exponential"``.
        mae: Mean absolute error of in-sample fit (lower is better).
        r2: R² of in-sample fit (1.0 = perfect, ≤ 0 = poor).
    """

    topic: str = ""
    historical_data: Any = None
    forecast_data: Any = None
    confidence_intervals: Any = None
    method: str = ""
    mae: float = 0.0
    r2: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        d: Dict[str, Any] = {
            "topic": self.topic,
            "method": self.method,
            "mae": float(self.mae),
            "r2": float(self.r2),
        }
        if self.historical_data is not None:
            d["historical"] = {
                int(k): float(v)
                for k, v in dict(self.historical_data).items()
            }
        if self.forecast_data is not None:
            d["forecast"] = {
                int(k): float(v)
                for k, v in dict(self.forecast_data).items()
            }
        if self.confidence_intervals is not None:
            ci = self.confidence_intervals
            try:
                d["confidence_intervals"] = {
                    "lower": [float(v) for v in ci["lower"].tolist()],
                    "upper": [float(v) for v in ci["upper"].tolist()],
                    "years": [int(y) for y in ci.index.tolist()],
                }
            except Exception:  # pragma: no cover - defensive
                d["confidence_intervals"] = None
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configure_fonts() -> None:
    """Configure matplotlib rcParams for CJK-aware font fallback."""
    try:
        import matplotlib
        from matplotlib import font_manager
        preferred = [
            "Noto Sans SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
            "Microsoft YaHei", "PingFang SC", "SimHei", "DejaVu Sans",
        ]
        available = {f.name for f in font_manager.fontManager.ttflist}
        family = [f for f in preferred if f in available] or ["DejaVu Sans"]
        matplotlib.rcParams["font.family"] = family
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Font configuration failed: %s", exc)


def _safe_year(p: Any) -> Optional[int]:
    """Return ``int(p.year)`` or ``None``."""
    y = getattr(p, "year", None)
    if y is None:
        return None
    try:
        return int(y)
    except (TypeError, ValueError):
        return None


def _series_to_pd(s: Dict[int, float]) -> Any:
    """Convert a ``{year: value}`` dict to a pandas Series indexed by year."""
    import pandas as pd  # lazy
    if not s:
        return pd.Series(dtype=float)
    years = sorted(s.keys())
    return pd.Series([float(s[y]) for y in years], index=years)


def _ci_to_pd(
    years: Sequence[int],
    lower: Sequence[float],
    upper: Sequence[float],
) -> Any:
    """Build a confidence-interval DataFrame."""
    import pandas as pd  # lazy
    return pd.DataFrame(
        {"lower": list(lower), "upper": list(upper)},
        index=list(years),
    )


def _r2_score(actual: Sequence[float], pred: Sequence[float]) -> float:
    """Coefficient of determination (R²)."""
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    if len(a) < 2:
        return 0.0
    ss_res = float(np.sum((a - p) ** 2))
    ss_tot = float(np.sum((a - a.mean()) ** 2))
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return float(1.0 - ss_res / ss_tot)


def _mae_score(actual: Sequence[float], pred: Sequence[float]) -> float:
    """Mean absolute error."""
    a = np.asarray(actual, dtype=float)
    p = np.asarray(pred, dtype=float)
    if len(a) == 0:
        return 0.0
    return float(np.mean(np.abs(a - p)))


# ---------------------------------------------------------------------------
# TrendForecaster
# ---------------------------------------------------------------------------


class TrendForecaster:
    """Research-trend forecaster using ARIMA / Prophet / linear / exponential."""

    def __init__(self, papers: Sequence[Any]) -> None:
        """Initialize the forecaster.

        Args:
            papers: Sequence of :class:`Paper`-like objects.
        """
        self.papers: List[Any] = list(papers)
        self.logger = logger
        self._topic_series_cache: Dict[str, Dict[int, int]] = {}

    # ------------------------------------------------------------------
    # Series construction
    # ------------------------------------------------------------------

    def _topic_yearly_counts(self, topic: str) -> Dict[int, int]:
        """Return ``{year: count}`` for papers matching ``topic`` (cached)."""
        if topic in self._topic_series_cache:
            return self._topic_series_cache[topic]
        counts: Dict[int, int] = {}
        topic_lower = topic.lower()
        for p in self.papers:
            y = _safe_year(p)
            if y is None:
                continue
            # Match topic against title, abstract, keywords.
            text = (
                (getattr(p, "title", "") or "") + " " +
                (getattr(p, "abstract", "") or "")
            ).lower()
            kws = [str(k).lower() for k in (getattr(p, "keywords", []) or [])]
            fos = [str(f).lower() for f in (getattr(p, "fields_of_study", []) or [])]
            if (topic_lower in text or topic_lower in kws
                    or topic_lower in fos):
                counts[y] = counts.get(y, 0) + 1
        self._topic_series_cache[topic] = counts
        return counts

    def _author_yearly_counts(self, author_id: str) -> Dict[int, int]:
        """Return ``{year: count}`` of papers per year for an author."""
        counts: Dict[int, int] = {}
        for p in self.papers:
            y = _safe_year(p)
            if y is None:
                continue
            for a in (getattr(p, "authors", []) or []):
                if author_id.lower() in str(a).lower():
                    counts[y] = counts.get(y, 0) + 1
                    break
        return counts

    def _paper_citation_yearly(self, paper_id: str) -> Dict[int, int]:
        """Approximate per-year citation trajectory for a single paper.

        Because most scrapers only return the *current* cumulative
        citation count, we synthesize a monotonic ramp (linear growth)
        from the publication year to the latest year in the corpus,
        ending at the paper's reported citation count.
        """
        target = None
        for p in self.papers:
            pid = getattr(p, "doi", None) or getattr(p, "title", None) or ""
            if str(pid) == str(paper_id):
                target = p
                break
        if target is None:
            return {}
        pub_year = _safe_year(target)
        if pub_year is None:
            return {}
        max_year = pub_year
        for p in self.papers:
            y = _safe_year(p)
            if y is not None and y > max_year:
                max_year = y
        total = int(getattr(target, "citations_count", 0) or 0)
        span = max(1, max_year - pub_year + 1)
        counts: Dict[int, int] = {}
        for i, y in enumerate(range(pub_year, max_year + 1)):
            counts[y] = int(round(total * (i + 1) / span))
        return counts

    def _field_yearly_counts(self, field: str) -> Dict[int, int]:
        """Return ``{year: count}`` for papers in a field of study."""
        counts: Dict[int, int] = {}
        field_lower = field.lower()
        for p in self.papers:
            y = _safe_year(p)
            if y is None:
                continue
            fos = [str(f).lower() for f in (getattr(p, "fields_of_study", []) or [])]
            if field_lower in fos:
                counts[y] = counts.get(y, 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Core forecast dispatch
    # ------------------------------------------------------------------

    def _forecast_arima(
        self,
        series: Dict[int, float],
        years_ahead: int,
    ) -> Tuple[List[float], List[float], List[float], List[float]]:
        """Fit ARIMA(1,1,1) and return historical fit + forecast + CI.

        Returns:
            Tuple ``(fitted, forecast, lower, upper)``.
        """
        years = sorted(series.keys())
        values = [float(series[y]) for y in years]
        n = len(values)
        fitted: List[float] = []
        forecast: List[float] = []
        lower: List[float] = []
        upper: List[float] = []
        try:
            from statsmodels.tsa.arima.model import ARIMA  # lazy
            import pandas as pd  # lazy
            idx = pd.period_range(start=str(years[0]), periods=n, freq="Y")
            ts = pd.Series(values, index=idx)
            if n < 4:
                raise ValueError("ARIMA needs >=4 observations")
            order = (1, 1, 1) if n >= 6 else (1, 0, 0)
            model = ARIMA(ts, order=order)
            fit = model.fit()
            fitted = list(map(float, np.asarray(fit.fittedvalues)))
            # Forecast with confidence interval.
            fobj = fit.get_forecast(steps=years_ahead)
            fc_mean = list(map(float, np.asarray(fobj.predicted_mean)))
            ci = fobj.conf_int(alpha=0.20)
            lower = list(map(float, np.asarray(ci.iloc[:, 0])))
            upper = list(map(float, np.asarray(ci.iloc[:, 1])))
            forecast = fc_mean
        except Exception as exc:
            self.logger.debug("ARIMA failed (%s); falling back to linear.", exc)
            return self._forecast_linear(series, years_ahead)
        return fitted, forecast, lower, upper

    def _forecast_prophet(
        self,
        series: Dict[int, float],
        years_ahead: int,
    ) -> Tuple[List[float], List[float], List[float], List[float]]:
        """Fit Prophet (if installed) and return fitted + forecast + CI."""
        years = sorted(series.keys())
        values = [float(series[y]) for y in years]
        try:
            from prophet import Prophet  # type: ignore  # lazy
            import pandas as pd  # lazy
            df = pd.DataFrame({
                "ds": [pd.Timestamp(year=int(y), month=1, day=1) for y in years],
                "y": values,
            })
            m = Prophet(interval_width=0.80, yearly_seasonality=False,
                         weekly_seasonality=False, daily_seasonality=False)
            m.fit(df)
            future = m.make_future_dataframe(periods=years_ahead, freq="YS")
            fc = m.predict(future)
            fitted = list(map(float, np.asarray(fc["yhat"][:len(values)])))
            forecast = list(map(float, np.asarray(fc["yhat"][len(values):])))
            lower = list(map(float, np.asarray(fc["yhat_lower"][len(values):])))
            upper = list(map(float, np.asarray(fc["yhat_upper"][len(values):])))
        except Exception as exc:
            self.logger.debug(
                "Prophet unavailable (%s); falling back to linear.", exc)
            return self._forecast_linear(series, years_ahead)
        return fitted, forecast, lower, upper

    def _forecast_linear(
        self,
        series: Dict[int, float],
        years_ahead: int,
    ) -> Tuple[List[float], List[float], List[float], List[float]]:
        """Linear-regression forecast (no CI; uses residual std for bounds)."""
        years = sorted(series.keys())
        values = [float(series[y]) for y in years]
        n = len(values)
        if n < 2:
            # Constant series — flat forecast.
            fitted = list(values)
            forecast = [values[-1]] * years_ahead if values else [0.0] * years_ahead
            std = 0.0
        else:
            x = np.asarray(years, dtype=float)
            y = np.asarray(values, dtype=float)
            slope, intercept = np.polyfit(x, y, 1)
            fitted = list(map(float, slope * x + intercept))
            future_years = list(range(years[-1] + 1, years[-1] + 1 + years_ahead))
            fx = np.asarray(future_years, dtype=float)
            forecast = list(map(float, slope * fx + intercept))
            residuals = y - (slope * x + intercept)
            std = float(np.std(residuals)) if len(residuals) > 1 else 0.0
        lower = [f - 1.2816 * std for f in forecast]
        upper = [f + 1.2816 * std for f in forecast]
        return fitted, forecast, lower, upper

    def _forecast_exponential(
        self,
        series: Dict[int, float],
        years_ahead: int,
    ) -> Tuple[List[float], List[float], List[float], List[float]]:
        """Exponential-smoothing forecast (Holt's linear trend)."""
        years = sorted(series.keys())
        values = [float(series[y]) for y in years]
        n = len(values)
        if n < 2:
            return self._forecast_linear(series, years_ahead)
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing  # lazy
            import pandas as pd  # lazy
            idx = pd.period_range(start=str(years[0]), periods=n, freq="Y")
            ts = pd.Series(values, index=idx)
            model = ExponentialSmoothing(
                ts, trend="add", seasonal=None, initialization_method="estimated",
            )
            fit = model.fit()
            fitted = list(map(float, np.asarray(fit.fittedvalues)))
            fc = fit.forecast(years_ahead)
            forecast = list(map(float, np.asarray(fc)))
            # CI: use in-sample residual std.
            residuals = np.asarray(values) - np.asarray(fitted)
            std = float(np.std(residuals)) if len(residuals) > 1 else 0.0
            lower = [f - 1.2816 * std for f in forecast]
            upper = [f + 1.2816 * std for f in forecast]
        except Exception as exc:
            self.logger.debug(
                "Exponential smoothing failed (%s); falling back to linear.", exc)
            return self._forecast_linear(series, years_ahead)
        return fitted, forecast, lower, upper

    def _run_forecast(
        self,
        topic: str,
        series: Dict[int, float],
        years_ahead: int,
        method: str,
    ) -> Forecast:
        """Dispatch the requested forecasting backend and build a Forecast."""
        if not series:
            return Forecast(topic=topic, method=method, mae=0.0, r2=0.0)
        method = (method or "arima").lower()
        if method == "arima":
            fitted, forecast, lower, upper = self._forecast_arima(series, years_ahead)
        elif method == "prophet":
            fitted, forecast, lower, upper = self._forecast_prophet(series, years_ahead)
        elif method == "linear":
            fitted, forecast, lower, upper = self._forecast_linear(series, years_ahead)
        elif method == "exponential":
            fitted, forecast, lower, upper = self._forecast_exponential(series, years_ahead)
        else:
            raise ValueError(f"Unknown forecast method: {method!r}")

        years = sorted(series.keys())
        hist_values = [float(series[y]) for y in years]
        # Compute fit metrics using the fitted values (truncated to
        # actual length when ARIMA's differencing reduces them).
        fitted_trimmed = fitted[-len(hist_values):] if fitted else []
        mae = _mae_score(hist_values, fitted_trimmed)
        r2 = _r2_score(hist_values, fitted_trimmed)
        forecast_years = list(range(years[-1] + 1, years[-1] + 1 + years_ahead))

        return Forecast(
            topic=topic,
            historical_data=_series_to_pd(series),
            forecast_data=_series_to_pd(
                {y: max(0.0, f) for y, f in zip(forecast_years, forecast)}
            ),
            confidence_intervals=_ci_to_pd(
                forecast_years,
                [max(0.0, v) for v in lower],
                [max(0.0, v) for v in upper],
            ),
            method=method,
            mae=mae,
            r2=r2,
        )

    # ------------------------------------------------------------------
    # Public forecasting methods
    # ------------------------------------------------------------------

    def forecast_topic(
        self,
        topic: str,
        years_ahead: int = 3,
        method: str = "arima",
    ) -> Forecast:
        """Forecast topic prevalence (papers per year) over the next years.

        Args:
            topic: Topic keyword.
            years_ahead: Number of years to forecast.
            method: ``"arima"`` | ``"prophet"`` | ``"linear"`` |
                ``"exponential"``.

        Returns:
            A :class:`Forecast`.
        """
        series = self._topic_yearly_counts(topic)
        return self._run_forecast(topic, series, years_ahead, method)

    def forecast_all_topics(
        self,
        years_ahead: int = 3,
        top_n: int = 10,
        method: str = "arima",
    ) -> List[Forecast]:
        """Forecast the top-N most prevalent topics.

        Args:
            years_ahead: Number of years to forecast.
            top_n: Number of topics to forecast.
            method: Forecasting method.

        Returns:
            List of :class:`Forecast` sorted by total historical papers.
        """
        # Build topic prevalence map.
        topic_totals: Dict[str, int] = {}
        for p in self.papers:
            for kw in (getattr(p, "keywords", []) or []):
                if not kw:
                    continue
                topic_totals[str(kw)] = topic_totals.get(str(kw), 0) + 1
        for fos in (getattr(p, "fields_of_study", []) or []):
            if not fos:
                continue
            topic_totals.setdefault(str(fos), 0)
        if not topic_totals:
            return []
        top = sorted(topic_totals.items(), key=lambda kv: -kv[1])[:top_n]
        results: List[Forecast] = []
        for topic, _ in top:
            series = self._topic_yearly_counts(topic)
            if not series or len(series) < 2:
                continue
            results.append(self._run_forecast(topic, series, years_ahead, method))
        return results

    def emerging_keywords(
        self,
        years_ahead: int = 2,
        top_n: int = 20,
    ) -> List[Tuple[str, float]]:
        """Return keywords predicted to grow most strongly.

        Args:
            years_ahead: Forecast horizon.
            top_n: Number of keywords to return.

        Returns:
            Sorted list of ``(keyword, growth_rate)`` tuples.
        """
        topic_totals: Dict[str, int] = {}
        for p in self.papers:
            for kw in (getattr(p, "keywords", []) or []):
                if not kw:
                    continue
                topic_totals[str(kw)] = topic_totals.get(str(kw), 0) + 1
        if not topic_totals:
            return []
        candidates = sorted(topic_totals.items(), key=lambda kv: -kv[1])[:top_n * 3]
        results: List[Tuple[str, float]] = []
        for topic, _ in candidates:
            series = self._topic_yearly_counts(topic)
            if not series or len(series) < 2:
                continue
            try:
                fc = self._run_forecast(topic, series, years_ahead, "linear")
                last_hist = float(series[max(series.keys())])
                avg_fc = float(np.mean(list(fc.forecast_data.values))) if len(fc.forecast_data) else 0.0
                growth = (avg_fc - last_hist) / max(last_hist, 1.0)
                results.append((topic, growth))
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.debug("emerging_keywords failed for %r: %s", topic, exc)
                continue
        results.sort(key=lambda kv: -kv[1])
        return results[:top_n]

    def fading_keywords(
        self,
        years_ahead: int = 2,
        top_n: int = 20,
    ) -> List[Tuple[str, float]]:
        """Return keywords predicted to decline most strongly.

        Args:
            years_ahead: Forecast horizon.
            top_n: Number of keywords to return.

        Returns:
            Sorted list of ``(keyword, decline_rate)`` tuples (most
            negative first).
        """
        emerging = self.emerging_keywords(years_ahead=years_ahead, top_n=top_n * 5)
        fading = sorted(emerging, key=lambda kv: kv[1])
        return fading[:top_n]

    def forecast_citation_growth(
        self,
        paper_id: str,
        years_ahead: int = 3,
        method: str = "arima",
    ) -> Forecast:
        """Forecast the citation trajectory of a single paper.

        Args:
            paper_id: DOI or title identifying the paper.
            years_ahead: Forecast horizon.
            method: Forecasting method.

        Returns:
            A :class:`Forecast`.
        """
        series = self._paper_citation_yearly(paper_id)
        return self._run_forecast(paper_id, series, years_ahead, method)

    def forecast_author_productivity(
        self,
        author_id: str,
        years_ahead: int = 3,
        method: str = "arima",
    ) -> Forecast:
        """Forecast an author's yearly publication output.

        Args:
            author_id: Author name (or substring).
            years_ahead: Forecast horizon.
            method: Forecasting method.

        Returns:
            A :class:`Forecast`.
        """
        series = self._author_yearly_counts(author_id)
        return self._run_forecast(author_id, series, years_ahead, method)

    def forecast_field(
        self,
        field_of_study: str,
        years_ahead: int = 5,
        method: str = "arima",
    ) -> Forecast:
        """Forecast the publication volume of a field of study.

        Args:
            field_of_study: Field name.
            years_ahead: Forecast horizon (default 5 years — longer
                than other forecasts because field-level trends evolve
                slowly).
            method: Forecasting method.

        Returns:
            A :class:`Forecast`.
        """
        series = self._field_yearly_counts(field_of_study)
        return self._run_forecast(field_of_study, series, years_ahead, method)

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def visualize(
        self,
        forecast: Forecast,
        figsize: Tuple[int, int] = (10, 6),
    ) -> Any:
        """Render a single forecast with historical + forecast + CI band.

        Args:
            forecast: A :class:`Forecast` instance.
            figsize: Figure size.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        import matplotlib.pyplot as plt  # lazy
        _configure_fonts()

        fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
        if (forecast.historical_data is None or len(forecast.historical_data) == 0):
            ax.text(0.5, 0.5, "No historical data",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            return fig

        hist_years = list(forecast.historical_data.index)
        hist_vals = list(forecast.historical_data.values)
        ax.plot(hist_years, hist_vals, marker="o", color="steelblue",
                label="historical")

        if forecast.forecast_data is not None and len(forecast.forecast_data) > 0:
            fc_years = list(forecast.forecast_data.index)
            fc_vals = list(forecast.forecast_data.values)
            # Connect last historical to first forecast.
            joined_x = [hist_years[-1]] + fc_years
            joined_y = [hist_vals[-1]] + fc_vals
            ax.plot(joined_x, joined_y, marker="s", color="darkorange",
                    linestyle="--", label="forecast")
            if forecast.confidence_intervals is not None and len(forecast.confidence_intervals) > 0:
                ci = forecast.confidence_intervals
                ax.fill_between(
                    fc_years,
                    ci["lower"], ci["upper"],
                    color="darkorange", alpha=0.20, label="80% CI",
                )

        ax.set_title(f"Forecast: {forecast.topic} ({forecast.method}, "
                     f"MAE={forecast.mae:.2f}, R²={forecast.r2:.2f})")
        ax.set_xlabel("Year")
        ax.set_ylabel("Count")
        ax.legend(loc="best", fontsize=9)
        ax.grid(True, alpha=0.3)
        return fig

    def batch_forecast_visualization(
        self,
        forecasts: Sequence[Forecast],
        cols: int = 2,
        figsize: Optional[Tuple[int, int]] = None,
    ) -> Any:
        """Render multiple forecasts in a grid.

        Args:
            forecasts: List of :class:`Forecast`.
            cols: Number of columns in the grid.
            figsize: Optional explicit figure size; otherwise
                computed from the number of forecasts.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        import matplotlib.pyplot as plt  # lazy
        _configure_fonts()

        n = len(forecasts)
        if n == 0:
            fig, ax = plt.subplots(figsize=(6, 4), constrained_layout=True)
            ax.text(0.5, 0.5, "No forecasts to display",
                    ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            return fig

        rows = math.ceil(n / cols)
        if figsize is None:
            figsize = (5 * cols, 4 * rows)
        fig, axes = plt.subplots(rows, cols, figsize=figsize,
                                   constrained_layout=True, squeeze=False)
        for idx, fc in enumerate(forecasts):
            r, c = divmod(idx, cols)
            ax = axes[r][c]
            if fc.historical_data is not None and len(fc.historical_data) > 0:
                hist_years = list(fc.historical_data.index)
                hist_vals = list(fc.historical_data.values)
                ax.plot(hist_years, hist_vals, marker="o",
                        color="steelblue", label="historical")
                if fc.forecast_data is not None and len(fc.forecast_data) > 0:
                    fc_years = list(fc.forecast_data.index)
                    fc_vals = list(fc.forecast_data.values)
                    joined_x = [hist_years[-1]] + fc_years
                    joined_y = [hist_vals[-1]] + fc_vals
                    ax.plot(joined_x, joined_y, marker="s",
                            color="darkorange", linestyle="--",
                            label="forecast")
                    if fc.confidence_intervals is not None and len(fc.confidence_intervals) > 0:
                        ci = fc.confidence_intervals
                        ax.fill_between(fc_years, ci["lower"], ci["upper"],
                                          color="darkorange", alpha=0.20)
            ax.set_title(f"{fc.topic} ({fc.method}, R²={fc.r2:.2f})",
                          fontsize=10)
            ax.tick_params(labelsize=8)
            if idx == 0:
                ax.legend(loc="best", fontsize=8)
            ax.grid(True, alpha=0.3)
        # Hide unused subplots.
        for idx in range(n, rows * cols):
            r, c = divmod(idx, cols)
            axes[r][c].set_axis_off()
        return fig


__all__ = [
    "Forecast",
    "TrendForecaster",
]
