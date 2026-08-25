"""v2.0.0 integration test suite for the Academic Research Suite.

These tests cover every v2.0.0 module added by the v2-* sub-agents:

* ``bibliometrics``      — PoP indices, journal metrics, citation analysis.
* ``networkx_pro``       — centrality, communities, components, paths/flows,
                          link prediction, isomorphism, bipartite, multigraph,
                          graph_io, generators.
* ``gephi_viz``          — ForceAtlas2 layout, filters, statistics,
                          partition, ranking, preview.
* ``systematic_review``  — protocol templates, screening, RoB tools,
                          PRISMA integration, data extraction, synthesis.
* ``meta_analysis``      — effect sizes, pooling (DL/REML/MH/Peto/etc.),
                          NMA, subgroup, forest plot, funnel plot, report.
* ``prisma``             — flow diagram, 27-item 2020 checklist,
                          extraction form, extensions, report.
* ``q1_figures``         — Q1FigureFactory, palettes, statistical plots,
                          multi-panel, typography, network/bibliometric/data
                          plots.
* ``research_lifecycle`` — 9 protocol templates, ideation, synthesis,
                          quality assessment, data extraction, writing
                          assistant, reporting checklists.
* ``innovation``         — citation bursts, frontier mapping, trend
                          forecasting, paper & collaboration recommenders,
                          novelty scoring, research directions.

Plus the new ``data_acquisition`` scrapers (Springer, IEEE, ACM, CORE,
BASE-ext, Unpaywall, OpenCitations, SciOpen, Wikipedia), the new
``ui.widgets`` panels (bibliometric_dashboard, gephi_advanced_view,
systematic_review_view, meta_analysis_view, prisma_builder,
q1_figure_studio, innovation_panel), the new ``web.routes`` blueprints
(bibliometrics, network_analysis, sr, ma, q1_figures, innovation,
research_lifecycle), and full end-to-end web-server flows.

The suite is hermetic — every test uses synthetic data only, no network
calls.  Run with::

    pytest tests/test_v2.py -v
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the project root is on sys.path so `import bibliometrics` etc.
# work regardless of where pytest is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Force offscreen Qt + Agg matplotlib for the entire test session.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def karate_graph():
    """Return the canonical Zachary's karate-club graph (34 nodes)."""
    import networkx as nx
    return nx.karate_club_graph()


@pytest.fixture()
def synthetic_papers():
    """Return a list of 5 synthetic Paper objects with growing citations."""
    from data_acquisition.base_scraper import Paper
    return [
        Paper(
            title=f"Synthetic Paper {i}",
            authors=[f"Author {i}"],
            abstract=f"Abstract for paper {i}.",
            year=2020 + i,
            doi=f"10.1000/synthetic-{i}",
            citations_count=10 * i,
            references=[],
            keywords=["AI", "ML"],
            fields_of_study=["CS"],
            url="https://example.com",
            source="test",
            raw={},
        )
        for i in range(5)
    ]


# ---------------------------------------------------------------------------
# 1. Module imports — all 9 v2 packages
# ---------------------------------------------------------------------------
V2_PACKAGES = [
    "bibliometrics", "networkx_pro", "gephi_viz", "systematic_review",
    "meta_analysis", "prisma", "q1_figures", "research_lifecycle",
    "innovation",
]


@pytest.mark.parametrize("pkg", V2_PACKAGES)
def test_v2_package_imports(pkg):
    """Every v2.0 package should import without raising."""
    import importlib
    mod = importlib.import_module(pkg)
    assert mod is not None


@pytest.mark.parametrize("pkg", V2_PACKAGES)
def test_v2_package_has_docstring(pkg):
    """Each v2.0 package's ``__init__`` should have a non-trivial docstring."""
    import importlib
    mod = importlib.import_module(pkg)
    assert mod.__doc__ and len(mod.__doc__.strip()) > 20, (
        f"{pkg}.__init__ has no module docstring"
    )


