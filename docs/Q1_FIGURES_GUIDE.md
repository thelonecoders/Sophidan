# Q1 Figure Production Guide

> **Audience:** corresponding authors, figure-makers, doctoral students
> preparing Q1 journal submissions.
> **Companion docs:** [META_ANALYSIS_GUIDE.md](META_ANALYSIS_GUIDE.md)
> for the underlying statistical analyses,
> [MODULE_REFERENCE.md](MODULE_REFERENCE.md) for the full module index.

This guide explains how Academic Research Suite (ARS) v2.0.0 produces
**publication-grade figures** for Q1 journals — Nature, Science, Cell,
NEJM, Lancet, JAMA — and for any journal that follows the standard
89 mm / 120 mm / 183 mm column-width conventions.

---

## Table of Contents

1. [Journal-specific palettes and typography](#journal-specific-palettes-and-typography)
2. [Single vs double column sizing](#single-vs-double-column-sizing)
3. [Vector formats vs raster](#vector-formats-vs-raster)
4. [Multi-panel composition](#multi-panel-composition)
5. [Statistical overlays](#statistical-overlays)
6. [Figure recipes](#figure-recipes)
7. [Export checklist](#export-checklist)

---

## Journal-specific palettes and typography

ARS ships six palettes under
`q1_figures.palettes.JournalPalettes`. Each palette is a 10-colour hex
list tuned to that journal's in-house style guide:

| Journal | Palette name | Primary colours | Type face |
|---|---|---|---|
| **Nature** | `nature` | `#E64B35 #4DBBD5 #00A087 #3C5488 #F39B7F ...` | Arial |
| **Science** | `science` | `#0B3C5D #062F4F #1C6E8C #328CC1 #D9B310 ...` | Helvetica |
| **Cell** | `cell` | `#2E86AB #A23B72 #F18F01 #C73E1D #3B1F2B ...` | Arial |
| **NEJM** | `nejm` | `#1F77B4 #FF7F0E #2CA02C #D62728 #9467BD ...` | classic (matplotlib default) |
| **Lancet** | `lancet` | `#00468B #ED0000 #42B540 #0099B4 #925E9F ...` | Times New Roman |
| **JAMA** | `jama` | `#374E55 #DF8F44 #00A1D5 #B24745 #79AF97 ...` | Helvetica |

Plus three colour-blind-safe / sequential palettes (`colorblind_safe`,
`diverging_rg`, `sequential_viridis`) for accessibility-mandated venues.

```python
from q1_figures.palettes import JournalPalettes

print(JournalPalettes.all_names())
# ['cell', 'colorblind_safe', 'diverging_rg', 'jama', 'lancet',
#  'nature', 'nejm', 'science', 'sequential_viridis', ...]

palette = JournalPalettes.get("nature")
print(palette[:5])  # ['#E64B35', '#4DBBD5', '#00A087', '#3C5488', '#F39B7F']
```

The typography stack
(`q1_figures.typography.Q1Typography.configure_matplotlib(journal)`)
applies journal-specific font families, sizes (7 pt tick labels, 9 pt
axis labels, 10 pt bold titles), and the matplotlib `axes.unicode_minus
= False` setting required for proper minus-sign rendering.

```python
from q1_figures.typography import Q1Typography

Q1Typography.configure_matplotlib("nature")    # Arial, 7/9/10 pt
Q1Typography.configure_matplotlib("lancet")    # Times New Roman, serif
```

Six journals are explicitly supported:
`nature`, `science`, `cell`, `nejm`, `lancet`, `jama`. Use the
`colorblind_safe` palette for any journal that mandates WCAG AAA
contrast.

---

## Single vs double column sizing

Q1 journals use three standard column widths:

| Column width | ARS code | Millimetres | Inches | Typical use |
|---|---|---|---|---|
| Single column | `single` | 89 mm | 3.50 in | One-panel main figure, sidebar |
| 1.5 column | `1.5` | 120 mm | 4.72 in | Wide single panel or 2-panel |
| Double column | `double` / `full` | 183 mm | 7.20 in | Multi-panel main figure |

Combine with the aspect-ratio keyword `square` (1.0), `wide` (1.6), or
`tall` (0.625 — inverse of wide):

```python
from q1_figures.figure_factory import Q1FigureFactory

f = Q1FigureFactory(journal="nature", dpi=300)
f.set_size(columns="single", aspect="square")   # 3.50 × 3.50 in
f.set_size(columns="1.5",     aspect="wide")    # 4.72 × 2.95 in
f.set_size(columns="double",   aspect="tall")    # 7.20 × 11.52 in
```

Most Q1 journals require figures at exactly these widths — production
teams rasterise figures at 600 DPI for print. ARS defaults to 300 DPI
(sufficient for web and most print workflows); pass `dpi=600` to the
factory constructor for high-resolution journals.

---

## Vector formats vs raster

| Format | Extension | Use case |
|---|---|---|
| SVG | `.svg` | **Preferred** for most journals (Nature, Science, Cell). Lossless, scalable, text remains selectable. |
| PDF | `.pdf` | **Preferred** for Lancet, JAMA, NEJM. Embeds fonts, smaller file size. |
| PNG | `.png` | Web supplements, preprint servers (bioRxiv). 300+ DPI acceptable. |
| TIFF | `.tiff` | Required by some journals (e.g. Cell Press for photographic content). 300+ DPI, LZW compression. |

The `Q1FigureFactory.save(fig, path)` method **auto-infers the format
from the path extension** when `format=None` (the default). It supports
`.png`, `.svg`, `.pdf`, `.tiff`; unknown extensions fall back to PNG.

```python
f.save(fig, "fig1.svg")             # SVG
f.save(fig, "fig1.pdf")             # PDF
f.save(fig, "fig1.png", dpi=600)    # high-res PNG
f.save(fig, "fig1.tiff", dpi=600)   # TIFF
```

**Rule of thumb:** prefer SVG/PDF for line art, plots, and diagrams
(forest plots, funnel plots, network figures, Sankey diagrams);
use PNG/TIFF only for raster-heavy content (heatmaps of large
matrices, photographic overlays).

---

## Multi-panel composition

`q1_figures.multi_panel.MultiPanelFigure` composes a multi-panel figure
with automatic panel labels (a, b, c, d — the Q1 convention):

```python
from q1_figures.multi_panel import MultiPanelFigure

mpf = MultiPanelFigure(rows=2, cols=2, journal="nature", dpi=300,
                        panel_labels="abcd")
ax0 = mpf.add_panel(row=0, col=0)
ax1 = mpf.add_panel(row=0, col=1)
ax2 = mpf.add_panel(row=1, col=0)
ax3 = mpf.add_panel(row=1, col=1)

mpf.set_panel_label(0, "a")
mpf.set_panel_label(1, "b")
mpf.set_panel_label(2, "c")
mpf.set_panel_label(3, "d")
mpf.set_panel_title(0, "Forest plot")
mpf.set_panel_title(1, "Funnel plot")
mpf.set_panel_title(2, "Network")
mpf.set_panel_title(3, "SUCRA ranking")

mpf.share_x([ax0, ax2])     # share x-axis between panels 0 and 2
mpf.share_y([ax0, ax1])
mpf.adjust_spacing(hspace=0.4, wspace=0.4)
mpf.finalize()
mpf.save("outputs/fig1_multipanel.svg")
```

For asymmetric layouts (e.g. one wide panel + two stacked panels), use
`GridLayout(rows, cols, ratios=[2, 1, 1])` which sets row heights and
column widths via GridSpec.

---

## Statistical overlays

`Q1FigureFactory` provides four overlay helpers:

| Method | Purpose |
|---|---|
| `add_error_bars(ax, x, y, yerr, xerr, cap_size, ...)` | Standard error bars with adjustable caps |
| `add_significance_bar(ax, x1, x2, y, text='***', ...)` | Significance bracket with star labels |
| `add_significance_line(ax, x1, x2, y, ...)` | Significance line (no text) |
| `add_colorbar(fig, ax, mappable, label, orientation, shrink, aspect)` | Colorbar with journal-matched typography |
| `annotate_panel(ax, label='a', xy=(0, 1.05), fontweight='bold')` | Bold panel label in top-left corner |
| `style_axes(ax, spine_top=False, spine_right=False, grid=False, ...)` | Remove top/right spines (Nature style) |

```python
f = Q1FigureFactory(journal="nature")
fig, ax = f.new_figure_and_axes()
ax.plot(x, y, color=JournalPalettes.get("nature")[0])
f.add_error_bars(ax, x, y, yerr=se, color="#3C5488", cap_size=2)
f.add_significance_bar(ax, x1=0, x2=1, y=1.2, text="***")
f.set_axis_labels(ax, xlabel="Dose (mg)", ylabel="Response")
f.set_title(ax, "Dose–response curve")
f.style_axes(ax, spine_top=False, spine_right=False, grid=True, grid_axis="y")
f.annotate_panel(ax, label="a")
f.add_legend(ax, frame=False, fontsize=7)
f.finalize(fig)
f.save(fig, "outputs/fig1a_dose_response.svg")
```

The `add_significance_bar` helper uses standard star conventions:
`*` p<0.05, `**` p<0.01, `***` p<0.001, `n.s.` not significant.

---

## Figure recipes

Every recipe below is verified against the v2.0.0 source. Use
`StatisticalPlots` for the basic chart types, `Q1NetworkPlots` for
graph-based figures, and `BibliometricPlots` for scientometric curves.

### 1. Forest plot

Rendered by `meta_analysis.forest_plot.ForestPlot` (see
[META_ANALYSIS_GUIDE.md](META_ANALYSIS_GUIDE.md)) and exported via the
factory:

```python
from meta_analysis.forest_plot import ForestPlot
from q1_figures.figure_factory import Q1FigureFactory

fp = ForestPlot(es_list, pooled=result.pooled_effect,
                x_label="OR (log scale)", x_scale="log", confidence=0.95)
fp.add_heterogeneity(f"I²={result.I_squared:.1f}%")
fig = fp.render(figsize=(7.2, 4.5), dpi=300, style="cochrane")
Q1FigureFactory(journal="nature").save(fig, "outputs/forest.svg")
```

### 2. Funnel plot

```python
from meta_analysis.funnel_plot import ContourEnhancedFunnel
from q1_figures.figure_factory import Q1FigureFactory

funnel = ContourEnhancedFunnel(es_list, pooled=result.pooled_effect)
funnel.add_significance_contours()
funnel.add_pseudo_ci(alpha=0.95)
funnel.add_trim_fill(method="R0")
fig = funnel.render(figsize=(3.5, 3.5), dpi=300, style="cochrane")
Q1FigureFactory(journal="nature").save(fig, "outputs/funnel.svg")
```

### 3. Volcano plot

```python
import numpy as np
from q1_figures.statistical_plots import StatisticalPlots
from q1_figures.figure_factory import Q1FigureFactory

f = Q1FigureFactory(journal="nature")
fig, ax = f.new_figure_and_axes()
log2fc = np.random.randn(2000)
neg_log10_p = -np.log10(np.random.uniform(1e-8, 1, size=2000))
genes = [f"gene_{i}" for i in range(2000)]
StatisticalPlots.volcano_plot(
    ax, log2fc=log2fc, neg_log10_p=neg_log10_p, gene_names=genes,
    fc_threshold=1.0, p_threshold=0.05, palette="nature",
    highlight_top_n=10, show_labels=True,
)
f.set_axis_labels(ax, xlabel="log₂ fold change", ylabel="-log₁₀(p)")
f.set_title(ax, "Differential expression")
f.finalize(fig)
f.save(fig, "outputs/volcano.svg")
```

### 4. Manhattan plot

```python
from q1_figures.statistical_plots import StatisticalPlots
from q1_figures.figure_factory import Q1FigureFactory

f = Q1FigureFactory(journal="science")
fig, ax = f.new_figure_and_axes()
StatisticalPlots.manhattan_plot(
    ax, chrom=chrom, pos=pos, p_value=pvals,
    threshold=5e-8, suggestive=1e-5, palette="grayscale",
)
f.set_axis_labels(ax, xlabel="Chromosome", ylabel="-log₁₀(p)")
f.finalize(fig)
f.save(fig, "outputs/manhattan.svg")
```

### 5. QQ plot

```python
from q1_figures.statistical_plots import StatisticalPlots
f = Q1FigureFactory(journal="nature")
fig, ax = f.new_figure_and_axes()
StatisticalPlots.qq_plot(ax, observed_p=pvals, ci=0.95)
f.set_axis_labels(ax, xlabel="Expected -log₁₀(p)", ylabel="Observed -log₁₀(p)")
f.finalize(fig)
f.save(fig, "outputs/qq.svg")
```

### 6. Kaplan–Meier curve

```python
from q1_figures.statistical_plots import StatisticalPlots
f = Q1FigureFactory(journal="lancet")
fig, ax = f.new_figure_and_axes()
StatisticalPlots.kaplan_meier(
    ax, time=time, event=event, groups=arms, palette="lancet",
    show_ci=True, show_at_risk_table=True, show_p_value=True,
)
f.set_axis_labels(ax, xlabel="Time (months)", ylabel="Survival probability")
f.finalize(fig)
f.save(fig, "outputs/km.svg")
```

### 7. ROC curve

```python
from q1_figures.statistical_plots import StatisticalPlots
f = Q1FigureFactory(journal="nature")
fig, ax = f.new_figure_and_axes()
StatisticalPlots.roc_curve(
    ax, fpr=fpr, tpr=tpr, auc=0.84, ci=(0.79, 0.89), palette="nature",
)
f.set_axis_labels(ax, xlabel="1 - Specificity", ylabel="Sensitivity")
f.finalize(fig)
f.save(fig, "outputs/roc.svg")
```

### 8. Raincloud plot

```python
from q1_figures.statistical_plots import StatisticalPlots
f = Q1FigureFactory(journal="nature")
fig, ax = f.new_figure_and_axes()
StatisticalPlots.raincloud_plot(
    ax, data=[group_a, group_b, group_c],
    groups=["Control", "Low dose", "High dose"],
    palette="nature", orientation="horizontal",
)
f.set_axis_labels(ax, xlabel="Response", ylabel="Group")
f.finalize(fig)
f.save(fig, "outputs/raincloud.svg")
```

### 9. Network figure

```python
from q1_figures.network_plots import Q1NetworkPlots
import networkx as nx
f = Q1FigureFactory(journal="nature")
fig = Q1NetworkPlots.network_figure(
    nx.karate_club_graph(), layout="spring",
    partition=communities, ranking=centrality, palette="nature",
    figsize=(3.5, 3.5), dpi=300, label_top_n=10,
    node_size_range=(20, 200), edge_alpha=0.3, show_legend=True,
)
f.save(fig, "outputs/network.svg")
```

### 10. Sankey diagram

```python
from q1_figures.network_plots import Q1NetworkPlots
flows = [("Search", "Screen", 1285), ("Screen", "Full-text", 225),
         ("Full-text", "Included", 126), ("Full-text", "Excluded", 87)]
fig = Q1NetworkPlots.sankey_diagram(flows, palette="nature",
                                    figsize=(8, 5))
Q1FigureFactory(journal="nature").save(fig, "outputs/sankey.svg")
```

### 11. Chord diagram

```python
from q1_figures.network_plots import Q1NetworkPlots
flows = [("USA", "China", 120), ("USA", "EU", 80), ("China", "EU", 60)]
fig = Q1NetworkPlots.chord_diagram(flows, palette="nature")
Q1FigureFactory(journal="nature").save(fig, "outputs/chord.svg")
```

### 12. Hive plot

```python
from q1_figures.network_plots import Q1NetworkPlots
nodes_by_axis = {
    "Authors": [("Alice", 0.8), ("Bob", 0.6)],
    "Papers":  [("P1", 0.3), ("P2", 0.7)],
    "Topics":  [("T1", 0.5), ("T2", 0.9)],
}
edges = [("Alice", "P1"), ("Bob", "P2"), ("P1", "T1"), ("P2", "T2")]
fig = Q1NetworkPlots.hive_plot(nodes_by_axis, edges, palette="nature")
Q1FigureFactory(journal="nature").save(fig, "outputs/hive.svg")
```

### 13. Lotka curve

```python
from q1_figures.bibliometric_plots import BibliometricPlots
f = Q1FigureFactory(journal="nature")
fig, ax = f.new_figure_and_axes()
BibliometricPlots.lotka_curve(author_paper_counts)
f.set_axis_labels(ax, xlabel="Number of papers (x)", ylabel="Number of authors (1/x²)")
f.set_title(ax, "Lotka's law of scientific productivity")
f.finalize(fig)
f.save(fig, "outputs/lotka.svg")
```

### 14. Bradford's law

```python
from q1_figures.bibliometric_plots import BibliometricPlots
f = Q1FigureFactory(journal="nature")
fig, ax = f.new_figure_and_axes()
BibliometricPlots.bradford_curve(journal_paper_counts)
f.set_axis_labels(ax, xlabel="Journal rank", ylabel="Cumulative papers")
f.set_title(ax, "Bradford's law of scattering")
f.finalize(fig)
f.save(fig, "outputs/bradford.svg")
```

### 15. Zipf's law

```python
from q1_figures.bibliometric_plots import BibliometricPlots
f = Q1FigureFactory(journal="nature")
fig, ax = f.new_figure_and_axes()
term_freqs = [("the", 5078), ("of", 4213), ("and", 3087), ...]
BibliometricPlots.zipf_law_plot(term_freqs)
ax.set_xscale("log"); ax.set_yscale("log")
f.set_axis_labels(ax, xlabel="Rank", ylabel="Frequency")
f.set_title(ax, "Zipf's law of word frequency")
f.finalize(fig)
f.save(fig, "outputs/zipf.svg")
```

### 16. Network figure (Gephi-style with partition)

The `network_figure` helper accepts a `partition` dict (output of
`gephi_viz.partition.Partition.from_clustering`) and a `ranking` dict
(e.g. PageRank or degree). Nodes are sized by ranking and coloured by
partition. Use `label_top_n=10` to label only the top-10 nodes by
centrality — this is the Gephi default and prevents label overlap on
dense graphs.

```python
import networkx as nx
from gephi_viz.layouts import ForceAtlas2
from gephi_viz.partition import Partition
from networkx_pro.algorithms_centralities import Centralities

G = nx.karate_club_graph()
fa2 = ForceAtlas2()
pos = fa2.apply(G, iterations=200)              # positions
part = Partition.from_clustering(G, method="louvain")   # colour groups
rank = Centralities.pagerank(G)                         # node sizes (dict)
# Build a node → community_id map from the partition's groups:
comm = {node: idx for idx, group in enumerate(part.groups) for node in group}

fig = Q1NetworkPlots.network_figure(
    G, layout="fa2", partition=comm, ranking=rank, palette="nature",
    figsize=(3.5, 3.5), dpi=300, label_top_n=10,
    node_size_range=(20, 200), edge_alpha=0.3, show_legend=True,
)
Q1FigureFactory(journal="nature").save(fig, "outputs/network_gephi.svg")
```

---

## Common pitfalls

### 1. Forgetting to call `finalize()`

`finalize(fig)` applies the journal typography, the constrained
layout, and the spine / tick styling. Without it the figure renders
with matplotlib defaults — Times New Roman, 12 pt, all four spines.

### 2. Mixing palettes across panels

If your multi-panel figure uses different palettes in different
panels (e.g. `nature` in panel a, `jama` in panel b), the reviewer
will flag it as visually inconsistent. Always pass the same `palette=`
keyword to every panel-level helper.

### 3. Sizing raster formats below 300 DPI

PNG at 72 DPI fails most journal technical checks. Use `dpi=300`
minimum, `dpi=600` for line art:

```python
f.save(fig, "outputs/forest.png", dpi=600)
```

### 4. Letting matplotlib auto-choose fonts

The journal-specific typography is applied via
`Q1Typography.configure_matplotlib(journal)` inside the factory
constructor. If you build a `matplotlib.pyplot.figure()` directly, you
bypass this and lose the Arial/Helvetica/Times setting. Always go
through `Q1FigureFactory` or `MultiPanelFigure`.

### 5. Forgetting `axes.unicode_minus = False`

matplotlib's default minus sign is a Unicode character that some
journals' typesetting systems cannot render. The typography module
sets this flag for you — don't override it.

---

## Export checklist

Before submitting a figure to a Q1 journal, verify:

1. **DPI.** Vector formats (SVG/PDF) are resolution-independent. For
   raster (PNG/TIFF), verify ≥ 300 DPI for colour, ≥ 600 DPI for line
   art. (`f.save(fig, path, dpi=600)`).
2. **Colour mode.** RGB by default in matplotlib. Convert to CMYK only
   if the journal explicitly requires it (rare).
3. **Font embedding.** SVG and PDF both embed fonts by default in
   matplotlib ≥ 3.5. Verify with `pdffonts output.pdf` — every font
   should be `emb=yes`.
4. **Panel labels.** All multi-panel figures must have bold lowercase
   labels (a, b, c, d) in the top-left corner of each panel — use
   `f.annotate_panel(ax, label='a')`.
5. **Axis labels.** Every axis must have a label with units, e.g.
   `"Time (months)"`, `"log₂ fold change"`.
6. **Spines.** Q1 convention is to remove top and right spines —
   `f.style_axes(ax, spine_top=False, spine_right=False)`.
7. **Colour palette.** Match the journal — Nature (red-orange-blue),
   Lancet (navy-red), etc. Use `colorblind_safe` if any co-author is
   colour-vision-deficient.
8. **Figure size.** Match the column width: 89 / 120 / 183 mm.
9. **Significance bars.** Use star conventions (`*` / `**` / `***` /
   `n.s.`) and annotate the test used (e.g. "Mann–Whitney U").
10. **Legend.** Inline legends (no border, no title) preferred. Use
    `f.add_legend(ax, frame=False, fontsize=7)`.

```python
# Quick pre-submission self-check:
import os
assert os.path.getsize("outputs/forest.svg") > 5_000         # not empty
assert os.path.splitext("outputs/forest.svg")[1] == ".svg"   # vector
import matplotlib.font_manager as fm
fm.findfont("Arial", fallback_to_default=False)               # font resolves
```

---

*For more on the underlying statistical analyses that produce the data
behind these figures, see [META_ANALYSIS_GUIDE.md](META_ANALYSIS_GUIDE.md)
and [PRISMA_GUIDE.md](PRISMA_GUIDE.md). For the full list of plot
classes and their method signatures, see
[MODULE_REFERENCE.md](MODULE_REFERENCE.md).*
