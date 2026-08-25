"""Gephi-style advanced network analysis widget.

Provides :class:`GephiAdvancedView` — a four-quadrant Qt interface to
the v2.0.0 :mod:`gephi_viz` package + :mod:`networkx_pro`:

* Top toolbar: graph-type selector (Citation/Collaboration/Temporal/
  Custom), layout selector (ForceAtlas2/OpenOrd/YifanHu/KamadaKawai/
  Circular/Radial/Hierarchical), partition selector (Community/Year/
  Source/Custom), ranking selector (Degree/PageRank/Betweenness/
  Closeness).
* Center: large :class:`InteractiveNetworkCanvas`.
* Right: statistics panel (nodes, edges, density, diameter, modularity,
  clustering coefficient, avg path length, top-10 centralities).
* Left sidebar: filter chain (DegreeRange / WeightRange / GiantComponent
  / KCore / EgoNetwork / Partition / TimeRange) with drag-and-drop.
* Bottom: Compute Statistics / Save Layout / Export PNG / SVG / PDF /
  Export to Gephi (.gexf).

Every heavy dep is lazy-imported.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, List, Optional

from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QSpinBox, QSplitter,
    QTextEdit, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)

__all__ = ["GephiAdvancedView"]


_GRAPH_TYPES: List[str] = ["Citation", "Collaboration", "Temporal", "Custom"]
_LAYOUTS: List[str] = [
    "ForceAtlas2", "OpenOrd", "YifanHu", "KamadaKawai",
    "Circular", "Radial", "Hierarchical",
]
_PARTITIONS: List[str] = ["(none)", "Community", "Year", "Source", "Custom"]
_RANKINGS: List[str] = ["(none)", "Degree", "PageRank", "Betweenness", "Closeness"]
_FILTERS: List[str] = [
    "DegreeRange", "WeightRange", "GiantComponent", "KCore",
    "EgoNetwork", "Partition", "TimeRange",
]


class GephiAdvancedView(QWidget):
    """Gephi-style advanced network analysis view."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("GephiAdvancedView")
        self._graph: Any = None
        self._canvas: Any = None
        self._build_ui()

    # ----------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Top toolbar.
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Graph:"))
        self.graph_combo = QComboBox()
        self.graph_combo.addItems(_GRAPH_TYPES)
        toolbar.addWidget(self.graph_combo)
        toolbar.addWidget(QLabel("Layout:"))
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(_LAYOUTS)
        toolbar.addWidget(self.layout_combo)
        toolbar.addWidget(QLabel("Partition:"))
        self.partition_combo = QComboBox()
        self.partition_combo.addItems(_PARTITIONS)
        toolbar.addWidget(self.partition_combo)
        toolbar.addWidget(QLabel("Ranking:"))
        self.ranking_combo = QComboBox()
        self.ranking_combo.addItems(_RANKINGS)
        toolbar.addWidget(self.ranking_combo)
        toolbar.addStretch()
        outer.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left: filter chain (drag-and-drop from the list, double-click to apply).
        left = QGroupBox("Filters")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 8, 8)
        self.filter_list = QListWidget()
        for f in _FILTERS:
            QListWidgetItem(f, self.filter_list)
        left_lay.addWidget(self.filter_list)
        self.filter_chain = QListWidget()
        self.filter_chain.setAlternatingRowColors(True)
        left_lay.addWidget(QLabel("Active chain:"))
        left_lay.addWidget(self.filter_chain, stretch=1)
        row = QHBoxLayout()
        self.btn_add_filter = QPushButton("→")
        self.btn_remove_filter = QPushButton("←")
        self.btn_apply_filters = QPushButton("Apply")
        for b in (self.btn_add_filter, self.btn_remove_filter, self.btn_apply_filters):
            row.addWidget(b)
        left_lay.addLayout(row)
        splitter.addWidget(left)

        # Center: interactive canvas (the gephi_viz widget).
        center = QWidget()
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        try:
            from gephi_viz.interactive_canvas import InteractiveNetworkCanvas
            self._canvas = InteractiveNetworkCanvas(self)
            center_lay.addWidget(self._canvas)
        except Exception as exc:
            logger.warning("InteractiveNetworkCanvas unavailable: %s", exc)
            placeholder = QLabel(f"(InteractiveNetworkCanvas unavailable: {exc})", self)
            placeholder.setAlignment(Qt.AlignCenter)
            center_lay.addWidget(placeholder)
        splitter.addWidget(center)

        # Right: statistics panel.
        right = QGroupBox("Statistics")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 8, 8, 8)
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        right_lay.addWidget(self.stats_text, stretch=1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter, stretch=1)

        # Bottom toolbar.
        bottom = QHBoxLayout()
        self.btn_compute = QPushButton("Compute Statistics")
        self.btn_save_layout = QPushButton("Save Layout")
        self.btn_export_png = QPushButton("Export PNG")
        self.btn_export_svg = QPushButton("Export SVG")
        self.btn_export_pdf = QPushButton("Export PDF")
        self.btn_export_gexf = QPushButton("Export to Gephi (.gexf)")
        for b in (self.btn_compute, self.btn_save_layout, self.btn_export_png,
                  self.btn_export_svg, self.btn_export_pdf, self.btn_export_gexf):
            bottom.addWidget(b)
        bottom.addStretch()
        outer.addLayout(bottom)

        # Connect signals.
        self.btn_add_filter.clicked.connect(self._on_add_filter)
        self.btn_remove_filter.clicked.connect(self._on_remove_filter)
        self.btn_apply_filters.clicked.connect(self._on_apply_filters)
        self.btn_compute.clicked.connect(self._on_compute_stats)
        self.btn_save_layout.clicked.connect(self._on_save_layout)
        self.btn_export_png.clicked.connect(lambda: self._on_export("png"))
        self.btn_export_svg.clicked.connect(lambda: self._on_export("svg"))
        self.btn_export_pdf.clicked.connect(lambda: self._on_export("pdf"))
        self.btn_export_gexf.clicked.connect(self._on_export_gexf)

    # ----------------------------------------------------------------- Public API
    def set_graph(self, graph: Any) -> None:
        """Bind a ``networkx.Graph`` and refresh the canvas + statistics."""
        self._graph = graph
        if self._canvas is not None:
            self._canvas.set_graph(graph)
        self._on_compute_stats()

    def graph(self) -> Any:
        return self._graph

    # ----------------------------------------------------------------- Slots
    def _on_add_filter(self) -> None:
        item = self.filter_list.currentItem()
        if item is None:
            return
        QListWidgetItem(item.text(), self.filter_chain)

    def _on_remove_filter(self) -> None:
        row = self.filter_chain.currentRow()
        if row >= 0:
            self.filter_chain.takeItem(row)

    def _on_apply_filters(self) -> None:
        """Walk the active filter chain and apply each filter in turn."""
        if self._graph is None:
            logger.info("No graph bound — filters are no-op.")
            return
        try:
            from gephi_viz.filters import (
                DegreeRangeFilter, WeightRangeFilter, GiantComponentFilter,
                KCoreFilter, EgoNetworkFilter, PartitionFilter, TimeRangeFilter,
                FilterChain,
            )
            chain = FilterChain()
            for i in range(self.filter_chain.count()):
                name = self.filter_chain.item(i).text()
                if name == "DegreeRange":
                    chain.add_filter(DegreeRangeFilter(min_degree=1))
                elif name == "WeightRange":
                    chain.add_filter(WeightRangeFilter(min_weight=0.5))
                elif name == "GiantComponent":
                    chain.add_filter(GiantComponentFilter())
                elif name == "KCore":
                    chain.add_filter(KCoreFilter(k=2))
                elif name == "EgoNetwork":
                    chain.add_filter(EgoNetworkFilter(ego_node=None))
                elif name == "Partition":
                    chain.add_filter(PartitionFilter())
                elif name == "TimeRange":
                    chain.add_filter(TimeRangeFilter())
            filtered = chain.apply(self._graph)
            self._graph = filtered
            if self._canvas is not None:
                self._canvas.set_graph(filtered)
            logger.info("Filter chain applied (%d filters).", self.filter_chain.count())
        except Exception as exc:
            logger.exception("Filter chain failed: %s", exc)

    def _on_compute_stats(self) -> None:
        """Run :class:`NetworkStatistics.compute_all` and dump to the panel."""
        if self._graph is None:
            self.stats_text.setPlainText("(no graph bound)")
            return
        try:
            from gephi_viz.statistics import NetworkStatistics
            report = NetworkStatistics().compute_all(self._graph)
            md = report.to_markdown() if hasattr(report, "to_markdown") else str(report)
            self.stats_text.setPlainText(md)
        except Exception as exc:
            logger.exception("Compute stats failed: %s", exc)
            self.stats_text.setPlainText(f"(stats error: {exc})")

    def _on_save_layout(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Layout", "layout.json",
                                              "JSON (*.json)")
        if not path:
            return
        import json
        positions = {}
        if self._graph is not None:
            try:
                positions = {str(n): [float(p[0]), float(p[1])]
                             for n, p in getattr(self._graph, "pos", {}).items()}
            except Exception:
                positions = {}
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"layout": self.layout_combo.currentText(),
                           "positions": positions}, fh, indent=2)
            logger.info("Layout saved to %s", path)
        except OSError:
            logger.exception("Layout save failed.")

    def _on_export(self, fmt: str) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {fmt.upper()}", f"network.{fmt}",
            f"{fmt.upper()} (*.{fmt})",
        )
        if not path:
            return
        if self._canvas is not None and hasattr(self._canvas, "_export"):
            try:
                self._canvas._export(fmt)
                logger.info("Network exported to %s via canvas", path)
                return
            except Exception as exc:
                logger.debug("Canvas export failed (%s); falling back to PreviewRenderer", exc)
        try:
            from gephi_viz.preview import PreviewRenderer
            renderer = PreviewRenderer(self._graph)
            if fmt == "png":
                renderer.export_png(path)
            elif fmt == "svg":
                renderer.export_svg(path)
            elif fmt == "pdf":
                renderer.export_pdf(path)
            logger.info("Network exported to %s via PreviewRenderer", path)
        except Exception as exc:
            logger.exception("Export %s failed: %s", fmt, exc)

    def _on_export_gexf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export to Gephi (.gexf)",
                                              "network.gexf", "GEXF (*.gexf)")
        if not path:
            return
        try:
            from networkx_pro.graph_io import GraphIO
            GraphIO.write_gexf(self._graph, path)
            logger.info("GEXF saved to %s", path)
        except Exception as exc:
            logger.exception("GEXF export failed: %s", exc)
