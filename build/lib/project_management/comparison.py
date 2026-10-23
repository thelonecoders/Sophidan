"""Cross-project comparison + reporting.

Given two project ids, :class:`ProjectComparison` computes:

* Paper set overlap (shared vs unique).
* Author set overlap.
* Topic / keyword overlap.
* Year-by-year publication counts side-by-side.
* Per-project aggregate metrics (paper count, total citations, h-index,
  productivity = papers / year-span).

Results are returned as a :class:`ComparisonResult` dataclass that exposes
``to_dict()``, ``to_markdown()`` and ``visualize()`` helpers. A Venn-diagram
helper is also provided via :meth:`ProjectComparison.overlap_venn`.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from database.connection import DatabaseConnection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass.
# ---------------------------------------------------------------------------
@dataclass
class ComparisonResult:
    """Holds the comparison between two projects.

    Attributes:
        project_a: Dict with id, name, paper_count of the first project.
        project_b: Same for the second project.
        shared_paper_ids: Paper ids present in both projects.
        unique_to_a: Paper ids present only in A.
        unique_to_b: Paper ids present only in B.
        shared_authors: Author names present in both projects.
        unique_authors_a / unique_authors_b: Author-name sets unique to each.
        shared_keywords: Keyword terms present in both.
        unique_keywords_a / unique_keywords_b: Keyword terms unique to each.
        year_distribution_a / year_distribution_b: ``{year: count}`` dicts.
        metrics_a / metrics_b: Aggregate metric dicts (papers, citations,
            h_index, productivity).
    """

    project_a: Dict[str, Any] = field(default_factory=dict)
    project_b: Dict[str, Any] = field(default_factory=dict)
    shared_paper_ids: List[int] = field(default_factory=list)
    unique_to_a: List[int] = field(default_factory=list)
    unique_to_b: List[int] = field(default_factory=list)
    shared_authors: List[str] = field(default_factory=list)
    unique_authors_a: List[str] = field(default_factory=list)
    unique_authors_b: List[str] = field(default_factory=list)
    shared_keywords: List[str] = field(default_factory=list)
    unique_keywords_a: List[str] = field(default_factory=list)
    unique_keywords_b: List[str] = field(default_factory=list)
    year_distribution_a: Dict[int, int] = field(default_factory=dict)
    year_distribution_b: Dict[int, int] = field(default_factory=dict)
    metrics_a: Dict[str, Any] = field(default_factory=dict)
    metrics_b: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        def _years(d): return {str(k): v for k, v in d.items()}
        return {
            "project_a": self.project_a,
            "project_b": self.project_b,
            "shared_paper_ids": list(self.shared_paper_ids),
            "unique_to_a": list(self.unique_to_a),
            "unique_to_b": list(self.unique_to_b),
            "shared_authors": list(self.shared_authors),
            "unique_authors_a": list(self.unique_authors_a),
            "unique_authors_b": list(self.unique_authors_b),
            "shared_keywords": list(self.shared_keywords),
            "unique_keywords_a": list(self.unique_keywords_a),
            "unique_keywords_b": list(self.unique_keywords_b),
            "year_distribution_a": _years(self.year_distribution_a),
            "year_distribution_b": _years(self.year_distribution_b),
            "metrics_a": self.metrics_a,
            "metrics_b": self.metrics_b,
        }

    def to_markdown(self) -> str:
        """Return a Markdown report of the comparison."""
        def _summary(p: Dict[str, Any]) -> str:
            return (f"**{p.get('name', '?')}** (id={p.get('id', '?')}, "
                    f"{p.get('paper_count', 0)} papers)")

        lines: List[str] = []
        lines.append("# Project Comparison\n")
        lines.append(_summary(self.project_a) + "  \nvs  \n" +
                     _summary(self.project_b) + "\n")
        lines.append("## Papers\n")
        lines.append(f"- Shared: **{len(self.shared_paper_ids)}**")
        lines.append(f"- Unique to A: **{len(self.unique_to_a)}**")
        lines.append(f"- Unique to B: **{len(self.unique_to_b)}**\n")
        lines.append("## Authors\n")
        lines.append(f"- Shared: **{len(self.shared_authors)}**")
        lines.append(f"- Unique to A: **{len(self.unique_authors_a)}**")
        lines.append(f"- Unique to B: **{len(self.unique_authors_b)}**\n")
        lines.append("## Keywords\n")
        lines.append(f"- Shared: **{len(self.shared_keywords)}**")
        lines.append(f"- Unique to A: **{len(self.unique_keywords_a)}**")
        lines.append(f"- Unique to B: **{len(self.unique_keywords_b)}**\n")
        lines.append("## Year distribution\n")
        all_years = sorted(set(self.year_distribution_a) |
                           set(self.year_distribution_b))
        if all_years:
            lines.append("| Year | A | B |")
            lines.append("|------|---|---|")
            for y in all_years:
                lines.append(f"| {y} | {self.year_distribution_a.get(y, 0)} | "
                             f"{self.year_distribution_b.get(y, 0)} |")
            lines.append("")
        lines.append("## Metrics\n")
        lines.append("| Metric | A | B |")
        lines.append("|--------|---|---|")
        keys = sorted(set(self.metrics_a) | set(self.metrics_b))
        for k in keys:
            lines.append(f"| {k} | {self.metrics_a.get(k)} | "
                         f"{self.metrics_b.get(k)} |")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Visualisation
    # ------------------------------------------------------------------
    def visualize(self) -> Any:
        """Return a 2-panel matplotlib figure (year distribution + metrics).

        Returns:
            A :class:`matplotlib.figure.Figure`. ``None`` if matplotlib is
            unavailable.
        """
        try:
            import matplotlib
            matplotlib.use("Agg", force=False)
            import matplotlib.pyplot as plt
        except Exception as exc:  # pragma: no cover
            logger.warning("matplotlib unavailable — visualize() returned None. (%s)", exc)
            return None
        plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5),
                                        constrained_layout=True)
        # Year distribution.
        all_years = sorted(set(self.year_distribution_a) |
                           set(self.year_distribution_b))
        if all_years:
            width = 0.4
            xs = list(range(len(all_years)))
            a_vals = [self.year_distribution_a.get(y, 0) for y in all_years]
            b_vals = [self.year_distribution_b.get(y, 0) for y in all_years]
            ax1.bar([x - width / 2 for x in xs], a_vals, width=width,
                    label=self.project_a.get("name", "A"),
                    color=self.project_a.get("color", "#3B82F6"))
            ax1.bar([x + width / 2 for x in xs], b_vals, width=width,
                    label=self.project_b.get("name", "B"),
                    color=self.project_b.get("color", "#EF4444"))
            ax1.set_xticks(xs)
            ax1.set_xticklabels([str(y) for y in all_years], rotation=45,
                                ha="right")
            ax1.set_ylabel("Papers")
            ax1.set_title("Year distribution")
            ax1.legend()
        else:
            ax1.text(0.5, 0.5, "No year data", ha="center", va="center",
                     transform=ax1.transAxes)
            ax1.set_axis_off()
        # Metrics bar chart.
        metric_keys = [k for k in ("papers", "citations", "h_index",
                                    "productivity") if k in self.metrics_a
                       or k in self.metrics_b]
        if metric_keys:
            xs = list(range(len(metric_keys)))
            width = 0.4
            a_vals = [float(self.metrics_a.get(k, 0) or 0) for k in metric_keys]
            b_vals = [float(self.metrics_b.get(k, 0) or 0) for k in metric_keys]
            ax2.bar([x - width / 2 for x in xs], a_vals, width=width,
                    label=self.project_a.get("name", "A"),
                    color=self.project_a.get("color", "#3B82F6"))
            ax2.bar([x + width / 2 for x in xs], b_vals, width=width,
                    label=self.project_b.get("name", "B"),
                    color=self.project_b.get("color", "#EF4444"))
            ax2.set_xticks(xs)
            ax2.set_xticklabels(metric_keys, rotation=30, ha="right")
            ax2.set_title("Aggregate metrics")
            ax2.legend()
        else:
            ax2.text(0.5, 0.5, "No metric data", ha="center", va="center",
                     transform=ax2.transAxes)
            ax2.set_axis_off()
        return fig


# ---------------------------------------------------------------------------
# Manager class.
# ---------------------------------------------------------------------------
class ProjectComparison:
    """Compare two projects: papers, authors, keywords, years, metrics."""

    def __init__(self, db: Optional[DatabaseConnection] = None) -> None:
        """Initialise the comparison engine.

        Args:
            db: Optional :class:`DatabaseConnection`. Defaults to the
                singleton.
        """
        self.db: DatabaseConnection = db or DatabaseConnection()

    # ------------------------------------------------------------------
    # Core compare()
    # ------------------------------------------------------------------
    def compare(self, project_a_id: int, project_b_id: int) -> ComparisonResult:
        """Compare two projects and return a :class:`ComparisonResult`.

        Args:
            project_a_id: First project id.
            project_b_id: Second project id.

        Returns:
            A populated :class:`ComparisonResult`.

        Raises:
            KeyError: If either project does not exist.
        """
        from database.models import ProjectModel, PaperModel, AuthorModel, KeywordModel
        session = self.db.get_session()
        try:
            a = session.get(ProjectModel, project_a_id)
            if a is None:
                raise KeyError(f"Project id={project_a_id} not found.")
            b = session.get(ProjectModel, project_b_id)
            if b is None:
                raise KeyError(f"Project id={project_b_id} not found.")
            papers_a = list(a.papers)
            papers_b = list(b.papers)
            ids_a = {p.id for p in papers_a}
            ids_b = {p.id for p in papers_b}
            shared = sorted(ids_a & ids_b)
            uniq_a = sorted(ids_a - ids_b)
            uniq_b = sorted(ids_b - ids_a)
            # Authors.
            auth_a: Set[str] = {au.name for p in papers_a for au in p.authors}
            auth_b: Set[str] = {au.name for p in papers_b for au in p.authors}
            # Keywords.
            kw_a: Set[str] = {k.term for p in papers_a for k in p.keywords}
            kw_b: Set[str] = {k.term for p in papers_b for k in p.keywords}
            # Year distribution.
            years_a: Dict[int, int] = {}
            years_b: Dict[int, int] = {}
            for p in papers_a:
                if p.year is not None:
                    years_a[p.year] = years_a.get(p.year, 0) + 1
            for p in papers_b:
                if p.year is not None:
                    years_b[p.year] = years_b.get(p.year, 0) + 1
            result = ComparisonResult(
                project_a={"id": a.id, "name": a.name, "color": a.color,
                            "paper_count": len(papers_a)},
                project_b={"id": b.id, "name": b.name, "color": b.color,
                            "paper_count": len(papers_b)},
                shared_paper_ids=shared,
                unique_to_a=uniq_a,
                unique_to_b=uniq_b,
                shared_authors=sorted(auth_a & auth_b),
                unique_authors_a=sorted(auth_a - auth_b),
                unique_authors_b=sorted(auth_b - auth_a),
                shared_keywords=sorted(kw_a & kw_b),
                unique_keywords_a=sorted(kw_a - kw_b),
                unique_keywords_b=sorted(kw_b - kw_a),
                year_distribution_a=dict(sorted(years_a.items())),
                year_distribution_b=dict(sorted(years_b.items())),
                metrics_a=self._metrics(papers_a),
                metrics_b=self._metrics(papers_b),
            )
            return result
        finally:
            self.db._session_factory.remove()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _metrics(papers: List[Any]) -> Dict[str, Any]:
        """Compute aggregate metrics for a list of papers.

        Args:
            papers: List of :class:`PaperModel`.

        Returns:
            Dict with keys: ``papers``, ``citations``, ``h_index``,
            ``productivity``, ``year_span``.
        """
        n = len(papers)
        cites = [int(getattr(p, "citations_count", 0) or 0) for p in papers]
        total_cites = sum(cites)
        # H-index: largest h such that there are >= h papers each with >= h citations.
        sorted_cites = sorted(cites, reverse=True)
        h_index = 0
        for i, c in enumerate(sorted_cites, start=1):
            if c >= i:
                h_index = i
            else:
                break
        years = [int(p.year) for p in papers if getattr(p, "year", None)]
        if years:
            span = max(years) - min(years) + 1
            productivity = round(n / span, 3) if span else float(n)
        else:
            span = 0
            productivity = 0.0
        return {
            "papers": n,
            "citations": total_cites,
            "h_index": h_index,
            "productivity": productivity,
            "year_span": span,
        }

    # ------------------------------------------------------------------
    # Venn diagram
    # ------------------------------------------------------------------
    def overlap_venn(self, project_a_id: int, project_b_id: int) -> Any:
        """Return a matplotlib Figure showing the paper-set Venn diagram.

        Uses matplotlib-venn when available; falls back to a 2-bar
        side-by-side chart when it is not.

        Args:
            project_a_id: First project id.
            project_b_id: Second project id.

        Returns:
            A :class:`matplotlib.figure.Figure` (or ``None`` if matplotlib
            is unavailable).
        """
        try:
            import matplotlib
            matplotlib.use("Agg", force=False)
            import matplotlib.pyplot as plt
        except Exception as exc:  # pragma: no cover
            logger.warning("matplotlib unavailable — overlap_venn() returned None. (%s)", exc)
            return None
        plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        result = self.compare(project_a_id, project_b_id)
        a_only = len(result.unique_to_a)
        b_only = len(result.unique_to_b)
        shared = len(result.shared_paper_ids)

        try:
            from matplotlib_venn import venn2  # type: ignore
            fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
            venn2(subsets=(a_only, b_only, shared),
                  set_labels=(result.project_a.get("name", "A"),
                               result.project_b.get("name", "B")),
                  ax=ax)
            ax.set_title("Paper overlap")
        except Exception as exc:
            # Fallback: bar chart.
            logger.info("matplotlib-venn unavailable (%s) — using bar fallback.", exc)
            fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
            labels = ["Only A", "Shared", "Only B"]
            counts = [a_only, shared, b_only]
            ax.bar(labels, counts,
                   color=[result.project_a.get("color", "#3B82F6"),
                          "#94A3B8",
                          result.project_b.get("color", "#EF4444")])
            ax.set_ylabel("Papers")
            ax.set_title("Paper overlap")
            for i, c in enumerate(counts):
                ax.text(i, c, str(c), ha="center", va="bottom")
        return fig

    # ------------------------------------------------------------------
    # Side-by-side metrics DataFrame.
    # ------------------------------------------------------------------
    def compare_metrics(self, project_a_id: int,
                        project_b_id: int) -> Any:
        """Return a side-by-side metrics DataFrame.

        Columns: ``metric``, ``<A name>``, ``<B name>``.

        Args:
            project_a_id: First project id.
            project_b_id: Second project id.

        Returns:
            A :class:`pandas.DataFrame`. ``None`` if pandas is unavailable.
        """
        try:
            import pandas as pd
        except Exception as exc:  # pragma: no cover
            logger.warning("pandas unavailable — compare_metrics() returned None. (%s)", exc)
            return None
        result = self.compare(project_a_id, project_b_id)
        name_a = result.project_a.get("name", "A")
        name_b = result.project_b.get("name", "B")
        rows: List[Tuple[str, Any, Any]] = []
        for key in ("papers", "citations", "h_index", "productivity",
                    "year_span"):
            rows.append((key, result.metrics_a.get(key), result.metrics_b.get(key)))
        rows.append(("shared_papers", len(result.shared_paper_ids),
                     len(result.shared_paper_ids)))
        rows.append(("unique_papers", len(result.unique_to_a),
                     len(result.unique_to_b)))
        rows.append(("shared_authors", len(result.shared_authors),
                     len(result.shared_authors)))
        rows.append(("shared_keywords", len(result.shared_keywords),
                     len(result.shared_keywords)))
        df = pd.DataFrame(rows, columns=["metric", name_a, name_b])
        return df


__all__ = ["ComparisonResult", "ProjectComparison"]
