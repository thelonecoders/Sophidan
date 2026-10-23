"""Journal-grade colour palettes for Q1 publication figures.

This module exposes :class:`JournalPalettes`, a container of curated
colour palettes inspired by (and harmonised with) the visual identities
of *Nature*, *Science*, *Cell*, *NEJM*, *Lancet*, *JAMA*, as well as
generally useful scientific, colour-blind-safe, diverging and sequential
palettes.

Palettes are intentionally short (10 entries for categorical, 11 for
diverging, 10 for sequential).  For continuous applications, use
:meth:`JournalPalettes.as_cmap` which builds a smooth
:class:`matplotlib.colors.LinearSegmentedColormap` from a named
palette.

Examples:
    >>> from q1_figures.palettes import JournalPalettes
    >>> JournalPalettes.NATURE[0]
    '#E64B35'
    >>> cmap = JournalPalettes.as_cmap('viridis')
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class JournalPalettes:
    """Container of curated journal-grade colour palettes.

    All palettes are lists of hex colour strings.  Categorical palettes
    contain 10 entries; diverging 11; sequential 10.  Indexing past the
    end of a categorical palette is the caller's responsibility (cycle
    with ``idx % len``).
    """

    # --- Top-tier journal palettes (categorical, 10 entries) ------------
    NATURE: List[str] = [
        "#E64B35", "#4DBBD5", "#00A087", "#3C5488", "#F39B7F",
        "#8491B4", "#91D1C2", "#DC0000", "#7E6148", "#B09C85",
    ]
    SCIENCE: List[str] = [
        "#0B3C5D", "#062F4F", "#1C6E8C", "#328CC1", "#D9B310",
        "#A8C5E6", "#6D757D", "#B0D5C5", "#5C7457", "#1D3461",
    ]
    CELL: List[str] = [
        "#2E86AB", "#A23B72", "#F18F01", "#C73E1D", "#3B1F2B",
        "#5C2751", "#A1C181", "#6A994E", "#F2E8CF", "#BC4749",
    ]
    NEJM: List[str] = [
        "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
        "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
    ]
    LANCET: List[str] = [
        "#00468B", "#ED0000", "#42B540", "#0099B4", "#925E9F",
        "#FDAF91", "#AD002A", "#ADB6B6", "#1B1919", "#524787",
    ]
    JAMA: List[str] = [
        "#374E55", "#DF8F44", "#00A1D5", "#B24745", "#79AF97",
        "#6A6599", "#80796B", "#E1B600", "#C7E2F1", "#5C5072",
    ]
    SCIENTIFIC: List[str] = [
        "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
        "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
    ]
    COLORBLIND_SAFE: List[str] = [
        "#0072B2", "#E69F00", "#009E73", "#F0E442", "#56B4E9",
        "#D55E00", "#CC79A7", "#000000", "#999999", "#FFFFFF",
    ]

    # --- Continuous palettes (sequential / diverging) ------------------
    DIVERGING_RG: List[str] = [
        "#053061", "#2166AC", "#4393C3", "#92C5DE", "#D1E5F0",
        "#F7F7F7", "#FDDBC7", "#F4A582", "#D6604D", "#B2182B",
        "#67001F",
    ]
    SEQUENTIAL_VIRIDIS: List[str] = [
        "#440154", "#482777", "#3F4A8A", "#31678E", "#26838F",
        "#1F9D8A", "#35B779", "#6ECE58", "#B5DE2B", "#FDE725",
    ]

    # Alias mapping for lookup / journal normalisation.
    _ALIASES: Dict[str, List[str]] = {
        "nature": NATURE,
        "science": SCIENCE,
        "cell": CELL,
        "nejm": NEJM,
        "lancet": LANCET,
        "jama": JAMA,
        "scientific": SCIENTIFIC,
        "colorblind": COLORBLIND_SAFE,
        "colorblind_safe": COLORBLIND_SAFE,
        "diverging": DIVERGING_RG,
        "diverging_rg": DIVERGING_RG,
        "viridis": SEQUENTIAL_VIRIDIS,
        "sequential": SEQUENTIAL_VIRIDIS,
        "sequential_viridis": SEQUENTIAL_VIRIDIS,
    }

    @classmethod
    def get(cls, name: str) -> List[str]:
        """Return a palette by name (case-insensitive).

        Args:
            name: Palette key — one of ``'nature'``, ``'science'``,
                ``'cell'``, ``'nejm'``, ``'lancet'``, ``'jama'``,
                ``'scientific'``, ``'colorblind_safe'``,
                ``'diverging_rg'``, ``'sequential_viridis'``, or
                aliases ``'colorblind'``, ``'diverging'``,
                ``'viridis'``, ``'sequential'``.

        Returns:
            A list of hex colour strings.  The original list is
            returned directly; callers should not mutate it.

        Raises:
            KeyError: If the palette name is unknown.
        """
        key = name.lower().strip()
        if key in cls._ALIASES:
            return cls._ALIASES[key]
        raise KeyError(
            f"Unknown palette {name!r}. "
            f"Known: {sorted(cls._ALIASES.keys())}"
        )

    @classmethod
    def as_cmap(cls, name: str):
        """Return a ``LinearSegmentedColormap`` for continuous use.

        Args:
            name: Palette name (see :meth:`get`).

        Returns:
            A :class:`matplotlib.colors.LinearSegmentedColormap`
            interpolating across the palette's hex colours.

        Raises:
            ImportError: If matplotlib is not installed.
            KeyError: If the palette name is unknown.
        """
        from matplotlib.colors import LinearSegmentedColormap

        colors = cls.get(name)
        cmap_name = f"q1_{name.lower()}"
        cmap = LinearSegmentedColormap.from_list(cmap_name, colors, N=256)
        logger.debug("Built cmap %s from %d colours", cmap_name, len(colors))
        return cmap

    @classmethod
    def all_names(cls) -> List[str]:
        """Return a sorted list of all known palette names."""
        return sorted(cls._ALIASES.keys())

    @classmethod
    def is_sequential(cls, name: str) -> bool:
        """Return ``True`` if the palette is sequential / diverging."""
        return name.lower().strip() in {
            "diverging",
            "diverging_rg",
            "viridis",
            "sequential",
            "sequential_viridis",
        }
