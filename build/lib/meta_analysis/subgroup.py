"""Subgroup & sensitivity analyses for meta-analysis.

* :class:`SubgroupAnalysis` — partition studies by a categorical subgroup,
  pool each subgroup, and compute Q-between (test for subgroup differences).
* :class:`SensitivityAnalysis` — leave-one-out, cumulative, influence
  diagnostics, Galbraith plot, radial plot, leave-one-out forest.

All heavy math (numpy, scipy, pandas, matplotlib, statsmodels) is
lazy-imported inside the methods.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from .effect_sizes import EffectSize, EffectSizeCalculator, EffectSizeType
from .pooling import PoolingEngine, PoolingMethod, MetaAnalysisResult

logger = logging.getLogger(__name__)

__all__ = [
    "SubgroupResult",
    "SubgroupAnalysis",
    "SensitivityAnalysis",
]


@dataclass
class SubgroupResult:
    """Result of a subgroup analysis.

    Attributes:
        subgroup_effects: Pooled effect per subgroup.
        Q_between: Heterogeneity BETWEEN subgroups (df = g − 1).
        Q_within: Heterogeneity WITHIN each subgroup (dict by subgroup name).
        p_value: p-value for the test of subgroup differences (Q-between).
        I_squared_within: I² within each subgroup.
    """

    subgroup_effects: Dict[str, EffectSize]
    Q_between: float
    Q_within: Dict[str, float]
    p_value: float
    I_squared_within: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "subgroup_effects": {k: v.to_dict() for k, v in self.subgroup_effects.items()},
            "Q_between": float(self.Q_between),
            "Q_within": {k: float(v) for k, v in self.Q_within.items()},
            "p_value": float(self.p_value),
            "I_squared_within": {k: float(v) for k, v in self.I_squared_within.items()},
        }

    def to_markdown(self) -> str:
        rows = ["| Subgroup | Pooled effect | 95% CI | I² within |",
                "|---|---|---|---|"]
        for name, es in self.subgroup_effects.items():
            ci = (
                f"{es.ci_lower:.3f} to {es.ci_upper:.3f}"
                if es.ci_lower is not None and es.ci_upper is not None
                else "—"
            )
            i2 = self.I_squared_within.get(name, float("nan"))
            rows.append(f"| {name} | {es.value:.3f} | {ci} | {i2:.1f}% |")
        rows.append("")
        rows.append(
            f"Test for subgroup differences: Q = {self.Q_between:.3f} "
            f"(p = {self.p_value:.4g})."
        )
        return "\n".join(rows)


class SubgroupAnalysis:
    """Subgroup meta-analysis.

    Pools each subgroup separately (default DerSimonian-Laird), then computes
    Q-between (between-subgroup heterogeneity) and Q-within (within-subgroup).
    """

    @staticmethod
    def analyze(
        effect_sizes: List[EffectSize],
        subgroups: Dict[str, str],
        method: Union[str, PoolingMethod] = PoolingMethod.DL,
    ) -> SubgroupResult:
        """Run subgroup analysis.

        Args:
            effect_sizes: List of :class:`EffectSize` objects (must have
                ``study_id`` populated).
            subgroups: Mapping ``study_id → subgroup_name``.
            method: Pooling method (default DL).

        Returns:
            :class:`SubgroupResult`.
        """
        if isinstance(method, str):
            method = PoolingMethod(method.lower())
        if not effect_sizes:
            raise ValueError("effect_sizes is empty.")
        # Partition by subgroup.
        groups: Dict[str, List[EffectSize]] = {}
        for es in effect_sizes:
            sid = es.study_id or ""
            grp = subgroups.get(sid)
            if grp is None:
                logger.warning("Study %r has no subgroup assignment; skipped.", sid)
                continue
            groups.setdefault(grp, []).append(es)
        if not groups:
            raise ValueError("No studies matched the subgroup mapping.")
        # Pool each subgroup.
        subgroup_effects: Dict[str, EffectSize] = {}
        Q_within: Dict[str, float] = {}
        I2_within: Dict[str, float] = {}
        df_within_total = 0
        Q_within_total = 0.0
        for name, es_list in groups.items():
            res = PoolingEngine.pool(es_list, method=method)
            subgroup_effects[name] = res.pooled_effect
            Q_within[name] = res.Q_statistic
            I2_within[name] = res.I_squared
            Q_within_total += res.Q_statistic
            df_within_total += max(len(es_list) - 1, 0)
        # Q-between: between-subgroup heterogeneity.
        # Q_total = Q_within + Q_between, where Q_total is computed from a
        # single grand-pool of all studies (regardless of subgroup).
        grand = PoolingEngine.pool(effect_sizes, method=PoolingMethod.FIXED)
        Q_total = grand.Q_statistic
        Q_between = max(0.0, Q_total - Q_within_total)
        df_between = max(len(groups) - 1, 0)
        p = SubgroupAnalysis._chi_square_p(Q_between, df_between)
        return SubgroupResult(
            subgroup_effects=subgroup_effects,
            Q_between=float(Q_between),
            Q_within={k: float(v) for k, v in Q_within.items()},
            p_value=float(p),
            I_squared_within={k: float(v) for k, v in I2_within.items()},
        )

    @staticmethod
    def test_for_subgroup_differences(
        effect_sizes: List[EffectSize],
        subgroups: Dict[str, str],
        method: Union[str, PoolingMethod] = PoolingMethod.DL,
    ) -> Tuple[float, float]:
        """Compute Q-between and its p-value (test for subgroup differences).

        Returns:
            Tuple ``(Q_between, p_value)``.
        """
        res = SubgroupAnalysis.analyze(effect_sizes, subgroups, method=method)
        return res.Q_between, res.p_value

    @staticmethod
    def _chi_square_p(Q: float, df: int) -> float:
        if df <= 0 or Q <= 0:
            return 1.0
        try:
            from scipy.stats import chi2  # type: ignore
            return float(chi2.sf(Q, df))
        except Exception:
            # Wilson-Hilferty approximation.
            z = ((Q / df) ** (1.0 / 3.0) - (1 - 2.0 / (9 * df))) / math.sqrt(2.0 / (9 * df))
            return float(max(0.0, min(1.0, 1.0 - 0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))))


class SensitivityAnalysis:
    """Sensitivity (leave-one-out, cumulative, influence) analyses."""

    # ------------------------------------------------------------------ #
    # Leave-one-out
    # ------------------------------------------------------------------ #
    @staticmethod
    def leave_one_out(
        effect_sizes: List[EffectSize],
        method: Union[str, PoolingMethod] = PoolingMethod.DL,
    ) -> List[MetaAnalysisResult]:
        """Leave-one-out sensitivity analysis.

        Runs N meta-analyses, each omitting one study.

        Returns:
            List of :class:`MetaAnalysisResult` (one per omitted study, in
            the same order as ``effect_sizes``).
        """
        if isinstance(method, str):
            method = PoolingMethod(method.lower())
        if len(effect_sizes) < 3:
            raise ValueError("Need at least 3 studies for leave-one-out.")
        results: List[MetaAnalysisResult] = []
        for i in range(len(effect_sizes)):
            subset = effect_sizes[:i] + effect_sizes[i + 1:]
            try:
                results.append(PoolingEngine.pool(subset, method=method))
            except Exception as e:
                logger.warning("Leave-one-out iteration %d failed: %s", i, e)
                results.append(None)
        return results

    # ------------------------------------------------------------------ #
    # Cumulative
    # ------------------------------------------------------------------ #
    @staticmethod
    def cumulative(
        effect_sizes: List[EffectSize],
        order_by: str = "year",
        method: Union[str, PoolingMethod] = PoolingMethod.DL,
    ) -> List[MetaAnalysisResult]:
        """Cumulative meta-analysis.

        Sorts studies by ``order_by`` ('year' | 'weight' | 'precision'),
        then runs N cumulative MAs of the first k studies for k = 2..N.

        Returns:
            List of :class:`MetaAnalysisResult` (length N − 1).
        """
        if isinstance(method, str):
            method = PoolingMethod(method.lower())
        if len(effect_sizes) < 3:
            raise ValueError("Need at least 3 studies for cumulative MA.")
        if order_by == "year":
            ordered = sorted(
                effect_sizes,
                key=lambda es: (es.year if es.year is not None else float("inf")),
            )
        elif order_by == "weight":
            # Approximate weight = 1/variance.
            ordered = sorted(
                effect_sizes,
                key=lambda es: -(1.0 / (es.variance or 1.0)),
            )
        elif order_by == "precision":
            ordered = sorted(
                effect_sizes,
                key=lambda es: (es.se if es.se is not None else float("inf")),
            )
        else:
            raise ValueError(f"Unknown order_by={order_by!r}")
        results: List[MetaAnalysisResult] = []
        for k in range(2, len(ordered) + 1):
            results.append(PoolingEngine.pool(ordered[:k], method=method))
        return results

    # ------------------------------------------------------------------ #
    # Influence diagnostics
    # ------------------------------------------------------------------ #
    @staticmethod
    def influence_diagnosis(
        effect_sizes: List[EffectSize],
        method: Union[str, PoolingMethod] = PoolingMethod.DL,
    ) -> Dict[str, Dict[str, float]]:
        """Compute per-study influence diagnostics.

        Returns a dict ``{study_id: {'DFFITS': ..., 'cooks_d': ..., 'pooled_with': ..., 'pooled_without': ...}}``.

        DFFITS = (θ̂_with − θ̂_without) / SE(θ̂_without)
        Cook's distance = (θ̂_with − θ̂_without)² / (p · MSE)
        """
        if isinstance(method, str):
            method = PoolingMethod(method.lower())
        if len(effect_sizes) < 3:
            raise ValueError("Need at least 3 studies for influence diagnosis.")
        full = PoolingEngine.pool(effect_sizes, method=method)
        theta_full = full.pooled_effect.value
        # Use the fixed-effect variance as the reference SE.
        se_full = full.fixed_effects_pooled.se or 1.0
        # MSE = mean residual variance.
        try:
            import numpy as np  # type: ignore
            log_list = [
                EffectSizeCalculator.to_log_scale(es)
                if es.type.is_log_scale_metric else es
                for es in effect_sizes
            ]
            vs = np.array([
                (es.variance if es.variance is not None else (es.se ** 2 if es.se else 1.0))
                for es in log_list
            ])
            mse = float(np.mean(vs))
        except Exception:
            mse = 1.0
        p = 1  # parameters in the model
        out: Dict[str, Dict[str, float]] = {}
        for i, es in enumerate(effect_sizes):
            sid = es.study_id or f"study_{i}"
            subset = effect_sizes[:i] + effect_sizes[i + 1:]
            try:
                without = PoolingEngine.pool(subset, method=method)
            except Exception as e:
                logger.warning("Influence: pool without study %s failed: %s", sid, e)
                continue
            theta_without = without.pooled_effect.value
            se_without = without.fixed_effects_pooled.se or 1.0
            dffits = (theta_full - theta_without) / se_without if se_without > 0 else 0.0
            cooks = ((theta_full - theta_without) ** 2) / (p * mse) if mse > 0 else 0.0
            out[sid] = {
                "DFFITS": float(dffits),
                "cooks_d": float(cooks),
                "pooled_with": float(theta_full),
                "pooled_without": float(theta_without),
            }
        return out

    # ------------------------------------------------------------------ #
    # Plots
    # ------------------------------------------------------------------ #
    @staticmethod
    def galbraith_plot(
        effect_sizes: List[EffectSize],
        pooled: Optional[EffectSize] = None,
    ):
        """Galbraith (radial) plot of standardized effect vs precision.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        import matplotlib  # type: ignore
        matplotlib.use("Agg", force=False)
        import matplotlib.pyplot as plt  # type: ignore
        import numpy as np  # type: ignore

        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = [
            "Noto Sans SC", "DejaVu Sans", "Arial",
        ]
        plt.rcParams["axes.unicode_minus"] = False

        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            if es.type.is_log_scale_metric else es
            for es in effect_sizes
        ]
        # z_i = theta_i / se_i ; precision_i = 1/se_i.
        z = np.array([es.value / es.se for es in log_list if es.se and es.se > 0])
        prec = np.array([1.0 / es.se for es in log_list if es.se and es.se > 0])
        if pooled is None:
            pooled = PoolingEngine._fixed_iv(effect_sizes)
        if pooled.type.is_log_scale_metric:
            pooled_log = EffectSizeCalculator.to_log_scale(pooled)
        else:
            pooled_log = pooled
        slope = pooled_log.value

        fig, ax = plt.subplots(figsize=(8, 8), constrained_layout=True)
        ax.scatter(prec, z, c="#4C72B0", s=60, edgecolors="white", linewidths=1.0)
        x_max = prec.max() * 1.1 if len(prec) else 1.0
        x_vals = np.array([0, x_max])
        ax.plot(x_vals, slope * x_vals, "--", color="#C44E52", lw=1.5,
                label=f"Pooled effect = {slope:.3f}")
        # 95% CI band on the regression line.
        se_slope = pooled_log.se if pooled_log.se else 0.0
        upper = (slope + 1.96 * se_slope) * x_vals
        lower = (slope - 1.96 * se_slope) * x_vals
        ax.fill_between(x_vals, lower, upper, color="#C44E52", alpha=0.15,
                        label="95% CI")
        ax.set_xlabel("Precision (1 / SE)")
        ax.set_ylabel("Standardized effect (z = θ / SE)")
        ax.set_title("Galbraith (radial) plot")
        ax.legend(loc="best", frameon=True)
        ax.set_xlim(left=0)
        return fig

    @staticmethod
    def radial_plot(
        effect_sizes: List[EffectSize],
        pooled: Optional[EffectSize] = None,
    ):
        """Radial plot — OR vs SE; tests for asymmetry.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        # A radial plot is a polar projection of the Galbraith plot.
        import matplotlib  # type: ignore
        matplotlib.use("Agg", force=False)
        import matplotlib.pyplot as plt  # type: ignore
        import numpy as np  # type: ignore

        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        log_list = [
            EffectSizeCalculator.to_log_scale(es)
            if es.type.is_log_scale_metric else es
            for es in effect_sizes
        ]
        z = np.array([es.value / es.se for es in log_list if es.se and es.se > 0])
        prec = np.array([1.0 / es.se for es in log_list if es.se and es.se > 0])
        if pooled is None:
            pooled = PoolingEngine._fixed_iv(effect_sizes)
        slope = (
            EffectSizeCalculator.to_log_scale(pooled).value
            if pooled.type.is_log_scale_metric else pooled.value
        )

        # Convert (prec, z) → polar (angle = arctan(z / prec), radius = sqrt(prec² + z²)).
        # But the conventional radial plot uses angle = arctan(z / prec).
        angle = np.arctan(z / prec) if len(z) else np.array([])
        radius = np.sqrt(prec ** 2 + z ** 2) if len(z) else np.array([])

        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={"projection": "polar"},
                              constrained_layout=True)
        ax.scatter(angle, radius, c="#4C72B0", s=60, edgecolors="white")
        # Pooled line: angle = arctan(slope).
        pooled_angle = math.atan(slope)
        r_max = float(radius.max() * 1.1) if len(radius) else 1.0
        ax.plot([pooled_angle, pooled_angle], [0, r_max], "--", color="#C44E52",
                lw=1.5, label=f"Pooled (slope={slope:.3f})")
        ax.set_theta_zero_location("E")
        ax.set_theta_direction(1)
        ax.set_title("Radial plot (polar)", pad=20)
        ax.legend(loc="upper right", bbox_to_anchor=(1.2, 1.1))
        return fig

    @staticmethod
    def leave_one_out_forest(
        effect_sizes: List[EffectSize],
        method: Union[str, PoolingMethod] = PoolingMethod.DL,
    ):
        """Forest plot of leave-one-out results.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        # Lazy import to avoid circular dependency at module load time.
        from .forest_plot import ForestPlot

        if isinstance(method, str):
            method = PoolingMethod(method.lower())
        loo_results = SensitivityAnalysis.leave_one_out(effect_sizes, method=method)
        # Synthesize pseudo-effect-sizes from LOO pooled estimates.
        pseudo_es: List[EffectSize] = []
        names: List[str] = []
        for i, res in enumerate(loo_results):
            if res is None:
                continue
            pe = res.pooled_effect
            pseudo_es.append(EffectSize(
                type=pe.type,
                value=pe.value,
                se=pe.se,
                ci_lower=pe.ci_lower,
                ci_upper=pe.ci_upper,
                variance=pe.variance,
                study_id=effect_sizes[i].study_id or f"omit_{i}",
                study_name=f"omit {effect_sizes[i].study_name or effect_sizes[i].study_id or i}",
            ))
            names.append(pseudo_es[-1].study_name)
        full = PoolingEngine.pool(effect_sizes, method=method)
        fp = ForestPlot(
            effect_sizes=pseudo_es,
            pooled=full.pooled_effect,
            title="Leave-one-out sensitivity analysis",
            study_names=names,
        )
        return fp.render(style="cochrane")