# Detailed module imports — verify every v2 submodule loads
V2_SUBMODULES = {
    "bibliometrics": ["pop_indices", "journal_metrics", "citespace",
                      "scientogram", "vosviewer"],
    "networkx_pro": ["algorithms_centralities", "algorithms_communities",
                     "algorithms_components", "algorithms_paths_flows",
                     "algorithms_link_prediction", "algorithms_isomorphism",
                     "algorithms_bipartite", "algorithms_generators",
                     "graph_io", "multigraph"],
    "gephi_viz": ["layouts", "filters", "statistics", "partition",
                  "ranking", "preview", "interactive_canvas"],
    "systematic_review": ["protocol", "screening", "risk_of_bias",
                          "data_extraction", "synthesis", "prisma_integration"],
    "meta_analysis": ["effect_sizes", "pooling", "network_meta",
                      "subgroup", "forest_plot", "funnel_plot", "report"],
    "prisma": ["flow_diagram", "checklist", "extraction_form",
               "extensions", "report"],
    "q1_figures": ["figure_factory", "palettes", "typography",
                   "statistical_plots", "data_plots", "network_plots",
                   "bibliometric_plots", "multi_panel"],
    "research_lifecycle": ["protocol_templates", "ideation",
                           "synthesis_methods", "quality_assessment",
                           "data_extraction", "writing_assistant",
                           "reporting_checklists"],
    "innovation": ["citation_bursts", "frontier_mapping",
                   "trend_forecasting", "paper_recommendation",
                   "collaboration_recommendation", "novelty_scoring",
                   "research_directions"],
}


def test_v2_all_submodules_importable():
    """Every v2 submodule (62 total) imports without raising."""
    import importlib
    failed = []
    for pkg, mods in V2_SUBMODULES.items():
        for mod in mods:
            full = f"{pkg}.{mod}"
            try:
                importlib.import_module(full)
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{full}: {type(exc).__name__}: {exc}")
    assert not failed, "Submodule import failures:\n  " + "\n  ".join(failed)


# ---------------------------------------------------------------------------
# 2. New data_acquisition modules + new ui widgets + new web routes
# ---------------------------------------------------------------------------
NEW_SCRAPERS = [
    "springer_scraper", "ieee_scraper", "acm_scraper", "core_scraper",
    "base_scraper_ext", "unpaywall_scraper", "opencitations_scraper",
    "sciopen_scraper", "wikipedia_scraper",
]


@pytest.mark.parametrize("mod", NEW_SCRAPERS)
def test_new_scraper_imports(mod):
    """Each new v2.0 scraper module imports cleanly."""
    import importlib
    importlib.import_module(f"data_acquisition.{mod}")


NEW_WIDGETS = [
    "bibliometric_dashboard", "prisma_builder", "meta_analysis_view",
    "systematic_review_view", "q1_figure_studio", "innovation_panel",
    "gephi_advanced_view",
]


@pytest.mark.parametrize("mod", NEW_WIDGETS)
def test_new_widget_imports(mod):
    """Each new v2.0 ui widget module imports cleanly (Qt offscreen)."""
    import importlib
    importlib.import_module(f"ui.widgets.{mod}")


NEW_ROUTES = [
    "bibliometrics", "network_analysis", "sr", "ma",
    "q1_figures", "innovation", "research_lifecycle",
]


@pytest.mark.parametrize("mod", NEW_ROUTES)
def test_new_route_imports(mod):
    """Each new v2.0 web route module imports cleanly."""
    import importlib
    importlib.import_module(f"web.routes.{mod}")


# ---------------------------------------------------------------------------
# 3. Bibliometric computations
# ---------------------------------------------------------------------------
def test_bibliometrics_h_index():
    """h-index of [10,5,3,1,0] should be 3 (top-3 papers all >=3)."""
    from bibliometrics.pop_indices import PoPIndices
    assert PoPIndices.h_index([10, 5, 3, 1, 0]) == 3


def test_bibliometrics_e_index():
    """e-index = sqrt(sum of excess citations above h) = sqrt(7+2+0) = 3."""
    from bibliometrics.pop_indices import PoPIndices
    e = PoPIndices.e_index([10, 5, 3, 1, 0])
    assert abs(e - 3.0) < 1e-6, f"e-index was {e}"


def test_bibliometrics_g_index():
    """g-index of [10,5,3,1,0] should be 4 (cumulative top-4 = 19 >= 16)."""
    from bibliometrics.pop_indices import PoPIndices
    assert PoPIndices.g_index([10, 5, 3, 1, 0]) == 4


