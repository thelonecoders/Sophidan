"""Pooling engines for meta-analysis.

Implements inverse-variance fixed-effect pooling, Mantel-Haenszel (OR/RR),
Peto, DerSimonian-Laird, REML, ML, Paule-Mandel, and empirical-Bayes random
effects, together with heterogeneity diagnostics (Q, I², H², τ²).

All heavy math (numpy, scipy) is lazy-imported inside the methods.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

from .effect_sizes import EffectSize, EffectSizeCalculator, EffectSizeType

logger = logging.getLogger(__name__)

__all__ = [
    "PoolingMethod",
    "Heterogeneity",
    "MetaAnalysisResult",
    "PoolingEngine",
]


class PoolingMethod(Enum):
    """Pooling strategies supported by :class:`PoolingEngine`."""

    FIXED = "fixed"        # inverse-variance fixed
    RANDOM = "random"      # alias for DerSimonian-Laird
    IV = "iv"              # inverse-variance fixed (alias)
    MH = "mh"              # Mantel-Haenszel (OR or RR)
    PETO = "peto"          # Peto one-step method for OR
    DL = "dl"              # DerSimonian-Laird random effects
    REML = "reml"          # REML estimator for tau²
    ML = "ml"              # maximum-likelihood estimator for tau²
    EB = "eb"              # empirical-Bayes (Morris 1983 / Berkey 1995)
    PAULE_MANDEL = "paule_mandel"  # Paule-Mandel (iterated) estimator

    @property
    def is_random_effects(self) -> bool:
        return self in {PoolingMethod.RANDOM, PoolingMethod.DL, PoolingMethod.REML,
                        PoolingMethod.ML, PoolingMethod.EB, PoolingMethod.PAULE_MANDEL}


# Default z multiplier for 95% CIs (kept for backwards compatibility).
_Z_95 = 1.959963984540054


def _z_from_confidence(confidence: float) -> float:
    """Return the two-sided normal quantile ``z`` for a confidence level.

    ``z = norm.ppf(1 - (1 - confidence) / 2)`` — e.g. 1.96 for 0.95,
    2.5758 for 0.99.  Falls back to a small lookup table when scipy is
    unavailable.
    """
    if not (0 < confidence < 1):
        raise ValueError("confidence must be in (0, 1).")
    try:
        from scipy.stats import norm  # type: ignore
        return float(norm.ppf(1.0 - (1.0 - confidence) / 2.0))
    except Exception:
        z_table = {0.90: 1.6448536269514722, 0.95: 1.959963984540054,
                   0.99: 2.5758293035489004}
        return z_table.get(round(confidence, 4), _Z_95)


@dataclass
class Heterogeneity:
    """Heterogeneity statistics for a meta-analysis.

    Attributes:
        I_squared: I² statistic (percent of variance due to between-study
            heterogeneity; range 0–100).
        H_squared: H² = Q / df.
        tau_squared: DerSimonian-Laird / REML between-study variance estimate.
        Q: Cochran's Q statistic.
        df: Degrees of freedom (= k − 1).
        p_value: P-value of Cochran's Q (chi-square test of homogeneity).
        interpretation: Human-readable qualitative interpretation of I².
    """

    I_squared: float
    H_squared: float
    tau_squared: float
    Q: float
    df: int
    p_value: float
    interpretation: str = ""

    def to_dict(self) -> dict:
        return {
            "I_squared": float(self.I_squared),
            "H_squared": float(self.H_squared),
            "tau_squared": float(self.tau_squared),
            "Q": float(self.Q),
            "df": int(self.df),
            "p_value": float(self.p_value),
            "interpretation": self.interpretation,
        }


@dataclass
class MetaAnalysisResult:
    """Result of a meta-analysis pool() call.

    Attributes:
        pooled_effect: The final pooled :class:`EffectSize` (on natural scale).
        heterogeneity: :class:`Heterogeneity` diagnostics.
        test_statistic: z-statistic for the pooled effect.
        p_value: Two-sided p-value for the pooled effect.
        method: The :class:`PoolingMethod` that was used.
        fixed_effects_pooled: Fixed-effect pooled :class:`EffectSize`.
        random_effects_pooled: Random-effects pooled :class:`EffectSize`
            (identical to ``fixed_effects_pooled`` when method is fixed).
        weights: Per-study weights used by the method.
        tau_squared: Between-study variance estimate.
        I_squared: I² statistic.
        Q_statistic: Cochran's Q.
        Q_p_value: P-value of the Q test.
        studies_count: Number of studies pooled.
        total_participants: Sum of ``n_total`` across studies (if available).
    """

    pooled_effect: EffectSize
    heterogeneity: Heterogeneity
    test_statistic: float
    p_value: float
    method: PoolingMethod
    fixed_effects_pooled: Optional[EffectSize] = None
    random_effects_pooled: Optional[EffectSize] = None
    weights: List[float] = field(default_factory=list)
    tau_squared: float = 0.0
    I_squared: float = 0.0
    Q_statistic: float = 0.0
    Q_p_value: float = 1.0
    studies_count: int = 0
    total_participants: int = 0
    #: Empirical-Bayes posterior (shrunken) per-study estimates — only
    #: populated for :attr:`PoolingMethod.EB`. Each entry is a dict with
    #: ``study_id``, ``observed``, ``shrunk`` and ``shrinkage_factor``
    #: (λ = τ²/(τ²+v); 0 = fully shrunk toward the pooled mean).
    shrunk_estimates: Optional[List[dict]] = None

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        return {
            "pooled_effect": self.pooled_effect.to_dict() if self.pooled_effect else None,
            "heterogeneity": self.heterogeneity.to_dict(),
            "test_statistic": float(self.test_statistic),
            "p_value": float(self.p_value),
            "method": self.method.value,
            "fixed_effects_pooled": self.fixed_effects_pooled.to_dict() if self.fixed_effects_pooled else None,
            "random_effects_pooled": self.random_effects_pooled.to_dict() if self.random_effects_pooled else None,
            "weights": list(self.weights),
            "tau_squared": float(self.tau_squared),
            "I_squared": float(self.I_squared),
            "Q_statistic": float(self.Q_statistic),
            "Q_p_value": float(self.Q_p_value),
            "studies_count": int(self.studies_count),
            "total_participants": int(self.total_participants),
            **({"shrunk_estimates": [dict(s) for s in self.shrunk_estimates]}
               if self.shrunk_estimates else {}),
        }

    def to_markdown(self) -> str:
        """Markdown table summarising the result."""
        pe = self.pooled_effect
        ci_str = ""
        if pe.ci_lower is not None and pe.ci_upper is not None:
            ci_str = f"{pe.ci_lower:.3f} to {pe.ci_upper:.3f}"
        return (
            f"## Meta-analysis summary\n\n"
            f"| Item | Value |\n|---|---|\n"
            f"| Effect type | {pe.type.value} |\n"
            f"| Pooled effect | {pe.value:.4f} |\n"
            f"| 95% CI | {ci_str} |\n"
            f"| z-statistic | {self.test_statistic:.3f} |\n"
            f"| p-value | {self.p_value:.4g} |\n"
            f"| Pooling method | {self.method.value} |\n"
            f"| Studies pooled | {self.studies_count} |\n"
            f"| Total participants | {self.total_participants} |\n"
            f"| Heterogeneity I² | {self.I_squared:.1f}% |\n"
            f"| τ² (between-study variance) | {self.tau_squared:.4f} |\n"
            f"| Q statistic (df={self.heterogeneity.df}) | "
            f"{self.Q_statistic:.3f} (p={self.Q_p_value:.4g}) |\n"
        )

    def summary_text(self) -> str:
        """One-paragraph narrative summary suitable for inclusion in a paper."""
        pe = self.pooled_effect
        ci_str = ""
        if pe.ci_lower is not None and pe.ci_upper is not None:
            ci_str = f" (95% CI {pe.ci_lower:.3f} to {pe.ci_upper:.3f})"
        sig = "statistically significant" if self.p_value < 0.05 else "not statistically significant"
        het = (
            f"Heterogeneity was low (I²={self.I_squared:.1f}%)"
            if self.I_squared < 25
            else f"Heterogeneity was moderate (I²={self.I_squared:.1f}%)"
            if self.I_squared < 50
            else f"Heterogeneity was substantial (I²={self.I_squared:.1f}%)"
            if self.I_squared < 75
            else f"Heterogeneity was considerable (I²={self.I_squared:.1f}%)"
        )
        return (
            f"Pooled analysis of {self.studies_count} studies "
            f"(N={self.total_participants} participants) using the "
            f"{self.method.value.upper()} method yielded a pooled "
            f"{pe.type.value} of {pe.value:.3f}{ci_str} (z={self.test_statistic:.2f}, "
            f"p={self.p_value:.4g}); the result was {sig}. {het} "
            f"(Q={self.Q_statistic:.2f}, df={self.heterogeneity.df}, "
            f"p={self.Q_p_value:.4g}; τ²={self.tau_squared:.4f})."
        )


class PoolingEngine:
    """Compute pooled effects for a list of :class:`EffectSize` objects."""

    # ------------------------------------------------------------------ #
    # Public dispatch
    # ------------------------------------------------------------------ #
    @staticmethod
    def pool(
        effect_sizes: List[EffectSize],
        method: PoolingMethod = PoolingMethod.DL,
        confidence: float = 0.95,
    ) -> MetaAnalysisResult:
        """Pool a list of effect sizes.

        Args:
            effect_sizes: List of :class:`EffectSize` (must all share the same
                metric type).
            method: Pooling strategy. Defaults to DerSimonian-Laird (DL).
            confidence: Confidence level for the pooled CI (default 0.95).

        Returns:
            A populated :class:`MetaAnalysisResult`.

        Raises:
            ValueError: If fewer than 2 studies, or if metrics are mixed.
        """
        if not effect_sizes:
            raise ValueError("effect_sizes list is empty.")
        if len(effect_sizes) == 1:
            logger.warning("pool() called with a single study — returning it as-is.")
        types = {es.type for es in effect_sizes}
        if len(types) > 1:
            raise ValueError(
                f"All effect sizes must share a metric type; got {types!r}."
            )
        es_type = effect_sizes[0].type

        # z multiplier honouring the requested confidence level end-to-end.
        z_mult = _z_from_confidence(confidence)

        # Always compute fixed-effect pool (for heterogeneity + comparison).
        fixed = PoolingEngine._fixed_iv(effect_sizes, z_mult=z_mult)
        Q, df = PoolingEngine._q_statistic(effect_sizes, fixed)
        Q_p = PoolingEngine._q_p_value(Q, df)
        # DL tau² (used as fallback / for I²).
        tau2_dl = PoolingEngine._tau2_dersimonian_laird(effect_sizes, fixed, Q, df)
        I2 = PoolingEngine._i_squared(effect_sizes, tau2_dl, Q=Q, df=df)

        # Dispatch the requested method.
        res = None  # set only by random-effects-style branches (DL/REML/ML/EB/PM)
        if method in {PoolingMethod.FIXED, PoolingMethod.IV}:
            pooled = fixed
            weights = PoolingEngine._iv_weights(effect_sizes)
            tau2 = 0.0
        elif method == PoolingMethod.MH:
            if es_type == EffectSizeType.OR:
                pooled = PoolingEngine._mh_or(effect_sizes, z_mult=z_mult)
            elif es_type == EffectSizeType.RR:
                pooled = PoolingEngine._mh_rr(effect_sizes, z_mult=z_mult)
            else:
                logger.warning("MH only supports OR/RR; falling back to IV fixed.")
                pooled = fixed
            weights = PoolingEngine._mh_weights(effect_sizes, es_type)
            tau2 = 0.0
        elif method == PoolingMethod.PETO:
            if es_type == EffectSizeType.OR:
                pooled = PoolingEngine._peto_or(effect_sizes, z_mult=z_mult)
            else:
                logger.warning("Peto only supports OR; falling back to IV fixed.")
                pooled = fixed
            weights = PoolingEngine._iv_weights(effect_sizes)
            tau2 = 0.0
        elif method in {PoolingMethod.DL, PoolingMethod.RANDOM}:
            res = PoolingEngine._dersimonian_laird(effect_sizes, z_mult=z_mult)
            pooled = res.pooled_effect
            weights = res.weights
            tau2 = res.tau_squared
        elif method == PoolingMethod.REML:
            res = PoolingEngine._reml(effect_sizes, z_mult=z_mult)
            pooled = res.pooled_effect
            weights = res.weights
            tau2 = res.tau_squared
        elif method == PoolingMethod.ML:
            res = PoolingEngine._ml(effect_sizes, z_mult=z_mult)
            pooled = res.pooled_effect
            weights = res.weights
            tau2 = res.tau_squared
        elif method == PoolingMethod.EB:
            res = PoolingEngine._empirical_bayes(effect_sizes, z_mult=z_mult)
            pooled = res.pooled_effect
            weights = res.weights
            tau2 = res.tau_squared
        elif method == PoolingMethod.PAULE_MANDEL:
            res = PoolingEngine._paule_mandel(effect_sizes, z_mult=z_mult)
            pooled = res.pooled_effect
            weights = res.weights
            tau2 = res.tau_squared
        else:
            raise ValueError(f"Unknown pooling method {method!r}.")

        # Random-effects result (DL) for the "both" fields.
        dl_res = PoolingEngine._dersimonian_laird(effect_sizes, z_mult=z_mult)

        # Compute test statistic & p-value on the analysis scale.
        test_es = pooled
        if pooled.type.is_log_scale_metric:
            test_es = EffectSizeCalculator.to_log_scale(pooled)
        if test_es.se is None or test_es.se <= 0:
            z = 0.0
            p = 1.0
        else:
            z = test_es.value / test_es.se
            p = 2.0 * (1.0 - _std_normal_cdf(abs(z)))

        het = Heterogeneity(
            I_squared=I2,
            H_squared=(Q / df) if df > 0 else float("nan"),
            tau_squared=tau2,
            Q=Q,
            df=int(df),
            p_value=Q_p,
            interpretation=PoolingEngine._i2_interpretation(I2),
        )

        total_n = sum((es.n_total or 0) for es in effect_sizes)

        shrunk = getattr(res, "shrunk_estimates", None) if res is not None else None
        return MetaAnalysisResult(
            pooled_effect=pooled,
            heterogeneity=het,
            test_statistic=float(z),
            p_value=float(p),
            method=method,
            fixed_effects_pooled=PoolingEngine._back_to_natural(fixed, es_type),
            random_effects_pooled=PoolingEngine._back_to_natural(
                dl_res.pooled_effect, es_type
            ),
            shrunk_estimates=list(shrunk) if shrunk else None,
            weights=list(weights),
            tau_squared=float(tau2),
            I_squared=float(I2),
            Q_statistic=float(Q),
            Q_p_value=float(Q_p),
            studies_count=len(effect_sizes),
            total_participants=int(total_n),
        )

    # ------------------------------------------------------------------ #
    # Scale helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_log_list(es_list: List[EffectSize]) -> List[EffectSize]:
        return [EffectSizeCalculator.to_log_scale(es) for es in es_list]

    @staticmethod
    def _back_to_natural(es: EffectSize, target_type: EffectSizeType) -> EffectSize:
        """Return ``es`` on the natural scale if its metric is log-scale."""
        if es is None:
            return None
        if target_type.is_log_scale_metric:
            return EffectSizeCalculator.to_natural_scale(es)
        return es

    # ------------------------------------------------------------------ #
    # Inverse-variance fixed
    # ------------------------------------------------------------------ #
    @staticmethod
    def _iv_weights(es_list: List[EffectSize]) -> List[float]:
        weights = []
        for es in es_list:
            v = es.variance if es.variance is not None else (es.se ** 2 if es.se else None)
            if v is None or v <= 0:
                logger.warning("EffectSize with zero/None variance — assigning zero weight.")
                weights.append(0.0)
            else:
                weights.append(1.0 / v)
        return weights

    @staticmethod
    def _fixed_iv(es_list: List[EffectSize], z_mult: float = _Z_95) -> EffectSize:
        """Inverse-variance fixed-effect pooling.

        For RR/OR/HR the pooling is performed on the log scale; the result is
        back-transformed to the natural scale before being returned.

        Args:
            es_list: Effect sizes to pool.
            z_mult: Two-sided normal quantile for the CI (honours the
                requested confidence level; 1.95996... for 95%).
        """
        if not es_list:
            raise ValueError("Cannot pool empty list.")
        log_list = PoolingEngine._to_log_list(es_list)
        weights = PoolingEngine._iv_weights(log_list)
        W = sum(weights)
        if W <= 0:
            raise ValueError("Total weight is zero — variances invalid.")
        theta = sum(w * es.value for w, es in zip(weights, log_list)) / W
        se = math.sqrt(1.0 / W)
        var = se * se
        ci_lo = theta - z_mult * se
        ci_hi = theta + z_mult * se
        # Construct on log scale, then back-transform.
        es_type = es_list[0].type
        log_pooled = EffectSize(
            type=es_type,
            value=theta,
            se=se,
            variance=var,
            ci_lower=ci_lo,
            ci_upper=ci_hi,
            n_total=sum((es.n_total or 0) for es in es_list),
        )
        return PoolingEngine._back_to_natural(log_pooled, es_type)

    # ------------------------------------------------------------------ #
    # Mantel-Haenszel
    # ------------------------------------------------------------------ #
    @staticmethod
    def _mh_weights(es_list: List[EffectSize], es_type: EffectSizeType) -> List[float]:
        """Return Mantel-Haenszel per-study weights (only meaningful for OR)."""
        weights = []
        for es in es_list:
            if (es.total_intervention is None or es.total_control is None
                    or es.events_intervention is None or es.events_control is None):
                # Fallback to IV weights.
                v = es.variance if es.variance is not None else (es.se ** 2 if es.se else 1.0)
                weights.append(1.0 / v if v > 0 else 0.0)
                continue
            n_i = es.total_intervention
            n_c = es.total_control
            N = n_i + n_c
            # MH weight for OR: w = n1i*n2i / N_i (correct for OR).
            weights.append((n_i * n_c) / float(N))
        return weights

    @staticmethod
    def _mh_or(es_list: List[EffectSize], z_mult: float = _Z_95) -> EffectSize:
        """Mantel-Haenszel pooled odds ratio.

        .. math::
            \\hat{OR}_{MH} = \\frac{\\sum a_i d_i / N_i}{\\sum b_i c_i / N_i}
        """
        a_sum, b_sum = 0.0, 0.0
        for es in es_list:
            if None in (es.events_intervention, es.total_intervention,
                        es.events_control, es.total_control):
                raise ValueError(
                    "MH pooling requires 2x2 cell counts — use "
                    "EffectSizeCalculator.from_dichotomous(...)."
                )
            a = es.events_intervention
            b = es.total_intervention - es.events_intervention
            c = es.events_control
            d = es.total_control - es.events_control
            N = es.total_intervention + es.total_control
            a_sum += (a * d) / float(N)
            b_sum += (b * c) / float(N)
        if b_sum == 0:
            raise ValueError("MH denominator is zero.")
        or_mh = a_sum / b_sum
        log_or = math.log(or_mh)
        # Robins-Breslow-Greenland (RBG) variance of log(OR_MH):
        #   V = R / (2 P^2) + S / (2 P Q) + T / (2 Q^2)
        # where P = Σ(a_i d_i / N_i), Q = Σ(b_i c_i / N_i) and the three
        # per-study sums (each divided by N_i^2) are:
        #   R_i = a_i d_i (a_i + d_i)
        #   S_i = a_i d_i (b_i + c_i) + b_i c_i (a_i + d_i)
        #   T_i = b_i c_i (b_i + c_i)
        # (Robins, Breslow & Greenland 1986; Greenland & Robins 1985.)
        P = a_sum
        Q = b_sum
        R_sum = S_sum = T_sum = 0.0
        for es in es_list:
            a = es.events_intervention
            b = es.total_intervention - es.events_intervention
            c = es.events_control
            d = es.total_control - es.events_control
            N = es.total_intervention + es.total_control
            N2 = float(N) ** 2
            R_sum += (a * d * (a + d)) / N2
            S_sum += (a * d * (b + c) + b * c * (a + d)) / N2
            T_sum += (b * c * (b + c)) / N2
        if P > 0 and Q > 0:
            var = (
                R_sum / (2.0 * P * P)
                + S_sum / (2.0 * P * Q)
                + T_sum / (2.0 * Q * Q)
            )
        else:
            var = 0.001
        se = math.sqrt(max(var, 0.0))
        return EffectSize(
            type=EffectSizeType.OR,
            value=float(or_mh),
            se=float(se),
            variance=float(var),
            ci_lower=float(math.exp(log_or - z_mult * se)),
            ci_upper=float(math.exp(log_or + z_mult * se)),
            n_total=sum((es.n_total or 0) for es in es_list),
        )

    @staticmethod
    def _mh_rr(es_list: List[EffectSize], z_mult: float = _Z_95) -> EffectSize:
        """Mantel-Haenszel pooled risk ratio.

        .. math::
            \\hat{RR}_{MH} = \\frac{\\sum a_i n_{Ci} / N_i}{\\sum c_i n_{Ti} / N_i}
        """
        num, denom = 0.0, 0.0
        for es in es_list:
            if None in (es.events_intervention, es.total_intervention,
                        es.events_control, es.total_control):
                raise ValueError(
                    "MH pooling requires 2x2 cell counts — use "
                    "EffectSizeCalculator.from_dichotomous(...)."
                )
            a = es.events_intervention
            n_t = es.total_intervention
            c = es.events_control
            n_c = es.total_control
            N = n_t + n_c
            num += (a * n_c) / float(N)
            denom += (c * n_t) / float(N)
        if denom == 0:
            raise ValueError("MH RR denominator is zero.")
        rr_mh = num / denom
        log_rr = math.log(rr_mh)
        # Approximate Greenland-Robins variance for log(RR_MH) using the
        # weighted-sum of within-study variances:
        #   Var ≈ Σ_i w_i^2 * Var_i / (Σ_i w_i)^2
        # where w_i = n_Ti * n_Ci / N_i and Var_i = 1/a_i - 1/n_t + 1/c_i - 1/n_c.
        num_v = 0.0
        W_sum = 0.0
        for es in es_list:
            a = es.events_intervention
            n_t = es.total_intervention
            c = es.events_control
            n_c = es.total_control
            N = n_t + n_c
            w = (n_t * n_c) / float(N)
            # Woolf log-RR variance, with continuity correction for zero cells.
            a_cc = a + (0.5 if a == 0 else 0.0)
            c_cc = c + (0.5 if c == 0 else 0.0)
            var_i = max(
                (1.0 / a_cc - 1.0 / n_t + 1.0 / c_cc - 1.0 / n_c), 1e-8
            )
            num_v += (w ** 2) * var_i
            W_sum += w
        if W_sum > 0:
            var = num_v / (W_sum ** 2)
        else:
            var = 0.001
        var = max(var, 0.0)
        se = math.sqrt(var)
        return EffectSize(
            type=EffectSizeType.RR,
            value=float(rr_mh),
            se=float(se),
            variance=float(var),
            ci_lower=float(math.exp(log_rr - z_mult * se)),
            ci_upper=float(math.exp(log_rr + z_mult * se)),
            n_total=sum((es.n_total or 0) for es in es_list),
        )

    # ------------------------------------------------------------------ #
    # Peto method
    # ------------------------------------------------------------------ #
    @staticmethod
    def _peto_or(es_list: List[EffectSize], z_mult: float = _Z_95) -> EffectSize:
        """Peto one-step method for pooling odds ratios.

        Uses observed vs expected events in the intervention arm.
        """
        O_minus_E = 0.0
        V_sum = 0.0
        for es in es_list:
            if None in (es.events_intervention, es.total_intervention,
                        es.events_control, es.total_control):
                raise ValueError(
                    "Peto pooling requires 2x2 cell counts — use "
                    "EffectSizeCalculator.from_dichotomous(...)."
                )
            a = es.events_intervention
            n_t = es.total_intervention
            c = es.events_control
            n_c = es.total_control
            N = n_t + n_c
            n_e = a + c  # total events
            # Expected events in intervention arm:
            E = n_t * n_e / float(N)
            # Peto variance of (O - E):
            V = (n_t * n_c * n_e * (N - n_e)) / (float(N) ** 2 * (N - 1)) \
                if N > 1 else 0.0
            O_minus_E += (a - E)
            V_sum += V
        if V_sum <= 0:
            raise ValueError("Peto variance is zero — cannot pool.")
        log_or = O_minus_E / V_sum
        se = math.sqrt(1.0 / V_sum)
        var = se * se
        return EffectSize(
            type=EffectSizeType.OR,
            value=float(math.exp(log_or)),
            se=float(se),
            variance=float(var),
            ci_lower=float(math.exp(log_or - z_mult * se)),
            ci_upper=float(math.exp(log_or + z_mult * se)),
            n_total=sum((es.n_total or 0) for es in es_list),
        )

    # ------------------------------------------------------------------ #
    # DerSimonian-Laird random effects
    # ------------------------------------------------------------------ #
    @staticmethod
    def _tau2_dersimonian_laird(
        es_list: List[EffectSize],
        fixed: EffectSize,
        Q: Optional[float] = None,
        df: Optional[int] = None,
    ) -> float:
        """Estimate τ² via the DerSimonian-Laird method-of-moments estimator."""
        log_list = PoolingEngine._to_log_list(es_list)
        weights = PoolingEngine._iv_weights(log_list)
        W = sum(weights)
        if W <= 0:
            return 0.0
        W2 = sum(w * w for w in weights)
        C = W - W2 / W
        if C <= 0:
            return 0.0
        if Q is None or df is None:
            Q, df = PoolingEngine._q_statistic(es_list, fixed)
        tau2 = (Q - df) / C
        return max(0.0, tau2)

    @staticmethod
    def _dersimonian_laird(es_list: List[EffectSize], z_mult: float = _Z_95) -> MetaAnalysisResult:
        """DerSimonian-Laird random-effects pooling."""
        log_list = PoolingEngine._to_log_list(es_list)
        weights = PoolingEngine._iv_weights(log_list)
        W = sum(weights)
        if W <= 0:
            raise ValueError("Total IV weight is zero — cannot pool.")
        # Fixed-effect estimate (on log scale):
        theta_fixed = sum(w * es.value for w, es in zip(weights, log_list)) / W
        # Q & tau²:
        Q = sum(w * (es.value - theta_fixed) ** 2 for w, es in zip(weights, log_list))
        df = len(es_list) - 1
        W2 = sum(w * w for w in weights)
        C = W - W2 / W
        tau2 = max(0.0, (Q - df) / C) if C > 0 else 0.0
        # Random-effects weights:
        re_weights = [1.0 / (v + tau2) for v in (
            es.variance if es.variance is not None else (es.se ** 2 if es.se else float("inf"))
            for es in log_list
        )]
        W_re = sum(re_weights)
        if W_re <= 0:
            raise ValueError("Total RE weight is zero — variances + tau² invalid.")
        theta_re = sum(w * es.value for w, es in zip(re_weights, log_list)) / W_re
        se_re = math.sqrt(1.0 / W_re)
        var_re = se_re * se_re
        # Back to natural scale:
        es_type = es_list[0].type
        log_pooled = EffectSize(
            type=es_type,
            value=theta_re,
            se=se_re,
            variance=var_re,
            ci_lower=theta_re - z_mult * se_re,
            ci_upper=theta_re + z_mult * se_re,
            n_total=sum((es.n_total or 0) for es in es_list),
        )
        pooled_natural = PoolingEngine._back_to_natural(log_pooled, es_type)
        I2 = PoolingEngine._i_squared(es_list, tau2, Q=Q, df=df)
        Q_p = PoolingEngine._q_p_value(Q, df)
        het = Heterogeneity(
            I_squared=I2,
            H_squared=(Q / df) if df > 0 else float("nan"),
            tau_squared=tau2,
            Q=Q,
            df=int(df),
            p_value=Q_p,
            interpretation=PoolingEngine._i2_interpretation(I2),
        )
        # z-test for pooled effect:
        z = theta_re / se_re if se_re > 0 else 0.0
        p = 2.0 * (1.0 - _std_normal_cdf(abs(z)))
        # Normalised percentage weights for display:
        pct_weights = [100.0 * w / W_re for w in re_weights]
        return MetaAnalysisResult(
            pooled_effect=pooled_natural,
            heterogeneity=het,
            test_statistic=float(z),
            p_value=float(p),
            method=PoolingMethod.DL,
            fixed_effects_pooled=PoolingEngine._back_to_natural(
                EffectSize(
                    type=es_type, value=theta_fixed,
                    se=math.sqrt(1.0 / W) if W > 0 else 0.0,
                    variance=1.0 / W if W > 0 else 0.0,
                    ci_lower=theta_fixed - z_mult * math.sqrt(1.0 / W) if W > 0 else None,
                    ci_upper=theta_fixed + z_mult * math.sqrt(1.0 / W) if W > 0 else None,
                    n_total=sum((es.n_total or 0) for es in es_list),
                ),
                es_type,
            ),
            random_effects_pooled=pooled_natural,
            weights=pct_weights,
            tau_squared=float(tau2),
            I_squared=float(I2),
            Q_statistic=float(Q),
            Q_p_value=float(Q_p),
            studies_count=len(es_list),
            total_participants=sum((es.n_total or 0) for es in es_list),
        )

    # ------------------------------------------------------------------ #
    # REML / ML / Paule-Mandel / EB estimators for τ²
    # ------------------------------------------------------------------ #
    @staticmethod
    def _reml(es_list: List[EffectSize], z_mult: float = _Z_95) -> MetaAnalysisResult:
        """REML estimator for τ² (Viechtbauer 2005 Fisher scoring).

        Solves the exact REML score equation for the intercept-only
        random-effects model::

            Σ w_i² (y_i − θ̂)² = W − Σ w_i² / W

        where ``w_i = 1/(v_i + τ²)`` and ``W = Σ w_i``.  This replaces the
        previous (incorrect) "DL-style" score equation; the root coincides
        with the maximum of the REML profile log-likelihood.
        """
        return PoolingEngine._iterative_tau2(es_list, estimator="reml", z_mult=z_mult)

    @staticmethod
    def _ml(es_list: List[EffectSize], z_mult: float = _Z_95) -> MetaAnalysisResult:
        """Maximum-likelihood estimator for τ².

        Solves the exact ML score equation::

            Σ w_i² (y_i − θ̂)² = W
        """
        return PoolingEngine._iterative_tau2(es_list, estimator="ml", z_mult=z_mult)

    @staticmethod
    def _paule_mandel(es_list: List[EffectSize], z_mult: float = _Z_95) -> MetaAnalysisResult:
        """Paule-Mandel (1982) iterated estimator for τ².

        Solves the unbiasedness (estimating) equation::

            Σ w_i (y_i − θ̂)² = k − 1
        """
        return PoolingEngine._iterative_tau2(
            es_list, estimator="paule_mandel", z_mult=z_mult
        )

    @staticmethod
    def _empirical_bayes(es_list: List[EffectSize], z_mult: float = _Z_95) -> MetaAnalysisResult:
        """Empirical-Bayes random-effects pooling (Morris 1983; Berkey et al. 1995).

        The EB estimate of τ² solves the same iterative equation as the
        Paule-Mandel estimator (the two methods are mathematically
        identical — Viechtbauer et al. 2015; metafor treats ``"EB"`` and
        ``"PM"`` as synonyms)::

            Σ w_i (y_i − θ̂)² = k − 1,   w_i = 1/(v_i + τ²)

        On top of the pooled estimate, the true empirical-Bayes posterior
        (shrinkage) estimates are computed for each study::

            θ_i^EB = λ_i y_i + (1 − λ_i) μ,   λ_i = τ² / (τ² + v_i)

        with μ the EB pooled mean — each study is shrunk toward the pooled
        mean with prior weight ``1/τ²``.  The shrunken estimates are
        attached to the result as ``shrunk_estimates``.
        """
        res = PoolingEngine._iterative_tau2(
            es_list, estimator="paule_mandel", z_mult=z_mult
        )
        res.method = PoolingMethod.EB
        # True EB shrinkage: posterior means with a N(μ, τ²) prior on θ_i.
        try:
            import numpy as np  # type: ignore
        except ImportError:
            return res
        log_list = PoolingEngine._to_log_list(es_list)
        tau2 = res.tau_squared
        es_type = es_list[0].type
        y = np.array([es.value for es in log_list], dtype=float)
        v = np.array([
            (es.variance if es.variance is not None else
             (es.se ** 2 if es.se else 1.0))
            for es in log_list
        ], dtype=float)
        mu = None
        if es_type.is_log_scale_metric:
            mu_log = res.pooled_effect
            mu_log = EffectSizeCalculator.to_log_scale(mu_log)
            mu = mu_log.value
        else:
            mu = res.pooled_effect.value
        shrunk: List[dict] = []
        if tau2 <= 0:
            # Degenerate prior — no shrinkage possible; λ undefined (0).
            for es, yi in zip(log_list, y.tolist()):
                shrunk.append({
                    "study_id": es.study_id or es.study_name or "",
                    "observed": float(
                        math.exp(yi) if es_type.is_log_scale_metric else es.value
                    ),
                    "shrunk": float(mu),
                    "shrinkage_factor": 0.0,
                })
        else:
            for es, yi, vi in zip(log_list, y.tolist(), v.tolist()):
                lam = tau2 / (tau2 + vi) if (tau2 + vi) > 0 else 0.0
                theta_eb = lam * yi + (1.0 - lam) * mu
                shrunk.append({
                    "study_id": es.study_id or es.study_name or "",
                    "observed": float(
                        math.exp(yi) if es_type.is_log_scale_metric else es.value
                    ),
                    "shrunk": float(
                        math.exp(theta_eb) if es_type.is_log_scale_metric else theta_eb
                    ),
                    "shrinkage_factor": float(lam),
                })
        res.shrunk_estimates = shrunk
        return res

    @staticmethod
    def _iterative_tau2(
        es_list: List[EffectSize],
        estimator: str = "reml",
        z_mult: float = _Z_95,
    ) -> MetaAnalysisResult:
        """Iterative τ² estimation via the exact ML / REML / PM score equations.

        The score equations (intercept-only random-effects model, with
        ``w_i = 1/(v_i + τ²)`` and ``θ̂ = Σw y / Σw``) are:

        * **REML** (Viechtbauer 2005, Fisher scoring):
          ``Σ w² (y − θ̂)² − (W − Σ w²/W) = 0``
        * **ML** (Hardy & Thompson 1996):
          ``Σ w² (y − θ̂)² − W = 0``
        * **PM / EB** (Paule & Mandel 1982):
          ``Σ w (y − θ̂)² − (k − 1) = 0``

        Root-finding uses :func:`scipy.optimize.brentq` (bracketed, robust);
        a damped Viechtbauer-style fixed-point iteration is used as the
        fallback when scipy is unavailable.  All equations are solved on
        the analysis (log) scale for RR/OR/HR metrics.
        """
        try:
            import numpy as np  # type: ignore
        except ImportError:  # pragma: no cover
            logger.warning("numpy unavailable — falling back to DerSimonian-Laird.")
            return PoolingEngine._dersimonian_laird(es_list, z_mult=z_mult)

        log_list = PoolingEngine._to_log_list(es_list)
        y = np.array([es.value for es in log_list], dtype=float)
        v = np.array([
            (es.variance if es.variance is not None else (es.se ** 2 if es.se else 1.0))
            for es in log_list
        ], dtype=float)
        v = np.where(np.isfinite(v) & (v > 0), v, 1.0)
        k = len(y)
        if k < 2:
            raise ValueError("Need at least 2 studies for iterative τ² estimation.")
        df = k - 1
        estimator = (estimator or "reml").lower()

        def _score(tau2_val: float) -> float:
            """Signed score whose root is the τ² estimate (≥ 0)."""
            tau2_val = max(0.0, float(tau2_val))
            w = 1.0 / (v + tau2_val)
            W = float(w.sum())
            theta = float((w * y).sum() / W)
            if estimator == "reml":
                return float((w * w * (y - theta) ** 2).sum()) - (W - float((w * w).sum()) / W)
            if estimator == "ml":
                return float((w * w * (y - theta) ** 2).sum()) - W
            # paule_mandel / eb
            return float((w * (y - theta) ** 2).sum()) - df

        def _fixed_point(tau2_val: float, maxiter: int = 200) -> float:
            """Damped fixed-point fallback (Viechtbauer-style iteration)."""
            tau2_val = max(0.0, float(tau2_val))
            for _ in range(maxiter):
                w = 1.0 / (v + tau2_val)
                W = float(w.sum())
                theta = float((w * y).sum() / W)
                rss2 = float((w * w * (y - theta) ** 2).sum())
                rss = float((w * (y - theta) ** 2).sum())
                if estimator == "reml":
                    s, denom = rss2 - (W - float((w * w).sum()) / W), float((w * w).sum())
                elif estimator == "ml":
                    s, denom = rss2 - W, float((w * w).sum())
                else:
                    s, denom = rss - df, W
                if denom <= 0:
                    break
                step = s / denom
                new_tau = max(0.0, tau2_val + step)
                if abs(new_tau - tau2_val) < 1e-10:
                    tau2_val = new_tau
                    break
                tau2_val = new_tau
            return tau2_val

        # Initial guess: DerSimonian-Laird.
        w0 = 1.0 / v
        W0 = float(w0.sum())
        theta0 = float((w0 * y).sum() / W0)
        Q0 = float((w0 * (y - theta0) ** 2).sum())
        W0sq = float((w0 * w0).sum())
        C0 = W0 - W0sq / W0
        tau2 = max(0.0, (Q0 - df) / C0) if C0 > 0 else 0.0

        tau2 = max(0.0, tau2)
        # Root-find on [0, hi]. If the score at 0 is already ≤ 0, τ̂² = 0
        # (the score is decreasing in τ² for all three estimators).
        hi = max(10.0 * float(v.max()), 10.0)
        s0 = _score(0.0)
        s_hi = _score(hi)
        try:
            from scipy.optimize import brentq  # type: ignore
            if s0 <= 0.0:
                tau2 = 0.0
            elif s0 * s_hi > 0:
                # No bracket — refine with the fixed-point iteration.
                tau2 = _fixed_point(tau2)
            else:
                tau2 = float(brentq(_score, 0.0, hi, maxiter=200, xtol=1e-12))
        except Exception as exc:  # pragma: no cover — scipy missing / solver issue
            logger.debug("τ² root solver unavailable (%s); using fixed-point.", exc)
            tau2 = _fixed_point(tau2)
        tau2 = max(0.0, float(tau2))

        # Final RE weights & pooled effect:
        w = 1.0 / (v + tau2)
        W = float(w.sum())
        theta = float((w * y).sum() / W)
        se = math.sqrt(1.0 / W)
        var = se * se
        es_type = es_list[0].type
        log_pooled = EffectSize(
            type=es_type,
            value=theta,
            se=se,
            variance=var,
            ci_lower=theta - z_mult * se,
            ci_upper=theta + z_mult * se,
            n_total=int(sum((es.n_total or 0) for es in es_list)),
        )
        pooled_natural = PoolingEngine._back_to_natural(log_pooled, es_type)
        # Heterogeneity stats (Cochran's Q on the IV scale):
        Q_val = Q0
        I2 = PoolingEngine._i_squared(es_list, tau2, Q=Q_val, df=df)
        Q_p = PoolingEngine._q_p_value(Q_val, df)
        het = Heterogeneity(
            I_squared=I2,
            H_squared=(Q_val / df) if df > 0 else float("nan"),
            tau_squared=tau2,
            Q=Q_val,
            df=int(df),
            p_value=Q_p,
            interpretation=PoolingEngine._i2_interpretation(I2),
        )
        z = theta / se if se > 0 else 0.0
        p = 2.0 * (1.0 - _std_normal_cdf(abs(z)))
        pct_weights = [100.0 * wi / W for wi in w.tolist()]
        method_enum = {
            "reml": PoolingMethod.REML,
            "ml": PoolingMethod.ML,
            "paule_mandel": PoolingMethod.PAULE_MANDEL,
        }.get(estimator, PoolingMethod.REML)
        return MetaAnalysisResult(
            pooled_effect=pooled_natural,
            heterogeneity=het,
            test_statistic=float(z),
            p_value=float(p),
            method=method_enum,
            fixed_effects_pooled=PoolingEngine._fixed_iv(es_list, z_mult=z_mult),
            random_effects_pooled=pooled_natural,
            weights=pct_weights,
            tau_squared=float(tau2),
            I_squared=float(I2),
            Q_statistic=float(Q_val),
            Q_p_value=float(Q_p),
            studies_count=len(es_list),
            total_participants=sum((es.n_total or 0) for es in es_list),
        )

    # ------------------------------------------------------------------ #
    # Heterogeneity statistics
    # ------------------------------------------------------------------ #
    @staticmethod
    def _q_statistic(
        es_list: List[EffectSize], pooled_effect: EffectSize
    ) -> Tuple[float, int]:
        """Cochran's Q = Σ w_i (θ_i − θ_pooled)².

        Computed on the analysis scale (log scale for RR/OR/HR).
        """
        if len(es_list) < 2:
            return 0.0, 0
        log_list = PoolingEngine._to_log_list(es_list)
        # Pooled on log scale:
        if pooled_effect.type.is_log_scale_metric:
            pooled_log = EffectSizeCalculator.to_log_scale(pooled_effect)
        else:
            pooled_log = pooled_effect
        weights = PoolingEngine._iv_weights(log_list)
        Q = sum(
            w * (es.value - pooled_log.value) ** 2
            for w, es in zip(weights, log_list)
        )
        return float(Q), len(es_list) - 1

    @staticmethod
    def _q_p_value(Q: float, df: int) -> float:
        """Upper-tail p-value of Cochran's Q under H₀: homogeneity."""
        if df <= 0 or Q <= 0:
            return 1.0
        try:
            from scipy.stats import chi2  # type: ignore
            return float(chi2.sf(Q, df))
        except Exception:
            # Wilson-Hilferty normal approximation fallback.
            z = ((Q / df) ** (1.0 / 3.0) - (1 - 2.0 / (9 * df))) / math.sqrt(2.0 / (9 * df))
            return float(max(0.0, min(1.0, 1.0 - _std_normal_cdf(z))))

    @staticmethod
    def _i_squared(
        es_list: List[EffectSize],
        tau_squared: float,
        Q: Optional[float] = None,
        df: Optional[int] = None,
    ) -> float:
        """I² = max(0, (Q − df) / Q) × 100."""
        if Q is None or df is None:
            fixed = PoolingEngine._fixed_iv(es_list)
            Q, df = PoolingEngine._q_statistic(es_list, fixed)
        if df <= 0 or Q <= 0:
            return 0.0
        return max(0.0, (Q - df) / Q) * 100.0

    @staticmethod
    def _i2_interpretation(I2: float) -> str:
        """Qualitative Cochrane interpretation of I² (Higgins 2003)."""
        if I2 < 25:
            level = "low"
        elif I2 < 50:
            level = "moderate"
        elif I2 < 75:
            level = "substantial"
        else:
            level = "considerable"
        return (
            f"I² = {I2:.1f}% → heterogeneity is {level} "
            f"(Cochrane thresholds: 25/50/75%)."
        )


# ---------------------------------------------------------------------- #
# Module-private helpers
# ---------------------------------------------------------------------- #
def _std_normal_cdf(x: float) -> float:
    """Standard normal CDF via erf — accurate to ~1e-7."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
