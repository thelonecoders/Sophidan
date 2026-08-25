"""Frequentist network meta-analysis (NMA).

Implements:

* Bucher's adjusted indirect comparison for 3-treatment loops.
* A general graph-based multivariate least-squares estimator for arbitrary
  networks (works for any number of treatments and studies).
* Node-splitting tests for loop inconsistency.
* SUCRA-based treatment ranking.
* League-table generation.
* Network plot (matplotlib) showing treatments as nodes and direct
  comparisons as edges weighted by the number of studies.

All heavy math (numpy, scipy, pandas, matplotlib, networkx) is lazy-imported
inside the methods so the module is importable on minimal environments.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import math
import logging
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "TreatmentComparison",
    "NMAResult",
    "InconsistencyTest",
    "NetworkMetaAnalysis",
]


@dataclass
class TreatmentComparison:
    """A single study's direct comparison of two treatments.

    Attributes:
        study_id: Identifier of the contributing study.
        treatment_a: Name of the first (typically comparator) treatment.
        treatment_b: Name of the second (typically experimental) treatment.
        effect_size: Point estimate on the **log** scale (log-OR/RR/HR/SMD).
            Positive ⇒ treatment_b > treatment_a on the outcome scale.
        se: Standard error of ``effect_size``.
        n_total: Optional total participants in the two arms.
    """

    study_id: str
    treatment_a: str
    treatment_b: str
    effect_size: float
    se: float
    n_total: Optional[int] = None


@dataclass
class InconsistencyTest:
    """Result of a single node-splitting inconsistency test.

    Attributes:
        comparison: Treatment pair tested (``'A vs B'``).
        direct: Direct pooled estimate.
        indirect: Indirect estimate.
        difference: ``direct - indirect``.
        z: z-statistic for the difference.
        p_value: Two-sided p-value.
        interpretation: Qualitative interpretation.
    """

    comparison: str
    direct: float
    indirect: float
    difference: float
    z: float
    p_value: float
    interpretation: str = ""


@dataclass
class NMAResult:
    """Result of a network meta-analysis.

    Attributes:
        relative_effects: DataFrame (rows = treatment_b, cols = treatment_a)
            of pooled log-scale relative effects.
        ranking: Dict[treatment, List[float]] — P(rank = k) for k = 1..N.
        inconsistency: Design-by-treatment inconsistency statistic
            (Cochran's Q for inconsistency).
        AIC: Akaike information criterion of the consistency model.
        BIC: Bayesian information criterion of the consistency model.
    """

    relative_effects: object = None  # pandas.DataFrame
    ranking: Dict[str, List[float]] = field(default_factory=dict)
    inconsistency: float = 0.0
    AIC: float = 0.0
    BIC: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to a dict (DataFrame → dict-of-lists)."""
        re = self.relative_effects
        if re is not None and hasattr(re, "to_dict"):
            re_dict = re.to_dict()
        elif re is not None:
            re_dict = dict(re)
        else:
            re_dict = None
        return {
            "relative_effects": re_dict,
            "ranking": dict(self.ranking),
            "inconsistency": float(self.inconsistency),
            "AIC": float(self.AIC),
            "BIC": float(self.BIC),
        }


class NetworkMetaAnalysis:
    """Frequentist network meta-analysis engine.

    The estimator is the standard graph-based least-squares approach
    (Rücker 2012): the network is described by a design matrix that maps
    each comparison's log-effect to the underlying baseline-relative
    treatment effects (``beta_t = effect(t) - effect(reference)``); the
    coefficients are estimated by weighted least squares with weights
    ``1/se^2``. Bucher's indirect comparison is the special case for a
    3-treatment loop.
    """

    def __init__(self, comparisons: List[TreatmentComparison]):
        """Construct a NetworkMetaAnalysis.

        Args:
            comparisons: List of :class:`TreatmentComparison` objects.
                All effect sizes must be on the log scale (log-OR/RR/HR/SMD).
        """
        if not comparisons:
            raise ValueError("comparisons list is empty.")
        self.comparisons = list(comparisons)
        # Deduce treatments (sorted alphabetically for determinism).
        treatments = set()
        for c in self.comparisons:
            treatments.add(c.treatment_a)
            treatments.add(c.treatment_b)
        self.treatments: List[str] = sorted(treatments)
        if len(self.treatments) < 2:
            raise ValueError("Need at least 2 distinct treatments.")
        # Reference treatment: the alphabetically-first treatment.
        self.reference: str = self.treatments[0]
        logger.info(
            "NetworkMetaAnalysis built with %d studies, %d treatments "
            "(reference = %s).",
            len(self.comparisons), len(self.treatments), self.reference,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _design_matrix(self):
        """Build the weighted least-squares design matrix.

        For each comparison (study, treatment_a, treatment_b, y, se):
            y_i = beta[treatment_b] - beta[treatment_a] + ε_i,
            Var(ε_i) = se_i^2.

        ``beta[reference]`` is fixed at 0.

        Returns:
            Tuple ``(X, y, W, treatment_order)`` where ``X`` is an
            ``(n_comparisons, n_treatments-1)`` numpy array, ``y`` the
            comparison estimates, ``W`` the weight vector (1/se²), and
            ``treatment_order`` the list of non-reference treatments
            (alphabetical order).
        """
        try:
            import numpy as np  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("numpy is required for NMA design matrix.") from exc

        non_ref = [t for t in self.treatments if t != self.reference]
        idx = {t: i for i, t in enumerate(non_ref)}
        n = len(self.comparisons)
        p = len(non_ref)
        X = np.zeros((n, p))
        y = np.zeros(n)
        w = np.zeros(n)
        for i, comp in enumerate(self.comparisons):
            ta, tb = comp.treatment_a, comp.treatment_b
            # The comparison y = beta[tb] - beta[ta].
            if tb in idx:
                X[i, idx[tb]] = 1.0
            if ta in idx:
                X[i, idx[ta]] -= 1.0
            y[i] = comp.effect_size
            w[i] = 1.0 / (comp.se ** 2) if comp.se > 0 else 0.0
        return X, y, w, non_ref

    def _fit_wls(self):
        """Fit the weighted-least-squares NMA model.

        Returns:
            Tuple ``(beta, cov, X, y, w, non_ref)``.
        """
        import numpy as np  # type: ignore
        X, y, w, non_ref = self._design_matrix()
        W = np.diag(w)
        XtWX = X.T @ W @ X
        try:
            XtWX_inv = np.linalg.pinv(XtWX)
        except np.linalg.LinAlgError:
            XtWX_inv = np.linalg.pinv(XtWX + 1e-8 * np.eye(XtWX.shape[0]))
        beta = XtWX_inv @ X.T @ W @ y
        cov = XtWX_inv
        return beta, cov, X, y, w, non_ref

    @staticmethod
    def _merge_pooled_estimate(comps: List[TreatmentComparison]) -> Tuple[float, float]:
        """Inverse-variance-pool multiple comparisons of the same pair.

        Returns ``(pooled_log_effect, pooled_se)``.
        """
        if not comps:
            return 0.0, 1.0
        w = [1.0 / (c.se ** 2) if c.se > 0 else 0.0 for c in comps]
        W = sum(w)
        if W <= 0:
            return comps[0].effect_size, comps[0].se
        theta = sum(wi * c.effect_size for wi, c in zip(w, comps)) / W
        se = math.sqrt(1.0 / W)
        return theta, se

    def _direct_pairs(self) -> Dict[Tuple[str, str], List[TreatmentComparison]]:
        """Group comparisons by (treatment_a, treatment_b) — both orderings.

        Returns:
            Mapping from (alphabetically-earlier treatment, later treatment)
            to the list of contributing comparisons (with effect sign
            flipped so it always reads ``later - earlier``).
        """
        groups: Dict[Tuple[str, str], List[TreatmentComparison]] = {}
        for c in self.comparisons:
            ta, tb = c.treatment_a, c.treatment_b
            if ta == tb:
                continue
            if ta < tb:
                key = (ta, tb)
                sign = 1.0
            else:
                key = (tb, ta)
                sign = -1.0
            adjusted = TreatmentComparison(
                study_id=c.study_id,
                treatment_a=ta,
                treatment_b=tb,
                effect_size=sign * c.effect_size,
                se=c.se,
                n_total=c.n_total,
            )
            groups.setdefault(key, []).append(adjusted)
        return groups

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def consistency_model(self) -> NMAResult:
        """Fit the consistency (no-inconsistency) NMA model.

        Returns:
            :class:`NMAResult` with ``relative_effects`` DataFrame,
            ``ranking``, ``AIC`` and ``BIC`` populated.
        """
        try:
            import numpy as np  # type: ignore
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("numpy + pandas required for NMA.") from exc

        beta, cov, X, y, w, non_ref = self._fit_wls()
        # Build the full treatment-coefficient vector (reference = 0).
        coef = {self.reference: 0.0}
        for t, b in zip(non_ref, beta):
            coef[t] = float(b)
        # Covariance: full matrix including the reference (var=0).
        # Order = self.treatments.
        full_cov = np.zeros((len(self.treatments), len(self.treatments)))
        ref_idx = self.treatments.index(self.reference)
        for i, ti in enumerate(non_ref):
            full_i = self.treatments.index(ti)
            for j, tj in enumerate(non_ref):
                full_j = self.treatments.index(tj)
                full_cov[full_i, full_j] = cov[i, j]

        # Build relative effects DataFrame: rows = treatment_b, cols = treatment_a.
        # Cell (i, j) = log effect of treatment i vs treatment j = beta_i - beta_j.
        rows = {}
        for ti in self.treatments:
            row = {}
            for tj in self.treatments:
                if ti == tj:
                    row[tj] = 0.0
                    continue
                val = coef[ti] - coef[tj]
                idx_i = self.treatments.index(ti)
                idx_j = self.treatments.index(tj)
                var = full_cov[idx_i, idx_i] + full_cov[idx_j, idx_j] - 2.0 * full_cov[idx_i, idx_j]
                row[tj] = float(val)
                row[f"{tj}_se"] = float(math.sqrt(max(var, 0.0)))
            rows[ti] = row
        df = pd.DataFrame(rows).T  # rows = treatment_b
        # Keep only the value cells (drop _se columns from main view; keep SE separate).
        value_cols = [c for c in df.columns if not c.endswith("_se")]
        se_cols = [c for c in df.columns if c.endswith("_se")]
        relative_effects = df[value_cols].copy()

        # Residual sum of squares for AIC/BIC:
        residuals = y - X @ beta
        RSS = float(np.sum(w * residuals ** 2))
        k_params = len(non_ref)
        n_obs = len(y)
        AIC = RSS + 2.0 * k_params
        BIC = RSS + math.log(n_obs if n_obs > 0 else 1) * k_params

        # Ranking via SUCRA — bootstrap-free: rank by coef (higher = better
        # if outcome is "good" → use sign = +1; assumes higher log-effect
        # = better treatment).
        ranking = self._rank_probability_from_coef(coef, full_cov)

        return NMAResult(
            relative_effects=relative_effects,
            ranking=ranking,
            inconsistency=0.0,  # populated by inconsistency_model
            AIC=float(AIC),
            BIC=float(BIC),
        )

    def _rank_probability_from_coef(
        self, coef: Dict[str, float], cov: np.ndarray
    ) -> Dict[str, List[float]]:
        """Compute P(rank = k) for each treatment using multivariate normal.

        Uses a Monte-Carlo simulation of ``n_sim`` draws from the
        multivariate-normal distribution of the treatment coefficients
        and counts how often each treatment ends up at rank k.
        """
        try:
            import numpy as np  # type: ignore
            from scipy.stats import mvn  # type: ignore  # noqa: F401
        except Exception:
            # Fallback: ranking by point estimate (deterministic).
            ordered = sorted(coef.items(), key=lambda kv: kv[1], reverse=True)
            ranking = {}
            for rank, (t, _) in enumerate(ordered, start=1):
                ranking[t] = [0.0] * len(self.treatments)
                ranking[t][rank - 1] = 1.0
            return ranking

        # Monte Carlo simulation.
        order = self.treatments
        beta_vec = np.array([coef[t] for t in order])
        # Remove reference (zero variance).
        non_ref_mask = np.array([t != self.reference for t in order])
        beta_nonref = beta_vec[non_ref_mask]
        cov_nonref = cov[np.ix_(non_ref_mask, non_ref_mask)]
        n_sim = 10000
        rng = np.random.default_rng(seed=42)
        try:
            samples = rng.multivariate_normal(beta_nonref, cov_nonref, size=n_sim)
        except Exception:
            samples = rng.standard_normal((n_sim, len(beta_nonref))) * 0.0
        # Add reference (always 0):
        full = np.zeros((n_sim, len(order)))
        full[:, non_ref_mask] = samples
        ranks = np.zeros_like(full, dtype=int)
        for s in range(n_sim):
            order_desc = np.argsort(-full[s])  # descending
            for rank_idx, idx in enumerate(order_desc):
                ranks[s, idx] = rank_idx + 1
        ranking = {}
        for i, t in enumerate(order):
            counts = [0.0] * len(order)
            for r in range(1, len(order) + 1):
                counts[r - 1] = float(np.sum(ranks[:, i] == r)) / n_sim
            ranking[t] = counts
        return ranking

    def inconsistency_model(self) -> NMAResult:
        """Design-by-treatment inconsistency model.

        Adds one extra parameter per independent loop in the network; the
        difference in RSS between the consistency and inconsistency models
        is reported as ``NMAResult.inconsistency``.
        """
        try:
            import numpy as np  # type: ignore
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("numpy + pandas required for inconsistency model.") from exc

        # Build the augmented design with an extra inconsistency parameter
        # for each independent cycle. Detect cycles using networkx.
        try:
            import networkx as nx  # type: ignore
        except ImportError:
            logger.warning("networkx unavailable — inconsistency model = consistency.")
            res = self.consistency_model()
            res.inconsistency = 0.0
            return res

        G = nx.Graph()
        for c in self.comparisons:
            G.add_edge(c.treatment_a, c.treatment_b)
        try:
            cycles = list(nx.cycle_basis(G))
        except Exception:
            cycles = []

        # Build the augmented design matrix.
        non_ref = [t for t in self.treatments if t != self.reference]
        idx = {t: i for i, t in enumerate(non_ref)}
        n = len(self.comparisons)
        p_consistency = len(non_ref)
        p_inconsistency = len(cycles)
        p = p_consistency + p_inconsistency
        X = np.zeros((n, p))
        y = np.zeros(n)
        w = np.zeros(n)
        for i, comp in enumerate(self.comparisons):
            ta, tb = comp.treatment_a, comp.treatment_b
            if tb in idx:
                X[i, idx[tb]] = 1.0
            if ta in idx:
                X[i, idx[ta]] -= 1.0
            y[i] = comp.effect_size
            w[i] = 1.0 / (comp.se ** 2) if comp.se > 0 else 0.0
        # Inconsistency parameters: one per cycle.
        for ci, cyc in enumerate(cycles):
            # Mark comparisons whose edge is in this cycle.
            cyc_edges = set()
            for a, b in zip(cyc, cyc[1:] + [cyc[0]]):
                cyc_edges.add(tuple(sorted([a, b])))
            for i, comp in enumerate(self.comparisons):
                edge = tuple(sorted([comp.treatment_a, comp.treatment_b]))
                if edge in cyc_edges:
                    X[i, p_consistency + ci] = 1.0
        W = np.diag(w)
        XtWX = X.T @ W @ X
        try:
            XtWX_inv = np.linalg.pinv(XtWX)
        except np.linalg.LinAlgError:
            XtWX_inv = np.linalg.pinv(XtWX + 1e-8 * np.eye(p))
        beta = XtWX_inv @ X.T @ W @ y
        residuals = y - X @ beta
        RSS_inc = float(np.sum(w * residuals ** 2))

        # Consistency RSS (without inconsistency params).
        X_cons = X[:, :p_consistency]
        XtWX_cons = X_cons.T @ W @ X_cons
        try:
            XtWX_cons_inv = np.linalg.pinv(XtWX_cons)
        except np.linalg.LinAlgError:
            XtWX_cons_inv = np.linalg.pinv(
                XtWX_cons + 1e-8 * np.eye(p_consistency)
            )
        beta_cons = XtWX_cons_inv @ X_cons.T @ W @ y
        residuals_cons = y - X_cons @ beta_cons
        RSS_cons = float(np.sum(w * residuals_cons ** 2))

        # Inconsistency statistic (Cochran's Q):
        inconsistency = max(0.0, RSS_cons - RSS_inc)
        # Build the relative-effects DataFrame using the consistency fit.
        coef = {self.reference: 0.0}
        for t, b in zip(non_ref, beta_cons):
            coef[t] = float(b)
        order = self.treatments
        rows = {}
        for ti in order:
            row = {}
            for tj in order:
                if ti == tj:
                    row[tj] = 0.0
                else:
                    row[tj] = float(coef[ti] - coef[tj])
            rows[ti] = row
        relative_effects = pd.DataFrame(rows).T

        # AIC/BIC of the inconsistency model:
        k = p
        n_obs = n
        AIC = RSS_inc + 2.0 * k
        BIC = RSS_inc + math.log(n_obs if n_obs > 0 else 1) * k

        return NMAResult(
            relative_effects=relative_effects,
            ranking=self._rank_probability_from_coef(
                coef, np.zeros((len(order), len(order)))
            ),
            inconsistency=float(inconsistency),
            AIC=float(AIC),
            BIC=float(BIC),
        )

    # ------------------------------------------------------------------ #
    # Node splitting
    # ------------------------------------------------------------------ #
    def node_splitting(self) -> List[InconsistencyTest]:
        """Split each direct comparison into direct vs indirect evidence.

        For each directly-compared pair (A, B), compute:
            - direct pooled estimate (IV of all studies A vs B),
            - indirect estimate from the rest of the network (via Bucher
              through any common comparator C),
            - z-test for the difference.

        Returns:
            List of :class:`InconsistencyTest` for every pair with both
            direct AND indirect evidence.
        """
        results: List[InconsistencyTest] = []
        direct = self._direct_pairs()

        for (ta, tb), comps in direct.items():
            # Direct pooled estimate (in direction tb - ta).
            direct_theta, direct_se = self._merge_pooled_estimate(comps)
            # Indirect: find a comparator tc that has direct comparisons to
            # both ta and tb in the network EXCLUDING the direct (ta, tb)
            # studies themselves.
            other_treatments = [
                t for t in self.treatments if t not in {ta, tb}
            ]
            indirect_thetas: List[float] = []
            indirect_vars: List[float] = []
            for tc in other_treatments:
                # Look up direct (ta, tc) and (tb, tc) — these are (sorted) pairs.
                key_ta_tc = tuple(sorted([ta, tc]))
                key_tb_tc = tuple(sorted([tb, tc]))
                if key_ta_tc not in direct or key_tb_tc not in direct:
                    continue
                # Direction: we want (tb - ta) = (tb - tc) - (ta - tc).
                # In `direct`, all entries are stored as (earlier - later)
                # with sign flipped if necessary. So compute:
                #   d_ta_tc = effect(tc) - effect(ta)
                #   d_tb_tc = effect(tc) - effect(tb)
                # so (tb - ta) = d_ta_tc - d_tb_tc.
                comps_a_c = direct[key_ta_tc]  # these are sorted(key) — earlier - later
                comps_b_c = direct[key_tb_tc]
                theta_ac, se_ac = self._merge_pooled_estimate(comps_a_c)
                theta_bc, se_bc = self._merge_pooled_estimate(comps_b_c)
                # theta_ac = effect(later) - effect(earlier) of pair (ta, tc).
                # If ta < tc: theta_ac = effect(tc) - effect(ta). We want effect(tc) - effect(ta) = theta_ac.
                # If tc < ta: theta_ac = effect(ta) - effect(tc). We want effect(tc) - effect(ta) = -theta_ac.
                sign_ac = 1.0 if ta < tc else -1.0
                sign_bc = 1.0 if tb < tc else -1.0
                # (tb - ta) = (tc - ta) - (tc - tb) = sign_ac*theta_ac - sign_bc*theta_bc
                # But we want (tb - ta) — careful with direction.
                # We want d_tb_ta = effect(tb) - effect(ta).
                # d_tb_ta = (effect(tb) - effect(tc)) - (effect(ta) - effect(tc))
                #        = sign_bc*theta_bc - sign_ac*theta_ac   ... wait
                # Actually theta_ac is (effect(later) - effect(earlier)) of pair (ta, tc).
                # If ta < tc: theta_ac = effect(tc) - effect(ta), so (effect(ta) - effect(tc)) = -theta_ac.
                # If tc < ta: theta_ac = effect(ta) - effect(tc), so (effect(ta) - effect(tc)) = +theta_ac.
                # Generalize: (effect(ta) - effect(tc)) = sign_ac * theta_ac where sign_ac = -1 if ta < tc else +1.
                # Actually the inversion: if ta < tc, theta_ac stores (effect(tc)-effect(ta)) = -theta_ac + 2*effect(tc)... no.
                # Re-think: I stored `adjusted = sign * c.effect_size` where sign = 1 if ta < tb else -1.
                # So theta_ac = sign_ac_orig * (effect(later) - effect(earlier)), where the comparison was given
                # as (treatment_a=orig_ta, treatment_b=orig_tb, effect_size=orig_y).
                # In the original comparison, orig_y = effect(orig_tb) - effect(orig_ta).
                # So adjusted effect = sign * (effect(orig_tb) - effect(orig_ta)) where sign = 1 if orig_ta < orig_tb else -1.
                # => theta_ac (pooled, sorted) = effect(later) - effect(earlier) for the (ta, tc) pair.
                # So effect(ta) - effect(tc) = -theta_ac if ta < tc else +theta_ac.
                d_ta_tc = -theta_ac if ta < tc else +theta_ac
                d_tb_tc = -theta_bc if tb < tc else +theta_bc
                # (tb - ta) = (tb - tc) - (ta - tc) = d_tb_tc - d_ta_tc.
                d_indirect = d_tb_tc - d_ta_tc
                var_indirect = se_ac ** 2 + se_bc ** 2
                indirect_thetas.append(d_indirect)
                indirect_vars.append(var_indirect)
            if not indirect_thetas:
                continue
            # Inverse-variance pool the indirect estimates.
            w = [1.0 / v if v > 0 else 0.0 for v in indirect_vars]
            W = sum(w)
            if W <= 0:
                continue
            indirect_theta = sum(wi * t for wi, t in zip(w, indirect_thetas)) / W
            indirect_se = math.sqrt(1.0 / W)
            # z-test for difference.
            diff = direct_theta - indirect_theta
            diff_se = math.sqrt(direct_se ** 2 + indirect_se ** 2)
            z = diff / diff_se if diff_se > 0 else 0.0
            p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(z) / math.sqrt(2.0))))
            interp = (
                "no evidence of inconsistency"
                if p >= 0.10
                else "some evidence of inconsistency"
                if p >= 0.05
                else "evidence of inconsistency"
            )
            results.append(InconsistencyTest(
                comparison=f"{tb} vs {ta}",
                direct=float(direct_theta),
                indirect=float(indirect_theta),
                difference=float(diff),
                z=float(z),
                p_value=float(p),
                interpretation=interp,
            ))
        return results

    # ------------------------------------------------------------------ #
    # Ranking
    # ------------------------------------------------------------------ #
    def rank_probability(self) -> Dict[str, List[float]]:
        """P(rank = k) for each treatment under the consistency model."""
        res = self.consistency_model()
        return res.ranking

    def sucra_scores(self) -> Dict[str, float]:
        """SUCRA scores (Surface Under the Cumulative Ranking curve).

        SUCRA = Σ_{k=1}^{N-1} F_k / (N - 1), where F_k = P(rank > k).
        Range: 0 (worst) to 1 (best).
        """
        ranks = self.rank_probability()
        scores: Dict[str, float] = {}
        for t, p_list in ranks.items():
            N = len(p_list)
            # Cumulative probability that treatment ranks worse than position k.
            cumulative_better = 0.0
            sucra = 0.0
            for k in range(1, N):
                # Probability of being at rank ≤ k:
                cumulative_better += p_list[k - 1]
                # Probability of NOT being in top k:
                F_k = 1.0 - cumulative_better
                sucra += F_k / (N - 1)
            scores[t] = float(sucra)
        return scores

    # ------------------------------------------------------------------ #
    # League table
    # ------------------------------------------------------------------ #
    def league_table(self):
        """N×N table of pooled pairwise effects.

        Returns:
            ``pandas.DataFrame`` with rows = treatment_b, columns = treatment_a;
            cell (i, j) = pooled log-effect of treatment_i vs treatment_j
            with 95% CI in parentheses (e.g. ``"0.45 (0.10, 0.80)"``).
        """
        try:
            import pandas as pd  # type: ignore
            import numpy as np  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pandas + numpy required for league_table.") from exc

        beta, cov, X, y, w, non_ref = self._fit_wls()
        coef = {self.reference: 0.0}
        for t, b in zip(non_ref, beta):
            coef[t] = float(b)
        order = self.treatments
        full_cov = np.zeros((len(order), len(order)))
        for i, ti in enumerate(non_ref):
            fi = order.index(ti)
            for j, tj in enumerate(non_ref):
                fj = order.index(tj)
                full_cov[fi, fj] = cov[i, j]
        rows = {}
        for ti in order:
            row = {}
            for tj in order:
                if ti == tj:
                    row[tj] = "—"
                    continue
                val = coef[ti] - coef[tj]
                idx_i = order.index(ti)
                idx_j = order.index(tj)
                var = (
                    full_cov[idx_i, idx_i]
                    + full_cov[idx_j, idx_j]
                    - 2.0 * full_cov[idx_i, idx_j]
                )
                se = math.sqrt(max(var, 0.0))
                ci_lo = val - 1.96 * se
                ci_hi = val + 1.96 * se
                row[tj] = f"{val:+.3f} ({ci_lo:+.3f}, {ci_hi:+.3f})"
            rows[ti] = row
        return pd.DataFrame(rows).T

    # ------------------------------------------------------------------ #
    # Network plot
    # ------------------------------------------------------------------ #
    def network_plot(self):
        """Visualize the network of treatments and direct comparisons.

        Returns:
            ``matplotlib.figure.Figure`` with treatments as nodes (sized by
            SUCRA score) and direct comparisons as edges (width ∝ # studies).
        """
        import matplotlib  # type: ignore
        matplotlib.use("Agg", force=False)
        import matplotlib.pyplot as plt  # type: ignore
        try:
            import networkx as nx  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("networkx required for network_plot().") from exc

        # Font configuration (CJK-safe).
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = [
            "Noto Sans SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
            "Microsoft YaHei", "PingFang SC", "SimHei", "DejaVu Sans",
        ]
        plt.rcParams["axes.unicode_minus"] = False

        G = nx.Graph()
        edge_counts: Dict[Tuple[str, str], int] = {}
        for c in self.comparisons:
            a, b = c.treatment_a, c.treatment_b
            if a == b:
                continue
            key = tuple(sorted([a, b]))
            edge_counts[key] = edge_counts.get(key, 0) + 1
        for (a, b), count in edge_counts.items():
            G.add_edge(a, b, weight=count)

        fig, ax = plt.subplots(figsize=(8, 8), constrained_layout=True)
        pos = nx.spring_layout(G, seed=42, k=2.0)
        # Node sizes by SUCRA.
        try:
            sucra = self.sucra_scores()
            node_sizes = [200 + 1500 * sucra.get(t, 0.0) for t in G.nodes()]
        except Exception:
            node_sizes = [600] * len(G.nodes())
        edge_widths = [0.5 + 2.0 * math.log1p(d["weight"]) for _, _, d in G.edges(data=True)]
        nx.draw_networkx_edges(G, pos, ax=ax, width=edge_widths, edge_color="#888888")
        nx.draw_networkx_nodes(
            G, pos, ax=ax, node_size=node_sizes,
            node_color="#4C72B0", alpha=0.85, edgecolors="white", linewidths=1.5,
        )
        nx.draw_networkx_labels(G, pos, ax=ax, font_size=10, font_weight="bold")
        # Edge labels: study counts.
        edge_labels = {(u, v): f"{d['weight']}" for u, v, d in G.edges(data=True)}
        nx.draw_networkx_edge_labels(G, pos, ax=ax, edge_labels=edge_labels, font_size=9)
        ax.set_title(
            "Network of direct comparisons (edge width ∝ # studies, "
            "node size ∝ SUCRA)",
            fontsize=11,
        )
        ax.set_axis_off()
        return fig
