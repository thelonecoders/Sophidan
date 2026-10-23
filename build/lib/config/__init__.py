"""Configuration package for Academic Research Suite.

Re-exports :class:`config.settings.Settings` and :func:`get_settings`.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from .settings import Settings, get_settings, reset_settings

__all__ = ["Settings", "get_settings", "reset_settings"]
