# Meta-Analysis Guide

> **Audience:** evidence-synthesis methodologists, statisticians, SR
> reviewers.
> **Companion docs:** [PRISMA_GUIDE.md](PRISMA_GUIDE.md) for the
> upstream SR workflow, [Q1_FIGURES_GUIDE.md](Q1_FIGURES_GUIDE.md) for
> rendering forest / funnel plots as publication-grade figures,
> [MODULE_REFERENCE.md](MODULE_REFERENCE.md) for the full module index.

This guide describes how to perform a complete meta-analysis in
Academic Research Suite (ARS) v2.0.0 — from choosing an effect-size
metric and pooling method, through heterogeneity assessment, subgroup /
sensitivity analyses, publication-bias testing, and network
meta-analysis, to producing Cochrane / JAMA / Lancet-style forest and
funnel plots.

---

## Table of Contents

1. [Effect size types](#effect-size-types)
2. [Pooling methods](#pooling-methods)
3. [Heterogeneity assessment](#heterogeneity-assessment)
4. [Publication bias testing](#publication-bias-testing)
5. [Subgroup analysis](#subgroup-analysis)
6. [Sensitivity analysis](#sensitivity-analysis)
7. [Network meta-analysis](#network-meta-analysis)
8. [Forest plot interpretation](#forest-plot-interpretation)
9. [Funnel plot interpretation](#funnel-plot-interpretation)
10. [GRADE assessment integration](#grade-assessment-integration)
11. [Full workflow example](#full-workflow-example)

---

## Effect size types

`meta_analysis.effect_sizes.EffectSizeCalculator` builds
`EffectSize` dataclasses for every standard metric. Each
`EffectSize` carries the point estimate, standard error, confidence
interval, 2×2-table cell counts (for dichotomous outcomes), and
optional study metadata (`study_id`, `study_name`, `year`).

| Metric | `EffectSizeType` | Null value | Formula | When to use |
|---|---|---|---|---|
| Mean difference (MD) | `MD` | 0 | μ₁ − μ₂ | Continuous outcome, same scale across studies |
| Standardized MD (SMD) | `SMD` | 0 | (μ₁ − μ₂) / SD_pooled | Continuous outcome, different scales |
| Cohen's d | (SMD with `smd_method='cohen'`) | 0 | (μ₁ − μ₂) / SD_pooled | Sample-size-weighted SD |
| Hedges' g | (`smd_method='hedges'`) | 0 | d × J(n₁, n₂) | Bias-corrected SMD for small samples |
| Glass' Δ | (`smd_method='glass'`) | 0 | (μ₁ − μ₂) / SD_control | When intervention affects variance |
| Risk ratio (RR) | `RR` | 1 | (a/n₁) / (c/n₂) | Dichotomous outcome, common baseline risk |
| Odds ratio (OR) | `OR` | 1 | (a·d) / (b·c) | Dichotomous, case-control, rare outcome |
| Hazard ratio (HR) | `HR` | 1 | supplied directly | Time-to-event |
| Risk difference (RD) | `RD` | 0 | (a/n₁) − (c/n₂) | Absolute risk difference |
| Number needed to treat (NNT) | `NNT` | ∞ | 1 / RD | Decision-making, absolute scale |

### Building continuous-outcome effect sizes

```python
from meta_analysis.effect_sizes import EffectSizeCalculator, ContinuousGroup

treatment = ContinuousGroup(n=45, mean=-1.2, sd=0.85)
control   = ContinuousGroup(n=43, mean=-0.4, sd=0.92)

# Standardized mean difference (Hedges' g, bias-corrected):
es_hedges = EffectSizeCalculator.from_continuous(
    treatment, control, type="SMD", smd_method="hedges",
)

# Mean difference on the natural scale:
es_md = EffectSizeCalculator.from_continuous(
    treatment, control, type="MD",
)

# Glass' Δ (uses control-arm SD as the standardiser):
es_glass = EffectSizeCalculator.from_continuous(
    treatment, control, type="SMD", smd_method="glass",
)
```

### Building dichotomous-outcome effect sizes

```python
es_or = EffectSizeCalculator.from_dichotomous(
    events_intervention=12, total_intervention=80,
    events_control=22,    total_control=78,
    type="OR",
)
es_rr = EffectSizeCalculator.from_dichotomous(
    events_intervention=12, total_intervention=80,
    events_control=22,    total_control=78,
    type="RR",
)
es_hr = EffectSizeCalculator.from_hazard_ratio(
    hr=0.78, ci_lower=0.62, ci_upper=0.98,
)

# Convert to derived metrics:
es_rdn = EffectSizeCalculator.to_natural_scale(es_or)            # natural-scale OR
es_nnt = EffectSizeCalculator.to_nnt(es_or, baseline_risk=0.25)  # NNT
es_rrr = EffectSizeCalculator.to_rrr(es_rr)                      # relative risk reduction
```

`from_continuous` / `from_dichotomous` automatically compute SE, CI,
variance, and the log-scale transform when applicable (RR/OR/HR are
pooled on the log scale).

---

## Pooling methods

`meta_analysis.pooling.PoolingEngine.pool()` is the single entry point
for both fixed-effect and random-effects pooling. The `PoolingMethod`
enum selects the estimator:

| Method | Enum value | Use case |
|---|---|---|
| Inverse-variance fixed | `PoolingMethod.FIXED` / `IV` | Homogeneous studies (I² < 25%) |
| Mantel–Haenszel | `PoolingMethod.MH` | Sparse-data OR/RR; uses 2×2 cell counts |
| Peto one-step | `PoolingMethod.PETO` | Sparse-data OR with rare events |
| DerSimonian–Laird | `PoolingMethod.DL` / `RANDOM` | Default random-effects; closed-form τ² |
| REML | `PoolingMethod.REML` | Iterative; preferred for moderate k |
| Maximum likelihood | `PoolingMethod.ML` | Iterative; for sensitivity to DL |
| Empirical Bayes | `PoolingMethod.EB` | Shrinkage towards fixed-effect |

```python
from meta_analysis.pooling import PoolingEngine, PoolingMethod

result = PoolingEngine.pool(es_list, method=PoolingMethod.DL, confidence=0.95)
print(result.summary_text())
# Pooled SMD: 0.412 (95% CI 0.21 to 0.61), z = 3.91, p = 9.2e-05
# I² = 38.5%, τ² = 0.018, Q = 19.5 (df=14, p=0.144)

# Compare fixed vs random-effects:
fixed = PoolingEngine.pool(es_list, method=PoolingMethod.FIXED)
reml  = PoolingEngine.pool(es_list, method=PoolingMethod.REML)
print(f"DL pooled  = {result.pooled_effect.value:.3f}")
print(f"REML pooled = {reml.pooled_effect.value:.3f}")
```

For dichotomous outcomes with rare events, prefer `MH` or `PETO` —
these use the exact 2×2 cell counts (stored on every
`EffectSize` built by `from_dichotomous`) instead of inverse-variance
weights, and are more stable when event counts are very small (zero
cells in some studies).

---

## Heterogeneity assessment

Every `MetaAnalysisResult` carries a `Heterogeneity` dataclass with
four canonical statistics:

| Statistic | Range | Interpretation |
|---|---|---|
| **Cochran's Q** | ≥ 0 | Sum of squared deviations weighted by inverse variance. Under H₀, Q ∼ χ²(df=k−1). High Q + low p ⇒ reject homogeneity. |
| **τ² (tau²)** | ≥ 0 | Between-study variance estimate (DL / REML / ML). In natural-effect units squared. |
| **I²** | 0–100% | Proportion of total variation due to heterogeneity (not chance). 25 / 50 / 75% thresholds (low / moderate / high). |
| **H²** | ≥ 1 | Relative excess of Q over its degrees of freedom. H² = 1 ⇒ homogeneous. |

Thresholds for I² (Higgins & Thompson 2002):

- **0–25%** — low heterogeneity; fixed-effect pooling acceptable.
- **25–50%** — moderate; consider random-effects.
- **50–75%** — substantial; random-effects; explore subgroups.
- **> 75%** — considerable; investigate sources of heterogeneity before
  pooling.

```python
print(f"I² = {result.I_squared:.1f}%")
print(f"τ² = {result.tau_squared:.4f}")
print(f"Q  = {result.Q_statistic:.2f} (df={result.heterogeneity.df}, "
      f"p={result.Q_p_value:.3f})")
print(f"H² = {result.heterogeneity.H_squared:.2f}")
```

When I² > 50% and there is a clinically meaningful subgroup variable,
run a subgroup analysis (below). When I² < 50% but one study is an
obvious outlier, run a leave-one-out sensitivity analysis to confirm
the pooled estimate is not driven by a single study.

---

## Publication bias testing

`meta_analysis.funnel_plot.FunnelPlot` and `ContourEnhancedFunnel`
implement the full battery of publication-bias diagnostics:

| Test / method | Class method | Returns | Use case |
|---|---|---|---|
| Egger's regression test | `eggers_test()` | (t, p, intercept) | Asymmetry in continuous-outcome funnel; ≥ 10 studies recommended |
| Begg's rank correlation | `beggs_test()` | (tau, p) | Non-parametric; less powerful than Egger but more stable |
| Peters' test | `peters_test()` | (z, p) | For dichotomous outcomes (OR/RR) |
| Harbord's test | `harbord_test()` | (z, p) | For OR/RR with sparse data |
| Orwin's test | `orp_test(target_effect=0.0)` | (n_required, n_imputed) | Number of studies needed to nullify effect |
| Trim-and-fill | `trim_and_fill(es_list, method='R0')` | (es_list_imputed, n_filled) | Impute missing studies on the right side of the funnel |
| Rosenthal fail-safe N | `rosenthal_fail_safe_n(alpha=0.05)` | int | How many null studies would nullify the effect |

```python
from meta_analysis.funnel_plot import ContourEnhancedFunnel

funnel = ContourEnhancedFunnel(es_list, pooled=result.pooled_effect)
funnel.add_significance_contours()         # contour-enhanced funnel
funnel.add_pseudo_ci(alpha=0.95)          # 95% pseudo-confidence region
n_filled = funnel.add_trim_fill(trim_method="R0")
print(f"Trim-and-fill added {n_filled} imputed studies")

t, p, intercept = funnel.eggers_test()
print(f"Egger: t={t:.2f}, p={p:.4g}, intercept={intercept:.3f}")

tau, p_begg = funnel.beggs_test()
print(f"Begg: tau={tau:.2f}, p={p_begg:.4g}")

z, p_peters = funnel.peters_test()
z_h, p_harbord = funnel.harbord_test()
n_fs = funnel.rosenthal_fail_safe_n()
n_req, n_imp = funnel.orp_test(target_effect=0.1)
```

`FunnelPlot` (the parent class) supports all of the above except
`add_significance_contours()` — use `ContourEnhancedFunnel` for the
contour-enhanced variant recommended by Peters et al. (2008).

### Interpretation rules

- **Egger p < 0.10** → suspected small-study bias.
- **Trim-and-fill imputed > 0** and pooled estimate shifts across the
  null → effect may be inflated by publication bias.
- **Rosenthal fail-safe N > 5k + 10** (where k = number of studies) →
  robust to publication bias (Rosenthal 1979 rule).

---

## Subgroup analysis

`meta_analysis.subgroup.SubgroupAnalysis` partitions studies by a
categorical moderator and pools each subgroup independently:

```python
from meta_analysis.subgroup import SubgroupAnalysis

# subgroups: study_id -> subgroup name
subgroups = {
    "smith2020": "Industry-funded",
    "jones2021": "Public-funded",
    "lee2022":   "Public-funded",
    "patel2023": "Industry-funded",
}

sa = SubgroupAnalysis()
sub_result = sa.analyze(es_list, subgroups, method=PoolingMethod.DL)
print(sub_result.to_markdown())

Q_between, p = sa.test_for_subgroup_differences(es_list, subgroups)
print(f"Q-between = {Q_between:.2f}, p = {p:.4g}")
```

`SubgroupResult` carries `subgroup_effects` (per-subgroup pooled
`EffectSize`), `Q_between` (heterogeneity between subgroups, df = g−1),
`Q_within` (heterogeneity within each subgroup), the test
`p_value`, and `I_squared_within` per subgroup.

A significant Q-between (p < 0.05) suggests the subgroup variable
explains part of the between-study heterogeneity — a candidate effect
modifier worth discussing in the SR's "Synthesis of results" section.

---

## Sensitivity analysis

`meta_analysis.subgroup.SensitivityAnalysis` provides four canonical
diagnostics:

| Method | Returns | Use case |
|---|---|---|
| `leave_one_out(es_list)` | List of (k − 1) `MetaAnalysisResult` | Confirm pooled estimate isn't driven by any single study |
| `leave_one_out_forest(es_list)` | matplotlib Figure | Forest plot of the k leave-one-out pooled effects |
| `cumulative(es_list, order_by='year')` | List of `MetaAnalysisResult` | Cumulative meta-analysis by year (or custom order) |
| `influence_diagnosis(es_list)` | Dict[str, Dict[str, float]] | Per-study Cook's distance, DFBETAS, hat values |
| `galbraith_plot(es_list, pooled=None)` | matplotlib Figure | Standardised effect vs precision (radial plot) |
| `radial_plot(es_list, pooled=None)` | matplotlib Figure | Alternative radial visualisation for IV weighting |

```python
from meta_analysis.subgroup import SensitivityAnalysis

sa = SensitivityAnalysis()
loo = sa.leave_one_out(es_list, method=PoolingMethod.DL)
for r in loo:
    print(f"Omitting study → pooled={r.pooled_effect.value:.3f}, "
          f"CI={r.pooled_effect.ci_lower:.3f}–{r.pooled_effect.ci_upper:.3f}")

fig = sa.leave_one_out_forest(es_list, method=PoolingMethod.DL)
cum = sa.cumulative(es_list, order_by="year", method=PoolingMethod.DL)
influence = sa.influence_diagnosis(es_list)
```

If the leave-one-out pooled estimates are all within ±10% of the
original, the result is stable to study removal. A single study that flips the sign or
crosses the null on omission should be flagged in the SR's "Certainty
of evidence" assessment.

---

## Network meta-analysis

`meta_analysis.network_meta.NetworkMetaAnalysis` implements a
graph-based NMA following the Rücker framework (2012). Inputs are a
list of `TreatmentComparison` objects, each carrying one direct
comparison (study_id, treatment_a, treatment_b, log-scale effect_size,
SE, n_total).

```python
from meta_analysis.network_meta import (
    NetworkMetaAnalysis, TreatmentComparison,
)

comparisons = [
    TreatmentComparison(study_id="A1", treatment_a="Placebo",
                        treatment_b="DrugA", effect_size=0.85, se=0.18, n_total=240),
    TreatmentComparison(study_id="A2", treatment_a="Placebo",
                        treatment_b="DrugA", effect_size=0.78, se=0.21, n_total=180),
    TreatmentComparison(study_id="B1", treatment_a="Placebo",
                        treatment_b="DrugB", effect_size=1.05, se=0.20, n_total=200),
    TreatmentComparison(study_id="C1", treatment_a="DrugA",
                        treatment_b="DrugB", effect_size=0.22, se=0.25, n_total=160),
    # ... more comparisons
]

nma = NetworkMetaAnalysis(comparisons)

# Consistency model (assumes direct + indirect agree):
cons_result = nma.consistency_model()
print(cons_result.relative_effects)         # DataFrame of pooled log effects

# Inconsistency model (relaxes the consistency assumption):
inc_result = nma.inconsistency_model()
print(f"AIC consistency = {cons_result.AIC:.1f}")
print(f"AIC inconsistency = {inc_result.AIC:.1f}")

# SUCRA ranking (Surface Under the Cumulative RAnking curve):
sucra = nma.sucra_scores()                  # Dict[treatment, SUCRA in [0, 1]]
rank_p = nma.rank_probability()             # Dict[treatment, List[P(rank=k)]]

# League table (k × k matrix of relative effects):
league_fig = nma.league_table()
network_fig = nma.network_plot()

# Node-splitting for local inconsistency tests:
splits = nma.node_splitting()               # List[InconsistencyTest]
for split in splits:
    print(f"{split.treatment_a} vs {split.treatment_b}: "
          f"direct={split.direct_effect:.3f}, indirect={split.indirect_effect:.3f}, "
          f"p={split.p_value:.4g}")
```

### Consistency vs inconsistency

The **consistency model** assumes direct evidence (A-B) and indirect
evidence (A-C + C-B) agree. The **inconsistency model** relaxes that
assumption, fitting an additional parameter per independent loop in the
network. Compare the two via AIC/BIC and the design-by-treatment
inconsistency Q (reported as `inc_result.inconsistency`). A significant
Q (p < 0.05) suggests the consistency assumption is violated — explore
node-splitting results to localise the source.

---

## Forest plot interpretation

`meta_analysis.forest_plot.ForestPlot` renders a publication-grade
forest plot. The renderer supports three journal styles — `cochrane`
(default, navy boxes), `jama` (grey), `lancet` (red diamonds) — via
the `style=` keyword.

```python
from meta_analysis.forest_plot import ForestPlot

fp = ForestPlot(
    effect_sizes=es_list,
    pooled=result.pooled_effect,         # diamond at the bottom
    title="Effect of SGLT2 inhibitors on HbA1c",
    x_label="Mean difference in HbA1c (%)",
    x_scale="natural",                  # 'log' for OR/RR/HR
    study_names=[es.study_name for es in es_list],
    weights=result.weights,             # sizes the squares
    confidence=0.95,
)
fp.add_heterogeneity(f"I² = {result.I_squared:.1f}%, "
                     f"τ² = {result.tau_squared:.3f}, "
                     f"Q = {result.Q_statistic:.2f} (p={result.Q_p_value:.3f})")
fp.add_favours_treatment_label()
fp.add_favours_control_label()
fig = fp.render(figsize=(10, 8), dpi=300, style="cochrane")
fp.save("outputs/forest.png", format="png")
fp.save("outputs/forest.svg", format="svg")
```

For subgroup forests, pass `subgroups=[...]` and call
`fp.add_subgroup("Industry-funded", indices=[0, 3])` then
`fp.add_subgroup("Public-funded", indices=[1, 2])`. Call
`fp.add_test_for_subgroup_effect(p_value=0.04)` to draw the
between-subgroup p-value at the bottom.

Each row in the forest shows: (1) study name, (2) point estimate as a
square sized by the study weight, (3) 95% CI as a horizontal whisker,
(4) numeric column with effect + CI. The bottom row shows the pooled
diamond — its width is the pooled CI; the diamond's centre is the
pooled point estimate. A diamond that does not cross the null (0 for
MD/SMD/RD, 1 for OR/RR/HR) indicates a statistically significant
pooled effect.

---

## Funnel plot interpretation

`meta_analysis.funnel_plot.FunnelPlot` (and the contour-enhanced
subclass `ContourEnhancedFunnel`) render the classic Egger funnel
(effect size on x-axis, SE on y-axis inverted). Asymmetry — a "hole"
in the bottom-right quadrant (large SE, large positive effect) — is
the canonical small-study / publication-bias signature.

```python
from meta_analysis.funnel_plot import ContourEnhancedFunnel

funnel = ContourEnhancedFunnel(es_list, pooled=result.pooled_effect)
funnel.add_significance_contours()      # regions of p<0.05 vs p≥0.05
funnel.add_pseudo_ci(alpha=0.95)        # 95% pseudo-CI cone
n_filled = funnel.add_trim_fill(method="R0")
fig = funnel.render(figsize=(8, 8), dpi=300, style="cochrane")
funnel.save("outputs/funnel.png", format="png")
```

The contour-enhanced funnel distinguishes asymmetry due to publication
bias (missing studies in p<0.05 region) from asymmetry due to other
small-study effects (missing studies in p≥0.05 region). Trim-and-fill
imputes the "missing" studies and reports a bias-adjusted pooled
estimate — call `funnel.pooled_effect` after `add_trim_fill` to read it.

---

## GRADE assessment integration

The **Grading of Recommendations Assessment, Development and Evaluation
(GRADE)** framework rates the certainty of evidence for each pooled
outcome on a four-level scale (High / Moderate / Low / Very Low).
ARS exposes GRADE working-group calculations under
`research_lifecycle.quality_assessment.MMAT` and via the
[`prisma`](prisma/) and [`research_lifecycle`](../research_lifecycle/)
integration layer — the per-study risk-of-bias assessments
(`CochraneRoB2.assess(...)`) feed directly into the GRADE "risk of
bias" domain, while the meta-analysis result's I² and τ² feed the
"inconsistency" domain. Egger's test / trim-and-fill feed the
"publication bias" domain.

The SR workflow (`/api/sr/...` endpoints) automatically assembles the
GRADE Summary-of-Findings (SoF) table when the meta-analysis result is
saved alongside the SR protocol. Use
[`research_lifecycle/quality_assessment.py`](../research_lifecycle/quality_assessment.py)
(`PRISMAComplianceChecklist`, `MMAT`, etc.) for the underlying tooling.

---

## Full workflow example

A complete meta-analysis with 10 dichotomous-outcome studies, DL
random-effects pooling, forest plot, contour-enhanced funnel plot with
trim-and-fill, and leave-one-out sensitivity analysis:

```python
import numpy as np
from meta_analysis.effect_sizes import EffectSizeCalculator, EffectSizeType
from meta_analysis.pooling import PoolingEngine, PoolingMethod
from meta_analysis.forest_plot import ForestPlot
from meta_analysis.funnel_plot import ContourEnhancedFunnel
from meta_analysis.subgroup import SensitivityAnalysis

# 1. Build 10 synthetic OR effect sizes (intervention vs control).
rng = np.random.default_rng(42)
es_list = []
for i in range(10):
    a = rng.integers(8, 30);   b = rng.integers(80, 120) - a
    c = rng.integers(20, 45);  d = rng.integers(80, 120) - c
    es = EffectSizeCalculator.from_dichotomous(
        events_intervention=int(a), total_intervention=int(a+b),
        events_control=int(c), total_control=int(c+d),
        type="OR",
    )
    es.study_id = f"S{i+1}"
    es.study_name = f"Study {i+1} (200{15+i})"
    es.year = 2015 + i
    es_list.append(es)

# 2. DerSimonian–Laird random-effects pooling.
result = PoolingEngine.pool(es_list, method=PoolingMethod.DL, confidence=0.95)
print(result.summary_text())
print(result.to_markdown())

# 3. Forest plot.
fp = ForestPlot(es_list, pooled=result.pooled_effect,
                title="Pooled OR (DL random effects)",
                x_label="Odds ratio (log scale)", x_scale="log",
                weights=result.weights, confidence=0.95)
fp.add_heterogeneity(
    f"I²={result.I_squared:.1f}%, τ²={result.tau_squared:.3f}, "
    f"Q={result.Q_statistic:.2f} (df={result.heterogeneity.df}, "
    f"p={result.Q_p_value:.3f})"
)
fp.add_favours_treatment_label()
fp.add_favours_control_label()
fp.render(figsize=(10, 8), dpi=300, style="cochrane")
fp.save("outputs/forest_dl.png", format="png")
fp.save("outputs/forest_dl.svg", format="svg")

# 4. Contour-enhanced funnel + Egger + trim-and-fill.
funnel = ContourEnhancedFunnel(es_list, pooled=result.pooled_effect)
funnel.add_significance_contours()
funnel.add_pseudo_ci(alpha=0.95)
n_filled = funnel.add_trim_fill(method="R0")
t, p, intercept = funnel.eggers_test()
tau_b, p_begg = funnel.beggs_test()
n_fs = funnel.rosenthal_fail_safe_n()
print(f"Trim-and-fill added {n_filled} studies.")
print(f"Egger: t={t:.2f}, p={p:.4g}")
print(f"Begg: tau={tau_b:.2f}, p={p_begg:.4g}")
print(f"Rosenthal fail-safe N = {n_fs} (5k+10 = {5*len(es_list)+10})")
funnel.render(figsize=(8, 8), dpi=300, style="cochrane")
funnel.save("outputs/funnel.png", format="png")

# 5. Leave-one-out sensitivity analysis.
sens = SensitivityAnalysis()
loo = sens.leave_one_out(es_list, method=PoolingMethod.DL)
for r in loo:
    pe = r.pooled_effect
    print(f"  omitting {pe.study_id}: OR={pe.value:.3f} "
          f"(95% CI {pe.ci_lower:.3f}–{pe.ci_upper:.3f}), p={r.p_value:.4g}")
sens.leave_one_out_forest(es_list, method=PoolingMethod.DL)
sens.galbraith_plot(es_list, pooled=result.pooled_effect)
```

This produces a complete evidence-synthesis bundle ready for
PRISMA-compliant journal submission: pooled effect + CI + p-value,
forest plot (PNG + SVG), funnel plot with significance contours and
trim-and-fill, Egger's test, Begg's test, Rosenthal fail-safe N, and
a leave-one-out forest plot. Combined with the
[`PRISMA_GUIDE.md`](PRISMA_GUIDE.md) outputs, this is everything needed
for the "Synthesis of results" and "Reporting biases" sections of a
Cochrane-style systematic review.

---

*Next: see [Q1_FIGURES_GUIDE.md](Q1_FIGURES_GUIDE.md) for how to
render the forest, funnel, and NMA plots as journal-specific figures
(Nature, Science, Cell, NEJM, Lancet, JAMA palettes), and
[PRISMA_GUIDE.md](PRISMA_GUIDE.md) for the upstream SR workflow.*
