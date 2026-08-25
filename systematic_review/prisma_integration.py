"""PRISMA 2020 flow-diagram & checklist integration.

This module bridges the systematic-review screening workflow with the
sibling :mod:`prisma` package (built by a parallel v2.0.0 sub-agent)
which exposes a ``PRISMAFlowGenerator`` capable of producing SVG / PNG
/ PDF flow diagrams and Markdown / PDF checklists.

When the sibling :mod:`prisma.generator` module is not yet available
in the working environment, this module gracefully degrades: the
flow-diagram-generation methods fall back to writing a self-contained
SVG / Markdown file so callers can still get *some* output, and the
checklist methods always work (they are implemented locally).

This module is independently importable — all heavy / sibling imports
are performed lazily inside the methods that need them.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import json as _json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PRISMA 2020 checklist (27 items)
# ---------------------------------------------------------------------------

_PRISMA_2020_CHECKLIST: List[Dict[str, Any]] = [
    {"item": 1, "section": "Title", "description": "Identify the report as a systematic review."},
    {"item": 2, "section": "Abstract", "description": "See the PRISMA 2020 for Abstracts checklist."},
    {"item": 3, "section": "Introduction", "description": "Describe the rationale for the review in the context of existing knowledge."},
    {"item": 4, "section": "Introduction", "description": "Provide an explicit statement of the objective(s) and question(s) the review addresses."},
    {"item": 5, "section": "Methods", "description": "Specify eligibility criteria (PICO)."},
    {"item": 6, "section": "Methods", "description": "Specify information sources and search date range."},
    {"item": 7, "section": "Methods", "description": "Provide the full search strategy for at least one database."},
    {"item": 8, "section": "Methods", "description": "Specify the selection process (number of reviewers, conflicts)."},
    {"item": 9, "section": "Methods", "description": "Specify the data extraction process."},
    {"item": 10, "section": "Methods", "description": "List the data items extracted."},
    {"item": 11, "section": "Methods", "description": "Specify the risk-of-bias tool(s) used (11a primary, 11b additional e.g. for non-randomised)."},
    {"item": 12, "section": "Methods", "description": "Specify the methods used to assess RoB in included studies."},
    {"item": 13, "section": "Methods", "description": "Describe the effect measures (13a) and synthesis methods (13b, e.g. meta-analysis)."},
    {"item": 14, "section": "Methods", "description": "Describe any methods used to synthesise results (narrative, tabular)."},
    {"item": 15, "section": "Methods", "description": "Describe any methods used to investigate heterogeneity."},
    {"item": 16, "section": "Methods", "description": "Describe any methods used to assess certainty of body of evidence."},
    {"item": 17, "section": "Results", "description": "Give numbers of records identified, screened, included (17a); cite sources (17b); reasons for exclusion (17c); report flow diagram (17d)."},
    {"item": 18, "section": "Results", "description": "Cite each included study with study characteristics."},
    {"item": 19, "section": "Results", "description": "Present RoB assessments per study and overall."},
    {"item": 20, "section": "Results", "description": "Report results for each outcome per study (20a); synthesis results, effect sizes, CIs, I^2 (20b)."},
    {"item": 21, "section": "Results", "description": "Present results of any sensitivity analyses."},
    {"item": 22, "section": "Discussion", "description": "Provide a summary of the main findings including the certainty of evidence."},
    {"item": 23, "section": "Discussion", "description": "Discuss limitations of the evidence (23a), limitations of the review processes (23b), and implications for practice and policy (23c)."},
    {"item": 24, "section": "Other", "description": "Discuss implications for future research (24a); registration info (24b); sources of support (24c); conflicts of interest (24d)."},
    {"item": 25, "section": "Other", "description": "Provide registration information (PROSPERO ID) or state none."},
    {"item": 26, "section": "Other", "description": "Provide sources of support and conflicts of interest."},
    {"item": 27, "section": "Other", "description": "Provide availability of data, code or materials."},
]



# ---------------------------------------------------------------------------
# PRISMA 2020 extensions
# ---------------------------------------------------------------------------

_PRISMA_EXTENSIONS: Dict[str, Dict[str, Any]] = {
    "IPD": {
        "full_name": "PRISMA-IPD",
        "description": (
            "PRISMA extension for individual patient data (IPD) "
            "systematic reviews."
        ),
        "items": [
            {"item": "IPD-1", "description": "State that the review is an IPD review."},
            {"item": "IPD-2", "description": "Describe the methods for obtaining IPD."},
        ],
    },
    "NMA": {
        "full_name": "PRISMA-NMA",
        "description": (
            "PRISMA extension for network meta-analyses."
        ),
        "items": [
            {"item": "NMA-1", "description": "Describe the network of interventions."},
            {"item": "NMA-2", "description": "Describe the assumptions of transitivity."},
        ],
    },
    "ScR": {
        "full_name": "PRISMA-ScR",
        "description": (
            "PRISMA extension for scoping reviews."
        ),
        "items": [
            {"item": "ScR-1", "description": "State the rationale for the scoping review."},
            {"item": "ScR-2", "description": "Provide PCC framework (Population, Concept, Context)."},
        ],
    },
    "Harms": {
        "full_name": "PRISMA-Harms",
        "description": (
            "PRISMA extension for reviews of adverse events / harms."
        ),
        "items": [
            {"item": "Harms-1", "description": "Describe methods for identifying harms data."},
            {"item": "Harms-2", "description": "Report harms per study."},
        ],
    },
    "Abstract": {
        "full_name": "PRISMA-A",
        "description": (
            "PRISMA extension for abstracts of systematic reviews."
        ),
        "items": [
            {"item": "A-1", "description": "Provide a structured abstract."},
            {"item": "A-2", "description": "Include number of studies included and participants."},
        ],
    },
    "Diagnostic": {
        "full_name": "PRISMA-DTA",
        "description": (
            "PRISMA extension for diagnostic test accuracy (DTA) reviews."
        ),
        "items": [
            {"item": "DTA-1", "description": "Describe the test under evaluation."},
            {"item": "DTA-2", "description": "Describe the reference standard."},
        ],
    },
}


# ---------------------------------------------------------------------------
# PRISMAIntegration
# ---------------------------------------------------------------------------

class PRISMAIntegration:
    """Bridge between a :class:`ScreeningManager` and the PRISMA outputs.

    The integration class exposes:

    * :meth:`from_screening`               — count records per PRISMA stage
    * :meth:`generate_flow_diagram`       — write SVG / PNG / PDF flow
    * :meth:`generate_checklist`          — write Markdown / PDF checklist
    * :meth:`prisma_2020_checklist`       — return the 27-item checklist
    * :meth:`prisma_extensions`           — return the 6 known extensions

    All heavy / sibling imports (matplotlib, prisma.generator,
    reportlab) are done lazily so the module is importable in a
    minimal environment.
    """

    # ------------------------------------------------------------------
    # Counting
    # ------------------------------------------------------------------

    def from_screening(self, screening: Any) -> Dict[str, int]:
        """Return a dict of PRISMA stage -> count from a ScreeningManager.

        Args:
            screening: A :class:`ScreeningManager` (duck-typed: must
                expose ``progress()`` returning a dict with stage keys
                matching the ``ScreeningStage`` enum values, plus a
                ``__len__`` for total record count).

        Returns:
            A dict with keys:

            * ``identification``   — records identified
            * ``title_abstract``   — records at title/abstract stage
            * ``full_text``        — records at full-text stage
            * ``included``         — records included
            * ``excluded``         — records excluded
            * ``duplicates_removed``— best-effort duplicate count
            * ``total``             — total records seen
        """
        # progress() returns stage-keyed counts
        progress = {}
        if hasattr(screening, "progress"):
            progress = dict(screening.progress() or {})
        total = len(screening) if hasattr(screening, "__len__") else progress.get("total", 0)
        out: Dict[str, int] = {
            "identification": int(progress.get("identification", 0)),
            "title_abstract": int(progress.get("title_abstract", 0)),
            "full_text": int(progress.get("full_text", 0)),
            "included": int(progress.get("included", 0)),
            "excluded": int(progress.get("excluded", 0)),
            "duplicates_removed": 0,
            "total": int(total),
        }
        # duplicates_removed: estimate from merged_from raw records
        if hasattr(screening, "records"):
            dupes = 0
            for rec in screening.records:  # type: ignore[attr-defined]
                raw = getattr(rec, "raw", None)
                if isinstance(raw, dict):
                    merged = raw.get("_merged_from", [])
                    dupes += len(merged) if isinstance(merged, list) else 0
            out["duplicates_removed"] = dupes
        return out

    # ------------------------------------------------------------------
    # Flow diagram generation
    # ------------------------------------------------------------------

    def generate_flow_diagram(
        self,
        screening: Any,
        output_path: str,
        title: str = "PRISMA 2020 Flow Diagram",
    ) -> str:
        """Generate a PRISMA 2020 flow diagram and save it.

        Delegates to :mod:`prisma.generator.PRISMAFlowGenerator` when
        available; otherwise falls back to a self-contained SVG
        generator that renders the stage counts as labelled boxes.

        Args:
            screening: A :class:`ScreeningManager`.
            output_path: Destination file path. Format is inferred from
                the extension (``.svg`` / ``.png`` / ``.pdf``).
            title: Diagram title.

        Returns:
            The actual path written (may differ from ``output_path``
            if a sibling generator chose a different extension).
        """
        counts = self.from_screening(screening)
        output_path = os.fspath(output_path)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        # try sibling prisma.generator
        try:
            from prisma.generator import PRISMAFlowGenerator  # type: ignore
            gen = PRISMAFlowGenerator()
            # The sibling API may take many shapes; try common ones.
            for attr in ("generate", "render", "save_flow_diagram"):
                fn = getattr(gen, attr, None)
                if callable(fn):
                    try:
                        result = fn(counts=counts, output_path=output_path,
                                    title=title)
                        if isinstance(result, str):
                            logger.info(
                                "PRISMA flow diagram written via prisma.generator -> %s",
                                result,
                            )
                            return result
                    except TypeError:
                        try:
                            result = fn(counts, output_path)
                            if isinstance(result, str):
                                return result
                        except Exception:
                            pass
            logger.warning(
                "prisma.generator.PRISMAFlowGenerator present but no "
                "compatible method found; using fallback SVG generator."
            )
        except ImportError:
            logger.info(
                "prisma.generator not yet available; using built-in "
                "fallback SVG flow diagram."
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "prisma.generator delegation failed (%s); using fallback.", exc
            )

        # fallback: write a self-contained SVG
        ext = os.path.splitext(output_path)[1].lower()
        if ext not in {".svg", ".png", ".pdf"}:
            ext = ".svg"
            output_path = output_path + ".svg"
        svg = self._render_svg_flow(counts, title)
        if ext == ".svg":
            with open(output_path, "w", encoding="utf-8") as fh:
                fh.write(svg)
            logger.info("Wrote PRISMA SVG flow diagram to %s", output_path)
            return output_path
        # for PNG/PDF, try matplotlib render of the same diagram
        return self._render_via_matplotlib(counts, output_path, title, svg)

    def _render_via_matplotlib(
        self,
        counts: Dict[str, int],
        output_path: str,
        title: str,
        fallback_svg: str,
    ) -> str:
        """Best-effort render of the flow diagram to PNG/PDF via matplotlib."""
        try:
            import matplotlib  # noqa: WPS433
            matplotlib.use("Agg", force=False)
            import matplotlib.pyplot as plt
            from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
            plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "matplotlib unavailable (%s); writing SVG instead of %s",
                exc, output_path,
            )
            alt_path = os.path.splitext(output_path)[0] + ".svg"
            with open(alt_path, "w", encoding="utf-8") as fh:
                fh.write(fallback_svg)
            return alt_path

        fig, ax = plt.subplots(figsize=(10, 7), constrained_layout=True)
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 10)
        ax.set_axis_off()

        # box layout
        boxes = [
            (1.0, 8.5, 4.0, 1.2, f"Identification\n(records: {counts['identification']})"),
            (5.5, 8.5, 4.0, 1.2, f"Duplicates removed\n({counts['duplicates_removed']})"),
            (1.0, 6.5, 4.0, 1.2, f"Title/abstract screened\n({counts['title_abstract']})"),
            (5.5, 6.5, 4.0, 1.2, f"Excluded at T/A\n({counts['excluded']})"),
            (1.0, 4.5, 4.0, 1.2, f"Full-text assessed\n({counts['full_text']})"),
            (5.5, 4.5, 4.0, 1.2, f"Excluded at full-text\n(included above)"),
            (1.0, 2.5, 4.0, 1.2, f"Included in synthesis\n({counts['included']})"),
        ]
        for x, y, w, h, label in boxes:
            ax.add_patch(FancyBboxPatch((x, y), w, h,
                                         boxstyle="round,pad=0.05",
                                         facecolor="#e8f1fa",
                                         edgecolor="#2c6da3"))
            ax.text(x + w / 2, y + h / 2, label,
                    ha="center", va="center", fontsize=9)
        # arrows
        arrow_props = dict(arrowstyle="->", color="#2c6da3", lw=1.4)
        ax.add_patch(FancyArrowPatch((3.0, 8.5), (3.0, 7.7),
                                      **arrow_props))
        ax.add_patch(FancyArrowPatch((3.0, 6.5), (3.0, 5.7),
                                      **arrow_props))
        ax.add_patch(FancyArrowPatch((3.0, 4.5), (3.0, 3.7),
                                      **arrow_props))
        ax.add_patch(FancyArrowPatch((5.0, 9.1), (5.5, 9.1),
                                      **arrow_props))
        ax.add_patch(FancyArrowPatch((5.0, 7.1), (5.5, 7.1),
                                      **arrow_props))
        ax.add_patch(FancyArrowPatch((5.0, 5.1), (5.5, 5.1),
                                      **arrow_props))
        ax.set_title(title, fontsize=12, pad=10)
        fig.savefig(output_path)
        plt.close(fig)
        logger.info("Wrote PRISMA flow diagram to %s", output_path)
        return output_path

    @staticmethod
    def _render_svg_flow(counts: Dict[str, int], title: str) -> str:
        """Render a minimal self-contained SVG flow diagram."""
        # minimal SVG with 4 stacked boxes
        box_w, box_h = 320, 70
        x_left = 60
        x_right = 480
        y_start = 60
        gap = 50
        rows = [
            (f"Identification: {counts['identification']} records"),
            (f"Duplicates removed: {counts['duplicates_removed']}"),
            (f"Title/abstract screened: {counts['title_abstract']}"),
            (f"Full-text assessed: {counts['full_text']}"),
            (f"Included in synthesis: {counts['included']}"),
            (f"Excluded: {counts['excluded']}"),
        ]
        svg_parts = [
            f'<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{y_start + len(rows) * (box_h + gap) + 40}" viewBox="0 0 900 {y_start + len(rows) * (box_h + gap) + 40}">',
            f'<rect width="100%" height="100%" fill="#ffffff"/>',
            f'<text x="450" y="30" text-anchor="middle" font-family="Noto Sans SC, DejaVu Sans, sans-serif" font-size="18" font-weight="bold">{title}</text>',
        ]
        y = y_start
        for i, label in enumerate(rows):
            x = x_left if i % 2 == 0 else x_right
            svg_parts.append(
                f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" '
                f'rx="8" ry="8" fill="#e8f1fa" stroke="#2c6da3" stroke-width="1.5"/>'
            )
            svg_parts.append(
                f'<text x="{x + box_w // 2}" y="{y + box_h // 2 + 6}" '
                f'text-anchor="middle" font-family="Noto Sans SC, DejaVu Sans, sans-serif" '
                f'font-size="13" fill="#1a1a1a">{label}</text>'
            )
            # arrow to next box
            if i + 1 < len(rows):
                next_x = x_left if (i + 1) % 2 == 0 else x_right
                svg_parts.append(
                    f'<line x1="{x + box_w // 2}" y1="{y + box_h}" '
                    f'x2="{next_x + box_w // 2}" y2="{y + box_h + gap}" '
                    f'stroke="#2c6da3" stroke-width="1.4" marker-end="url(#arr)"/>'
                )
            y += box_h + gap
        # arrow marker
        svg_parts.append(
            '<defs><marker id="arr" markerWidth="10" markerHeight="10" refX="6" refY="3" '
            'orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#2c6da3"/></marker></defs>'
        )
        svg_parts.append('</svg>')
        return "\n".join(svg_parts)

    # ------------------------------------------------------------------
    # Checklist generation
    # ------------------------------------------------------------------

    def generate_checklist(
        self,
        screening: Any,
        output_path: str,
        title: str = "PRISMA 2020 Checklist",
    ) -> str:
        """Generate a PRISMA 2020 checklist file (Markdown or PDF).

        Writes a Markdown checklist with each item's description and a
        ``Reported?`` column set to ``No``. The caller can edit the
        Markdown to mark items as reported.

        If the file extension is ``.pdf``, the Markdown is rendered to
        PDF via reportlab when available; otherwise the Markdown file
        is written as-is and a ``.pdf`` extension is downgraded to
        ``.md``.

        Args:
            screening: A :class:`ScreeningManager` (used only to get
                counts; can be ``None``).
            output_path: Destination path.
            title: Checklist title.

        Returns:
            The actual path written.
        """
        output_path = os.fspath(output_path)
        ext = os.path.splitext(output_path)[1].lower()
        if ext == ".pdf":
            # try reportlab; fallback to .md
            try:
                import reportlab  # type: ignore  # noqa: F401
                from reportlab.lib.pagesizes import A4
                from reportlab.lib.styles import getSampleStyleSheet
                from reportlab.platypus import (
                    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                )
                from reportlab.lib import colors
                md_path = os.path.splitext(output_path)[0] + ".md"
                md = self._build_checklist_markdown(screening, title)
                with open(md_path, "w", encoding="utf-8") as fh:
                    fh.write(md)
                # render to PDF
                doc = SimpleDocTemplate(output_path, pagesize=A4,
                                         leftMargin=36, rightMargin=36,
                                         topMargin=36, bottomMargin=36)
                styles = getSampleStyleSheet()
                flow = [Paragraph(title, styles["Title"]), Spacer(1, 12)]
                counts = self.from_screening(screening) if screening is not None else {}
                if counts:
                    flow.append(Paragraph(
                        "<b>Counts:</b> "
                        + ", ".join(f"{k}={v}" for k, v in counts.items()),
                        styles["BodyText"],
                    ))
                    flow.append(Spacer(1, 12))
                data = [["#", "Section", "Description", "Reported?"]]
                for item in self.prisma_2020_checklist():
                    data.append([
                        str(item["item"]),
                        item["section"],
                        Paragraph(item["description"], styles["BodyText"]),
                        "No",
                    ])
                tbl = Table(data, colWidths=[30, 80, 360, 70])
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c6da3")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]))
                flow.append(tbl)
                doc.build(flow)
                logger.info("Wrote PRISMA PDF checklist to %s", output_path)
                return output_path
            except ImportError:
                logger.warning(
                    "reportlab not available; writing Markdown checklist instead."
                )
                output_path = os.path.splitext(output_path)[0] + ".md"
        # default: write Markdown
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        md = self._build_checklist_markdown(screening, title)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(md)
        logger.info("Wrote PRISMA Markdown checklist to %s", output_path)
        return output_path

    def _build_checklist_markdown(self, screening: Any, title: str) -> str:
        """Build the Markdown representation of the checklist."""
        lines: List[str] = [f"# {title}", ""]
        lines.append(
            f"_Generated by systematic_review.prisma_integration "
            f"at {datetime.now(timezone.utc).isoformat()}_"
        )
        lines.append("")
        if screening is not None:
            counts = self.from_screening(screening)
            if counts:
                lines.append("## Screening counts")
                lines.append("")
                for k, v in counts.items():
                    lines.append(f"- **{k}**: {v}")
                lines.append("")
        lines.append("## PRISMA 2020 main checklist (27 items)")
        lines.append("")
        lines.append("| # | Section | Description | Reported? |")
        lines.append("|---|---|---|---|")
        for item in self.prisma_2020_checklist():
            desc = item["description"].replace("\n", " ").replace("|", "\\|")
            lines.append(
                f"| {item['item']} | {item['section']} | {desc} | No |"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Checklist + extension catalog
    # ------------------------------------------------------------------

    def prisma_2020_checklist(self) -> List[Dict[str, Any]]:
        """Return the 27-item PRISMA 2020 checklist as a list of dicts."""
        return [dict(item) for item in _PRISMA_2020_CHECKLIST]

    def prisma_extensions(self) -> Dict[str, Dict[str, Any]]:
        """Return the 6 known PRISMA extensions (IPD, NMA, ScR, Harms, Abstract, Diagnostic).

        Each value is a dict with ``full_name``, ``description`` and
        ``items`` keys.
        """
        # deep copy to keep module constant pristine
        return _json.loads(_json.dumps(_PRISMA_EXTENSIONS))
