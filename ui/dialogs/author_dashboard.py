"""Author Dashboard dialog.

Provides :class:`AuthorDashboard` — a modal QDialog showing an author's
profile (name / ORCID / affiliation / photo), metric cards (h-index, total
citations, papers count, avg citations), citation timeline chart, top-cited
papers table, collaboration network graph and topic distribution chart.

The matplotlib figures use ``constrained_layout=True`` and the project-wide
``font.sans-serif`` rcParams. Uses ``FigureCanvasQTAgg`` for embedding.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from qtpy.QtCore import Qt
from qtpy.QtGui import QFont, QPixmap
from qtpy.QtWidgets import (
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


def _configure_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams."""
    import matplotlib.pyplot as plt  # lazy
    plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def calculate_h_index(citations: List[int]) -> int:
    """Compute the h-index from a list of citation counts."""
    sorted_c = sorted([c for c in citations if c >= 0], reverse=True)
    h = 0
    for i, count in enumerate(sorted_c, start=1):
        if i <= count:
            h = i
        else:
            break
    return h


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return default


class AuthorDashboard(QDialog):
    """Modal author-profile dashboard dialog.

    Args:
        author: Dict with keys ``name``, ``orcid``, ``affiliation``,
            ``photo_path`` (optional), ``publications`` (list of dicts with
            ``title``, ``authors``, ``year``, ``citations``, ``venue``,
            ``topics``).
    """

    def __init__(self, author: Dict[str, Any],
                 parent: Optional[QWidget] = None) -> None:
        """Build the dashboard from the author info dict."""
        super().__init__(parent)
        self.setWindowTitle(f"Author Dashboard — {author.get('name', '?')}")
        self.setModal(True)
        self.setMinimumSize(960, 720)
        self._author = author
        self._publications: List[Dict[str, Any]] = list(author.get("publications") or [])

        self._figure_timeline = None
        self._canvas_timeline = None
        self._ax_timeline = None
        self._figure_collab = None
        self._canvas_collab = None
        self._ax_collab = None
        self._figure_topics = None
        self._canvas_topics = None
        self._ax_topics = None

        self._build_ui()
        self._populate()

    # ----------------------------------------------------------- UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_metrics_row())

        # Splitter: charts | table
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        charts_holder = QWidget()
        charts_layout = QVBoxLayout(charts_holder)
        charts_layout.setContentsMargins(0, 0, 0, 0)

        # Two side-by-side charts: timeline + topics
        charts_row = QSplitter(Qt.Orientation.Horizontal)
        charts_row.setChildrenCollapsible(False)
        charts_row.addWidget(self._build_timeline_box())
        charts_row.addWidget(self._build_topics_box())
        charts_row.setStretchFactor(0, 2)
        charts_row.setStretchFactor(1, 1)
        charts_layout.addWidget(charts_row, stretch=1)

        charts_layout.addWidget(self._build_collab_box(), stretch=1)
        splitter.addWidget(charts_holder)

        splitter.addWidget(self._build_top_papers_box())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, stretch=1)

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

    def _build_header(self) -> QWidget:
        box = QGroupBox("Author")
        layout = QHBoxLayout(box)
        self.photo_label = QLabel()
        self.photo_label.setFixedSize(72, 72)
        self.photo_label.setStyleSheet(
            "background:#2b2b2b;border-radius:36px;border:2px solid #555;"
        )
        self.photo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_label.setText("👤")
        layout.addWidget(self.photo_label)

        info_form = QFormLayout()
        info_form.setContentsMargins(0, 0, 0, 0)
        info_form.setSpacing(4)
        self.name_label = QLabel(self._author.get("name", "Unknown"))
        f = QFont()
        f.setPointSize(15)
        f.setBold(True)
        self.name_label.setFont(f)
        info_form.addRow("Name:", self.name_label)
        self.orcid_label = QLabel(str(self._author.get("orcid", "—")))
        self.orcid_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        info_form.addRow("ORCID:", self.orcid_label)
        self.affil_label = QLabel(str(self._author.get("affiliation", "—")))
        self.affil_label.setWordWrap(True)
        info_form.addRow("Affiliation:", self.affil_label)
        layout.addLayout(info_form, stretch=1)
        return box

    def _build_metrics_row(self) -> QWidget:
        box = QGroupBox("Metrics")
        layout = QGridLayout(box)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)
        self.lbl_h_index = QLabel("—")
        self.lbl_total_citations = QLabel("—")
        self.lbl_papers_count = QLabel("—")
        self.lbl_avg_citations = QLabel("—")
        for i, (title, lbl) in enumerate(
            [
                ("h-index", self.lbl_h_index),
                ("Total citations", self.lbl_total_citations),
                ("Papers count", self.lbl_papers_count),
                ("Avg citations / paper", self.lbl_avg_citations),
            ]
        ):
            value_font = QFont()
            value_font.setPointSize(18)
            value_font.setBold(True)
            lbl.setFont(value_font)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color:#007acc;")
            title_label = QLabel(title)
            title_label.setStyleSheet("color:#888;")
            title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.addWidget(lbl)
            container_layout.addWidget(title_label)
            layout.addWidget(container, 0, i)
        return box

    def _build_timeline_box(self) -> QWidget:
        box = QGroupBox("Citation Timeline")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 6)
        self._build_canvas(box_layout=layout,
                           attr_prefix="timeline",
                           empty_text="No citation timeline data")
        return box

    def _build_topics_box(self) -> QWidget:
        box = QGroupBox("Topic Distribution")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 6)
        self._build_canvas(box_layout=layout,
                           attr_prefix="topics",
                           empty_text="No topic data")
        return box

    def _build_collab_box(self) -> QWidget:
        box = QGroupBox("Collaboration Network")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 6)
        self._build_canvas(box_layout=layout,
                           attr_prefix="collab",
                           empty_text="No collaboration network data")
        return box

    def _build_canvas(self, box_layout: QVBoxLayout, attr_prefix: str,
                      empty_text: str) -> None:
        """Build an embedded matplotlib FigureCanvasQTAgg inside the given layout."""
        _configure_matplotlib()
        import matplotlib.pyplot as plt  # noqa: WPS433 lazy
        from matplotlib.backends.backend_qt5agg import (  # noqa: WPS433 lazy
            FigureCanvasQTAgg,
            NavigationToolbar2QT,
        )
        fig = plt.Figure(constrained_layout=True)
        ax = fig.add_subplot(111)
        ax.set_axis_off()
        ax.text(0.5, 0.5, empty_text, ha="center", va="center",
                transform=ax.transAxes, color="#888")
        canvas = FigureCanvasQTAgg(fig)
        toolbar = NavigationToolbar2QT(canvas, self)
        box_layout.addWidget(canvas, stretch=1)
        box_layout.addWidget(toolbar)
        setattr(self, f"_figure_{attr_prefix}", fig)
        setattr(self, f"_canvas_{attr_prefix}", canvas)
        setattr(self, f"_ax_{attr_prefix}", ax)

    def _build_top_papers_box(self) -> QWidget:
        box = QGroupBox("Top Cited Papers")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 6)
        self.top_papers_table = QTableWidget(0, 0)
        self.top_papers_table.setEditTriggers(
            self.top_papers_table.EditTrigger.NoEditTriggers
        )
        layout.addWidget(self.top_papers_table)
        return box

    # ----------------------------------------------------------- Populate

    def _populate(self) -> None:
        # Photo
        photo_path = self._author.get("photo_path")
        if photo_path:
            pix = QPixmap(photo_path)
            if not pix.isNull():
                self.photo_label.setPixmap(
                    pix.scaled(72, 72, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )

        # Metrics
        citations = [p.get("citations", 0) for p in self._publications]
        int_cits = [_coerce_int(c) for c in citations]
        total = sum(int_cits)
        count = len(self._publications)
        avg = (total / count) if count else 0
        h = calculate_h_index(int_cits)
        self.lbl_h_index.setText(str(h))
        self.lbl_total_citations.setText(f"{total:,}")
        self.lbl_papers_count.setText(str(count))
        self.lbl_avg_citations.setText(f"{avg:.1f}")

        self._draw_timeline()
        self._draw_topics()
        self._draw_collab_network()
        self._draw_top_papers()

    # ----------------------------------------------------------- Charts

    def _draw_timeline(self) -> None:
        if self._ax_timeline is None:
            return
        ax = self._ax_timeline
        ax.clear()
        if not self._publications:
            ax.set_axis_off()
            ax.text(0.5, 0.5, "No citation timeline data",
                    ha="center", va="center", transform=ax.transAxes, color="#888")
            self._canvas_timeline.draw_idle()
            return
        year_to_cits: Dict[int, int] = {}
        for p in self._publications:
            y = _coerce_int(p.get("year"), 0)
            if y > 0:
                year_to_cits[y] = year_to_cits.get(y, 0) + _coerce_int(p.get("citations"))
        if not year_to_cits:
            ax.set_axis_off()
            ax.text(0.5, 0.5, "No year data", ha="center", va="center",
                    transform=ax.transAxes, color="#888")
            self._canvas_timeline.draw_idle()
            return
        years = sorted(year_to_cits.keys())
        values = [year_to_cits[y] for y in years]
        ax.bar(years, values, color="#007acc", alpha=0.85)
        ax.set_xlabel("Year")
        ax.set_ylabel("Citations")
        ax.set_title("Citations per year")
        self._canvas_timeline.draw_idle()

    def _draw_topics(self) -> None:
        if self._ax_topics is None:
            return
        ax = self._ax_topics
        ax.clear()
        topic_counts: Dict[str, int] = {}
        for p in self._publications:
            for t in p.get("topics") or []:
                t_str = str(t)
                topic_counts[t_str] = topic_counts.get(t_str, 0) + 1
        if not topic_counts:
            ax.set_axis_off()
            ax.text(0.5, 0.5, "No topic data", ha="center", va="center",
                    transform=ax.transAxes, color="#888")
            self._canvas_topics.draw_idle()
            return
        top_items = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        labels = [t for t, _ in top_items]
        sizes = [c for _, c in top_items]
        ax.pie(sizes, labels=labels, autopct="%1.0f%%", startangle=90,
               textprops={"fontsize": 8})
        ax.set_title("Top topics")
        self._canvas_topics.draw_idle()

    def _draw_collab_network(self) -> None:
        if self._ax_collab is None:
            return
        ax = self._ax_collab
        ax.clear()
        try:
            import networkx as nx  # noqa: WPS433 lazy
        except Exception as exc:  # noqa: BLE001
            logger.warning("networkx unavailable for collaboration network: %s", exc)
            ax.set_axis_off()
            ax.text(0.5, 0.5, "networkx not installed",
                    ha="center", va="center", transform=ax.transAxes, color="#888")
            self._canvas_collab.draw_idle()
            return

        author_name = str(self._author.get("name", "Author"))
        g = nx.Graph()
        g.add_node(author_name, kind="author")
        for p in self._publications:
            coauthors = p.get("authors") or []
            if isinstance(coauthors, str):
                coauthors = [c.strip() for c in coauthors.split(",")]
            for ca in coauthors:
                ca_str = str(ca).strip()
                if ca_str and ca_str != author_name:
                    g.add_node(ca_str, kind="coauthor")
                    g.add_edge(author_name, ca_str)
        if g.number_of_nodes() <= 1:
            ax.set_axis_off()
            ax.text(0.5, 0.5, "No collaborators found",
                    ha="center", va="center", transform=ax.transAxes, color="#888")
            self._canvas_collab.draw_idle()
            return
        pos = nx.spring_layout(g, seed=42)
        node_colors = ["#007acc" if n == author_name else "#888"
                       for n in g.nodes()]
        node_sizes = [120 + 20 * g.degree(n) for n in g.nodes()]
        nx.draw_networkx_edges(g, pos, ax=ax, alpha=0.4, edge_color="#888")
        nx.draw_networkx_nodes(g, pos, ax=ax, node_color=node_colors,
                               node_size=node_sizes, edgecolors="white",
                               linewidths=0.5)
        nx.draw_networkx_labels(g, pos, ax=ax, font_size=7)
        ax.set_axis_off()
        ax.set_title(f"{g.number_of_nodes()} nodes • {g.number_of_edges()} edges")
        self._canvas_collab.draw_idle()

    def _draw_top_papers(self) -> None:
        sorted_pubs = sorted(
            self._publications,
            key=lambda p: _coerce_int(p.get("citations")),
            reverse=True,
        )[:10]
        headers = ["#", "Title", "Year", "Venue", "Citations"]
        self.top_papers_table.setRowCount(len(sorted_pubs))
        self.top_papers_table.setColumnCount(len(headers))
        self.top_papers_table.setHorizontalHeaderLabels(headers)
        for r, paper in enumerate(sorted_pubs):
            cells = [
                str(r + 1),
                str(paper.get("title", "")),
                str(paper.get("year", "")),
                str(paper.get("venue", "")),
                str(paper.get("citations", "")),
            ]
            for c, val in enumerate(cells):
                self.top_papers_table.setItem(r, c, QTableWidgetItem(val))
        self.top_papers_table.resizeColumnsToContents()
