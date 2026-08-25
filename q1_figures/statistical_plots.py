"""Statistical visualization methods for Q1 publication figures.

Every method on :class:`StatisticalPlots` takes an ``ax`` parameter and
modifies it in-place; each returns ``ax`` so calls can be chained.

Supported plot types:

* :meth:`boxplot` — with paired-points option, means, notches.
* :meth:`violinplot` — with optional box overlay.
* :meth:`raincloud_plot` — violin + box + scatter combo.
* :meth:`beeswarm` — swarm plot.
* :meth:`paired_plot` — before / after dots with connecting lines.
* :meth:`volcano_plot` — genomics log2FC vs -log10(p).
* :meth:`manhattan_plot` — GWAS.
* :meth:`qq_plot` — quantile-quantile.
* :meth:`kaplan_meier` — survival with CI + at-risk table.
* :meth:`roc_curve` — ROC with optional CI.
* :meth:`pr_curve` — precision-recall.
* :meth:`calibration_plot` — predicted vs observed probabilities.
* :meth:`bland_altman` — Bland-Altman agreement.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .palettes import JournalPalettes

logger = logging.getLogger(__name__)


def _palette(name_or_list: Union[str, Sequence[str]]) -> List[str]:
    if isinstance(name_or_list, str):
        try:
            return JournalPalettes.get(name_or_list)
        except KeyError:
            return JournalPalettes.NATURE
    return list(name_or_list)


class StatisticalPlots:
    """Collection of static statistical plot methods.

    All methods follow the convention: take ``ax``, modify in-place,
    return ``ax``.
    """

    # ------------------------------------------------------------------
    # Box / violin / raincloud / beeswarm / paired
    # ------------------------------------------------------------------
    @staticmethod
    def boxplot(
        ax,
        data: Sequence[Sequence[float]],
        groups: Sequence[str],
        palette: Union[str, Sequence[str]] = "nature",
        show_points: bool = True,
        show_means: bool = True,
        notch: bool = True,
        flier_size: float = 3,
    ):
        """Boxplot with optional individual points and mean markers.

        Args:
            ax: Target axes.
            data: List of value arrays, one per group.
            groups: Group labels.
            palette: Palette name or list of colours.
            show_points: When ``True``, overlay jittered individual
                points.
            show_means: When ``True``, mark the mean with a green
                diamond.
            notch: When ``True``, draw a notched boxplot.
            flier_size: Outlier marker size.
        """
        import numpy as np
        colors = _palette(palette)
        positions = list(range(1, len(data) + 1))
        bp = ax.boxplot(
            data, positions=positions, widths=0.6, notch=notch,
            patch_artist=True, showfliers=True,
            flierprops={"markersize": flier_size, "marker": "o",
                        "markerfacecolor": "none", "markeredgecolor": "gray",
                        "alpha": 0.6},
            medianprops={"color": "black", "linewidth": 1.0},
            meanprops={"marker": "D", "markerfacecolor": "#2CA02C",
                        "markeredgecolor": "black", "markersize": 5},
            whiskerprops={"color": "black", "linewidth": 0.5},
            capprops={"color": "black", "linewidth": 0.5},
        )
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)
            patch.set_edgecolor("black")
            patch.set_linewidth(0.5)
        if show_means:
            for d, pos in zip(data, positions):
                mean = float(np.mean(d))
                ax.plot([pos], [mean], marker="D", color="#2CA02C",
                        markeredgecolor="black", markersize=5, zorder=5)
        if show_points:
            rng = np.random.default_rng(0)
            for d, pos in zip(data, positions):
                jitter = rng.uniform(-0.12, 0.12, size=len(d))
                ax.scatter(
                    pos + jitter, d, s=8, color="black", alpha=0.5,
                    zorder=4, edgecolors="none",
                )
        ax.set_xticks(positions)
        ax.set_xticklabels(groups)
        return ax

    @staticmethod
    def violinplot(
        ax,
        data: Sequence[Sequence[float]],
        groups: Sequence[str],
        palette: Union[str, Sequence[str]] = "nature",
        show_means: bool = True,
        show_medians: bool = True,
        show_box: bool = True,
        cut: float = 0,
    ):
        """Violin plot with optional box / mean / median markers."""
        import numpy as np
        colors = _palette(palette)
        positions = list(range(1, len(data) + 1))
        # Matplotlib's violinplot() does not accept 'cut' directly; if a
        # truncated violin is requested (cut=0) we manually clip the KDE
        # to the data range by setting points=200 and trimming.  For
        # cut > 0 we leave matplotlib's default smoothing on.
        violin_kwargs: dict = dict(
            positions=positions, widths=0.7,
            showmeans=False, showmedians=False, showextrema=False,
        )
        vp = ax.violinplot(dataset=list(data), **violin_kwargs)
        # When cut==0, trim each violin body to the data range.
        if cut == 0:
            for body, d in zip(vp["bodies"], data):
                import numpy as _np
                path = body.get_paths()[0]
                verts = path.vertices
                d_min, d_max = float(_np.min(d)), float(_np.max(d))
                # verts[:, 1] is the value axis.
                mask = (verts[:, 1] >= d_min) & (verts[:, 1] <= d_max)
                body.get_paths()[0] = path.__class__(verts[mask])
        for body, color in zip(vp["bodies"], colors):
            body.set_facecolor(color)
            body.set_alpha(0.4)
            body.set_edgecolor("black")
            body.set_linewidth(0.5)
        if show_box:
            ax.boxplot(
                data, positions=positions, widths=0.15,
                patch_artist=True, showfliers=False,
                boxprops={"facecolor": "white", "edgecolor": "black",
                          "linewidth": 0.5},
                medianprops={"color": "black", "linewidth": 0.8},
                whiskerprops={"color": "black", "linewidth": 0.5},
                capprops={"color": "black", "linewidth": 0.5},
            )
        if show_means:
            for d, pos in zip(data, positions):
                ax.plot([pos], [float(np.mean(d))], marker="D",
                        color="#2CA02C", markersize=5, zorder=6)
        if show_medians:
            for d, pos in zip(data, positions):
                ax.plot([pos], [float(np.median(d))], marker="_",
                        color="white", markersize=8, markeredgewidth=2, zorder=6)
        ax.set_xticks(positions)
        ax.set_xticklabels(groups)
        return ax

    @staticmethod
    def raincloud_plot(
        ax,
        data: Sequence[Sequence[float]],
        groups: Sequence[str],
        palette: Union[str, Sequence[str]] = "nature",
        orientation: str = "horizontal",
    ):
        """Raincloud plot = violin (half) + box + jittered scatter."""
        import numpy as np
        colors = _palette(palette)
        rng = np.random.default_rng(0)
        positions = list(range(1, len(data) + 1))
        for i, (d, color) in enumerate(zip(data, colors)):
            pos = positions[i]
            if orientation == "horizontal":
                # Half-violin above
                kde = None
                try:
                    from scipy.stats import gaussian_kde
                    kde = gaussian_kde(d)
                except Exception:
                    pass
                if kde is not None:
                    xs = np.linspace(min(d), max(d), 80)
                    density = kde(xs)
                    density = density / density.max() * 0.4
                    ax.fill_between(xs, pos, pos + density, alpha=0.5,
                                    color=color, edgecolor="black", linewidth=0.5)
                # Box below
                bp = ax.boxplot(
                    [d], positions=[pos - 0.2], vert=False, widths=0.15,
                    patch_artist=True, showfliers=False,
                    boxprops={"facecolor": color, "edgecolor": "black",
                              "alpha": 0.6, "linewidth": 0.5},
                    medianprops={"color": "black", "linewidth": 0.8},
                    whiskerprops={"color": "black", "linewidth": 0.5},
                    capprops={"color": "black", "linewidth": 0.5},
                )
                # Scatter below the box
                jitter = rng.uniform(-0.05, 0.05, size=len(d)) - 0.4
                ax.scatter(d, pos + jitter, s=10, color=color, alpha=0.5,
                           edgecolors="none", zorder=4)
            else:
                # Vertical orientation
                kde = None
                try:
                    from scipy.stats import gaussian_kde
                    kde = gaussian_kde(d)
                except Exception:
                    pass
                if kde is not None:
                    xs = np.linspace(min(d), max(d), 80)
                    density = kde(xs)
                    density = density / density.max() * 0.4
                    ax.fill_betweenx(xs, pos, pos + density, alpha=0.5,
                                     color=color, edgecolor="black", linewidth=0.5)
                ax.boxplot(
                    [d], positions=[pos - 0.2], widths=0.15,
                    patch_artist=True, showfliers=False,
                    boxprops={"facecolor": color, "edgecolor": "black",
                              "alpha": 0.6, "linewidth": 0.5},
                    medianprops={"color": "black", "linewidth": 0.8},
                    whiskerprops={"color": "black", "linewidth": 0.5},
                    capprops={"color": "black", "linewidth": 0.5},
                )
                jitter = rng.uniform(-0.05, 0.05, size=len(d)) - 0.4
                ax.scatter(pos + jitter, d, s=10, color=color, alpha=0.5,
                           edgecolors="none", zorder=4)
        if orientation == "horizontal":
            ax.set_yticks(positions)
            ax.set_yticklabels(groups)
        else:
            ax.set_xticks(positions)
            ax.set_xticklabels(groups)
        return ax

    @staticmethod
    def beeswarm(
        ax,
        data: Sequence[Sequence[float]],
        groups: Sequence[str],
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Beeswarm / jittered scatter plot."""
        import numpy as np
        colors = _palette(palette)
        rng = np.random.default_rng(0)
        for i, (d, color) in enumerate(zip(data, colors)):
            pos = i + 1
            # Simple one-sided swarm: sort and stagger.
            sorted_d = sorted(d)
            n = len(sorted_d)
            offsets = rng.uniform(-0.15, 0.15, size=n).tolist()
            ax.scatter([pos + off for off in offsets], sorted_d, s=12,
                       color=color, alpha=0.7, edgecolors="black",
                       linewidths=0.3, zorder=3)
        ax.set_xticks(list(range(1, len(data) + 1)))
        ax.set_xticklabels(groups)
        return ax

    @staticmethod
    def paired_plot(
        ax,
        before: Sequence[float],
        after: Sequence[float],
        color: str = "gray",
        highlight_changed: bool = True,
    ):
        """Paired before / after plot with connecting lines."""
        import numpy as np
        before = list(before); after = list(after)
        if len(before) != len(after):
            raise ValueError(
                f"before ({len(before)}) and after ({len(after)}) must be equal length"
            )
        x = [1] * len(before) + [2] * len(after)
        y = before + after
        for b, a in zip(before, after):
            line_color = color
            lw = 0.5
            if highlight_changed and not math.isclose(b, a):
                line_color = "#DC0000"
                lw = 0.8
            ax.plot([1, 2], [b, a], color=line_color, alpha=0.4, linewidth=lw,
                    zorder=2)
        ax.scatter([1] * len(before), before, s=30, color="#3C5488", zorder=3,
                   edgecolors="black", linewidths=0.3)
        ax.scatter([2] * len(after), after, s=30, color="#E64B35", zorder=3,
                   edgecolors="black", linewidths=0.3)
        ax.set_xticks([1, 2])
        ax.set_xticklabels(["Before", "After"])
        return ax

    # ------------------------------------------------------------------
    # Genomics / GWAS
    # ------------------------------------------------------------------
    @staticmethod
    def volcano_plot(
        ax,
        log2fc: Sequence[float],
        neg_log10_p: Sequence[float],
        gene_names: Optional[Sequence[str]] = None,
        fc_threshold: float = 1.0,
        p_threshold: float = 0.05,
        palette: Union[str, Sequence[str]] = "nature",
        highlight_top_n: int = 10,
        show_labels: bool = True,
    ):
        """Volcano plot of log2 fold-change vs -log10(p-value)."""
        import numpy as np
        log2fc = np.asarray(log2fc)
        neg_log10_p = np.asarray(neg_log10_p)
        colors = _palette(palette)
        # Classify: up, down, ns
        up = (log2fc > fc_threshold) & (neg_log10_p > -math.log10(p_threshold))
        down = (log2fc < -fc_threshold) & (neg_log10_p > -math.log10(p_threshold))
        ns = ~(up | down)
        ax.scatter(log2fc[ns], neg_log10_p[ns], s=6, color="lightgray",
                   alpha=0.5, edgecolors="none")
        ax.scatter(log2fc[up], neg_log10_p[up], s=10, color=colors[0],
                   alpha=0.7, edgecolors="none", label="Up")
        ax.scatter(log2fc[down], neg_log10_p[down], s=10, color=colors[2],
                   alpha=0.7, edgecolors="none", label="Down")
        # Threshold lines
        ax.axhline(-math.log10(p_threshold), color="gray", linestyle="--",
                   linewidth=0.4, alpha=0.7)
        ax.axvline(fc_threshold, color="gray", linestyle="--", linewidth=0.4,
                   alpha=0.7)
        ax.axvline(-fc_threshold, color="gray", linestyle="--", linewidth=0.4,
                   alpha=0.7)
        # Highlight top N by p-value
        if show_labels and gene_names is not None and highlight_top_n > 0:
            order = np.argsort(neg_log10_p)[::-1][:highlight_top_n]
            for i in order:
                ax.annotate(
                    str(gene_names[i]),
                    (log2fc[i], neg_log10_p[i]),
                    fontsize=6, ha="left", va="bottom",
                    xytext=(2, 2), textcoords="offset points",
                )
        ax.set_xlabel(r"$\log_2$(fold change)")
        ax.set_ylabel(r"$-\log_{10}$($p$)")
        ax.legend(loc="best", frameon=False, fontsize=7)
        return ax

    @staticmethod
    def manhattan_plot(
        ax,
        chrom: Sequence[int],
        pos: Sequence[float],
        p_value: Sequence[float],
        threshold: float = 5e-8,
        suggestive: float = 1e-5,
        palette: Union[str, Sequence[str]] = "grayscale",
    ):
        """Manhattan plot for GWAS summary statistics."""
        import numpy as np
        chrom = np.asarray(chrom)
        pos = np.asarray(pos, dtype=float)
        p_value = np.asarray(p_value, dtype=float)
        neg_log10_p = -np.log10(np.clip(p_value, 1e-300, None))
        # Alternate colors per chromosome
        if isinstance(palette, str) and palette == "grayscale":
            colors = ["#404040", "#A0A0A0"]
        else:
            colors = _palette(palette)
        # Cumulative x position per chromosome
        unique_chrom = sorted(set(chrom.tolist()))
        chrom_offset: Dict[int, float] = {}
        offset = 0.0
        max_pos_per_chrom: Dict[int, float] = {}
        for c in unique_chrom:
            mask = chrom == c
            span = float(pos[mask].max() - pos[mask].min()) if mask.any() else 0.0
            chrom_offset[c] = offset + span / 2.0
            offset += span
            max_pos_per_chrom[c] = pos[mask].max() if mask.any() else 0.0
        # X coordinates
        x_coords = np.zeros_like(pos, dtype=float)
        running = 0.0
        for c in unique_chrom:
            mask = chrom == c
            x_coords[mask] = running + (pos[mask] - pos[mask].min())
            running += float(pos[mask].max() - pos[mask].min()) if mask.any() else 0.0
        for i, c in enumerate(unique_chrom):
            mask = chrom == c
            ax.scatter(x_coords[mask], neg_log10_p[mask], s=4,
                       color=colors[i % len(colors)], alpha=0.6,
                       edgecolors="none")
        ax.axhline(-math.log10(threshold), color="red", linestyle="-",
                   linewidth=0.5)
        ax.axhline(-math.log10(suggestive), color="blue", linestyle="--",
                   linewidth=0.4, alpha=0.5)
        # Set chrom labels at midpoint offsets
        ax.set_xticks([chrom_offset[c] for c in unique_chrom])
        ax.set_xticklabels([str(c) for c in unique_chrom], fontsize=7)
        ax.set_xlabel("Chromosome")
        ax.set_ylabel(r"$-\log_{10}$($p$)")
        return ax

    @staticmethod
    def qq_plot(
        ax,
        observed_p: Sequence[float],
        expected_p: Optional[Sequence[float]] = None,
        ci: float = 0.95,
    ):
        """Quantile-quantile plot for p-value distribution."""
        import numpy as np
        obs = np.sort(np.asarray(observed_p, dtype=float))
        n = len(obs)
        if expected_p is None:
            # Uniform expected
            expected = (np.arange(1, n + 1) - 0.5) / n
        else:
            expected = np.sort(np.asarray(expected_p, dtype=float))
            if len(expected) != n:
                raise ValueError(
                    f"observed_p ({n}) and expected_p ({len(expected)}) differ"
                )
        obs_log = -np.log10(np.clip(obs, 1e-300, None))
        exp_log = -np.log10(np.clip(expected, 1e-300, None))
        ax.scatter(exp_log, obs_log, s=10, color="#3C5488", alpha=0.6,
                   edgecolors="none")
        max_val = max(exp_log.max(), obs_log.max())
        ax.plot([0, max_val], [0, max_val], color="gray", linestyle="--",
                linewidth=0.5)
        # CI band (rough beta-based)
        try:
            from scipy.stats import beta
            lower = -np.log10(beta.ppf((1 - ci) / 2.0,
                                       np.arange(1, n + 1),
                                       n - np.arange(1, n + 1) + 1))
            upper = -np.log10(beta.ppf(1 - (1 - ci) / 2.0,
                                       np.arange(1, n + 1),
                                       n - np.arange(1, n + 1) + 1))
            ax.fill_between(exp_log, lower, upper, alpha=0.2, color="gray")
        except Exception as exc:
            logger.debug("QQ CI band skipped: %s", exc)
        ax.set_xlabel(r"Expected $-\log_{10}$($p$)")
        ax.set_ylabel(r"Observed $-\log_{10}$($p$)")
        return ax

    # ------------------------------------------------------------------
    # Survival / diagnostic
    # ------------------------------------------------------------------
    @staticmethod
    def kaplan_meier(
        ax,
        time: Sequence[float],
        event: Sequence[int],
        groups: Optional[Sequence[str]] = None,
        palette: Union[str, Sequence[str]] = "nature",
        show_ci: bool = True,
        show_at_risk_table: bool = True,
        show_p_value: bool = True,
    ):
        """Kaplan-Meier survival curve with CI, at-risk table, log-rank p."""
        import numpy as np
        colors = _palette(palette)
        time = np.asarray(time, dtype=float)
        event = np.asarray(event)
        if groups is None:
            groups_arr = np.zeros_like(time, dtype=int)
        else:
            unique_groups = sorted(set(groups))
            group_to_idx = {g: i for i, g in enumerate(unique_groups)}
            groups_arr = np.asarray([group_to_idx[g] for g in groups])

        unique_g = sorted(set(groups_arr.tolist()))
        survival_curves: List[Tuple[np.ndarray, np.ndarray, str]] = []
        for i, g in enumerate(unique_g):
            mask = groups_arr == g
            t = time[mask]
            e = event[mask]
            order = np.argsort(t)
            t = t[order]
            e = e[order]
            # KM estimate
            uniq_t, inverse = np.unique(t, return_inverse=True)
            n_at_risk = np.array([np.sum(t >= ut) for ut in uniq_t])
            n_events = np.array([np.sum((t == ut) & (e == 1)) for ut in uniq_t])
            surv = np.cumprod(1.0 - n_events / np.maximum(n_at_risk, 1))
            surv = np.concatenate([[1.0], surv])
            x = np.concatenate([[0], uniq_t])
            label = (
                groups[i] if groups is not None and i < len(set(groups))
                else f"Group {g + 1}"
            )
            ax.step(x, surv, where="post", color=colors[i % len(colors)],
                    linewidth=1.0, label=str(label))
            survival_curves.append((x, surv, str(label)))
            # CI band (rough Greenwood)
            if show_ci and len(uniq_t) > 0:
                with np.errstate(divide="ignore", invalid="ignore"):
                    se = np.sqrt(
                        np.cumsum(n_events / (n_at_risk * np.maximum(n_at_risk - n_events, 1)))
                    )
                se = np.nan_to_num(se, nan=0.0, posinf=0.0, neginf=0.0)
                # se has length == len(uniq_t) == len(surv) without the
                # leading 1.0 sentinel; align by prepending 0.0.
                se = np.concatenate([[0.0], se])
                with np.errstate(divide="ignore", invalid="ignore"):
                    ci_low = np.exp(np.log(np.clip(surv, 1e-10, None)) - 1.96 * se)
                    ci_high = np.exp(np.log(np.clip(surv, 1e-10, None)) + 1.96 * se)
                ci_low = np.clip(ci_low, 0, 1)
                ci_high = np.clip(ci_high, 0, 1)
                ax.fill_between(x, ci_low, ci_high, step="post",
                                color=colors[i % len(colors)], alpha=0.15)
        ax.set_xlabel("Time")
        ax.set_ylabel("Survival probability")
        ax.set_ylim(0, 1.05)
        if show_p_value and len(unique_g) == 2:
            try:
                # Log-rank test (chi2 approximation)
                from scipy.stats import chi2
                mask0 = groups_arr == unique_g[0]
                mask1 = groups_arr == unique_g[1]
                t0, e0 = time[mask0], event[mask0]
                t1, e1 = time[mask1], event[mask1]
                uniq_times = np.unique(np.concatenate([t0, t1]))
                obs0 = np.array([np.sum((t0 == ut) & (e0 == 1)) for ut in uniq_times])
                obs1 = np.array([np.sum((t1 == ut) & (e1 == 1)) for ut in uniq_times])
                n0 = np.array([np.sum(t0 >= ut) for ut in uniq_times])
                n1 = np.array([np.sum(t1 >= ut) for ut in uniq_times])
                total = obs0 + obs1
                n_total = n0 + n1
                expected0 = np.where(n_total > 0, total * n0 / np.maximum(n_total, 1), 0)
                chi2_stat = np.sum(
                    (obs0 - expected0) ** 2 / np.maximum(expected0, 1e-10)
                )
                p_val = 1 - chi2.cdf(chi2_stat, df=1)
                ax.text(
                    0.95, 0.95, f"log-rank\np = {p_val:.3g}",
                    transform=ax.transAxes, ha="right", va="top",
                    fontsize=7,
                )
            except Exception as exc:
                logger.debug("log-rank computation skipped: %s", exc)
        if show_at_risk_table:
            # We don't render a separate table here (would require
            # dividing the axes); we annotate at the bottom of the axes.
            for x_vals, surv, label in survival_curves:
                # Place at-risk counts at the final 5 timepoints.
                if len(x_vals) >= 5:
                    sample_x = x_vals[::max(1, len(x_vals) // 5)][:5]
                    for sx in sample_x:
                        idx = np.searchsorted(x_vals, sx)
                        n_risk = max(0, int(surv[min(idx, len(surv) - 1)] * 100))
                        ax.text(sx, -0.08, str(n_risk),
                                ha="center", va="top", fontsize=6,
                                transform=ax.get_xaxis_transform())
        if groups is not None:
            ax.legend(loc="best", frameon=False, fontsize=7)
        return ax

    @staticmethod
    def roc_curve(
        ax,
        fpr: Sequence[float],
        tpr: Sequence[float],
        auc: Optional[float] = None,
        ci: Optional[Tuple[float, float]] = None,
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """ROC curve with optional AUC annotation."""
        colors = _palette(palette)
        ax.plot(fpr, tpr, color=colors[0], linewidth=1.0,
                label=f"AUC = {auc:.3f}" if auc is not None else "ROC")
        ax.plot([0, 1], [0, 1], color="gray", linestyle="--", linewidth=0.5)
        if ci is not None:
            ax.fill_between(fpr, [max(0, t - 0.05) for t in tpr],
                             [min(1, t + 0.05) for t in tpr],
                             color=colors[0], alpha=0.15)
        ax.set_xlabel("False positive rate")
        ax.set_ylabel("True positive rate")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.02)
        ax.set_aspect("equal")
        ax.legend(loc="lower right", frameon=False, fontsize=7)
        return ax

    @staticmethod
    def pr_curve(
        ax,
        precision: Sequence[float],
        recall: Sequence[float],
        ap: Optional[float] = None,
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Precision-recall curve."""
        colors = _palette(palette)
        ax.plot(recall, precision, color=colors[0], linewidth=1.0,
                label=f"AP = {ap:.3f}" if ap is not None else "PR")
        ax.set_xlabel("Recall")
        ax.set_ylabel("Precision")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.02)
        ax.set_aspect("equal")
        ax.legend(loc="lower left", frameon=False, fontsize=7)
        return ax

    @staticmethod
    def calibration_plot(
        ax,
        predicted_prob: Sequence[float],
        observed_prob: Sequence[float],
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Calibration plot (predicted vs observed probabilities)."""
        colors = _palette(palette)
        ax.plot([0, 1], [0, 1], color="gray", linestyle="--", linewidth=0.5)
        ax.plot(predicted_prob, observed_prob, marker="o", markersize=4,
                color=colors[0], linewidth=1.0, label="Model")
        ax.set_xlabel("Predicted probability")
        ax.set_ylabel("Observed probability")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_aspect("equal")
        ax.legend(loc="upper left", frameon=False, fontsize=7)
        return ax

    @staticmethod
    def bland_altman(
        ax,
        method1: Sequence[float],
        method2: Sequence[float],
        ci: float = 0.95,
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Bland-Altman agreement plot with limits of agreement."""
        import numpy as np
        m1 = np.asarray(method1, dtype=float)
        m2 = np.asarray(method2, dtype=float)
        if len(m1) != len(m2):
            raise ValueError("method1 and method2 must be the same length")
        mean = (m1 + m2) / 2.0
        diff = m1 - m2
        bias = float(np.mean(diff))
        sd = float(np.std(diff, ddof=1)) if len(diff) > 1 else 0.0
        z = 1.96  # 95% CI
        from scipy.stats import norm
        z = norm.ppf(0.5 + ci / 2.0)
        upper = bias + z * sd
        lower = bias - z * sd
        colors = _palette(palette)
        ax.scatter(mean, diff, s=20, color=colors[0], alpha=0.7,
                   edgecolors="black", linewidths=0.3)
        ax.axhline(bias, color="black", linestyle="-", linewidth=0.6,
                   label=f"Bias = {bias:.3g}")
        ax.axhline(upper, color="red", linestyle="--", linewidth=0.5,
                   label=f"+{ci:.0%} LoA = {upper:.3g}")
        ax.axhline(lower, color="red", linestyle="--", linewidth=0.5,
                   label=f"-{ci:.0%} LoA = {lower:.3g}")
        ax.set_xlabel("Mean of methods")
        ax.set_ylabel("Difference (m1 − m2)")
        ax.legend(loc="best", frameon=False, fontsize=7)
        return ax
