"""Utility package for Academic Research Suite.

Re-exports the most commonly used helpers so callers can do::

    from utils import get_logger, ConfigManager, Cache, run_in_background

Sub-modules: :mod:`utils.exceptions`, :mod:`utils.logger`,
:mod:`utils.workers`, :mod:`utils.cache`, :mod:`utils.config_manager`.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from .exceptions import ARSError
from .logger import get_logger, LogViewer
from .config_manager import ConfigManager, get_config_manager
from .cache import Cache, TTLCache
from .workers import Worker, WorkerSignals, WorkerPool, run_in_background

__all__ = [
    "ARSError",
    "get_logger",
    "LogViewer",
    "ConfigManager",
    "get_config_manager",
    "Cache",
    "TTLCache",
    "Worker",
    "WorkerSignals",
    "WorkerPool",
    "run_in_background",
]
