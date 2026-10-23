"""Global application settings for Academic Research Suite.

This module exposes a singleton ``Settings`` instance accessible through
:func:`get_settings`. Settings are loaded in the following priority order
(lowest to highest):

1. Hard-coded defaults baked into the :class:`Settings` dataclass.
2. ``config/default_config.yaml`` (shipped with the package).
3. ``config/secrets.yaml`` (optional, user-provided, .gitignored).
4. Environment variables prefixed with ``ARS_`` (case-insensitive lookup).
   Underscores in the variable name map directly to the field name, e.g.
   both ``ARS_AI_API_KEY`` and ``ars_ai_api_key`` set ``ai_api_key``.
5. Bare (unprefixed) fallback variables for the per-source API keys:
   ``SPRINGER_API_KEY``, ``IEEE_API_KEY``, ``CORE_API_KEY``,
   ``BASE_API_KEY``, ``S2_API_KEY``, ``UNPAYWALL_EMAIL``.

The loader is a plain :mod:`dataclasses` implementation that keeps the
module importable without pydantic (the optional pydantic path from the
original design was never wired; the dataclass surface is canonical).

Example:
    >>> from config.settings import get_settings
    >>> s = get_settings()
    >>> s.app_name
    'Academic Research Suite'
    >>> s.web_server_port
    8765
"""
from __future__ import annotations

#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
_CONFIG_DIR: Path = Path(__file__).resolve().parent
_PROJECT_ROOT: Path = _CONFIG_DIR.parent
_DEFAULT_CONFIG_PATH: Path = _CONFIG_DIR / "default_config.yaml"
_SECRETS_PATH: Path = _CONFIG_DIR / "secrets.yaml"

_ENV_PREFIX = "ARS_"

# Bare (unprefixed) environment fallbacks — CONTRACT #9. Checked in addition
# to the standard ``ARS_<FIELD>`` name.
_BARE_ENV_ALIASES: Dict[str, tuple] = {
    "springer_api_key": ("SPRINGER_API_KEY",),
    "ieee_api_key": ("IEEE_API_KEY",),
    "core_api_key": ("CORE_API_KEY",),
    "base_api_key": ("BASE_API_KEY",),
    "s2_api_key": ("S2_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"),
    "unpaywall_email": ("UNPAYWALL_EMAIL",),
    "ai_api_key": ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"),
}


