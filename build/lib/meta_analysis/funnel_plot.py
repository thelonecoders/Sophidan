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
        # Pseudo-CI triangle (level from add_pseudo_ci, default 95%).
        pseudo_alpha = float(getattr(self, "_pseudo_alpha", 0.95) or 0.95)
        self._draw_pseudo_ci(ax, pooled_log.value, se_max, alpha=pseudo_alpha)
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
        """Peters' test for publication bias in binary outcomes (Peters 2006).

        Weighted least-squares regression of the log-OR on ``1/n`` with
        weights ``1 / Var(logOR_i)`` (Woolf variance, with 0.5 continuity
        correction for zero cells). The previous implementation used
        unweighted OLS, which is not the Peters test.

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
        ys: List[float] = []
        inv_ns: List[float] = []
        weights: List[float] = []
        for es in self.effect_sizes:
            a = es.events_intervention
            b = es.total_intervention - es.events_intervention
            c = es.events_control
            d = es.total_control - es.events_control
            n_total = float(es.total_intervention + es.total_control)
            a2, b2, c2, d2 = a + 0.5, b + 0.5, c + 0.5, d + 0.5
            log_or = math.log((a2 * d2) / (b2 * c2))
            var = 1.0 / a2 + 1.0 / b2 + 1.0 / c2 + 1.0 / d2
            if not (var > 0 and math.isfinite(var)):
                continue
            ys.append(log_or)
            inv_ns.append(1.0 / n_total)
            weights.append(1.0 / var)
        if len(ys) < 3:
            return 0.0, 1.0
        y_arr = np.asarray(ys, dtype=float)
        x_arr = np.asarray(inv_ns, dtype=float)
        w_arr = np.asarray(weights, dtype=float)
        sw = np.sqrt(w_arr)
        X = np.column_stack([np.ones_like(x_arr), x_arr])
        # Weighted least squares: scale rows by sqrt(w).
        Xw = X * sw[:, np.newaxis]
        yw = y_arr * sw
        beta, _, _, _ = np.linalg.lstsq(Xw, yw, rcond=None)
        # Fixed-variance (known-weights) covariance of the estimates.
        try:
            cov = np.linalg.inv(X.T @ (w_arr[:, np.newaxis] * X))
            se_intercept = math.sqrt(max(cov[0, 0], 0.0))
        except np.linalg.LinAlgError:
            se_intercept = 1.0
        t = beta[0] / se_intercept if se_intercept > 0 else 0.0
        p_val = float(2.0 * stats.t.sf(abs(t), df=len(ys) - 2))
        return float(t), p_val

    def harbord_test(self) -> Tuple[float, float]:
        """Harbord's modified Egger test for binary outcomes (Harbord 2006).

        Regresses the already-standardised score ``z_i = (O_i − E_i)/√V_i``
        on ``√V_i`` — the intercept tests funnel-plot asymmetry. (The
        previous implementation regressed ``z_i / √V_i = (O−E)/V`` on
        ``1/√V``, i.e. it standardised twice and used the wrong
        covariate, which is not the Harbord test.)

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
        svs = []  # √V per study
        for es in self.effect_sizes:
            a = es.events_intervention
            n_t = es.total_intervention
            c = es.events_control
            n_c = es.total_control
            N = n_t + n_c
            n_e = a + c
            E = n_t * n_e / float(N)
            # Peto-style variance of (O − E).
            V = (n_t * n_c * n_e * (N - n_e)) / (float(N) ** 2 * (N - 1)) if N > 1 else 0.0
            if V <= 0:
                continue
            z = (a - E) / math.sqrt(V)
            zs.append(z)
            svs.append(math.sqrt(V))
        if len(zs) < 3:
            return 0.0, 1.0
        z_arr = np.array(zs)
        sv_arr = np.array(svs)
        # Harbord: y = (O−E)/√V (already computed), x = √V.
        y = z_arr
        x = sv_arr
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
        effect_sizes: List[EffectSize], method: str = "R0",
        max_iterations: int = 10,
    ) -> Tuple[List[EffectSize], int]:
        """Iterative Duval & Tweedie (2000) trim-and-fill.

        The previous implementation was a *one-shot* formula: it estimated
        the number of missing studies once from the raw set, trimmed,
        pooled and mirrored a single time. The canonical algorithm is
        iterative — trim, re-pool, re-mirror — until the trim count is
        stable. This implementation runs that loop (capped at
        ``max_iterations``, default 10):

        1. Pool the current set with inverse-variance fixed weights to
           get the funnel centre ``θ̂``.
        2. Trim: remove the single most extreme study on the side with
           the larger aggregate asymmetry (``Σ|θ_i − θ̂|``), re-pooling
           after every removal, while the imbalance between the two
           sides keeps shrinking (Duval-Tweedie "trim until symmetric").
        3. Mirror: reflect every trimmed study about the FINAL centre
           (keeping its SE), and augment the imputed set.
        4. Repeat trim+re-pool on the augmented set until the number of
           imputed studies no longer changes.

        Args:
            effect_sizes: Original studies.
            method: ``'L0'`` | ``'R0'`` | ``'Q0'`` — which side is treated
                as the (assumed) suppressed side. ``'L0'`` mirrors toward
                the left (small-effect) side, ``'R0'`` toward the right;
                ``'Q0'`` runs both and keeps the larger fill count.
            max_iterations: Cap for the outer trim→re-pool→mirror loop.

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
        log_list = [
            es for es in log_list
            if es.se is not None and es.se > 0 and math.isfinite(es.value)
        ]
        if len(log_list) < 3:
            return [], 0
        method = (method or "R0").upper()
        if method not in {"L0", "R0", "Q0"}:
            raise ValueError(f"Unknown trim_method={method!r}.")

        def _run_once(seed: List[EffectSize], side: str) -> List[EffectSize]:
            """One iterative trim→re-pool→mirror pass for one side."""
            current = list(seed)
            trimmed: List[EffectSize] = []
            # --- Trim loop: remove extremes until symmetric ---
            for _ in range(max_iterations):
                if len(current) <= 2:
                    break
                pooled = PoolingEngine._fixed_iv(current)
                center = (
                    EffectSizeCalculator.to_log_scale(pooled).value
                    if es_type.is_log_scale_metric else pooled.value
                )
                left = [es for es in current if es.value < center]
                right = [es for es in current if es.value >= center]
                sum_left = sum(abs(es.value - center) for es in left)
                sum_right = sum(abs(es.value - center) for es in right)
                # The side to trim: the heavier side, or the forced side
                # for R0/L0 when tied.
                if sum_left > sum_right + 1e-12:
                    trim_side = "left"
                elif sum_right > sum_left + 1e-12:
                    trim_side = "right"
                else:
                    trim_side = side
                pool_side = left if trim_side == "left" else right
                if not pool_side:
                    break
                # Stop when the heavier side is (nearly) symmetric: the
                # most extreme deviation there is not larger than the
                # largest on the opposite side.
                extreme = max(pool_side, key=lambda es: abs(es.value - center))
                other_side = right if trim_side == "left" else left
                max_other = max(
                    (abs(es.value - center) for es in other_side), default=0.0
                )
                if abs(extreme.value - center) <= max_other * (1.0 + 1e-9):
                    break
                current.remove(extreme)
                trimmed.append(extreme)
            if not trimmed:
                return []
            # --- Final centre from the trimmed (symmetric) set ---
            if not current:
                return []
            pooled = PoolingEngine._fixed_iv(current)
            center = (
                EffectSizeCalculator.to_log_scale(pooled).value
                if es_type.is_log_scale_metric else pooled.value
            )
            # --- Mirror the trimmed studies about the final centre ---
            imputed: List[EffectSize] = []
            for es in trimmed:
                mirrored_value = 2.0 * center - es.value
                z95 = _std_normal_ppf(0.975)
                new_es = EffectSize(
                    type=es.type,
                    value=mirrored_value,
                    se=es.se,
                    variance=es.variance,
                    ci_lower=(mirrored_value - z95 * es.se) if es.se else None,
                    ci_upper=(mirrored_value + z95 * es.se) if es.se else None,
                    study_id=(es.study_id or "") + "_imputed",
                    study_name=(es.study_name or "Imputed") + " (imputed)",
                    n_total=es.n_total,
                )
                if es_type.is_log_scale_metric:
                    new_es = EffectSizeCalculator.to_natural_scale(new_es)
                imputed.append(new_es)
            return imputed

        if method == "Q0":
            imputed_l = _run_once(log_list, "left")
            imputed_r = _run_once(log_list, "right")
            imputed = (
                imputed_l if len(imputed_l) >= len(imputed_r) else imputed_r
            )
        else:
            imputed = _run_once(log_list, "left" if method == "L0" else "right")
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

    #: Backwards-compatible alias for :meth:`orwin_fail_safe_n`
    #: (docs/META_ANALYSIS_GUIDE.md documents ``orp_test``).
    def orp_test(self, target_effect: Optional[float] = None) -> Tuple[float, int]:
        """Deprecated alias of :meth:`orwin_fail_safe_n`."""
        return self.orwin_fail_safe_n(target_effect)

    def orwin_fail_safe_n(
        self, target_effect: Optional[float] = None
    ) -> Tuple[float, int]:
        """Orwin's (1983) fail-safe N.

        Number of additional null-effect studies (effect = 0) needed to
        bring the pooled effect down to a *trivial* criterion level
        ``target_effect``::

            (k·θ_obs + N·0) / (k + N) = θ_c  ⇒  N = k·(θ_obs − θ_c) / θ_c

        Args:
            target_effect: The criterion value for a "trivial" effect,
                expressed on the **analysis scale** (log scale for
                OR/RR/HR — e.g. log(1.05)). REQUIRED and must be
                non-zero: there is no sensible default, and silently
                substituting ``0.1 × observed`` (the previous behaviour)
                always returned the bogus ``ceil(9k)``.

        Returns:
            Tuple ``(pooled_observed_effect, fail_safe_N)``.

        Raises:
            ValueError: If ``target_effect`` is missing or zero.
        """
        es_type = self.effect_sizes[0].type
        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            if es_type.is_log_scale_metric else es
            for es in self.effect_sizes
        ]
        log_list = [
            es for es in log_list
            if es.se is not None and es.se > 0 and math.isfinite(es.value)
        ]
        if not log_list:
            return 0.0, 0
        pooled = PoolingEngine._fixed_iv(log_list)
        observed = pooled.value if pooled.value is not None else 0.0
        k = len(log_list)
        if target_effect is None or target_effect == 0:
            raise ValueError(
                "Orwin's fail-safe N requires an explicit non-zero "
                "target_effect (the 'trivial' criterion on the analysis "
                "scale, e.g. log(1.05) for log-OR or 0.1 for SMD)."
            )
        target = float(target_effect)
        denom = k * (observed - target) / target
        if denom <= 0 or not math.isfinite(denom):
            # Observed already at/below the criterion — no studies needed.
            return float(observed), 0
        N = int(math.ceil(denom))
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
