"""PRISMA 2020 flow-diagram & checklist integration.

This module bridges the systematic-review screening workflow with the
sibling :mod:`prisma` package, whose :class:`~prisma.flow_diagram.PRISMAFlowGenerator`
produces publication-grade SVG / PNG / PDF flow diagrams and whose
:class:`~prisma.checklist.PRISMAChecklist` is the single source of the
official PRISMA 2020 27-item checklist content.

When the sibling :mod:`prisma` package is not importable, this module
gracefully degrades: the flow-diagram generation falls back to writing a
self-contained SVG / matplotlib file so callers can still get *some*
output, and the checklist methods always work (they re-use the official
item list when the sibling is importable).

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
# PRISMA 2020 checklist (27 items) — SINGLE SOURCE: prisma.checklist.
# The previous local 27-item list was an unofficial variant that disagreed
# with Page et al. 2021 (item 5/24a confusion, scrambled tail). The official
# list now lives in prisma/checklist.py and is re-used here verbatim.
# ---------------------------------------------------------------------------

#: Fallback descriptions used ONLY when the sibling prisma package is not
#: importable (kept minimal — points readers at the official source).
_PRISMA_2020_FALLBACK: List[Dict[str, Any]] = [
    {"item": i,
     "section": s,
     "description": "(official PRISMA 2020 item %d — install/import the "
                    "sibling `prisma` package for the full text; see Page "
                    "MJ et al., BMJ 2021;372:n71)" % i}
    for i, s in enumerate(
        ["Title", "Abstract",
         "Introduction", "Introduction",
         "Methods", "Methods", "Methods", "Methods", "Methods", "Methods",
         "Methods", "Methods", "Methods", "Methods", "Methods",
         "Results", "Results", "Results", "Results", "Results", "Results",
         "Results",
         "Discussion",
         "Other", "Other", "Other", "Other"],
        start=1,
    )
]


def _load_official_checklist() -> List[Dict[str, Any]]:
    """Return the official 27-item checklist from prisma.checklist."""
    try:
        from prisma.checklist import PRISMAChecklist
        items = PRISMAChecklist.default_2020_items()
        return [
            {"item": it.id, "section": it.section, "description": it.item_text}
            for it in items
        ]
    except Exception as exc:  # pragma: no cover — sibling missing
        logger.debug("prisma.checklist unavailable (%s); using fallback.", exc)
        return [dict(x) for x in _PRISMA_2020_FALLBACK]


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

    #: Legacy short keys kept for backwards compatibility.
    _LEGACY_UI_KEYS = {
        "n_records_databases": "n_records_databases",
        "n_records_other": None,  # split across registers/websites/citation
        "n_records_deduplicated": "n_records_after_duplicates",
        "n_records_screened": "n_records_screened",
        "n_records_excluded": "n_records_excluded_title_abstract",
        "n_records_assessed": "n_full_text_assessed",
        "n_records_fulltext_excluded": "n_full_text_excluded",
        "n_included": "n_studies_included_qualitative",
    }

    def from_screening(self, screening: Any) -> Dict[str, Any]:
        """Return PRISMA stage counts (+ validation warnings) for a screening
        workflow, an already-collected counts dict, or a
        :class:`~prisma.flow_diagram.PRISMAStageCounts`.

        Accepted inputs (duck-typed, in order):

        1. :class:`prisma.flow_diagram.PRISMAStageCounts` — passed through.
        2. A plain dict with ``n_records_*`` / ``n_included`` style keys
           (as produced by the PRISMA builder UI).
        3. A :class:`~systematic_review.screening.ScreeningManager` — stage
           counts are derived from ``progress()`` and the per-record
           ``excluded_at_stage`` / duplicates ledger.

        Returns:
            A dict with:

            * the legacy scalar keys (``identification``, ``title_abstract``,
              ``full_text``, ``included``, ``excluded``,
              ``duplicates_removed``, ``total``) — unchanged contract;
            * ``stage_counts`` — the official
              :class:`PRISMAStageCounts` fields as a dict;
            * ``warnings`` — flow-arithmetic validation warnings;
            * ``notes`` — bookkeeping notes (e.g. the ingest-time
              duplicates ledger).
        """
        stage = self._collect_stage_counts(screening)
        sc = stage  # dict of official keys (None = unknown)
        warnings = self._validate_flow(sc)
        notes: List[str] = []
        dupes = int(sc.get("n_duplicates_removed") or 0)
        if dupes:
            notes.append(
                f"Duplicates ledger: {dupes} duplicate record(s) were merged "
                "at ingest time into their kept records (see each record's "
                "raw['_merged_from'] list for the audit trail)."
            )

        # Legacy scalar keys (backwards compatible).
        total = (
            int(sc.get("n_records_before_duplicates") or 0)
            or int(sc.get("n_records_total") or 0)
            or int(sc.get("n_records_after_duplicates") or 0)
        )
        out: Dict[str, Any] = {
            "identification": int(
                sc.get("n_records_total")
                or ((sc.get("n_records_databases") or 0)
                    + (sc.get("n_records_registers") or 0)
                    + (sc.get("n_records_websites_orgs") or 0)
                    + (sc.get("n_records_citation_searching") or 0))
                or total
            ),
            "title_abstract": int(sc.get("n_records_screened") or 0),
            "full_text": int(sc.get("n_full_text_assessed") or 0),
            "included": int(
                sc.get("n_studies_included_qualitative")
                or sc.get("n_studies_included_quantitative") or 0
            ),
            "excluded": int(
                (sc.get("n_records_excluded_title_abstract") or 0)
                + (sc.get("n_full_text_excluded") or 0)
            ),
            "duplicates_removed": dupes,
            "total": int(total),
            # New structured payload:
            "stage_counts": {k: v for k, v in sc.items() if v is not None},
            "warnings": warnings,
            "notes": notes,
        }
        return out

    # ------------------------------------------------------------------
    # Stage-count collection helpers
    # ------------------------------------------------------------------
    def _collect_stage_counts(self, screening: Any) -> Dict[str, Optional[int]]:
        """Normalise any accepted input into official stage-count keys."""
        sc: Dict[str, Optional[int]] = {
            "n_records_databases": None,
            "n_records_registers": None,
            "n_records_websites_orgs": None,
            "n_records_citation_searching": None,
            "n_records_total": None,
            "n_records_before_duplicates": None,
            "n_records_after_duplicates": None,
            "n_duplicates_removed": None,
            "n_records_screened": None,
            "n_records_excluded_title_abstract": None,
            "n_records_sought_full_text": None,
            "n_records_not_retrieved": None,
            "n_full_text_assessed": None,
            "n_full_text_excluded": None,
            "n_studies_included_qualitative": None,
            "n_studies_included_quantitative": None,
        }
        if screening is None:
            return sc
        # 1) PRISMAStageCounts passthrough.
        try:
            from prisma.flow_diagram import PRISMAStageCounts
            if isinstance(screening, PRISMAStageCounts):
                sc.update({
                    k: (int(v) if v is not None else None)
                    for k, v in screening.to_dict().items()
                    if k != "n_excluded_with_reasons"
                })
                sc["n_excluded_with_reasons"] = list(
                    screening.n_excluded_with_reasons or []
                )
                return sc
        except ImportError:
            pass
        # 2) Plain dict of counts (UI-style or official-style keys).
        if isinstance(screening, dict):
            sc["n_excluded_with_reasons"] = list(
                screening.get("n_excluded_with_reasons") or []
            )
            # direct official keys first
            for k in list(sc):
                if k in screening and screening[k] is not None:
                    try:
                        sc[k] = int(screening[k])
                    except (TypeError, ValueError):
                        pass
            # legacy UI keys
            for ui_key, official in self._LEGACY_UI_KEYS.items():
                if official is None or ui_key not in screening:
                    continue
                try:
                    val = int(screening[ui_key])
                except (TypeError, ValueError):
                    continue
                if sc.get(official) is None:
                    sc[official] = val
            # databases → before-duplicates when not given
            if sc.get("n_records_before_duplicates") is None \
                    and sc.get("n_records_databases") is not None:
                extra = sum(
                    v for k, v in (
                        ("n_records_registers", sc.get("n_records_registers")),
                        ("n_records_websites_orgs", sc.get("n_records_websites_orgs")),
                        ("n_records_citation_searching", sc.get("n_records_citation_searching")),
                    ) if v
                )
                sc["n_records_before_duplicates"] = \
                    int(sc["n_records_databases"]) + int(extra)
            if sc.get("n_records_after_duplicates") is None \
                    and sc.get("n_records_before_duplicates") is not None \
                    and sc.get("n_duplicates_removed") is not None:
                sc["n_records_after_duplicates"] = int(
                    sc["n_records_before_duplicates"]
                ) - int(sc["n_duplicates_removed"])
            return sc
        # 3) ScreeningManager (duck-typed).
        progress: Dict[str, int] = {}
        if hasattr(screening, "progress"):
            progress = dict(screening.progress() or {})
        total = len(screening) if hasattr(screening, "__len__") else \
            int(progress.get("total", 0))
        records = list(getattr(screening, "records", []) or [])
        dupes = 0
        ta_excluded = ft_excluded = at_full_text = 0
        included = 0
        for rec in records:
            raw = getattr(rec, "raw", None)
            if isinstance(raw, dict):
                merged = raw.get("_merged_from", [])
                dupes += len(merged) if isinstance(merged, list) else 0
            stage_val = str(getattr(getattr(rec, "stage", None), "value", ""))
            excl_stage = getattr(rec, "excluded_at_stage", None)
            excl_stage_val = str(getattr(excl_stage, "value", excl_stage or ""))
            if stage_val == "included":
                included += 1
            elif stage_val == "excluded":
                if excl_stage_val == "full_text":
                    ft_excluded += 1
                else:
                    ta_excluded += 1
            elif stage_val == "full_text":
                at_full_text += 1
        screened = total
        sought = included + ft_excluded + at_full_text
        sc.update({
            "n_records_before_duplicates": total + dupes,
            "n_records_after_duplicates": total,
            "n_duplicates_removed": dupes,
            "n_records_screened": screened,
            "n_records_excluded_title_abstract": ta_excluded,
            "n_records_sought_full_text": sought,
            "n_full_text_assessed": included + ft_excluded,
            "n_full_text_excluded": ft_excluded,
            "n_studies_included_qualitative": included,
        })
        return sc

    @staticmethod
    def _validate_flow(sc: Dict[str, Optional[int]]) -> List[str]:
        """Flow-arithmetic validation → human-readable warnings."""
        warnings: List[str] = []

        def get(k: str) -> Optional[int]:
            v = sc.get(k)
            if v is None or isinstance(v, (list, tuple, dict, str)):
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        for key, val in sc.items():
            if key == "n_excluded_with_reasons" or val is None:
                continue
            if isinstance(val, (list, tuple, dict)):
                continue
            try:
                if int(val) < 0:
                    warnings.append(f"{key} is negative ({val}).")
            except (TypeError, ValueError):
                continue
        before, dupes, after = (
            get("n_records_before_duplicates"),
            get("n_duplicates_removed"),
            get("n_records_after_duplicates"),
        )
        if None not in (before, dupes) and after is not None \
                and before - dupes != after:
            warnings.append(
                f"Records after duplicates ({after}) != records before "
                f"duplicates ({before}) minus duplicates removed ({dupes})."
            )
        total, screened = get("n_records_total"), get("n_records_screened")
        if None not in (before, dupes, screened) and before - dupes != screened:
            warnings.append(
                f"Records screened ({screened}) != records identified "
                f"({before}) minus duplicates removed ({dupes})."
            )
        excluded_ta = get("n_records_excluded_title_abstract")
        sought = get("n_records_sought_full_text")
        if None not in (screened, excluded_ta, sought) \
                and screened - excluded_ta != sought:
            warnings.append(
                f"Records sought for retrieval ({sought}) != records "
                f"screened ({screened}) minus title/abstract exclusions "
                f"({excluded_ta})."
            )
        not_retrieved, assessed = (
            get("n_records_not_retrieved"), get("n_full_text_assessed"),
        )
        if None not in (sought, not_retrieved, assessed) \
                and sought - not_retrieved != assessed:
            warnings.append(
                f"Records assessed for eligibility ({assessed}) != records "
                f"sought ({sought}) minus not retrieved ({not_retrieved})."
            )
        ft_excluded = get("n_full_text_excluded")
        qual = get("n_studies_included_qualitative")
        quant = get("n_studies_included_quantitative")
        if None not in (assessed, ft_excluded, qual) \
                and assessed - ft_excluded < max(
                    x for x in (qual or 0, quant or 0)
                ):
            warnings.append(
                "Included studies exceed assessed-minus-excluded "
                f"({assessed} − {ft_excluded}) — flow arithmetic broken."
            )
        if qual is not None and quant is not None and quant > qual:
            warnings.append(
                f"Quantitative synthesis ({quant}) includes more studies "
                f"than the qualitative synthesis ({qual})."
            )
        reasons = sc.get("n_excluded_with_reasons")
        if reasons and ft_excluded is not None:
            try:
                total_reasons = sum(int(c) for _, c in reasons)
                if total_reasons != ft_excluded:
                    warnings.append(
                        f"Sum of full-text exclusion reasons ({total_reasons}) "
                        f"!= records excluded at full text ({ft_excluded})."
                    )
            except (TypeError, ValueError):
                pass
        return warnings

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

        Delegates to the REAL generator,
        :class:`prisma.flow_diagram.PRISMAFlowGenerator` (constructed with
        a properly populated :class:`PRISMAStageCounts` — the previous
        implementation imported a nonexistent ``prisma.generator`` module
        and instantiated the class with no counts, so the
        publication-grade generator was never used). Falls back to the
        local self-contained renderer when the sibling package is
        unavailable.

        Args:
            screening: A :class:`ScreeningManager`, a counts dict, or a
                :class:`PRISMAStageCounts` (see :meth:`from_screening`).
            output_path: Destination file path. Format is inferred from
                the extension (``.svg`` / ``.png`` / ``.pdf``).
            title: Diagram title.

        Returns:
            The actual path written.
        """
        counts = self.from_screening(screening)
        for w in counts.get("warnings", []):
            logger.warning("PRISMA flow validation: %s", w)
        output_path = os.fspath(output_path)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        ext = os.path.splitext(output_path)[1].lower()
        if ext not in {".svg", ".png", ".pdf"}:
            ext = ".svg"
            output_path = output_path + ".svg"

        # Delegate to the real prisma.flow_diagram generator.
        try:
            from prisma.flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts
            # from_dict tolerantly normalises n_excluded_with_reasons.
            stage = PRISMAStageCounts.from_dict(counts.get("stage_counts") or {})
            gen = PRISMAFlowGenerator(stage, title=title)
            if ext == ".svg":
                written = gen.render_svg(output_path)
            elif ext == ".png":
                written = gen.render_png(output_path)
            else:
                written = gen.render_pdf(output_path)
            logger.info(
                "PRISMA flow diagram written via prisma.flow_diagram -> %s",
                written,
            )
            return written
        except ImportError:
            logger.info(
                "prisma.flow_diagram not available; using built-in "
                "fallback flow-diagram renderer."
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "prisma.flow_diagram delegation failed (%s); using fallback.", exc
            )

        # fallback: self-contained renderer (SVG directly; PNG/PDF via
        # matplotlib rendering of the same layout).
        svg = self._render_svg_flow(counts, title)
        if ext == ".svg":
            with open(output_path, "w", encoding="utf-8") as fh:
                fh.write(svg)
            logger.info("Wrote PRISMA SVG flow diagram to %s", output_path)
            return output_path
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

        stage = counts.get("stage_counts") or {}
        sc = self._collect_stage_counts(stage or None) if stage else {}

        def _n(key: str, fallback: int = 0) -> int:
            v = (sc.get(key) if sc else None)
            if v is None:
                v = stage.get(key)
            return int(v) if v is not None else fallback

        ta_excl = _n("n_records_excluded_title_abstract")
        ft_excl = _n("n_full_text_excluded")
        # box layout — exclusions are split per stage (T/A vs full-text),
        # never merged into one lumped "(included above)" box.
        boxes = [
            (1.0, 8.5, 4.0, 1.2,
             f"Identification\n(records: {counts.get('identification', 0)})"),
            (5.5, 8.5, 4.0, 1.2,
             f"Duplicates removed\n({counts.get('duplicates_removed', 0)})"),
            (1.0, 6.5, 4.0, 1.2,
             f"Title/abstract screened\n({counts.get('title_abstract', 0)})"),
            (5.5, 6.5, 4.0, 1.2,
             f"Excluded at title/abstract\n(n={ta_excl})"),
            (1.0, 4.5, 4.0, 1.2,
             f"Full-text assessed\n({counts.get('full_text', 0)})"),
            (5.5, 4.5, 4.0, 1.2,
             f"Excluded at full-text\n(n={ft_excl})"),
            (1.0, 2.5, 4.0, 1.2,
             f"Included in synthesis\n({counts.get('included', 0)})"),
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
    def _render_svg_flow(counts: Dict[str, Any], title: str) -> str:
        """Render a minimal self-contained SVG flow diagram (fallback)."""
        stage = counts.get("stage_counts") or {}
        try:
            sc = PRISMAIntegration._collect_stage_counts(stage or None) \
                if stage else {}
        except Exception:
            sc = {}

        def _n(key: str, fallback: int = 0) -> int:
            v = (sc.get(key) if sc else None)
            if v is None:
                v = stage.get(key)
            return int(v) if v is not None else fallback

        ta_excl = _n("n_records_excluded_title_abstract")
        ft_excl = _n("n_full_text_excluded")
        box_w, box_h = 320, 70
        x_left = 60
        x_right = 480
        y_start = 60
        gap = 50
        rows = [
            f"Identification: {counts.get('identification', 0)} records",
            f"Duplicates removed: {counts.get('duplicates_removed', 0)}",
            f"Title/abstract screened: {counts.get('title_abstract', 0)}",
            f"Excluded at title/abstract: {ta_excl}",
            f"Full-text assessed: {counts.get('full_text', 0)}",
            f"Excluded at full-text: {ft_excl}",
            f"Included in synthesis: {counts.get('included', 0)}",
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
                    scalar = ", ".join(
                        f"{k}={counts.get(k, 0)}"
                        for k in ("identification", "title_abstract",
                                  "full_text", "included", "excluded",
                                  "duplicates_removed", "total")
                    )
                    flow.append(Paragraph(
                        "<b>Counts:</b> " + scalar, styles["BodyText"]))
                    for w in counts.get("warnings", []):
                        flow.append(Paragraph(
                            f"<b>Warning:</b> {w}", styles["BodyText"]))
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
                for k in ("identification", "title_abstract", "full_text",
                          "included", "excluded", "duplicates_removed", "total"):
                    lines.append(f"- **{k}**: {counts.get(k, 0)}")
                lines.append("")
                for note in counts.get("notes", []):
                    lines.append(f"> {note}")
                    lines.append("")
                if counts.get("warnings"):
                    lines.append("### Flow validation warnings")
                    lines.append("")
                    for w in counts["warnings"]:
                        lines.append(f"- ⚠ {w}")
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
        """Return the official 27-item PRISMA 2020 checklist as dicts.

        Single source of truth: :mod:`prisma.checklist` (Page MJ et al.,
        BMJ 2021;372:n71). Falls back to a stub pointing at the official
        publication when the sibling package is unavailable.
        """
        return _load_official_checklist()

    def prisma_extensions(self) -> Dict[str, Dict[str, Any]]:
        """Return the 6 known PRISMA extensions (IPD, NMA, ScR, Harms, Abstract, Diagnostic).

        Each value is a dict with ``full_name``, ``description`` and
        ``items`` keys.
        """
        # deep copy to keep module constant pristine
        return _json.loads(_json.dumps(_PRISMA_EXTENSIONS))
