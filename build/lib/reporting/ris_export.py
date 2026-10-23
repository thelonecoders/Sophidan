"""Alias module: ``reporting.ris_export`` → :mod:`reporting.ris_exporter`.

``ui/dialogs/export_wizard.py`` resolves ``RisExporter`` by trying
``reporting.ris_export`` first, then ``reporting.bibtex_export`` and the
``reporting`` package.  The canonical implementation lives in
:mod:`reporting.ris_exporter`; this thin re-export (added by the P-g
reporting/proxy patch) makes the wizard's first candidate resolve too.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from .ris_exporter import RisExporter

__all__ = ["RisExporter"]