def _coerce(default: Any, raw: str) -> Any:
    """Coerce a raw string env value to match the type of ``default``.

    Args:
        default: The default value whose type determines the target.
        raw: The raw string value read from the environment.

    Returns:
        The coerced value, or ``default`` if coercion fails.
    """
    if isinstance(default, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on", "y"}
    if isinstance(default, int) and not isinstance(default, bool):
        try:
            return int(raw)
        except ValueError:
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except ValueError:
            return default
    return raw


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file into a dict, returning an empty dict on any failure.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed dictionary, or ``{}`` if the file is missing or unparseable.
    """
    if not path.exists():
        return {}
    try:
        import yaml  # lazy import — PyYAML is in requirements but optional at runtime

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            logger.warning("Config file %s did not contain a mapping; ignoring.", path)
            return {}
        return data
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to load YAML config %s: %s", path, exc)
        return {}


# ---------------------------------------------------------------------------
# Settings dataclass (canonical definition; used by both code paths)
# ---------------------------------------------------------------------------
@dataclass
class Settings:
    """Application-wide configuration container.

    Attributes:
        app_name: Human-readable application name.
        version: Semantic version string.
        data_dir: Root data directory (relative or absolute).
        cache_dir: Directory for HTTP / scraper caches.
        projects_dir: Directory for user project workspaces.
        db_path: Path to the primary SQLite database file.
        log_level: Logging level name (``DEBUG``/``INFO``/``WARNING``/...).
        theme_name: Default UI theme identifier.
        proxy_enabled: Whether outbound scraping should use proxies.
        web_server_port: TCP port for the optional local web server.
        ai_provider: One of ``ollama``, ``openai``, ``anthropic``, ``none``.
        ai_model: Model identifier for the selected provider.
        ai_api_key: API key for the selected provider (secret).
        ai_base_url: Override base URL for the AI provider endpoint.
        scraping_rate_limit_per_sec: Max requests per second per host.
        scraping_max_concurrent: Maximum concurrent scraper workers.
        user_agent: Default ``User-Agent`` header for outbound HTTP.
        springer_api_key: Per-source API key for the Springer scraper.
        ieee_api_key: Per-source API key for the IEEE Xplore scraper.
        core_api_key: Per-source API key for the CORE aggregator.
        base_api_key: Per-source API key for the BASE index.
        s2_api_key: Per-source API key for Semantic Scholar.
        unpaywall_email: Contact e-mail required by the Unpaywall API.
        first_run_completed: Set once the first-run welcome screen has been
            shown (persisted to ``secrets.yaml`` so it is not shown again).
    """

    app_name: str = "Academic Research Suite"
    version: str = "2.0.0"
    data_dir: str = "data"
    cache_dir: str = "data/cache"
    projects_dir: str = "data/projects"
    db_path: str = "data/ars.db"
    log_level: str = "INFO"
    theme_name: str = "modern_dark"
    proxy_enabled: bool = False
    web_server_port: int = 8765
    ai_provider: str = "none"
    ai_model: str = ""
    ai_api_key: str = ""
    ai_base_url: str = ""
    scraping_rate_limit_per_sec: float = 1.0
    scraping_max_concurrent: int = 4
    user_agent: str = (
        "Mozilla/5.0 (compatible; AcademicResearchSuite/1.0; "
        "+https://github.com/thelonecoders/Sophidan)"
    )
    # Per-source API keys (CONTRACT #9) — all optional.
    springer_api_key: Optional[str] = None
    ieee_api_key: Optional[str] = None
    core_api_key: Optional[str] = None
    base_api_key: Optional[str] = None
    s2_api_key: Optional[str] = None
    unpaywall_email: Optional[str] = None
    # One-shot UI state.
    first_run_completed: bool = False

    # ------------------------------------------------------------------ helpers
    def to_dict(self) -> Dict[str, Any]:
        """Serialize this settings object to a plain dictionary."""
        return asdict(self)

    def resolve_path(self, key: str) -> Path:
        """Resolve a settings path field to an absolute :class:`pathlib.Path`.

        Relative paths are anchored at the project root.

        Args:
            key: Name of the path-valued settings field.

        Returns:
            Absolute ``Path`` object.
        """
        raw = getattr(self, key)
        p = Path(raw)
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        return p

    def ensure_directories(self) -> None:
        """Create the data / cache / projects directories if missing."""
        for key in ("data_dir", "cache_dir", "projects_dir"):
            try:
                path = self.resolve_path(key)
                path.mkdir(parents=True, exist_ok=True)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Could not create directory for %s: %s", key, exc)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def _build_settings() -> Settings:
    """Construct a :class:`Settings` instance from defaults + yaml + env.

    Returns:
        A fully populated :class:`Settings` instance.
    """
    defaults = Settings()
    default_dict = defaults.to_dict()
    merged: Dict[str, Any] = dict(default_dict)

    # 1. default_config.yaml
    merged.update(_load_yaml(_DEFAULT_CONFIG_PATH))
    # 2. secrets.yaml (optional)
    merged.update(_load_yaml(_SECRETS_PATH))
    # 3. ARS_-prefixed environment variables — CASE-INSENSITIVE lookup
    #    (the docstring promised this; the implementation was upper-case
    #    only). Also honour bare per-source fallbacks (CONTRACT #9).
    env_map: Dict[str, str] = {
        str(k).upper(): v for k, v in os.environ.items()
    }
    for field_name, default_value in default_dict.items():
        env_names = [f"{_ENV_PREFIX}{field_name.upper()}"]
        env_names.extend(_BARE_ENV_ALIASES.get(field_name, ()))
        for env_name in env_names:
            if env_name in env_map:
                merged[field_name] = _coerce(
                    default_value, env_map[env_name],
                )
                break

    # Filter to known fields only (ignore unknown keys in yaml/env).
    known = set(default_dict.keys())
    clean = {k: v for k, v in merged.items() if k in known}

    try:
        return Settings(**clean)
    except TypeError as exc:
        logger.warning("Falling back to defaults due to settings error: %s", exc)
        return defaults


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------
_settings_instance: Optional[Settings] = None


def get_settings(refresh: bool = False) -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    Args:
        refresh: If ``True``, rebuild the singleton from sources (config files
            + environment). Useful after editing ``secrets.yaml``.

    Returns:
        The shared :class:`Settings` instance.
    """
    global _settings_instance
    if _settings_instance is None or refresh:
        _settings_instance = _build_settings()
    return _settings_instance


def reset_settings() -> None:
    """Reset the singleton (primarily for tests)."""
    global _settings_instance
    _settings_instance = None


__all__ = ["Settings", "get_settings", "reset_settings"]
