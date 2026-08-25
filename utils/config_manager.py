"""High-level configuration manager that wraps :mod:`config.settings`.

:class:`ConfigManager` adds the ability to mutate settings at runtime and
persist them back to ``config/secrets.yaml``. It also emits a Qt signal
``config_changed(key, value)`` whenever a setting is updated, so UI widgets
can react in real time.

The manager keeps the singleton :class:`config.settings.Settings` instance in
sync with its own internal state.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Qt shim — only the Signal needs Qt. Fall back to a stub when qtpy is missing.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - depends on environment
    from qtpy.QtCore import QObject, Signal

    _HAS_QT = True
    _QObjectBase = QObject  # type: ignore[misc, valid-type]
except Exception:  # pragma: no cover - depends on environment
    _HAS_QT = False

    class _QObjectBase:  # type: ignore[no-redef]
        """Stub QObject replacement used when Qt is missing."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass


class _StubSignal:
    """No-op replacement for ``qtpy.QtCore.Signal`` when Qt is unavailable."""

    def __init__(self, *types: object) -> None:
        self._types = types

    def emit(self, *args: object, **kwargs: object) -> None:
        return None

    def connect(self, slot: Any) -> Any:
        return slot


def _signal(*types: object) -> Any:
    """Return a Qt ``Signal`` or a stub depending on availability."""
    if _HAS_QT:
        return Signal(*types)  # type: ignore[no-redef]
    return _StubSignal(*types)


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------
class ConfigManager(_QObjectBase):  # type: ignore[misc]
    """Runtime configuration manager.

    Wraps :class:`config.settings.Settings` to provide:

    * ``get(key)`` / ``set(key, value)`` accessors
    * ``save()`` persistence to ``config/secrets.yaml``
    * ``reload()`` to re-read sources (defaults + yaml + env)
    * ``to_dict()`` / ``from_dict(d)`` for serialization
    * ``config_changed(key, value)`` Qt signal on every successful ``set``

    Attributes:
        settings: The live :class:`config.settings.Settings` instance.
    """

    config_changed: Any = _signal(str, object)

    _CONFIG_DIR: Path = Path(__file__).resolve().parent.parent / "config"
    _DEFAULT_YAML: Path = _CONFIG_DIR / "default_config.yaml"
    _SECRETS_YAML: Path = _CONFIG_DIR / "secrets.yaml"

    def __init__(self, secrets_path: Optional[Path] = None) -> None:
        """Initialize the manager.

        Args:
            secrets_path: Override path for the user-editable secrets file.
                Defaults to ``config/secrets.yaml``.
        """
        super().__init__()
        self._secrets_path: Path = secrets_path or self._SECRETS_YAML
        self._lock = threading.RLock()
        # Lazy import to avoid any circular dependency at module import time.
        from config.settings import get_settings

        self.settings = get_settings(refresh=True)

    # ------------------------------------------------------------------ get/set
    def get(self, key: str, default: Any = None) -> Any:
        """Return the value of ``key``, or ``default`` if absent.

        Args:
            key: Settings field name.
            default: Returned when the field is not found.

        Returns:
            The current value.
        """
        with self._lock:
            return getattr(self.settings, key, default)

    def set(self, key: str, value: Any, *, persist: bool = False) -> None:
        """Update a setting and emit ``config_changed``.

        Args:
            key: Settings field name.
            value: New value (will be coerced to the existing field's type
                via :meth:`_coerce`).
            persist: If ``True``, also write the change to ``secrets.yaml``.
        """
        with self._lock:
            current = getattr(self.settings, key, None)
            coerced = self._coerce(current, value)
            setattr(self.settings, key, coerced)
            try:
                self.config_changed.emit(key, coerced)
            except Exception:  # pragma: no cover - defensive
                logger.debug("config_changed signal emission failed", exc_info=True)
            if persist:
                self.save()
        logger.info("Config updated: %s = %r", key, coerced)

    # ------------------------------------------------------------------ coerce
    @staticmethod
    def _coerce(default: Any, raw: Any) -> Any:
        """Coerce ``raw`` to match the type of ``default`` (best-effort)."""
        if isinstance(default, bool):
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                return raw.strip().lower() in {"1", "true", "yes", "on", "y"}
            return bool(raw)
        if isinstance(default, int) and not isinstance(default, bool):
            try:
                return int(raw)
            except (TypeError, ValueError):
                return default
        if isinstance(default, float):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return default
        return raw

    # ------------------------------------------------------------------ save/load
    def save(self, path: Optional[Path] = None) -> None:
        """Persist the current settings to a YAML file.

        Args:
            path: Target file path. Defaults to ``secrets.yaml``.
        """
        target = path or self._secrets_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = self.settings.to_dict()
        try:
            import yaml  # lazy — PyYAML is in requirements

            with open(target, "w", encoding="utf-8") as fh:
                yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)
            logger.info("Config saved to %s", target)
        except Exception as exc:
            logger.error("Could not save config to %s: %s", target, exc)

    def reload(self) -> None:
        """Re-read settings from sources (defaults + yaml + env)."""
        with self._lock:
            from config.settings import get_settings, reset_settings

            reset_settings()
            self.settings = get_settings(refresh=True)
        try:
            self.config_changed.emit("__reload__", self.settings.to_dict())
        except Exception:  # pragma: no cover - defensive
            pass
        logger.info("Config reloaded")

    # ------------------------------------------------------------------ dict
    def to_dict(self) -> Dict[str, Any]:
        """Return a deep copy of all settings as a plain dict."""
        with self._lock:
            return self.settings.to_dict()

    def from_dict(self, d: Dict[str, Any], *, persist: bool = False) -> None:
        """Bulk-update settings from a dictionary.

        Unknown keys are silently ignored.

        Args:
            d: Dictionary of settings to apply.
            persist: If ``True``, also write the result to ``secrets.yaml``.
        """
        known = set(self.settings.to_dict().keys())
        with self._lock:
            for key, value in d.items():
                if key not in known:
                    continue
                coerced = self._coerce(getattr(self.settings, key), value)
                setattr(self.settings, key, coerced)
                try:
                    self.config_changed.emit(key, coerced)
                except Exception:  # pragma: no cover - defensive
                    pass
        if persist:
            self.save()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------
_CONFIG_MANAGER: Optional[ConfigManager] = None
_CM_LOCK = threading.Lock()


def get_config_manager() -> ConfigManager:
    """Return the process-wide :class:`ConfigManager` singleton."""
    global _CONFIG_MANAGER
    with _CM_LOCK:
        if _CONFIG_MANAGER is None:
            _CONFIG_MANAGER = ConfigManager()
        return _CONFIG_MANAGER


__all__ = ["ConfigManager", "get_config_manager"]
