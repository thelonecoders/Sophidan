"""PRISMA 2020 reporting package for systematic reviews.

This package provides publication-grade PRISMA 2020 flow diagrams, the
27-item PRISMA 2020 checklist, six official extensions (IPD, NMA, ScR,
Harms, Abstract, Diagnostic), data extraction forms, and an end-to-end
report generator that bundles all of the above into a single PDF/DOCX/HTML
document.

Reference
---------
Page MJ, McKenzie JE, Bossuyt PM, Boutron I, Hoffmann TC, Mulrow CD, et al.
*The PRISMA 2020 statement: an updated guideline for reporting systematic
reviews.* BMJ 2021;372:n71. doi:10.1136/bmj.n71

Modules
-------
* :mod:`prisma.flow_diagram`     — flow-diagram generator
* :mod:`prisma.extensions`       — extension-template builders
* :mod:`prisma.checklist`        — 27-item checklist + per-extension items
* :mod:`prisma.extraction_form`  — per-study extraction forms + search records
* :mod:`prisma.report`           — bundled end-to-end report generator
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

# Heavy deps (matplotlib, reportlab, python-docx, PyYAML) are imported
# lazily inside the relevant methods, so importing this package never
# raises even when an optional dep is absent.
from .checklist import PRISMAChecklist, PRISMAItem, PRISMAExtensionsChecklist
from .extraction_form import PRISMAExtractionForm, PRISMASearchStrategy
from .extensions import PRISMAExtension, PRISMAExtensionGenerator
from .flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts
from .report import PRISMAReport

__all__ = [
    "PRISMAFlowGenerator",
    "PRISMAStageCounts",
    "PRISMAExtension",
    "PRISMAExtensionGenerator",
    "PRISMAChecklist",
    "PRISMAItem",
    "PRISMAExtensionsChecklist",
    "PRISMAExtractionForm",
    "PRISMASearchStrategy",
    "PRISMAReport",
]
