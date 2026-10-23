"""research_lifecycle — end-to-end research lifecycle toolkit (v2.0.0).

The ``research_lifecycle`` package provides the workflow-level glue that
turns the Academic Research Suite from a *toolkit* of isolated capabilities
(scrapers, knowledge graphs, AI chat, reporting) into a *workflow platform*
that supports an entire research project from idea generation through
publication.

Sub-modules
-----------
* :mod:`research_lifecycle.ideation`            — research-question / gap
  detection and idea generation (LLM-augmented with deterministic fallback).
* :mod:`research_lifecycle.protocol_templates`   — pre-built study-protocol
  templates (PRISMA SR, scoping, meta-analysis, RCT, cohort, case study,
  qualitative, mixed methods, rapid review) plus a builder that produces
  Markdown / PDF / DOCX protocols from any template.
* :mod:`research_lifecycle.data_extraction`     — structured extraction
  templates (Cochrane RCT, observational, qualitative, mixed methods,
  bibliometric, content analysis, survey research) and a session class
  with validation + YAML / JSON serialisation.
* :mod:`research_lifecycle.synthesis_methods`    — synthesis methods that
  go beyond meta-analysis: narrative, thematic / framework / grounded,
  qualitative comparative analysis (QCA) with fuzzy-set calibration,
  meta-synthesis, and Best-Fit Framework synthesis.
* :mod:`research_lifecycle.quality_assessment`   — quality / risk-of-bias
  tools for non-RCT designs: MMAT, STROBE, CONSORT, PRISMA, CARE, CARE+,
  SRQR, ENTREQ, CASP (multi-variant).
* :mod:`research_lifecycle.reporting_checklists`— publication reporting
  checklists aligned with the EQUATOR Network (CONSORT, STROBE, PRISMA,
  STARD, TRIPOD, SPIRIT, SQUIRE, CHEERS, TREND, COREQ).
* :mod:`research_lifecycle.writing_assistant`    — AI-assisted writing with
  deterministic templates when no LLM client is supplied (outlines, section
  drafting, prose improvement, grammar checks, abstract / title generation,
  citation formatting, IMRaD summarisation).

Every sub-module is independently importable: heavy third-party deps
(``pandas``, ``networkx``, ``reportlab``, ``python-docx``, ``matplotlib``)
are imported lazily inside the functions that actually need them, so
``import research_lifecycle`` succeeds even in a minimal environment. The
package follows the same coding standards as the v1.0.0 baseline:
Python 3.10+, type hints, Google docstrings, ``logging.getLogger``
(never ``print``), MIT header, lazy imports.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

__version__ = "2.0.0"

__all__ = [
    "ideation",
    "protocol_templates",
    "data_extraction",
    "synthesis_methods",
    "quality_assessment",
    "reporting_checklists",
    "writing_assistant",
    "__version__",
]