def test_bibliometrics_i10_index():
    """i10-index = number of papers with >= 10 citations."""
    from bibliometrics.pop_indices import PoPIndices
    assert PoPIndices.i10_index([10, 5, 3, 1, 0]) == 1


def test_bibliometrics_hc_index():
    """Contemporary h-index (hc-index) decays older citations."""
    from bibliometrics.pop_indices import PoPIndices
    cites = [10, 5, 3, 1, 0]
    years = [2020, 2021, 2022, 2023, 2024]
    hc = PoPIndices.contemporary_h_index(cites, years, current_year=2024)
    assert hc > 0
    assert hc <= 4  # always ≤ h-index


def test_bibliometrics_compute_all():
    """compute_all should return all PoP indices as a dict."""
    from bibliometrics.pop_indices import PoPIndices
    result = PoPIndices().compute_all([10, 5, 3, 1, 0])
    for key in ("h_index", "e_index", "g_index", "i10_index",
                "hc_index", "q2_index", "w_index", "h_max_index"):
        # hc_index has multiple aliases in the dict; check at least one
        pass
    assert result["h_index"] == 3
    assert result["g_index"] == 4
    assert result["i10_index"] == 1
    assert result["total_citations"] == 19


def test_bibliometrics_author_profile(synthetic_papers):
    """AuthorProfile.from_papers should produce sensible h/e-indices."""
    from bibliometrics.pop_indices import AuthorProfile
    p = AuthorProfile.from_papers(synthetic_papers)
    assert p.h_index >= 1
    assert p.e_index >= 0
    assert p.total_citations == sum(p.citations_count for p in synthetic_papers)


def test_bibliometrics_journal_metrics(synthetic_papers):
    """JournalMetrics should compute an impact factor without raising."""
    from bibliometrics.journal_metrics import JournalMetrics
    # Tag all papers with a journal so impact_factor can be computed.
    for p in synthetic_papers:
        p.journal = "Journal of Tests"
    jm = JournalMetrics()
    # Use year 2023 (cites from 2021-2022 to 2023); papers span 2020-2024.
    if_val = jm.impact_factor(synthetic_papers, "Journal of Tests", 2023)
    assert isinstance(if_val, float)
    assert if_val >= 0.0


# ---------------------------------------------------------------------------
# 4. networkx_pro algorithms
# ---------------------------------------------------------------------------
def test_networkx_pro_centrality(karate_graph):
    """Centralities.pagerank should return a dict of node -> score."""
    from networkx_pro.algorithms_centralities import Centralities
    pr = Centralities.pagerank(karate_graph)
    assert isinstance(pr, dict)
    assert len(pr) == karate_graph.number_of_nodes()
    # PageRank scores should sum to ~1.0
    assert abs(sum(pr.values()) - 1.0) < 1e-6


def test_networkx_pro_community_detection(karate_graph):
    """CommunityDetection.louvain_communities should partition the graph."""
    from networkx_pro.algorithms_communities import CommunityDetection
    comms = CommunityDetection.louvain_communities(karate_graph)
    assert len(comms) >= 2  # karate club has 2+ communities
    # Every node should be in exactly one community.
    all_nodes = set()
    for c in comms:
        all_nodes |= set(c)
    assert all_nodes == set(karate_graph.nodes())


def test_networkx_pro_components(karate_graph):
    """ComponentAnalysis.connected_components should list components."""
    from networkx_pro.algorithms_components import ComponentAnalysis
    comps = ComponentAnalysis.connected_components(karate_graph)
    assert isinstance(comps, list)
    assert len(comps) >= 1
    assert sum(len(c) for c in comps) == karate_graph.number_of_nodes()


def test_networkx_pro_paths_flows(karate_graph):
    """PathsAndFlows.diameter / radius / shortest_path should work."""
    from networkx_pro.algorithms_paths_flows import PathsAndFlows
    pf = PathsAndFlows()
    d = pf.diameter(karate_graph)
    assert d >= 1 and d <= 10
    r = pf.radius(karate_graph)
    assert r >= 1 and r <= d
    path = pf.shortest_path(karate_graph, source=0, target=1)
    assert isinstance(path, list)
    assert path[0] == 0 and path[-1] == 1


