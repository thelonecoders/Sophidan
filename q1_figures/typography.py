"""Publication typography for Q1 journals.

The :class:`Q1Typography` class centralises font-family selection and
matplotlib ``rcParams`` configuration for each supported journal.
Each journal has a preferred font family (mostly sans-serif Arial /
Helvetica; *Lancet* prefers Times New Roman serif) plus a sensible
fallback chain that always terminates at ``'DejaVu Sans'`` / ``'DejaVu
Serif'`` to guarantee rendering even on stock Linux.

CJK support is preserved by always including ``'Noto Sans SC'`` in the
sans-serif fallback list.

Examples:
    >>> from q1_figures.typography import Q1Typography
    >>> Q1Typography.configure_matplotlib('nature')
    >>> Q1Typography.configure_matplotlib('lancet')
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class Q1Typography:
    """Publication typography settings and matplotlib rcParams applier.

    The class exposes the canonical font family per journal as a class
    attribute (``NATURE_FAMILY``, ``SCIENCE_FAMILY`` etc.) and provides
    two class-method helpers:

    * :meth:`apply` — set every rcParam individually.
    * :meth:`configure_matplotlib` — one-shot journal configuration
      that picks the font family, sizes, line widths, and tick settings
      appropriate for the chosen journal.
    """

    # --- Font families (per journal) --------------------------------
    NATURE_FAMILY: str = "Arial"
    SCIENCE_FAMILY: str = "Helvetica"
    CELL_FAMILY: str = "Arial"
    LANCET_FAMILY: str = "Times New Roman"
    JAMA_FAMILY: str = "Helvetica"

    # Default fallback chains — always include CJK + DejaVu so that the
    # figure renders on stock Linux even when Arial / Helvetica are
    # missing.
    SANS_FALLBACK: List[str] = ["Arial", "Helvetica", "Noto Sans SC", "DejaVu Sans"]
    SERIF_FALLBACK: List[str] = ["Times New Roman", "Noto Serif SC", "DejaVu Serif"]
    MONO_FALLBACK: List[str] = ["Courier New", "DejaVu Sans Mono"]

    # Sensible default sizes (points).  Nature/Cell use 7–8 pt body text
    # for figures; Lancet/NEJM prefer slightly larger.
    _JOURNAL_DEFAULTS: Dict[str, Dict[str, object]] = {
        "nature": {
            "font_family": "Arial",
            "font_size": 8,
            "axes_label_size": 9,
            "title_size": 10,
            "tick_label_size": 7,
            "legend_size": 7,
            "line_width": 0.5,
            "axes_line_width": 0.5,
            "tick_width": 0.5,
            "tick_length": 2.0,
        },
        "science": {
            "font_family": "Helvetica",
            "font_size": 8,
            "axes_label_size": 9,
            "title_size": 10,
            "tick_label_size": 7,
            "legend_size": 7,
            "line_width": 0.5,
            "axes_line_width": 0.5,
            "tick_width": 0.5,
            "tick_length": 2.0,
        },
        "cell": {
            "font_family": "Arial",
            "font_size": 8,
            "axes_label_size": 9,
            "title_size": 10,
            "tick_label_size": 7,
            "legend_size": 7,
            "line_width": 0.5,
            "axes_line_width": 0.5,
            "tick_width": 0.5,
            "tick_length": 2.0,
        },
        "nejm": {
            "font_family": "Helvetica",
            "font_size": 9,
            "axes_label_size": 10,
            "title_size": 11,
            "tick_label_size": 8,
            "legend_size": 8,
            "line_width": 0.6,
            "axes_line_width": 0.6,
            "tick_width": 0.6,
            "tick_length": 2.5,
        },
        "lancet": {
            "font_family": "Times New Roman",
            "font_size": 9,
            "axes_label_size": 10,
            "title_size": 11,
            "tick_label_size": 8,
            "legend_size": 8,
            "line_width": 0.6,
            "axes_line_width": 0.6,
            "tick_width": 0.6,
            "tick_length": 2.5,
        },
        "jama": {
            "font_family": "Helvetica",
            "font_size": 9,
            "axes_label_size": 10,
            "title_size": 11,
            "tick_label_size": 8,
            "legend_size": 8,
            "line_width": 0.6,
            "axes_line_width": 0.6,
            "tick_width": 0.6,
            "tick_length": 2.5,
        },
    }

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    @classmethod
    def apply(
        cls,
        font_family: str,
        font_size: int = 8,
        axes_label_size: int = 9,
        title_size: int = 10,
        tick_label_size: int = 7,
        legend_size: int = 7,
        line_width: float = 0.5,
        axes_line_width: float = 0.5,
        tick_width: float = 0.5,
        tick_length: float = 2.0,
    ) -> None:
        """Apply individual rcParams to matplotlib.

        Args:
            font_family: Preferred font family (e.g. ``'Arial'``).
            font_size: Base font size (points).
            axes_label_size: X / Y axis label font size.
            title_size: Title font size.
            tick_label_size: Tick label font size.
            legend_size: Legend font size.
            line_width: Default line width.
            axes_line_width: Axes spine line width.
            tick_width: Tick mark line width.
            tick_length: Tick mark length (points).

        Raises:
            ImportError: If matplotlib is unavailable.
        """
        import matplotlib as mpl
        from matplotlib import font_manager

        # Detect serif vs sans-serif based on the requested family.
        serif_families = {"Times New Roman", "Georgia", "Garamond", "Cambria"}
        is_serif = font_family in serif_families

        fallback = list(cls.SERIF_FALLBACK) if is_serif else list(cls.SANS_FALLBACK)
        if font_family not in fallback:
            fallback = [font_family] + fallback

        # Register any system fonts that match the requested family so
        # matplotlib's font cache picks them up; ignore failure (e.g.
        # missing font files).
        try:
            for f in font_manager.fontManager.ttflist:
                # Touch the list to ensure fontManager is initialised.
                _ = f.name
        except Exception as exc:  # pragma: no cover - environment specific
            logger.debug("font_manager scan skipped: %s", exc)

        mpl.rcParams.update({
            "font.family": "serif" if is_serif else "sans-serif",
            "font.sans-serif": cls.SANS_FALLBACK if not is_serif else [font_family] + cls.SANS_FALLBACK,
            "font.serif": cls.SERIF_FALLBACK if is_serif else [font_family] + cls.SERIF_FALLBACK,
            "font.size": font_size,
            "axes.labelsize": axes_label_size,
            "axes.titlesize": title_size,
            "xtick.labelsize": tick_label_size,
            "ytick.labelsize": tick_label_size,
            "legend.fontsize": legend_size,
            "lines.linewidth": line_width,
            "axes.linewidth": axes_line_width,
            "xtick.major.width": tick_width,
            "ytick.major.width": tick_width,
            "xtick.minor.width": tick_width,
            "ytick.minor.width": tick_width,
            "xtick.major.size": tick_length,
            "ytick.major.size": tick_length,
            "xtick.minor.size": tick_length * 0.6,
            "ytick.minor.size": tick_length * 0.6,
            "axes.unicode_minus": False,
            "pdf.fonttype": 42,   # TrueType (editable) — required by most journals
            "ps.fonttype": 42,
            "svg.fonttype": "none",  # keep text as text in SVG (not paths)
        })
        logger.debug(
            "Typography applied: family=%s serif=%s size=%d label=%d title=%d tick=%d legend=%d "
            "lw=%.2f axes_lw=%.2f tick_w=%.2f tick_l=%.2f",
            font_family, is_serif, font_size, axes_label_size, title_size,
            tick_label_size, legend_size, line_width, axes_line_width,
            tick_width, tick_length,
        )

    @classmethod
    def configure_matplotlib(cls, journal: str = "nature") -> None:
        """One-shot journal-specific matplotlib configuration.

        Picks the font family, sizes, line widths, and tick settings
        appropriate for the chosen journal, then applies them via
        :meth:`apply`.

        Args:
            journal: One of ``'nature'``, ``'science'``, ``'cell'``,
                ``'nejm'``, ``'lancet'``, ``'jama'`` (case-insensitive).

        Raises:
            ImportError: If matplotlib is unavailable.
            KeyError: If the journal name is unknown.
        """
        key = journal.lower().strip()
        if key not in cls._JOURNAL_DEFAULTS:
            raise KeyError(
                f"Unknown journal {journal!r}. Known: {sorted(cls._JOURNAL_DEFAULTS)}"
            )
        params = cls._JOURNAL_DEFAULTS[key]
        cls.apply(**params)  # type: ignore[arg-type]
        logger.info("Configured matplotlib for journal %r", key)

    @classmethod
    def journal_family(cls, journal: str) -> str:
        """Return the canonical font family for a journal name."""
        key = journal.lower().strip()
        if key not in cls._JOURNAL_DEFAULTS:
            raise KeyError(f"Unknown journal {journal!r}")
        return str(cls._JOURNAL_DEFAULTS[key]["font_family"])

    @classmethod
    def supported_journals(cls) -> List[str]:
        """Return a sorted list of supported journal keys."""
        return sorted(cls._JOURNAL_DEFAULTS.keys())
