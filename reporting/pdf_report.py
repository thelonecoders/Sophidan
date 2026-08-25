"""Publication-quality PDF report generator built on ReportLab.

This module produces styled PDF reports with full CJK (Chinese / Japanese /
Korean) support.  Heavy dependencies (``reportlab``, ``matplotlib``,
``Pillow``) are imported lazily inside the methods so the module itself is
always importable, even on a stripped-down environment.

Character safety
-----------------
Per project convention we **never** use Python unicode escape sequences
(``\\u00d7`` etc.) for symbols.  All special characters (×, ÷, ±, ≤, ≥, →,
etc.) appear as **literal** characters in this source file, which is UTF-8
encoded.  Superscripts and subscripts use ReportLab's inline ``<super>`` and
``<sub>`` tags rather than Unicode codepoints.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import io
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Union

from ._paper_utils import (
    get_authors,
    get_citation_count,
    get_doi,
    get_field,
    get_str,
    get_year,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Font registration (Noto Serif SC body, Noto Sans SC headings, DejaVu symbols).
# ---------------------------------------------------------------------------
# Known filesystem locations for the fonts we prefer.  ReportLab's TTFont
# cannot handle variable OpenType fonts (Noto Sans SC's variable .ttf fails
# with "unpack requires a buffer of 2 bytes"), so we offer several fallback
# paths for each font family.
_FONT_CANDIDATES: Dict[str, List[str]] = {
    "NotoSerifSC": [
        "/usr/share/fonts/truetype/noto-serif-sc/NotoSerifSC-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifSC-Regular.otf",
        "/usr/share/fonts/noto-cjk/NotoSerifCJKsc-Regular.otf",
    ],
    "NotoSerifSC-Bold": [
        "/usr/share/fonts/truetype/noto-serif-sc/NotoSerifSC-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSerifSC-Bold.otf",
        "/usr/share/fonts/noto-cjk/NotoSerifCJKsc-Bold.otf",
    ],
    "NotoSerifSC-Italic": [
        # Noto Serif SC does not ship an italic face; fall back to regular.
        "/usr/share/fonts/truetype/noto-serif-sc/NotoSerifSC-Regular.ttf",
    ],
    "NotoSansSC": [
        # The variable .ttf is broken in ReportLab, but list it first in case
        # a non-variable version is added later.  Then fall back to WenQuanYi
        # Zen Hei (a sans-style CJK font that registers fine).
        "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/lxgw-wenkai/LXGWWenKai-Regular.ttf",
    ],
    "NotoSansSC-Bold": [
        "/usr/share/fonts/truetype/noto/NotoSansSC-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
        "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Bold.otf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/lxgw-wenkai/LXGWWenKai-Medium.ttf",
    ],
    "DejaVuSans": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    "DejaVuSans-Bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    "DejaVuSans-Oblique": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    ],
}

_FONTS_REGISTERED = False
_AVAILABLE_FONTS: Dict[str, str] = {}


def _register_fonts() -> None:
    """Register CJK + symbol fonts with ReportLab (idempotent).

    On failure (no reportlab, no font files), the function logs a warning and
    returns silently.  The :class:`PDFReport` constructor will then fall back
    to ReportLab's built-in Helvetica/Times faces.
    """
    global _FONTS_REGISTERED, _AVAILABLE_FONTS
    if _FONTS_REGISTERED:
        return
    _FONTS_REGISTERED = True
    try:
        from reportlab.pdfbase import pdfmetrics  # noqa: WPS433
        from reportlab.pdfbase.ttfonts import TTFont  # noqa: WPS433
        from reportlab.pdfbase.pdfmetrics import registerFontFamily  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - reportlab is required at runtime
        logger.warning("reportlab not installed; PDF CJK fonts unavailable: %s", exc)
        return

    for font_name, candidates in _FONT_CANDIDATES.items():
        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                # WenQuanYi is a .ttc collection; reportlab needs subfontIndex=0.
                kwargs: Dict[str, Any] = {}
                if path.endswith(".ttc"):
                    kwargs["subfontIndex"] = 0
                f = TTFont(font_name, path, **kwargs)
                pdfmetrics.registerFont(f)
                _AVAILABLE_FONTS[font_name] = path
                logger.debug("registered font %s -> %s", font_name, path)
                break
            except Exception as exc:
                logger.debug("font register failed %s @ %s: %s", font_name, path, exc)
                continue

    # Register font families so <b>/<i> tags work inside Paragraph.
    def _family(family: str, normal: str, bold: str, italic: str, bold_italic: str) -> None:
        if (
            normal in _AVAILABLE_FONTS
            and bold in _AVAILABLE_FONTS
            and italic in _AVAILABLE_FONTS
        ):
            try:
                registerFontFamily(
                    family,
                    normal=normal,
                    bold=bold,
                    italic=italic,
                    boldItalic=bold_italic or bold,
                )
            except Exception as exc:  # pragma: no cover
                logger.debug("registerFontFamily %s failed: %s", family, exc)

    _family("NotoSerifSC", "NotoSerifSC", "NotoSerifSC-Bold", "NotoSerifSC-Italic", "NotoSerifSC-Bold")
    _family("NotoSansSC", "NotoSansSC", "NotoSansSC-Bold", "NotoSansSC", "NotoSansSC-Bold")
    _family(
        "DejaVuSans",
        "DejaVuSans",
        "DejaVuSans-Bold",
        "DejaVuSans-Oblique",
        "DejaVuSans-Bold",
    )


def _pick_font(*candidates: str) -> str:
    """Return the first candidate font that was successfully registered."""
    for c in candidates:
        if c in _AVAILABLE_FONTS:
            return c
    return candidates[0]  # fall back to the first name even if not registered.


# ---------------------------------------------------------------------------
# ReportLab lazy imports.
# ---------------------------------------------------------------------------
def _rl_imports():
    """Lazy import of all reportlab symbols used by this module."""
    from reportlab.lib import colors  # noqa: WPS433
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY  # noqa: WPS433
    from reportlab.lib.pagesizes import letter, A4  # noqa: WPS433
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: WPS433
    from reportlab.lib.units import inch, cm  # noqa: WPS433
    from reportlab.platypus import (  # noqa: WPS433
        BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak, PageTemplate,
        Paragraph, Spacer, Table, TableStyle, KeepTogether,
    )
    from reportlab.platypus.tableofcontents import TableOfContents  # noqa: WPS433
    return dict(
        colors=colors, TA_CENTER=TA_CENTER, TA_LEFT=TA_LEFT, TA_JUSTIFY=TA_JUSTIFY,
        letter=letter, A4=A4, ParagraphStyle=ParagraphStyle,
        getSampleStyleSheet=getSampleStyleSheet, inch=inch, cm=cm,
        BaseDocTemplate=BaseDocTemplate, Frame=Frame, Image=Image,
        NextPageTemplate=NextPageTemplate, PageBreak=PageBreak,
        PageTemplate=PageTemplate, Paragraph=Paragraph, Spacer=Spacer,
        Table=Table, TableStyle=TableStyle, KeepTogether=KeepTogether,
        TableOfContents=TableOfContents,
    )


# ---------------------------------------------------------------------------
# Helper to escape stray XML-significant chars in plain text body content.
# We do NOT escape text the caller has explicitly tagged (<b>, <i>, <a>, ...),
# because Paragraph parses those as inline tags.  Callers with raw text should
# pass escape=True.
# ---------------------------------------------------------------------------
def _xml_escape(text: str) -> str:
    """Escape ``&``, ``<``, ``>`` for safe inclusion in a ReportLab Paragraph.

    This is intended for *user-supplied* text that should not contain
    intentional Paragraph markup.  Tag-bearing body strings (e.g. from
    :meth:`PDFReport.add_section`) are passed through unescaped.
    """
    if not text:
        return ""
    s = str(text)
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    return s


# ---------------------------------------------------------------------------
# Custom doc template that supports TOC entry collection + page numbers.
# ---------------------------------------------------------------------------
class _TocDocTemplate:
    """Placeholder so type hints resolve without importing reportlab at top.

    The real class is constructed inside :meth:`PDFReport.build` via
    ``_rl_imports()['BaseDocTemplate']``.
    """


def _make_toc_doc_template_cls(BaseDocTemplate, Paragraph):  # type: ignore[no-untyped-def]
    """Build a BaseDocTemplate subclass that captures H1/H2 entries for the TOC."""

    class _TocDocTemplateInner(BaseDocTemplate):  # type: ignore[misc]
        def afterFlowable(self, flowable):  # noqa: D401 - reportlab hook
            try:
                style_name = getattr(flowable.style, "name", "")
            except AttributeError:
                return
            if not isinstance(flowable, Paragraph):
                return
            text = flowable.getPlainText()
            if not text:
                return
            if style_name == "h1":
                self.notify("TOCEntry", (0, text, self.page))
            elif style_name == "h2":
                self.notify("TOCEntry", (1, text, self.page))

    return _TocDocTemplateInner


# ---------------------------------------------------------------------------
# Main class.
# ---------------------------------------------------------------------------
class PDFReport:
    """Build publication-quality PDF reports with CJK support.

    Usage::

        rpt = PDFReport("Survey of AI Methods", author="J. Doe")
        rpt.add_cover_page({...})
        rpt.add_section("Introduction", "Body text with <b>bold</b>...")
        rpt.add_papers_table(papers, columns=["title", "year", "citations"])
        rpt.add_chart(fig, caption="Publications over time")
        rpt.build("report.pdf")
    """

    def __init__(
        self,
        title: str,
        author: Optional[str] = None,
        subject: Optional[str] = None,
    ) -> None:
        """Initialise the report builder.

        Args:
            title: Report title (used in PDF metadata + cover page).
            author: Optional author string for PDF metadata.
            subject: Optional subject string for PDF metadata.
        """
        _register_fonts()
        self.title = title
        self.author = author
        self.subject = subject
        self._story: List[Any] = []
        # Lazy-import reportlab pieces we need for style setup.
        rl = _rl_imports()
        self._rl = rl
        self._styles = self._build_styles(rl)
        # Heading counters for the auto-generated TOC.
        self._section_number = 0
        self._subsection_number = 0

    # ------------------------------------------------------------------
    # Styles
    # ------------------------------------------------------------------
    def _build_styles(self, rl: Dict[str, Any]) -> Dict[str, Any]:
        """Build the project style sheet with CJK fonts registered.

        Falls back gracefully to ReportLab built-ins when Noto / WenQuanYi
        are unavailable.
        """
        ParagraphStyle = rl["ParagraphStyle"]
        getSampleStyleSheet = rl["getSampleStyleSheet"]

        body_font = _pick_font("NotoSerifSC", "DejaVuSans", "Times-Roman")
        body_bold = _pick_font("NotoSerifSC-Bold", "DejaVuSans-Bold", "Times-Bold")
        body_italic = _pick_font("NotoSerifSC-Italic", "DejaVuSans-Oblique", "Times-Italic")
        heading_font = _pick_font("NotoSansSC", "DejaVuSans", "Helvetica")

        styles = getSampleStyleSheet()
        custom: Dict[str, Any] = {}
        # Cover title: 24pt bold sans.
        custom["cover_title"] = ParagraphStyle(
            "cover_title",
            parent=styles["Title"],
            fontName=heading_font,
            fontSize=24,
            leading=30,
            alignment=rl["TA_CENTER"],
            spaceAfter=18,
        )
        # Cover subtitle / metadata: 12pt.
        custom["cover_meta"] = ParagraphStyle(
            "cover_meta",
            parent=styles["Normal"],
            fontName=body_font,
            fontSize=12,
            leading=16,
            alignment=rl["TA_CENTER"],
            textColor=rl["colors"].HexColor("#444444"),
        )
        # H1: 16pt bold sans.
        custom["h1"] = ParagraphStyle(
            "h1",
            parent=styles["Heading1"],
            fontName=heading_font,
            fontSize=16,
            leading=22,
            spaceBefore=18,
            spaceAfter=10,
            textColor=rl["colors"].HexColor("#2E5C8A"),
            keepWithNext=True,
        )
        # H2: 14pt bold sans.
        custom["h2"] = ParagraphStyle(
            "h2",
            parent=styles["Heading2"],
            fontName=heading_font,
            fontSize=14,
            leading=18,
            spaceBefore=12,
            spaceAfter=6,
            textColor=rl["colors"].HexColor("#2E5C8A"),
            keepWithNext=True,
        )
        # Body: 11pt serif (CJK-aware).
        custom["body"] = ParagraphStyle(
            "body",
            parent=styles["BodyText"],
            fontName=body_font,
            fontSize=11,
            leading=16,
            alignment=rl["TA_JUSTIFY"],
            spaceAfter=8,
        )
        # Table cell text.
        custom["cell"] = ParagraphStyle(
            "cell",
            parent=styles["BodyText"],
            fontName=body_font,
            fontSize=9,
            leading=12,
            alignment=rl["TA_LEFT"],
        )
        # Table header text.
        custom["cell_header"] = ParagraphStyle(
            "cell_header",
            parent=styles["BodyText"],
            fontName=heading_font,
            fontSize=10,
            leading=12,
            alignment=rl["TA_LEFT"],
            textColor=rl["colors"].white,
        )
        # Caption.
        custom["caption"] = ParagraphStyle(
            "caption",
            parent=styles["BodyText"],
            fontName=body_italic,
            fontSize=9,
            leading=12,
            alignment=rl["TA_CENTER"],
            textColor=rl["colors"].HexColor("#666666"),
            spaceBefore=4,
            spaceAfter=10,
        )
        # TOC entry styles.
        custom["toc_h1"] = ParagraphStyle(
            "toc_h1",
            fontName=heading_font,
            fontSize=11,
            leading=16,
            leftIndent=0,
        )
        custom["toc_h2"] = ParagraphStyle(
            "toc_h2",
            fontName=body_font,
            fontSize=10,
            leading=14,
            leftIndent=16,
        )
        return custom

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------
    def add_cover_page(self, metadata: Dict[str, Any]) -> None:
        """Append a cover page.

        Args:
            metadata: Dict with optional keys: ``title``, ``author``,
                ``date``, ``abstract``, ``keywords`` (list or str), ``version``.
        """
        Paragraph = self._rl["Paragraph"]
        Spacer = self._rl["Spacer"]
        inch = self._rl["inch"]

        self._story.append(Spacer(1, 1.5 * inch))
        title = metadata.get("title", self.title)
        self._story.append(Paragraph(_xml_escape(title), self._styles["cover_title"]))

        # Author / date / version line.
        meta_lines: List[str] = []
        author = metadata.get("author", self.author)
        if author:
            meta_lines.append(_xml_escape(str(author)))
        date = metadata.get("date")
        if date:
            meta_lines.append(_xml_escape(str(date)))
        version = metadata.get("version")
        if version:
            meta_lines.append(f"v{_xml_escape(str(version))}")
        if meta_lines:
            self._story.append(Paragraph("<br/>".join(meta_lines), self._styles["cover_meta"]))

        self._story.append(Spacer(1, 0.6 * inch))

        abstract = metadata.get("abstract")
        if abstract:
            self._story.append(Paragraph("<b>Abstract</b>", self._styles["h2"]))
            self._story.append(Paragraph(_xml_escape(abstract), self._styles["body"]))

        keywords = metadata.get("keywords")
        if keywords:
            if isinstance(keywords, (list, tuple)):
                kw_str = "; ".join(str(k) for k in keywords)
            else:
                kw_str = str(keywords)
            self._story.append(Spacer(1, 0.2 * inch))
            self._story.append(
                Paragraph(
                    f"<b>Keywords:</b> {_xml_escape(kw_str)}",
                    self._styles["body"],
                )
            )

        # Force a page break after the cover.
        self.add_page_break()

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------
    def add_section(self, heading: str, body: str) -> None:
        """Append an H1 section heading + body paragraph.

        The ``body`` string supports ReportLab inline markup: ``<b>``,
        ``<i>``, ``<super>``, ``<sub>``, ``<a href="...">...</a>``.
        Stray ``&`` characters in the body should be written as ``&amp;``.

        Args:
            heading: Section title.
            body: Paragraph body (may contain Paragraph tags).
        """
        Paragraph = self._rl["Paragraph"]
        self._section_number += 1
        self._subsection_number = 0
        # Use literal section-number glyph "·" (CJK-safe), not an escape.
        heading_text = f"{self._section_number}. {_xml_escape(heading)}"
        self._story.append(Paragraph(heading_text, self._styles["h1"]))
        if body:
            self._story.append(Paragraph(body, self._styles["body"]))

    def add_subsection(self, heading: str, body: str = "") -> None:
        """Append an H2 subsection heading + optional body.

        Args:
            heading: Subsection title.
            body: Paragraph body (may contain Paragraph tags).
        """
        Paragraph = self._rl["Paragraph"]
        self._subsection_number += 1
        sub_num = f"{self._section_number}.{self._subsection_number}"
        heading_text = f"{sub_num}. {_xml_escape(heading)}"
        self._story.append(Paragraph(heading_text, self._styles["h2"]))
        if body:
            self._story.append(Paragraph(body, self._styles["body"]))

    # ------------------------------------------------------------------
    # Papers table
    # ------------------------------------------------------------------
    def add_papers_table(
        self,
        papers: Sequence[Any],
        columns: Optional[List[str]] = None,
        page_break: bool = True,
    ) -> None:
        """Append a styled table of papers.

        Args:
            papers: Sequence of Paper-like objects.
            columns: Optional column-name override.  Defaults to
                ``["title", "authors", "year", "journal", "citations"]``.
            page_break: When ``True``, insert a page break before the table.
        """
        Paragraph = self._rl["Paragraph"]
        Table = self._rl["Table"]
        TableStyle = self._rl["TableStyle"]
        Spacer = self._rl["Spacer"]
        colors = self._rl["colors"]
        inch = self._rl["inch"]

        if page_break and self._story:
            self.add_page_break()

        cols = list(columns) if columns else [
            "title", "authors", "year", "journal", "citations",
        ]
        # Build header row.
        header_cells = [
            Paragraph(_xml_escape(c.replace("_", " ").title()), self._styles["cell_header"])
            for c in cols
        ]
        data: List[List[Any]] = [header_cells]
        for p in papers:
            row: List[Any] = []
            for col in cols:
                raw = self._cell_value(p, col)
                row.append(Paragraph(_xml_escape(raw), self._styles["cell"]))
            data.append(row)

        # Column widths: scale by content importance.
        col_widths = self._column_widths(cols, total=6.5 * inch)
        table = Table(data, repeatRows=1, colWidths=col_widths, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E5C8A")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "NotoSansSC"),
                    ("FONTSIZE", (0, 0), (-1, 0), 10),
                    ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("TOPPADDING", (0, 0), (-1, 0), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FA")]),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 1), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
                ]
            )
        )
        self._story.append(table)
        self._story.append(Spacer(1, 0.2 * inch))

    def _cell_value(self, paper: Any, col: str) -> str:
        """Return a short string representation of one cell."""
        if col == "authors":
            authors = get_authors(paper)
            if not authors:
                return ""
            if len(authors) <= 3:
                return "; ".join(authors)
            return f"{authors[0]} <i>et al.</i> ({len(authors)})"
        if col == "citations":
            return str(get_citation_count(paper))
        if col == "year":
            y = get_year(paper)
            return str(y) if y is not None else ""
        if col == "doi":
            return get_doi(paper)
        if col == "title":
            t = get_str(paper, "title")
            # Truncate very long titles in the table.
            return t if len(t) <= 120 else t[:117] + "..."
        return get_str(paper, col)

    def _column_widths(self, cols: List[str], total: float) -> List[float]:
        """Distribute column widths heuristically across ``total`` inches."""
        weights: Dict[str, float] = {
            "title": 2.4,
            "authors": 1.6,
            "abstract": 3.0,
            "keywords": 1.6,
            "journal": 1.4,
            "booktitle": 1.4,
            "url": 1.2,
            "doi": 1.2,
        }
        default_w = 1.0
        raw = [weights.get(c, default_w) for c in cols]
        s = sum(raw) or 1.0
        return [total * (w / s) for w in raw]

    # ------------------------------------------------------------------
    # Chart image
    # ------------------------------------------------------------------
    def add_chart(
        self,
        figure: Any,
        caption: Optional[str] = None,
        width: float = 6 * 1.0,  # 6 * inch passed at call time
    ) -> None:
        """Embed a matplotlib Figure as a PNG image.

        Args:
            figure: A ``matplotlib.figure.Figure`` object.
            caption: Optional caption text (italic, centred).
            width: Width in points (use ``reportlab.lib.units.inch``).
        """
        Image = self._rl["Image"]
        Paragraph = self._rl["Paragraph"]
        Spacer = self._rl["Spacer"]

        png_bytes = self._figure_to_png_bytes(figure)
        from io import BytesIO  # local import keeps top-level clean
        bio = BytesIO(png_bytes)
        # Determine aspect ratio so height is preserved.
        try:
            from PIL import Image as PILImage  # noqa: WPS433
            bio.seek(0)
            with PILImage.open(bio) as im:
                w_px, h_px = im.size
            bio.seek(0)
            aspect = h_px / w_px if w_px else 0.75
        except Exception:
            aspect = 0.75
        height = width * aspect

        self._story.append(Image(bio, width=width, height=height))
        if caption:
            self._story.append(Spacer(1, 4))
            self._story.append(Paragraph(_xml_escape(caption), self._styles["caption"]))
        self._story.append(Spacer(1, 6))

    @staticmethod
    def _figure_to_png_bytes(figure: Any) -> bytes:
        """Render a matplotlib Figure to PNG bytes."""
        bio = io.BytesIO()
        try:
            # constrained_layout=True is set by ChartGenerator; never call
            # bbox_inches='tight' on top of it.
            figure.savefig(bio, format="png", dpi=150)
        except Exception as exc:
            logger.warning("figure.savefig failed: %s", exc, exc_info=True)
            # Fall back to an empty 1x1 PNG so build() doesn't crash.
            from reportlab.lib.utils import ImageReader  # noqa: WPS433
            del ImageReader
            bio.write(b"\x89PNG\r\n\x1a\n")
        return bio.getvalue()

    # ------------------------------------------------------------------
    # Citation graph image
    # ------------------------------------------------------------------
    def add_citation_graph(
        self,
        graph_image: Union[bytes, str],
        caption: Optional[str] = None,
    ) -> None:
        """Embed a citation-graph image (path or raw PNG/JPEG bytes).

        Args:
            graph_image: Filesystem path (str) OR raw image bytes.
            caption: Optional caption text.
        """
        Image = self._rl["Image"]
        Paragraph = self._rl["Paragraph"]
        Spacer = self._rl["Spacer"]
        inch = self._rl["inch"]

        width = 6.0 * inch
        if isinstance(graph_image, (bytes, bytearray)):
            from io import BytesIO
            stream: Any = BytesIO(graph_image)
            try:
                from PIL import Image as PILImage  # noqa: WPS433
                with PILImage.open(stream) as im:
                    w_px, h_px = im.size
                stream.seek(0)
                aspect = h_px / w_px if w_px else 0.75
            except Exception:
                aspect = 0.75
            height = width * aspect
            self._story.append(Image(stream, width=width, height=height))
        else:
            path = str(graph_image)
            if not os.path.exists(path):
                logger.warning("citation graph image not found: %s", path)
                return
            try:
                from PIL import Image as PILImage  # noqa: WPS433
                with PILImage.open(path) as im:
                    w_px, h_px = im.size
                aspect = h_px / w_px if w_px else 0.75
            except Exception:
                aspect = 0.75
            height = width * aspect
            self._story.append(Image(path, width=width, height=height))
        if caption:
            self._story.append(Spacer(1, 4))
            self._story.append(Paragraph(_xml_escape(caption), self._styles["caption"]))
        self._story.append(Spacer(1, 6))

    # ------------------------------------------------------------------
    # Page break / TOC
    # ------------------------------------------------------------------
    def add_page_break(self) -> None:
        """Insert an explicit page break."""
        PageBreak = self._rl["PageBreak"]
        self._story.append(PageBreak())

    def add_toc(self) -> None:
        """Insert an auto-populated Table of Contents.

        The TOC is filled in on the second build pass (``multiBuild``).
        """
        TableOfContents = self._rl["TableOfContents"]
        Paragraph = self._rl["Paragraph"]
        toc = TableOfContents()
        toc.levelStyles = [self._styles["toc_h1"], self._styles["toc_h2"]]
        self._story.append(Paragraph("Table of Contents", self._styles["h1"]))
        self._story.append(toc)
        self.add_page_break()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def build(self, path: str) -> str:
        """Render the report to ``path`` and return the absolute path.

        Uses ``BaseDocTemplate.multiBuild`` so the TableOfContents is
        populated correctly across passes.
        """
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        abs_path = os.path.abspath(path)

        BaseDocTemplate = self._rl["BaseDocTemplate"]
        Frame = self._rl["Frame"]
        PageTemplate = self._rl["PageTemplate"]
        Paragraph = self._rl["Paragraph"]
        inch = self._rl["inch"]
        letter = self._rl["letter"]

        DocCls = _make_toc_doc_template_cls(BaseDocTemplate, Paragraph)

        doc = DocCls(
            abs_path,
            pagesize=letter,
            title=self.title,
            author=self.author or "",
            subject=self.subject or "",
            leftMargin=0.9 * inch,
            rightMargin=0.9 * inch,
            topMargin=0.9 * inch,
            bottomMargin=0.9 * inch,
        )
        frame = Frame(
            doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
            id="normal", showBoundary=0,
        )
        template = PageTemplate(id="main", frames=[frame], onPage=self._on_page)
        doc.addPageTemplates([template])

        try:
            # multiBuild is required for TableOfContents to populate.
            doc.multiBuild(self._story)
        except Exception as exc:
            logger.error("PDF build failed -> %s: %s", abs_path, exc, exc_info=True)
            raise
        logger.info("PDF built -> %s", abs_path)
        return abs_path

    # ------------------------------------------------------------------
    # Page header / footer (page numbers).
    # ------------------------------------------------------------------
    def _on_page(self, canvas, doc) -> None:
        """Draw a footer with page number + report title."""
        canvas.saveState()
        colors = self._rl["colors"]
        inch = self._rl["inch"]
        canvas.setFont(_pick_font("DejaVuSans", "Helvetica"), 8)
        canvas.setFillColor(colors.HexColor("#888888"))
        # Footer: page number centred.
        canvas.drawCentredString(
            doc.pagesize[0] / 2.0, 0.5 * inch,
            f"Page {doc.page}",
        )
        # Footer left: title (truncated).
        title_str = self.title if len(self.title) <= 60 else self.title[:57] + "..."
        canvas.drawString(0.9 * inch, 0.5 * inch, title_str)
        canvas.restoreState()


__all__ = ["PDFReport"]
