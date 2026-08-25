"""Project explorer widget.

Provides :class:`ProjectExplorer` — a three-pane project manager:
  * Left: project list (tree view with name / paper count / last modified)
          plus New / Import / Export buttons.
  * Center: project dashboard (mini data view + recent snapshots +
            comparison chart with another project).
  * Right: project actions panel (Rename / Description / Color /
           Snapshot / Compare With… / Delete).
  * Bottom: snapshots timeline (clickable to restore).

Uses ``project_management.project_manager.ProjectManager`` (lazy import).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QColor, QFont
from qtpy.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


class ProjectExplorer(QWidget):
    """Project management widget.

    Lets the user create, import, export, rename, color-code, snapshot,
    compare and delete research projects. Backed by
    ``project_management.project_manager.ProjectManager`` (lazy import).
    """

    project_selected = Signal(str)
    snapshot_restored = Signal(str, str)  # (project_id, snapshot_id)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize the explorer with empty state."""
        super().__init__(parent)
        self._manager: Optional[Any] = None
        self._current_project_id: Optional[str] = None
        self._snapshots: List[Dict[str, Any]] = []

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ---- Left: project list
        left_box = QGroupBox("Projects")
        left_layout = QVBoxLayout(left_box)
        left_btns = QHBoxLayout()
        self.new_button = QPushButton("New Project")
        self.import_button = QPushButton("Import…")
        self.export_button = QPushButton("Export…")
        left_btns.addWidget(self.new_button)
        left_btns.addWidget(self.import_button)
        left_btns.addWidget(self.export_button)
        left_layout.addLayout(left_btns)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Papers", "Modified"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        left_layout.addWidget(self.tree, stretch=1)
        splitter.addWidget(left_box)

        # ---- Center: dashboard
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

        self.dashboard_title = QLabel("No project selected")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.dashboard_title.setFont(f)
        center_layout.addWidget(self.dashboard_title)

        # Mini data view (papers table)
        papers_box = QGroupBox("Papers")
        papers_layout = QVBoxLayout(papers_box)
        self.papers_table = QTableWidget(0, 0)
        self.papers_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.papers_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        papers_layout.addWidget(self.papers_table)
        center_layout.addWidget(papers_box, stretch=1)

        # Comparison chart (matplotlib embedded)
        comp_box = QGroupBox("Comparison Chart")
        comp_layout = QVBoxLayout(comp_box)
        comp_top = QHBoxLayout()
        comp_top.addWidget(QLabel("Compare with:"))
        self.compare_combo = QComboBox()
        self.compare_combo.addItem("—")
        comp_top.addWidget(self.compare_combo, stretch=1)
        comp_layout.addLayout(comp_top)
        self._comp_figure = None
        self._comp_canvas = None
        self._build_comp_canvas(comp_layout)
        center_layout.addWidget(comp_box)
        splitter.addWidget(center)

        # ---- Right: actions panel
        right_box = QGroupBox("Project Actions")
        right_layout = QVBoxLayout(right_box)

        form = QFormLayout()
        self.rename_edit = QLineEdit()
        self.rename_edit.setPlaceholderText("New name…")
        form.addRow("Rename:", self.rename_edit)
        self.color_button = QPushButton("Pick color…")
        form.addRow("Color:", self.color_button)
        right_layout.addLayout(form)

        right_layout.addWidget(QLabel("Description:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setMaximumHeight(80)
        right_layout.addWidget(self.desc_edit)

        self.rename_apply = QPushButton("Apply Rename")
        self.save_desc = QPushButton("Save Description")
        self.set_color = QPushButton("Apply Color")
        self.snapshot_button = QPushButton("Create Snapshot")
        self.compare_button = QPushButton("Compare With…")
        self.delete_button = QPushButton("Delete Project")
        self.delete_button.setStyleSheet("color:#d62728;")
        for btn in (self.rename_apply, self.save_desc, self.set_color,
                    self.snapshot_button, self.compare_button, self.delete_button):
            right_layout.addWidget(btn)
        right_layout.addStretch()
        splitter.addWidget(right_box)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter, stretch=1)

        # ---- Bottom: snapshots timeline
        snap_box = QGroupBox("Snapshots Timeline")
        snap_layout = QVBoxLayout(snap_box)
        self.snapshots_list = QListWidget()
        self.snapshots_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        snap_layout.addWidget(self.snapshots_list)
        outer.addWidget(snap_box)

    def _build_comp_canvas(self, layout: QVBoxLayout) -> None:
        """Build embedded matplotlib canvas for the comparison chart."""
        _configure_matplotlib()
        import matplotlib.pyplot as plt  # noqa: WPS433 lazy
        from matplotlib.backends.backend_qt5agg import (  # noqa: WPS433 lazy
            FigureCanvasQTAgg,
        )
        self._comp_figure = plt.Figure(constrained_layout=True)
        self._comp_ax = self._comp_figure.add_subplot(111)
        self._comp_ax.set_axis_off()
        self._comp_ax.text(0.5, 0.5, "Select two projects to compare",
                           ha="center", va="center",
                           transform=self._comp_ax.transAxes, color="#888")
        self._comp_canvas = FigureCanvasQTAgg(self._comp_figure)
        layout.addWidget(self._comp_canvas)

    def _connect_signals(self) -> None:
        self.tree.itemSelectionChanged.connect(self._on_project_selected)
        self.new_button.clicked.connect(self._on_new_project)
        self.import_button.clicked.connect(self._on_import_project)
        self.export_button.clicked.connect(self._on_export_project)
        self.rename_apply.clicked.connect(self._on_rename)
        self.save_desc.clicked.connect(self._on_save_desc)
        self.color_button.clicked.connect(self._on_pick_color)
        self.set_color.clicked.connect(self._on_apply_color)
        self.snapshot_button.clicked.connect(self._on_create_snapshot)
        self.compare_button.clicked.connect(self._on_compare)
        self.delete_button.clicked.connect(self._on_delete)
        self.compare_combo.currentIndexChanged.connect(self._refresh_comparison_chart)
        self.snapshots_list.itemDoubleClicked.connect(self._on_restore_snapshot)

    # --------------------------------------------------------- Manager

    def _get_manager(self) -> Any:
        if self._manager is None:
            try:
                from project_management.project_manager import ProjectManager
                self._manager = ProjectManager()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ProjectManager not available: %s", exc)
                self._manager = None
        return self._manager

    # --------------------------------------------------------- Project list

    def refresh(self) -> None:
        """Reload the project list from the ProjectManager."""
        manager = self._get_manager()
        if manager is None:
            return
        try:
            projects = manager.list_projects()
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_projects failed: %s", exc)
            projects = []
        self.tree.clear()
        self.compare_combo.clear()
        self.compare_combo.addItem("—")
        for p in projects:
            name = str(p.get("name", p.get("id", "?")))
            count = str(p.get("paper_count", p.get("papers", 0)))
            modified = str(p.get("last_modified", p.get("modified", "")))
            item = QTreeWidgetItem([name, count, modified])
            item.setData(0, Qt.ItemDataRole.UserRole, p)
            color = p.get("color")
            if color:
                item.setForeground(0, QColor(color))
            self.tree.addTopLevelItem(item)
            self.compare_combo.addItem(name, p)

    def _on_project_selected(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        item = items[0]
        project = item.data(0, Qt.ItemDataRole.UserRole) or {}
        self._current_project_id = project.get("id") or project.get("name")
        self.dashboard_title.setText(str(project.get("name", "(unnamed)")))
        self.desc_edit.setPlainText(str(project.get("description", "")))
        self.project_selected.emit(str(self._current_project_id or ""))
        self._load_project_papers(project)
        self._load_snapshots(project)

    def _load_project_papers(self, project: Dict[str, Any]) -> None:
        manager = self._get_manager()
        if manager is None:
            return
        try:
            papers = manager.list_papers(project.get("id") or project.get("name"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_papers failed: %s", exc)
            papers = []
        if not papers:
            self.papers_table.setRowCount(0)
            self.papers_table.setColumnCount(0)
            return
        headers = list(papers[0].keys()) if papers else []
        self.papers_table.setRowCount(len(papers))
        self.papers_table.setColumnCount(len(headers))
        self.papers_table.setHorizontalHeaderLabels(headers)
        for r, paper in enumerate(papers):
            for c, key in enumerate(headers):
                self.papers_table.setItem(
                    r, c, QTableWidgetItem(str(paper.get(key, "")))
                )

    def _load_snapshots(self, project: Dict[str, Any]) -> None:
        manager = self._get_manager()
        if manager is None:
            return
        try:
            snapshots = manager.list_snapshots(project.get("id") or project.get("name"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_snapshots failed: %s", exc)
            snapshots = []
        self._snapshots = list(snapshots) if snapshots else []
        self.snapshots_list.clear()
        for snap in self._snapshots:
            label = f"{snap.get('created', '')} — {snap.get('label', 'snapshot')}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, snap)
            self.snapshots_list.addItem(item)

    # --------------------------------------------------------- Actions

    def _on_new_project(self) -> None:
        manager = self._get_manager()
        if manager is None:
            return
        try:
            new = manager.create_project()
            self.refresh()
            if new:
                self.project_selected.emit(str(new.get("id", "")))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "New Project", f"Failed: {exc}")

    def _on_import_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Project", "", "Project archive (*.zip *.json)"
        )
        if not path:
            return
        manager = self._get_manager()
        if manager is None:
            return
        try:
            manager.import_project(path)
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Import Project", f"Failed: {exc}")

    def _on_export_project(self) -> None:
        if self._current_project_id is None:
            QMessageBox.information(self, "Export Project", "Select a project first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Project", "project.zip", "Project archive (*.zip *.json)"
        )
        if not path:
            return
        manager = self._get_manager()
        if manager is None:
            return
        try:
            manager.export_project(self._current_project_id, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export Project", f"Failed: {exc}")

    def _on_rename(self) -> None:
        if self._current_project_id is None:
            return
        new_name = self.rename_edit.text().strip()
        if not new_name:
            return
        manager = self._get_manager()
        if manager is None:
            return
        try:
            manager.rename_project(self._current_project_id, new_name)
            self.refresh()
            self.rename_edit.clear()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Rename", f"Failed: {exc}")

    def _on_save_desc(self) -> None:
        if self._current_project_id is None:
            return
        manager = self._get_manager()
        if manager is None:
            return
        try:
            manager.set_description(self._current_project_id, self.desc_edit.toPlainText())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Description", f"Failed: {exc}")

    def _on_pick_color(self) -> None:
        color = QColorDialog.getColor()
        if color.isValid():
            self._pending_color = color.name()

    def _on_apply_color(self) -> None:
        if self._current_project_id is None:
            return
        color = getattr(self, "_pending_color", None)
        if not color:
            return
        manager = self._get_manager()
        if manager is None:
            return
        try:
            manager.set_color(self._current_project_id, color)
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Color", f"Failed: {exc}")

    def _on_create_snapshot(self) -> None:
        if self._current_project_id is None:
            return
        manager = self._get_manager()
        if manager is None:
            return
        try:
            snap = manager.create_snapshot(self._current_project_id, label="manual")
            if snap:
                self._snapshots.insert(0, snap)
                self._load_snapshots({"id": self._current_project_id})
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Snapshot", f"Failed: {exc}")

    def _on_compare(self) -> None:
        if self._current_project_id is None:
            return
        # Use the combo to pick the other project.
        idx = self.compare_combo.currentIndex()
        if idx <= 0:
            QMessageBox.information(self, "Compare", "Pick another project to compare with.")
            return
        self._refresh_comparison_chart()

    def _on_delete(self) -> None:
        if self._current_project_id is None:
            return
        confirm = QMessageBox.question(
            self, "Delete Project",
            f"Delete project '{self._current_project_id}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        manager = self._get_manager()
        if manager is None:
            return
        try:
            manager.delete_project(self._current_project_id)
            self._current_project_id = None
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Delete", f"Failed: {exc}")

    def _on_restore_snapshot(self, item: QListWidgetItem) -> None:
        snap = item.data(Qt.ItemDataRole.UserRole)
        if not snap or self._current_project_id is None:
            return
        manager = self._get_manager()
        if manager is None:
            return
        try:
            manager.restore_snapshot(
                self._current_project_id, snap.get("id", snap.get("label", ""))
            )
            self.snapshot_restored.emit(
                self._current_project_id, str(snap.get("id", ""))
            )
            self._on_project_selected()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Restore Snapshot", f"Failed: {exc}")

    # --------------------------------------------------------- Comparison chart

    def _refresh_comparison_chart(self) -> None:
        if self._comp_ax is None:
            return
        if self._current_project_id is None:
            return
        idx = self.compare_combo.currentIndex()
        if idx <= 0:
            self._comp_ax.clear()
            self._comp_ax.set_axis_off()
            self._comp_ax.text(0.5, 0.5, "Select another project to compare",
                               ha="center", va="center",
                               transform=self._comp_ax.transAxes, color="#888")
            self._comp_canvas.draw_idle()
            return
        other = self.compare_combo.itemData(idx) or {}
        manager = self._get_manager()
        if manager is None:
            return
        try:
            series_a = manager.yearly_counts(self._current_project_id)
            series_b = manager.yearly_counts(other.get("id") or other.get("name"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("yearly_counts failed: %s", exc)
            series_a, series_b = {}, {}
        self._comp_ax.clear()
        if series_a:
            years = sorted(series_a.keys())
            self._comp_ax.bar(
                [y - 0.2 for y in years], [series_a[y] for y in years],
                width=0.4, color="#007acc", label=self._current_project_id,
            )
        if series_b:
            years = sorted(series_b.keys())
            self._comp_ax.bar(
                [y + 0.2 for y in years], [series_b[y] for y in years],
                width=0.4, color="#d62728", label=str(other.get("name", "")),
            )
        self._comp_ax.set_xlabel("Year")
        self._comp_ax.set_ylabel("Papers")
        self._comp_ax.legend()
        self._comp_canvas.draw_idle()
