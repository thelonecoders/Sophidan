# Changelog

All notable changes to Academic Research Suite are documented in
this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

---

## [v2.0.0] — 2026-08-25 — Research-lifecycle OS release

The v2.0.0 release turns Academic Research Suite from a literature-
scraping workbench into a **full research-lifecycle OS** — every step
from ideation through publication is now covered. Ten new top-level
packages are layered on top of the v1.0.0 baseline; the v1 API and UI
remain 100% backwards-compatible.

### Added

#### New top-level packages (10)

- `bibliometrics/` — Publish-or-Perish-grade author-level indices
  (`PoPIndices` exposes h, g, i10, e-index, h_core, h_max_index,
  w_index, q2_index, contemporary h-index (hc), age-weighted citation
  rate (AWCR), AR index, multi-authored h-index (hm), individual
  h-index (hi)); JCR-style journal metrics (`JournalMetrics` — IF,
  5-year IF, immediacy index, Eigenfactor, Article Influence, SJR,
  SNIP, CiteScore, journal h/g/h5/h5-median, quartile);
  VOSviewer-style analyses (`VOSAnalyzer` — bibliographic coupling,
  co-citation, co-authorship, term co-occurrence, overlay
  visualization, cluster graph, force-atlas 2D mapping);
  CiteSpace-style analyses (`CiteSpaceAnalyzer` — Kleinberg citation
  bursts, knowledge-domain maps, timezone view, spectral clustering
  view, structural-variation analysis, landmark papers,
  intellectual turning points, research fronts); and the
  `ScientogramBuilder` for Sci2 / Leydesdorff-style scientograms.
- `networkx_pro/` — full NetworkX algorithm library exposed behind
  ten stateless classes: `Centralities` (20 measures),
  `CommunityDetection`, `ComponentAnalysis`, `PathsAndFlows`,
  `LinkPrediction`, `Isomorphism`, `BipartiteAnalysis`,
  `GraphGenerators`, `GraphIO`, `MultiGraphAnalysis` — together
  covering **60+ algorithms**.
- `gephi_viz/` — Gephi-style interactive visualization: 11 layout
  algorithms (`ForceAtlas2`, `OpenOrd`, `YifanHu`, Fruchterman-Reingold,
  Kamada-Kawai, circular, grid, radial, hierarchical, geographic, plus
  `LayoutPipeline`), 15 filters (degree / weight / edge-weight /
  property range, giant component, connected components, k-core,
  ego-network, shortest-path, mutual-edge, parallel-edge, partition,
  equal-property, edge-type, inter-edges, time-range, all combinable
  via `FilterChain`), Gephi-grade `NetworkStatsReport` / `NetworkStatistics`,
  `Partition`, `Ranking`, `PreviewRenderer` (matplotlib / pyvis /
  plotly / Cytoscape.js), and a Qt-embedded `InteractiveNetworkCanvas`.
- `systematic_review/` — full PRISMA 2020 systematic-review lifecycle:
  `SystematicReviewProtocol` (PICO + eligibility + versioning + PROSPERO
  registration), `ScreeningManager` (title/abstract + full-text
  screening with dual-reviewer support, Cohen's & Fleiss kappa,
  conflict resolution, auto-dedup), four RoB tools — `CochraneRoB2`,
  `ROBINS_I`, `QUADAS2`, `NewcastleOttawaScale` — with
  `RoBFigureGenerator` for traffic-light + summary-bar figures,
  `DataExtractionForm` + `DataExtractor`, `SynthesisFactory`
  (narrative / thematic / QCA / meta-analysis / NMA),
  `SWiMReportingChecklist`, and `PRISMAIntegration`.