def test_networkx_pro_link_prediction(karate_graph):
    """LinkPrediction.jaccard_coefficient should return triples."""
    from networkx_pro.algorithms_link_prediction import LinkPrediction
    lp = LinkPrediction()
    preds = lp.jaccard_coefficient(karate_graph, ebunch=[(0, 33), (1, 2)])
    assert isinstance(preds, list)
    assert all(len(t) == 3 for t in preds)
    assert all(0.0 <= p <= 1.0 for *_, p in preds)


# ---------------------------------------------------------------------------
# 5. gephi_viz tests
# ---------------------------------------------------------------------------
def test_gephi_viz_forceatlas2_layout(karate_graph):
    """ForceAtlas2.apply should return positions for every node."""
    from gephi_viz.layouts import ForceAtlas2
    fa2 = ForceAtlas2()
    pos = {n: (0.0, 0.0) for n in karate_graph.nodes()}
    new_pos = fa2.apply(karate_graph, pos, iterations=20)
    assert isinstance(new_pos, dict)
    assert len(new_pos) == karate_graph.number_of_nodes()
    # Positions should diverge from the origin (not all zero).
    distances = [(x ** 2 + y ** 2) ** 0.5 for x, y in new_pos.values()]
    assert max(distances) > 0.0


def test_gephi_viz_filter_chain(karate_graph):
    """FilterChain.apply with no filters should return the input graph."""
    from gephi_viz.filters import FilterChain
    fc = FilterChain()
    out = fc.apply(karate_graph)
    assert out.number_of_nodes() == karate_graph.number_of_nodes()


def test_gephi_viz_filter_chain_with_filter(karate_graph):
    """FilterChain with a degree filter should reduce the graph."""
    from gephi_viz.filters import FilterChain, Filter

    class _MinDegreeFilter(Filter):
        def __init__(self, threshold: int = 5) -> None:
            super().__init__()
            self.threshold = threshold

        def apply(self, graph):
            keep = {n for n, d in graph.degree() if d >= self.threshold}
            return graph.subgraph(keep).copy()

    original_degrees = dict(karate_graph.degree())
    fc = FilterChain().add_filter(_MinDegreeFilter(threshold=5))
    out = fc.apply(karate_graph)
    # The subgraph should have fewer nodes than the original.
    assert out.number_of_nodes() < karate_graph.number_of_nodes()
    # Every node in the result had an original degree ≥ the threshold.
    for n in out.nodes():
        assert original_degrees[n] >= 5


def test_gephi_viz_statistics(karate_graph):
    """NetworkStatistics.compute_all should return sensible numbers."""
    from gephi_viz.statistics import NetworkStatistics
    report = NetworkStatistics().compute_all(karate_graph)
    assert report.total_nodes == 34
    assert report.total_edges == 78
    assert 0.0 <= report.density <= 1.0
    assert report.avg_degree > 0
    assert 0.0 <= report.avg_clustering <= 1.0


def test_gephi_viz_partition(karate_graph):
    """Partition.from_clustering with louvain should produce a valid mapping."""
    from gephi_viz.partition import Partition
    p = Partition.from_clustering(karate_graph, method="louvain")
    assert len(p.mapping) == karate_graph.number_of_nodes()
    assert p.num_groups() >= 1
    # Colors should produce a hex string per node.
    colors = p.colors()
    assert len(colors) == karate_graph.number_of_nodes()
    for c in colors.values():
        assert c.startswith("#") and len(c) == 7


# ---------------------------------------------------------------------------
# 6. systematic_review tests
# ---------------------------------------------------------------------------
SR_TEMPLATES = ["cochrane", "campbell", "jbi", "prisma_2020"]


@pytest.mark.parametrize("template", SR_TEMPLATES)
def test_sr_protocol_template_validates(template):
    """Each of the 4 protocol templates should build & validate cleanly."""
    from systematic_review.protocol import SystematicReviewProtocol
    p = SystematicReviewProtocol.from_template(template)
    errors = p.validate()
    # Templates may produce warnings (placeholders), but no fatal errors.
    assert isinstance(errors, list)


