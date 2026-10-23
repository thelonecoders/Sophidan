"""Shared pytest configuration for the Academic Research Suite.

Provides the session-wide, hermetic environment the test-suite
documentation promises (CONTRIBUTING.md: "per-feature tests inherit
these via ``conftest.py``"):

* ``QT_QPA_PLATFORM=offscreen`` — Qt tests run headless.
* ``MPLBACKEND=Agg`` — matplotlib never opens a window.
* Project root on ``sys.path`` regardless of invocation CWD.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")
