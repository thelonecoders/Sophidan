"""
data_acquisition.integrations
=============================

Cross-source integration layer for the Academic Research Suite's
data-acquisition package.

This sub-package composes multiple individual scrapers into higher-
order services used throughout the application:

* :mod:`citation_resolver`  — :class:`CitationResolver` merges
  citation / references lists from Crossref, OpenCitations and
  Semantic Scholar, picking the most authoritative value when
  sources disagree.
* :mod:`oa_finder`          — :class:`OpenAccessFinder` searches
  Unpaywall, CORE and BASE in parallel for an open-access copy
  of a paper, and downloads the PDF when one is available.
* :mod:`metadata_enricher`  — :class:`MetadataEnricher` augments
  :class:`Paper` records with metadata from a configurable list
  of upstream sources, applying conflict resolution rules.

All three classes are deliberately tolerant of missing sources
(no API key, network error, ...).  When a source is unavailable,
the resolver skips it and continues with the remaining ones —
integration tests thus pass even in headless / minimal installs.
"""

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

from .citation_resolver import CitationResolver
from .oa_finder import OpenAccessFinder
from .metadata_enricher import MetadataEnricher

__all__ = [
    "CitationResolver",
    "OpenAccessFinder",
    "MetadataEnricher",
]