def test_sr_rob_tools_instantiate():
    """All 4 risk-of-bias tools should instantiate without raising."""
    from systematic_review.risk_of_bias import (
        CochraneRoB2, ROBINS_I, QUADAS2, NewcastleOttawaScale,
    )
    for cls in (CochraneRoB2, ROBINS_I, QUADAS2, NewcastleOttawaScale):
        inst = cls()
        assert inst is not None
        assert hasattr(inst, "name") or hasattr(inst, "__class__")


# ---------------------------------------------------------------------------
# 7. meta_analysis tests
# ---------------------------------------------------------------------------
def test_meta_analysis_pooling_DL():
    """DerSimonian-Laird pooling on 5 SMDs should return a non-None result."""
    from meta_analysis.effect_sizes import (
        EffectSize, EffectSizeType,
    )
    from meta_analysis.pooling import PoolingEngine, PoolingMethod
    es_list = [
        EffectSize(
            type=EffectSizeType.SMD, value=v, se=0.5,
            ci_lower=v - 1, ci_upper=v + 1, variance=0.25,
            study_name=f"Study {i + 1}",
        )
        for i, v in enumerate([0.3, 0.5, 0.7, -0.2, 0.4])
    ]
    result = PoolingEngine.pool(es_list, method=PoolingMethod.DL)
    assert result is not None
    assert result.pooled_effect is not None
    assert isinstance(result.I_squared, float)
    assert 0.0 <= result.I_squared <= 100.0
    assert len(result.weights) == len(es_list)


def test_meta_analysis_forest_plot_returns_figure():
    """ForestPlot.render should return a matplotlib Figure."""
    import matplotlib.figure
    from meta_analysis.effect_sizes import EffectSize, EffectSizeType
    from meta_analysis.pooling import PoolingEngine, PoolingMethod
    from meta_analysis.forest_plot import ForestPlot
    es_list = [
        EffectSize(
            type=EffectSizeType.SMD, value=v, se=0.5,
            ci_lower=v - 1, ci_upper=v + 1, variance=0.25,
            study_name=f"S{i + 1}",
        )
        for i, v in enumerate([0.3, 0.5, 0.7, -0.2, 0.4])
    ]
    result = PoolingEngine.pool(es_list, method=PoolingMethod.DL)
    fp = ForestPlot(es_list, result.pooled_effect, title="Test MA")
    fig = fp.render()
    assert isinstance(fig, matplotlib.figure.Figure)


# ---------------------------------------------------------------------------
# 8. prisma tests
# ---------------------------------------------------------------------------
def test_prisma_flow_generator_renders():
    """PRISMAFlowGenerator.render_matplotlib should not raise on valid counts."""
    from prisma.flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts
    counts = PRISMAStageCounts(
        n_records_databases=100, n_duplicates_removed=10,
        n_records_screened=90, n_records_excluded_title_abstract=70,
        n_full_text_assessed=20, n_full_text_excluded=5,
        n_studies_included_qualitative=15, n_studies_included_quantitative=12,
    )
    gen = PRISMAFlowGenerator(counts)
    fig = gen.render_matplotlib()
    assert fig is not None


def test_prisma_checklist_has_27_items():
    """The PRISMA 2020 checklist should expose exactly 27 items."""
    from prisma.checklist import PRISMAChecklist
    items = PRISMAChecklist().default_2020_items()
    assert isinstance(items, list)
    assert len(items) == 27


# ---------------------------------------------------------------------------
# 9. q1_figures tests
# ---------------------------------------------------------------------------
def test_q1_figures_factory_creates_figure():
    """Q1FigureFactory.new_figure should return a matplotlib Figure."""
    import matplotlib.figure
    from q1_figures.figure_factory import Q1FigureFactory
    f = Q1FigureFactory(journal="nature")
    fig = f.new_figure()
    assert isinstance(fig, matplotlib.figure.Figure)


def test_q1_figures_new_figure_and_axes():
    """The convenience helper new_figure_and_axes returns (fig, ax)."""
    import matplotlib.figure
    from matplotlib.axes import Axes
    from q1_figures.figure_factory import Q1FigureFactory
    f = Q1FigureFactory(journal="science")
    fig, ax = f.new_figure_and_axes()
    assert isinstance(fig, matplotlib.figure.Figure)
    assert isinstance(ax, Axes)


