"""Regression tests that lock the numbers printed in README.md.

Every expected value is derived independently (by hand / closed form) so a
documentation or implementation drift is caught immediately.
"""
from __future__ import annotations

import math

CITATIONS = [120, 45, 30, 12, 8, 5, 3, 1, 0, 0]
YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2025, 2025]
AUTHORS = [3, 4, 2, 5, 6, 2, 3, 4, 1, 1]


def test_readme_hirsch_family_values():
    from bibliometrics import quick_stats

    s = quick_stats(citations=CITATIONS, years=YEARS, author_counts=AUTHORS)
    # h: five papers (120, 45, 30, 12, 8) have >= 5 citations; the 6th has 5 < 6.
    assert s["h_index"] == 5
    # g (capped at the number of papers): cumulative 224 >= 10**2.
    assert s["g_index"] == 10
    assert s["i10_index"] == 4
    # e = sqrt(sum_{i<=h}(c_i - h)) = sqrt(215 - 25) = sqrt(190)
    assert math.isclose(s["e_index"], math.sqrt(190), rel_tol=1e-12)


def test_readme_dersimonian_laird_example():
    from meta_analysis.effect_sizes import EffectSize, EffectSizeType
    from meta_analysis.pooling import PoolingEngine, PoolingMethod

    data = [(2.1, 0.8, 42), (1.8, 0.7, 55), (2.5, 1.1, 30), (1.4, 0.6, 68), (2.0, 0.9, 44)]
    studies = [
        EffectSize(type=EffectSizeType.MD, value=v, se=se, n_total=n, study_id=f"s{i}")
        for i, (v, se, n) in enumerate(data)
    ]
    res = PoolingEngine().pool(studies, method=PoolingMethod.DL)

    w = [1 / se ** 2 for _, se, _ in data]
    est = sum(wi * v for wi, (v, _, _) in zip(w, data)) / sum(w)
    se_pooled = 1 / math.sqrt(sum(w))
    q = sum(wi * (v - est) ** 2 for wi, (v, _, _) in zip(w, data))

    pooled = res.pooled_effect
    assert math.isclose(pooled.value, est, rel_tol=1e-9)           # 1.8217
    assert math.isclose(pooled.se, se_pooled, rel_tol=1e-9)        # 0.3442
    assert math.isclose(pooled.ci_lower, est - 1.96 * se_pooled, abs_tol=0.01)
    assert math.isclose(pooled.ci_upper, est + 1.96 * se_pooled, abs_tol=0.01)
    assert q < 4          # Q below df => tau^2 = 0 under DL
    assert res.I_squared == 0.0
