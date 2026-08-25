"""Funnel plots & publication-bias tests.

* :class:`FunnelPlot` — scatter of effect estimate vs standard error (or
  precision), with optional pseudo-CI triangle, trim-and-fill imputation,
  Egger / Begg / Peters / Harbord tests, Rosenthal & Orwin fail-safe N.
* :class:`ContourEnhancedFunnel` — adds shaded significance contours
  (0.01 / 0.05 / 0.10) which help distinguish publication bias from
  genuine asymmetry (Peters et al. 2008).

Heavy deps (numpy, scipy, matplotlib, statsmodels) are lazy-imported.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .effect_sizes import EffectSize, EffectSizeCalculator, EffectSizeType
from .pooling import PoolingEngine, PoolingMethod

logger = logging.getLogger(__name__)

__all__ = ["FunnelPlot", "ContourEnhancedFunnel"]


def _std_normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _std_normal_ppf(p: float) -> float:
    """Inverse normal CDF — falls back to scipy if available."""
    try:
        from scipy.stats import norm  # type: ignore
        return float(norm.ppf(p))
    except Exception:
        # Beasley-Springer-Moro approximation.
        a = [-3.969683028665376e+01, 2.209460984245205e+02,
             -2.759285104469687e+02, 1.383577518672690e+02,
             -3.066479806614716e+01, 2.506628277459239e+00]
        b = [-5.447609879822406e+01, 1.615858368580409e+02,
             -1.556989798598866e+02, 6.680131188771972e+01,
             -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01,
             -2.400758277161838e+00, -2.549732539343734e+00,
             4.374664141464968e+00, 2.938163982698783e+00]
        d = [7.784695709041462e-03, 3.224671290700398e-01,
             2.445134137142996e+00, 3.754408661907416e+00]
        p_low = 0.02425
        p_high = 1 - p_low
        if p < p_low:
            q = math.sqrt(-2 * math.log(p))
            x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        elif p <= p_high:
            q = p - 0.5
            r = q * q
            x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
                (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        else:
            q = math.sqrt(-2 * math.log(1 - p))
            x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
        return float(x)


class FunnelPlot:
    """Funnel plot with publication-bias diagnostics.

    Attributes:
        effect_sizes: List of :class:`EffectSize`.
        pooled: Optional pooled :class:`EffectSize` (defines the centre
            vertical of the funnel). If ``None``, computed via IV fixed.
    """

    def __init__(
        self,
        effect_sizes: List[EffectSize],
        pooled: Optional[EffectSize] = None,
    ):
        if not effect_sizes:
            raise ValueError("effect_sizes is empty.")
        self.effect_sizes = list(effect_sizes)
        self.pooled = pooled
        # Imputed studies (populated by trim_and_fill / add_trim_fill).
        self._imputed: List[EffectSize] = []

    # ------------------------------------------------------------------ #
    # Render
    # ------------------------------------------------------------------ #
    def render(
        self,
        figsize: Tuple[float, float] = (8, 8),
        dpi: int = 300,
        style: str = "cochrane",
    ):
        """Render the funnel plot.

        Args:
            figsize: (width, height) in inches.
            dpi: Resolution.
            style: ``'cochrane'`` | ``'jama'`` | ``'lancet'``.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        import matplotlib  # type: ignore
        matplotlib.use("Agg", force=False)
        import matplotlib.pyplot as plt  # type: ignore
        import numpy as np  # type: ignore

        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = [
            "Noto Sans SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
            "Microsoft YaHei", "PingFang SC", "SimHei", "DejaVu Sans",
        ]
        plt.rcParams["axes.unicode_minus"] = False

        if self.pooled is None:
            self.pooled = PoolingEngine._fixed_iv(self.effect_sizes)

        # Work on the analysis scale (log for RR/OR/HR).
        es_type = self.effect_sizes[0].type
        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            if es_type.is_log_scale_metric else es
            for es in self.effect_sizes
        ]
        pooled_log = (
            EffectSizeCalculator.to_log_scale(self.pooled)
            if es_type.is_log_scale_metric else self.pooled
        )

        thetas = np.array([es.value for es in log_list], dtype=float)
        ses = np.array([
            es.se if es.se is not None else 1.0 for es in log_list
        ], dtype=float)
        # Handle NaN / inf.
        thetas = np.where(np.isfinite(thetas), thetas, 0.0)
        ses = np.where(np.isfinite(ses) & (ses > 0), ses, 1.0)
        se_max = float(ses.max())

        fig, ax = plt.subplots(figsize=figsize, dpi=dpi, constrained_layout=True)
        # Scatter: x = effect estimate, y = standard error (inverted y-axis).
        ax.scatter(thetas, ses, c="#1F77B4", s=40, edgecolors="white",
                   linewidths=0.5, label="Observed studies")
        # Imputed studies (from trim-and-fill):
        if self._imputed:
            imputed_log = [
                EffectSizeCalculator.to_log_scale(es)
                if es_type.is_log_scale_metric else es
                for es in self._imputed
            ]
            imputed_thetas = np.array([es.value for es in imputed_log])
            imputed_ses = np.array([es.se if es.se else 1.0 for es in imputed_log])
            ax.scatter(
                imputed_thetas, imputed_ses, c="#D62728", s=40, marker="^",
                edgecolors="white", linewidths=0.5,
                label=f"Imputed ({len(self._imputed)})",
            )

        # Centre vertical at pooled effect.
        ax.axvline(pooled_log.value, color="#444444", linestyle="--", lw=1.0)
        # Pseudo-CI triangle (95% by default).
        self._draw_pseudo_ci(ax, pooled_log.value, se_max)
        # Invert y-axis so smaller SE (more precise) at top.
        ax.set_ylim(bottom=0.0, top=se_max * 1.05)
        ax.invert_yaxis()
        ax.set_xlabel(f"{es_type.value} (analysis scale)")
        ax.set_ylabel("Standard Error")
        ax.set_title("Funnel plot")
        ax.legend(loc="upper left", frameon=True, fontsize=8)
        self._fig = fig
        return fig

    def _draw_pseudo_ci(self, ax, pooled_value: float, se_max: float, alpha: float = 0.95):
        """Draw the pseudo-confidence triangle for the null of no asymmetry."""
        z = _std_normal_ppf(0.5 + alpha / 2.0)
        # Triangle from (pooled_value, 0) to (pooled ± z*se_max, se_max).
        xs = [pooled_value, pooled_value - z * se_max, pooled_value + z * se_max, pooled_value]
        ys = [0.0, se_max, se_max, 0.0]
        ax.fill(xs, ys, color="#CCCCCC", alpha=0.35, label=f"{int(alpha*100)}% pseudo-CI")

    # ------------------------------------------------------------------ #
    # Publication-bias tests
    # ------------------------------------------------------------------ #
    def eggers_test(self) -> Tuple[float, float, float]:
        """Egger's test for funnel-plot asymmetry.

        Regresses the standardised effect (θ / SE) on precision (1 / SE):
            θ_i / SE_i = β0 + β1 · (1 / SE_i) + ε_i
        The intercept β0 ≠ 0 ⇒ funnel-plot asymmetry.

        Returns:
            Tuple ``(t_statistic, p_value, bias_estimate)``.
        """
        try:
            import numpy as np  # type: ignore
            from scipy import stats  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("numpy + scipy required for eggers_test.") from exc

        es_type = self.effect_sizes[0].type
        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            if es_type.is_log_scale_metric else es
            for es in self.effect_sizes
        ]
        y = np.array([es.value / es.se for es in log_list if es.se and es.se > 0])
        x = np.array([1.0 / es.se for es in log_list if es.se and es.se > 0])
        if len(y) < 3:
            return 0.0, 1.0, 0.0
        # OLS: y = b0 + b1 * x.
        X = np.column_stack([np.ones_like(x), x])
        beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        residuals = y - X @ beta
        n, p = len(y), 2
        sse = float(np.sum(residuals ** 2))
        if sse <= 0 or n - p <= 0:
            return 0.0, 1.0, float(beta[0])
        sigma2 = sse / (n - p)
        try:
            cov = sigma2 * np.linalg.inv(X.T @ X)
            se_intercept = math.sqrt(cov[0, 0])
        except np.linalg.LinAlgError:
            se_intercept = 1.0
        t = beta[0] / se_intercept if se_intercept > 0 else 0.0
        p_val = float(2.0 * stats.t.sf(abs(t), df=n - p))
        return float(t), p_val, float(beta[0])

    def beggs_test(self) -> Tuple[float, float]:
        """Begg's rank-correlation test for funnel-plot asymmetry.

        Returns:
            Tuple ``(kendall_tau, p_value)``.
        """
        try:
            from scipy import stats  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("scipy required for beggs_test.") from exc

        es_type = self.effect_sizes[0].type
        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            if es_type.is_log_scale_metric else es
            for es in self.effect_sizes
        ]
        theta = [es.value for es in log_list if es.se and es.se > 0]
        var = [es.se ** 2 for es in log_list if es.se and es.se > 0]
        if len(theta) < 3:
            return 0.0, 1.0
        tau, p_val = stats.kendalltau(theta, var)
        return float(tau), float(p_val)

    def peters_test(self) -> Tuple[float, float]:
        """Peters' test for publication bias in binary outcomes.

        Regression-based: O(E) on 1/n — appropriate for OR.

        Returns:
            Tuple ``(t_statistic, p_value)``.
        """
        try:
            import numpy as np  # type: ignore
            from scipy import stats  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("numpy + scipy required for peters_test.") from exc

        # Need cell counts.
        for es in self.effect_sizes:
            if None in (es.events_intervention, es.total_intervention,
                        es.events_control, es.total_control):
                raise ValueError(
                    "Peters test requires 2x2 cell counts on every EffectSize."
                )
        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            for es in self.effect_sizes
        ]
        # Peters: logOR_i = β0 + β1 * (1/n_i) + ε.
        log_or = np.array([es.value for es in log_list])
        inv_n = np.array([
            1.0 / float(es.total_intervention + es.total_control)
            for es in self.effect_sizes
        ])
        X = np.column_stack([np.ones_like(inv_n), inv_n])
        beta, _, _, _ = np.linalg.lstsq(X, log_or, rcond=None)
        residuals = log_or - X @ beta
        n, p = len(log_or), 2
        sse = float(np.sum(residuals ** 2))
        if sse <= 0 or n - p <= 0:
            return 0.0, 1.0
        sigma2 = sse / (n - p)
        try:
            cov = sigma2 * np.linalg.inv(X.T @ X)
            se_intercept = math.sqrt(cov[0, 0])
        except np.linalg.LinAlgError:
            se_intercept = 1.0
        t = beta[0] / se_intercept if se_intercept > 0 else 0.0
        p_val = float(2.0 * stats.t.sf(abs(t), df=n - p))
        return float(t), p_val

    def harbord_test(self) -> Tuple[float, float]:
        """Harbord's modified Egger test for binary outcomes (OR).

        Regresses Z_i / V_i on 1 / sqrt(V_i) where Z = O - E and V = variance.

        Returns:
            Tuple ``(t_statistic, p_value)``.
        """
        try:
            import numpy as np  # type: ignore
            from scipy import stats  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("numpy + scipy required for harbord_test.") from exc

        # Need cell counts.
        for es in self.effect_sizes:
            if None in (es.events_intervention, es.total_intervention,
                        es.events_control, es.total_control):
                raise ValueError(
                    "Harbord test requires 2x2 cell counts on every EffectSize."
                )
        zs = []
        vs = []
        for es in self.effect_sizes:
            a = es.events_intervention
            n_t = es.total_intervention
            c = es.events_control
            n_c = es.total_control
            N = n_t + n_c
            n_e = a + c
            E = n_t * n_e / float(N)
            # Peto-style variance.
            V = (n_t * n_c * n_e * (N - n_e)) / (float(N) ** 2 * (N - 1)) if N > 1 else 0.0
            if V <= 0:
                continue
            z = (a - E) / math.sqrt(V)
            zs.append(z)
            vs.append(V)
        if len(zs) < 3:
            return 0.0, 1.0
        z_arr = np.array(zs)
        v_arr = np.array(vs)
        y = z_arr / np.sqrt(v_arr)
        x = 1.0 / np.sqrt(v_arr)
        X = np.column_stack([np.ones_like(x), x])
        beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        residuals = y - X @ beta
        n, p = len(y), 2
        sse = float(np.sum(residuals ** 2))
        if sse <= 0 or n - p <= 0:
            return 0.0, 1.0
        sigma2 = sse / (n - p)
        try:
            cov = sigma2 * np.linalg.inv(X.T @ X)
            se_intercept = math.sqrt(cov[0, 0])
        except np.linalg.LinAlgError:
            se_intercept = 1.0
        t = beta[0] / se_intercept if se_intercept > 0 else 0.0
        p_val = float(2.0 * stats.t.sf(abs(t), df=n - p))
        return float(t), p_val

    # ------------------------------------------------------------------ #
    # Trim and fill
    # ------------------------------------------------------------------ #
    def add_trim_fill(self, trim_method: str = "R0") -> int:
        """Run Duval & Tweedie's trim-and-fill and add imputed studies.

        Args:
            trim_method: ``'L0'`` | ``'R0'`` | ``'Q0'`` — leftmost / rightmost
                / largest estimator. ``'R0'`` (default) is the rightmost
                variant.

        Returns:
            Number of imputed studies.
        """
        imputed, n = self.trim_and_fill(self.effect_sizes, method=trim_method)
        self._imputed = imputed
        return n

    @staticmethod
    def trim_and_fill(
        effect_sizes: List[EffectSize], method: str = "R0"
    ) -> Tuple[List[EffectSize], int]:
        """Duval & Tweedie (2000) trim-and-fill.

        Args:
            effect_sizes: Original studies.
            method: ``'L0'`` | ``'R0'`` | ``'Q0'``.

        Returns:
            Tuple ``(imputed_effect_sizes, n_imputed)``.
        """
        if not effect_sizes:
            return [], 0
        es_type = effect_sizes[0].type
        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            if es_type.is_log_scale_metric else es
            for es in effect_sizes
        ]
        # Sort by effect estimate.
        ordered = sorted(log_list, key=lambda es: es.value)
        theta = [es.value for es in ordered]
        se = [es.se if es.se else 1.0 for es in ordered]
        k = len(ordered)
        if k < 2:
            return [], 0
        # Estimate gamma_0 (number of asymmetric studies) via the chosen estimator.
        # Compute T_n = Σ (theta_max - theta_i) for the rightmost k0 + 1 studies.
        theta_max = max(theta)
        theta_min = min(theta)

        def trim_estimate_left() -> int:
            """How many studies to trim on the LEFT (i.e., missing small
            studies, publication bias against negatives)."""
            # Sort descending by theta; T_n is sum of (theta_max - theta_i).
            sorted_desc = sorted(theta, reverse=True)
            cumsum = 0
            for n_trimmed in range(1, k):
                cumsum += (theta_max - sorted_desc[n_trimmed - 1])
                # Solve T_n = γ0 * (theta_{k-γ0} - theta_{k-1})
                if n_trimmed >= k:
                    break
                denom = theta_max - sorted_desc[n_trimmed] if n_trimmed < k else 0
                if denom > 0:
                    gamma = cumsum / denom - (k - 1) / 2.0
                    gamma_int = round(gamma)
                    if gamma_int == n_trimmed:
                        return max(0, gamma_int)
            return 0

        def trim_estimate_right() -> int:
            sorted_asc = sorted(theta)
            cumsum = 0
            for n_trimmed in range(1, k):
                cumsum += (sorted_asc[n_trimmed - 1] - theta_min)
                denom = sorted_asc[n_trimmed] - theta_min if n_trimmed < k else 0
                if denom > 0:
                    gamma = cumsum / denom - (k - 1) / 2.0
                    gamma_int = round(gamma)
                    if gamma_int == n_trimmed:
                        return max(0, gamma_int)
            return 0

        method = method.upper()
        if method == "L0":
            n_trim = trim_estimate_left()
        elif method == "R0":
            n_trim = trim_estimate_right()
        elif method == "Q0":
            # Most-conservative: max of L0 and R0.
            n_trim = max(trim_estimate_left(), trim_estimate_right())
        else:
            raise ValueError(f"Unknown trim_method={method!r}.")
        if n_trim <= 0 or n_trim >= k:
            return [], 0

        # Trim the most-extreme studies; pool the trimmed set (IV fixed).
        if method == "L0":
            trimmed = ordered[n_trim:]  # remove smallest
        else:
            trimmed = ordered[:-n_trim]  # remove largest
        if not trimmed:
            return [], 0
        # Recompute pooled (center of funnel) without the trimmed studies.
        pooled = PoolingEngine._fixed_iv(trimmed)
        if es_type.is_log_scale_metric:
            pooled_log = EffectSizeCalculator.to_log_scale(pooled)
        else:
            pooled_log = pooled
        center = pooled_log.value
        # Mirror the trimmed studies around the center.
        imputed: List[EffectSize] = []
        if method == "L0":
            to_mirror = ordered[:n_trim]  # the trimmed-away small studies.
        else:
            to_mirror = ordered[k - n_trim:]
        for es in to_mirror:
            mirrored_value = 2.0 * center - es.value
            new_es = EffectSize(
                type=es.type,
                value=mirrored_value,
                se=es.se,
                variance=es.variance,
                ci_lower=mirrored_value - 1.96 * es.se if es.se else None,
                ci_upper=mirrored_value + 1.96 * es.se if es.se else None,
                study_id=(es.study_id or "") + "_imputed",
                study_name=(es.study_name or "Imputed") + " (imputed)",
                n_total=es.n_total,
            )
            if es_type.is_log_scale_metric:
                new_es = EffectSizeCalculator.to_natural_scale(new_es)
            imputed.append(new_es)
        return imputed, len(imputed)

    # ------------------------------------------------------------------ #
    # Fail-safe N
    # ------------------------------------------------------------------ #
    def rosenthal_fail_safe_n(self, alpha: float = 0.05) -> int:
        """Rosenthal's fail-safe N (file drawer number).

        The number of additional null-result studies that would be needed to
        bring the combined p-value above ``alpha``.

        Args:
            alpha: Significance threshold (default 0.05).

        Returns:
            The fail-safe N (rounded up).
        """
        try:
            from scipy.stats import norm  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("scipy required for rosenthal_fail_safe_n.") from exc

        es_type = self.effect_sizes[0].type
        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            if es_type.is_log_scale_metric else es
            for es in self.effect_sizes
        ]
        k = len(log_list)
        # Convert each effect to a z-statistic.
        zs = [es.value / es.se for es in log_list if es.se and es.se > 0]
        if not zs:
            return 0
        sum_z = sum(zs)
        # Stouffer's combined z:
        Z_combined = sum_z / math.sqrt(k)
        z_alpha = norm.ppf(1 - alpha / 2.0)
        # N such that sum_z / sqrt(k + N) = z_alpha.
        if Z_combined <= z_alpha:
            return 0
        N = ((sum_z / z_alpha) ** 2) - k
        return max(0, int(math.ceil(N)))

    def orp_test(self, target_effect: float = 0.0) -> Tuple[float, int]:
        """Orwin's fail-safe N.

        Number of additional studies needed to bring the pooled effect size
        down to ``target_effect`` (assumes the missing studies have effect
        = 0).

        Args:
            target_effect: Desired pooled effect after adding the missing
                studies (default 0).

        Returns:
            Tuple ``(pooled_observed_effect, fail_safe_N)``.
        """
        es_type = self.effect_sizes[0].type
        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            if es_type.is_log_scale_metric else es
            for es in self.effect_sizes
        ]
        pooled = PoolingEngine._fixed_iv(log_list)
        observed = pooled.value if pooled.value is not None else 0.0
        k = len(log_list)
        if abs(target_effect - observed) < 1e-9:
            return float(observed), 0
        # Orwin: N = k * (observed - target) / target_effect  (where target_effect
        # is the mean of missing studies = 0 by default).
        if target_effect == 0:
            N = int(round(k * observed / (-target_effect))) if target_effect != 0 else 0
            # Use the proper formula with assumed mean = 0:
            if target_effect == 0:
                N = int(math.ceil(k * observed / (0.0 - 0.0) if False else
                                  k * (observed - 0) / (0 - observed)
                                  if observed != 0 else 0))
                # Cleaner: solve k*observed / (k + N) = target ⇒ N = k*(observed - target)/target
                # For target=0 the formula diverges; use target = 0.1*observed.
                target_safe = 0.1 * observed if observed != 0 else 0.01
                N = int(math.ceil(k * (observed - target_safe) / target_safe))
        else:
            N = int(math.ceil(k * (observed - target_effect) / target_effect))
        return float(observed), max(0, N)

    # ------------------------------------------------------------------ #
    # Pseudo CI
    # ------------------------------------------------------------------ #
    def add_pseudo_ci(self, alpha: float = 0.95) -> "FunnelPlot":
        """Add a pseudo-confidence triangle to the next render."""
        self._pseudo_alpha = alpha
        return self

    # ------------------------------------------------------------------ #
    # Save
    # ------------------------------------------------------------------ #
    def save(self, path: str, format: str = "png") -> str:
        """Save the rendered figure."""
        import warnings  # type: ignore
        if not hasattr(self, "_fig") or self._fig is None:
            self.render()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self._fig.savefig(path, format=format, dpi=self._fig.get_dpi())
        return path