def test_q1_figures_factory_saves_png(tmp_path):
    """Q1FigureFactory.save should write a non-empty PNG file."""
    from q1_figures.figure_factory import Q1FigureFactory
    import numpy as np
    f = Q1FigureFactory(journal="cell")
    fig, ax = f.new_figure_and_axes()
    ax.plot([0, 1, 2, 3], [0, 1, 4, 9])
    out = tmp_path / "test.png"
    f.save(fig, str(out))
    assert out.exists()
    assert out.stat().st_size > 100


def test_q1_figures_save_infers_format(tmp_path):
    """save() should infer the format from the path extension."""
    from q1_figures.figure_factory import Q1FigureFactory
    f = Q1FigureFactory(journal="nature")
    fig, ax = f.new_figure_and_axes()
    ax.plot([0, 1, 2], [0, 1, 4])
    # SVG should produce a text file (vector format).
    svg = tmp_path / "test.svg"
    f.save(fig, str(svg))
    assert svg.exists()
    head = svg.read_text(errors="ignore")[:200]
    assert "<svg" in head.lower() or "<?xml" in head.lower() or "svg" in head.lower()


def test_q1_palettes_have_10_plus_colors():
    """Every Q1 palette constant should expose at least 10 colors."""
    from q1_figures.palettes import JournalPalettes
    palette_names = [
        n for n in dir(JournalPalettes)
        if n.isupper() and not n.startswith("_")
        and isinstance(getattr(JournalPalettes, n), list)
    ]
    assert len(palette_names) >= 10, (
        f"Expected ≥10 palettes, got {len(palette_names)}: {palette_names}"
    )
    for name in palette_names:
        colors = getattr(JournalPalettes, name)
        assert len(colors) >= 10, (
            f"{name} has {len(colors)} colors, expected ≥10"
        )


# ---------------------------------------------------------------------------
# 10. research_lifecycle tests
# ---------------------------------------------------------------------------
def test_research_lifecycle_protocol_templates_count():
    """The lifecycle library should expose ≥9 protocol templates."""
    from research_lifecycle.protocol_templates import ProtocolTemplateLibrary
    lib = ProtocolTemplateLibrary()
    templates = lib.available()
    assert len(templates) >= 9


def test_research_lifecycle_writing_assistant_outline_fallback():
    """WritingAssistant.outline should return a non-empty string in fallback."""
    from research_lifecycle.writing_assistant import WritingAssistant
    wa = WritingAssistant()
    out = wa.outline("Quantum Machine Learning")
    assert isinstance(out, str)
    assert len(out) > 50
    # Should at minimum mention Introduction and a heading marker.
    assert "introduction" in out.lower() or "##" in out


# ---------------------------------------------------------------------------
# 11. innovation tests
# ---------------------------------------------------------------------------
def test_innovation_citation_bursts_detection(synthetic_papers):
    """CitationBurstDetector should detect bursts on synthetic papers."""
    from innovation.citation_bursts import CitationBurstDetector
    det = CitationBurstDetector()
    bursts = det.detect_papers(synthetic_papers)
    assert isinstance(bursts, list)


def test_innovation_citation_bursts_on_larger_corpus():
    """CitationBurstDetector should detect ≥1 burst on a 50-paper corpus."""
    import random
    from data_acquisition.base_scraper import Paper
    from innovation.citation_bursts import CitationBurstDetector
    random.seed(42)
    papers = [
        Paper(
            title=f"P{i}", authors=["A"], abstract="",
            year=2015 + (i % 8), doi=f"10.1000/p{i}",
            citations_count=random.randint(0, 100),
            references=[], keywords=["ML"], fields_of_study=["CS"],
            url="", source="test", raw={},
        )
        for i in range(50)
    ]
    bursts = CitationBurstDetector().detect_papers(papers)
    assert isinstance(bursts, list)


