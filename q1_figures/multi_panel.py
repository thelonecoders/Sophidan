"""Multi-panel figure composition for Q1 publication figures.

Two complementary helpers are exposed:

* :class:`MultiPanelFigure` — a high-level builder for uniform
  ``rows × cols`` multi-panel figures with optional panel labels
  (``a, b, c, d``), shared axes, per-panel colourbars, and adjustable
  inter-panel spacing.
* :class:`GridLayout` — a lower-level helper for *unequal* layouts
  (e.g. a wide top row + 2×2 grid below) built on
  :class:`matplotlib.gridspec.GridSpec`.

Both classes produce figures created with ``constrained_layout=True``
and never call ``tight_layout`` or pass ``bbox_inches='tight'``.

Examples:
    >>> from q1_figures.multi_panel import MultiPanelFigure
    >>> mp = MultiPanelFigure(2, 2, journal='nature')
    >>> ax_a = mp.add_panel(0, 0)
    >>> ax_b = mp.add_panel(0, 1)
    >>> ax_c = mp.add_panel(1, 0)
    >>> ax_d = mp.add_panel(1, 1)
    >>> mp.share_x([ax_a, ax_c])
    >>> fig = mp.finalize()
    >>> mp.save('/tmp/multi.png', format='png')
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import List, Optional, Sequence, Tuple

from .figure_factory import Q1FigureFactory

logger = logging.getLogger(__name__)

_PANEL_LABEL_TEMPLATES = {
    "abcd": list("abcdefghijklmnopqrstuvwxyz"),
    "ABCD": list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    "1234": [str(i) for i in range(1, 100)],
}


class GridLayout:
    """Unequal-row/col grid layout via :class:`matplotlib.gridspec.GridSpec`.

    Args:
        rows: Number of rows.
        cols: Number of columns.
        ratios: Optional list of length ``rows`` (row height ratios)
            or ``rows + cols`` (row heights then column widths).  When
            ``None``, all rows / cols are equal.
        figure: Optional figure to attach the gridspec to.  When
            ``None``, a new figure is created via
            :class:`Q1FigureFactory`.
    """

    def __init__(
        self,
        rows: int,
        cols: int,
        ratios: Optional[Sequence[int]] = None,
        figure=None,
        journal: str = "nature",
        dpi: int = 300,
    ) -> None:
        if rows < 1 or cols < 1:
            raise ValueError(f"rows and cols must be >=1, got {rows}×{cols}")
        self.rows = rows
        self.cols = cols
        self.journal = journal
        self._factory = Q1FigureFactory(journal=journal, dpi=dpi)
        if figure is None:
            figure = self._factory.new_figure()
        self.figure = figure

        # Interpret ratios: if len matches rows -> row heights only;
        # if len matches rows+cols -> row heights + col widths.
        height_ratios: Optional[List[int]] = None
        width_ratios: Optional[List[int]] = None
        if ratios is not None:
            r = list(ratios)
            if len(r) == rows:
                height_ratios = r
            elif len(r) == rows + cols:
                height_ratios = r[:rows]
                width_ratios = r[rows:]
            else:
                raise ValueError(
                    f"ratios length {len(r)} must equal rows ({rows}) "
                    f"or rows+cols ({rows + cols})"
                )

        from matplotlib import gridspec
        self._gs = gridspec.GridSpec(
            rows, cols, figure=figure,
            height_ratios=height_ratios, width_ratios=width_ratios,
        )
        logger.debug("GridLayout %d×%d ratios=%s", rows, cols, ratios)

    def place(self, row: int, col: int, rowspan: int = 1, colspan: int = 1):
        """Place an Axes spanning ``rowspan`` × ``colspan`` at ``(row, col)``."""
        if not (0 <= row < self.rows) or not (0 <= col < self.cols):
            raise ValueError(
                f"(row, col)=({row}, {col}) out of bounds for "
                f"{self.rows}×{self.cols} grid"
            )
        sub = self._gs[row:row + rowspan, col:col + colspan]
        ax = self.figure.add_subplot(sub)
        self._factory.style_axes(ax)
        return ax


class MultiPanelFigure:
    """Uniform ``rows × cols`` multi-panel figure builder.

    Args:
        rows: Number of rows.
        cols: Number of columns.
        figsize: Optional explicit figure size.  When ``None``, the
            size is derived from the journal and column width.
        journal: Journal key (passed to :class:`Q1FigureFactory`).
        dpi: Figure DPI.
        panel_labels: ``'abcd'``, ``'ABCD'``, or ``'1234'``.
    """

    def __init__(
        self,
        rows: int,
        cols: int,
        figsize: Optional[Tuple[float, float]] = None,
        journal: str = "nature",
        dpi: int = 300,
        panel_labels: str = "abcd",
    ) -> None:
        if rows < 1 or cols < 1:
            raise ValueError(f"rows and cols must be >=1, got {rows}×{cols}")
        if panel_labels not in _PANEL_LABEL_TEMPLATES:
            raise ValueError(
                f"panel_labels must be one of {sorted(_PANEL_LABEL_TEMPLATES)}, "
                f"got {panel_labels!r}"
            )
        self.rows = rows
        self.cols = cols
        self.panel_labels_style = panel_labels
        self._factory = Q1FigureFactory(journal=journal, dpi=dpi, figsize=figsize)
        self._figsize = self._factory.figsize
        self.figure = self._factory.new_figure(self._figsize)
        from matplotlib import gridspec
        self._gs = gridspec.GridSpec(rows, cols, figure=self.figure)
        self._axes: List = [None] * (rows * cols)
        self._labels: List[Optional[str]] = [None] * (rows * cols)
        self._titles: List[Optional[str]] = [None] * (rows * cols)
        self._colorbars: List = [None] * (rows * cols)
        logger.debug(
            "MultiPanelFigure %d×%d journal=%s dpi=%d labels=%s",
            rows, cols, journal, dpi, panel_labels,
        )

    # ------------------------------------------------------------------
    # Panel creation
    # ------------------------------------------------------------------
    def _idx(self, row: int, col: int) -> int:
        if not (0 <= row < self.rows) or not (0 <= col < self.cols):
            raise ValueError(
                f"(row, col)=({row}, {col}) out of bounds for "
                f"{self.rows}×{self.cols} grid"
            )
        return row * self.cols + col

    def add_panel(self, row: int, col: int, panel_type: str = "axes"):
        """Add a panel at ``(row, col)`` and return the Axes.

        Args:
            row, col: Grid position.
            panel_type: ``'axes'``, ``'image'``, or ``'heatmap'``.
                ``image`` / ``heatmap`` panels are styled with
                ``ax.set_aspect('equal')`` and no axis labels by
                default.
        """
        idx = self._idx(row, col)
        sub = self._gs[row, col]
        ax = self.figure.add_subplot(sub)
        self._factory.style_axes(ax)
        if panel_type in {"image", "heatmap"}:
            ax.set_aspect("equal")
        self._axes[idx] = ax
        # Auto-assign a panel label unless one is already set.
        if self._labels[idx] is None:
            labels = _PANEL_LABEL_TEMPLATES[self.panel_labels_style]
            self._labels[idx] = labels[idx] if idx < len(labels) else str(idx + 1)
        return ax

    def add_panel_at(self, grid_spec_position):
        """Add a panel at an arbitrary GridSpec position.

        ``grid_spec_position`` is any valid ``GridSpec`` slice, e.g.
        ``self._gs[0, :]`` for a full-width top panel.  Returns the
        new Axes.
        """
        ax = self.figure.add_subplot(grid_spec_position)
        self._factory.style_axes(ax)
        return ax

    # ------------------------------------------------------------------
    # Share / labels / titles
    # ------------------------------------------------------------------
    def share_x(self, axes: Sequence) -> "MultiPanelFigure":
        """Share X axis across the given axes (first becomes master)."""
        if len(axes) < 2:
            return self
        master = axes[0]
        for ax in axes[1:]:
            ax.sharex(master)
        # Hide tick labels on all but the bottom row.
        for ax in axes[:-1]:
            for label in ax.get_xticklabels():
                label.set_visible(False)
        return self

    def share_y(self, axes: Sequence) -> "MultiPanelFigure":
        """Share Y axis across the given axes (first becomes master)."""
        if len(axes) < 2:
            return self
        master = axes[0]
        for ax in axes[1:]:
            ax.sharey(master)
        for ax in axes[1:]:
            for label in ax.get_yticklabels():
                label.set_visible(False)
        return self

    def set_panel_label(self, panel_idx: int, label: str) -> "MultiPanelFigure":
        """Override the auto-assigned label for a panel."""
        if not (0 <= panel_idx < len(self._labels)):
            raise ValueError(f"panel_idx {panel_idx} out of bounds")
        self._labels[panel_idx] = label
        return self

    def set_panel_title(self, panel_idx: int, title: str) -> "MultiPanelFigure":
        """Set the title for a panel."""
        if not (0 <= panel_idx < len(self._titles)):
            raise ValueError(f"panel_idx {panel_idx} out of bounds")
        self._titles[panel_idx] = title
        ax = self._axes[panel_idx]
        if ax is not None:
            ax.set_title(title, fontsize=10, fontweight="bold")
        return self

    def add_colorbar_to(
        self,
        panel_idx: int,
        mappable,
        label: str = "",
        orientation: str = "vertical",
        shrink: float = 0.8,
        aspect: int = 20,
    ):
        """Attach a colourbar to a specific panel.  Returns the colourbar."""
        if not (0 <= panel_idx < len(self._axes)):
            raise ValueError(f"panel_idx {panel_idx} out of bounds")
        ax = self._axes[panel_idx]
        if ax is None:
            raise RuntimeError(f"panel {panel_idx} has no axes; call add_panel first")
        cb = self._factory.add_colorbar(
            self.figure, ax, mappable,
            label=label, orientation=orientation, shrink=shrink, aspect=aspect,
        )
        self._colorbars[panel_idx] = cb
        return cb

    # ------------------------------------------------------------------
    # Spacing / finalise / save
    # ------------------------------------------------------------------
    def adjust_spacing(self, hspace: float = 0.4, wspace: float = 0.4) -> "MultiPanelFigure":
        """Adjust inter-panel spacing.

        Note: with ``constrained_layout=True`` these values are passed
        to the layout engine as hints; matplotlib may still adjust them.
        """
        try:
            self.figure.set_constrained_layout_pads(
                hspace=hspace, wspace=wspace,
            )
        except Exception as exc:
            logger.debug("constrained_layout pads skipped: %s", exc)
        # Also set the gridspec spacing as a fallback hint.
        try:
            self._gs.update(hspace=hspace, wspace=wspace)
        except Exception as exc:
            logger.debug("gridspec update skipped: %s", exc)
        return self

    def finalize(self):
        """Apply panel labels + finalise layout.  Returns the figure."""
        for idx, ax in enumerate(self._axes):
            if ax is None:
                continue
            label = self._labels[idx]
            if label:
                self._factory.annotate_panel(ax, label=label)
            title = self._titles[idx]
            if title and not ax.get_title():
                ax.set_title(title, fontsize=10, fontweight="bold")
        return self._factory.finalize(self.figure)

    def save(self, path: str, format: str = "png", dpi: int = 300) -> str:
        """Save the multi-panel figure.  Returns the saved path."""
        return self._factory.save(self.figure, path, format=format, dpi=dpi)
