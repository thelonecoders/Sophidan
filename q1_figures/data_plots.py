"""Publication-grade general-purpose data plots.

The :class:`Q1DataPlots` class exposes a range of plot types commonly
used in Q1 publications: scatter, line, bar (vertical / horizontal /
stacked / grouped), heatmap, clustered heatmap, density, contour,
ridgeline (joy), parallel coordinates, and polar.

Each method takes an ``ax`` parameter and modifies it in-place; each
returns ``ax`` for chaining.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
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


class Q1DataPlots:
    """Collection of publication-grade general-purpose data plot methods."""

    # ------------------------------------------------------------------
    # Scatter / line
    # ------------------------------------------------------------------
    @staticmethod
    def scatter(
        ax,
        x,
        y,
        color=None,
        size=None,
        alpha: float = 0.7,
        palette: Union[str, Sequence[str]] = "nature",
        regression_line: bool = False,
        ci_band: bool = True,
        marginal_x: Optional[str] = None,
        marginal_y: Optional[str] = None,
    ):
        """Scatter plot with optional regression line, CI band, and marginals.

        Args:
            ax: Target axes.  When ``marginal_x`` or ``marginal_y`` is
                set, the axes should be embedded in a
                :class:`matplotlib.gridspec.GridSpec` (or use
                ``make_axes_locatable``).  When neither marginal is
                requested, a plain ``ax`` is fine.
            x, y: Data arrays.
            color: Optional colour for all points; when ``None``, a
                single palette colour is used.
            size: Optional per-point sizes.
            alpha: Point transparency.
            palette: Palette name.
            regression_line: When ``True``, draw an OLS regression line.
            ci_band: When ``True`` and ``regression_line=True``, draw a
                95 % CI band around the regression.
            marginal_x: ``'histogram'``, ``'kde'``, ``'rug'`` or ``None``.
            marginal_y: Same options for the Y axis.
        """
        import numpy as np
        colors = _palette(palette)
        # Build main scatter
        if color is None:
            color = colors[0]
        kwargs = dict(s=size if size is not None else 20, alpha=alpha,
                       edgecolors="black", linewidths=0.3)
        ax.scatter(x, y, color=color, **kwargs)
        # Regression + CI band
        if regression_line:
            try:
                from scipy import stats
                x_arr = np.asarray(x, dtype=float)
                y_arr = np.asarray(y, dtype=float)
                mask = np.isfinite(x_arr) & np.isfinite(y_arr)
                if mask.sum() >= 3:
                    slope, intercept, r, p, se = stats.linregress(
                        x_arr[mask], y_arr[mask]
                    )
                    x_line = np.linspace(x_arr.min(), x_arr.max(), 100)
                    y_line = slope * x_line + intercept
                    ax.plot(x_line, y_line, color="black", linewidth=0.8,
                            label=f"$r$ = {r:.3f}")
                    if ci_band:
                        y_hat = slope * x_arr[mask] + intercept
                        residuals = y_arr[mask] - y_hat
                        dof = max(mask.sum() - 2, 1)
                        std_err = np.sqrt(np.sum(residuals ** 2) / dof)
                        ci = 1.96 * std_err
                        ax.fill_between(
                            x_line, y_line - ci, y_line + ci,
                            color="gray", alpha=0.15,
                        )
                    ax.legend(loc="best", frameon=False, fontsize=7)
            except Exception as exc:
                logger.debug("Regression skipped: %s", exc)
        # Marginals
        if marginal_x is not None or marginal_y is not None:
            try:
                from mpl_toolkits.axes_grid1 import make_axes_locatable
                divider = make_axes_locatable(ax)
                if marginal_x is not None:
                    ax_marg_x = divider.append_axes("top", size="15%", pad=0.05, sharex=ax)
                    Q1DataPlots._draw_marginal(ax_marg_x, x, marginal_x, axis="x",
                                                 color=colors[1])
                if marginal_y is not None:
                    ax_marg_y = divider.append_axes("right", size="15%", pad=0.05, sharey=ax)
                    Q1DataPlots._draw_marginal(ax_marg_y, y, marginal_y, axis="y",
                                                 color=colors[1])
            except Exception as exc:
                logger.debug("Marginal axes skipped: %s", exc)
        return ax

    @staticmethod
    def _draw_marginal(ax, data, kind: str, axis: str, color: str):
        import numpy as np
        if kind == "histogram":
            ax.hist(data, bins=20, color=color, alpha=0.6)
        elif kind == "kde":
            try:
                from scipy.stats import gaussian_kde
                kde = gaussian_kde(np.asarray(data))
                xs = np.linspace(min(data), max(data), 80)
                density = kde(xs)
                if axis == "x":
                    ax.plot(xs, density, color=color)
                    ax.fill_between(xs, density, alpha=0.3, color=color)
                else:
                    ax.plot(density, xs, color=color)
                    ax.fill_betweenx(xs, density, alpha=0.3, color=color)
            except Exception as exc:
                logger.debug("KDE marginal skipped: %s", exc)
        elif kind == "rug":
            if axis == "x":
                ax.plot(data, [0.5] * len(data), "|", color=color, ms=8)
            else:
                ax.plot([0.5] * len(data), data, "_", color=color, ms=8)
        ax.set_xticks([])
        ax.set_yticks([])

    @staticmethod
    def line_plot(
        ax,
        x,
        y,
        color_by=None,
        palette: Union[str, Sequence[str]] = "nature",
        error_bands=None,
        error_lines=None,
        marker: str = "o",
        linestyle: str = "-",
        linewidth: float = 1.0,
        markersize: int = 4,
    ):
        """Line plot with optional error bands / lines.

        Args:
            ax: Target axes.
            x: X values.  When ``color_by`` is a list of group labels,
                ``x`` may be ``None`` (per-group x inferred from index).
            y: Either a 1-D array (single line) or a 2-D array (multiple
                lines).
            color_by: Optional list of group labels (length == number
                of lines).
            palette: Palette name.
            error_bands: Optional ``(lower, upper)`` arrays (same shape
                as ``y``) for shaded error bands.
            error_lines: Optional array (same shape as ``y``) for
                thin error lines.
            marker, linestyle, linewidth, markersize: Standard
                matplotlib style options.
        """
        import numpy as np
        colors = _palette(palette)
        y_arr = np.asarray(y)
        x_arr = np.asarray(x) if x is not None else None
        if y_arr.ndim == 1:
            y_arr = y_arr.reshape(-1, 1).T  # 1 row of len(x)
        n_lines = y_arr.shape[0]
        labels = list(color_by) if color_by is not None else [None] * n_lines
        for i in range(n_lines):
            y_row = y_arr[i]
            if x_arr is None:
                x_row = np.arange(len(y_row))
            else:
                x_row = x_arr
            color = colors[i % len(colors)]
            ax.plot(
                x_row, y_row,
                color=color, marker=marker, linestyle=linestyle,
                linewidth=linewidth, markersize=markersize,
                label=labels[i],
            )
            if error_bands is not None:
                lower, upper = error_bands
                lower_arr = np.asarray(lower)
                upper_arr = np.asarray(upper)
                if lower_arr.ndim == 1:
                    lower_arr = lower_arr.reshape(1, -1)
                    upper_arr = upper_arr.reshape(1, -1)
                ax.fill_between(x_row, lower_arr[i], upper_arr[i],
                                color=color, alpha=0.15)
            if error_lines is not None:
                err = np.asarray(error_lines)
                if err.ndim == 1:
                    err = err.reshape(1, -1)
                ax.plot(x_row, err[i], color=color, linestyle=":",
                        linewidth=0.5, alpha=0.6)
        if color_by is not None:
            ax.legend(loc="best", frameon=False, fontsize=7)
        return ax

    # ------------------------------------------------------------------
    # Bar plots
    # ------------------------------------------------------------------
    @staticmethod
    def bar_plot(
        ax,
        categories: Sequence[str],
        values: Sequence[float],
        error: Optional[Sequence[float]] = None,
        palette: Union[str, Sequence[str]] = "nature",
        bar_type: str = "vertical",
        error_bar_type: str = "std",
        show_individual_points: bool = True,
    ):
        """Bar plot (vertical or horizontal) with error bars."""
        import numpy as np
        colors = _palette(palette)
        positions = list(range(len(categories)))
        bar_colors = [colors[i % len(colors)] for i in positions]
        if bar_type == "horizontal":
            bars = ax.barh(positions, values, color=bar_colors,
                            edgecolor="black", linewidth=0.5)
            ax.set_yticks(positions)
            ax.set_yticklabels(categories)
            if error is not None:
                ax.errorbar(values, positions, xerr=error, fmt="none",
                             color="black", capsize=2, linewidth=0.5)
            if show_individual_points:
                rng = np.random.default_rng(0)
                jitter = rng.uniform(-0.1, 0.1, size=len(values))
                ax.scatter(values, positions + jitter, s=10, color="black",
                            alpha=0.4, edgecolors="none", zorder=3)
        else:
            bars = ax.bar(positions, values, color=bar_colors,
                            edgecolor="black", linewidth=0.5)
            ax.set_xticks(positions)
            ax.set_xticklabels(categories, rotation=0)
            if error is not None:
                ax.errorbar(positions, values, yerr=error, fmt="none",
                             color="black", capsize=2, linewidth=0.5)
            if show_individual_points:
                rng = np.random.default_rng(0)
                jitter = rng.uniform(-0.1, 0.1, size=len(values))
                ax.scatter(positions + jitter, values, s=10, color="black",
                            alpha=0.4, edgecolors="none", zorder=3)
        return ax

    @staticmethod
    def stacked_bar(
        ax,
        categories: Sequence[str],
        sub_categories: Sequence[str],
        values_matrix,
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Stacked bar chart.

        Args:
            ax: Target axes.
            categories: N main categories (X axis).
            sub_categories: M sub-categories (stacked colours).
            values_matrix: 2-D array of shape ``(M, N)`` — rows are
                sub-categories, columns are main categories.
        """
        import numpy as np
        colors = _palette(palette)
        mat = np.asarray(values_matrix)
        positions = np.arange(len(categories))
        bottom = np.zeros(len(categories))
        for i, (sub_name, row) in enumerate(zip(sub_categories, mat)):
            ax.bar(
                positions, row, bottom=bottom,
                color=colors[i % len(colors)],
                edgecolor="white", linewidth=0.4, label=sub_name,
            )
            bottom = bottom + row
        ax.set_xticks(positions)
        ax.set_xticklabels(categories)
        ax.legend(loc="best", frameon=False, fontsize=7)
        return ax

    @staticmethod
    def grouped_bar(
        ax,
        categories: Sequence[str],
        sub_categories: Sequence[str],
        values_matrix,
        palette: Union[str, Sequence[str]] = "nature",
        error=None,
    ):
        """Grouped bar chart.

        Args:
            ax: Target axes.
            categories: N main groups.
            sub_categories: M sub-categories per group.
            values_matrix: 2-D array of shape ``(M, N)``.
            error: Optional ``(M, N)`` error matrix.
        """
        import numpy as np
        colors = _palette(palette)
        mat = np.asarray(values_matrix)
        n_cats = len(categories)
        n_subs = len(sub_categories)
        group_width = 0.8
        bar_width = group_width / max(n_subs, 1)
        positions = np.arange(n_cats)
        for i, sub_name in enumerate(sub_categories):
            offset = (i - (n_subs - 1) / 2.0) * bar_width
            err_row = None
            if error is not None:
                err_row = np.asarray(error)[i]
            ax.bar(
                positions + offset, mat[i], width=bar_width,
                color=colors[i % len(colors)],
                edgecolor="black", linewidth=0.3,
                yerr=err_row, capsize=1.5,
                error_kw={"linewidth": 0.5, "ecolor": "black"},
                label=sub_name,
            )
        ax.set_xticks(positions)
        ax.set_xticklabels(categories)
        ax.legend(loc="best", frameon=False, fontsize=7, ncol=min(n_subs, 4))
        return ax

    # ------------------------------------------------------------------
    # Heatmaps
    # ------------------------------------------------------------------
    @staticmethod
    def heatmap(
        ax,
        data,
        row_labels: Optional[Sequence[str]] = None,
        col_labels: Optional[Sequence[str]] = None,
        palette: str = "viridis",
        annotate_cells: bool = True,
        fmt: str = ".2f",
        cmap_centered: bool = False,
        vmin: Optional[float] = None,
        vmax: Optional[float] = None,
        show_colorbar: bool = True,
    ):
        """Heatmap with optional cell annotations and colorbar.

        Args:
            ax: Target axes.
            data: 2-D array.
            row_labels, col_labels: Tick labels.
            palette: Palette name (passed through ``as_cmap`` for
                continuous use).
            annotate_cells: When ``True``, annotate each cell with
                its value.
            fmt: ``format`` string for cell annotations.
            cmap_centered: When ``True``, use a diverging cmap
                centred on 0.
            vmin, vmax: Colour-scale limits.
            show_colorbar: When ``True``, attach a colorbar.
        """
        import numpy as np
        try:
            cmap = JournalPalettes.as_cmap(palette)
        except KeyError:
            cmap = JournalPalettes.as_cmap("viridis")
        mat = np.asarray(data)
        if cmap_centered:
            max_abs = np.nanmax(np.abs(mat)) or 1.0
            vmin = vmin if vmin is not None else -max_abs
            vmax = vmax if vmax is not None else max_abs
        im = ax.imshow(mat, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
        n_rows, n_cols = mat.shape
        if row_labels is not None:
            ax.set_yticks(range(n_rows))
            ax.set_yticklabels(row_labels, fontsize=7)
        if col_labels is not None:
            ax.set_xticks(range(n_cols))
            ax.set_xticklabels(col_labels, fontsize=7, rotation=45, ha="right")
        if annotate_cells:
            for i in range(n_rows):
                for j in range(n_cols):
                    v = mat[i, j]
                    color = "white" if abs(v - (vmin or 0)) > abs(vmax - vmin or 1) * 0.6 else "#222222"
                    ax.text(j, i, format(v, fmt), ha="center", va="center",
                            fontsize=6, color=color)
        if show_colorbar:
            from matplotlib import pyplot as plt
            cb = plt.colorbar(im, ax=ax, shrink=0.8)
            cb.ax.tick_params(labelsize=7)
        return ax

    @staticmethod
    def clustered_heatmap(
        data,
        row_labels: Optional[Sequence[str]] = None,
        col_labels: Optional[Sequence[str]] = None,
        palette: str = "viridis",
        method: str = "ward",
        metric: str = "euclidean",
        show_dendro: bool = True,
    ):
        """Clustered heatmap with hierarchical-clustering dendrograms.

        Returns a new matplotlib Figure (not an Axes) because the
        dendrograms require a multi-axes layout.
        """
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib import gridspec
        from scipy.cluster.hierarchy import linkage, dendrogram
        try:
            cmap = JournalPalettes.as_cmap(palette)
        except KeyError:
            cmap = JournalPalettes.as_cmap("viridis")
        mat = np.asarray(data, dtype=float)
        n_rows, n_cols = mat.shape
        if row_labels is None:
            row_labels = [str(i) for i in range(n_rows)]
        if col_labels is None:
            col_labels = [str(j) for j in range(n_cols)]
        # Cluster rows and columns
        from scipy.spatial.distance import pdist
        try:
            Z_rows = linkage(pdist(mat, metric=metric), method=method)
            Z_cols = linkage(pdist(mat.T, metric=metric), method=method)
            row_order = dendrogram(Z_rows, no_plot=True)["leaves"]
            col_order = dendrogram(Z_cols, no_plot=True)["leaves"]
        except Exception as exc:
            logger.debug("Clustering skipped: %s", exc)
            row_order = list(range(n_rows))
            col_order = list(range(n_cols))
            Z_rows = Z_cols = None
        mat_o = mat[np.ix_(row_order, col_order)]
        row_labels_o = [row_labels[i] for i in row_order]
        col_labels_o = [col_labels[j] for j in col_order]
        if show_dendro and Z_rows is not None:
            fig = plt.figure(figsize=(7, 7), constrained_layout=True, dpi=120)
            gs = gridspec.GridSpec(2, 2, width_ratios=[1, 5], height_ratios=[1, 5],
                                   figure=fig)
            ax_top = fig.add_subplot(gs[0, 1])
            ax_left = fig.add_subplot(gs[1, 0])
            ax_main = fig.add_subplot(gs[1, 1])
            dendrogram(Z_cols, ax=ax_top)
            ax_top.set_axis_off()
            dendrogram(Z_rows, ax=ax_left, orientation="left")
            ax_left.set_axis_off()
            im = ax_main.imshow(mat_o, cmap=cmap, aspect="auto")
            ax_main.set_xticks(range(n_cols))
            ax_main.set_xticklabels(col_labels_o, fontsize=6, rotation=45, ha="right")
            ax_main.set_yticks(range(n_rows))
            ax_main.set_yticklabels(row_labels_o, fontsize=6)
            fig.colorbar(im, ax=ax_main, shrink=0.6)
        else:
            fig, ax = plt.subplots(figsize=(6, 6), constrained_layout=True,
                                     dpi=120)
            im = ax.imshow(mat_o, cmap=cmap, aspect="auto")
            ax.set_xticks(range(n_cols))
            ax.set_xticklabels(col_labels_o, fontsize=6, rotation=45, ha="right")
            ax.set_yticks(range(n_rows))
            ax.set_yticklabels(row_labels_o, fontsize=6)
            fig.colorbar(im, ax=ax, shrink=0.6)
        return fig

    # ------------------------------------------------------------------
    # Distribution / contour / ridgeline / parallel / polar
    # ------------------------------------------------------------------
    @staticmethod
    def density_plot(
        ax,
        data: Sequence[Sequence[float]],
        palette: Union[str, Sequence[str]] = "nature",
        fill: bool = True,
        alpha: float = 0.3,
        bw_method: str = "scott",
    ):
        """Kernel density plot (one or several distributions)."""
        import numpy as np
        colors = _palette(palette)
        if not isinstance(data[0], (list, tuple, np.ndarray)):
            data = [data]
        for i, d in enumerate(data):
            try:
                from scipy.stats import gaussian_kde
                kde = gaussian_kde(np.asarray(d), bw_method=bw_method)
                xs = np.linspace(min(d), max(d), 200)
                density = kde(xs)
                ax.plot(xs, density, color=colors[i % len(colors)],
                        linewidth=1.0)
                if fill:
                    ax.fill_between(xs, density, alpha=alpha,
                                    color=colors[i % len(colors)])
            except Exception as exc:
                logger.debug("density_plot skipped: %s", exc)
                ax.hist(d, bins=30, alpha=alpha, color=colors[i % len(colors)],
                        density=True)
        return ax

    @staticmethod
    def contour_plot(
        ax,
        x,
        y,
        z,
        levels: int = 10,
        palette: str = "viridis",
        filled: bool = True,
        show_colorbar: bool = True,
    ):
        """Contour plot of 2-D ``z`` data over ``(x, y)`` grid."""
        import numpy as np
        try:
            cmap = JournalPalettes.as_cmap(palette)
        except KeyError:
            cmap = JournalPalettes.as_cmap("viridis")
        x_arr = np.asarray(x)
        y_arr = np.asarray(y)
        z_arr = np.asarray(z)
        if filled:
            cs = ax.contourf(x_arr, y_arr, z_arr, levels=levels, cmap=cmap)
        else:
            cs = ax.contour(x_arr, y_arr, z_arr, levels=levels, cmap=cmap)
            ax.clabel(cs, inline=True, fontsize=6)
        if show_colorbar:
            from matplotlib import pyplot as plt
            plt.colorbar(cs, ax=ax, shrink=0.8)
        return ax

    @staticmethod
    def ridgeline_plot(
        ax,
        data: Sequence[Sequence[float]],
        groups: Sequence[str],
        palette: Union[str, Sequence[str]] = "nature",
        overlap: float = 0.5,
        fill: bool = True,
        alpha: float = 0.5,
    ):
        """Ridgeline (joy) plot — stacked KDEs."""
        import numpy as np
        colors = _palette(palette)
        if not isinstance(data[0], (list, tuple, np.ndarray)):
            data = [data]
        max_density = 0.0
        kdes: List = []
        for d in data:
            try:
                from scipy.stats import gaussian_kde
                kde = gaussian_kde(np.asarray(d))
                xs = np.linspace(min(d), max(d), 200)
                density = kde(xs)
                kdes.append((xs, density))
                max_density = max(max_density, density.max())
            except Exception as exc:
                logger.debug("ridgeline KDE skipped: %s", exc)
                kdes.append((None, None))
        for i, (xs, density) in enumerate(kdes):
            if xs is None:
                continue
            y_offset = i * (1.0 - overlap)
            scaled = density / max_density
            ax.plot(xs, scaled + y_offset, color=colors[i % len(colors)],
                    linewidth=0.8)
            if fill:
                ax.fill_between(xs, y_offset, scaled + y_offset,
                                color=colors[i % len(colors)], alpha=alpha)
            ax.text(min(xs), y_offset + 0.5, groups[i], fontsize=6,
                    ha="left", va="center")
        ax.set_yticks([])
        ax.spines["left"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["top"].set_visible(False)
        return ax

    @staticmethod
    def parallel_coordinates(
        ax,
        data,
        class_column: str,
        palette: Union[str, Sequence[str]] = "nature",
    ):
        """Parallel coordinates plot.

        Args:
            ax: Target axes.
            data: Either a 2-D array-like or a pandas DataFrame.
            class_column: Column name (when ``data`` is a DataFrame)
                used to colour lines.
            palette: Palette name.
        """
        import numpy as np
        colors = _palette(palette)
        try:
            import pandas as pd
            df = pd.DataFrame(data) if not isinstance(data, pd.DataFrame) else data
            classes = df[class_column].astype("category").cat.codes.tolist()
            cols = [c for c in df.columns if c != class_column]
            arr = df[cols].to_numpy()
        except Exception:
            arr = np.asarray(data, dtype=float)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            classes = [0] * arr.shape[0]
            cols = list(range(arr.shape[1]))
        n_dims = arr.shape[1]
        x_positions = list(range(n_dims))
        # Normalise each column to 0-1
        norm = np.zeros_like(arr, dtype=float)
        for j in range(n_dims):
            col = arr[:, j]
            cmin, cmax = float(np.min(col)), float(np.max(col))
            span = max(cmax - cmin, 1e-12)
            norm[:, j] = (col - cmin) / span
        for i in range(arr.shape[0]):
            color = colors[classes[i] % len(colors)]
            ax.plot(x_positions, norm[i], color=color, alpha=0.5,
                    linewidth=0.5)
        ax.set_xticks(x_positions)
        ax.set_xticklabels(cols, rotation=45, ha="right")
        ax.set_ylim(-0.05, 1.05)
        ax.set_ylabel("Normalised value")
        return ax

    @staticmethod
    def polar_plot(
        ax,
        theta,
        r,
        palette: Union[str, Sequence[str]] = "nature",
        fill: bool = True,
    ):
        """Polar plot — assumes ``ax`` was created with
        ``projection='polar'``.
        """
        import numpy as np
        colors = _palette(palette)
        theta_arr = np.asarray(theta)
        r_arr = np.asarray(r)
        # Close the loop
        if not np.isclose(theta_arr[0], theta_arr[-1]):
            theta_arr = np.append(theta_arr, theta_arr[0])
            r_arr = np.append(r_arr, r_arr[0])
        ax.plot(theta_arr, r_arr, color=colors[0], linewidth=1.0)
        if fill:
            ax.fill(theta_arr, r_arr, color=colors[0], alpha=0.3)
        return ax