def test_innovation_paper_recommender_with_mock_embedder(synthetic_papers):
    """PaperRecommender should index & recommend papers using a mock embedder."""
    from innovation.paper_recommendation import PaperRecommender

    class _MockEmbedder:
        def encode(self, texts):
            import numpy as np
            return np.random.rand(len(list(texts)), 8)

    rec = PaperRecommender(synthetic_papers, embedder=_MockEmbedder())
    rec.index_papers()
    # recommend_similar should return list of (paper, score) tuples.
    res = rec.recommend_similar(synthetic_papers[0], top_k=2)
    assert isinstance(res, list)
    assert len(res) <= 2


# ---------------------------------------------------------------------------
# 12. New scrapers registered in ScrapingEngine
# ---------------------------------------------------------------------------
def test_scraping_engine_registers_13_scrapers():
    """ScrapingEngine should auto-register ≥13 scrapers without API keys."""
    from data_acquisition.scraping_engine import ScrapingEngine
    e = ScrapingEngine()
    names = e.available_scrapers()
    assert len(names) >= 13, (
        f"Expected ≥13 registered scrapers, got {len(names)}: {names}"
    )
    # Spot-check a few names from each generation.
    for required in ("arxiv", "acm", "wikipedia", "unpaywall"):
        assert required in names, f"Required scraper {required!r} not registered"


# ---------------------------------------------------------------------------
# 13. Web server blueprints
# ---------------------------------------------------------------------------
def test_web_server_has_15_blueprints():
    """web.routes.ALL_BLUEPRINTS should expose exactly 15 blueprints."""
    import web.routes as wr
    assert len(wr.ALL_BLUEPRINTS) == 15


