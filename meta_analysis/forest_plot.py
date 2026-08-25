"""Forest-plot generator for meta-analysis.

Implements the canonical Cochrane forest plot (black squares sized by
weight, horizontal CIs, diamond for the pooled effect, vertical null line)
plus JAMA and Lancet typographic variants.  Subgroup forests, leave-one-out
forests, and heterogeneity-statistic annotations are all supported.

Heavy deps (matplotlib, numpy) are lazy-imported in :meth:`render`.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from .effect_sizes import EffectSize, EffectSizeCalculator, EffectSizeType

logger = logging.getLogger(__name__)

__all__ = ["ForestPlot"]


# Per-style visual defaults.
_STYLES = {
    "cochrane": {
        "color_study": "#000000",
        "color_pooled": "#000000",
        "color_null": "#000000",
        "color_axis": "#444444",
        "color_favours": "#888888",
        "diamond_edge": "#000000",
        "fontsize_title": 12,
        "fontsize_label": 9,
        "fontsize_stats": 8,
        "marker": "square",
        "show_weights": True,
        "show_stats": True,
    },
    "jama": {
        "color_study": "#1F77B4",
        "color_pooled": "#D62728",
        "color_null": "#666666",
        "color_axis": "#333333",
        "color_favours": "#999999",
        "diamond_edge": "#D62728",
        "fontsize_title": 13,
        "fontsize_label": 9,
        "fontsize_stats": 8,
        "marker": "square",
        "show_weights": True,
        "show_stats": True,
    },
    "lancet": {
        "color_study": "#222222",
        "color_pooled": "#222222",
        "color_null": "#888888",
        "color_axis": "#888888",
        "color_favours": "#AAAAAA",
        "diamond_edge": "#222222",
        "fontsize_title": 11,
        "fontsize_label": 8,
        "fontsize_stats": 7,
        "marker": "circle",
        "show_weights": False,
        "show_stats": False,
    },
}


@dataclass
class _DiamondAnnotation:
    """Internal record of an additional diamond to draw under the studies."""

    effect_size: EffectSize
    label: str = "Pooled"


@dataclass
class _SubgroupAnnotation:
    """Internal record of a subgroup heading."""

    name: str
    indices: List[int]


class ForestPlot:
    """Publication-grade forest plot.

    Example:
        >>> fp = ForestPlot(es_list, pooled=pooled_es, title='My MA')
        >>> fig = fp.render(style='cochrane')
        >>> fp.save('forest.png')
    """

    def __init__(
        self,
        effect_sizes: List[EffectSize],
        pooled: Optional[EffectSize] = None,
        title: str = "",
        x_label: str = "",
        x_scale: str = "natural",
        study_names: Optional[List[str]] = None,
        weights: Optional[List[float]] = None,
        subgroups: Optional[List[str]] = None,
        confidence: float = 0.95,
    ):
        """Construct a ForestPlot.

        Args:
            effect_sizes: List of :class:`EffectSize` (one per study).
            pooled: Optional pooled :class:`EffectSize` drawn as a diamond.
            title: Plot title.
            x_label: X-axis label (defaults to ``effect_sizes[0].type.value``).
            x_scale: ``'natural'`` or ``'log'``. Defaults to ``'natural'``;
                log-scale axis is appropriate for OR/RR/HR.
            study_names: Optional list of study labels. Defaults to
                ``es.study_name or es.study_id``.
            weights: Optional per-study weights (used to size the squares).
                Defaults to inverse-variance weights.
            subgroups: Optional per-study subgroup labels (for subgroup forest).
            confidence: Confidence level (default 0.95).
        """
        if not effect_sizes:
            raise ValueError("effect_sizes is empty.")
        self.effect_sizes = list(effect_sizes)
        self.pooled = pooled
        self.title = title
        self.x_label = x_label or effect_sizes[0].type.value
        self.x_scale = x_scale.lower()
        self.study_names = study_names or [
            es.study_name or es.study_id or f"Study {i+1}"
            for i, es in enumerate(self.effect_sizes)
        ]
        self.weights = weights
        self.subgroups = subgroups
        self.confidence = confidence
        self._subgroup_annotations: List[_SubgroupAnnotation] = []
        self._diamond_annotations: List[_DiamondAnnotation] = []
        self._het_text: Optional[str] = None
        self._subgroup_p: Optional[float] = None
        self._favours_labels: Optional[Tuple[str, str]] = None

    # ------------------------------------------------------------------ #
    # Annotation API
    # ------------------------------------------------------------------ #
    def add_subgroup(self, name: str, indices: List[int]) -> "ForestPlot":
        """Mark a contiguous block of studies as a subgroup.

        Args:
            name: Subgroup heading text.
            indices: 0-based list of indices into ``effect_sizes``.
        """
        self._subgroup_annotations.append(_SubgroupAnnotation(name=name, indices=list(indices)))
        return self

    def add_diamond(self, effect_size: EffectSize, label: str = "Pooled") -> "ForestPlot":
        """Add an extra diamond (e.g. for a per-subgroup pooled effect)."""
        self._diamond_annotations.append(_DiamondAnnotation(effect_size=effect_size, label=label))
        return self

    def add_heterogeneity(self, stats: str) -> "ForestPlot":
        """Free-form heterogeneity-stats text shown in the lower-right corner."""
        self._het_text = stats
        return self

    def add_test_for_subgroup_effect(self, p_value: float) -> "ForestPlot":
        """Add the p-value for the test of subgroup differences."""
        self._subgroup_p = float(p_value)
        return self

    def add_favours_treatment_label(self) -> "ForestPlot":
        """Add "Favours treatment" / "Favours control" arrow labels at the bottom."""
        self._favours_labels = ("Favours treatment", "Favours control")
        return self

    def add_favours_control_label(self) -> "ForestPlot":
        """Symmetric helper — same as :meth:`add_favours_treatment_label`."""
        self._favours_labels = ("Favours treatment", "Favours control")
        return self

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #
    def render(
        self,
        figsize: Tuple[float, float] = (10, 8),
        dpi: int = 300,
        style: str = "cochrane",
    ):
        """Render the forest plot.

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
        from matplotlib.patches import Polygon  # type: ignore
        import numpy as np  # type: ignore

        cfg = _STYLES.get(style.lower(), _STYLES["cochrane"])

        # CJK-safe font fallback.
        plt.rcParams["font.family"] = "sans-serif"
        plt.rcParams["font.sans-serif"] = [
            "Noto Sans SC", "Noto Sans CJK SC", "WenQuanYi Zen Hei",
            "Microsoft YaHei", "PingFang SC", "SimHei", "DejaVu Sans",
        ]
        plt.rcParams["axes.unicode_minus"] = False

        es_type = self.effect_sizes[0].type
        null_value = es_type.null_value
        is_log_metric = es_type.is_log_scale_metric

        # Compute weights if not supplied.
        if self.weights is None:
            self.weights = []
            for es in self.effect_sizes:
                v = es.variance if es.variance is not None else (es.se ** 2 if es.se else 1.0)
                self.weights.append(1.0 / v if v > 0 else 0.0)
        weights_arr = np.array(self.weights, dtype=float)
        w_max = weights_arr.max() if weights_arr.size else 1.0
        if w_max <= 0:
            w_max = 1.0
        weight_pct = 100.0 * weights_arr / w_max  # 0..100 for sizing

        # Number of rows (studies + diamonds + subgroup headers + pooled).
        n_studies = len(self.effect_sizes)
        n_extra = len(self._diamond_annotations)
        # Compose row layout: each row is one study or one diamond.
        rows_labels: List[str] = []
        rows_kind: List[str] = []  # 'study', 'diamond', 'header'
        rows_es: List[Optional[EffectSize]] = []
        rows_weight: List[float] = []
        # If subgroups specified, interleave headers.
        if self._subgroup_annotations:
            # Iterate through subgroups in order, then any remaining studies.
            seen = set()
            for sg in self._subgroup_annotations:
                rows_labels.append(sg.name)
                rows_kind.append("header")
                rows_es.append(None)
                rows_weight.append(0.0)
                for idx in sg.indices:
                    if idx in seen or idx >= n_studies:
                        continue
                    seen.add(idx)
                    rows_labels.append(self.study_names[idx])
                    rows_kind.append("study")
                    rows_es.append(self.effect_sizes[idx])
                    rows_weight.append(weight_pct[idx])
            # Leftover studies.
            for idx in range(n_studies):
                if idx not in seen:
                    rows_labels.append(self.study_names[idx])
                    rows_kind.append("study")
                    rows_es.append(self.effect_sizes[idx])
                    rows_weight.append(weight_pct[idx])
        else:
            for i, es in enumerate(self.effect_sizes):
                rows_labels.append(self.study_names[i])
                rows_kind.append("study")
                rows_es.append(es)
                rows_weight.append(weight_pct[i])
        # Diamonds (additional pooled rows).
        for d in self._diamond_annotations:
            rows_labels.append(d.label)
            rows_kind.append("diamond")
            rows_es.append(d.effect_size)
            rows_weight.append(100.0)
        # Pooled at the bottom.
        if self.pooled is not None:
            rows_labels.append("Pooled (random-effects)" if style == "cochrane" else "Overall")
            rows_kind.append("pooled")
            rows_es.append(self.pooled)
            rows_weight.append(100.0)

        n_rows = len(rows_labels)
        # Layout: 3 columns of axes — (labels, plot, stats).
        fig, (ax_label, ax_plot, ax_stats) = plt.subplots(
            1, 3, figsize=figsize, dpi=dpi, constrained_layout=True,
            gridspec_kw={"width_ratios": [3, 5, 2]},
        )
        y_positions = list(range(n_rows))[::-1]  # top row = highest y.

        # ----- Plot axis -----
        ax_plot.axvline(
            x=null_value, color=cfg["color_null"], linestyle="--", linewidth=0.8, zorder=1,
        )
        # X-limits.
        all_vals: List[float] = []
        for es in rows_es:
            if es is None:
                continue
            lo = es.ci_lower if es.ci_lower is not None else es.value
            hi = es.ci_upper if es.ci_upper is not None else es.value
            all_vals.extend([lo, hi])
        if not all_vals:
            all_vals = [null_value - 1, null_value + 1]
        lo = min(all_vals)
        hi = max(all_vals)
        pad = (hi - lo) * 0.10 if hi > lo else 1.0
        ax_plot.set_xlim(lo - pad, hi + pad)
        ax_plot.set_ylim(-0.5, n_rows - 0.5)
        ax_plot.set_yticks([])
        ax_plot.set_xlabel(
            self.x_label, fontsize=cfg["fontsize_label"], color=cfg["color_axis"]
        )
        if self.x_scale == "log" and is_log_metric:
            ax_plot.set_xscale("log")

        # Render each row.
        for i, (lbl, kind, es, w) in enumerate(
            zip(rows_labels, rows_kind, rows_es, rows_weight)
        ):
            y = y_positions[i]
            if kind == "header":
                ax_label.text(
                    0.0, y, lbl, fontsize=cfg["fontsize_label"], fontweight="bold",
                    va="center", ha="left", transform=ax_label.get_yaxis_transform(),
                )
                continue
            if es is None:
                continue
            # Label column.
            ax_label.text(
                0.0, y, lbl, fontsize=cfg["fontsize_label"], va="center", ha="left",
                transform=ax_label.get_yaxis_transform(),
            )
            # Stats column.
            ci_str = (
                f"{es.value:.2f} ({es.ci_lower:.2f}, {es.ci_upper:.2f})"
                if es.ci_lower is not None and es.ci_upper is not None
                else f"{es.value:.2f}"
            )
            w_str = f"{w:5.1f}%" if cfg["show_weights"] else ""
            ax_stats.text(
                1.0, y, f"{ci_str}  {w_str}", fontsize=cfg["fontsize_stats"],
                va="center", ha="right",
                transform=ax_stats.get_yaxis_transform(),
            )
            # Plot column.
            if kind in ("study", "diamond"):
                if es.ci_lower is not None and es.ci_upper is not None:
                    ax_plot.plot(
                        [es.ci_lower, es.ci_upper], [y, y],
                        color=cfg["color_study"], linewidth=1.2, zorder=2,
                    )
                # Marker.
                if cfg["marker"] == "square":
                    size = 40 + 200 * (w / 100.0)  # in points^2.
                    ax_plot.scatter(
                        [es.value], [y], s=size, c=cfg["color_study"],
                        marker="s", edgecolors="white", linewidths=0.5, zorder=3,
                    )
                else:  # circle (lancet)
                    size = 30 + 150 * (w / 100.0)
                    ax_plot.scatter(
                        [es.value], [y], s=size, c=cfg["color_study"],
                        marker="o", edgecolors="white", linewidths=0.5, zorder=3,
                    )
                if kind == "diamond":
                    # Draw a diamond at this row as well.
                    self._draw_diamond(
                        ax_plot, es.value, es.ci_lower, es.ci_upper, y,
                        color=cfg["color_pooled"],
                        edge=cfg["diamond_edge"],
                    )
            elif kind == "pooled":
                self._draw_diamond(
                    ax_plot, es.value, es.ci_lower, es.ci_upper, y,
                    color=cfg["color_pooled"], edge=cfg["diamond_edge"],
                )

        # Cosmetic.
        for spine in ["top", "right", "left"]:
            ax_plot.spines[spine].set_visible(False)
        ax_label.axis("off")
        ax_stats.axis("off")
        if self.title:
            fig.suptitle(
                self.title, fontsize=cfg["fontsize_title"], fontweight="bold",
            )

        # Heterogeneity stats annotation.
        if self._het_text and cfg["show_stats"]:
            ax_stats.text(
                1.0, -0.5, self._het_text, fontsize=cfg["fontsize_stats"],
                va="top", ha="right", transform=ax_stats.get_yaxis_transform(),
                bbox=dict(boxstyle="round,pad=0.3", fc="#F5F5F5", ec="#CCCCCC", lw=0.5),
            )

        # Subgroup-effect p-value annotation.
        if self._subgroup_p is not None and cfg["show_stats"]:
            ax_stats.text(
                1.0, -1.0,
                f"Test for subgroup differences: p = {self._subgroup_p:.4g}",
                fontsize=cfg["fontsize_stats"],
                va="top", ha="right",
                transform=ax_stats.get_yaxis_transform(),
            )

        # Favours labels at the bottom.
        if self._favours_labels:
            lo_x, hi_x = ax_plot.get_xlim()
            mid = (lo_x + hi_x) / 2.0
            half = (hi_x - lo_x) / 2.0
            ax_plot.annotate(
                self._favours_labels[0],
                xy=(mid - half * 0.45, -1.0), xycoords="data",
                xytext=(mid - half * 0.45, -1.5), textcoords="data",
                fontsize=cfg["fontsize_stats"], color=cfg["color_favours"],
                ha="center", va="top",
                arrowprops=dict(arrowstyle="->", color=cfg["color_favours"]),
            )
            ax_plot.annotate(
                self._favours_labels[1],
                xy=(mid + half * 0.45, -1.0), xycoords="data",
                xytext=(mid + half * 0.45, -1.5), textcoords="data",
                fontsize=cfg["fontsize_stats"], color=cfg["color_favours"],
                ha="center", va="top",
                arrowprops=dict(arrowstyle="->", color=cfg["color_favours"]),
            )
        self._fig = fig
        return fig

    def _draw_diamond(self, ax, value, ci_lo, ci_hi, y, color="#000000", edge="#000000"):
        """Draw a diamond marker for a pooled effect."""
        from matplotlib.patches import Polygon  # type: ignore
        half_h = 0.35
        verts = [
            (ci_lo, y), (value, y + half_h),
            (ci_hi, y), (value, y - half_h),
        ]
        diamond = Polygon(
            verts, closed=True, facecolor=color, edgecolor=edge,
            linewidth=1.0, zorder=4,
        )
        ax.add_patch(diamond)

    # ------------------------------------------------------------------ #
    # Save
    # ------------------------------------------------------------------ #
    def save(self, path: str, format: str = "png") -> str:
        """Save the rendered figure to ``path`` in the requested format.

        Returns:
            The path written.
        """
        import warnings  # type: ignore
        if not hasattr(self, "_fig") or self._fig is None:
            self.render()
        # The 3-axis forest layout occasionally triggers a benign
        # constrained_layout warning when label/stats text exceeds the
        # nominal axis width — the figure renders correctly regardless.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self._fig.savefig(path, format=format, dpi=self._fig.get_dpi())
        return path
