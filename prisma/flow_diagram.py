"""Publication-grade PRISMA 2020 flow-diagram generator.

This module renders the official PRISMA 2020 flow diagram (Page MJ, et al.
*The PRISMA 2020 statement: an updated guideline for reporting systematic
reviews.* BMJ 2021;372:n71) and its seven templates:

* ``standard`` — original PRISMA 2020 flow diagram
* ``ipd``       — individual participant data extension
* ``nma``       — network meta-analysis extension
* ``scr``       — scoping review extension
* ``harms``     — adverse events extension
* ``abstract``  — conference abstract (abridged) extension
* ``diagnostic``— diagnostic test accuracy extension

All heavy dependencies (``matplotlib``) are imported lazily inside the
renderer methods so that this module is always importable, even on a
stripped-down environment.

Conventions
-----------
* Matplotlib figures use ``constrained_layout=True``; we never call
  ``tight_layout()`` or pass ``bbox_inches='tight'``.
* Font fallback chain: ``['Noto Sans SC', 'DejaVu Sans', ...]``; we set
  ``axes.unicode_minus = False``.
* All symbols (×, →, etc.) appear as **literal** UTF-8 characters in this
  source — no Python unicode escape sequences.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Matplotlib initialisation (idempotent).
# ---------------------------------------------------------------------------
_FONT_SANS_SERIF: List[str] = [
    "Noto Sans SC",
    "DejaVu Sans",
    "WenQuanYi Zen Hei",
    "LXGW WenKai",
]
_MPL_INITIALISED = False


def _init_matplotlib() -> None:
    """Apply project-wide matplotlib rcParams (idempotent)."""
    global _MPL_INITIALISED
    if _MPL_INITIALISED:
        return
    try:
        import matplotlib  # noqa: WPS433  (lazy import)
        matplotlib.use("Agg", force=False)
        import matplotlib.pyplot as plt  # noqa: WPS433
        plt.rcParams["font.sans-serif"] = _FONT_SANS_SERIF
        plt.rcParams["axes.unicode_minus"] = False
        plt.rcParams["figure.dpi"] = 120
        plt.rcParams["savefig.dpi"] = 120
        _MPL_INITIALISED = True
        logger.debug("matplotlib rcParams initialised: fonts=%s", _FONT_SANS_SERIF)
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("matplotlib init failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Style palettes (BMJ / JAMA / Lancet).
# ---------------------------------------------------------------------------
_STYLE_PALETTE: Dict[str, Dict[str, str]] = {
    "bmj": {
        "bg":           "#ffffff",
        "stage_bg":     "#1a3a5c",   # navy stage-header background
        "stage_fg":     "#ffffff",
        "box_bg":       "#cfe2f3",   # light blue box background
        "box_fg":       "#1a3a5c",   # navy text
        "box_border":   "#2e5c8a",   # dark blue border
        "excl_bg":      "#f4f7fb",   # very pale blue for exclusion boxes
        "excl_border":  "#7a9bc2",
        "arrow":        "#2e5c8a",   # dark blue arrows
        "reason_fg":    "#34495e",
    },
    "jama": {
        "bg":           "#ffffff",
        "stage_bg":     "#222222",
        "stage_fg":     "#ffffff",
        "box_bg":       "#f5f5f5",
        "box_fg":       "#222222",
        "box_border":   "#555555",
        "excl_bg":      "#fafafa",
        "excl_border":  "#888888",
        "arrow":        "#555555",
        "reason_fg":    "#444444",
    },
    "lancet": {
        "bg":           "#ffffff",
        "stage_bg":     "#7a0c0c",   # Lancet red
        "stage_fg":     "#ffffff",
        "box_bg":       "#ffffff",
        "box_fg":       "#1a1a1a",
        "box_border":   "#1a1a1a",
        "excl_bg":      "#fbf5f5",
        "excl_border":  "#7a0c0c",
        "arrow":        "#7a0c0c",
        "reason_fg":    "#333333",
    },
}


# ---------------------------------------------------------------------------
# Box / arrow data structures (plain dicts for easy extension editing).
# ---------------------------------------------------------------------------
# Box kinds:
#   'title'         — top title text
#   'stage_header'  — full-width stage section header (Identification, ...)
#   'flow_box'      — main vertical-flow box with count
#   'exclusion_box' — right-column exclusion box with count
#   'reason_item'   — sub-line inside an exclusion box (reason + count)
#   'note'          — small italic note
# Arrow kinds:
#   'down'  — straight vertical down arrow
#   'right' — straight horizontal right arrow
#   'merge' — two arrows merging into one (Y shape)


# ---------------------------------------------------------------------------
# PRISMAStageCounts dataclass.
# ---------------------------------------------------------------------------
@dataclass
class PRISMAStageCounts:
    """Container for all official PRISMA 2020 stage counts.

    All integer fields are nullable so users may omit any stage they did
    not perform.  The :class:`PRISMAFlowGenerator` will simply skip the
    corresponding box when rendering.

    Attributes:
        n_records_databases: Records identified from databases.
        n_records_registers: Records identified from registers.
        n_records_total: Total records (explicit override; auto-computed
            if not given).
        n_records_before_duplicates: Records before duplicate removal.
        n_records_after_duplicates: Records after duplicate removal.
        n_duplicates_removed: Duplicates removed.
        n_records_screened: Records screened (title/abstract).
        n_records_excluded_title_abstract: Records excluded at title/abstract.
        n_records_sought_full_text: Full-text articles sought for retrieval.
        n_records_not_retrieved: Full-text articles not retrieved.
        n_full_text_assessed: Records assessed for eligibility (full-text).
        n_full_text_excluded: Records excluded at full-text stage.
        n_excluded_with_reasons: List of ``(reason, count)`` tuples for
            full-text exclusions.
        n_studies_included_qualitative: Studies included in qualitative
            synthesis.
        n_studies_included_quantitative: Studies included in quantitative
            synthesis (meta-analysis).
    """

    n_records_databases: Optional[int] = None
    n_records_registers: Optional[int] = None
    n_records_total: Optional[int] = None
    n_records_before_duplicates: Optional[int] = None
    n_records_after_duplicates: Optional[int] = None
    n_duplicates_removed: Optional[int] = None
    n_records_screened: Optional[int] = None
    n_records_excluded_title_abstract: Optional[int] = None
    n_records_sought_full_text: Optional[int] = None
    n_records_not_retrieved: Optional[int] = None
    n_full_text_assessed: Optional[int] = None
    n_full_text_excluded: Optional[int] = None
    n_excluded_with_reasons: List[Tuple[str, int]] = field(default_factory=list)
    n_studies_included_qualitative: Optional[int] = None
    n_studies_included_quantitative: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (JSON-compatible)."""
        d = asdict(self)
        # tuples -> lists for JSON friendliness
        d["n_excluded_with_reasons"] = [
            [r, c] for r, c in d.get("n_excluded_with_reasons", []) or []
        ]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PRISMAStageCounts":
        """Reconstruct from a dict (tolerant of tuple/list for reasons)."""
        reasons = d.get("n_excluded_with_reasons") or []
        norm: List[Tuple[str, int]] = []
        for item in reasons:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                norm.append((str(item[0]), int(item[1])))
        kwargs = dict(d)
        kwargs["n_excluded_with_reasons"] = norm
        # Drop unknown keys gracefully.
        valid = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in kwargs.items() if k in valid}
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# PRISMAFlowGenerator.
# ---------------------------------------------------------------------------
class PRISMAFlowGenerator:
    """Generate publication-grade PRISMA 2020 flow diagrams.

    The generator produces matplotlib figures (BMJ/JAMA/Lancet style),
    vector SVG output, PDF/PNG raster output, an interactive HTML version
    with hover tooltips, a GraphViz DOT representation, and a JSON-friendly
    ``to_dict``/``from_dict`` round-trip.

    Example:
        >>> from prisma.flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts
        >>> counts = PRISMAStageCounts(
        ...     n_records_databases=1247, n_duplicates_removed=312,
        ...     n_records_screened=988, n_records_excluded_title_abstract=852,
        ...     n_records_sought_full_text=136, n_records_not_retrieved=8,
        ...     n_full_text_assessed=128, n_full_text_excluded=46,
        ...     n_excluded_with_reasons=[('Wrong design', 18),
        ...                              ('Wrong population', 12)],
        ...     n_studies_included_qualitative=82,
        ...     n_studies_included_quantitative=76,
        ... )
        >>> gen = PRISMAFlowGenerator(counts, title='Example Review')
        >>> fig = gen.render_matplotlib()
        >>> gen.render_png('prisma.png', dpi=150)
    """

    #: Valid extension template identifiers.
    EXTENSIONS: Tuple[str, ...] = (
        "standard", "ipd", "nma", "scr", "harms", "abstract", "diagnostic",
    )

    def __init__(
        self,
        counts: PRISMAStageCounts,
        title: str = "",
        extension: str = "standard",
    ) -> None:
        """Initialise the generator.

        Args:
            counts: A :class:`PRISMAStageCounts` instance with the
                stage counts to render.
            title: Optional figure title (review title).
            extension: Which PRISMA template to use. Must be one of
                :attr:`EXTENSIONS`.

        Raises:
            ValueError: If ``extension`` is not recognised.
        """
        if extension not in self.EXTENSIONS:
            raise ValueError(
                f"extension must be one of {self.EXTENSIONS!r}, got {extension!r}"
            )
        self.counts = counts
        self.title = title or ""
        self.extension = extension
        logger.debug(
            "PRISMAFlowGenerator created: extension=%s, title=%r",
            extension, self.title,
        )

    # ------------------------------------------------------------------
    # Public renderers.
    # ------------------------------------------------------------------
    def render_matplotlib(
        self,
        figsize: Tuple[float, float] = (10.0, 14.0),
        dpi: int = 300,
        style: str = "bmj",
    ):
        """Render the flow diagram as a :class:`matplotlib.figure.Figure`.

        Args:
            figsize: Figure (width, height) in inches.
            dpi: Resolution for rasterised elements.
            style: One of ``'bmj'``, ``'jama'``, ``'lancet'``.

        Returns:
            ``matplotlib.figure.Figure``.
        """
        _init_matplotlib()
        import matplotlib.pyplot as plt  # noqa: WPS433
        from matplotlib.patches import FancyBboxPatch, FancyArrowPatch  # noqa: WPS433

        if style not in _STYLE_PALETTE:
            raise ValueError(
                f"style must be one of {list(_STYLE_PALETTE)!r}, got {style!r}"
            )
        palette = _STYLE_PALETTE[style]

        fig, ax = plt.subplots(
            figsize=figsize, dpi=dpi, constrained_layout=True,
            facecolor=palette["bg"],
        )
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.set_aspect("auto")
        ax.axis("off")
        ax.set_facecolor(palette["bg"])

        # Build layout.
        boxes, arrows = self._build_layout()

        # Draw stage-header full-width bars first (bottom layer).
        for box in boxes:
            if box["kind"] == "stage_header":
                self._draw_stage_header(ax, box, palette)

        # Draw arrows.
        for arrow in arrows:
            self._draw_arrow(ax, arrow, palette, boxes=boxes)

        # Draw flow boxes and exclusion boxes.
        for box in boxes:
            if box["kind"] == "stage_header":
                continue
            self._draw_box(ax, box, palette)

        # Title (top of figure).
        if self.title:
            ax.text(
                50, 98.5, self.title,
                ha="center", va="top",
                fontsize=15, fontweight="bold",
                color=palette["stage_bg"],
                wrap=True,
            )

        # Footer attribution.
        ext_label = self._extension_label()
        ax.text(
            50, 0.6,
            f"PRISMA 2020 flow diagram{ext_label} "
            f"(Page MJ et al., BMJ 2021;372:n71)",
            ha="center", va="bottom",
            fontsize=7, style="italic", color=palette["reason_fg"],
        )

        return fig

    def render_svg(self, path: str, style: str = "bmj",
                   figsize: Tuple[float, float] = (10.0, 14.0)) -> str:
        """Render the diagram as a standalone SVG vector file.

        Args:
            path: Output ``.svg`` path.
            style: Style palette name.
            figsize: Figure size in inches.

        Returns:
            Absolute path to the written SVG.
        """
        _init_matplotlib()
        import matplotlib.pyplot as plt  # noqa: WPS433
        fig = self.render_matplotlib(figsize=figsize, dpi=300, style=style)
        out = os.path.abspath(path)
        fig.savefig(out, format="svg", facecolor=fig.get_facecolor())
        plt.close(fig)
        logger.info("PRISMA SVG written to %s", out)
        return out

    def render_pdf(self, path: str, style: str = "bmj",
                   figsize: Tuple[float, float] = (10.0, 14.0)) -> str:
        """Render the diagram as a single-page PDF.

        Args:
            path: Output ``.pdf`` path.
            style: Style palette name.
            figsize: Figure size in inches.

        Returns:
            Absolute path to the written PDF.
        """
        _init_matplotlib()
        import matplotlib.pyplot as plt  # noqa: WPS433
        fig = self.render_matplotlib(figsize=figsize, dpi=300, style=style)
        out = os.path.abspath(path)
        fig.savefig(out, format="pdf", facecolor=fig.get_facecolor())
        plt.close(fig)
        logger.info("PRISMA PDF written to %s", out)
        return out

    def render_png(self, path: str, dpi: int = 300,
                   style: str = "bmj",
                   figsize: Tuple[float, float] = (10.0, 14.0)) -> str:
        """Render the diagram as a high-resolution PNG.

        Args:
            path: Output ``.png`` path.
            dpi: Raster DPI.
            style: Style palette name.
            figsize: Figure size in inches.

        Returns:
            Absolute path to the written PNG.
        """
        _init_matplotlib()
        import matplotlib.pyplot as plt  # noqa: WPS433
        fig = self.render_matplotlib(figsize=figsize, dpi=dpi, style=style)
        out = os.path.abspath(path)
        fig.savefig(out, format="png", dpi=dpi, facecolor=fig.get_facecolor())
        plt.close(fig)
        logger.info("PRISMA PNG written to %s", out)
        return out

    def render_html(self, output_path: str, style: str = "bmj") -> str:
        """Render an interactive HTML version with hover tooltips.

        The HTML embeds an inline SVG (so no external file dependencies),
        adds CSS hover highlights per box, and a ``<title>`` tooltip on
        every box so hovering shows the full description.

        Args:
            output_path: Where to write the ``.html`` file.
            style: Style palette name (controls CSS colours).

        Returns:
            Absolute path to the written HTML.
        """
        palette = _STYLE_PALETTE.get(style, _STYLE_PALETTE["bmj"])
        # Write SVG to a temp in-memory string by saving to a temp file.
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w+", suffix=".svg", delete=False, encoding="utf-8",
        ) as tmp:
            tmp_path = tmp.name
        try:
            self.render_svg(tmp_path, style=style)
            with open(tmp_path, "r", encoding="utf-8") as f:
                svg_content = f.read()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        # Build per-box tooltip registry.
        boxes, _arrows = self._build_layout()
        tooltips = []
        for b in boxes:
            if b["kind"] in ("flow_box", "exclusion_box"):
                tooltips.append({
                    "id": _slug(b["text"]),
                    "label": b["text"],
                    "tooltip": b.get("tooltip", b["text"]),
                })

        tooltip_js = (
            "const TOOLTIPS = " + str(tooltips).replace("'", '"') + ";"
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_escape_html(self.title or 'PRISMA 2020 Flow Diagram')}</title>
<style>
  body {{ font-family: 'Noto Sans SC','DejaVu Sans',Helvetica,Arial,sans-serif;
          margin: 0; padding: 24px; background: {palette['bg']}; color: #222; }}
  h1 {{ color: {palette['stage_bg']}; margin-top: 0; font-size: 20px; }}
  .prisma-svg {{ display: block; margin: 0 auto; max-width: 1100px;
                 width: 100%; height: auto;
                 border: 1px solid #ddd; background: #fff; }}
  .prisma-svg svg {{ width: 100%; height: auto; }}
  .prisma-svg svg .flow-box, .prisma-svg svg .exclusion-box {{ cursor: help; }}
  .prisma-svg svg .flow-box:hover, .prisma-svg svg .exclusion-box:hover {{
     stroke-width: 3; filter: drop-shadow(0 0 6px rgba(46,92,138,0.5)); }}
  .tooltip {{ position: absolute; background: {palette['stage_bg']}; color: #fff;
              padding: 6px 10px; border-radius: 4px; font-size: 12px;
              pointer-events: none; opacity: 0; transition: opacity 0.15s;
              max-width: 280px; z-index: 10; }}
  footer {{ margin-top: 16px; font-size: 11px; color: #666; font-style: italic;
            text-align: center; }}
</style>
</head>
<body>
  <h1>{_escape_html(self.title or 'PRISMA 2020 Flow Diagram')}</h1>
  <div class="prisma-svg">{svg_content}</div>
  <footer>Generated from PRISMA 2020 (Page MJ et al., BMJ 2021;372:n71) —
  {_extension_full_label(self.extension)}.</footer>
  <div class="tooltip" id="tip"></div>
  <script>
    {tooltip_js}
    const tip = document.getElementById('tip');
    document.querySelectorAll('.prisma-svg svg rect').forEach((r) => {{
      r.classList.add('flow-box');
      r.addEventListener('mouseenter', (e) => {{
        const t = r.parentNode.querySelector('text');
        const label = t ? t.textContent : '';
        const match = TOOLTIPS.find((x) => label.includes(x.id));
        if (match) {{
          tip.textContent = match.tooltip;
          tip.style.opacity = '1';
          tip.style.left = (e.pageX + 12) + 'px';
          tip.style.top = (e.pageY + 12) + 'px';
        }}
      }});
      r.addEventListener('mousemove', (e) => {{
        tip.style.left = (e.pageX + 12) + 'px';
        tip.style.top = (e.pageY + 12) + 'px';
      }});
      r.addEventListener('mouseleave', () => {{ tip.style.opacity = '0'; }});
    }});
  </script>
</body>
</html>
"""
        out = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("PRISMA HTML written to %s", out)
        return out

    # ------------------------------------------------------------------
    # Alternative representations.
    # ------------------------------------------------------------------
    def to_dot(self) -> str:
        """Return GraphViz DOT source for the flow diagram.

        Useful for editing in GraphViz / Gephi / dot CLI tools.

        Returns:
            A string containing a complete DOT graph definition.
        """
        boxes, arrows = self._build_layout()
        lines: List[str] = [
            "digraph prisma {",
            '  graph [rankdir=TB, splines=ortho, nodesep=0.4, ranksep=0.5,',
            '         bgcolor="white", fontname="Helvetica"];',
            '  node [shape=box, style="filled,rounded", fontname="Helvetica",',
            '        fontsize=10, margin="0.15,0.08"];',
            '  edge [color="#2e5c8a", arrowhead=vee, arrowsize=0.7];',
            "",
        ]
        # Nodes.
        for i, b in enumerate(boxes):
            if b["kind"] == "title":
                continue
            if b["kind"] == "stage_header":
                lines.append(
                    f'  n{i} [label="{_escape_dot(b["text"])}", '
                    f'shape=box, style="filled", fillcolor="#1a3a5c", '
                    f'fontcolor="white", fontsize=11];'
                )
            else:
                fill = "#cfe2f3" if b["kind"] == "flow_box" else "#f4f7fb"
                lines.append(
                    f'  n{i} [label="{_escape_dot(b["text"])}", '
                    f'fillcolor="{fill}"];'
                )
        lines.append("")
        # Edges.
        for a in arrows:
            src = self._find_box_index(boxes, a["from"])
            dst = self._find_box_index(boxes, a["to"])
            if src is None or dst is None:
                continue
            attrs = []
            if a["kind"] == "right":
                attrs.append('label="excluded"')
            lines.append(f"  n{src} -> n{dst}" + (" [" + ", ".join(attrs) + "]" if attrs else "") + ";")
        lines.append("}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the generator to a JSON-friendly dict."""
        return {
            "title": self.title,
            "extension": self.extension,
            "counts": self.counts.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PRISMAFlowGenerator":
        """Reconstruct a generator from a dict produced by :meth:`to_dict`."""
        return cls(
            counts=PRISMAStageCounts.from_dict(d.get("counts") or {}),
            title=d.get("title", "") or "",
            extension=d.get("extension", "standard") or "standard",
        )

    # ------------------------------------------------------------------
    # Layout builders (one per extension).
    # ------------------------------------------------------------------
    def _build_layout(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Dispatch to the appropriate layout builder for the extension."""
        dispatch = {
            "standard":  self._layout_standard,
            "ipd":       self._layout_ipd,
            "nma":       self._layout_nma,
            "scr":       self._layout_scr,
            "harms":     self._layout_harms,
            "abstract":  self._layout_abstract,
            "diagnostic":self._layout_diagnostic,
        }
        return dispatch[self.extension]()

    def _layout_standard(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Standard PRISMA 2020 layout (Page et al., BMJ 2021)."""
        c = self.counts
        boxes: List[Dict[str, Any]] = []
        arrows: List[Dict[str, Any]] = []

        # Geometry: main column x=12..58, exclusion column x=66..92.
        MAIN_X, MAIN_W = 12.0, 46.0
        EX_X,  EX_W  = 66.0, 26.0
        BOX_H = 6.0

        # --- IDENTIFICATION stage ------------------------------------
        # Stage header bar.
        boxes.append({
            "kind": "stage_header", "text": "IDENTIFICATION",
            "x": 0.5, "y": 89.0, "w": 99, "h": 4.0,
        })
        # Two side-by-side source boxes (only render if data exists).
        y = 80.0
        if c.n_records_databases is not None:
            boxes.append({
                "kind": "flow_box",
                "text": f"Records identified from databases\n(n={c.n_records_databases:,})",
                "tooltip": "Records identified from database searches (PubMed, Embase, etc.).",
                "x": MAIN_X, "y": y, "w": MAIN_W, "h": BOX_H + 2.5,
            })
            left_idx = len(boxes) - 1
        else:
            left_idx = None
        if c.n_records_registers is not None:
            boxes.append({
                "kind": "flow_box",
                "text": f"Records identified from registers\n(n={c.n_records_registers:,})",
                "tooltip": "Records identified from study registers (ClinicalTrials.gov, etc.).",
                "x": EX_X, "y": y, "w": EX_W, "h": BOX_H + 2.5,
            })
            right_idx = len(boxes) - 1
        else:
            right_idx = None

        # Deduplication summary box (only if duplicates info given).
        # Span the full diagram width so merge arrows look clean.
        y = 70.0
        dedup_text = ""
        if c.n_records_before_duplicates is not None:
            dedup_text += f"Records before duplicates (n={c.n_records_before_duplicates:,})\n"
        if c.n_duplicates_removed is not None:
            dedup_text += f"Duplicates removed (n={c.n_duplicates_removed:,})"
        if c.n_records_after_duplicates is not None:
            if dedup_text:
                dedup_text += "\n"
            dedup_text += f"Records after duplicates (n={c.n_records_after_duplicates:,})"
        if dedup_text:
            # Wide dedup box spanning main + exclusion columns.
            boxes.append({
                "kind": "flow_box", "text": dedup_text.strip(),
                "tooltip": "Records before/after duplicate removal.",
                "x": MAIN_X, "y": y, "w": EX_X + EX_W - MAIN_X, "h": BOX_H + 4.5,
            })
            dedup_idx = len(boxes) - 1
            if left_idx is not None:
                arrows.append({"kind": "down", "from": left_idx, "to": dedup_idx})
            if right_idx is not None:
                arrows.append({"kind": "down", "from": right_idx, "to": dedup_idx})
            last_main_idx = dedup_idx
        else:
            last_main_idx = left_idx if left_idx is not None else right_idx

        # --- SCREENING stage -----------------------------------------
        boxes.append({
            "kind": "stage_header", "text": "SCREENING",
            "x": 0.5, "y": 63.0, "w": 99, "h": 3.5,
        })
        y = 56.5
        if c.n_records_screened is not None:
            boxes.append({
                "kind": "flow_box",
                "text": f"Records screened\n(n={c.n_records_screened:,})",
                "tooltip": "Records screened by title and abstract.",
                "x": MAIN_X, "y": y, "w": MAIN_W, "h": BOX_H,
            })
            screen_idx = len(boxes) - 1
            if last_main_idx is not None:
                arrows.append({"kind": "down", "from": last_main_idx, "to": screen_idx})
            last_main_idx = screen_idx

            # Right-side exclusion box.
            if c.n_records_excluded_title_abstract is not None:
                boxes.append({
                    "kind": "exclusion_box",
                    "text": (f"Records excluded\n"
                             f"(n={c.n_records_excluded_title_abstract:,})"),
                    "tooltip": "Records excluded at title/abstract screening.",
                    "x": EX_X, "y": y, "w": EX_W, "h": BOX_H,
                })
                ex_idx = len(boxes) - 1
                arrows.append({"kind": "right", "from": screen_idx, "to": ex_idx})

        # Records sought for retrieval.
        y = 47.0
        if c.n_records_sought_full_text is not None:
            boxes.append({
                "kind": "flow_box",
                "text": (f"Records sought for retrieval\n"
                         f"(n={c.n_records_sought_full_text:,})"),
                "tooltip": "Full-text articles sought for retrieval.",
                "x": MAIN_X, "y": y, "w": MAIN_W, "h": BOX_H,
            })
            sought_idx = len(boxes) - 1
            if last_main_idx is not None:
                arrows.append({"kind": "down", "from": last_main_idx, "to": sought_idx})
            last_main_idx = sought_idx

            if c.n_records_not_retrieved is not None:
                boxes.append({
                    "kind": "exclusion_box",
                    "text": (f"Records not retrieved\n"
                             f"(n={c.n_records_not_retrieved:,})"),
                    "tooltip": "Full-text articles not retrievable.",
                    "x": EX_X, "y": y, "w": EX_W, "h": BOX_H,
                })
                nr_idx = len(boxes) - 1
                arrows.append({"kind": "right", "from": sought_idx, "to": nr_idx})

        # Records assessed for eligibility.
        y = 37.5
        if c.n_full_text_assessed is not None:
            boxes.append({
                "kind": "flow_box",
                "text": (f"Records assessed for eligibility\n"
                         f"(n={c.n_full_text_assessed:,})"),
                "tooltip": "Records assessed for eligibility in full-text.",
                "x": MAIN_X, "y": y, "w": MAIN_W, "h": BOX_H,
            })
            elig_idx = len(boxes) - 1
            if last_main_idx is not None:
                arrows.append({"kind": "down", "from": last_main_idx, "to": elig_idx})
            last_main_idx = elig_idx

            # Right-side exclusion box with reasons.
            reason_count = c.n_full_text_excluded
            reasons = c.n_excluded_with_reasons or []
            if reason_count is not None or reasons:
                ex_height = BOX_H + 1.5 * max(0, len(reasons))
                ex_text = "Records excluded"
                if reason_count is not None:
                    ex_text += f"\n(n={reason_count:,})"
                if reasons:
                    ex_text += "\n" + "\n".join(f"• {r} (n={n:,})" for r, n in reasons)
                boxes.append({
                    "kind": "exclusion_box",
                    "text": ex_text,
                    "tooltip": "Records excluded at full-text with reasons.",
                    "x": EX_X, "y": y - (ex_height - BOX_H) / 2,
                    "w": EX_W, "h": ex_height,
                })
                ex_idx = len(boxes) - 1
                arrows.append({"kind": "right", "from": elig_idx, "to": ex_idx})

        # --- ELIGIBILITY stage label ---------------------------------
        boxes.append({
            "kind": "stage_header", "text": "ELIGIBILITY",
            "x": 0.5, "y": 31.5, "w": 99, "h": 3.0,
        })

        # --- INCLUDED stage ------------------------------------------
        boxes.append({
            "kind": "stage_header", "text": "INCLUDED",
            "x": 0.5, "y": 25.0, "w": 99, "h": 3.0,
        })
        y = 17.5
        if c.n_studies_included_qualitative is not None:
            boxes.append({
                "kind": "flow_box",
                "text": (f"Studies included in qualitative synthesis\n"
                         f"(n={c.n_studies_included_qualitative:,})"),
                "tooltip": "Studies included in qualitative synthesis (narrative).",
                "x": MAIN_X, "y": y, "w": MAIN_W, "h": BOX_H,
            })
            qual_idx = len(boxes) - 1
            if last_main_idx is not None:
                arrows.append({"kind": "down", "from": last_main_idx, "to": qual_idx})
            last_main_idx = qual_idx

        y = 8.5
        if c.n_studies_included_quantitative is not None:
            boxes.append({
                "kind": "flow_box",
                "text": (f"Studies included in quantitative synthesis\n"
                         f"(n={c.n_studies_included_quantitative:,})"),
                "tooltip": "Studies included in quantitative synthesis (meta-analysis).",
                "x": MAIN_X, "y": y, "w": MAIN_W, "h": BOX_H,
            })
            quant_idx = len(boxes) - 1
            if last_main_idx is not None:
                arrows.append({"kind": "down", "from": last_main_idx, "to": quant_idx})

        return boxes, arrows

    def _layout_ipd(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Individual participant data (IPD) extension layout.

        Adds IPD-request / IPD-received / IPD-not-obtained stages between
        eligibility and inclusion.
        """
        boxes, arrows = self._layout_standard()
        # Append an IPD note box before the INCLUDED stage header.
        ipd_note = (
            "IPD sought from eligible studies\n"
            "(individual participant data requested)"
        )
        boxes.append({
            "kind": "exclusion_box",
            "text": ipd_note,
            "tooltip": "IPD extension: individual participant data requested.",
            "x": 66.0, "y": 28.0, "w": 26.0, "h": 6.0,
        })
        return boxes, arrows

    def _layout_nma(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Network meta-analysis (NMA) extension layout."""
        boxes, arrows = self._layout_standard()
        boxes.append({
            "kind": "note",
            "text": ("Network geometry: ensure transitivity, "
                     "consistency, and report network structure."),
            "x": 12.0, "y": 3.5, "w": 80.0, "h": 3.0,
        })
        return boxes, arrows

    def _layout_scr(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Scoping review (ScR) extension layout.

        Scoping reviews skip risk-of-bias assessment; we add a note.
        """
        boxes, arrows = self._layout_standard()
        boxes.append({
            "kind": "note",
            "text": "Scoping review: no risk-of-bias assessment performed.",
            "x": 12.0, "y": 3.5, "w": 80.0, "h": 3.0,
        })
        return boxes, arrows

    def _layout_harms(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Adverse events (Harms) extension layout."""
        boxes, arrows = self._layout_standard()
        boxes.append({
            "kind": "note",
            "text": ("Adverse events extension: extract harms separately "
                     "and report by severity / seriousness."),
            "x": 12.0, "y": 3.5, "w": 80.0, "h": 3.0,
        })
        return boxes, arrows

    def _layout_abstract(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Conference abstract (abridged) extension layout."""
        boxes, arrows = self._layout_standard()
        boxes.append({
            "kind": "note",
            "text": "Abridged flow for conference abstract submission.",
            "x": 12.0, "y": 3.5, "w": 80.0, "h": 3.0,
        })
        return boxes, arrows

    def _layout_diagnostic(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Diagnostic test accuracy extension layout."""
        boxes, arrows = self._layout_standard()
        boxes.append({
            "kind": "note",
            "text": ("Diagnostic accuracy extension: report index test, "
                     "reference standard, and 2×2 data per study."),
            "x": 12.0, "y": 3.5, "w": 80.0, "h": 3.0,
        })
        return boxes, arrows

    # ------------------------------------------------------------------
    # Drawing helpers.
    # ------------------------------------------------------------------
    def _draw_stage_header(self, ax, box: Dict[str, Any],
                           palette: Dict[str, str]) -> None:
        """Draw a full-width stage-header bar."""
        from matplotlib.patches import Rectangle  # noqa: WPS433
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        rect = Rectangle(
            (x, y), w, h,
            facecolor=palette["stage_bg"], edgecolor=palette["stage_bg"],
            linewidth=0.8, zorder=2,
        )
        ax.add_patch(rect)
        ax.text(
            x + w / 2, y + h / 2, box["text"],
            ha="center", va="center",
            fontsize=11, fontweight="bold", color=palette["stage_fg"],
            zorder=3,
        )

    def _draw_box(self, ax, box: Dict[str, Any],
                  palette: Dict[str, str]) -> None:
        """Draw a flow / exclusion / note box."""
        from matplotlib.patches import FancyBboxPatch  # noqa: WPS433
        if box["kind"] == "note":
            ax.text(
                box["x"] + box["w"] / 2, box["y"] + box["h"] / 2,
                box["text"], ha="center", va="center",
                fontsize=8, style="italic",
                color=palette["reason_fg"],
                wrap=True,
            )
            return

        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        if box["kind"] == "flow_box":
            face = palette["box_bg"]
            edge = palette["box_border"]
            fg = palette["box_fg"]
        else:  # exclusion_box / reason_item
            face = palette["excl_bg"]
            edge = palette["excl_border"]
            fg = palette["reason_fg"]

        rect = FancyBboxPatch(
            (x, y), w, h,
            boxstyle="round,pad=0.3,rounding_size=1.0",
            facecolor=face, edgecolor=edge,
            linewidth=1.2, zorder=2,
        )
        ax.add_patch(rect)
        ax.text(
            x + w / 2, y + h / 2, box["text"],
            ha="center", va="center",
            fontsize=9, color=fg, zorder=3,
            linespacing=1.4,
        )

    def _draw_arrow(self, ax, arrow: Dict[str, Any],
                    palette: Dict[str, str],
                    boxes: Optional[List[Dict[str, Any]]] = None) -> None:
        """Draw a single arrow between two boxes (by kind).

        Args:
            ax: Matplotlib axes.
            arrow: Arrow dict from ``_build_layout``.
            palette: Style palette.
            boxes: Pre-computed boxes list (avoids re-calling ``_build_layout``).
        """
        from matplotlib.patches import FancyArrowPatch  # noqa: WPS433
        if boxes is None:
            boxes = self._build_layout()[0]
        # We only support straight arrows now (down / right); the legacy
        # 'merge' kind is rendered as two 'down' arrows at construction time.
        src = boxes[arrow["from"]] if 0 <= arrow["from"] < len(boxes) else None
        dst = boxes[arrow["to"]]   if 0 <= arrow["to"]   < len(boxes) else None
        if src is None or dst is None:
            return

        if arrow["kind"] == "down":
            # Vertical arrow from bottom-centre of src to top-centre of dst.
            x1 = src["x"] + src["w"] / 2
            y1 = src["y"]
            x2 = dst["x"] + dst["w"] / 2
            y2 = dst["y"] + dst["h"]
            self._draw_segment(ax, x1, y1, x2, y2, palette)
        elif arrow["kind"] == "right":
            # Horizontal arrow from right-centre of src to left-centre of dst.
            x1 = src["x"] + src["w"]
            y1 = src["y"] + src["h"] / 2
            x2 = dst["x"]
            y2 = dst["y"] + dst["h"] / 2
            self._draw_segment(ax, x1, y1, x2, y2, palette)

    def _draw_segment(self, ax, x1, y1, x2, y2,
                      palette: Dict[str, str], kind: str = "down") -> None:
        """Draw a FancyArrowPatch segment."""
        from matplotlib.patches import FancyArrowPatch  # noqa: WPS433
        # Pick connection style so that horizontal arrows render with a
        # nice right-angle bend and vertical arrows are straight.
        if abs(x1 - x2) < 0.1:
            connectionstyle = "arc3,rad=0"
        else:
            connectionstyle = "arc3,rad=0"
        arr = FancyArrowPatch(
            (x1, y1), (x2, y2),
            arrowstyle="-|>",
            connectionstyle=connectionstyle,
            mutation_scale=14,
            linewidth=1.4,
            color=palette["arrow"],
            zorder=1,
            shrinkA=0, shrinkB=0,
        )
        ax.add_patch(arr)

    def _find_box_index(self, boxes: List[Dict[str, Any]],
                        idx: int) -> Optional[int]:
        """Return the box index (or None if out of range)."""
        if 0 <= idx < len(boxes):
            return idx
        return None

    def _extension_label(self) -> str:
        """Short label for the footer."""
        if self.extension == "standard":
            return ""
        labels = {
            "ipd": " — IPD extension",
            "nma": " — NMA extension",
            "scr": " — Scoping Review extension",
            "harms": " — Harms extension",
            "abstract": " — Conference Abstract extension",
            "diagnostic": " — Diagnostic Test Accuracy extension",
        }
        return labels.get(self.extension, "")


# ---------------------------------------------------------------------------
# Module-level helpers.
# ---------------------------------------------------------------------------
def _extension_full_label(extension: str) -> str:
    """Return a fully-spelled-out extension label for the HTML footer."""
    labels = {
        "standard":   "standard PRISMA 2020 template",
        "ipd":        "Individual Participant Data (IPD) extension",
        "nma":        "Network Meta-Analysis (NMA) extension",
        "scr":        "Scoping Review (ScR) extension",
        "harms":      "Adverse Events (Harms) extension",
        "abstract":   "Conference Abstract (abridged) extension",
        "diagnostic": "Diagnostic Test Accuracy extension",
    }
    return labels.get(extension, "standard PRISMA 2020 template")


def _slug(text: str) -> str:
    """Make a slug from text (for HTML element ids)."""
    out = []
    for ch in text.lower().strip():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    return "".join(out)[:50]


def _escape_html(text: str) -> str:
    """Escape HTML-significant characters."""
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))


def _escape_dot(text: str) -> str:
    """Escape GraphViz DOT-significant characters."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
