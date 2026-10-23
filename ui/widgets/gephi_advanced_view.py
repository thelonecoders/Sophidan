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
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
    QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from ui.modern_theme import ModernTheme

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

        # Status line — surfaces filter/export outcomes to the user
        # (previously these failures were only visible in the logs).
        self.status_label = QLabel("Ready.", self)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            f"color:{ModernTheme.DARK_TEXT_MUTED}; font-size:8pt;")
        outer.addWidget(self.status_label)

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
    def _set_status(self, message: str, is_error: bool = False) -> None:
        """Show a user-visible status/error line at the bottom of the view."""
        if hasattr(self, "status_label") and self.status_label is not None:
            self.status_label.setStyleSheet(
                f"color:{ModernTheme.DANGER if is_error else ModernTheme.DARK_TEXT_MUTED}; "
                "font-size:8pt;")
            self.status_label.setText(message)
        if is_error:
            logger.error("%s", message)
        else:
            logger.info("%s", message)

    def _on_add_filter(self) -> None:
        item = self.filter_list.currentItem()
        if item is None:
            return
        QListWidgetItem(item.text(), self.filter_chain)

    def _on_remove_filter(self) -> None:
        row = self.filter_chain.currentRow()
        if row >= 0:
            self.filter_chain.takeItem(row)

    @staticmethod
    def _filter_args(name: str, graph: Any) -> Optional[tuple]:
        """Derive the constructor arguments for ``name`` from ``graph``.

        Several filters need graph-derived arguments and previously
        received none (``EgoNetworkFilter(ego_node=None)`` wiped the view
        to an empty graph; ``PartitionFilter()`` / ``TimeRangeFilter()``
        raised TypeError and silently no-oped the chain).  Returns
        ``None`` when the filter cannot be constructed from this graph —
        the caller surfaces a visible status and skips it.
        """
        if graph is None or graph.number_of_nodes() == 0:
            return None
        if name == "EgoNetwork":
            # Pick the highest-degree node as the ego centre.
            ego = max(graph.nodes(), key=lambda n: graph.degree(n))
            return (ego, 1)
        if name == "Partition":
            # Categorical node attribute present on most nodes.
            for attr in ("community", "partition", "cluster", "component",
                         "source", "year"):
                values = [d.get(attr) for _, d in graph.nodes(data=True)
                          if d.get(attr) is not None]
                if len(values) >= max(1, graph.number_of_nodes() // 2):
                    # Restrict to the most frequent value so the result
                    # stays a meaningful sub-view rather than everything.
                    top = max(set(values), key=values.count)
                    return (attr, [top])
            return None
        if name == "TimeRange":
            years = []
            for _, d in graph.nodes(data=True):
                val = d.get("year", d.get("time", None))
                if isinstance(val, (list, tuple, set)):
                    years.extend(int(v) for v in val
                                 if isinstance(v, (int, float)))
                elif isinstance(val, (int, float)):
                    years.append(int(val))
                elif isinstance(val, dict):
                    first = val.get("first_year")
                    if isinstance(first, (int, float)):
                        years.append(int(first))
            if not years:
                return None
            return (min(years), max(years), "year")
        return ()

    def _on_apply_filters(self) -> None:
        """Walk the active filter chain and apply each filter in turn."""
        if self._graph is None:
            self._set_status("No graph bound — load a graph before applying filters.",
                             is_error=True)
            return
        try:
            from gephi_viz.filters import (
                DegreeRangeFilter, WeightRangeFilter, GiantComponentFilter,
                KCoreFilter, EgoNetworkFilter, PartitionFilter, TimeRangeFilter,
                FilterChain,
            )
            factories = {
                "DegreeRange": lambda: DegreeRangeFilter(min_degree=1),
                "WeightRange": lambda: WeightRangeFilter(min_weight=0.5),
                "GiantComponent": lambda: GiantComponentFilter(),
                "KCore": lambda: KCoreFilter(k=2),
                "EgoNetwork": lambda: EgoNetworkFilter(*args),
                "Partition": lambda: PartitionFilter(*args),
                "TimeRange": lambda: TimeRangeFilter(*args),
            }
            chain = FilterChain()
            skipped: List[str] = []
            applied: List[str] = []
            for i in range(self.filter_chain.count()):
                name = self.filter_chain.item(i).text()
                if name not in factories:
                    continue
                args = self._filter_args(name, self._graph) or ()
                if name in ("EgoNetwork", "Partition", "TimeRange") and not args:
                    skipped.append(name)
                    continue
                try:
                    chain.add_filter(factories[name]())
                    applied.append(name)
                except TypeError:
                    skipped.append(name)
            before = self._graph.number_of_nodes()
            filtered = chain.apply(self._graph)
            self._graph = filtered
            if self._canvas is not None:
                self._canvas.set_graph(filtered)
            msg = (f"Applied {len(applied)} filter(s): "
                   f"{before} → {filtered.number_of_nodes()} nodes.")
            if skipped:
                msg += (f" Skipped (needs graph attributes this graph "
                        f"does not carry): {', '.join(skipped)}.")
            self._set_status(msg, is_error=bool(skipped and not applied))
        except Exception as exc:
            logger.exception("Filter chain failed: %s", exc)
            self._set_status(f"Filter chain failed: {exc}", is_error=True)

    def _on_compute_stats(self) -> None:
        """Run :class:`NetworkStatistics.compute_all` and dump to the panel."""
        if self._graph is None:
            self._set_status("No graph bound — run a search and open the "
                             "network page with data first.", is_error=True)
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
            self._set_status(f"Layout saved to {path}")
        except OSError as exc:
            logger.exception("Layout save failed.")
            self._set_status(f"Layout save failed: {exc}", is_error=True)

    def _on_export(self, fmt: str) -> None:
        if self._graph is None:
            self._set_status(f"No graph bound — cannot export {fmt.upper()}.",
                             is_error=True)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {fmt.upper()}", f"network.{fmt}",
            f"{fmt.upper()} (*.{fmt})",
        )
        if not path:
            return
        # NOTE: the canvas' own ``_export`` deliberately is NOT used here —
        # it ignores the user-chosen path and opens a second file dialog.
        try:
            from gephi_viz.preview import PreviewRenderer
            renderer = PreviewRenderer(self._graph)
            if fmt == "png":
                renderer.export_png(path)
            elif fmt == "svg":
                renderer.export_svg(path)
            elif fmt == "pdf":
                renderer.export_pdf(path)
            else:
                raise ValueError(f"Unsupported export format: {fmt}")
            self._set_status(f"Network exported to {path}")
        except Exception as exc:
            logger.exception("Export %s failed: %s", fmt, exc)
            self._set_status(f"Export {fmt.upper()} failed: {exc}", is_error=True)

    def _on_export_gexf(self) -> None:
        if self._graph is None:
            self._set_status("No graph bound — cannot export GEXF.", is_error=True)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export to Gephi (.gexf)",
                                              "network.gexf", "GEXF (*.gexf)")
        if not path:
            return
        try:
            from networkx_pro.graph_io import GraphIO
            GraphIO.write_gexf(self._graph, path)
            self._set_status(f"GEXF saved to {path}")
        except Exception as exc:
            logger.exception("GEXF export failed: %s", exc)
            self._set_status(f"GEXF export failed: {exc}", is_error=True)
