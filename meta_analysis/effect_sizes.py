"""Effect-size computation for meta-analysis.

This module implements effect-size types (mean difference, standardized mean
difference, risk ratio, odds ratio, hazard ratio, risk difference, relative
risk reduction, number needed to treat) and the :class:`EffectSizeCalculator`
that converts raw study data into :class:`EffectSize` objects ready for
pooling by :mod:`meta_analysis.pooling`.

All heavy math (numpy, scipy) is lazy-imported inside the methods so the
module remains importable on minimal environments.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Tuple, Union

logger = logging.getLogger(__name__)

__all__ = [
    "EffectSizeType",
    "EffectSize",
    "ContinuousGroup",
    "EffectSizeCalculator",
]


class EffectSizeType(Enum):
    """Supported effect-size metrics."""

    MD = "MD"           # Mean difference
    SMD = "SMD"         # Standardized mean difference (Cohen's d / Hedges' g / Glass' Δ)
    RR = "RR"           # Risk ratio
    OR = "OR"           # Odds ratio
    HR = "HR"           # Hazard ratio
    RD = "RD"           # Risk difference
    RRR = "RRR"         # Relative risk reduction
    NNT = "NNT"         # Number needed to treat

    @property
    def is_log_scale_metric(self) -> bool:
        """True for RR / OR / HR — metrics that are analysed on the log scale."""
        return self in {EffectSizeType.RR, EffectSizeType.OR, EffectSizeType.HR}

    @property
    def null_value(self) -> float:
        """Value of the effect under the null hypothesis of no effect."""
        if self in {EffectSizeType.MD, EffectSizeType.SMD, EffectSizeType.RD}:
            return 0.0
        # RR, OR, HR, RRR are ratio metrics — null is 1 (or log-scale 0).
        return 1.0


@dataclass
class ContinuousGroup:
    """Summary statistics for a continuous outcome arm.

    Attributes:
        n: Number of participants.
        mean: Sample mean.
        sd: Sample standard deviation.
    """

    n: int
    mean: float
    sd: float

    def __post_init__(self) -> None:
        if self.n <= 0:
            raise ValueError(f"ContinuousGroup.n must be > 0, got {self.n}")
        if self.sd < 0:
            raise ValueError(f"ContinuousGroup.sd must be >= 0, got {self.sd}")


@dataclass
class EffectSize:
    """A single study's effect estimate with uncertainty.

    Attributes:
        type: Metric type (MD/SMD/RR/OR/HR/RD/RRR/NNT).
        value: Point estimate on the **natural** scale (e.g. RR=1.5, SMD=0.4).
        se: Standard error of ``value`` (on natural scale for MD/SMD/RD,
            on log scale for RR/OR/HR — see ``EffectSizeCalculator.to_log_scale``).
        ci_lower: Lower bound of the (1-α) confidence interval.
        ci_upper: Upper bound of the (1-α) confidence interval.
        variance: Variance of ``value`` (= ``se**2`` when not otherwise given).
        weight: Pooled-analysis weight (filled in by ``PoolingEngine``).
        n_total: Total participants (intervention + control).
        study_id: Stable identifier of the study.
        study_name: Human-readable study name (for forest plots).
        group_intervention: Label of the intervention arm.
        group_control: Label of the control arm.
    """

    type: EffectSizeType
    value: float
    se: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    variance: Optional[float] = None
    weight: Optional[float] = None
    n_total: Optional[int] = None
    study_id: Optional[str] = None
    study_name: Optional[str] = None
    group_intervention: Optional[str] = None
    group_control: Optional[str] = None
    # 2x2-table cell counts (filled in by ``from_dichotomous``); needed for
    # Mantel-Haenszel and Peto pooling which use exact cell counts rather
    # than inverse-variance weights.
    events_intervention: Optional[int] = None
    total_intervention: Optional[int] = None
    events_control: Optional[int] = None
    total_control: Optional[int] = None
    # Optional study metadata used for cumulative & subgroup analyses.
    year: Optional[int] = None

    def __post_init__(self) -> None:
        # Derive variance / se if either is missing.
        if self.variance is None and self.se is not None:
            self.variance = float(self.se) ** 2
        if self.se is None and self.variance is not None:
            self.se = math.sqrt(self.variance) if self.variance >= 0 else None
        # Derive CI if either bound is missing (95% default).
        if (self.ci_lower is None or self.ci_upper is None) and self.se is not None:
            lo, hi = EffectSizeCalculator.confidence_interval(self, confidence=0.95)
            if self.ci_lower is None:
                self.ci_lower = lo
            if self.ci_upper is None:
                self.ci_upper = hi

    def to_dict(self) -> dict:
        """Serialize to a plain dict (dataclasses.asdict-friendly)."""
        d = asdict(self)
        d["type"] = self.type.value
        return d

    @property
    def is_log_scale_metric(self) -> bool:
        """True if the metric is normally analysed on the log scale."""
        return self.type.is_log_scale_metric


class EffectSizeCalculator:
    """Factory + transformer for :class:`EffectSize` objects."""

    # ------------------------------------------------------------------ #
    # Continuous outcomes
    # ------------------------------------------------------------------ #
    @staticmethod
    def pooled_sd(sd1: float, n1: int, sd2: float, n2: int) -> float:
        """Pooled standard deviation using the two-sample t-test denominator.

        .. math::
            s_{pooled} = \\sqrt{ \\frac{(n_1-1)s_1^2 + (n_2-1)s_2^2}{n_1+n_2-2} }

        Args:
            sd1, n1: SD & sample size of arm 1.
            sd2, n2: SD & sample size of arm 2.

        Returns:
            Pooled SD (>= 0).
        """
        if n1 + n2 <= 2:
            raise ValueError("Need n1 + n2 > 2 to pool SDs.")
        num = (n1 - 1) * sd1 ** 2 + (n2 - 1) * sd2 ** 2
        denom = n1 + n2 - 2
        return math.sqrt(max(num / denom, 0.0))

    @staticmethod
    def cohen_d(g1: ContinuousGroup, g2: ContinuousGroup) -> float:
        """Cohen's *d* standardized mean difference (pooled-SD denominator)."""
        sd_p = EffectSizeCalculator.pooled_sd(g1.sd, g1.n, g2.sd, g2.n)
        if sd_p <= 0:
            raise ValueError("Pooled SD is zero — cannot compute Cohen's d.")
        return (g1.mean - g2.mean) / sd_p

    @staticmethod
    def hedges_g(d: float, n1: int, n2: int) -> float:
        """Apply Hedges' small-sample bias-correction to Cohen's *d*.

        Correction factor:
        .. math:: J = 1 - \\frac{3}{4(n_1+n_2)-9}
        """
        N = n1 + n2
        if N <= 3:
            return float(d)
        J = 1.0 - 3.0 / (4.0 * N - 9.0)
        return d * J

    @staticmethod
    def glass_delta(g1: ContinuousGroup, g2: ContinuousGroup) -> float:
        """Glass' Δ — uses the **control** arm SD as the denominator.

        ``g1`` is the intervention arm, ``g2`` is the control arm.
        """
        if g2.sd <= 0:
            raise ValueError("Control SD is zero — cannot compute Glass' Δ.")
        return (g1.mean - g2.mean) / g2.sd

    @staticmethod
    def from_continuous(
        intervention: ContinuousGroup,
        control: ContinuousGroup,
        type: str = "SMD",
        smd_method: str = "cohen",
    ) -> EffectSize:
        """Build an :class:`EffectSize` from two continuous-arm summaries.

        Args:
            intervention: Intervention-arm ``ContinuousGroup``.
            control: Control-arm ``ContinuousGroup``.
            type: ``'SMD'`` (standardized MD) or ``'MD'`` (raw mean difference).
            smd_method: When ``type='SMD'``, one of ``'cohen'``, ``'hedges'``,
                ``'glass'``.

        Returns:
            Populated :class:`EffectSize`.
        """
        n_i, n_c = intervention.n, control.n
        n_total = n_i + n_c
        if type.upper() == "MD":
            md = intervention.mean - control.mean
            sd_p = EffectSizeCalculator.pooled_sd(
                intervention.sd, n_i, control.sd, n_c
            )
            se = sd_p * math.sqrt(1.0 / n_i + 1.0 / n_c)
            var = se * se
            ci_lo = md - 1.96 * se
            ci_hi = md + 1.96 * se
            return EffectSize(
                type=EffectSizeType.MD,
                value=float(md),
                se=float(se),
                variance=float(var),
                ci_lower=float(ci_lo),
                ci_upper=float(ci_hi),
                n_total=n_total,
                group_intervention="intervention",
                group_control="control",
            )
        elif type.upper() == "SMD":
            method = smd_method.lower()
            if method == "cohen":
                d = EffectSizeCalculator.cohen_d(intervention, control)
            elif method == "hedges":
                d_raw = EffectSizeCalculator.cohen_d(intervention, control)
                d = EffectSizeCalculator.hedges_g(d_raw, n_i, n_c)
            elif method == "glass":
                d = EffectSizeCalculator.glass_delta(intervention, control)
            else:
                raise ValueError(
                    f"Unknown smd_method={smd_method!r} (use cohen/hedges/glass)."
                )
            # Variance of SMD (Hedges & Olkin 1985):
            #   V(d) = (n1+n2)/(n1*n2) + d^2 / (2*(n1+n2))
            var = (n_i + n_c) / (n_i * n_c) + d ** 2 / (2.0 * (n_i + n_c))
            se = math.sqrt(var)
            ci_lo = d - 1.96 * se
            ci_hi = d + 1.96 * se
            return EffectSize(
                type=EffectSizeType.SMD,
                value=float(d),
                se=float(se),
                variance=float(var),
                ci_lower=float(ci_lo),
                ci_upper=float(ci_hi),
                n_total=n_total,
                group_intervention="intervention",
                group_control="control",
            )
        else:
            raise ValueError(f"Unsupported continuous effect type {type!r}.")

    @staticmethod
    def from_mean_diff(
        mean_diff: float,
        sd_pooled: float,
        n_intervention: int,
        n_control: int,
    ) -> EffectSize:
        """Construct an MD :class:`EffectSize` from a pre-computed mean difference."""
        if n_intervention <= 0 or n_control <= 0:
            raise ValueError("Sample sizes must be > 0.")
        se = sd_pooled * math.sqrt(1.0 / n_intervention + 1.0 / n_control)
        var = se * se
        return EffectSize(
            type=EffectSizeType.MD,
            value=float(mean_diff),
            se=float(se),
            variance=float(var),
            ci_lower=float(mean_diff - 1.96 * se),
            ci_upper=float(mean_diff + 1.96 * se),
            n_total=n_intervention + n_control,
            group_intervention="intervention",
            group_control="control",
        )

    # ------------------------------------------------------------------ #
    # Dichotomous outcomes (2x2 table)
    # ------------------------------------------------------------------ #
    @staticmethod
    def from_dichotomous(
        events_intervention: int,
        total_intervention: int,
        events_control: int,
        total_control: int,
        type: str = "OR",
    ) -> EffectSize:
        """Build an :class:`EffectSize` from a 2×2 table.

        Args:
            events_intervention: Events in the intervention arm.
            total_intervention: Total in the intervention arm.
            events_control: Events in the control arm.
            total_control: Total in the control arm.
            type: ``'OR'`` | ``'RR'`` | ``'RD'``.

        Returns:
            Populated :class:`EffectSize` (with continuity correction of 0.5
            applied to zero cells for OR/RR).
        """
        a = events_intervention
        b = total_intervention - events_intervention
        c = events_control
        d = total_control - events_control
        if a < 0 or b < 0 or c < 0 or d < 0:
            raise ValueError("Cell counts must be non-negative.")
        if total_intervention <= 0 or total_control <= 0:
            raise ValueError("Totals must be > 0.")

        # Continuity correction if any cell is zero (for OR/RR).
        cc = 0.0
        if type.upper() in {"OR", "RR"} and min(a, b, c, d) == 0:
            cc = 0.5
        a2, b2, c2, d2 = a + cc, b + cc, c + cc, d + cc

        if type.upper() == "OR":
            or_val = (a2 * d2) / (b2 * c2)
            log_or = math.log(or_val)
            # Woolf's SE of log OR:
            se = math.sqrt(1.0 / a2 + 1.0 / b2 + 1.0 / c2 + 1.0 / d2)
            var = se * se
            ci_lo = math.exp(log_or - 1.96 * se)
            ci_hi = math.exp(log_or + 1.96 * se)
            return EffectSize(
                type=EffectSizeType.OR,
                value=float(or_val),
                se=float(se),
                variance=float(var),
                ci_lower=float(ci_lo),
                ci_upper=float(ci_hi),
                n_total=total_intervention + total_control,
                group_intervention="intervention",
                group_control="control",
                events_intervention=int(events_intervention),
                total_intervention=int(total_intervention),
                events_control=int(events_control),
                total_control=int(total_control),
            )
        elif type.upper() == "RR":
            p_i = a2 / (a2 + b2)
            p_c = c2 / (c2 + d2)
            rr = p_i / p_c
            log_rr = math.log(rr)
            se = math.sqrt(
                1.0 / a2 - 1.0 / (a2 + b2) + 1.0 / c2 - 1.0 / (c2 + d2)
            )
            var = se * se
            ci_lo = math.exp(log_rr - 1.96 * se)
            ci_hi = math.exp(log_rr + 1.96 * se)
            return EffectSize(
                type=EffectSizeType.RR,
                value=float(rr),
                se=float(se),
                variance=float(var),
                ci_lower=float(ci_lo),
                ci_upper=float(ci_hi),
                n_total=total_intervention + total_control,
                group_intervention="intervention",
                group_control="control",
                events_intervention=int(events_intervention),
                total_intervention=int(total_intervention),
                events_control=int(events_control),
                total_control=int(total_control),
            )
        elif type.upper() == "RD":
            p_i = a / total_intervention
            p_c = c / total_control
            rd = p_i - p_c
            se = math.sqrt(
                p_i * (1 - p_i) / total_intervention
                + p_c * (1 - p_c) / total_control
            )
            var = se * se
            return EffectSize(
                type=EffectSizeType.RD,
                value=float(rd),
                se=float(se),
                variance=float(var),
                ci_lower=float(rd - 1.96 * se),
                ci_upper=float(rd + 1.96 * se),
                n_total=total_intervention + total_control,
                group_intervention="intervention",
                group_control="control",
                events_intervention=int(events_intervention),
                total_intervention=int(total_intervention),
                events_control=int(events_control),
                total_control=int(total_control),
            )
        else:
            raise ValueError(f"Unsupported dichotomous effect type {type!r}.")

    # ------------------------------------------------------------------ #
    # Time-to-event (hazard ratio)
    # ------------------------------------------------------------------ #
    @staticmethod
    def from_hazard_ratio(
        hr: float, ci_lower: float, ci_upper: float
    ) -> EffectSize:
        """Build an :class:`EffectSize` from a reported HR + CI.

        The reported CI is used to back-calculate the SE of the log-HR.
        """
        if hr <= 0 or ci_lower <= 0 or ci_upper <= 0:
            raise ValueError("HR and CI bounds must be strictly positive.")
        log_hr = math.log(hr)
        # CI symmetric on log scale:
        #   log(upper) - log(lower) = 2 * 1.96 * SE
        se = (math.log(ci_upper) - math.log(ci_lower)) / (2.0 * 1.96)
        var = se * se
        ci_lo = math.exp(log_hr - 1.96 * se)
        ci_hi = math.exp(log_hr + 1.96 * se)
        return EffectSize(
            type=EffectSizeType.HR,
            value=float(hr),
            se=float(se),
            variance=float(var),
            ci_lower=float(ci_lo),
            ci_upper=float(ci_hi),
        )

    # ------------------------------------------------------------------ #
    # Scale transformations
    # ------------------------------------------------------------------ #
    @staticmethod
    def to_log_scale(es: EffectSize) -> EffectSize:
        """Return a copy of ``es`` with value/CI transformed to the log scale.

        For RR/OR/HR the standard meta-analytic practice is to pool on the
        log scale (variance is symmetric there).  MD/SMD/RD are unchanged.
        """
        if not es.is_log_scale_metric:
            return es
        return EffectSize(
            type=es.type,
            value=math.log(es.value) if es.value > 0 else float("nan"),
            se=es.se,
            variance=es.variance,
            ci_lower=math.log(es.ci_lower) if es.ci_lower and es.ci_lower > 0 else None,
            ci_upper=math.log(es.ci_upper) if es.ci_upper and es.ci_upper > 0 else None,
            weight=es.weight,
            n_total=es.n_total,
            study_id=es.study_id,
            study_name=es.study_name,
            group_intervention=es.group_intervention,
            group_control=es.group_control,
        )

    @staticmethod
    def to_natural_scale(es: EffectSize) -> EffectSize:
        """Back-transform a log-scale :class:`EffectSize` to the natural scale."""
        if not es.is_log_scale_metric:
            return es
        return EffectSize(
            type=es.type,
            value=math.exp(es.value) if es.value is not None else None,
            se=es.se,
            variance=es.variance,
            ci_lower=math.exp(es.ci_lower) if es.ci_lower is not None else None,
            ci_upper=math.exp(es.ci_upper) if es.ci_upper is not None else None,
            weight=es.weight,
            n_total=es.n_total,
            study_id=es.study_id,
            study_name=es.study_name,
            group_intervention=es.group_intervention,
            group_control=es.group_control,
        )

    # ------------------------------------------------------------------ #
    # Derived metrics
    # ------------------------------------------------------------------ #
    @staticmethod
    def to_rrr(es: EffectSize) -> EffectSize:
        """Convert an RR to RRR (relative risk reduction = 1 - RR)."""
        if es.type != EffectSizeType.RR:
            raise ValueError("RRR is only derivable from an RR EffectSize.")
        rrr = 1.0 - es.value
        ci_lo = 1.0 - es.ci_upper if es.ci_upper else None
        ci_hi = 1.0 - es.ci_lower if es.ci_lower else None
        return EffectSize(
            type=EffectSizeType.RRR,
            value=float(rrr),
            se=es.se,
            variance=es.variance,
            ci_lower=ci_lo,
            ci_upper=ci_hi,
            weight=es.weight,
            n_total=es.n_total,
            study_id=es.study_id,
            study_name=es.study_name,
            group_intervention=es.group_intervention,
            group_control=es.group_control,
        )

    @staticmethod
    def to_nnt(es: EffectSize, baseline_risk: Optional[float] = None) -> EffectSize:
        """Convert an RD or RR to NNT (number needed to treat).

        Args:
            es: An RD or RR :class:`EffectSize`.
            baseline_risk: Control-arm event risk. Required when ``es`` is an
                RR (NNT = 1 / (baseline_risk * (1 - RR))). Ignored for RD.
        """
        if es.type == EffectSizeType.RD:
            if es.value == 0:
                arr = float("inf")
            else:
                arr = abs(es.value)
        elif es.type == EffectSizeType.RR:
            if baseline_risk is None:
                raise ValueError("baseline_risk required when converting RR to NNT.")
            arr = abs(baseline_risk * (1.0 - es.value))
        else:
            raise ValueError("NNT is only derivable from RD or RR EffectSizes.")
        nnt = float("inf") if arr == 0 else 1.0 / arr
        return EffectSize(
            type=EffectSizeType.NNT,
            value=float(nnt),
            se=es.se,
            variance=es.variance,
            ci_lower=None,
            ci_upper=None,
            weight=es.weight,
            n_total=es.n_total,
            study_id=es.study_id,
            study_name=es.study_name,
            group_intervention=es.group_intervention,
            group_control=es.group_control,
        )

    # ------------------------------------------------------------------ #
    # Confidence interval helper
    # ------------------------------------------------------------------ #
    @staticmethod
    def confidence_interval(
        es: EffectSize, confidence: float = 0.95
    ) -> Tuple[float, float]:
        """Compute the (1-α) confidence interval for an :class:`EffectSize`.

        Uses the normal approximation on the analysis scale (natural for MD/
        SMD/RD; log for RR/OR/HR).
        """
        if es.se is None:
            raise ValueError("EffectSize.se is None — cannot compute CI.")
        if not (0 < confidence < 1):
            raise ValueError("confidence must be in (0, 1).")
        # Lazy import scipy for the inverse normal CDF (more accurate than
        # hard-coding z=1.96).
        try:
            from scipy.stats import norm  # type: ignore
            z = float(norm.ppf(0.5 + confidence / 2.0))
        except Exception:
            # Fallback table for common confidence levels.
            z_table = {0.90: 1.6449, 0.95: 1.96, 0.99: 2.5758}
            z = z_table.get(round(confidence, 4), 1.96)
        # If the effect is on the natural scale for a log-scale metric, the
        # CI bounds should be computed on the log scale first then exp'd.
        if es.is_log_scale_metric and es.value and es.value > 0:
            log_val = math.log(es.value)
            lo = math.exp(log_val - z * es.se)
            hi = math.exp(log_val + z * es.se)
            return lo, hi
        return es.value - z * es.se, es.value + z * es.se


# Convenience module-level alias for type-only imports in sibling modules.
_EffectSize = EffectSize
_EffectSizeType = EffectSizeType
_ContinuousGroup = ContinuousGroup
