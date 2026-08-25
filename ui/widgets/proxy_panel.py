"""Proxy management panel.

Provides :class:`ProxyPanel` — a top stats row (total / healthy / avg latency /
last refresh), Refresh Pool / Import / Export buttons, a proxies table with
right-click context menu (Test / Add to Chain / Ban / Remove), a rotation
strategy selector + drag-and-drop chain builder, and a real-time event log.
Backed by ``proxy.proxy_pool.ProxyPool`` (lazy import).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from qtpy.QtCore import Qt, Signal, QTimer
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QAbstractItemView,
    QAction,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Table column headers.
PROXY_COLUMNS: List[str] = [
    "Host", "Port", "Protocol", "Country", "Anonymity",
    "Latency (ms)", "Success Rate", "Last Check", "Actions",
]

# Rotation strategies exposed in the bottom selector.
ROTATION_STRATEGIES: List[str] = [
    "Round-robin", "Random", "Least-latency", "Weighted", "Sticky-session",
]


class StatCard(QGroupBox):
    """Small card showing a labelled metric value (used in the top stats row)."""

    def __init__(self, label: str, value: str = "—",
                 parent: Optional[QWidget] = None) -> None:
        """Build a card with the given label and initial value."""
        super().__init__(label, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet("font-size:18px;font-weight:bold;color:#007acc;")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        """Update the displayed value."""
        self.value_label.setText(value)


class ProxyPanel(QWidget):
    """Proxy management widget.

    Displays and manages the proxy pool, builds chains, logs events, and
    exposes import/export. Uses ``proxy.proxy_pool.ProxyPool`` (lazy import).
    """

    refresh_started = Signal()
    refresh_finished = Signal()
    proxy_tested = Signal(str, dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the panel with an empty proxy pool reference."""
        super().__init__(parent)
        self._pool: Optional[Any] = None
        self._worker: Optional[Any] = None
        self._cancel_requested: bool = False
        self._last_refresh: float = 0.0

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # Stats row
        stats_row = QHBoxLayout()
        self.card_total = StatCard("Total Proxies")
        self.card_healthy = StatCard("Healthy Proxies")
        self.card_latency = StatCard("Avg Latency")
        self.card_refresh = StatCard("Last Refresh")
        for card in (self.card_total, self.card_healthy, self.card_latency, self.card_refresh):
            stats_row.addWidget(card, stretch=1)
        outer.addLayout(stats_row)

        # Actions row
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh Pool")
        self.refresh_button.setObjectName("PrimaryButton")
        self.import_button = QPushButton("Import…")
        self.export_button = QPushButton("Export…")
        self.test_all_button = QPushButton("Test All")
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.test_all_button)
        actions.addWidget(self.import_button)
        actions.addWidget(self.export_button)
        actions.addStretch()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumWidth(220)
        actions.addWidget(self.progress_bar)
        outer.addLayout(actions)

        # Splitter: table | right (chain + log)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Table
        table_box = QGroupBox("Proxy Pool")
        table_layout = QVBoxLayout(table_box)
        self.table = QTableWidget(0, len(PROXY_COLUMNS))
        self.table.setHorizontalHeaderLabels(PROXY_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table_layout.addWidget(self.table)
        splitter.addWidget(table_box)

        # Right: chain builder + log
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        chain_box = QGroupBox("Chain Builder")
        chain_layout = QVBoxLayout(chain_box)
        chain_top = QHBoxLayout()
        chain_top.addWidget(QLabel("Strategy:"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(ROTATION_STRATEGIES)
        chain_top.addWidget(self.strategy_combo, stretch=1)
        chain_layout.addLayout(chain_top)

        self.chain_list = QListWidget()
        self.chain_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.chain_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.chain_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        chain_layout.addWidget(self.chain_list, stretch=1)

        chain_btns = QHBoxLayout()
        self.clear_chain_btn = QPushButton("Clear Chain")
        self.save_chain_btn = QPushButton("Save Chain")
        chain_btns.addWidget(self.clear_chain_btn)
        chain_btns.addWidget(self.save_chain_btn)
        chain_layout.addLayout(chain_btns)
        right_layout.addWidget(chain_box, stretch=1)

        log_box = QGroupBox("Event Log")
        log_layout = QVBoxLayout(log_box)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(140)
        log_layout.addWidget(self.log_edit)
        right_layout.addWidget(log_box)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, stretch=1)

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self._on_refresh)
        self.import_button.clicked.connect(self._on_import)
        self.export_button.clicked.connect(self._on_export)
        self.test_all_button.clicked.connect(self._on_test_all)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.clear_chain_btn.clicked.connect(self.chain_list.clear)
        self.save_chain_btn.clicked.connect(self._on_save_chain)

    # ----------------------------------------------------- Pool accessors

    def _get_pool(self) -> Any:
        if self._pool is None:
            try:
                from proxy.proxy_pool import ProxyPool
                self._pool = ProxyPool()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ProxyPool not available: %s", exc)
                self._pool = None
        return self._pool

    # ----------------------------------------------------- Refresh / test

    def _on_refresh(self) -> None:
        pool = self._get_pool()
        if pool is None:
            self._log("ProxyPool unavailable — cannot refresh.")
            return
        self._cancel_requested = False
        self.progress_bar.setValue(0)
        self.refresh_started.emit()
        self._log("Refreshing proxy pool…")

        try:
            from utils.workers import Worker  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("utils.workers.Worker not available, running sync: %s", exc)
            Worker = None  # type: ignore

        def _work() -> Any:
            return pool.refresh()

        if Worker is None:
            try:
                proxies = _work()
                self._populate_table(proxies)
            except Exception as exc:  # noqa: BLE001
                self._log(f"Refresh failed: {exc}")
            self.refresh_finished.emit()
            return

        self._worker = Worker(_work)
        for sig_name, slot in (
            ("progress", self._on_progress),
            ("result", lambda r: self._populate_table(r)),
            ("error", lambda e: self._log(f"Refresh failed: {e}")),
            ("finished", lambda *_: self._on_refresh_done()),
        ):
            sig = getattr(self._worker, sig_name, None)
            if sig is not None:
                try:
                    sig.connect(slot)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Could not connect %s: %s", sig_name, exc)
        try:
            self._worker.start()
        except Exception as exc:  # noqa: BLE001
            self._log(f"Failed to start refresh worker: {exc}")

    def _on_progress(self, value: Any) -> None:
        if isinstance(value, int):
            self.progress_bar.setValue(value)
        elif isinstance(value, (tuple, list)) and value:
            cur = value[0]
            total = value[1] if len(value) > 1 else 0
            stage = value[2] if len(value) > 2 else ""
            pct = int(100 * cur / total) if total else 0
            self.progress_bar.setValue(pct)
            if stage:
                self._log(f"{stage} ({cur}/{total})…")

    def _on_refresh_done(self) -> None:
        self.progress_bar.setValue(100)
        self._last_refresh = time.time()
        self.card_refresh.set_value(time.strftime("%H:%M:%S", time.localtime(self._last_refresh)))
        self.refresh_finished.emit()

    def _on_test_all(self) -> None:
        pool = self._get_pool()
        if pool is None:
            self._log("ProxyPool unavailable — cannot test.")
            return
        self._log("Testing all proxies…")

        try:
            from utils.workers import Worker  # type: ignore
        except Exception as exc:  # noqa: BLE001
            logger.warning("utils.workers.Worker not available, running sync: %s", exc)
            Worker = None  # type: ignore

        def _work() -> Any:
            return pool.health_check_all()

        if Worker is None:
            try:
                results = _work()
                self._apply_test_results(results)
            except Exception as exc:  # noqa: BLE001
                self._log(f"Test failed: {exc}")
            return

        self._worker = Worker(_work)
        for sig_name, slot in (
            ("result", lambda r: self._apply_test_results(r)),
            ("error", lambda e: self._log(f"Test failed: {e}")),
        ):
            sig = getattr(self._worker, sig_name, None)
            if sig is not None:
                try:
                    sig.connect(slot)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Could not connect %s: %s", sig_name, exc)
        try:
            self._worker.start()
        except Exception as exc:  # noqa: BLE001
            self._log(f"Failed to start test worker: {exc}")

    # ----------------------------------------------------- Table population

    def _populate_table(self, proxies: Any) -> None:
        if proxies is None:
            return
        rows: List[Dict[str, Any]] = []
        if isinstance(proxies, list):
            rows = [p for p in proxies if isinstance(p, dict)]
        elif isinstance(proxies, dict) and "proxies" in proxies:
            rows = [p for p in proxies["proxies"] if isinstance(p, dict)]

        self.table.setRowCount(len(rows))
        total = len(rows)
        healthy = 0
        latencies: List[float] = []
        for r, proxy in enumerate(rows):
            host = str(proxy.get("host", ""))
            port = str(proxy.get("port", ""))
            protocol = str(proxy.get("protocol", ""))
            country = str(proxy.get("country", ""))
            anonymity = str(proxy.get("anonymity", ""))
            latency = proxy.get("latency_ms", proxy.get("latency", 0))
            success = proxy.get("success_rate", proxy.get("success", 0))
            last_check = str(proxy.get("last_check", ""))
            cells = [host, port, protocol, country, anonymity,
                     str(latency), str(success), last_check, ""]
            for c, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if c == 5 and isinstance(latency, (int, float)):
                    if latency < 200:
                        item.setForeground(QColor("#2ca02c"))
                    elif latency < 800:
                        item.setForeground(QColor("#ff7f0e"))
                    else:
                        item.setForeground(QColor("#d62728"))
                self.table.setItem(r, c, item)
            if isinstance(latency, (int, float)) and latency > 0:
                latencies.append(float(latency))
                healthy += 1

        self.card_total.set_value(str(total))
        self.card_healthy.set_value(str(healthy))
        avg = (sum(latencies) / len(latencies)) if latencies else 0
        self.card_latency.set_value(f"{avg:.0f} ms" if avg else "—")
        if self._last_refresh == 0.0:
            self._last_refresh = time.time()
            self.card_refresh.set_value(
                time.strftime("%H:%M:%S", time.localtime(self._last_refresh))
            )

    def _apply_test_results(self, results: Any) -> None:
        if not isinstance(results, dict):
            return
        # results: {host:port -> {latency_ms, success_rate, last_check}}
        for r in range(self.table.rowCount()):
            host_item = self.table.item(r, 0)
            port_item = self.table.item(r, 1)
            if host_item is None or port_item is None:
                continue
            key = f"{host_item.text()}:{port_item.text()}"
            info = results.get(key)
            if not info:
                continue
            if "latency_ms" in info:
                self.table.setItem(r, 5, QTableWidgetItem(str(info["latency_ms"])))
            if "success_rate" in info:
                self.table.setItem(r, 6, QTableWidgetItem(str(info["success_rate"])))
            if "last_check" in info:
                self.table.setItem(r, 7, QTableWidgetItem(str(info["last_check"])))
            self.proxy_tested.emit(key, info)

    # ----------------------------------------------------- Context menu

    def _on_context_menu(self, pos: Any) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        host_item = self.table.item(row, 0)
        if host_item is None:
            return
        host = host_item.text()
        port_item = self.table.item(row, 1)
        port = port_item.text() if port_item else ""

        menu = QMenu(self)
        test_action = QAction("Test Now", self)
        add_chain_action = QAction("Add to Chain", self)
        ban_action = QAction("Ban", self)
        remove_action = QAction("Remove", self)
        menu.addAction(test_action)
        menu.addAction(add_chain_action)
        menu.addSeparator()
        menu.addAction(ban_action)
        menu.addAction(remove_action)
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == test_action:
            self._test_one(host, port)
        elif chosen == add_chain_action:
            self.chain_list.addItem(f"{host}:{port}")
        elif chosen == ban_action:
            self._ban_proxy(host, port)
        elif chosen == remove_action:
            self.table.removeRow(row)
            self._log(f"Removed {host}:{port}")

    def _test_one(self, host: str, port: str) -> None:
        pool = self._get_pool()
        if pool is None:
            self._log("ProxyPool unavailable.")
            return
        try:
            result = pool.health_check(f"{host}:{port}")
            self._log(f"Tested {host}:{port} → {result}")
            self.proxy_tested.emit(f"{host}:{port}", result or {})
        except Exception as exc:  # noqa: BLE001
            self._log(f"Test error: {exc}")

    def _ban_proxy(self, host: str, port: str) -> None:
        pool = self._get_pool()
        if pool is None:
            return
        try:
            pool.ban(f"{host}:{port}")
            self._log(f"Banned {host}:{port}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"Ban error: {exc}")

    # ----------------------------------------------------- Import / Export

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Proxies", "", "JSON / CSV / TXT (*.json *.csv *.txt)"
        )
        if not path:
            return
        pool = self._get_pool()
        if pool is None:
            self._log("ProxyPool unavailable — cannot import.")
            return
        try:
            proxies = pool.import_from(path)
            self._populate_table(proxies)
            self._log(f"Imported {len(proxies) if proxies else 0} proxies from {path}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"Import error: {exc}")

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Proxies", "proxies.json", "JSON file (*.json)"
        )
        if not path:
            return
        proxies: List[Dict[str, Any]] = []
        for r in range(self.table.rowCount()):
            proxy: Dict[str, Any] = {}
            for c, key in enumerate(PROXY_COLUMNS[:-1]):  # skip "Actions"
                item = self.table.item(r, c)
                proxy[key.lower().replace(" ", "_").replace("_(ms)", "_ms")] = (
                    item.text() if item is not None else ""
                )
            proxies.append(proxy)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(proxies, fh, ensure_ascii=False, indent=2)
            self._log(f"Exported {len(proxies)} proxies to {path}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"Export error: {exc}")

    def _on_save_chain(self) -> None:
        items: List[str] = []
        for i in range(self.chain_list.count()):
            item = self.chain_list.item(i)
            if item is not None:
                items.append(item.text())
        if not items:
            self._log("Chain is empty — nothing to save.")
            return
        strategy = self.strategy_combo.currentText()
        self._log(f"Saved chain ({strategy}): {' → '.join(items)}")
        pool = self._get_pool()
        if pool is not None:
            try:
                pool.set_chain(items, strategy=strategy)
            except Exception as exc:  # noqa: BLE001
                self._log(f"Chain save error: {exc}")

    # ----------------------------------------------------- Logging

    def _log(self, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_edit.appendPlainText(f"[{ts}] {message}")