class ContourEnhancedFunnel(FunnelPlot):
    """Contour-enhanced funnel plot (Peters et al. 2008).

    Same as :class:`FunnelPlot` but with shaded significance contours
    showing regions where p < 0.01, 0.05, 0.10 (helpful for distinguishing
    publication bias from genuine asymmetry).
    """

    def add_significance_contours(self) -> "ContourEnhancedFunnel":
        """Flag that the next render should include shaded contours."""
        self._contours = True
        return self

    def render(
        self,
        figsize: Tuple[float, float] = (8, 8),
        dpi: int = 300,
        style: str = "cochrane",
    ):
        """Render with shaded significance contours."""
        import matplotlib  # type: ignore
        matplotlib.use("Agg", force=False)
        import matplotlib.pyplot as plt  # type: ignore
        import numpy as np  # type: ignore

        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = [
            "Noto Sans SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
            "Microsoft YaHei", "PingFang SC", "SimHei", "DejaVu Sans",
        ]
        plt.rcParams["axes.unicode_minus"] = False

        if self.pooled is None:
            self.pooled = PoolingEngine._fixed_iv(self.effect_sizes)
        es_type = self.effect_sizes[0].type
        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            if es_type.is_log_scale_metric else es
            for es in self.effect_sizes
        ]
        pooled_log = (
            EffectSizeCalculator.to_log_scale(self.pooled)
            if es_type.is_log_scale_metric else self.pooled
        )
        thetas = np.array([es.value for es in log_list], dtype=float)
        ses = np.array([
            es.se if es.se is not None else 1.0 for es in log_list
        ], dtype=float)
        thetas = np.where(np.isfinite(thetas), thetas, 0.0)
        ses = np.where(np.isfinite(ses) & (ses > 0), ses, 1.0)
        se_max = float(ses.max()) * 1.10

        fig, ax = plt.subplots(figsize=figsize, dpi=dpi, constrained_layout=True)
        # Contour bands: for each SE in [0, se_max], the (1-α) CI bounds are
        #   θ_pooled ± z_α * SE.
        # Fill regions:
        #   - |θ - θ_pooled| > z_99% * SE ⇒ p < 0.01 (darkest)
        #   - z_95% < |θ - θ_pooled| / SE ≤ z_99% ⇒ p < 0.05
        #   - z_90% < ... ≤ z_95% ⇒ p < 0.10
        #   - else p > 0.10 (no fill).
        z01 = _std_normal_ppf(0.995)
        z05 = _std_normal_ppf(0.975)
        z10 = _std_normal_ppf(0.95)
        se_grid = np.linspace(0.0, se_max, 200)
        # p<0.10 region (outer).
        ax.fill_betweenx(
            se_grid,
            pooled_log.value - z10 * se_grid,
            pooled_log.value - z05 * se_grid,
            color="#FEE0D2", alpha=0.6,
        )
        ax.fill_betweenx(
            se_grid,
            pooled_log.value + z05 * se_grid,
            pooled_log.value + z10 * se_grid,
            color="#FEE0D2", alpha=0.6,
        )
        # p<0.05 region.
        ax.fill_betweenx(
            se_grid,
            pooled_log.value - z05 * se_grid,
            pooled_log.value - z01 * se_grid,
            color="#FDBB84", alpha=0.6,
        )
        ax.fill_betweenx(
            se_grid,
            pooled_log.value + z01 * se_grid,
            pooled_log.value + z05 * se_grid,
            color="#FDBB84", alpha=0.6,
        )
        # p<0.01 region (innermost).
        ax.fill_betweenx(
            se_grid,
            pooled_log.value - 5 * se_grid,
            pooled_log.value - z01 * se_grid,
            color="#E34A33", alpha=0.5,
        )
        ax.fill_betweenx(
            se_grid,
            pooled_log.value + z01 * se_grid,
            pooled_log.value + 5 * se_grid,
            color="#E34A33", alpha=0.5,
        )
        # Scatter observed.
        ax.scatter(thetas, ses, c="#1F77B4", s=40, edgecolors="white", linewidths=0.5)
        if self._imputed:
            imputed_log = [
                EffectSizeCalculator.to_log_scale(es)
                if es_type.is_log_scale_metric else es
                for es in self._imputed
            ]
            ax.scatter(
                [es.value for es in imputed_log],
                [es.se if es.se else 1.0 for es in imputed_log],
                c="#D62728", s=40, marker="^", edgecolors="white",
            )
        ax.axvline(pooled_log.value, color="#444444", linestyle="--", lw=1.0)
        ax.set_ylim(bottom=0.0, top=se_max)
        ax.invert_yaxis()
        ax.set_xlabel(f"{es_type.value} (analysis scale)")
        ax.set_ylabel("Standard Error")
        ax.set_title("Contour-enhanced funnel plot")
        # Legend (manually).
        from matplotlib.patches import Patch  # type: ignore
        legend_elements = [
            Patch(facecolor="#E34A33", alpha=0.5, label="p < 0.01"),
            Patch(facecolor="#FDBB84", alpha=0.6, label="p < 0.05"),
            Patch(facecolor="#FEE0D2", alpha=0.6, label="p < 0.10"),
        ]
        ax.legend(handles=legend_elements, loc="upper left", fontsize=8, frameon=True)
        self._fig = fig
        return fig
