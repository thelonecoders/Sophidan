"""Main figure factory for Q1 publication-grade figures.

The :class:`Q1FigureFactory` is the primary entry point for producing
publication-ready matplotlib figures.  It handles:

* Journal-specific typography (via :class:`Q1Typography`).
* Column-width sizing (single 89 mm, 1.5-column 120 mm, double 183 mm).
* High-DPI raster + vector (SVG / PDF) export.
* Axes styling, legends, statistical annotations, error bars, panel
  labels, colourbars.
* A :meth:`finalize` hook that applies all journal-specific touches.

All figures are created with ``constrained_layout=True`` — the
factory never calls ``tight_layout`` and never passes
``bbox_inches='tight'`` to ``savefig``.

Examples:
    >>> from q1_figures.figure_factory import Q1FigureFactory
    >>> import numpy as np
    >>> f = Q1FigureFactory(journal='nature')
    >>> fig = f.new_figure()
    >>> ax = f.new_axes(fig)
    >>> x = np.linspace(0, 1, 50)
    >>> ax.plot(x, x**2)
    >>> f.set_axis_labels(ax, 'x', 'y')
    >>> f.style_axes(ax)
    >>> f.save(fig, '/tmp/example.png', format='png')
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import os
from typing import Any, List, Optional, Tuple, Union

from .palettes import JournalPalettes
from .typography import Q1Typography

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column widths (in mm) — Nature / Science / Cell standard.
# ---------------------------------------------------------------------------
_MM_TO_INCH = 1.0 / 25.4
_COLUMN_WIDTHS_MM = {
    "single": 89.0,
    "1.5": 120.0,
    "double": 183.0,
    "full": 183.0,
}
_ASPECT_RATIOS = {
    "square": 1.0,
    "wide": 1.6,
    "tall": 0.625,  # 1 / 1.6
}


class Q1FigureFactory:
    """Factory for publication-grade matplotlib figures.

    Args:
        journal: Journal key — ``'nature'``, ``'science'``, ``'cell'``,
            ``'nejm'``, ``'lancet'``, ``'jama'``.
        figsize: Optional explicit ``(width, height)`` in inches.  When
            ``None``, the figure size is computed from the column width
            and aspect ratio via :meth:`set_size`.
        dpi: Default DPI for raster outputs (300 / 600 / 1200 supported).
    """

    def __init__(
        self,
        journal: str = "nature",
        figsize: Optional[Tuple[float, float]] = None,
        dpi: int = 300,
    ) -> None:
        self.journal: str = journal.lower().strip()
        self.dpi: int = int(dpi)
        self._figsize: Tuple[float, float] = figsize or (3.5, 2.5)
        self._columns: str = "single"
        self._aspect: str = "square"
        # Apply journal typography up-front.
        try:
            Q1Typography.configure_matplotlib(self.journal)
        except Exception as exc:  # pragma: no cover - env dependent
            logger.warning("Could not configure typography for %r: %s", self.journal, exc)
        logger.debug(
            "Q1FigureFactory initialised: journal=%s dpi=%d figsize=%s",
            self.journal, self.dpi, self._figsize,
        )

    # ------------------------------------------------------------------
    # Chainable setters
    # ------------------------------------------------------------------
    def set_journal(self, name: str) -> "Q1FigureFactory":
        """Set the journal (chainable).  Re-applies typography."""
        self.journal = name.lower().strip()
        try:
            Q1Typography.configure_matplotlib(self.journal)
        except Exception as exc:  # pragma: no cover
            logger.warning("configure_matplotlib failed: %s", exc)
        return self

    def set_size(
        self,
        columns: str = "single",
        aspect: str = "square",
    ) -> "Q1FigureFactory":
        """Set the figure size based on column width and aspect ratio.

        Args:
            columns: ``'single'`` (89 mm), ``'1.5'`` (120 mm),
                ``'double'`` (183 mm), or ``'full'`` (alias for double).
            aspect: ``'square'`` (1.0), ``'wide'`` (1.6), ``'tall'``
                (0.625 — inverse of wide).

        Returns:
            ``self`` (chainable).
        """
        if columns not in _COLUMN_WIDTHS_MM:
            raise ValueError(
                f"columns must be one of {sorted(_COLUMN_WIDTHS_MM)}, got {columns!r}"
            )
        if aspect not in _ASPECT_RATIOS:
            raise ValueError(
                f"aspect must be one of {sorted(_ASPECT_RATIOS)}, got {aspect!r}"
            )
        self._columns = columns
        self._aspect = aspect
        width_mm = _COLUMN_WIDTHS_MM[columns]
        width_in = width_mm * _MM_TO_INCH
        height_in = width_in / _ASPECT_RATIOS[aspect]
        self._figsize = (width_in, height_in)
        logger.debug(
            "Figure size set: %s column × %s aspect → %.2f × %.2f in",
            columns, aspect, width_in, height_in,
        )
        return self

    def set_dpi(self, dpi: int) -> "Q1FigureFactory":
        """Set the default DPI (chainable). 300/600/1200 supported."""
        if dpi not in {300, 600, 1200}:
            logger.warning("DPI %d not in {300,600,1200}; accepting anyway.", dpi)
        self.dpi = int(dpi)
        return self

    # ------------------------------------------------------------------
    # Figure / axes creation
    # ------------------------------------------------------------------
    @property
    def figsize(self) -> Tuple[float, float]:
        return self._figsize

    @property
    def palette(self) -> List[str]:
        """Return the current journal's palette."""
        try:
            return JournalPalettes.get(self.journal)
        except KeyError:
            return JournalPalettes.NATURE

    def new_figure(self, figsize: Optional[Tuple[float, float]] = None):
        """Return a new constrained-layout matplotlib Figure."""
        import matplotlib.pyplot as plt
        size = figsize or self._figsize
        fig = plt.figure(figsize=size, constrained_layout=True, dpi=self.dpi)
        logger.debug("Created new figure: %s dpi=%d", size, self.dpi)
        return fig

    def new_axes(self, fig=None, position: Optional[Any] = None):
        """Return a pre-styled matplotlib Axes.

        Args:
            fig: Target figure.  When ``None``, a new figure is
                created via :meth:`new_figure`.
            position: Optional ``[left, bottom, width, height]`` in
                figure coordinates.  When ``None``, a single full-figure
                subplot is added.
        """
        if fig is None:
            fig = self.new_figure()
        if position is not None:
            ax = fig.add_axes(position)
        else:
            ax = fig.add_subplot(1, 1, 1)
        self.style_axes(ax)
        return ax

    def new_figure_and_axes(
        self,
        figsize: Optional[Tuple[float, float]] = None,
        position: Optional[Any] = None,
    ):
        """Convenience helper — create a new figure AND a styled axes.

        Equivalent to::

            fig = self.new_figure(figsize)
            ax = self.new_axes(fig, position)

        Returns:
            ``(fig, ax)`` tuple.
        """
        fig = self.new_figure(figsize=figsize)
        ax = self.new_axes(fig, position=position)
        return fig, ax

    # ------------------------------------------------------------------
    # Axes styling
    # ------------------------------------------------------------------
    def style_axes(
        self,
        ax,
        spine_top: bool = False,
        spine_right: bool = False,
        grid: bool = False,
        grid_axis: str = "y",
        grid_color: str = "lightgray",
        grid_linewidth: float = 0.3,
    ) -> "Q1FigureFactory":
        """Style an Axes object (spines, grid, ticks).

        Returns ``self`` for chaining.
        """
        ax.spines["top"].set_visible(spine_top)
        ax.spines["right"].set_visible(spine_right)
        ax.spines["left"].set_linewidth(0.5)
        ax.spines["bottom"].set_linewidth(0.5)
        if grid:
            ax.grid(
                True,
                axis=grid_axis,
                color=grid_color,
                linewidth=grid_linewidth,
                alpha=0.7,
                linestyle="-",
            )
            ax.set_axisbelow(True)
        else:
            ax.grid(False)
        ax.tick_params(
            axis="both",
            which="both",
            direction="out",
            length=2.0,
            width=0.5,
            colors="black",
        )
        return self

    def set_axis_labels(
        self,
        ax,
        xlabel: str = "",
        ylabel: str = "",
        fontsize: int = 9,
    ) -> "Q1FigureFactory":
        """Set X / Y axis labels."""
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=fontsize)
        if ylabel:
            ax.set_ylabel(ylabel, fontsize=fontsize)
        return self

    def set_title(
        self,
        ax,
        title: str,
        fontsize: int = 10,
        fontweight: str = "bold",
        pad: int = 10,
    ) -> "Q1FigureFactory":
        """Set the axes title."""
        ax.set_title(title, fontsize=fontsize, fontweight=fontweight, pad=pad)
        return self

    def set_tick_labels_fontsize(self, ax, fontsize: int = 7) -> "Q1FigureFactory":
        """Set the tick label font size on both axes."""
        ax.tick_params(axis="both", which="major", labelsize=fontsize)
        ax.tick_params(axis="both", which="minor", labelsize=fontsize)
        return self

    # ------------------------------------------------------------------
    # Legend, significance, error bars
    # ------------------------------------------------------------------
    def add_legend(
        self,
        ax,
        location: str = "best",
        frame: bool = False,
        fontsize: int = 7,
    ) -> "Q1FigureFactory":
        """Add a legend to the axes.

        Args:
            ax: Target axes.
            location: ``'best'``, ``'outside_right'``, or
                ``'outside_bottom'``.  The two ``outside_*`` modes use
                ``bbox_to_anchor`` so the legend sits outside the axes
                area (works with constrained_layout).
            frame: When ``True``, draw a legend frame.
            fontsize: Legend font size.
        """
        kwargs: dict = {"frameon": frame, "fontsize": fontsize}
        if location == "outside_right":
            kwargs["loc"] = "center left"
            kwargs["bbox_to_anchor"] = (1.02, 0.5)
            kwargs["borderaxespad"] = 0.0
        elif location == "outside_bottom":
            kwargs["loc"] = "upper center"
            kwargs["bbox_to_anchor"] = (0.5, -0.18)
            kwargs["ncol"] = max(1, len(ax.get_legend_handles_labels()[1]))
            kwargs["borderaxespad"] = 0.0
        else:
            kwargs["loc"] = location
        ax.legend(**kwargs)
        return self

    def add_significance_bar(
        self,
        ax,
        x1: float,
        x2: float,
        y: float,
        height: float = 0.05,
        text: str = "***",
        fontsize: int = 6,
    ) -> "Q1FigureFactory":
        """Draw a statistical significance bar with asterisks.

        Draws a horizontal bracket from ``x1`` to ``x2`` at ``y``, with
        small vertical tick-downs at each end, and the supplied ``text``
        (typically ``'*'``, ``'**'``, ``'***'`` or ``'ns'``) centred
        above.

        Args:
            ax: Target axes.
            x1, x2: X coordinates of the bar endpoints.
            y: Y coordinate of the horizontal bar.
            height: Vertical size of the tick-downs.
            text: Significance text (asterisks / ``'ns'``).
            fontsize: Annotation font size.
        """
        ax.plot([x1, x1, x2, x2], [y - height, y, y, y - height],
                lw=0.5, color="black", clip_on=False)
        ax.text(
            (x1 + x2) / 2.0, y + 0.005, text,
            ha="center", va="bottom", fontsize=fontsize, clip_on=False,
        )
        return self

    def add_significance_line(
        self,
        ax,
        x1: float,
        x2: float,
        y: float,
        color: str = "black",
        linestyle: str = "-",
        linewidth: float = 0.5,
    ) -> "Q1FigureFactory":
        """Draw a thin significance line between two x positions."""
        ax.plot([x1, x2], [y, y], color=color, linestyle=linestyle,
                linewidth=linewidth, clip_on=False)
        return self

    def add_error_bars(
        self,
        ax,
        x,
        y,
        yerr=None,
        xerr=None,
        color: str = "black",
        cap_size: float = 2,
        cap_thick: float = 0.5,
        linewidth: float = 0.5,
        **kwargs,
    ):
        """Add error bars to the axes and return the ErrorbarContainer."""
        container = ax.errorbar(
            x, y, yerr=yerr, xerr=xerr,
            color=color, capsize=cap_size, capthick=cap_thick,
            lw=linewidth, fmt="none", **kwargs,
        )
        return container

    # ------------------------------------------------------------------
    # Colourbar, panel labels
    # ------------------------------------------------------------------
    def add_colorbar(
        self,
        fig,
        ax,
        mappable,
        label: str = "",
        orientation: str = "vertical",
        shrink: float = 0.8,
        aspect: int = 20,
    ):
        """Attach a colourbar to the figure for the given mappable.

        Returns the colourbar object.
        """
        cb = fig.colorbar(
            mappable, ax=ax,
            orientation=orientation, shrink=shrink, aspect=aspect,
        )
        if label:
            cb.set_label(label, fontsize=8)
        cb.ax.tick_params(labelsize=7)
        return cb

    def annotate_panel(
        self,
        ax,
        label: str = "a",
        xy: Tuple[float, float] = (0.0, 1.05),
        fontsize: int = 12,
        fontweight: str = "bold",
    ) -> "Q1FigureFactory":
        """Annotate a panel with a bold lowercase letter (a, b, c, ...)."""
        ax.annotate(
            label,
            xy=xy, xycoords="axes fraction",
            fontsize=fontsize, fontweight=fontweight,
            ha="left", va="bottom",
        )
        return self

    # ------------------------------------------------------------------
    # Save / finalize
    # ------------------------------------------------------------------
    def save(
        self,
        fig,
        path: str,
        format: Optional[str] = None,
        transparent: bool = False,
        dpi: Optional[int] = None,
    ) -> str:
        """Save the figure to disk.

        Vector formats (``svg``, ``pdf``) are saved as vector for
        journal submission.  Raster formats use the factory's DPI.

        Args:
            fig: The matplotlib Figure to save.
            path: Output file path.  The directory is created if
                missing.  When ``format`` is ``None``, the format is
                inferred from the path extension (``.png``, ``.svg``,
                ``.pdf``, ``.tiff``); falls back to ``'png'`` for
                unknown / missing extensions.
            format: ``'png'``, ``'svg'``, ``'pdf'``, or ``'tiff'``.
                When ``None`` (default), inferred from ``path``.
            transparent: When ``True``, use a transparent background.
            dpi: Override DPI for raster output (defaults to
                ``self.dpi``).

        Returns:
            The saved file path.
        """
        if format is None:
            ext = os.path.splitext(path)[1].lstrip(".").lower()
            format = ext if ext in {"png", "svg", "pdf", "tiff"} else "png"
        if format not in {"png", "svg", "pdf", "tiff"}:
            raise ValueError(
                f"format must be 'png'|'svg'|'pdf'|'tiff', got {format!r}"
            )
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        save_kwargs = {
            "format": format,
            "transparent": transparent,
        }
        if format in {"png", "tiff"}:
            save_kwargs["dpi"] = dpi or self.dpi
        # CRITICAL: never use bbox_inches='tight' with constrained_layout.
        fig.savefig(path, **save_kwargs)
        logger.info("Saved figure -> %s (%s)", path, format)
        return path

    def finalize(self, fig):
        """Apply all journal-specific final touches and return the figure.

        Currently this is a no-op marker that ensures typography is
        applied and the figure's constrained_layout is honoured.  Future
        journal-specific tweaks (e.g. NEJM-required spine colours) hook
        in here.
        """
        try:
            Q1Typography.configure_matplotlib(self.journal)
        except Exception as exc:  # pragma: no cover
            logger.warning("typography re-apply failed: %s", exc)
        # Ensure constrained_layout is engaged (no-op if already True).
        try:
            fig.set_constrained_layout(True)
        except Exception:
            pass
        return fig
