"""High-level configuration manager that wraps :mod:`config.settings`.

:class:`ConfigManager` adds the ability to mutate settings at runtime and
persist them back to ``config/secrets.yaml`` (saved with ``0600``
permissions because the file holds API keys). It also emits a Qt signal
``config_changed(key, value)`` whenever a setting is updated, so UI widgets
can react in real time.

Hardening (audit 4-a / CONTRACT #9):

* ``get_setting(key, default)`` / ``set_setting(key, value, *, persist)``
  aliases exist alongside ``get`` / ``set``.
* Unknown keys are rejected with a warning instead of being silently set
  as arbitrary attributes; ``set`` returns ``False`` in that case.
* ``ai_provider`` and ``log_level`` values are validated before applying.
* Values whose key matches ``(api_key|secret|token|password)`` are
  REDACTED in the "Config updated" log line.
* ``config/secrets.yaml`` is written with ``chmod 0600``.
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Keys whose values must never be logged in plaintext.
_SECRET_KEY_RE = re.compile(r"api_key|secret|token|password", re.IGNORECASE)

_VALID_AI_PROVIDERS = {"openai", "anthropic", "ollama", "none"}
_VALID_LOG_LEVELS = {"debug", "info", "warning", "error", "critical"}

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
        self._slots: list = []

    def emit(self, *args: object, **kwargs: object) -> None:
        for slot in self._slots:
            try:
                slot(*args, **kwargs)
            except Exception:  # pragma: no cover - defensive
                pass

    def connect(self, slot: Any) -> Any:
        self._slots.append(slot)
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

    * ``get(key)`` / ``set(key, value)`` accessors (plus the
      ``get_setting`` / ``set_setting`` aliases)
    * ``save()`` persistence to ``config/secrets.yaml`` (chmod 0600)
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
        if not _HAS_QT:
            # Per-instance stub so managers never share a slot list (the
            # class attribute would otherwise be one shared object).
            self.config_changed = _signal(str, object)
        self._secrets_path: Path = secrets_path or self._SECRETS_YAML
        self._lock = threading.RLock()
        # Lazy import to avoid any circular dependency at module import time.
        from config.settings import get_settings

        self.settings = get_settings(refresh=True)
        # Canonical field names — anything else is an unknown key.
        self._known_keys: set = set(self.settings.to_dict().keys())

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

    def set(self, key: str, value: Any, *, persist: bool = False) -> bool:
        """Update a setting, validate it, and emit ``config_changed``.

        Args:
            key: Settings field name. Unknown keys are rejected (warning +
                ``False``) instead of being silently ``setattr``-ed.
            value: New value (coerced to the existing field's type via
                :meth:`_coerce`).
            persist: If ``True``, also write the change to ``secrets.yaml``.

        Returns:
            ``True`` when the setting was applied, ``False`` when the key is
            unknown or the value failed validation.
        """
        with self._lock:
            if key not in self._known_keys:
                logger.warning(
                    "ConfigManager.set: unknown settings key %r ignored "
                    "(not a Settings field)", key,
                )
                return False
            if not self._validate(key, value):
                return False
            current = getattr(self.settings, key, None)
            coerced = self._coerce(current, value)
            setattr(self.settings, key, coerced)
            try:
                self.config_changed.emit(key, coerced)
            except Exception:  # pragma: no cover - defensive
                logger.debug("config_changed signal emission failed", exc_info=True)
            if persist:
                self.save()
        if _SECRET_KEY_RE.search(key):
            logger.info("Config updated: %s = <redacted>", key)
        else:
            logger.info("Config updated: %s = %r", key, coerced)
        return True

    # Alias names required by the UI / main entry point (CONTRACT #9).
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Alias of :meth:`get`."""
        return self.get(key, default)

    def set_setting(
        self, key: str, value: Any, *, persist: bool = False,
    ) -> bool:
        """Alias of :meth:`set` (same validation + return semantics)."""
        return self.set(key, value, persist=persist)

    # ------------------------------------------------------------------ validation
    @staticmethod
    def _validate(key: str, value: Any) -> bool:
        """Validate constrained settings values. Warn + ``False`` when bad.

        ``ai_provider`` must be one of openai/anthropic/ollama/none;
        ``log_level`` one of DEBUG/INFO/WARNING/ERROR/CRITICAL
        (case-insensitive; stored normalised by :meth:`set` via coercion).
        """
        if key == "ai_provider":
            if isinstance(value, str) and value.strip().lower() in _VALID_AI_PROVIDERS:
                return True
            logger.warning(
                "Invalid ai_provider %r — expected one of %s",
                value, sorted(_VALID_AI_PROVIDERS),
            )
            return False
        if key == "log_level":
            if isinstance(value, str) and value.strip().lower() in _VALID_LOG_LEVELS:
                return True
            logger.warning(
                "Invalid log_level %r — expected one of %s",
                value, sorted(_VALID_LOG_LEVELS),
            )
            return False
        return True

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
        if default is None or isinstance(default, str):
            if raw is None or isinstance(raw, str):
                return raw
            return str(raw)
        return raw

    # ------------------------------------------------------------------ save/load
    def save(self, path: Optional[Path] = None) -> None:
        """Persist the current settings to a YAML file.

        The file may contain API keys, so it is written with ``0600``
        permissions (best-effort — some filesystems do not support chmod).

        Args:
            path: Target file path. Defaults to ``secrets.yaml``.
        """
        target = Path(path) if path else self._secrets_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = self.settings.to_dict()
        try:
            import yaml  # lazy — PyYAML is in requirements

            with open(target, "w", encoding="utf-8") as fh:
                yaml.safe_dump(data, fh, sort_keys=False, default_flow_style=False)
            try:
                os.chmod(target, 0o600)
            except OSError as exc:  # pragma: no cover - exotic filesystems
                logger.debug("Could not chmod 600 %s: %s", target, exc)
            logger.info("Config saved to %s", target)
        except Exception as exc:
            logger.error("Could not save config to %s: %s", target, exc)

    def reload(self) -> None:
        """Re-read settings from sources (defaults + yaml + env)."""
        with self._lock:
            from config.settings import get_settings, reset_settings

            reset_settings()
            self.settings = get_settings(refresh=True)
            self._known_keys = set(self.settings.to_dict().keys())
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

    def from_dict(self, d: Dict[str, Any], *, persist: bool = False) -> int:
        """Bulk-update settings from a dictionary.

        Unknown keys are warned about and skipped (they are no longer
        silently ignored, and never ``setattr``-ed onto the settings object).

        Args:
            d: Dictionary of settings to apply.
            persist: If ``True``, also write the result to ``secrets.yaml``.

        Returns:
            The number of settings actually applied.
        """
        known = self._known_keys
        applied = 0
        with self._lock:
            for key, value in d.items():
                if key not in known:
                    logger.warning(
                        "ConfigManager.from_dict: unknown settings key %r skipped",
                        key,
                    )
                    continue
                if not self._validate(key, value):
                    continue
                coerced = self._coerce(getattr(self.settings, key), value)
                setattr(self.settings, key, coerced)
                applied += 1
                try:
                    self.config_changed.emit(key, coerced)
                except Exception:  # pragma: no cover - defensive
                    pass
        if persist:
            self.save()
        return applied


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
