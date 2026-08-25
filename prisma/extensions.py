"""PRISMA 2020 extensions — IPD, NMA, ScR, Harms, Abstract, Diagnostic.

This module wraps :class:`prisma.flow_diagram.PRISMAFlowGenerator` to provide
builders for each of the six official PRISMA 2020 extensions documented by
Page et al. (BMJ 2021;372:n71) and the companion PRISMA extension papers.

Each builder returns a configured :class:`PRISMAFlowGenerator` instance whose
``render_matplotlib`` / ``render_pdf`` / ``render_png`` / ``render_svg`` /
``render_html`` methods then produce the publication-grade diagram.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

from .flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts

if TYPE_CHECKING:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)


class PRISMAExtension(Enum):
    """Enumeration of all PRISMA 2020 extension templates.

    Members:
        STANDARD:   Original PRISMA 2020 flow diagram.
        IPD:        Individual participant data extension (Stewart LA et al., BMJ 2012).
        NMA:        Network meta-analysis extension (Hutton B et al., Ann Intern Med 2015).
        ScR:        Scoping review extension (Tricco AC et al., Ann Intern Med 2018).
        HARMS:      Adverse events extension (Zorzela L et al., PLoS One 2016).
        ABSTRACT:   Conference abstract extension (Beller EM et al., J Clin Epidemiol 2013).
        DIAGNOSTIC: Diagnostic test accuracy extension (McInnes MDF et al., BMJ 2018).
    """

    STANDARD = "standard"
    IPD = "ipd"
    NMA = "nma"
    ScR = "scr"
    HARMS = "harms"
    ABSTRACT = "abstract"
    DIAGNOSTIC = "diagnostic"

    @property
    def code(self) -> str:
        """The short code used as ``extension=`` kwarg in :class:`PRISMAFlowGenerator`."""
        return self.value


class PRISMAExtensionGenerator:
    """Factory that produces PRISMA flow diagrams for each official extension.

    Every method returns a fully-configured :class:`PRISMAFlowGenerator`
    instance; callers can then render via ``render_matplotlib()``,
    ``render_pdf()``, ``render_png()``, ``render_svg()``, or ``render_html()``.

    Example:
        >>> from prisma.extensions import PRISMAExtensionGenerator
        >>> from prisma.flow_diagram import PRISMAStageCounts
        >>> counts = PRISMAStageCounts(n_records_databases=500, n_records_screened=400)
        >>> g = PRISMAExtensionGenerator().ipd_flow(counts, title='My IPD Review')
        >>> g.render_png('ipd.png', dpi=150)
    """

    @staticmethod
    def ipd_flow(counts: PRISMAStageCounts,
                 title: str = "") -> PRISMAFlowGenerator:
        """Build an IPD (individual participant data) flow diagram.

        The IPD extension (Stewart LA et al., *PRISMA-IPD extensions*,
        BMJ 2012;345:e5705) adds stages for requesting and obtaining
        individual participant data from study authors before the
        meta-analysis step.

        Args:
            counts: Stage counts.
            title: Review title.

        Returns:
            Configured :class:`PRISMAFlowGenerator` with ``extension='ipd'``.
        """
        gen = PRISMAFlowGenerator(counts, title=title, extension="ipd")
        logger.debug("IPD flow generator created: title=%r", title)
        return gen

    @staticmethod
    def nma_flow(counts: PRISMAStageCounts,
                 title: str = "") -> PRISMAFlowGenerator:
        """Build a network meta-analysis (NMA) flow diagram.

        The NMA extension (Hutton B et al., *The PRISMA extension statement
        for reporting of systematic reviews incorporating network
        meta-analyses*, Ann Intern Med 2015;162:777-84) adds a network
        geometry note describing the comparison structure.

        Args:
            counts: Stage counts.
            title: Review title.

        Returns:
            Configured :class:`PRISMAFlowGenerator` with ``extension='nma'``.
        """
        gen = PRISMAFlowGenerator(counts, title=title, extension="nma")
        logger.debug("NMA flow generator created: title=%r", title)
        return gen

    @staticmethod
    def scr_flow(counts: PRISMAStageCounts,
                 title: str = "") -> PRISMAFlowGenerator:
        """Build a scoping review (ScR) flow diagram.

        The ScR extension (Tricco AC et al., *PRISMA Extension for Scoping
        Reviews*, Ann Intern Med 2018;169:467-73) omits risk-of-bias
        assessment and emphasises study-mapping over synthesis.

        Args:
            counts: Stage counts.
            title: Review title.

        Returns:
            Configured :class:`PRISMAFlowGenerator` with ``extension='scr'``.
        """
        gen = PRISMAFlowGenerator(counts, title=title, extension="scr")
        logger.debug("ScR flow generator created: title=%r", title)
        return gen

    @staticmethod
    def harms_flow(counts: PRISMAStageCounts,
                   title: str = "") -> PRISMAFlowGenerator:
        """Build an adverse events (Harms) flow diagram.

        The Harms extension (Zorzela L et al., *PRISMA Harms extension*,
        PLoS One 2016;11(6):e0157635) adds a note that adverse events
        were extracted and reported separately by severity / seriousness.

        Args:
            counts: Stage counts.
            title: Review title.

        Returns:
            Configured :class:`PRISMAFlowGenerator` with ``extension='harms'``.
        """
        gen = PRISMAFlowGenerator(counts, title=title, extension="harms")
        logger.debug("Harms flow generator created: title=%r", title)
        return gen

    @staticmethod
    def abstract_flow(counts: PRISMAStageCounts,
                      title: str = "") -> PRISMAFlowGenerator:
        """Build a conference-abstract (abridged) flow diagram.

        The Abstract extension (Beller EM et al., *PRISMA for Abstracts*,
        J Clin Epidemiol 2013;66:657-8) provides an abridged diagram for
        conference submissions, journals with strict word counts, etc.

        Args:
            counts: Stage counts.
            title: Review title.

        Returns:
            Configured :class:`PRISMAFlowGenerator` with ``extension='abstract'``.
        """
        gen = PRISMAFlowGenerator(counts, title=title, extension="abstract")
        logger.debug("Abstract flow generator created: title=%r", title)
        return gen

    @staticmethod
    def diagnostic_flow(counts: PRISMAStageCounts,
                        title: str = "") -> PRISMAFlowGenerator:
        """Build a diagnostic test accuracy flow diagram.

        The DTA extension (McInnes MDF et al., *Preferred Reporting Items for
        a Systematic Review and Meta-analysis of Diagnostic Test Accuracy
        Studies*, JAMA 2018;319:388-96) requires reporting of index test,
        reference standard, and 2×2 data per study.

        Args:
            counts: Stage counts.
            title: Review title.

        Returns:
            Configured :class:`PRISMAFlowGenerator` with ``extension='diagnostic'``.
        """
        gen = PRISMAFlowGenerator(counts, title=title, extension="diagnostic")
        logger.debug("Diagnostic flow generator created: title=%r", title)
        return gen


__all__ = ["PRISMAExtension", "PRISMAExtensionGenerator"]
