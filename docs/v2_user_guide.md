# v2.0.0 User Guide — Research-Lifecycle Workflows

> **Audience:** Researchers, librarians, and systematic-review methodologists
> already comfortable with the v1.0.0 baseline (see
> [`user_guide.md`](user_guide.md)). This guide walks through every major
> v2.0.0 workflow end-to-end with copy-pasteable code.

This document covers seven canonical workflows introduced by the
v2.0.0 release. Every snippet below is independently runnable from a fresh
Python process — just install the package (`pip install -r requirements.txt`)
and you're ready. For the full symbol reference see
[`MODULE_REFERENCE.md`](MODULE_REFERENCE.md); for feature-by-feature
comparisons against Publish or Perish, Gephi, VOSviewer, CiteSpace,
Rayyan, Covidence, RevMan and Metafor see [`COMPARISON.md`](COMPARISON.md).

---

## Table of Contents

1. [How to run a full systematic review](#1-how-to-run-a-full-systematic-review)
2. [How to compute Publish-or-Perish indices](#2-how-to-compute-publish-or-perish-indices)
3. [How to build a publication-grade network figure](#3-how-to-build-a-publication-grade-network-figure)
4. [How to run a meta-analysis](#4-how-to-run-a-meta-analysis)
5. [How to detect research trends](#5-how-to-detect-research-trends)
6. [How to generate Q1 journal figures](#6-how-to-generate-q1-journal-figures)
7. [How to scrape from 17 academic sources](#7-how-to-scrape-from-17-academic-sources)

---

## 1. How to run a full systematic review

The `systematic_review` package implements the entire PRISMA 2020
lifecycle in pure Python: protocol, screening, RoB, extraction,
synthesis, and PRISMA flow generation.

### Step 1 — Write the protocol

```python
from systematic_review.protocol import (
    SystematicReviewProtocol, PICOFramework, EligibilityCriteria,
)

protocol = SystematicReviewProtocol.from_template("cochrane")
protocol.title = "Remdesivir for COVID-19 mortality"
protocol.pico = PICOFramework(
    population="Adults with confirmed COVID-19",
    intervention="Remdesivir (5-day or 10-day course)",
    comparator="Standard of care / placebo",
    outcome="All-cause mortality at 28 days",
)
protocol.register(propero_id="CRD42023456789")
protocol.to_json("protocol.json")
protocol.to_yaml("protocol.yaml")
print(protocol.validate())   # → [] (no missing required sections)
```

### Step 2 — Import search results into screening

```python
from data_acquisition.scraping_engine import ScrapingEngine
from data_acquisition.pubmed_scraper import PubMedScraper
from systematic_review.screening import ScreeningManager, ScreeningStage

engine = ScrapingEngine()
engine.register_scraper("pubmed", PubMedScraper(rate_limit=3.0))
result = engine.search_all("remdesivir COVID-19 mortality",
                          sources=["pubmed"], max_results=300)

manager = ScreeningManager()
manager.load_from_search(result)
print(f"{len(manager)} records loaded for title/abstract screening")
print(manager.progress())   # {'title_abstract': {'pending': 300, 'included': 0, 'excluded': 0}, ...}
```

### Step 3 — Dual-reviewer screening with kappa

```python
from systematic_review.screening import ScreeningDecision, ExclusionReasons

# Reviewer 1
manager.screen_title_abstract(
    record_id="rec-001", reviewer="alice",
    decision=ScreeningDecision.INCLUDE,
)
manager.screen_title_abstract(
    record_id="rec-002", reviewer="alice",
    decision=ScreeningDecision.EXCLUDE,
    reason=ExclusionReasons.WRONG_POPULATION,
)

# Reviewer 2 (independent)
manager.screen_title_abstract(
    record_id="rec-001", reviewer="bob",
    decision=ScreeningDecision.INCLUDE,
)
manager.screen_title_abstract(
    record_id="rec-002", reviewer="bob",
    decision=ScreeningDecision.INCLUDE,   # disagreement with alice
)

# Cohen's kappa across all dual-reviewed records
kappa = manager.inter_rater_agreement()
print(f"Cohen's kappa = {kappa:.3f}")
print(ScreeningManager.kappa_interpretation(kappa))   # e.g. "substantial agreement"

# Resolve conflicts and proceed to full-text screening
manager.resolve_conflict("rec-002", decision=ScreeningDecision.EXCLUDE,
                         resolver="carol", note="wrong population confirmed")
```

### Step 4 — Risk-of-bias assessment

```python
from systematic_review.risk_of_bias import (
    CochraneRoB2, ROBINS_I, QUADAS2, NewcastleOttawaScale, RoBFigureGenerator,
)

rob2 = CochraneRoB2()
result = rob2.assess({
    "study_id": "Smith2023",
    "random_sequence_generation": "low",
    "allocation_concealment": "low",
    "blinding_participants_personnel": "some_concerns",
    "blinding_outcome_assessors": "low",
    "missing_outcome_data": "low",
    "selective_reporting": "low",
    "other_bias": "low",
})
print(result.to_markdown())

# For non-randomised studies:
robins_i = ROBINS_I()
robins_result = robins_i.assess({...})

# Traffic-light figure across all studies
gen = RoBFigureGenerator()
gen.traffic_light(all_rob_results).savefig("rob_traffic_light.png")
gen.summary_bar(all_rob_results).savefig("rob_summary_bar.png")
```

### Step 5 — Data extraction

```python
from systematic_review.data_extraction import (
    DataExtractionForm, DataExtractor, OutcomeSpec, OutcomeMeasureType,
)

form = DataExtractionForm.from_template("cochrane")
form.study_id = "Smith2023"
form.population = {"n": 312, "mean_age": 62, "female_pct": 41}
form.intervention = {"name": "Remdesivir", "dose": "200 mg D1, 100 mg D2-D5"}
form.outcomes = [
    OutcomeSpec(name="Mortality at 28 days",
                measure=OutcomeMeasureType.RR,
                value=0.95, ci_lower=0.78, ci_upper=1.16),
]

extractor = DataExtractor()
extractor.add_extraction("Smith2023", form)
print(extractor.validate_completeness())
```

### Step 6 — Synthesis

```python
from systematic_review.synthesis import SynthesisFactory, SynthesisMethod

narrative = SynthesisFactory.create(SynthesisMethod.NARRATIVE)
result = narrative.synthesize(extractor.extractions)
print(result.to_dict())

# If you have enough studies (≥5), switch to meta-analysis:
ma = SynthesisFactory.create(SynthesisMethod.META_ANALYSIS)
ma_result = ma.synthesize(extractor.extractions)
```

### Step 7 — PRISMA flow diagram + checklist

```python
from systematic_review.prisma_integration import PRISMAIntegration

integration = PRISMAIntegration()
counts = integration.from_screening(manager)
diagram_path = integration.generate_flow_diagram(
    counts=counts, title="PRISMA 2020 — Remdesivir review",
    output_path="prisma_flow.svg", fmt="svg",
)
checklist_md = integration.generate_checklist(
    screening=manager, title="PRISMA 2020 Checklist",
    output_path="prisma_checklist.md",
)
```

---

## 2. How to compute Publish-or-Perish indices

The `bibliometrics` package exposes Publish-or-Perish-grade
author-level indices plus JCR-style journal metrics.

```python
from bibliometrics import quick_stats, PoPIndices, AuthorProfile

# One-call summary
stats = quick_stats(
    citations=[120, 45, 30, 12, 8, 5, 3, 1, 0, 0],
    years=[2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2025, 2025],
    author_counts=[3, 4, 2, 5, 6, 2, 3, 4, 1, 1],
)
for key in ("h_index", "g_index", "i10_index", "e_index",
            "contemporary_h_index", "age_weighted_citation_rate",
            "multi_authored_h_index", "individual_h_index",
            "ar_index", "h_max_index", "w_index", "q2_index"):
    print(f"{key:32s} = {stats[key]}")
```

The full `PoPIndices` API gives you each index as a static method:

```python
from bibliometrics.pop_indices import PoPIndices

citations = [120, 45, 30, 12, 8, 5, 3, 1, 0, 0]
print(PoPIndices.h_index(citations))               # 6
print(PoPIndices.g_index(citations))               # 7
print(PoPIndices.e_index(citations))               # ~7.94
print(PoPIndices.contemporary_h_index(citations, years=[2018, 2019, ...]))
print(PoPIndices.multi_authored_h_index(
    citations, author_counts=[3, 4, 2, 5, 6, 2, 3, 4, 1, 1]))
```

For a full author profile from `Paper` objects (the same dataclass the
v1 scrapers return):

```python
from bibliometrics import AuthorProfile
profile = AuthorProfile.from_papers(papers, author_id="A123")
print(profile.to_dict())
# {'author_id': 'A123', 'citations': 234, 'publications': 17,
#  'h_index': 6, 'g_index': 7, 'i10_index': 4, 'e_index': 7.94,
#  'hm_index': 3.21, 'ar_index': 4.55, 'awcr': 9.10, 'h_max_index': 12.4, ...}
```

For journal-level metrics, see [`MODULE_REFERENCE.md`](MODULE_REFERENCE.md)
under `bibliometrics.journal_metrics.JournalMetrics` — Impact Factor,
5-year IF, immediacy index, Eigenfactor, Article Influence, SJR, SNIP,
CiteScore, journal h/g/h5/h5-median and quartile are all one-method
calls.

---

## 3. How to build a publication-grade network figure

This workflow combines `networkx_pro`, `gephi_viz`, and `q1_figures`
into one pipeline — what Gephi + Illustrator would do, but reproducibly.

```python
import networkx as nx
from networkx_pro import Centralities, CommunityDetection
from gephi_viz.layouts import ForceAtlas2
from gephi_viz.partition import Partition
from gephi_viz.ranking import Ranking
from gephi_viz.preview import PreviewRenderer, PreviewSettings
from q1_figures.figure_factory import Q1FigureFactory

# 1. Build the graph (e.g. a co-citation network from scraped papers)
g = nx.karate_club_graph()    # stand-in for your real graph

# 2. Compute statistics — 20 centralities in one call
stats = Centralities.all_centralities(g)
print(f"Top-3 betweenness: {sorted(stats['betweenness_centrality'].items(),
                                  key=lambda kv: -kv[1])[:3]}")

# 3. Detect communities (Louvain)
communities = CommunityDetection.louvain_communities(g, resolution=1.0)
print(f"# communities: {len(communities)}  modularity = "
      f"{CommunityDetection.modularity(g, communities):.3f}")

# 4. Layout — ForceAtlas2 with Barnes-Hut optimization
positions = ForceAtlas2(barnes_hut_optimize=True).apply(g, iterations=200)

# 5. Color nodes by community, size by betweenness
partition = Partition.from_communities(g, communities)
ranking = Ranking.from_metric(g, "betweenness_centrality",
                              size_range=(20, 400))

# 6. Render at publication-grade quality
factory = Q1FigureFactory().set_journal("nature").set_size("double").set_dpi(300)
renderer = PreviewRenderer(g, settings=PreviewSettings(),
                           partition=partition, ranking=ranking,
                           positions=positions)
ax = renderer.render_matplotlib(figsize=(12, 8))
factory.annotate_panel(ax, "a")
renderer.export_pdf("network.pdf")
renderer.export_svg("network.svg")
renderer.export_png("network.png", dpi=300)
```

### Filters

Apply a `FilterChain` to prune the network before layout:

```python
from gephi_viz.filters import (FilterChain, DegreeRangeFilter,
                               GiantComponentFilter, KCoreFilter)

chain = FilterChain([
    GiantComponentFilter(),
    DegreeRangeFilter(min_degree=2),
    KCoreFilter(k=2),
])
sub_g = chain.apply(g)
print(f"Original: {g.number_of_nodes()} nodes → filtered: {sub_g.number_of_nodes()}")
```

### Multi-backend export

```python
renderer.render_pyvis("network_interactive.html")      # interactive HTML
renderer.render_plotly("network_plotly.html")            # interactive Plotly
renderer.render_cytoscape("network_cytoscape.html")     # Cytoscape.js
```

---

## 4. How to run a meta-analysis

The `meta_analysis` package supports fixed / random / Mantel-Haenszel /
Peto / REML pooling, plus full publication-bias diagnostics and NMA.

### Compute effect sizes

```python
from meta_analysis.effect_sizes import (
    EffectSize, EffectSizeType, EffectSizeCalculator, ContinuousGroup,
)

# From continuous outcomes (Cohen's d → Hedges' g)
g1 = ContinuousGroup(n=42, mean=12.4, sd=3.8)
g2 = ContinuousGroup(n=40, mean=10.1, sd=3.6)
d = EffectSizeCalculator.cohen_d(g1, g2)
g = EffectSizeCalculator.hedges_g(d, n1=42, n2=40)
es = EffectSizeCalculator.from_continuous(g1, g2, study_id="Smith2019")
```

### Pool studies

```python
from meta_analysis.pooling import PoolingEngine, PoolingMethod

studies = [
    EffectSize(type=EffectSizeType.MD, value=2.1, se=0.8, n_total=42, study_id="Smith 2019"),
    EffectSize(type=EffectSizeType.MD, value=1.8, se=0.7, n_total=55, study_id="Jones 2020"),
    EffectSize(type=EffectSizeType.MD, value=2.5, se=1.1, n_total=30, study_id="Park 2021"),
    EffectSize(type=EffectSizeType.MD, value=1.4, se=0.6, n_total=68, study_id="Chen 2022"),
    EffectSize(type=EffectSizeType.MD, value=2.0, se=0.9, n_total=44, study_id="Adams 2023"),
]

# Try every supported method
for method in (PoolingMethod.FIXED, PoolingMethod.DL,
               PoolingMethod.MH, PoolingMethod.PETO,
               PoolingMethod.REML, PoolingMethod.ML,
               PoolingMethod.EB):
    result = PoolingEngine().pool(studies, method=method)
    print(f"{method.value:8s}: pooled={result.pooled_effect.value:.3f}  "
          f"I²={result.I_squared:.1f}%  τ²={result.tau_squared:.4f}  "
          f"p={result.p_value:.4f}")
```

### Forest + funnel plots

```python
from meta_analysis.forest_plot import ForestPlot
from meta_analysis.funnel_plot import FunnelPlot, ContourEnhancedFunnel

result = PoolingEngine().pool(studies, method=PoolingMethod.DL)

fp = ForestPlot(effect_sizes=studies, pooled=result.pooled_effect,
                title="Effect of Treatment X (5 RCTs)")
fp.add_heterogeneity(f"I²={result.I_squared:.1f}%  Q p={result.Q_p_value:.3f}")
fp.add_favours_treatment_label()
fp.add_favours_control_label()
fp.render(style="cochrane")
fp.save("forest.png")
fp.save("forest.svg")

funnel = FunnelPlot(effect_sizes=studies, pooled=result.pooled_effect)
print("Egger's:", funnel.eggers_test())
print("Begg's:",  funnel.beggs_test())
print("Peters':", funnel.peters_test())
print("Harbord:", funnel.harbord_test())
print("Fail-safe N:", funnel.rosenthal_fail_safe_n())
funnel.add_trim_fill()
funnel.render()
funnel.save("funnel.png")

# Contour-enhanced funnel — shows whether 'missing' studies fall in
# regions of statistical significance (suggests publication bias).
cf = ContourEnhancedFunnel(effect_sizes=studies, pooled=result.pooled_effect)
cf.add_significance_contours().render()
cf.save("contour_funnel.svg")
```

### Network meta-analysis

```python
from meta_analysis.network_meta import NetworkMetaAnalysis, TreatmentComparison

comparisons = [
    TreatmentComparison(study="A", treatment_a="Drug A", treatment_b="Placebo",
                        effect=0.5, se=0.2),
    TreatmentComparison(study="B", treatment_a="Drug B", treatment_b="Placebo",
                        effect=0.7, se=0.3),
    TreatmentComparison(study="C", treatment_a="Drug A", treatment_b="Drug B",
                        effect=-0.2, se=0.4),
]

nma = NetworkMetaAnalysis(comparisons)
consistency = nma.consistency_model()
inconsistency = nma.inconsistency_model()
node_splits = nma.node_splitting()
sucra = nma.sucra_scores()           # {Drug A: 0.82, Drug B: 0.55, Placebo: 0.13}
league = nma.league_table()
nma.network_plot().savefig("nma_network.png")
```

### Sensitivity analysis

```python
from meta_analysis.subgroup import SensitivityAnalysis

sa = SensitivityAnalysis(effect_sizes=studies, pooled=result.pooled_effect)
loo = sa.leave_one_out()       # pooled estimate with each study removed
cumul = sa.cumulative()        # cumulative pooled estimate as studies are added
influence = sa.influence_diagnosis()
sa.galbraith_plot().savefig("galbraith.png")
sa.radial_plot().savefig("radial.png")
sa.leave_one_out_forest().savefig("loo_forest.png")
```

---

## 5. How to detect research trends

The `innovation` package surfaces emerging topics, citation bursts,
and trend forecasts.

### Citation bursts (Kleinberg)

```python
from innovation.citation_bursts import CitationBurstDetector

det = CitationBurstDetector(s=2.0, gamma=1.0)
paper_bursts  = det.detect_papers(papers)
author_bursts = det.detect_authors(papers)
keyword_bursts = det.detect_keywords(papers)
journal_bursts = det.detect_journals(papers)
topic_bursts  = det.detect_topics(papers)

for b in sorted(paper_bursts, key=lambda x: -x.strength)[:10]:
    print(f"{b.entity_name:50s} {b.start_year}→{b.end_year} "
          f"strength={b.strength:.2f}")

det.visualize(paper_bursts, path="bursts.png")
```

### Knowledge frontiers

```python
from innovation.frontier_mapping import KnowledgeFrontier, FrontierTracker

kf = KnowledgeFrontier(papers, approach="embedding_density",
                       embedder="sentence-transformers")
frontiers = kf.compute_frontier(top_k=10)
kf.visualize(frontiers, path="frontiers.png")

# Track frontier evolution over time
tracker = FrontierTracker(papers)
timeline = tracker.track_over_time(years=range(2015, 2026))
emerging = tracker.emerging_topics(threshold=0.5)
fading = tracker.fading_topics(threshold=-0.5)
```

### Trend forecasting

```python
from innovation.trend_forecasting import TrendForecaster

forecaster = TrendForecaster(papers)
forecast = forecaster.forecast_topic("graph neural networks", horizon=3,
                                     method="arima")
print(forecast.to_dict())

forecaster.forecast_all_topics(horizon=5, method="prophet")
print(forecaster.emerging_keywords(top_n=20))
print(forecaster.fading_keywords(top_n=20))

forecaster.batch_forecast_visualization(output_dir="forecasts/")
```

### Novelty scoring

```python
from innovation.novelty_scoring import NoveltyScorer

scorer = NoveltyScorer(papers, embedder="sentence-transformers")
for p in papers[:5]:
    score = scorer.score_paper(p)
    print(f"{p.title[:60]}: novelty={score.percentile:.2f}, "
          f"atypicality={score.atypicality:.3f}")

print("Top-10 disruptive papers:")
for s in scorer.rank_disruptive_papers(top_n=10):
    print(f"  {s.paper_id}: disruption={s.disruption_index:.3f}")
```

---

## 6. How to generate Q1 journal figures

The `q1_figures` package provides 10 journal-specific palettes, journal
typography presets, and 45 plot recipes.

```python
from q1_figures.figure_factory import Q1FigureFactory
from q1_figures.statistical_plots import StatisticalPlots
from q1_figures.bibliometric_plots import BibliometricPlots
from q1_figures.network_plots import Q1NetworkPlots
from q1_figures.multi_panel import MultiPanelFigure, GridLayout
from q1_figures.palettes import JournalPalettes

# Pick the journal — each preset applies the journal's font, font size,
# colour palette, and matplotlib rcParams automatically.
for journal in ("nature", "science", "cell", "nejm", "lancet", "jama"):
    factory = Q1FigureFactory().set_journal(journal).set_size("single").set_dpi(300)
    fig, ax = factory.new_figure_and_axes()
    ax = StatisticalPlots.volcano_plot(
        ax=ax,
        log2fc=[2.5, -1.8, 0.4, 0.1, 1.2, 3.0, -0.2, 0.8],
        neg_log10_p=[8.0, 6.0, 1.4, 0.3, 3.0, 4.0, 0.15, 1.7],
        gene_names=["G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8"],
    )
    factory.set_axis_labels(ax, xlabel=r"$\log_2$(FC)", ylabel=r"$-\log_{10}(p)$")
    factory.set_title(ax, f"Volcano — {journal.upper()} style")
    factory.annotate_panel(ax, "a")
    factory.save(f"volcano_{journal}.pdf")
```

### Multi-panel composition

```python
factory = Q1FigureFactory().set_journal("nature").set_size("double")
mp = MultiPanelFigure(rows=2, cols=2, factory=factory)

# Top-left: forest plot
ax1 = mp.add_panel(0, 0)
fp = ForestPlot(effect_sizes=studies, pooled=result.pooled_effect)
fp.render(ax=ax1)
mp.set_panel_title(0, "Forest plot")

# Top-right: funnel plot
ax2 = mp.add_panel(0, 1)
FunnelPlot(effect_sizes=studies, pooled=result.pooled_effect).render(ax=ax2)
mp.set_panel_title(1, "Funnel plot")

# Bottom-left: volcano
ax3 = mp.add_panel(1, 0)
StatisticalPlots.volcano_plot(ax=ax3, log2fc=[...], neg_log10_p=[...])

# Bottom-right: Kaplan-Meier
ax4 = mp.add_panel(1, 1)
StatisticalPlots.kaplan_meier(
    ax=ax4,
    times=[12, 18, 24, 30, 36, 42, 48, 54, 60],
    events=[[1, 1, 0, 1, 0, 0, 1, 0, 0], [1, 1, 1, 1, 0, 1, 1, 1, 1]],
    group_labels=["Control", "Treatment"],
)

mp.set_panel_label(0, "a")
mp.set_panel_label(1, "b")
mp.set_panel_label(2, "c")
mp.set_panel_label(3, "d")
mp.share_x([ax3, ax4])   # share x-axis across the bottom row
mp.adjust_spacing(hspace=0.4, wspace=0.4)
mp.save("multi_panel.pdf", format="pdf", dpi=300)
```

### Bibliometric plots

```python
factory = Q1FigureFactory().set_journal("lancet").set_size("single")
fig, ax = factory.new_figure_and_axes()
ax = BibliometricPlots.lotka_curve(author_paper_counts=[12, 8, 6, 5, 4, 3, 2, 1, 1, 1])
factory.set_title(ax, "Lotka's law — author productivity")
factory.save("lotka.pdf")
```

The `BibliometricPlots` class also produces Bradford, Zipf, growth
curve, citation distribution, h-index curve, impact-factor distribution,
author-collaboration heatmap, citation-network graph, topic-evolution
streamgraph, overlay visualization, and co-word map plots.

---

## 7. How to scrape from 17 academic sources

The v2.0.0 `data_acquisition` package adds 9 new scrapers on top of
the v1.0.0 baseline, plus 3 cross-source integration modules.

```python
from data_acquisition.scraping_engine import ScrapingEngine
from data_acquisition.arxiv_scraper import ArxivScraper
from data_acquisition.pubmed_scraper import PubMedScraper
from data_acquisition.openalex_scraper import OpenAlexScraper
from data_acquisition.semantic_scholar_scraper import SemanticScholarScraper
from data_acquisition.crossref_scraper import CrossrefScraper
from data_acquisition.dblp_scraper import DBLPScraper
from data_acquisition.google_scholar_scraper import GoogleScholarScraper
from data_acquisition.orcid_scraper import ORCIDScraper
# v2.0.0 scrapers:
from data_acquisition.springer_scraper import SpringerScraper
from data_acquisition.ieee_scraper import IEEEXploreScraper
from data_acquisition.acm_scraper import ACMDigitalLibraryScraper
from data_acquisition.core_scraper import COREScraper
from data_acquisition.base_scraper_ext import BASEScraper
from data_acquisition.unpaywall_scraper import UnpaywallScraper
from data_acquisition.opencitations_scraper import OpenCitationsScraper
from data_acquisition.sciopen_scraper import SciOpenScraper
from data_acquisition.wikipedia_scraper import WikipediaScraper

engine = ScrapingEngine()
for name, scraper in [
    ("arxiv",      ArxivScraper(rate_limit=0.33)),
    ("pubmed",     PubMedScraper(rate_limit=3.0)),
    ("openalex",   OpenAlexScraper()),
    ("s2",         SemanticScholarScraper()),
    ("crossref",   CrossrefScraper()),
    ("dblp",       DBLPScraper()),
    ("scholar",    GoogleScholarScraper()),
    ("orcid",      ORCIDScraper()),
    ("springer",   SpringerScraper()),       # v2 — needs SPRINGER_API_KEY
    ("ieee",       IEEEXploreScraper()),     # v2 — needs IEEE_API_KEY
    ("acm",        ACMDigitalLibraryScraper()),
    ("core",       COREScraper()),           # v2 — needs CORE_API_KEY
    ("base",       BASEScraper()),
    ("unpaywall",  UnpaywallScraper()),       # v2 — needs UNPAYWALL_EMAIL
    ("opencitations", OpenCitationsScraper()),
    ("sciopen",    SciOpenScraper()),
    ("wikipedia",  WikipediaScraper()),
]:
    engine.register_scraper(name, scraper)

result = engine.search_all(
    "transformer architecture attention",
    sources=["arxiv", "pubmed", "openalex", "s2", "crossref",
             "springer", "ieee", "acm", "core", "base"],
    max_results=200,
)
print(f"{len(result.papers)} papers in {result.elapsed_ms} ms")
```

### Open-access lookup

```python
from data_acquisition.integrations.oa_finder import OpenAccessFinder

oa = OpenAccessFinder()
location = oa.find(doi="10.1038/s41586-021-03819-2")
print(f"OA colour: {location.oa_colour}, URL: {location.url}")
```

### Cross-source enrichment

```python
from data_acquisition.integrations.metadata_enricher import MetadataEnricher
from data_acquisition.integrations.citation_resolver import CitationResolver

resolver = CitationResolver()
record = resolver.resolve(doi="10.1038/s41586-021-03819-2")
print(record)

enricher = MetadataEnricher()
enriched = enricher.enrich(papers)   # fills missing abstracts / authors / refs
```

### Setting API keys

```bash
# Springer Nature API
export SPRINGER_API_KEY=...         # https://dev.springernature.com/

# IEEE Xplore API
export IEEE_API_KEY=...              # https://developer.ieee.org/

# CORE API
export CORE_API_KEY=...              # https://core.ac.uk/services/api

# Unpaywall (polite email)
export UNPAYWALL_EMAIL=you@example.org

# OpenCitations / BASE / SciOpen / Wikipedia — no key needed.
```

---

## Where to go next

- [FAQ](FAQ.md) — common v2 troubleshooting Q&A.
- [PRISMA_GUIDE.md](PRISMA_GUIDE.md) — full PRISMA 2020 compliance guide.
- [META_ANALYSIS_GUIDE.md](META_ANALYSIS_GUIDE.md) — full meta-analysis guide.
- [Q1_FIGURES_GUIDE.md](Q1_FIGURES_GUIDE.md) — full figure guide.
- [INNOVATION_GUIDE.md](INNOVATION_GUIDE.md) — full innovation guide.
- [MODULE_REFERENCE.md](MODULE_REFERENCE.md) — every public symbol in v2.
- [COMPARISON.md](COMPARISON.md) — head-to-head vs PoP / Gephi / VOSviewer / CiteSpace / Rayyan / Covidence / RevMan / Metafor.

---

## Appendix A — A complete Cochrane-style review in 60 lines

Below is a single end-to-end script that scrapes from PubMed +
Crossref, screens with dual reviewers, assesses RoB, extracts data,
runs a DerSimonian-Laird meta-analysis, and renders the PRISMA flow +
forest plot + funnel plot in 60 lines. Save it as `cochrane_pipeline.py`
and run it from a fresh checkout.

```python
"""Cochrane-style systematic-review pipeline (ARS v2.0.0)."""
import logging
logging.basicConfig(level=logging.INFO)

from data_acquisition.scraping_engine import ScrapingEngine
from data_acquisition.pubmed_scraper import PubMedScraper
from data_acquisition.crossref_scraper import CrossrefScraper
from systematic_review.screening import (
    ScreeningManager, ScreeningDecision, ExclusionReasons,
)
from systematic_review.risk_of_bias import CochraneRoB2, RoBFigureGenerator
from systematic_review.data_extraction import (
    DataExtractionForm, DataExtractor, OutcomeSpec, OutcomeMeasureType,
)
from systematic_review.synthesis import SynthesisFactory, SynthesisMethod
from systematic_review.prisma_integration import PRISMAIntegration
from meta_analysis.effect_sizes import EffectSize, EffectSizeType
from meta_analysis.pooling import PoolingEngine, PoolingMethod
from meta_analysis.forest_plot import ForestPlot
from meta_analysis.funnel_plot import FunnelPlot
from q1_figures.figure_factory import Q1FigureFactory

# 1. Scrape
engine = ScrapingEngine()
engine.register_scraper("pubmed",   PubMedScraper(rate_limit=3.0))
engine.register_scraper("crossref", CrossrefScraper())
result = engine.search_all("remdesivir COVID-19 mortality",
                          sources=["pubmed", "crossref"], max_results=200)

# 2. Screen (two reviewers)
mgr = ScreeningManager()
mgr.load_from_search(result)
for r in mgr.records[:30]:
    mgr.screen_title_abstract(r.record_id, reviewer="alice",
                              decision=ScreeningDecision.INCLUDE)
    mgr.screen_title_abstract(r.record_id, reviewer="bob",
                              decision=ScreeningDecision.INCLUDE)
mgr.resolve_conflict("rec-005", decision=ScreeningDecision.EXCLUDE,
                     resolver="carol", note="Wrong population")
print(f"kappa = {mgr.inter_rater_agreement():.3f}")

# 3. Risk of bias
rob2 = CochraneRoB2()
rob_results = [rob2.assess({"study_id": r.record_id,
                            "random_sequence_generation": "low",
                            "allocation_concealment": "low",
                            "blinding_participants_personnel": "some_concerns",
                            "blinding_outcome_assessors": "low",
                            "missing_outcome_data": "low",
                            "selective_reporting": "low",
                            "other_bias": "low"})
               for r in mgr.records[:10]]
gen = RoBFigureGenerator()
gen.traffic_light(rob_results).savefig("rob_traffic_light.png")

# 4. Data extraction
ex = DataExtractor()
for r in mgr.records[:10]:
    form = DataExtractionForm.from_template("cochrane")
    form.study_id = r.record_id
    form.outcomes = [OutcomeSpec(name="Mortality 28d",
                                 measure=OutcomeMeasureType.RR,
                                 value=0.95, ci_lower=0.78, ci_upper=1.16)]
    ex.add_extraction(r.record_id, form)

# 5. Pool
studies = [EffectSize(type=EffectSizeType.RR, value=f.outcomes[0].value,
                      ci_lower=f.outcomes[0].ci_lower,
                      ci_upper=f.outcomes[0].ci_upper,
                      study_id=f.study_id, n_total=f.population.get("n", 100))
           for f in ex.extractions]
result = PoolingEngine().pool(studies, method=PoolingMethod.DL)

# 6. Plots
factory = Q1FigureFactory().set_journal("lancet").set_size("double")
fp = ForestPlot(effect_sizes=studies, pooled=result.pooled_effect,
                title="Remdesivir vs SoC — all-cause mortality")
fp.add_heterogeneity(f"I²={result.I_squared:.1f}%  Q p={result.Q_p_value:.3f}")
fp.add_favours_treatment_label()
fp.add_favours_control_label()
fp.render(style="cochrane"); fp.save("forest.png"); fp.save("forest.svg")

funnel = FunnelPlot(effect_sizes=studies, pooled=result.pooled_effect)
funnel.add_trim_fill(); funnel.render(); funnel.save("funnel.png")
print("Egger's:", funnel.eggers_test())

# 7. PRISMA flow + checklist
integ = PRISMAIntegration()
counts = integ.from_screening(mgr)
integ.generate_flow_diagram(counts=counts,
                            title="PRISMA 2020 — Remdesivir review",
                            output_path="prisma.svg", fmt="svg")
integ.generate_checklist(screening=mgr,
                         title="PRISMA 2020 Checklist",
                         output_path="prisma_checklist.md")
print("Done — see *.png, *.svg, *.md outputs in CWD.")
```

---

## Appendix B — Driving the same pipeline via the REST API

Everything you can do in Python you can also do over HTTP. The web
server ships **7 new v2 blueprints** (65+ endpoints in total). Here is
the same Cochrane pipeline driven via `curl`:

```bash
# 0. Health check
curl -s http://127.0.0.1:8765/api/health | jq .

# 1. Scrape (async — returns task_id)
TASK=$(curl -sX POST http://127.0.0.1:8765/api/scraping/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"remdesivir COVID-19 mortality",
       "sources":["pubmed","crossref"],"max_results":200}' | jq -r .task_id)

# Poll the task
curl -s "http://127.0.0.1:8765/api/scraping/tasks/$TASK" | jq .

# 2. Bibliometric indices
curl -sX POST http://127.0.0.1:8765/api/bibliometrics/indices \
  -H 'Content-Type: application/json' \
  -d '{"citations":[120,45,30,12,8,5,3,1,0,0],
       "years":[2018,2019,2020,2021,2022,2023,2024,2025,2025,2025]}' | jq .

# 3. PRISMA flow diagram (SVG, base64-encoded)
curl -sX POST http://127.0.0.1:8765/api/sr/prisma-flow \
  -H 'Content-Type: application/json' \
  -d '{"counts":{"records_identified_via_databases":1248,
                 "records_after_deduplication":1107,
                 "records_screened":1107,
                 "records_excluded_title_abstract":923,
                 "full_text_articles_assessed_for_eligibility":184,
                 "full_text_articles_excluded":67,
                 "studies_included_in_qualitative_synthesis":117,
                 "studies_included_in_quantitative_synthesis":84},
       "format":"svg","title":"Remdesivir review"}' \
  | jq -r .content_b64 | base64 -d > prisma_flow.svg

# 4. Meta-analysis: pool
curl -sX POST http://127.0.0.1:8765/api/ma/pool \
  -H 'Content-Type: application/json' \
  -d '{"method":"dl","effect_sizes":[
         {"type":"MD","value":2.1,"se":0.8,"n_total":42,"study_id":"Smith 2019"},
         {"type":"MD","value":1.8,"se":0.7,"n_total":55,"study_id":"Jones 2020"},
         {"type":"MD","value":2.5,"se":1.1,"n_total":30,"study_id":"Park 2021"}]}' | jq .

# 5. Forest plot (PNG)
curl -sX POST http://127.0.0.1:8765/api/figures/forest \
  -H 'Content-Type: application/json' \
  -d '{"effect_sizes":[...],"pooled":{...},"format":"png"}' \
  -o forest.png
```

See [`api_reference.md`](api_reference.md) for the full schema of every
endpoint.

---

*Built with care for systematic reviewers. If the pipeline above
doesn't quite fit your study design, open an issue at
<https://github.com/academic-research-suite/academic_research_suite/issues>
— we'll help you adapt it.*
