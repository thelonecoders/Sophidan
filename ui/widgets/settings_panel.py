"""Application settings panel.

Provides :class:`SettingsPanel` — a tabbed interface (General / Scraping /
Proxy / AI / Database / Appearance / Advanced) backed by
``utils.config_manager.ConfigManager`` (lazy import). Save / Reset / Defaults
buttons at the bottom persist the user's choices.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Theme options.
THEMES: List[str] = ["dark", "light", "system"]
# Log levels exposed in the General tab.
LOG_LEVELS: List[str] = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
# AI providers exposed in the AI tab.
AI_PROVIDERS: List[str] = ["none", "ollama", "openai", "anthropic"]


class SettingsPanel(QWidget):
    """Application settings widget with seven tabs and Save/Reset/Defaults.

    Uses ``utils.config_manager.ConfigManager`` (lazy import) to persist
    settings. Emits ``settings_saved`` whenever the user saves.
    """

    settings_saved = Signal(dict)
    settings_reset = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the panel and load defaults from ConfigManager."""
        super().__init__(parent)
        self._manager: Optional[Any] = None
        self._defaults: Dict[str, Any] = self._build_defaults()

        self._build_ui()
        self._connect_signals()
        self.load_settings()

    # ------------------------------------------------------- Defaults

    def _build_defaults(self) -> Dict[str, Any]:
        return {
            # General
            "theme": "dark",
            "language": "en",
            "data_dir": "./data",
            "log_level": "INFO",
            # Scraping
            "default_sources": ["arXiv", "OpenAlex"],
            "rate_limit": 1.0,
            "max_concurrent": 4,
            "cache_ttl": 3600,
            "user_agent": "AcademicResearchSuite/0.1",
            # Proxy
            "proxy_enabled": False,
            "default_strategy": "Round-robin",
            "auto_refresh_interval": 600,
            "ban_threshold": 5,
            # AI
            "ai_provider": "none",
            "ai_model": "gpt-4o-mini",
            "ai_api_key": "",
            "ai_base_url": "",
            "ai_temperature": 0.7,
            "ai_max_tokens": 2048,
            "ai_system_prompt": "",
            # Database
            "db_path": "./data/suite.db",
            # Appearance
            "accent_color": "#007acc",
            "font_family": "Noto Sans",
            "font_size": 11,
            "sidebar_collapsed_default": False,
            # Advanced
            "experimental_features": False,
            "debug_mode": False,
            "telemetry_opt_out": True,
        }

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), "General")
        self.tabs.addTab(self._build_scraping_tab(), "Scraping")
        self.tabs.addTab(self._build_proxy_tab(), "Proxy")
        self.tabs.addTab(self._build_ai_tab(), "AI")
        self.tabs.addTab(self._build_database_tab(), "Database")
        self.tabs.addTab(self._build_appearance_tab(), "Appearance")
        self.tabs.addTab(self._build_advanced_tab(), "Advanced")
        outer.addWidget(self.tabs, stretch=1)

        # Bottom action buttons
        btns = QHBoxLayout()
        btns.addStretch()
        self.defaults_button = QPushButton("Reset to Defaults")
        self.reset_button = QPushButton("Reset (Discard)")
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("PrimaryButton")
        btns.addWidget(self.defaults_button)
        btns.addWidget(self.reset_button)
        btns.addWidget(self.save_button)
        outer.addLayout(btns)

    # ------------------------------------------------------- Tabs

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(12, 12, 12, 12)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES)
        form.addRow("Theme:", self.theme_combo)

        self.language_combo = QComboBox()
        self.language_combo.addItems(["en", "zh", "es", "fr", "de", "ja"])
        self.language_combo.setEditable(True)
        form.addRow("Language:", self.language_combo)

        self.data_dir_edit = QLineEdit()
        self.data_dir_edit.setPlaceholderText("Path to data directory…")
        data_dir_row = QHBoxLayout()
        data_dir_row.addWidget(self.data_dir_edit, stretch=1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_data_dir)
        data_dir_row.addWidget(browse)
        form.addRow("Data dir:", self._wrap(data_dir_row))

        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(LOG_LEVELS)
        form.addRow("Log level:", self.log_level_combo)
        return tab

    def _build_scraping_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(12, 12, 12, 12)

        self.scraping_default_sources = QLineEdit()
        self.scraping_default_sources.setPlaceholderText("comma-separated, e.g. arXiv, OpenAlex")
        form.addRow("Default sources:", self.scraping_default_sources)

        self.rate_limit_spin = QDoubleSpinBox()
        self.rate_limit_spin.setRange(0.0, 60.0)
        self.rate_limit_spin.setSingleStep(0.1)
        self.rate_limit_spin.setDecimals(2)
        self.rate_limit_spin.setSuffix(" req/s")
        form.addRow("Rate limit:", self.rate_limit_spin)

        self.max_concurrent_spin = QSpinBox()
        self.max_concurrent_spin.setRange(1, 64)
        form.addRow("Max concurrent:", self.max_concurrent_spin)

        self.cache_ttl_spin = QSpinBox()
        self.cache_ttl_spin.setRange(0, 24 * 3600)
        self.cache_ttl_spin.setSuffix(" s")
        form.addRow("Cache TTL:", self.cache_ttl_spin)

        self.user_agent_edit = QLineEdit()
        form.addRow("User agent:", self.user_agent_edit)
        return tab

    def _build_proxy_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(12, 12, 12, 12)
        self.proxy_enabled = QCheckBox("Enable proxy usage")
        form.addRow(self.proxy_enabled)

        self.proxy_strategy_combo = QComboBox()
        self.proxy_strategy_combo.addItems(
            ["Round-robin", "Random", "Least-latency", "Weighted", "Sticky-session"]
        )
        form.addRow("Default strategy:", self.proxy_strategy_combo)

        self.proxy_refresh_spin = QSpinBox()
        self.proxy_refresh_spin.setRange(30, 86400)
        self.proxy_refresh_spin.setSuffix(" s")
        form.addRow("Auto-refresh interval:", self.proxy_refresh_spin)

        self.ban_threshold_spin = QSpinBox()
        self.ban_threshold_spin.setRange(0, 100)
        form.addRow("Ban threshold (failures):", self.ban_threshold_spin)
        return tab

    def _build_ai_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(12, 12, 12, 12)

        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.addItems(AI_PROVIDERS)
        form.addRow("Provider:", self.ai_provider_combo)

        self.ai_model_edit = QLineEdit()
        form.addRow("Model:", self.ai_model_edit)

        self.ai_api_key_edit = QLineEdit()
        self.ai_api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_api_key_edit.setPlaceholderText("sk-…")
        form.addRow("API key:", self.ai_api_key_edit)

        self.ai_base_url_edit = QLineEdit()
        self.ai_base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        form.addRow("Base URL:", self.ai_base_url_edit)

        self.ai_temperature_spin = QDoubleSpinBox()
        self.ai_temperature_spin.setRange(0.0, 2.0)
        self.ai_temperature_spin.setSingleStep(0.05)
        self.ai_temperature_spin.setDecimals(2)
        form.addRow("Temperature:", self.ai_temperature_spin)

        self.ai_max_tokens_spin = QSpinBox()
        self.ai_max_tokens_spin.setRange(64, 32768)
        self.ai_max_tokens_spin.setSingleStep(64)
        form.addRow("Max tokens:", self.ai_max_tokens_spin)

        self.ai_system_prompt_edit = QTextEdit()
        self.ai_system_prompt_edit.setMaximumHeight(100)
        form.addRow("System prompt:", self.ai_system_prompt_edit)
        return tab

    def _build_database_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(12, 12, 12, 12)

        self.db_path_edit = QLineEdit()
        form.addRow("DB path:", self.db_path_edit)

        db_row = QHBoxLayout()
        self.vacuum_btn = QPushButton("Vacuum")
        self.backup_btn = QPushButton("Backup…")
        self.restore_btn = QPushButton("Restore…")
        self.fts_rebuild_btn = QPushButton("Rebuild FTS")
        self.vector_reset_btn = QPushButton("Reset Vector Store")
        for b in (self.vacuum_btn, self.backup_btn, self.restore_btn,
                  self.fts_rebuild_btn, self.vector_reset_btn):
            db_row.addWidget(b)
        form.addRow("Maintenance:", self._wrap(db_row))
        return tab

    def _build_appearance_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(12, 12, 12, 12)

        self.accent_color_edit = QLineEdit()
        self.accent_color_edit.setPlaceholderText("#007acc")
        accent_row = QHBoxLayout()
        accent_row.addWidget(self.accent_color_edit, stretch=1)
        pick = QPushButton("Pick…")
        pick.clicked.connect(self._pick_accent_color)
        accent_row.addWidget(pick)
        form.addRow("Accent color:", self._wrap(accent_row))

        self.font_family_combo = QComboBox()
        self.font_family_combo.setEditable(True)
        self.font_family_combo.addItems(["Noto Sans", "DejaVu Sans", "Segoe UI", "Roboto", "Arial"])
        form.addRow("Font family:", self.font_family_combo)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        form.addRow("Font size:", self.font_size_spin)

        self.sidebar_collapsed = QCheckBox("Collapse sidebar by default")
        form.addRow(self.sidebar_collapsed)
        return tab

    def _build_advanced_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(12, 12, 12, 12)
        self.experimental_check = QCheckBox("Enable experimental features")
        self.debug_check = QCheckBox("Debug mode")
        self.telemetry_check = QCheckBox("Opt out of telemetry")
        self.telemetry_check.setChecked(True)
        form.addRow(self.experimental_check)
        form.addRow(self.debug_check)
        form.addRow(self.telemetry_check)
        return tab

    def _wrap(self, layout: QHBoxLayout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        return w

    # ------------------------------------------------------- Signals

    def _connect_signals(self) -> None:
        self.save_button.clicked.connect(self._on_save)
        self.reset_button.clicked.connect(self.load_settings)
        self.defaults_button.clicked.connect(self._on_defaults)
        self.vacuum_btn.clicked.connect(self._on_vacuum)
        self.backup_btn.clicked.connect(self._on_backup)
        self.restore_btn.clicked.connect(self._on_restore)
        self.fts_rebuild_btn.clicked.connect(self._on_fts_rebuild)
        self.vector_reset_btn.clicked.connect(self._on_vector_reset)

    # ------------------------------------------------------- ConfigManager

    def _get_manager(self) -> Any:
        if self._manager is None:
            try:
                from utils.config_manager import ConfigManager
                self._manager = ConfigManager()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ConfigManager not available: %s", exc)
                self._manager = None
        return self._manager

    def load_settings(self) -> None:
        """Load settings from the ConfigManager into the widgets."""
        manager = self._get_manager()
        if manager is not None:
            try:
                cfg = manager.to_dict()
            except Exception as exc:  # noqa: BLE001
                logger.warning("to_dict failed: %s", exc)
                cfg = {}
            merged = dict(self._defaults)
            merged.update(cfg if isinstance(cfg, dict) else {})
        else:
            merged = dict(self._defaults)
        self._apply_settings(merged)

    def _apply_settings(self, settings: Dict[str, Any]) -> None:
        # General
        self.theme_combo.setCurrentText(str(settings.get("theme", "dark")))
        self.language_combo.setCurrentText(str(settings.get("language", "en")))
        self.data_dir_edit.setText(str(settings.get("data_dir", "")))
        self.log_level_combo.setCurrentText(str(settings.get("log_level", "INFO")))
        # Scraping
        self.scraping_default_sources.setText(
            ", ".join(settings.get("default_sources", []) or [])
        )
        self.rate_limit_spin.setValue(float(settings.get("rate_limit", 1.0)))
        self.max_concurrent_spin.setValue(int(settings.get("max_concurrent", 4)))
        self.cache_ttl_spin.setValue(int(settings.get("cache_ttl", 3600)))
        self.user_agent_edit.setText(str(settings.get("user_agent", "")))
        # Proxy
        self.proxy_enabled.setChecked(bool(settings.get("proxy_enabled", False)))
        self.proxy_strategy_combo.setCurrentText(
            str(settings.get("default_strategy", "Round-robin"))
        )
        self.proxy_refresh_spin.setValue(int(settings.get("auto_refresh_interval", 600)))
        self.ban_threshold_spin.setValue(int(settings.get("ban_threshold", 5)))
        # AI
        self.ai_provider_combo.setCurrentText(str(settings.get("ai_provider", "none")))
        self.ai_model_edit.setText(str(settings.get("ai_model", "")))
        self.ai_api_key_edit.setText(str(settings.get("ai_api_key", "")))
        self.ai_base_url_edit.setText(str(settings.get("ai_base_url", "")))
        self.ai_temperature_spin.setValue(float(settings.get("ai_temperature", 0.7)))
        self.ai_max_tokens_spin.setValue(int(settings.get("ai_max_tokens", 2048)))
        self.ai_system_prompt_edit.setPlainText(str(settings.get("ai_system_prompt", "")))
        # Database
        self.db_path_edit.setText(str(settings.get("db_path", "")))
        # Appearance
        self.accent_color_edit.setText(str(settings.get("accent_color", "#007acc")))
        self.font_family_combo.setCurrentText(str(settings.get("font_family", "Noto Sans")))
        self.font_size_spin.setValue(int(settings.get("font_size", 11)))
        self.sidebar_collapsed.setChecked(bool(settings.get("sidebar_collapsed_default", False)))
        # Advanced
        self.experimental_check.setChecked(bool(settings.get("experimental_features", False)))
        self.debug_check.setChecked(bool(settings.get("debug_mode", False)))
        self.telemetry_check.setChecked(bool(settings.get("telemetry_opt_out", True)))

    def _collect_settings(self) -> Dict[str, Any]:
        sources = [
            s.strip() for s in self.scraping_default_sources.text().split(",")
            if s.strip()
        ]
        return {
            "theme": self.theme_combo.currentText(),
            "language": self.language_combo.currentText(),
            "data_dir": self.data_dir_edit.text().strip(),
            "log_level": self.log_level_combo.currentText(),
            "default_sources": sources,
            "rate_limit": self.rate_limit_spin.value(),
            "max_concurrent": self.max_concurrent_spin.value(),
            "cache_ttl": self.cache_ttl_spin.value(),
            "user_agent": self.user_agent_edit.text(),
            "proxy_enabled": self.proxy_enabled.isChecked(),
            "default_strategy": self.proxy_strategy_combo.currentText(),
            "auto_refresh_interval": self.proxy_refresh_spin.value(),
            "ban_threshold": self.ban_threshold_spin.value(),
            "ai_provider": self.ai_provider_combo.currentText(),
            "ai_model": self.ai_model_edit.text().strip(),
            "ai_api_key": self.ai_api_key_edit.text(),
            "ai_base_url": self.ai_base_url_edit.text().strip(),
            "ai_temperature": self.ai_temperature_spin.value(),
            "ai_max_tokens": self.ai_max_tokens_spin.value(),
            "ai_system_prompt": self.ai_system_prompt_edit.toPlainText(),
            "db_path": self.db_path_edit.text().strip(),
            "accent_color": self.accent_color_edit.text().strip(),
            "font_family": self.font_family_combo.currentText(),
            "font_size": self.font_size_spin.value(),
            "sidebar_collapsed_default": self.sidebar_collapsed.isChecked(),
            "experimental_features": self.experimental_check.isChecked(),
            "debug_mode": self.debug_check.isChecked(),
            "telemetry_opt_out": self.telemetry_check.isChecked(),
        }

    def _on_save(self) -> None:
        settings = self._collect_settings()
        manager = self._get_manager()
        if manager is not None:
            try:
                manager.from_dict(settings, persist=True)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Save", f"Failed to save: {exc}")
                return
        else:
            logger.info("ConfigManager unavailable — settings not persisted.")
        self.settings_saved.emit(settings)

    def _on_defaults(self) -> None:
        self._apply_settings(self._defaults)
        self.settings_reset.emit()

    # ------------------------------------------------------- Pickers / DB ops

    def _browse_data_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select data directory")
        if path:
            self.data_dir_edit.setText(path)

    def _pick_accent_color(self) -> None:
        color = QColorDialog.getColor()
        if color.isValid():
            self.accent_color_edit.setText(color.name())

    def _on_vacuum(self) -> None:
        try:
            from database.connection import DatabaseConnection
            DatabaseConnection().vacuum()
            QMessageBox.information(self, "Vacuum", "Database vacuumed.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Vacuum", f"Failed: {exc}")

    def _on_backup(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Backup Database", "backup.db", "SQLite DB (*.db)"
        )
        if not path:
            return
        try:
            from database.connection import DatabaseConnection
            DatabaseConnection().backup(path)
            QMessageBox.information(self, "Backup", f"Backed up to {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Backup", f"Failed: {exc}")

    def _on_restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore Database", "", "SQLite DB (*.db)"
        )
        if not path:
            return
        try:
            from database.connection import DatabaseConnection
            DatabaseConnection().restore(path)
            QMessageBox.information(self, "Restore", "Database restored.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Restore", f"Failed: {exc}")

    def _on_fts_rebuild(self) -> None:
        try:
            from database.search import SearchIndexer
            SearchIndexer().rebuild_index()
            QMessageBox.information(self, "FTS", "FTS index rebuilt.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "FTS", f"Failed: {exc}")

    def _on_vector_reset(self) -> None:
        confirm = QMessageBox.question(
            self, "Reset Vector Store",
            "This will wipe the vector store. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            from database.vector_store import VectorStore
            VectorStore().clear()
            QMessageBox.information(self, "Vector Store", "Vector store reset.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Vector Store", f"Failed: {exc}")