- `meta_analysis/` — `EffectSizeCalculator` (Cohen's d / Hedges' g /
  Glass's Δ / mean diff / RR / OR / HR with RRR & NNT),
  `PoolingEngine` (fixed IV / DerSimonian-Laird / Mantel-Haenszel
  OR & RR / Peto / REML / ML / Paule-Mandel / empirical-Bayes;
  Heterogeneity Q / τ² / I²), `SubgroupAnalysis`,
  `SensitivityAnalysis` (leave-one-out, cumulative, Cook's distance,
  DFFITS, Galbraith & radial plots), `ForestPlot`, `FunnelPlot`
  (Egger / Begg / Peters / Harbord tests, trim-and-fill,
  Rosenthal fail-safe N), `ContourEnhancedFunnel`,
  `NetworkMetaAnalysis` (consistency + inconsistency + node-splitting
  + SUCRA + league table), `MetaAnalysisReport`.
- `prisma/` — dedicated PRISMA 2020 generator: `PRISMAFlowGenerator`
  (matplotlib / SVG / PDF / PNG / standalone HTML; BMJ + BMJ-style
  templates), `PRISMAChecklist` (27-item canonical checklist with
  markdown / YAML / PDF / DOCX export), `PRISMAExtensionsChecklist`
  (6 official extensions: IPD, NMA, ScR, Harms, Abstract, Diagnostic),
  `PRISMAExtensionGenerator`, `PRISMAExtractionForm`, `PRISMAReport`.
- `q1_figures/` — publication-grade Q1-journal figure factory:
  `JournalPalettes` (10 palettes: Nature, Science, Cell, NEJM,
  Lancet, JAMA, scientific, colorblind-safe, diverging-RG,
  sequential-viridis), `Q1Typography` (journal-specific font
  families + matplotlib rcParams), `Q1FigureFactory` (single-call
  builder with `set_journal` / `set_size` / `new_figure_and_axes` /
  `style_axes` / `add_legend` / `add_significance_bar` /
  `add_error_bars` / `add_colorbar` / `annotate_panel` / `save`),
  `MultiPanelFigure`, `StatisticalPlots` (14 plots), `Q1NetworkPlots`
  (8 plots), `BibliometricPlots` (12 plots), `Q1DataPlots` (11 plots).
- `research_lifecycle/` — `ResearchGapDetector` (gap detection from a
  corpus + LLM enrichment), `IdeaGenerator` (generate / refine /
  combine / score ideas), `ProtocolTemplateLibrary` (9 templates),
  `ProtocolBuilder`, `ExtractionTemplateLibrary` (7 templates),
  `ExtractionSession`, `QualityAssessmentTool` (8 tools: MMAT,
  STROBE, CONSORT, PRISMA-compliance, CARE, CARE-Plus, SRQR, ENTREQ,
  CASP), 5 synthesis methods (NarrativeSynthesis, ThematicSynthesis,
  QualitativeComparativeAnalysis, MetaSynthesis,
  BestFitFrameworkSynthesis), `EquatorChecklists` (10 EQUATOR
  checklists: CONSORT, STROBE, PRISMA, STARD, TRIPOD, SPIRIT, SQUIRE,
  CHEERS, TREND, COREQ), `WritingAssistant` (outline / draft /
  improve / grammar / abstract / title / citation formatting /
  paraphrase / IMRaD summary).
- `innovation/` — `CitationBurstDetector` (Kleinberg burst detection
  on papers / authors / keywords / journals / topics),
  `KnowledgeFrontier` (3 frontier-mapping approaches: embedding
  density, topic boundary, citation velocity), `FrontierTracker`
  (emerging / fading topics over time), `TrendForecaster`
  (ARIMA / Prophet / linear / exponential forecasting),
  `PaperRecommender` (semantic search + MMR diversification +
  bridge papers + trending + per-topic),
  `CollaborationRecommender` (complementary expertise + weak ties +
  institution recommendations), `NoveltyScorer` (Uzzi atypicality +
  Funk & Owen-Smith disruption index), `ResearchDirectionRecommender`
  (combine gaps + frontiers + trends into a roadmap).
- Extended `data_acquisition/` — 9 new academic scrapers
  (`SpringerScraper`, `IEEEXploreScraper`, `ACMDigitalLibraryScraper`,
  `COREScraper`, `BASEScraper`, `UnpaywallScraper`,
  `OpenCitationsScraper`, `SciOpenScraper`, `WikipediaScraper`) plus
  3 integration modules (`CitationResolver`, `OpenAccessFinder`,
  `MetadataEnricher`) in `data_acquisition/integrations/`.

#### New UI widgets (7)

- `ui/widgets/bibliometric_dashboard.py` — `BibliometricDashboard`.
- `ui/widgets/gephi_advanced_view.py` — `GephiAdvancedView`.
- `ui/widgets/systematic_review_view.py` — `SystematicReviewView`.
- `ui/widgets/meta_analysis_view.py` — `MetaAnalysisView`.
- `ui/widgets/prisma_builder.py` — `PRISMAFlowBuilder`.
- `ui/widgets/q1_figure_studio.py` — `Q1FigureStudio`.
- `ui/widgets/innovation_panel.py` — `InnovationPanel`.

The sidebar grew from 10 to **18 NavItems** to expose every new page.

#### New web blueprints (7)

- `web/routes/bibliometrics.py` — `/api/bibliometrics` (6 endpoints).
- `web/routes/network_analysis.py` — `/api/network` (9 endpoints).
- `web/routes/sr.py` — `/api/sr` (11 endpoints).
- `web/routes/ma.py` — `/api/ma` (8 endpoints).
- `web/routes/q1_figures.py` — `/api/figures` (16 endpoints).
- `web/routes/innovation.py` — `/api/innovation` (7 endpoints).
- `web/routes/research_lifecycle.py` — `/api/lifecycle` (8 endpoints).

Total: 8 (v1) + 7 (v2) = **15 blueprints**, exposing **65+ REST endpoints**.

#### New tests (92)

- `tests/test_v2.py` — 92 new tests covering every v2 module plus 6
  end-to-end integration tests (scrape → bibliometrics → network →
  gephi_viz → meta-analysis → forest plot → Q1 figure; PRISMA flow +
  checklist; SR protocol + RoB; screening + kappa).
- The full suite is now **209 tests** (117 v1 + 92 v2), all passing
  on a fresh checkout with no API keys set.

#### New figure / palette / checklist assets

- 10 publication-grade color palettes (Nature, Science, Cell, NEJM,
  Lancet, JAMA, scientific, colorblind-safe, diverging-RG,
  sequential-viridis).
- 14 statistical plots (box, violin, raincloud, beeswarm, paired,
  volcano, Manhattan, QQ, Kaplan-Meier, ROC, PR-curve, calibration,
  Bland-Altman).
- 8 network plots (network, bipartite, circular network, arc diagram,
  heatmap-graph, Sankey, chord, hive).
- 12 bibliometric plots (Lotka, Bradford, Zipf, growth curve, citation
  distribution, h-index curve, impact-factor distribution, author
  collaboration heatmap, citation network graph, topic-evolution
  streamgraph, overlay visualization, co-word map).
- 11 data plots (scatter, line, bar, stacked-bar, grouped-bar, heatmap,
  clustered heatmap, density, contour, ridgeline, parallel coordinates,
  polar).
- 4 systematic-review RoB tools (Cochrane RoB 2, ROBINS-I, QUADAS-2,
  Newcastle-Ottawa Scale).
- 6 PRISMA 2020 extensions (IPD, NMA, ScR, Harms, Abstract, Diagnostic).
- 60+ NetworkX algorithms exposed via the `networkx_pro` package.
- 11 Gephi-style layouts (ForceAtlas2, OpenOrd, YifanHu,
  Fruchterman-Reingold, Kamada-Kawai, circular, grid, radial,
  hierarchical, geographic, plus a `LayoutPipeline`).
- 15 Gephi-style graph filters (combinable via `FilterChain`).

#### New documentation (7 files)

- `docs/v2_user_guide.md` — v2 workflow walkthroughs (2,500+ words).
- `docs/COMPARISON.md` — feature-by-feature comparison with PoP, Gephi,
  VOSviewer, CiteSpace, Sci2, Zotero, Mendeley, Connected Papers,
  Inciteful, Rayyan, Covidence, RevMan, Metafor (2,000+ words).
- `docs/MODULE_REFERENCE.md` — public-symbol reference card covering
  all ~200 v2 symbols (3,000+ words).
- `docs/PRISMA_GUIDE.md` — PRISMA 2020 compliance guide (1,500+ words).
- `docs/META_ANALYSIS_GUIDE.md` — meta-analysis guide (2,000+ words).
- `docs/Q1_FIGURES_GUIDE.md` — publication-grade figure guide (2,000+
  words).
- `docs/INNOVATION_GUIDE.md` — innovation & frontiers guide (1,800+
  words).

### Changed

- `README.md` expanded from 4,414 → 10,600+ words; badges updated
  from `v1.0.0` to `v2.0.0`; tagline updated to mention
  "Publish-or-Perish-grade bibliometrics + Gephi-grade network
  visualization + systematic-review & meta-analysis workflows".
- `ui/widgets/sidebar.py` `default_nav_items()` expanded from 10 → 18
  entries (added Bibliometrics, Advanced Networks, Systematic Review,
  Meta-Analysis, PRISMA Builder, Q1 Figures, Innovation, plus Settings
  + Help).
- `web/routes/__init__.py` `ALL_BLUEPRINTS` expanded from 8 → 15
  entries (added `bibliometrics_bp`, `network_bp`, `sr_bp`, `ma_bp`,
  `figures_bp`, `innovation_bp`, `lifecycle_bp`).
- `web/server.py` registers all 15 blueprints via the same
  `_safe_import` pattern.
- `tests/test_v2.py` added (92 tests); total test count grew from
  117 → 209.
- `requirements.txt` grew with optional v2 dependencies
  (`prophet`, `faiss-cpu`, `pyvis`).
- `docs/INSTALL.md` gained a "v2.0.0 Optional Dependencies" section.
- `docs/FAQ.md` gained 15 new Q&A covering every v2 capability.
- `docs/architecture.md` gained a "v2.0.0 Architecture Addendum"
  section with an updated Mermaid dependency graph and four new
  "Extension points" subsections.
- `docs/api_reference.md` gained sections for each of the 7 new
  endpoint groups.
- `docs/user_guide.md` gained 7 new sections (Bibliometric Dashboard,
  PRISMA Flow Builder, Meta-Analysis, Systematic Review, Q1 Figures,
  Innovation, Advanced Network Analysis).

### Fixed

- `Q1FigureFactory.new_figure_and_axes` now returns `(fig, ax)` even
  when `figsize` is `None` (previously raised on the `None` default).
- `Q1FigureFactory.save` now auto-detects format from the path
  extension when `format` is not explicitly provided (previously
  defaulted silently to PNG).
- `web/routes/innovation.py` paper-recommendation handler now coerces
  incoming paper payloads via the same `_coerce_papers` helper used by
  the bibliometrics blueprint (previously failed when given a dict
  list rather than `Paper` objects).

### Removed

- None. v1.0.0 API and UI are 100% backwards-compatible.

---

## [v1.0.0] — 2026-08-25 — Initial Release

The first public release of Academic Research Suite. A pure-Python,
PyQt5-based desktop workbench for academic literature research,
scraping, analysis, knowledge-graph construction, AI assistance, and
reporting. Real scrapers only, no mock data, MIT-licensed, with an
optional local Flask web server.

### Added

#### Core Infrastructure (1-core)

- `config/settings.py` — `Settings` dataclass with 17 typed fields,
  layered loader (defaults → `default_config.yaml` → `secrets.yaml`
  → `ARS_`-prefixed env vars) and `get_settings()` singleton.
- `core/events.py` — `EventType` enum (9 canonical types), `Event`
  dataclass, thread-safe `EventBus` with wildcard subscriptions,
  `SignalBridge(QObject)` for Qt integration.
- `core/task_queue.py` — `Task`/`TaskStatus` dataclasses plus
  `TaskQueue` wrapping `ThreadPoolExecutor` with `enqueue`,
  `wait_all`, `cancel`, `list_by_status`, `results`.
- `core/orchestrator.py` — `SignalHub` (composition around an
  internal `QObject`) emitting 5 Qt signals; `Orchestrator` with
  `register_module`, `submit_task(stage=...)`, `get_status`,
  `cancel`, `wait_all`, `shutdown`; `get_orchestrator()` singleton.
- `utils/logger.py` — `get_logger(name)` with rotating `FileHandler`
  (`logs/ars.log`, 2 MB × 5 backups) + console `StreamHandler`; exact
  format `%(asctime)s [%(levelname)s] %(name)s: %(message)s`;
  `QtLogHandler` re-emits records as Qt signals; `LogViewer` Qt widget
  with 10 000-line ring buffer.
- `utils/workers.py` — `WorkerSignals`, `Worker(QRunnable)`,
  `WorkerPool` (composition around `QThreadPool.globalInstance()`),
  `run_in_background()` convenience helper.
- `utils/cache.py` — SQLite-backed `Cache` (`data/cache/cache.db`,
  WAL mode, `RLock`-guarded) + `TTLCache` with automatic expiry.
- `utils/config_manager.py` — `ConfigManager(QObject)` wrapping the
  `Settings` singleton with `config_changed(key, value)` signal,
  `to_dict()` / `from_dict()` / `save()`.
- `utils/exceptions.py` — `ARSError` base + 9 subclasses.
- `pyproject.toml` — PEP 621 metadata, MIT license, two entry points
  (`ars`, `ars-web`), dev extras (pytest, black, ruff, mypy).

#### Proxy Suite (1-proxy)

- `proxy/proxy_manager.py` — `Proxy` dataclass + `ProxyManager(QObject)`
  with 4 Qt signals, SQLite persistence (own `proxy_pool_cache` table).
- `proxy/proxy_scraper.py` — `ProxyScraper` covering 9 free-proxy
  sources with 4 parser types; `tenacity` retries with manual
  fallback; parallel + async scrape modes; dedup by
  `protocol://host:port`.
- `proxy/proxy_health_check.py` — `ProxyCheckResult` dataclass +
  `ProxyHealthChecker` (single / batch / continuous / geoip-cached).
- `proxy/proxy_chain.py` — `ProxyChain` + `ProxyChainError`;
  multi-hop SOCKS4/SOCKS5/HTTP-CONNECT tunneling with hand-rolled
  protocol handshakes; TLS wrap for HTTPS targets; returns
  `requests.Response`.
- `proxy/proxy_rotation.py` — `RotationStrategy` enum (5 strategies) +
  `ProxyRotator` with banlist / cooldown / `on_rotate` callback.
- `proxy/proxy_pool.py` — `ProxyPool` facade: `refresh_pool`,
  `get_workable`, `get_proxy(strategy=)`, background refresh,
  export/import (txt/json/csv), `stats`.

#### Data Acquisition (1-scraper-a, 1-scraper-b)

- `data_acquisition/base_scraper.py` — `Paper` dataclass,
  `ScraperResult` dataclass, `BaseScraper(ABC)` with HTTP retries
  (`tenacity` + manual fallback), token-bucket rate limiter,
  transparent response caching, proxy rotation, pagination helper,
  EventBus progress signalling.
- `data_acquisition/arxiv_scraper.py` — arXiv Atom-XML search,
  single-paper fetch, category taxonomy, optional PDF download.
- `data_acquisition/pubmed_scraper.py` — NCBI E-utilities
  (ESearch/EFetch) with MeSH-term support.
- `data_acquisition/openalex_scraper.py` — REST search across works,
  authors, institutions; citation lookup.
- `data_acquisition/semantic_scholar_scraper.py` — Search + paper
  details + bulk embeddings endpoint.
- `data_acquisition/crossref_scraper.py` — Polite-pool metadata
  search, DOI lookup, reference-list expansion.
- `data_acquisition/dblp_scraper.py` — Computer-science bibliography
  search and author disambiguation.
- `data_acquisition/google_scholar_scraper.py` — Headless-Chrome
  (Selenium) scraper with captcha-aware backoff.
- `data_acquisition/orcid_scraper.py` — Author lookup by ORCID iD,
  publication harvest, affiliation graph.
- `data_acquisition/doi_lookup.py` — Cross-API DOI resolver with
  cached redirects.
- `data_acquisition/scraping_engine.py` — Multi-source
  `ScrapingEngine` with `search_all`, `search_advanced`
  (filter translation), `export_results`, `search_all_async`.
  Four Qt signals (`scrape_started`, `progress`,
  `scrape_completed`, `scrape_error`) bridged to the EventBus.

#### Data Science (1-datasci)

- `data_science/analysis_engine.py` — `AnalysisEngine` with load /
  save / summary / clean + EventBus integration.
- `data_science/topic_modeler.py` — `TopicModeler` + `TopicModel`
  dataclass (LDA / NMF / BERTopic; fit / transform / visualize /
  save / load; `top_papers_per_topic`).
- `data_science/embeddings.py` — `EmbeddingsModel`
  (sentence-transformers wrapper with deterministic SHA-256-hash
  fallback into 384-D vectors).
- `data_science/clustering.py` — `Clusterer` + `ClusterResult`
  (KMeans / DBSCAN / HDBSCAN / Agglomerative; `optimal_k` via
  silhouette + elbow; `visualize`).
- `data_science/temporal_analysis.py` — `TemporalAnalyzer`
  (publication / citation time series; topic_evolution;
  trending_topics; emerging_authors; ARIMA forecast with linear
  fallback).
- `data_science/statistics.py` — `Bibliometrics` (h-index, i10-index,
  g-index, author metrics, journal metrics, collaboration_index,
  co-citation / co-authorship matrices).
- `data_science/visualizations.py` — `Visualizer` with 8
  figure-returning methods + CJK font fallback + `constrained_layout`
  throughout.

#### Knowledge Graph (1-graph)

- `knowledge_graph/network_analyzer.py` — Unified `NetworkAnalyzer`
  with generic centrality / community / topology metrics.
- `knowledge_graph/citation_graph.py` — `CitationGraph` with
  PageRank, HITS authority/hub scores, h-index per node.
- `knowledge_graph/collaboration_graph.py` — `CollaborationGraph`
  co-authorship projection from a bipartite author–paper set.
- `knowledge_graph/temporal_network.py` — `TemporalNetwork` with
  year-tagged edges, snapshot / evolution / growth-curve utilities,
  GIF animation via `imageio`.
- `knowledge_graph/graph_algorithms.py` — `GraphAlgorithms`
  pure-function library (k-core, modularity via Louvain/Leiden,
  link prediction, betweenness).

#### AI Assistant (1-ai)

- `ai_assistant/llm_client.py` — `LLMProvider` enum
  (OLLAMA, OPENAI, ANTHROPIC, NONE); `_EchoBackend` for
  deterministic offline mode; `LLMClient` with provider-agnostic
  `chat()` / `complete()` / `embed()` / `list_models()`.
- `ai_assistant/prompts.py` — `PromptTemplates` with 10 named
  `string.Template` attributes (summarize, extract_keywords,
  extract_entities, generate_literature_review, critique_paper,
  chat_system, research_questions, bibliographic_augment,
  identify_research_gaps).
- `ai_assistant/rag_engine.py` — `RAGEngine` + `RAGResponse` over
  the ChromaDB-backed `VectorStore` with NumPy fallback.
- `ai_assistant/summarizer.py` — `PaperSummarizer` producing
  structured `PaperSummary`, `TopicSummary`, `ComparisonTable`.
- `ai_assistant/chat_engine.py` — `ChatEngine` with streaming,
  tool-calling hooks, JSON conversation-history persistence.

#### Reporting (1-reporting)

- `reporting/pdf_report.py` — ReportLab-based structured PDF report
  (cover, abstract, methods, results, tables, charts, bibliography).
- `reporting/docx_report.py` — python-docx DOCX report with TOC
  field XML and live chart embedding.
- `reporting/pptx_report.py` — python-pptx PPTX deck with styled
  cover and per-section slides.
- `reporting/bibtex_export.py` — UTF-8 → LaTeX-safe BibTeX writer
  with `@article` / `@inproceedings` / `@book` typing and DOI dedup.
- `reporting/csv_export.py` — CSV / TSV / XLSX exporter with
  column picker.
- `reporting/chart_generator.py` — `ChartGenerator` with 8 styled
  figure-returning factories and CJK font fallback.
- `reporting/_paper_utils.py` — duck-typed Paper accessors shared
  across the package.

#### Database (1-db)

- `database/models.py` — SQLAlchemy 2.x ORM with 14 tables
  (papers, authors, keywords, fields_of_study, references,
  projects, snapshots, proxies, query_history, embeddings +
  4 association tables).
- `database/connection.py` — `DatabaseConnection` singleton with
  WAL journaling, foreign-key enforcement, `init_db`, `backup`
  (via `VACUUM INTO`), `restore`, `vacuum`, `stats`, `dispose`.
- `database/search.py` — `FullTextSearch` over SQLite FTS5 with
  BM25 ranking, snippet highlighting, and `LIKE`-based fallback.
- `database/vector_store.py` — `VectorStore` with ChromaDB
  preferred backend at `data/chroma/` and NumPy in-memory fallback
  — same API for both.

#### Project Management (1-db)

- `project_management/project_manager.py` — `Project` dataclass +
  `ProjectManager` with CRUD, snapshot delegation, and
  `compare_projects(a_id, b_id)`.
- `project_management/workspace.py` — multi-project `Workspace`.
- `project_management/snapshots.py` — `SnapshotManager` with restore.
- `project_management/comparison.py` — `ProjectComparison`
  returning shared / unique paper sets and bibliometric deltas
  (with `matplotlib-venn` if available).

#### UI Core (1-ui-core)

- `ui/main_window.py` — `MainWindow(QMainWindow)` shell with
  sidebar + `QStackedWidget` of lazily-loaded pages,
  `_PAGE_REGISTRY` dict mapping page keys to module+class tuples,
  top toolbar (global search + AI provider + theme toggle),
  status bar (queue size, active tasks, DB size, log button),
  menu bar (File/Edit/View/Tools/Help), keyboard shortcuts.
- `ui/welcome_screen.py` — first-launch wizard with three choices.
- `ui/modern_theme.py` — `ModernTheme.apply(app, theme=)` with
  two QSS themes (dark/light), accent colors, optional icon-font
  integration.
- `ui/widgets/sidebar.py` — `Sidebar` nav rail + `NavItem`.

#### UI Panels & Dialogs (1-ui-panels)

- `ui/widgets/dashboard.py` — `DashboardWidget`.
- `ui/widgets/search_panel.py` — `SearchPanel` + `ResultCard`
  (debounced autocomplete, multi-source checkboxes, filter row,
  result cards with Add-to-Project).
- `ui/widgets/data_view.py` — `DataViewWidget` (read-only paper
  browser).
- `ui/widgets/network_view.py` — `NetworkViewWidget` (matplotlib
  canvas with hover / click / drill-in, layouts, metrics).
- `ui/widgets/analysis_view.py` — `AnalysisViewWidget` (5 analysis
  types, results splitter).
- `ui/widgets/ai_chat.py` — `AIChatWidget` + `ChatBubble` +
  `ChatSettingsDialog` (provider/model selectors, RAG toggle,
  streaming display, history persistence).
- `ui/widgets/proxy_panel.py` — `ProxyPanel` + `StatCard` (4 stat
  cards, sortable table, drag-and-drop chain builder, event log).
- `ui/widgets/project_explorer.py` — `ProjectExplorer` (three-pane
  layout, snapshots timeline).
- `ui/widgets/settings_panel.py` — `SettingsPanel` (7-tab
  `QTabWidget`).
- `ui/dialogs/advanced_search.py` — `AdvancedSearchDialog` +
  `QueryRowWidget`.
- `ui/dialogs/author_dashboard.py` — `AuthorDashboard` +
  `calculate_h_index`.
- `ui/dialogs/reporting_dashboard.py` — `ReportingDashboard`
  (4-step wizard).
- `ui/dialogs/export_wizard.py` — `ExportWizard` (4-step wizard).
- `ui/dialogs/help_dialog.py` — `HelpDialog` (5-tab Help + FAQ +
  About + MIT License) + `FaqItem`.

#### Web Server (1-web)

- `web/server.py` — `create_app(config_overrides=None)` Flask app
  factory + `ServerState` singleton (lazy `db`,
  `project_manager`, `scraping_engine`, `proxy_pool`,
  `chat_engine`, `event_bus` accessors) + `run_server(host, port,
  debug)` entry point. Socket.IO is optional.
- `web/routes/__init__.py` — `_safe_import` with graceful
  degradation, `ALL_BLUEPRINTS` list of 8 entries.
- `web/routes/papers.py` — `/api/papers` CRUD + FTS + similar.
- `web/routes/projects.py` — `/api/projects` CRUD + papers +
  snapshots + comparison.
- `web/routes/scraping.py` — `/api/scraping` async tasks.
- `web/routes/analytics.py` — `/api/analytics` wraps `data_science`
  + `knowledge_graph`.
- `web/routes/ai.py` — `/api/ai` SSE chat, summarization, model
  listing, embeddings.
- `web/routes/proxy.py` — `/api/proxy` list / refresh / test /
  chain / stats.
- `web/routes/export.py` — `/api/export` papers / report / bibtex.
- `web/routes/websocket.py` — `/ws` status + Socket.IO handler
  registration + EventBus → Socket.IO bridge.
- `web/templates/index.html` — browser dashboard.
- `web/templates/api_docs.html` — live API docs.

#### Testing & Validation (2-validate)

- `tests/test_smoke.py` — 117-test pytest suite covering module
  imports (80-module sweep), DB init (14-table schema), MainWindow
  offscreen launch, web server endpoint health, `__init__.py` audit
  (16 package directories), end-to-end project→paper→FTS→CSV
  mini-flow, cross-module integration tests
  (ScrapingEngine + ProxyManager, ChatEngine + LLMClient(echo),
  ChartGenerator + Paper dataclass, CitationGraph + Paper
  dataclass), `web/routes/__init__.py` blueprint exposure.
- `scripts/smoke_test.sh` — bash smoke runner (imports + pytest +
  web endpoint pings + Qt offscreen launch) with `--quick` flag.

#### Documentation (3-docs)

- `README.md` — public-facing README (1500+ words, badges, ToC,
  features, quick start, usage examples, configuration reference,
  API key setup, architecture overview, project structure,
  keyboard shortcuts, web API reference, testing, contributing,
  roadmap, license, acknowledgments, citation).
- `docs/architecture.md` — system architecture (1200+ words,
  Mermaid diagrams, component descriptions, data flow, threading
  model, persistence, configuration, extension points, design
  decisions).
- `docs/user_guide.md` — end-user guide (2000+ words, walkthrough
  of every UI page, workflows, troubleshooting).
- `docs/development.md` — developer guide (1500+ words, code style,
  project layout, extension tutorials, testing, building, releasing,
  debugging, contributing workflow).
- `docs/api_reference.md` — REST API reference (1500+ words, every
  endpoint, schemas, examples, error reference, end-to-end flow).
- `docs/CHANGELOG.md` — this file.
- `docs/CODE_OF_CONDUCT.md` — Contributor Covenant 2.1.
- `docs/SECURITY.md` — security policy.
- `docs/INSTALL.md` — per-OS install guide.
- `docs/FAQ.md` — 20+ Q&A.
- `docs/INNOVATION.md` — novel features showcase.
- `CONTRIBUTING.md` — contribution guidelines.

### Changed

- N/A — initial release.

### Fixed

#### Integration Bugs (2-validate)

- `web/server.py::ServerState.scraping_engine` was passing a
  nonexistent `proxy_pool=` kwarg to `ScrapingEngine`. Fixed by
  adding `proxy_manager` to `ScrapingEngine.__init__` and unwrapping
  `ProxyPool.manager` in the lazy property.
- `web/server.py::ServerState.chat_engine` was constructing
  `ChatEngine()` without the required `llm_client` argument. Fixed
  by constructing an offline `LLMClient(provider="none",
  model="echo")` first.
- `web/server.py::ServerState.db` did not call `init_db()` on first
  access, so the `/api/projects/` endpoint returned 500 with
  `no such table: projects` on a fresh DB. Fixed by calling
  `init_db()` on first lazy access (idempotent).
- `web/routes/projects.py::create_project` was passing a dict
  positionally to `ProjectManager.create_project`, which expected
  `(name, description, color, settings)` keyword args. Fixed.
- `web/routes/projects.py::list_projects` called
  `pm.list_projects(query=q)` but `ProjectManager.list_projects`
  took no args. Added an optional `query` kwarg with substring
  filtering.
- `web/routes/projects.py` referenced `pm.update_project`,
  `pm.add_papers_to_project`, `pm.remove_paper_from_project`,
  `pm.list_snapshots`, `pm.create_snapshot`,
  `pm.compare_projects` — none existed on `ProjectManager`. Added
  all six as convenience methods (delegates for snapshots /
  comparison; full implementations for the rest).
- `ProjectManager.delete_project` returned `None` instead of a
  truthy/falsy value the REST DELETE handler expected. Now returns
  `bool`.
- `requirements.txt` had 4 duplicate package lines
  (`matplotlib>=3.8` x3, `pandas>=2.2` x2, `networkx>=3.2` x2,
  `plotly>=5.19` x2). Deduped; added new `# === TESTING ===` header
  with `pytest>=7.4`.

### Removed

- N/A — initial release.

### Deprecated

- N/A — initial release.

---

## Planned Versions

### [v1.1.0] — planned (Q4 2026)

- Pluggable authentication for the web server (API tokens +
  optional OIDC).
- Postgres-backed deployment guide with Docker Compose.
- Real-time collaborative editing of project notes.
- Bulk PDF full-text ingestion with Tesseract OCR.
- Snapshots diff view in the UI.
- PyInstaller `main.spec` for one-click desktop binary builds.

### [v1.2.0] — planned (Q1 2027)

- Bidirectional Zotero / Mendeley / EndNote sync.
- Custom report templates with Jinja2.
- Plugin system: drop-in scrapers and analyses via entry-points.
- Bilingual UI (English / 简体中文).
- Public plugin registry at <https://plugins.academic-research-suite.org>.

### [v2.0.0] — planned (Q2 2027)

- Multi-user server mode with PostgreSQL + Redis.
- PySide6 / Qt 6 migration behind the qtpy shim.
- Cloud LLM routing layer (multi-provider, automatic fail-over,
  cost tracking, budget alerts).
- Distributed scrape orchestration via Celery.
- Public REST API stabilization with versioning.
- WebSocket → SSE migration for simpler client library support.

---

*[Unreleased]:* v1.0.0 is shipped as a GitHub source release.
PyPI publication is deferred to v1.1.0.

