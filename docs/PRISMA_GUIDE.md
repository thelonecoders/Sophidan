# PRISMA 2020 Compliance Guide

> **Audience:** systematic-review authors, journal editors, evidence-synthesis methodologists.
> **Companion docs:** [META_ANALYSIS_GUIDE.md](META_ANALYSIS_GUIDE.md) for the downstream meta-analysis,
> [user_guide.md](user_guide.md) for daily usage,
> [MODULE_REFERENCE.md](MODULE_REFERENCE.md) for the full module index.

This guide explains how Academic Research Suite (ARS) v2.0.0 supports
end-to-end PRISMA 2020 compliance — from generating the canonical
four-stage flow diagram to filling the 27-item checklist and bundling
everything into a publication-grade PDF/DOCX report.

---

## Table of Contents

1. [What is PRISMA 2020?](#what-is-prisma-2020)
2. [Generating a flow diagram](#generating-a-flow-diagram)
3. [The 27-item checklist](#the-27-item-checklist)
4. [PRISMA extensions](#prisma-extensions)
5. [Export formats](#export-formats)
6. [BMJ vs JAMA vs Lancet styles](#bmj-vs-jama-vs-lancet-styles)
7. [Integration with the systematic-review module](#integration-with-the-systematic-review-module)
8. [Example: End-to-end PRISMA-compliant SR](#example-end-to-end-prisma-compliant-sr)

---

## What is PRISMA 2020?

**PRISMA** (Preferred Reporting Items for Systematic Reviews and
Meta-Analyses) is an evidence-based minimum set of reporting items
for systematic reviews and meta-analyses. The original 2009 statement
(Moher D, et al. *PRISMA 2009*. PLoS Med 2009;6:e1000097) consolidated
the earlier QUOROM statement and became the de-facto reporting standard
adopted by >1,000 biomedical journals.

The **PRISMA 2020 update** (Page MJ, et al. *The PRISMA 2020 statement:
an updated guideline for reporting systematic reviews.* BMJ 2021;372:n71)
modernised the checklist and flow diagram in several ways:

- The checklist grew from 27 items to 27 entirely revised items,
  adding emphasis on **data availability**, **registration**, **risk of
  bias**, **certainty of evidence** (GRADE), and **synthesis methods**.
- The flow diagram was redesigned with **separate identification,
  screening, and inclusion branches**; new boxes for *duplicates
  removed*, *records not retrieved*, *studies excluded with reasons*, and
  *studies included in quantitative vs qualitative synthesis*.
- Six official **extensions** were consolidated: IPD (individual
  participant data), NMA (network meta-analysis), ScR (scoping review),
  Harms (adverse events), Abstract (conference abstract), and Diagnostic
  (test accuracy).

**Why compliance matters.** Most high-impact biomedical journals
(BMJ, JAMA, Lancet, NEJM, Annals of Internal Medicine, PLoS Medicine)
require a completed PRISMA checklist as a submission attachment, and
many require the flow diagram as Figure 1. Cochrane, JBI (Joanna Briggs
Institute), and Campbell systematic review platforms enforce PRISMA
reporting at the protocol-registration stage. A non-compliant review is
a desk-reject risk.

ARS ships a complete PRISMA implementation under the
[`prisma/`](../prisma/) package, plus a thin integration layer in
[`systematic_review/prisma_integration.py`](../systematic_review/prisma_integration.py)
that connects the SR workflow to the PRISMA outputs.

---

## Generating a flow diagram

The flow diagram is rendered by
`prisma.flow_diagram.PRISMAFlowGenerator`. Counts are stored in the
`PRISMAStageCounts` dataclass (all 16 official stage-count fields):

```python
from prisma.flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts

counts = PRISMAStageCounts(
    n_records_databases=1248,            # identified from databases
    n_records_registers=37,              # identified from registers
    n_records_before_duplicates=1285,    # before deduplication
    n_duplicates_removed=180,
    n_records_after_duplicates=1105,
    n_records_screened=1105,             # title/abstract
    n_records_excluded_title_abstract=880,
    n_records_sought_full_text=225,      # sought for retrieval
    n_records_not_retrieved=12,          # not retrieved
    n_full_text_assessed=213,            # assessed for eligibility
    n_full_text_excluded=87,             # excluded at full-text
    n_excluded_with_reasons=[            # PRISMA 2020 item — give reasons
        ("Wrong outcome", 31),
        ("Wrong population", 22),
        ("Wrong study design", 18),
        ("Unable to retrieve full text", 16),
    ],
    n_studies_included_qualitative=126,  # in synthesis
    n_studies_included_quantitative=98,  # in meta-analysis
)

gen = PRISMAFlowGenerator(counts, title="Effect of SGLT2 inhibitors on HbA1c")
fig = gen.render_matplotlib(figsize=(10.0, 14.0), dpi=300, style="bmj")
```

To save the diagram, call one of the four format-specific writers:

```python
gen.render_png("prisma_flow.png", dpi=300, style="bmj")
gen.render_svg("prisma_flow.svg", style="lancet")
gen.render_pdf("prisma_flow.pdf", style="jama")
gen.render_html("prisma_flow.html", style="bmj")
```

For GraphViz users, `gen.to_dot()` returns the diagram as a DOT source
string that you can pipe to `dot -Tsvg`.

All `PRISMAStageCounts` fields are `Optional[int]` — any missing
stage is simply not drawn. The `n_excluded_with_reasons` field is a
list of `(reason, count)` tuples that the renderer lays out vertically
next to the *studies excluded* box.

---

## The 27-item checklist

The 27 official PRISMA 2020 checklist items are returned by
`PRISMAChecklist.default_2020_items()`. Each item is a `PRISMAItem`
dataclass with fields `id`, `section` (Title / Abstract / Introduction /
Methods / Results / Discussion / Other), `item_text`, `location_in_report`,
`reported`, and `notes`.

```python
from prisma.checklist import PRISMAChecklist, PRISMAItem

checklist = PRISMAChecklist()               # 27 items loaded by default
print(f"{checklist.completion_rate():.1%} complete")  # 0.0%

# Mark item 5 ("Eligibility criteria") as reported, located in Methods §2.2
for item in checklist.items:
    if "Eligibility criteria" in item.item_text:
        item.reported = True
        item.location_in_report = "Methods §2.2"
        item.notes = "PICOS framework; final list in Supplementary Table S1"
        break

print(checklist.completion_rate())              # ~0.037
print([it.item_text for it in checklist.missing_items()][:5])

# Export to publication-grade formats:
checklist.to_pdf("prisma_checklist.pdf", title="PRISMA 2020 Checklist")
checklist.to_docx("prisma_checklist.docx")
checklist.to_yaml("prisma_checklist.yaml")
print(checklist.to_markdown())
```

The `to_pdf` and `to_docx` methods render a publication-ready table with
item ID, section, item text, location in report, reported flag, and
notes — exactly the format expected by journal submission portals.

---

## PRISMA extensions

The seven PRISMA 2020 templates are enumerated in
`prisma.extensions.PRISMAExtension`:

| Code | Extension | Use case |
|---|---|---|
| `standard` | Original PRISMA 2020 | Default for any SR with or without meta-analysis |
| `ipd` | Individual participant data | One-stage or two-stage IPD meta-analysis (Stewart 2012) |
| `nma` | Network meta-analysis | Multi-treatment comparisons (Hutton 2015) |
| `scr` | Scoping review | Broad mapping reviews (Tricco 2018) |
| `harms` | Adverse events | Reviews focusing on harms (Zorzela 2016) |
| `abstract` | Conference abstract | Abridged 200-word format (Beller 2013) |
| `diagnostic` | Diagnostic test accuracy | DTA reviews (McInnes 2018) |

To switch templates, pass the extension code to `PRISMAFlowGenerator`:

```python
gen = PRISMAFlowGenerator(counts, title="NMA of 5 GLP-1 agonists",
                         extension="nma")
gen.render_png("nma_flow.png", style="bmj")
```

Extension-specific **checklist** items (additional to the standard 27)
are returned by `PRISMAExtensionsChecklist`:

```python
from prisma.checklist import PRISMAChecklist, PRISMAExtensionsChecklist

items = PRISMAChecklist.default_2020_items() + \
        PRISMAExtensionsChecklist.ipd_checklist()       # 27 + 7 = 34 items
checklist = PRISMAChecklist(items=items)
print(len(checklist.items))                              # 34
```

The convenience factory `PRISMAExtensionGenerator` builds a fully
configured `PRISMAFlowGenerator` for a given extension:

```python
from prisma.extensions import PRISMAExtensionGenerator
gen = PRISMAExtensionGenerator().ipd_flow(counts, title="IPD Meta-analysis")
gen.render_pdf("ipd_flow.pdf", style="bmj")
```

---

## Export formats

`PRISMAFlowGenerator` ships five output channels:

| Method | Format | Use case |
|---|---|---|
| `render_png(path, dpi=300)` | Raster PNG | Quick previews, slide decks |
| `render_svg(path)` | Vector SVG | Journal submission (lossless) |
| `render_pdf(path)` | Vector PDF | Journal submission (preferred) |
| `render_html(path)` | HTML + CSS | Web supplements, interactive previews |
| `to_dot()` | GraphViz DOT | Programmatic post-processing |

PNG is rendered at 300 DPI by default — sufficient for journal
submission. SVG and PDF are preferred because they embed text as
selectable vector outlines and scale without aliasing to any print
size. The HTML renderer produces a self-contained file with inline CSS
that mirrors the matplotlib layout — useful for web supplements or
preprint servers (bioRxiv, medRxiv).

For word-processor submission, use the `PRISMAReport` (see
[Integration](#integration-with-the-systematic-review-module) below)
which embeds both the flow diagram and the checklist into a single DOCX
file.

---

## BMJ vs JAMA vs Lancet styles

The `style=` keyword selects a journal-specific colour palette defined
in `prisma.flow_diagram._STYLE_PALETTE`:

| Style | Stage box bg | Stage box fg | Process box bg | Process box border | Arrow | Notes |
|---|---|---|---|---|---|---|
| `bmj` (default) | `#1a3a5c` (navy) | `#ffffff` | `#cfe2f3` (light blue) | `#2e5c8a` | `#2e5c8a` | Classic BMJ navy/light-blue |
| `jama` | `#222222` (near-black) | `#ffffff` | `#f5f5f5` (off-white) | `#555555` | `#555555` | Monochrome, JAMA-style minimalism |
| `lancet` | `#7a0c0c` (deep red) | `#ffffff` | `#ffffff` | `#1a1a1a` | `#7a0c0c` | Lancet's signature red header |

The three styles share an identical layout (PRISMA 2020 four-stage
flow). They differ only in the colour of the stage labels, the
process-box fill, and the arrow strokes. Choose the style that matches
your target journal to match its editorial typesetting:

```python
# Cochrane-style review (typically BMJ-published sister journals)
gen.render_pdf("flow_bmj.pdf", style="bmj")

# JAMA family submission
gen.render_pdf("flow_jama.pdf", style="jama")

# The Lancet / Lancet sister journals
gen.render_pdf("flow_lancet.pdf", style="lancet")
```

If your target journal has no equivalent (e.g. NEJM, Annals of Internal
Medicine), the default `bmj` style is the safest choice — most journal
production teams accept it unchanged.

---

## Integration with the systematic-review module

The thin integration layer
`systematic_review.prisma_integration.PRISMAIntegration` connects a
`ScreeningManager` (the SR workflow's screening module) to the PRISMA
outputs:

| Method | Input | Output |
|---|---|---|
| `from_screening(screening)` | `ScreeningManager` instance | dict of stage counts |
| `generate_flow_diagram(screening, output_path, title)` | screening + path | writes PNG/SVG/PDF/HTML |
| `generate_checklist(screening, output_path, title)` | screening + path | writes PDF/DOCX checklist |
| `prisma_2020_checklist()` | — | the 27-item checklist as list of dicts |
| `prisma_extensions()` | — | the six extension templates as a dict |

Usage:

```python
from systematic_review.screening import ScreeningManager
from systematic_review.prisma_integration import PRISMAIntegration

mgr = ScreeningManager()
mgr.load_from_search(results)               # populate from a scrape
mgr.auto_dedup()                            # remove duplicates
mgr.screen_title_abstract("rec-001", "include", reviewer="Alice")
# ... screen more records ...

integration = PRISMAIntegration()
counts = integration.from_screening(mgr)    # dict[str, int]
integration.generate_flow_diagram(mgr, "prisma_flow.pdf",
                                   title="My Systematic Review")
integration.generate_checklist(mgr, "prisma_checklist.pdf")
```

This is the canonical path used by the desktop UI
(`ui/widgets/prisma_builder.py`) and by the REST endpoint
`POST /api/sr/prisma-flow` documented in
[api_reference.md](api_reference.md#v200-endpoints).

---

## Example: End-to-end PRISMA-compliant SR

Putting it all together — a fully compliant Cochrane-style review with
flow diagram, checklist, per-study extraction forms, and a bundled PDF
report:

```python
from data_acquisition.scraping_engine import ScrapingEngine
from systematic_review.screening import ScreeningManager, ScreeningDecision
from systematic_review.prisma_integration import PRISMAIntegration
from systematic_review.risk_of_bias import CochraneRoB2
from prisma.flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts
from prisma.checklist import PRISMAChecklist
from prisma.extraction_form import PRISMAExtractionForm
from prisma.report import PRISMAReport

# 1. Scrape candidate records (PubMed + Embase via Crossref + Cochrane via OpenAlex)
engine = ScrapingEngine()
results = engine.search_all("SGLT2 inhibitor HbA1c", sources=["pubmed", "openalex", "crossref"])

# 2. Screen title/abstract, then full-text
mgr = ScreeningManager()
mgr.load_from_search(results)
mgr.auto_dedup()
for rid in [r.id for r in mgr.records][:800]:
    mgr.screen_title_abstract(rid, "exclude", reviewer="Alice",
                              exclusion_reason="wrong_population")
for rid in [r.id for r in mgr.records if r.stage == "title_abstract" and r.decision == "include"]:
    mgr.screen_full_text(rid, "include", reviewer="Bob")

# 3. Build PRISMA flow + checklist from screening
integration = PRISMAIntegration()
counts = integration.from_screening(mgr)
flow_gen = PRISMAFlowGenerator(
    PRISMAStageCounts(**counts),
    title="Effect of SGLT2 inhibitors on HbA1c in T2DM",
    extension="standard",
)
flow_gen.render_pdf("outputs/flow.pdf", style="bmj")
flow_gen.render_svg("outputs/flow.svg", style="bmj")

checklist = PRISMAChecklist()
for item in checklist.items:
    item.location_in_report = "(to be filled)"
    item.reported = True
checklist.to_pdf("outputs/checklist.pdf")
checklist.to_docx("outputs/checklist.docx")

# 4. Risk of bias + extraction per included study
rob = CochraneRoB2()
extraction = []
for study in [r for r in mgr.records if r.decision == "include"]:
    rob_result = rob.assess({"study_id": study.id, "randomization": "low", ...})
    form = PRISMAExtractionForm(
        study_id=study.id,
        study_design="RCT",
        population="Adults ≥18y with T2DM",
        intervention="SGLT2 inhibitor",
        comparator="Placebo",
        outcomes=["HbA1c change", "Body weight change"],
        sample_size=study.n_total,
    )
    extraction.append(form)

# 5. Bundle into a single publication-grade PDF
report = PRISMAReport(
    counts=flow_gen.counts,
    checklist=checklist,
    extraction=extraction,
    title="Effect of SGLT2 inhibitors on HbA1c in T2DM: a systematic review",
    authors=["Doe J", "Smith A"],
)
report.generate("outputs/prisma_report.pdf", format="pdf")
```

This produces a single PDF containing: (a) the BMJ-style PRISMA flow
diagram, (b) the completed 27-item checklist, and (c) a per-study
extraction table. That is the canonical submission-ready PRISMA bundle.

---

*Next: see [META_ANALYSIS_GUIDE.md](META_ANALYSIS_GUIDE.md) for the
meta-analysis workflow that follows the PRISMA inclusion step, and
[Q1_FIGURES_GUIDE.md](Q1_FIGURES_GUIDE.md) for rendering
publication-grade forest / funnel / volcano plots.*