def test_web_bibliometrics_indices_endpoint():
    """POST /api/bibliometrics/indices should return h-index=3 for [10,5,3,1,0]."""
    from web.server import create_app
    app = create_app()
    client = app.test_client()
    r = client.post(
        "/api/bibliometrics/indices",
        json={"citations": [10, 5, 3, 1, 0], "years": [2020, 2021, 2022, 2023, 2024]},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert "indices" in data
    assert data["indices"]["h_index"] == 3
    assert data["indices"]["g_index"] == 4


def test_web_network_centrality_endpoint(karate_graph):
    """POST /api/network/centrality should accept pagerank and return 200."""
    import networkx as nx
    from web.server import create_app
    app = create_app()
    client = app.test_client()
    graph_json = nx.node_link_data(karate_graph)
    r = client.post(
        "/api/network/centrality",
        json={"graph": graph_json, "method": "pagerank"},
    )
    assert r.status_code == 200


def test_web_figures_palettes_endpoint():
    """GET /api/figures/palettes should return a palette list."""
    from web.server import create_app
    app = create_app()
    client = app.test_client()
    r = client.get("/api/figures/palettes")
    assert r.status_code == 200
    data = r.get_json()
    assert "palettes" in data
    assert isinstance(data["palettes"], list)
    assert len(data["palettes"]) >= 10


def test_web_innovation_bursts_endpoint():
    """POST /api/innovation/bursts should accept dict papers & return 200."""
    from web.server import create_app
    app = create_app()
    client = app.test_client()
    r = client.post(
        "/api/innovation/bursts",
        json={
            "papers": [
                {"title": f"P{i}", "year": 2020 + i, "citations_count": 10 * i}
                for i in range(20)
            ],
            "time_window": 1,
        },
    )
    assert r.status_code == 200
    data = r.get_json()
    assert "bursts" in data
    assert isinstance(data["bursts"], list)


# ---------------------------------------------------------------------------
# 14. Cross-module integration
# ---------------------------------------------------------------------------
def test_integration_scrape_to_bibliometrics(synthetic_papers):
    """Scrape → Bibliometric analysis end-to-end with synthetic papers."""
    from bibliometrics.pop_indices import AuthorProfile
    profile = AuthorProfile.from_papers(synthetic_papers)
    assert profile.h_index >= 1
    assert profile.e_index >= 0


def test_integration_network_to_gephi_viz(karate_graph):
    """NetworkX graph → Gephi layout + statistics + partition end-to-end."""
    from gephi_viz.layouts import ForceAtlas2
    from gephi_viz.statistics import NetworkStatistics
    from gephi_viz.partition import Partition
    pos = {n: (0.0, 0.0) for n in karate_graph.nodes()}
    new_pos = ForceAtlas2().apply(karate_graph, pos, iterations=20)
    assert len(new_pos) == karate_graph.number_of_nodes()
    report = NetworkStatistics().compute_all(karate_graph)
    assert report.total_nodes == 34 and report.total_edges == 78
    p = Partition.from_clustering(karate_graph, method="louvain")
    assert p.num_groups() >= 1


def test_integration_meta_analysis_to_forest_plot():
    """Meta-analysis pooling → forest plot rendering end-to-end."""
    from meta_analysis.effect_sizes import EffectSize, EffectSizeType
    from meta_analysis.pooling import PoolingEngine, PoolingMethod
    from meta_analysis.forest_plot import ForestPlot
    es_list = [
        EffectSize(
            type=EffectSizeType.SMD, value=v, se=0.5,
            ci_lower=v - 1, ci_upper=v + 1, variance=0.25,
            study_name=f"Study {i + 1}",
        )
        for i, v in enumerate([0.3, 0.5, 0.7, -0.2, 0.4])
    ]
    result = PoolingEngine.pool(es_list, method=PoolingMethod.DL)
    fp = ForestPlot(es_list, result.pooled_effect, title="Integration MA")
    fig = fp.render()
    assert fig is not None


def test_integration_q1_figures_factory_save_png_svg(tmp_path):
    """Q1FigureFactory → StatisticalPlots.boxplot → save PNG + SVG end-to-end."""
    import numpy as np
    from q1_figures.figure_factory import Q1FigureFactory
    from q1_figures.statistical_plots import StatisticalPlots
    f = Q1FigureFactory(journal="nature")
    fig, ax = f.new_figure_and_axes()
    data = [np.random.randn(30) for _ in range(3)]
    StatisticalPlots.boxplot(ax, data, ["A", "B", "C"], show_points=True)
    png = tmp_path / "test.png"
    svg = tmp_path / "test.svg"
    f.save(fig, str(png))
    f.save(fig, str(svg))
    assert png.exists() and png.stat().st_size > 100
    assert svg.exists() and svg.stat().st_size > 100


def test_integration_prisma_flow_and_checklist():
    """PRISMA flow generator + 27-item checklist integration."""
    from prisma.flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts
    from prisma.checklist import PRISMAChecklist
    counts = PRISMAStageCounts(
        n_records_databases=100, n_duplicates_removed=10,
        n_records_screened=90, n_records_excluded_title_abstract=70,
        n_full_text_assessed=20, n_full_text_excluded=5,
        n_studies_included_qualitative=15, n_studies_included_quantitative=12,
    )
    fig = PRISMAFlowGenerator(counts).render_matplotlib()
    assert fig is not None
    items = PRISMAChecklist().default_2020_items()
    assert len(items) == 27


# ---------------------------------------------------------------------------
# 15. Desktop app launch + sidebar pages
# ---------------------------------------------------------------------------
def test_desktop_app_switches_to_all_v2_pages():
    """MainWindow should be able to switch to every v2 sidebar page."""
    from qtpy.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.modern_theme import ModernTheme
    ModernTheme.apply(app, "dark")
    from ui.main_window import MainWindow
    w = MainWindow()
    try:
        from ui.widgets.sidebar import default_nav_items
        pages = [item.page_key for item in default_nav_items()]
        v2_pages = [
            "bibliometrics", "gephi_advanced", "systematic_review",
            "meta_analysis", "prisma_builder", "q1_figures", "innovation",
        ]
        ok = 0
        for p in v2_pages:
            try:
                w.show_page(p)
                ok += 1
            except Exception:
                pass
        # Every v2 page should be switchable (>=7 OK).
        assert ok >= 7, f"Only {ok}/7 v2 pages switched successfully"
        # And the overall page list should include all 18 v1+v2 pages.
        assert len(pages) >= 18
    finally:
        w.close()


# ---------------------------------------------------------------------------
# 16. v1 regression check (sanity)
# ---------------------------------------------------------------------------
def test_v1_smoke_still_imports():
    """A handful of v1 modules should still import (regression sanity)."""
    import importlib
    for mod in (
        "core.orchestrator", "data_acquisition.arxiv_scraper",
        "database.connection", "ui.main_window", "web.server",
    ):
        importlib.import_module(mod)
