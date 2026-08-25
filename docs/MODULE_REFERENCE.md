# Module Reference — v2.0.0 Public Symbols

> **Quick-reference card for every public class and function added in
> v2.0.0.** Each entry shows the module path, signature summary, a
> one-line description, and a runnable example. For the full prose
> walkthrough see [`v2_user_guide.md`](v2_user_guide.md); for v1.0.0
> symbols see the source-tree docstrings.

Every symbol below is **verified against the actual code** as of
v2.0.0 (commit on 2026-08-25). Where a method signature is shortened
for readability the ellipsis is shown as `...`.

---

## Table of Contents

1. [bibliometrics](#bibliometrics)
2. [networkx_pro](#networkx_pro)
3. [gephi_viz](#gephi_viz)
4. [systematic_review](#systematic_review)
5. [meta_analysis](#meta_analysis)
6. [prisma](#prisma)
7. [q1_figures](#q1_figures)
8. [research_lifecycle](#research_lifecycle)
9. [innovation](#innovation)
10. [data_acquisition (v2 additions)](#data_acquisition-v2-additions)
11. [web/routes (v2 additions)](#webroutes-v2-additions)

---

## bibliometrics

### `bibliometrics` — package-level helpers

| Symbol | Module | Description |
|---|---|---|
| `quick_stats(citations, years=None, author_counts=None)` | `bibliometrics` | One-call summary returning h, g, i10, e, h_core, h_max, w, q2, hc, AWCR, AR, hm, hi as a dict. |
| `PoPIndices` | `bibliometrics.pop_indices` | Stateless class with 13 author-level indices (one static method per index) + `compute_all`. |
| `AuthorProfile` | `bibliometrics.pop_indices` | Per-author profile dataclass built from a list of `Paper`. |
| `JournalMetrics` | `bibliometrics.journal_metrics` | JCR-style journal metrics (IF, 5-year IF, immediacy, Eigenfactor, Article Influence, SJR, SNIP, CiteScore, journal h/g/h5/h5-median, quartile). |
| `JournalProfile` | `bibliometrics.journal_metrics` | Per-journal profile dataclass built from a list of `Paper`. |
| `VOSAnalyzer` | `bibliometrics.vosviewer` | VOSviewer-style analyses (coupling, co-citation, co-authorship, term co-occurrence, overlay, cluster). |
| `CiteSpaceAnalyzer` | `bibliometrics.citespace` | CiteSpace-style analyses (bursts, knowledge-domain map, timezone view, spectral view, structural variation, landmark papers, turning points, research fronts). |
| `Burst` | `bibliometrics.citespace` | Dataclass for a single detected citation burst. |
| `ResearchFront` | `bibliometrics.citespace` | Dataclass for a detected research front. |
| `ScientogramBuilder` | `bibliometrics.scientogram` | Sci2 / Leydesdorff-style scientograms (co-word, co-journal, institute collaboration matrices + normalize + prune + layout). |

```python
from bibliometrics import quick_stats, PoPIndices, AuthorProfile
from bibliometrics import JournalMetrics, VOSAnalyzer, CiteSpaceAnalyzer, ScientogramBuilder

stats = quick_stats([120, 45, 30, 12, 8, 5, 3, 1, 0, 0])
print(stats["h_index"], stats["e_index"])

profile = AuthorProfile.from_papers(papers, author_id="A1")
print(profile.to_dict())

jm = JournalMetrics()
print(jm.impact_factor(papers, journal="Nature", year=2023))

vos = VOSAnalyzer()
coupling_graph = vos.bibliographic_coupling(papers)
coauthor_graph = vos.co_authorship_analysis(papers)

cs = CiteSpaceAnalyzer()
bursts = cs.detect_citation_bursts(papers)
fronts = cs.research_fronts(papers)
landmark = cs.landmark_papers(papers, top_n=10)

sb = ScientogramBuilder()
coword = sb.co_word_matrix(papers)
sb.build_scientogram(papers, output_path="scientogram.png")
```

### `PoPIndices` — full method list

| Method | Returns | Description |
|---|---|---|
| `h_index(citations)` | `int` | Hirsch h-index. |
| `g_index(citations)` | `int` | Egghe g-index. |
| `i10_index(citations)` | `int` | Google i10-index. |
| `h_core(citations)` | `List[int]` | Citations in the h-core. |
| `e_index(citations)` | `float` | Zhang e-index. |
| `contemporary_h_index(citations, years, current_year=None)` | `float` | Sidiropoulos hc-index. |
| `age_weighted_citation_rate(citations, years, current_year=None)` | `float` | Jin AWCR (AWCR). |
| `multi_authored_h_index(citations, author_counts)` | `float` | Schreiber hm-index. |
| `individual_h_index(citations, author_counts)` | `float` | Batista hi-index. |
| `ar_index(citations, years, current_year=None)` | `float` | Jin AR-index. |
| `normalized_h_index(citations, years, current_year=None)` | `float` | Sidiropoulos normalized h. |
| `q2_index(citations)` | `int` | PoP-extension q2-index. |
| `w_index(citations)` | `int` | PoP-extension w-index. |
| `h_max_index(citations)` | `float` | PoP-extension h_max-index. |
| `compute_all(citations, years=None, author_counts=None)` | `Dict[str, Any]` | All-of-the-above in one call. |

---

## networkx_pro

Ten stateless classes covering **60+ NetworkX algorithms**. Every
method takes a `networkx.Graph` (or DiGraph / MultiGraph /
MultiDiGraph) as its first argument; no method mutates its input.

| Symbol | Module | Description |
|---|---|---|
| `Centralities` | `networkx_pro.algorithms_centralities` | 20 centrality measures + `all_centralities` aggregator. |
| `CommunityDetection` | `networkx_pro.algorithms_communities` | Louvain, greedy modularity, label propagation (sync/async), Girvan-Newman, k-clique; plus modularity, partition quality, density, silhouette, NMI/AMI/ARI/VI. |
| `ComponentAnalysis` | `networkx_pro.algorithms_components` | Connected / strongly / weakly components, condensation, articulation points, bridges, k-core / k-shell / k-crust / k-corona / k-truss, core_number, onion_layers, cliques, max-weight clique, triangles, transitivity, average clustering. |
| `PathsAndFlows` | `networkx_pro.algorithms_paths_flows` | Shortest paths (single/all/all-pairs), diameter/radius/eccentricity/center/periphery, max-flow/min-cut, Edmonds-Karp, Ford-Fulkerson, edge/node disjoint paths, A*, all simple paths. |
| `LinkPrediction` | `networkx_pro.algorithms_link_prediction` | Resource allocation, Jaccard, Adamic-Adar, preferential attachment, Soundarajan-Hopcroft (CN/RA), within-inter-cluster, common-neighbour centrality, Katz similarity, `predict_top_links`. |
| `Isomorphism` | `networkx_pro.algorithms_isomorphism` | `is_isomorphic`, `could_be_isomorphic`, `faster_could_be_isomorphic`, `is_isomorphic_to`, VF2 graph isomorphism, `graph_census`, `find_motifs`. |
| `BipartiteAnalysis` | `networkx_pro.algorithms_bipartite` | `is_bipartite`, sets, density, degrees, projections (simple / weighted / collaboration / generic), clustering, average clustering, redundancy. |
| `GraphGenerators` | `networkx_pro.algorithms_generators` | Complete / complete_bipartite / Karate / Davis / Florentine / Erdős-Rényi / Watts-Strogatz / Barabási-Albert / powerlaw-cluster / random-geometric / configuration / expected-degree / Havel-Hakimi / random-tree / random-cograph + `null_model`. |
| `GraphIO` | `networkx_pro.graph_io` | Read/write GraphML / GEXF / GML / Pajek / edgelist / adjlist; JSON (node-link), Cytoscape JSON, pyvis Network, d3-force layout dict. |
| `MultiGraphAnalysis` | `networkx_pro.multigraph` | Multi-degree centrality, parallel-edge aggregation, parallel-edge counting, multi-edge-aware PageRank. |

```python
import networkx as nx
from networkx_pro import (Centralities, CommunityDetection, ComponentAnalysis,
                          PathsAndFlows, LinkPrediction, Isomorphism,
                          BipartiteAnalysis, GraphGenerators, GraphIO,
                          MultiGraphAnalysis)

g = nx.karate_club_graph()

# 20 centralities in one call
cent = Centralities.all_centralities(g)
print(cent["betweenness_centrality"])

# Community detection
communities = CommunityDetection.louvain_communities(g, resolution=1.0)
print(CommunityDetection.modularity(g, communities))

# Components
print(ComponentAnalysis.k_core(g, k=3).number_of_nodes())
print(ComponentAnalysis.k_truss(g, k=3).number_of_edges())

# Paths & flows
print(PathsAndFlows.diameter(g))
print(PathsAndFlows.maximum_flow(g, _s=0, _t=33))

# Link prediction
preds = LinkPrediction.adamic_adar_index(g, [(0, 1), (0, 2), (0, 33)])
print(list(preds)[:3])

# Bipartite
B = GraphGenerators.complete_bipartite_graph(5, 5)
print(BipartiteAnalysis.bipartite_density(B, nodes=list(range(5))))

# Generators + IO
g2 = GraphGenerators.barabasi_albert_graph(n=100, m=3)
GraphIO.write_gexf(g2, "ba.gexf")
GraphIO.write_graphml(g2, "ba.graphml")
GraphIO.to_json(g2)

# Multigraph
MG = nx.MultiGraph()
MG.add_edges_from([(1, 2), (1, 2), (2, 3)])
print(MultiGraphAnalysis.parallel_edge_count(MG, 1, 2))   # 2
```

---

## gephi_viz

Eleven layout algorithms, fifteen filters, Gephi-grade statistics,
partition coloring, ranking-based sizing, multi-backend renderer,
Qt-embedded interactive canvas.

| Symbol | Module | Description |
|---|---|---|
| `LayoutAlgorithm` | `gephi_viz.layouts` | Abstract base class for all layouts. |
| `ForceAtlas2` | `gephi_viz.layouts` | Jacomy et al. 2014 — Barnes-Hut optimized. |
| `OpenOrd` | `gephi_viz.layouts` | Martin et al. — simulated-annealing multi-stage. |
| `YifanHu` | `gephi_viz.layouts` | Hu — multilevel force-directed. |
| `FruchtermanReingold` | `gephi_viz.layouts` | Classic FR layout. |
| `KamadaKawai` | `gephi_viz.layouts` | Kamada-Kawai path-length layout. |
| `CircularLayout` | `gephi_viz.layouts` | Circle layout. |
| `GridLayout` | `gephi_viz.layouts` | Grid layout. |
| `RadialLayout` | `gephi_viz.layouts` | Radial / concentric circles. |
| `HierarchicalLayout` | `gephi_viz.layouts` | Top-down / left-right hierarchy. |
| `GeoLayout` | `gephi_viz.layouts` | Lat/lon geographic layout. |
| `LayoutPipeline` | `gephi_viz.layouts` | Chained layout pass. |
| `Filter` | `gephi_viz.filters` | Abstract filter base. |
| `DegreeRangeFilter` | `gephi_viz.filters` | Filter by node degree range. |
| `WeightRangeFilter` | `gephi_viz.filters` | Filter by node weight. |
| `EdgeWeightRangeFilter` | `gephi_viz.filters` | Filter by edge weight. |
| `PropertyValueRangeFilter` | `gephi_viz.filters` | Filter by node property range. |
| `GiantComponentFilter` | `gephi_viz.filters` | Keep only the giant component. |
| `ConnectedComponentsFilter` | `gephi_viz.filters` | Keep N largest components. |
| `KCoreFilter` | `gephi_viz.filters` | Keep k-core. |
| `EgoNetworkFilter` | `gephi_viz.filters` | Keep ego network of a node. |
| `ShortestPathFilter` | `gephi_viz.filters` | Keep shortest path between two nodes. |
| `MutualEdgeFilter` | `gephi_viz.filters` | Keep mutual edges only. |
| `ParallelEdgeFilter` | `gephi_viz.filters` | Remove parallel edges. |
| `PartitionFilter` | `gephi_viz.filters` | Keep nodes in selected partitions. |
| `EqualPropertyFilter` | `gephi_viz.filters` | Keep nodes matching a property value. |
| `EdgeTypeFilter` | `gephi_viz.filters` | Filter by edge type attribute. |
| `InterEdgesFilter` | `gephi_viz.filters` | Keep inter-partition edges only. |
| `TimeRangeFilter` | `gephi_viz.filters` | Filter by time interval (dynamic graphs). |
| `FilterChain` | `gephi_viz.filters` | Compose filters sequentially. |
| `NetworkStatsReport` | `gephi_viz.statistics` | Gephi "Statistics" panel — centrality, modularity, diameter, HITS, PageRank, components. |
| `NetworkStatistics` | `gephi_viz.statistics` | Stand-alone statistics helpers. |
| `nx_density` | `gephi_viz.statistics` | Density helper. |
| `Partition` | `gephi_viz.partition` | Node→group mapping with palette support. |
| `Ranking` | `gephi_viz.ranking` | Ranking-based node sizing / coloring / edge widths / label selection. |
| `PreviewSettings` | `gephi_viz.preview` | Configuration dataclass for the preview renderer. |
| `PreviewRenderer` | `gephi_viz.preview` | Multi-backend publication-grade renderer. |
| `InteractiveNetworkCanvas` | `gephi_viz.interactive_canvas` | Qt-embedded interactive canvas. |

```python
import networkx as nx
from networkx_pro import CommunityDetection
from gephi_viz.layouts import ForceAtlas2
from gephi_viz.filters import FilterChain, GiantComponentFilter, KCoreFilter
from gephi_viz.partition import Partition
from gephi_viz.ranking import Ranking
from gephi_viz.preview import PreviewRenderer, PreviewSettings
from gephi_viz.statistics import NetworkStatistics

g = nx.karate_club_graph()

# Filter → layout → partition → ranking → render
chain = FilterChain([GiantComponentFilter(), KCoreFilter(k=2)])
g = chain.apply(g)

positions = ForceAtlas2(barnes_hut_optimize=True).apply(g, iterations=200)

communities = CommunityDetection.louvain_communities(g, resolution=1.0)
partition = Partition.from_communities(g, communities)

ranking = Ranking.from_node_attribute(g, "degree")

stats = NetworkStatistics()
report = stats.compute(g)
print(report.to_dict())

renderer = PreviewRenderer(g, settings=PreviewSettings(),
                           partition=partition, ranking=ranking,
                           positions=positions)
ax = renderer.render_matplotlib(figsize=(10, 8))
renderer.export_png("network.png", dpi=300)
renderer.export_svg("network.svg")
renderer.render_pyvis("network.html")
renderer.render_plotly("network_plotly.html")
renderer.render_cytoscape("network_cytoscape.html")
```

---

## systematic_review

The full PRISMA 2020 systematic-review lifecycle in seven modules.

| Symbol | Module | Description |
|---|---|---|
| `PICOFramework` | `systematic_review.protocol` | PICO dataclass. |
| `EligibilityCriteria` | `systematic_review.protocol` | Inclusion / exclusion criteria. |
| `SystematicReviewProtocol` | `systematic_review.protocol` | Full protocol with versioning + PROSPERO registration; `from_template`, `to_json`, `to_yaml`, `validate`. |
| `ScreeningStage` | `systematic_review.screening` | Enum: title_abstract / full_text. |
| `ScreeningDecision` | `systematic_review.screening` | Enum: include / exclude / maybe. |
| `ExclusionReasons` | `systematic_review.exclusion_reasons` | Enum of canonical exclusion reasons. |
| `ScreeningRecord` | `systematic_review.screening` | Per-record dataclass with dual-reviewer support. |
| `ScreeningManager` | `systematic_review.screening` | The dual-reviewer screening engine with kappa + conflict resolution + auto-dedup. |
| `Rob2Judgment`, `RobinsIJudgment`, `Quadas2Judgment` | `systematic_review.risk_of_bias` | Enum judgments per RoB tool. |
| `RoBResult` | `systematic_review.risk_of_bias` | Per-study RoB result dataclass. |
| `RiskOfBiasTool` | `systematic_review.risk_of_bias` | Abstract base for all RoB tools. |
| `CochraneRoB2` | `systematic_review.risk_of_bias` | Cochrane RoB 2 (RCTs). |
| `ROBINS_I` | `systematic_review.risk_of_bias` | ROBINS-I (non-randomised). |
| `QUADAS2` | `systematic_review.risk_of_bias` | QUADAS-2 (diagnostic accuracy). |
| `NewcastleOttawaScale` | `systematic_review.risk_of_bias` | NOS (observational). |
| `RoBFigureGenerator` | `systematic_review.risk_of_bias` | Traffic-light + summary-bar figures. |
| `OutcomeMeasureType` | `systematic_review.data_extraction` | Enum: MD/SMD/RR/OR/HR/RD. |
| `OutcomeSpec` | `systematic_review.data_extraction` | Outcome definition dataclass. |
| `EffectSize` | `systematic_review.data_extraction` | SR-package effect size (legacy). |
| `PopulationData`, `InterventionData`, `ResultsData` | `systematic_review.data_extraction` | PICO alignment. |
| `DataExtractionForm` | `systematic_review.data_extraction` | Per-study extraction form. |
| `DataExtractor` | `systematic_review.data_extraction` | Multi-study extraction manager. |
| `SynthesisMethod` | `systematic_review.synthesis` | Enum: narrative / thematic / qca / meta-analysis / NMA. |
| `NarrativeSummary`, `NarrativeSynthesis` | `systematic_review.synthesis` | Narrative synthesis. |
| `QCAResult`, `QualitativeComparativeAnalysis` | `systematic_review.synthesis` | QCA. |
| `SWiMReportingChecklist` | `systematic_review.synthesis` | SWiM 9-item reporting checklist. |
| `Synthesizer` (ABC), `_NarrativeSynthesizer`, `_QCASynthesizer`, `_MetaAnalysisSynthesizer`, `_NetworkMetaAnalysisSynthesizer` | `systematic_review.synthesis` | Synthesizer hierarchy. |
| `SynthesisFactory` | `systematic_review.synthesis` | Factory dispatching `SynthesisMethod` → `Synthesizer`. |
| `PRISMAIntegration` | `systematic_review.prisma_integration` | One-call bridge between ScreeningManager and `prisma.PRISMAFlowGenerator`. |

```python
from systematic_review.screening import (
    ScreeningManager, ScreeningDecision, ExclusionReasons,
)
from systematic_review.risk_of_bias import CochraneRoB2, ROBINS_I, RoBFigureGenerator
from systematic_review.data_extraction import (
    DataExtractionForm, DataExtractor, OutcomeSpec, OutcomeMeasureType,
)
from systematic_review.synthesis import SynthesisFactory, SynthesisMethod
from systematic_review.prisma_integration import PRISMAIntegration

mgr = ScreeningManager()
mgr.load_from_search(result)
mgr.screen_title_abstract("rec-001", reviewer="alice",
                          decision=ScreeningDecision.INCLUDE)
mgr.screen_title_abstract("rec-002", reviewer="alice",
                          decision=ScreeningDecision.EXCLUDE,
                          reason=ExclusionReasons.WRONG_DESIGN)
print(mgr.inter_rater_agreement())   # Cohen's kappa

rob = CochraneRoB2().assess({...})
RoBFigureGenerator().traffic_light([rob]).savefig("rob.png")

ex = DataExtractor()
ex.add_extraction("S1", DataExtractionForm.from_template("cochrane"))

synth = SynthesisFactory.create(SynthesisMethod.NARRATIVE)
result = synth.synthesize(ex.extractions)

integ = PRISMAIntegration()
counts = integ.from_screening(mgr)
integ.generate_flow_diagram(counts=counts, title="...",
                            output_path="prisma.svg", fmt="svg")
```

---

## meta_analysis

| Symbol | Module | Description |
|---|---|---|
| `EffectSizeType` | `meta_analysis.effect_sizes` | Enum: MD/SMD/RR/OR/HR/RD/RRR/NNT. |
| `ContinuousGroup` | `meta_analysis.effect_sizes` | n/mean/sd summary for a continuous arm. |
| `EffectSize` | `meta_analysis.effect_sizes` | Per-study effect dataclass with CI + variance + study_id. |
| `EffectSizeCalculator` | `meta_analysis.effect_sizes` | Cohen's d, Hedges' g, Glass's Δ, mean diff, RR, OR, HR + `to_log_scale` / `to_natural_scale` / `to_rrr` / `to_nnt` / `confidence_interval`. |
| `PoolingMethod` | `meta_analysis.pooling` | Enum: FIXED / IV / RANDOM / MH / PETO / DL / REML / ML / EB. |
| `Heterogeneity` | `meta_analysis.pooling` | Q / τ² / I² / H² + interpretation. |
| `MetaAnalysisResult` | `meta_analysis.pooling` | Full pooling result dataclass. |
| `PoolingEngine` | `meta_analysis.pooling` | The pooling engine — `pool(es_list, method=...)`. |
| `SubgroupResult` | `meta_analysis.subgroup` | Per-subgroup pooling result. |
| `SubgroupAnalysis` | `meta_analysis.subgroup` | `analyze` + `test_for_subgroup_differences`. |
| `SensitivityAnalysis` | `meta_analysis.subgroup` | `leave_one_out`, `cumulative`, `influence_diagnosis`, `galbraith_plot`, `radial_plot`, `leave_one_out_forest`. |
| `ForestPlot` | `meta_analysis.forest_plot` | Publication-grade forest plot with subgroups, diamonds, favours labels. |
| `FunnelPlot` | `meta_analysis.funnel_plot` | Funnel plot with Egger/Begg/Peters/Harbord tests, trim-and-fill, Rosenthal fail-safe N, ORP. |
| `ContourEnhancedFunnel` | `meta_analysis.funnel_plot` | Contour-enhanced funnel subclass. |
| `TreatmentComparison` | `meta_analysis.network_meta` | Pairwise comparison dataclass for NMA. |
| `InconsistencyTest` | `meta_analysis.network_meta` | Node-splitting result. |
| `NMAResult` | `meta_analysis.network_meta` | Full NMA result. |
| `NetworkMetaAnalysis` | `meta_analysis.network_meta` | `consistency_model`, `inconsistency_model`, `node_splitting`, `rank_probability`, `sucra_scores`, `league_table`, `network_plot`. |
| `MetaAnalysisReport` | `meta_analysis.report` | PDF / DOCX / HTML / Markdown report with characteristics table, summary-of-findings, GRADE. |

```python
from meta_analysis.effect_sizes import (
    EffectSize, EffectSizeType, EffectSizeCalculator, ContinuousGroup,
)
from meta_analysis.pooling import PoolingEngine, PoolingMethod
from meta_analysis.subgroup import SubgroupAnalysis, SensitivityAnalysis
from meta_analysis.forest_plot import ForestPlot
from meta_analysis.funnel_plot import FunnelPlot, ContourEnhancedFunnel
from meta_analysis.network_meta import NetworkMetaAnalysis, TreatmentComparison
from meta_analysis.report import MetaAnalysisReport

studies = [
    EffectSize(type=EffectSizeType.MD, value=2.1, se=0.8, n_total=42, study_id="S1"),
    EffectSize(type=EffectSizeType.MD, value=1.8, se=0.7, n_total=55, study_id="S2"),
    EffectSize(type=EffectSizeType.MD, value=2.5, se=1.1, n_total=30, study_id="S3"),
]
result = PoolingEngine().pool(studies, method=PoolingMethod.DL)
print(result.to_markdown())

fp = ForestPlot(effect_sizes=studies, pooled=result.pooled_effect)
fp.render(); fp.save("forest.png")

funnel = FunnelPlot(effect_sizes=studies, pooled=result.pooled_effect)
print(funnel.eggers_test(), funnel.beggs_test(), funnel.peters_test(),
      funnel.harbord_test(), funnel.rosenthal_fail_safe_n())
funnel.add_trim_fill(); funnel.render(); funnel.save("funnel.png")

sa = SensitivityAnalysis(effect_sizes=studies, pooled=result.pooled_effect)
print(sa.leave_one_out())
sa.galbraith_plot().savefig("galbraith.png")

nma = NetworkMetaAnalysis([
    TreatmentComparison(study="A", treatment_a="Drug", treatment_b="Placebo",
                        effect=0.5, se=0.2),
    TreatmentComparison(study="B", treatment_a="Drug", treatment_b="Placebo",
                        effect=0.6, se=0.3),
])
print(nma.sucra_scores())
print(nma.league_table())

report = MetaAnalysisReport(result=result, effect_sizes=studies)
report.generate("meta_report.pdf", format="pdf")
```

---

## prisma

| Symbol | Module | Description |
|---|---|---|
| `PRISMAStageCounts` | `prisma.flow_diagram` | Stage counts dataclass. |
| `PRISMAFlowGenerator` | `prisma.flow_diagram` | Renders the canonical PRISMA 2020 flow diagram to matplotlib / SVG / PDF / PNG / HTML; supports BMJ and BMJ-style templates; `to_dot` for Graphviz. |
| `PRISMAItem` | `prisma.checklist` | Single 27-item checklist entry. |
| `PRISMAChecklist` | `prisma.checklist` | 27-item PRISMA 2020 checklist with `completion_rate`, `missing_items`, `to_markdown`, `to_yaml`, `to_pdf`, `to_docx`. |
| `PRISMAExtensionsChecklist` | `prisma.checklist` | 6 official extensions: IPD / NMA / ScR / Harms / Abstract / Diagnostic. |
| `PRISMAExtension` (Enum) | `prisma.extensions` | Enum of the 6 extensions. |
| `PRISMAExtensionGenerator` | `prisma.extensions` | Generates extension-specific flow diagrams. |
| `PRISMAExtractionForm` | `prisma.extraction_form` | Per-study extraction form. |
| `PRISMASearchStrategy` | `prisma.extraction_form` | Search-strategy dataclass. |
| `PRISMAReport` | `prisma.report` | Auto-filled printable report (flow + checklist + characteristics). |

```python
from prisma.flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts
from prisma.checklist import PRISMAChecklist, PRISMAExtensionsChecklist
from prisma.extensions import PRISMAExtension, PRISMAExtensionGenerator

counts = PRISMAStageCounts(
    records_identified_via_databases=1248,
    records_after_deduplication=1107,
    records_screened=1107,
    records_excluded_title_abstract=923,
    full_text_articles_assessed_for_eligibility=184,
    full_text_articles_excluded=67,
    studies_included_in_qualitative_synthesis=117,
    studies_included_in_quantitative_synthesis=84,
)
gen = PRISMAFlowGenerator(counts, title="Remdesivir review")
gen.render_svg("prisma.svg"); gen.render_pdf("prisma.pdf")
gen.render_png("prisma.png", dpi=200); gen.render_html("prisma.html")

cl = PRISMAChecklist()
print(cl.completion_rate(), len(cl.missing_items()))
cl.to_markdown(); cl.to_pdf("checklist.pdf"); cl.to_docx("checklist.docx")

ext = PRISMAExtensionsChecklist()
print(len(ext.ipd_checklist()), len(ext.nma_checklist()),
      len(ext.scr_checklist()), len(ext.harms_checklist()),
      len(ext.abstract_checklist()), len(ext.diagnostic_checklist()))

PRISMAExtensionGenerator.nma_flow(counts, title="NMA flow")
```

---

## q1_figures

| Symbol | Module | Description |
|---|---|---|
| `JournalPalettes` | `q1_figures.palettes` | 10 publication-grade palettes (Nature/Science/Cell/NEJM/Lancet/JAMA + scientific / colorblind-safe / diverging / sequential). `get(name)`, `as_cmap(name)`. |
| `Q1Typography` | `q1_figures.typography` | Journal-specific font families + matplotlib rcParams; `apply(ax, journal="nature")`, `configure_matplotlib(journal="nature")`, `journal_family`, `supported_journals`. |
| `Q1FigureFactory` | `q1_figures.figure_factory` | Single-call builder: `set_journal`, `set_size(columns, aspect)`, `set_dpi`, `new_figure`, `new_axes`, `new_figure_and_axes`, `style_axes`, `set_axis_labels`, `set_title`, `set_tick_labels_fontsize`, `add_legend`, `add_significance_bar`, `add_significance_line`, `add_error_bars`, `add_colorbar`, `annotate_panel`, `save`, `finalize`. |
| `GridLayout` | `q1_figures.multi_panel` | Grid layout helper. |
| `MultiPanelFigure` | `q1_figures.multi_panel` | Multi-panel composition with panel labels, shared axes, per-panel colorbars; `add_panel`, `add_panel_at`, `share_x`, `share_y`, `set_panel_label`, `set_panel_title`, `add_colorbar_to`, `adjust_spacing`, `finalize`, `save`. |
| `StatisticalPlots` | `q1_figures.statistical_plots` | 14 plots: `boxplot`, `violinplot`, `raincloud_plot`, `beeswarm`, `paired_plot`, `volcano_plot`, `manhattan_plot`, `qq_plot`, `kaplan_meier`, `roc_curve`, `pr_curve`, `calibration_plot`, `bland_altman`. |
| `Q1NetworkPlots` | `q1_figures.network_plots` | 8 plots: `network_figure`, `bipartite_figure`, `circular_network`, `arc_diagram`, `heatmap_graph`, `sankey_diagram`, `chord_diagram`, `hive_plot`. |
| `BibliometricPlots` | `q1_figures.bibliometric_plots` | 12 plots: `lotka_curve`, `bradford_curve`, `zipf_law_plot`, `growth_curve`, `citation_distribution`, `h_index_curve`, `impact_factor_distribution`, `author_collaboration_heatmap`, `citation_network_graph`, `topic_evolution_streamgraph`, `overlay_visualization`, `co_word_map`. |
| `Q1DataPlots` | `q1_figures.data_plots` | 11 plots: `scatter`, `line_plot`, `bar_plot`, `stacked_bar`, `grouped_bar`, `heatmap`, `clustered_heatmap`, `density_plot`, `contour_plot`, `ridgeline_plot`, `parallel_coordinates`, `polar_plot`. |

```python
from q1_figures.figure_factory import Q1FigureFactory
from q1_figures.statistical_plots import StatisticalPlots
from q1_figures.network_plots import Q1NetworkPlots
from q1_figures.bibliometric_plots import BibliometricPlots
from q1_figures.data_plots import Q1DataPlots
from q1_figures.multi_panel import MultiPanelFigure
from q1_figures.palettes import JournalPalettes

# Palette
print(JournalPalettes.get("nature"))
print(JournalPalettes.as_cmap("lancet"))

# Single-figure workflow
factory = Q1FigureFactory().set_journal("nature").set_size("single").set_dpi(300)
fig, ax = factory.new_figure_and_axes()
ax = StatisticalPlots.volcano_plot(
    ax=ax, log2fc=[...], neg_log10_p=[...], gene_names=[...])
factory.set_axis_labels(ax, xlabel="log2FC", ylabel="-log10(p)")
factory.set_title(ax, "Volcano")
factory.annotate_panel(ax, "a")
factory.style_axes(ax, grid=True)
factory.save("volcano.pdf")
factory.save("volcano.png")

# Multi-panel
mp = MultiPanelFigure(rows=2, cols=2, factory=factory)
ax1 = mp.add_panel(0, 0)
ax2 = mp.add_panel(0, 1)
ax3 = mp.add_panel(1, 0)
ax4 = mp.add_panel(1, 1)
mp.set_panel_label(0, "a"); mp.set_panel_label(1, "b")
mp.set_panel_label(2, "c"); mp.set_panel_label(3, "d")
mp.share_x([ax3, ax4]); mp.share_y([ax1, ax3])
mp.adjust_spacing(hspace=0.4, wspace=0.4)
mp.save("multi_panel.pdf", format="pdf", dpi=300)

# Bibliometric plot
fig, ax = factory.new_figure_and_axes()
ax = BibliometricPlots.lotka_curve([12, 8, 6, 5, 4, 3, 2, 1, 1, 1])
factory.save("lotka.pdf")

# Network plot
fig, ax = factory.new_figure_and_axes()
ax = Q1NetworkPlots.sankey_diagram(
    ax=ax, flows=[("A", "X", 10), ("A", "Y", 5), ("B", "X", 3)])
factory.save("sankey.pdf")
```

---

## research_lifecycle

| Symbol | Module | Description |
|---|---|---|
| `ResearchGap` | `research_lifecycle.ideation` | Detected research gap. |
| `ResearchIdea` | `research_lifecycle.ideation` | Generated research idea with composite score. |
| `ResearchGapDetector` | `research_lifecycle.ideation` | `from_corpus`, `from_literature_review`, `compare_frontiers`, `_enrich_with_llm`. |
| `IdeaGenerator` | `research_lifecycle.ideation` | `generate`, `refine`, `combine`, `score`. |
| `ProtocolSection` | `research_lifecycle.protocol_templates` | Single template section. |
| `ProtocolTemplate` | `research_lifecycle.protocol_templates` | Template containing sections. |
| `Protocol` | `research_lifecycle.protocol_templates` | Filled-in protocol. |
| `ProtocolTemplateLibrary` | `research_lifecycle.protocol_templates` | 9 templates: `systematic_review`, `scoping_review`, `meta_analysis_protocol`, `rapid_review`, `case_study_protocol`, `cohort_study_protocol`, `rct_protocol`, `qualitative_protocol`, `mixed_methods_protocol`. |
| `ProtocolBuilder` | `research_lifecycle.protocol_templates` | `from_template`, `fill_section`, `validate`, `to_markdown`, `to_pdf`, `to_docx`. |
| `ExtractionField` | `research_lifecycle.data_extraction` | Single field in an extraction template. |
| `ExtractionTemplate` | `research_lifecycle.data_extraction` | Template with fields. |
| `ExtractionTemplateLibrary` | `research_lifecycle.data_extraction` | 7 templates: `cochrane_rct`, `observational`, `qualitative`, `mixed_methods`, `bibliometric`, `content_analysis`, `survey_research`. |
| `ExtractionSession` | `research_lifecycle.data_extraction` | Per-study filled-in extraction. |
| `QualityResult` | `research_lifecycle.quality_assessment` | Quality-assessment result. |
| `QualityAssessmentTool` (ABC) | `research_lifecycle.quality_assessment` | Abstract base. |
| `MMAT` | `research_lifecycle.quality_assessment` | Mixed Methods Appraisal Tool. |
| `STROBEChecklist` | `research_lifecycle.quality_assessment` | STROBE observational-studies checklist. |
| `CONSORTChecklist` | `research_lifecycle.quality_assessment` | CONSORT RCT checklist. |
| `PRISMAComplianceChecklist` | `research_lifecycle.quality_assessment` | PRISMA compliance checklist. |
| `CAREChecklist`, `CAREPlusChecklist` | `research_lifecycle.quality_assessment` | CARE case-report checklists. |
| `SRQRChecklist` | `research_lifecycle.quality_assessment` | SRQR qualitative-research checklist. |
| `ENTREQChecklist` | `research_lifecycle.quality_assessment` | ENTREQ qualitative-synthesis checklist. |
| `CASPChecklist` | `research_lifecycle.quality_assessment` | CASP critical-appraisal checklist. |
| `NarrativeResult`, `NarrativeSynthesis` | `research_lifecycle.synthesis_methods` | Narrative synthesis. |
| `Theme`, `ThematicResult`, `ThematicSynthesis` | `research_lifecycle.synthesis_methods` | Thematic synthesis. |
| `QCAResult`, `QualitativeComparativeAnalysis` | `research_lifecycle.synthesis_methods` | QCA. |
| `MetaSynthesisResult`, `MetaSynthesis` | `research_lifecycle.synthesis_methods` | Meta-synthesis. |
| `BestFitFrameworkSynthesis` | `research_lifecycle.synthesis_methods` | Best-fit framework synthesis. |
| `ChecklistItem` | `research_lifecycle.reporting_checklists` | Single EQUATOR checklist item. |
| `EquatorChecklists` | `research_lifecycle.reporting_checklists` | 10 checklists: `consort`, `strobe`, `prisma`, `stard`, `tripod`, `spirit`, `squire`, `cheers`, `trend`, `coreq`. |
| `ReportingChecklist` | `research_lifecycle.reporting_checklists` | Wrapper: `available_checklists`, `equator_network_lookup`, `get`, `to_markdown`, `to_pdf`. |
| `WritingAssistant` | `research_lifecycle.writing_assistant` | `outline`, `draft_section`, `improve_prose`, `check_grammar`, `generate_abstract`, `generate_title`, `format_citation`, `format_bibliography`, `paraphrase`, `summarize_for_imrad`. |

```python
from research_lifecycle.ideation import ResearchGapDetector, IdeaGenerator
from research_lifecycle.protocol_templates import (
    ProtocolTemplateLibrary, ProtocolBuilder,
)
from research_lifecycle.data_extraction import (
    ExtractionTemplateLibrary, ExtractionSession,
)
from research_lifecycle.quality_assessment import MMAT, CASPChecklist
from research_lifecycle.synthesis_methods import (
    NarrativeSynthesis, QualitativeComparativeAnalysis, MetaSynthesis,
)
from research_lifecycle.reporting_checklists import EquatorChecklists, ReportingChecklist
from research_lifecycle.writing_assistant import WritingAssistant
from ai_assistant import LLMClient

llm = LLMClient(provider="ollama", model="llama3", base_url="http://localhost:11434")

# Ideation
detector = ResearchGapDetector(llm_client=llm)
gaps = detector.from_corpus(papers)
ideas = IdeaGenerator(llm_client=llm).generate(topic="...", gaps=gaps)

# Protocol
template = ProtocolTemplateLibrary.get("systematic_review")
protocol = ProtocolBuilder.from_template(template)
ProtocolBuilder.fill_section(protocol, "Background", "...")
ProtocolBuilder.to_pdf(protocol, "protocol.pdf")

# Extraction
extraction_template = ExtractionTemplateLibrary.get("cochrane_rct")
session = ExtractionSession(extraction_template)
session.set_field("study_id", "S1").set_field("year", 2023)
session.to_yaml("extraction.yaml")

# Quality
mmat = MMAT().assess(study_data={...})
casp = CASPChecklist(variant="rct").assess(study_data={...})

# Synthesis
narrative = NarrativeSynthesis().synthesize(extractions)
qca = QualitativeComparativeAnalysis().calibrate(...).run(...)

# Reporting checklist
items = ReportingChecklist.get("consort")
print(ReportingChecklist.to_markdown(items))

# Writing
writer = WritingAssistant(llm_client=llm)
outline = writer.outline(topic="...", papers=papers[:30])
abstract = writer.generate_abstract(topic="...", papers=papers[:20])
```

---

## innovation

| Symbol | Module | Description |
|---|---|---|
| `Burst` | `innovation.citation_bursts` | Detected burst dataclass. |
| `CitationBurstDetector` | `innovation.citation_bursts` | `detect_papers`, `detect_authors`, `detect_keywords`, `detect_journals`, `detect_topics`, `aggregate_bursts`, `to_dataframe`, `visualize`. |
| `FrontierRegion` | `innovation.frontier_mapping` | Detected frontier region. |
| `KnowledgeFrontier` | `innovation.frontier_mapping` | `compute_frontier`, `embedding_density_approach`, `topic_model_boundary_approach`, `citation_velocity_approach`, `visualize`. |
| `FrontierTracker` | `innovation.frontier_mapping` | `track_over_time`, `emerging_topics`, `fading_topics`. |
| `Forecast` | `innovation.trend_forecasting` | Forecast dataclass. |
| `TrendForecaster` | `innovation.trend_forecasting` | `forecast_topic`, `forecast_all_topics`, `emerging_keywords`, `fading_keywords`, `forecast_citation_growth`, `forecast_author_productivity`, `forecast_field`, `visualize`, `batch_forecast_visualization`. |
| `PaperRecommender` | `innovation.paper_recommendation` | `index_papers`, `recommend_for_query`, `recommend_similar`, `recommend_for_user`, `recommend_for_topic`, `recommend_bridge_papers`, `recommend_trending`, `diversify`, `explain`, `evaluate`. |
| `CollaborationRecommender` | `innovation.collaboration_recommendation` | `recommend_collaborators`, `recommend_institutions`, `bridge_authors`, `compute_strength`, `emerging_collaborations`, `visualize_collaboration_network`. |
| `NoveltyScore` | `innovation.novelty_scoring` | Novelty score dataclass. |
| `NoveltyScorer` | `innovation.novelty_scoring` | `score_paper`, `score_topic`, `disruption_index`, `atypicality_score`, `rank_novel_papers`, `rank_disruptive_papers`, `visualize_distribution`, `visualize_paper`. |
| `ResearchDirection` | `innovation.research_directions` | Recommended direction dataclass. |
| `ResearchDirectionRecommender` | `innovation.research_directions` | `recommend_directions`, `from_gaps`, `from_frontier`, `from_trends`, `combine_signals`, `score`, `visualize_roadmap`. |

```python
from innovation.citation_bursts import CitationBurstDetector
from innovation.frontier_mapping import KnowledgeFrontier, FrontierTracker
from innovation.trend_forecasting import TrendForecaster
from innovation.paper_recommendation import PaperRecommender
from innovation.collaboration_recommendation import CollaborationRecommender
from innovation.novelty_scoring import NoveltyScorer
from innovation.research_directions import ResearchDirectionRecommender

# Bursts
det = CitationBurstDetector(s=2.0, gamma=1.0)
bursts = det.detect_papers(papers)
det.visualize(bursts, path="bursts.png")

# Frontiers
kf = KnowledgeFrontier(papers, approach="embedding_density")
frontiers = kf.compute_frontier(top_k=10)
kf.visualize(frontiers, path="frontiers.png")
tracker = FrontierTracker(papers)
print(tracker.emerging_topics(threshold=0.5))

# Trend forecasting
forecaster = TrendForecaster(papers)
forecast = forecaster.forecast_topic("graph neural networks", horizon=3, method="arima")

# Recommendations
rec = PaperRecommender(papers)
rec.index_papers()
print(rec.recommend_for_query("transformers attention", top_k=10))

# Collaboration
cr = CollaborationRecommender(papers)
print(cr.recommend_collaborators(author="Alice", top_k=5))

# Novelty
ns = NoveltyScorer(papers)
print(ns.score_paper(papers[0]).to_dict())
print(ns.disruption_index(papers[0]))

# Research directions
dr = ResearchDirectionRecommender(papers, llm_client=llm)
directions = dr.recommend_directions(topic="...")
dr.visualize_roadmap(directions, path="roadmap.png")
```

---

## data_acquisition (v2 additions)

Nine new scrapers + three integration modules.

| Symbol | Module | Description |
|---|---|---|
| `SpringerScraper` | `data_acquisition.springer_scraper` | Springer Nature Meta API (journals + book chapters). |
| `IEEEXploreScraper` | `data_acquisition.ieee_scraper` | IEEE Xplore Metadata API. |
| `ACMDigitalLibraryScraper` | `data_acquisition.acm_scraper` | ACM Digital Library search. |
| `COREScraper` | `data_acquisition.core_scraper` | CORE open-access aggregator with full-text PDFs. |
| `BASEScraper` | `data_acquisition.base_scraper_ext` | Bielefeld Academic Search Engine. |
| `UnpaywallScraper` | `data_acquisition.unpaywall_scraper` | DOI → open-access URL resolver; tags OA colour. |
| `OpenAccessLocation` | `data_acquisition.unpaywall_scraper` | OA location dataclass. |
| `OpenCitationsScraper` | `data_acquisition.opencitations_scraper` | OpenCitations COCI citation index. |
| `Citation` | `data_acquisition.opencitations_scraper` | Citation dataclass. |
| `SciOpenScraper` | `data_acquisition.sciopen_scraper` | SciOpen publisher API. |
| `WikipediaArticle`, `WikipediaScraper` | `data_acquisition.wikipedia_scraper` | Wikipedia REST + MediaWiki search. |
| `CitationResolver` | `data_acquisition.integrations.citation_resolver` | Cross-API DOI / OpenAlex / Crossref / OpenCitations resolver. |
| `OpenAccessFinder` | `data_acquisition.integrations.oa_finder` | Best-URL open-access lookup. |
| `MetadataEnricher` | `data_acquisition.integrations.metadata_enricher` | Cross-source enrichment (author / abstract / references). |

```python
from data_acquisition.springer_scraper import SpringerScraper
from data_acquisition.ieee_scraper import IEEEXploreScraper
from data_acquisition.acm_scraper import ACMDigitalLibraryScraper
from data_acquisition.core_scraper import COREScraper
from data_acquisition.base_scraper_ext import BASEScraper
from data_acquisition.unpaywall_scraper import UnpaywallScraper
from data_acquisition.opencitations_scraper import OpenCitationsScraper
from data_acquisition.sciopen_scraper import SciOpenScraper
from data_acquisition.wikipedia_scraper import WikipediaScraper
from data_acquisition.integrations.citation_resolver import CitationResolver
from data_acquisition.integrations.oa_finder import OpenAccessFinder
from data_acquisition.integrations.metadata_enricher import MetadataEnricher

# Each scraper follows the same BaseScraper API:
result = SpringerScraper().search("graph neural networks", max_results=20)
print(len(result.papers))

# Integrations:
cr = CitationResolver()
record = cr.resolve(doi="10.1038/s41586-021-03819-2")

oa = OpenAccessFinder()
location = oa.find(doi="10.1038/s41586-021-03819-2")

me = MetadataEnricher()
enriched = me.enrich(papers)
```

### Environment variables

```bash
export SPRINGER_API_KEY=...        # https://dev.springernature.com/
export IEEE_API_KEY=...             # https://developer.ieee.org/
export CORE_API_KEY=...             # https://core.ac.uk/services/api
export UNPAYWALL_EMAIL=you@example.org
# OpenCitations / BASE / SciOpen / Wikipedia — no key needed.
```

---

## web/routes (v2 additions)

Seven new Flask blueprints with 65+ endpoints in total. The handler
functions live in `web/routes/` and follow Flask conventions.

| Blueprint | URL prefix | # endpoints | Description |
|---|---|---|---|
| `bibliometrics_bp` | `/api/bibliometrics` | 6 | indices, journal-metrics, vos, bursts, author-profile, journal-profile |
| `network_bp` | `/api/network` | 9 | centrality, community, components, paths, link-prediction, layouts, stats, filter, export |
| `sr_bp` | `/api/sr` | 11 | protocol (POST + GET + PUT), screening (import + decide + progress), rob (POST + GET), extraction, synthesis, prisma-flow, prisma-checklist |
| `ma_bp` | `/api/ma` | 8 | effect-size, pool, forest-plot, funnel-plot, subgroup, sensitivity, nma, report |
| `figures_bp` | `/api/figures` | 16 | forest, funnel, volcano, manhattan, qq, kaplan-meier, roc, pr-curve, boxplot, violin, raincloud, heatmap, network, sankey, multi-panel, palettes |
| `innovation_bp` | `/api/innovation` | 7 | bursts, frontiers, forecast, recommend-papers, recommend-collaborators, novelty, directions |
| `lifecycle_bp` | `/api/lifecycle` | 8 | gaps, ideas, protocol-templates, protocol, extraction-templates, quality-assessment, reporting-checklists, write |

See [`api_reference.md`](api_reference.md) for full request/response
schemas and examples for every endpoint.

---

*Last verified against code on 2026-08-25. If you spot a stale or
wrong signature, please open a PR against this file.*
