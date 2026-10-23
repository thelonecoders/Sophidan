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

from qtpy.QtCore import Qt, Signal
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

from ui.modern_theme import ModernTheme

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
        self.value_label.setStyleSheet(
            f"font-size:18px;font-weight:bold;color:{ModernTheme.ACCENT};")
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
        self.refresh_button.setObjectName("PrimaryBtn")
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

    @staticmethod
    def _proxy_to_dict(proxy: Any) -> Dict[str, Any]:
        """Normalise a ``Proxy`` object (or dict) to the table schema.

        The facade's ``list_proxies()`` returns dicts; the legacy pool's
        ``ProxyManager.all_proxies()`` returns :class:`Proxy` dataclasses,
        so both shapes are accepted.
        """
        if isinstance(proxy, dict):
            return proxy
        success_rate = 0
        try:
            success = int(getattr(proxy, "success_count", 0) or 0)
            fails = int(getattr(proxy, "fail_count", 0) or 0)
            total = success + fails
            success_rate = round(100.0 * success / total, 1) if total else 0
        except Exception:  # noqa: BLE001 — display only
            success_rate = 0
        last_check = getattr(proxy, "last_check", None)
        if isinstance(last_check, (int, float)) and last_check:
            last_check = time.strftime("%Y-%m-%d %H:%M",
                                       time.localtime(last_check))
        return {
            "host": getattr(proxy, "host", ""),
            "port": getattr(proxy, "port", ""),
            "protocol": getattr(proxy, "protocol", ""),
            "country": getattr(proxy, "country", ""),
            "anonymity": getattr(proxy, "anonymity", ""),
            "latency_ms": getattr(proxy, "latency_ms", 0) or 0,
            "success_rate": success_rate,
            "last_check": last_check or "",
        }

    def _list_proxies(self, pool: Any) -> Optional[List[Dict[str, Any]]]:
        """Read the pool contents via the facade, falling back to the
        legacy ``ProxyManager.all_proxies()`` when the facade method is
        not yet available."""
        list_fn = getattr(pool, "list_proxies", None)
        if callable(list_fn):
            try:
                proxies = list_fn() or []
            except Exception as exc:  # noqa: BLE001
                self._log(f"list_proxies failed: {exc}")
                return []
            return [self._proxy_to_dict(p) for p in proxies]
        manager = getattr(pool, "manager", None)
        all_fn = getattr(manager, "all_proxies", None) if manager else None
        if callable(all_fn):
            try:
                proxies = all_fn() or []
            except Exception as exc:  # noqa: BLE001
                self._log(f"all_proxies failed: {exc}")
                return []
            return [self._proxy_to_dict(p) for p in proxies]
        return None

    # ----------------------------------------------------- Refresh / test

    def _on_refresh(self) -> None:
        """Scrape fresh proxies in a background Worker.

        Uses the facade ``ProxyPool.refresh(sources, target_count,
        progress_cb)``; the pool's ``(done, total, result)`` progress
        tuples are adapted to the Worker's ``(int, str)`` channel.
        """
        pool = self._get_pool()
        if pool is None:
            self._log("ProxyPool unavailable — cannot refresh.")
            return
        self._cancel_requested = False
        self.progress_bar.setValue(0)
        self.refresh_started.emit()
        self._log("Refreshing proxy pool…")

        from utils.workers import Worker, WorkerPool

        def _work(progress_callback=None) -> Any:
            report = progress_callback or (lambda pct, msg="": None)

            def _pool_progress(done: int, total: int, result: Any = None) -> None:
                pct = int(100 * done / total) if total else 0
                report(pct, f"Health-checking proxies ({done}/{total})…")

            try:
                # Facade: refresh(sources=None, target_count=None,
                #                 progress_cb=None)
                pool.refresh(progress_cb=_pool_progress)
            except (TypeError, AttributeError):
                try:
                    # Legacy pool: refresh_pool(target_count=…,
                    # progress_cb=…) → int.
                    pool.refresh_pool(progress_cb=_pool_progress)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Proxy refresh failed.")
                    raise
            proxies = self._list_proxies(pool)
            report(100, "Done")
            return proxies

        self._worker = Worker(_work)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.result.connect(self._populate_table)
        self._worker.signals.error.connect(
            lambda e: self._log(f"Refresh failed: {e}"))
        self._worker.signals.finished.connect(self._on_refresh_done)
        WorkerPool.instance().submit(self._worker)

    def _on_progress(self, percent: int, message: str = "") -> None:
        """Worker progress callback — ``signals.progress(int, str)``."""
        self.progress_bar.setValue(int(percent))
        if message:
            self._log(str(message))

    def _on_refresh_done(self) -> None:
        self.progress_bar.setValue(100)
        self._last_refresh = time.time()
        self.card_refresh.set_value(time.strftime("%H:%M:%S", time.localtime(self._last_refresh)))
        self.refresh_finished.emit()

    def _on_test_all(self) -> None:
        """Health-check every proxy in a background Worker."""
        pool = self._get_pool()
        if pool is None:
            self._log("ProxyPool unavailable — cannot test.")
            return
        self._log("Testing all proxies…")

        from utils.workers import Worker, WorkerPool

        def _work(progress_callback=None) -> Any:
            report = progress_callback or (lambda pct, msg="": None)
            report(0, "Health check started…")
            results = pool.health_check_all()
            report(100, "Done")
            return results

        self._worker = Worker(_work)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.result.connect(self._apply_test_results)
        self._worker.signals.error.connect(
            lambda e: self._log(f"Test failed: {e}"))
        WorkerPool.instance().submit(self._worker)

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
                        item.setForeground(QColor(ModernTheme.SUCCESS))
                    elif latency < 800:
                        item.setForeground(QColor(ModernTheme.WARNING))
                    else:
                        item.setForeground(QColor(ModernTheme.DANGER))
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
        """Test a single proxy off the UI thread (facade ``test_proxy``)."""
        pool = self._get_pool()
        if pool is None:
            self._log("ProxyPool unavailable.")
            return
        addr = f"{host}:{port}"
        from utils.workers import Worker, WorkerPool

        def _work(progress_callback=None) -> Any:
            return pool.test_proxy(addr)

        worker = Worker(_work)
        worker.signals.result.connect(lambda res: self._on_one_tested(addr, res))
        worker.signals.error.connect(lambda e: self._log(f"Test error: {e}"))
        WorkerPool.instance().submit(worker)

    def _on_one_tested(self, addr: str, result: Any) -> None:
        self._log(f"Tested {addr} → {result}")
        self.proxy_tested.emit(addr, result or {})

    def _ban_proxy(self, host: str, port: str) -> None:
        pool = self._get_pool()
        if pool is None:
            return
        addr = f"{host}:{port}"
        try:
            pool.ban(addr)
            self._log(f"Banned {addr}")
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
            # Facade: import_from(sources) → list[dict]; legacy pool:
            # import_from_file(path) → int count.
            proxies: Any
            try:
                proxies = pool.import_from(path)
            except (TypeError, AttributeError):
                count = pool.import_from_file(path)
                proxies = self._list_proxies(pool)
                if isinstance(count, int) and proxies is not None:
                    self._log(f"Imported {count} proxies from {path}")
            self._populate_table(proxies)
            if proxies is not None:
                self._log(f"Import finished from {path} — "
                          f"{len(proxies) if proxies else 0} proxies listed")
        except Exception as exc:  # noqa: BLE001
            self._log(f"Import error: {exc}")
            QMessageBox.warning(self, "Import Proxies", f"Import failed:\n{exc}")

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
            except TypeError:
                try:
                    pool.set_chain(items)
                except Exception as exc:  # noqa: BLE001
                    self._log(f"Chain save error: {exc}")
            except Exception as exc:  # noqa: BLE001
                self._log(f"Chain save error: {exc}")

    # ----------------------------------------------------- Logging

    def _log(self, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_edit.appendPlainText(f"[{ts}] {message}")
