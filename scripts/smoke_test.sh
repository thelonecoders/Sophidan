#!/usr/bin/env bash
#
# Academic Research Suite — end-to-end smoke test runner.
#
# Usage:
#     ./scripts/smoke_test.sh              # run pytest suite + module smoke
#     ./scripts/smoke_test.sh --quick      # skip the heavy DB / Qt launch
#     ./scripts/smoke_test.sh --help
#
# Exits 0 on success, 1 on any failure. Prints a short summary at the end.
#
# MIT License — Academic Research Suite — Copyright (c) 2026
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Force offscreen Qt + Agg matplotlib for headless environments.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export MPLBACKEND="${MPLBACKEND:-Agg}"

QUICK_MODE=0
if [[ "${1:-}" == "--quick" ]]; then
    QUICK_MODE=1
    shift
fi
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'USAGE'
Academic Research Suite — smoke test runner.

Options:
  --quick    Skip the module import sweep (only run pytest).
  --help     Show this help.

The script:
  1. (Unless --quick) imports every public Python module to catch
     ImportError / circular-import regressions.
  2. Runs the pytest suite at tests/test_smoke.py.
  3. Boots the Flask web server test client and pings /api/health,
     /api/papers/, /api/projects/, /api/proxy/stats, /.
  4. Launches the PyQt5 desktop MainWindow offscreen.

Exit codes:
  0 — all checks passed
  1 — one or more checks failed
USAGE
    exit 0
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

log()  { echo "${BOLD}>>>${RESET} $*"; }
ok()   { echo "${GREEN}  OK${RESET}  $*"; }
warn() { echo "${YELLOW}  WARN${RESET} $*"; }
fail() { echo "${RED}FAIL${RESET}  $*"; }

status=0

# ---------------------------------------------------------------------------
# Step 1 — module import sweep
# ---------------------------------------------------------------------------
if [[ "$QUICK_MODE" -eq 0 ]]; then
    log "Importing every public module..."
    fail_count=0
    while IFS= read -r mod; do
        if ! python -c "import $mod" 2>/dev/null; then
            fail "import $mod"
            fail_count=$((fail_count + 1))
        fi
    done <<'MODULES'
config.settings
utils.logger
utils.config_manager
utils.workers
utils.cache
utils.exceptions
core.orchestrator
core.task_queue
core.events
proxy.proxy_manager
proxy.proxy_pool
proxy.proxy_chain
proxy.proxy_rotation
proxy.proxy_health_check
proxy.proxy_scraper
data_acquisition.base_scraper
data_acquisition.arxiv_scraper
data_acquisition.pubmed_scraper
data_acquisition.openalex_scraper
data_acquisition.semantic_scholar_scraper
data_acquisition.google_scholar_scraper
data_acquisition.crossref_scraper
data_acquisition.dblp_scraper
data_acquisition.orcid_scraper
data_acquisition.doi_lookup
data_acquisition.scraping_engine
data_science.analysis_engine
data_science.topic_modeler
data_science.embeddings
data_science.clustering
data_science.temporal_analysis
data_science.statistics
data_science.visualizations
knowledge_graph.network_analyzer
knowledge_graph.citation_graph
knowledge_graph.collaboration_graph
knowledge_graph.temporal_network
knowledge_graph.graph_algorithms
ai_assistant.llm_client
ai_assistant.prompts
ai_assistant.rag_engine
ai_assistant.summarizer
ai_assistant.chat_engine
reporting.pdf_report
reporting.docx_report
reporting.pptx_report
reporting.bibtex_export
reporting.csv_export
reporting.chart_generator
database.models
database.connection
database.search
database.vector_store
project_management.project_manager
project_management.workspace
project_management.snapshots
project_management.comparison
ui.modern_theme
ui.welcome_screen
ui.main_window
ui.widgets.sidebar
ui.widgets.dashboard
ui.widgets.data_view
ui.widgets.search_panel
ui.widgets.network_view
ui.widgets.analysis_view
ui.widgets.ai_chat
ui.widgets.proxy_panel
ui.widgets.project_explorer
ui.widgets.settings_panel
ui.dialogs.advanced_search
ui.dialogs.author_dashboard
ui.dialogs.reporting_dashboard
ui.dialogs.export_wizard
ui.dialogs.help_dialog
web.server
web.routes
web.routes.papers
web.routes.projects
web.routes.scraping
web.routes.analytics
main
MODULES
    if [[ "$fail_count" -eq 0 ]]; then
        ok "All modules imported successfully."
    else
        fail "$fail_count module(s) failed to import."
        status=1
    fi
fi

# ---------------------------------------------------------------------------
# Step 2 — pytest suite
# ---------------------------------------------------------------------------
log "Running pytest suite (tests/test_smoke.py)..."
if python -m pytest tests/test_smoke.py -q 2>&1 | tail -5; then
    ok "pytest suite passed."
else
    fail "pytest suite reported failures."
    status=1
fi

# ---------------------------------------------------------------------------
# Step 3 — web server endpoints
# ---------------------------------------------------------------------------
log "Pinging Flask web server endpoints..."
if python - <<'PY' 2>/dev/null
from web.server import create_app
app = create_app()
client = app.test_client()
endpoints = [
    "/api/health", "/api/papers/", "/api/projects/",
    "/api/proxy/stats", "/",
]
for ep in endpoints:
    r = client.get(ep)
    assert r.status_code < 500, f"{ep} -> {r.status_code}"
print("All web endpoints returned < 500.")
PY
then
    ok "Web server endpoints healthy."
else
    fail "Web server endpoint check failed."
    status=1
fi

# ---------------------------------------------------------------------------
# Step 4 — desktop app launch (offscreen)
# ---------------------------------------------------------------------------
log "Launching MainWindow (offscreen Qt)..."
if python - <<'PY' 2>/dev/null
import sys
from qtpy.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from ui.modern_theme import ModernTheme
ModernTheme.apply(app, "dark")
from ui.main_window import MainWindow
w = MainWindow()
w.show()
app.processEvents()
w.close()
app.processEvents()
print("MainWindow launched and closed cleanly.")
PY
then
    ok "MainWindow launched and closed cleanly."
else
    fail "MainWindow launch failed."
    status=1
fi

# ---------------------------------------------------------------------------
# Stage 5 — v2.0 module smoke tests
# ---------------------------------------------------------------------------
log "Stage 5: v2.0 module smoke tests..."

# 5a. Import every v2.0 module (9 packages + new scrapers + new widgets + new routes).
v2_import_failures=0
while IFS= read -r mod; do
    if ! python -c "import $mod" 2>/dev/null; then
        fail "import $mod (v2)"
        v2_import_failures=$((v2_import_failures + 1))
    fi
done <<'V2_MODULES'
bibliometrics
bibliometrics.pop_indices
bibliometrics.journal_metrics
bibliometrics.citespace
bibliometrics.scientogram
bibliometrics.vosviewer
networkx_pro
networkx_pro.algorithms_centralities
networkx_pro.algorithms_communities
networkx_pro.algorithms_components
networkx_pro.algorithms_paths_flows
networkx_pro.algorithms_link_prediction
networkx_pro.algorithms_isomorphism
networkx_pro.algorithms_bipartite
networkx_pro.algorithms_generators
networkx_pro.graph_io
networkx_pro.multigraph
gephi_viz
gephi_viz.layouts
gephi_viz.filters
gephi_viz.statistics
gephi_viz.partition
gephi_viz.ranking
gephi_viz.preview
gephi_viz.interactive_canvas
systematic_review
systematic_review.protocol
systematic_review.screening
systematic_review.risk_of_bias
systematic_review.data_extraction
systematic_review.synthesis
systematic_review.prisma_integration
meta_analysis
meta_analysis.effect_sizes
meta_analysis.pooling
meta_analysis.network_meta
meta_analysis.subgroup
meta_analysis.forest_plot
meta_analysis.funnel_plot
meta_analysis.report
prisma
prisma.flow_diagram
prisma.checklist
prisma.extraction_form
prisma.extensions
prisma.report
q1_figures
q1_figures.figure_factory
q1_figures.palettes
q1_figures.typography
q1_figures.statistical_plots
q1_figures.data_plots
q1_figures.network_plots
q1_figures.bibliometric_plots
q1_figures.multi_panel
research_lifecycle
research_lifecycle.protocol_templates
research_lifecycle.ideation
research_lifecycle.synthesis_methods
research_lifecycle.quality_assessment
research_lifecycle.data_extraction
research_lifecycle.writing_assistant
research_lifecycle.reporting_checklists
innovation
innovation.citation_bursts
innovation.frontier_mapping
innovation.trend_forecasting
innovation.paper_recommendation
innovation.collaboration_recommendation
innovation.novelty_scoring
innovation.research_directions
data_acquisition.springer_scraper
data_acquisition.ieee_scraper
data_acquisition.acm_scraper
data_acquisition.core_scraper
data_acquisition.base_scraper_ext
data_acquisition.unpaywall_scraper
data_acquisition.opencitations_scraper
data_acquisition.sciopen_scraper
data_acquisition.wikipedia_scraper
ui.widgets.bibliometric_dashboard
ui.widgets.prisma_builder
ui.widgets.meta_analysis_view
ui.widgets.systematic_review_view
ui.widgets.q1_figure_studio
ui.widgets.innovation_panel
ui.widgets.gephi_advanced_view
web.routes.bibliometrics
web.routes.network_analysis
web.routes.sr
web.routes.ma
web.routes.q1_figures
web.routes.innovation
web.routes.research_lifecycle
V2_MODULES
if [[ "$v2_import_failures" -eq 0 ]]; then
    ok "All v2.0 modules imported successfully."
else
    fail "$v2_import_failures v2.0 module(s) failed to import."
    status=1
fi

# 5b. Run the v2 pytest suite.
log "Running v2 pytest suite (tests/test_v2.py)..."
if python -m pytest tests/test_v2.py -q 2>&1 | tail -5; then
    ok "v2 pytest suite passed."
else
    fail "v2 pytest suite reported failures."
    status=1
fi

# 5c. Quick integration checks (scrape→bibliometrics, network→gephi,
#     meta-analysis→forest plot, PRISMA flow + checklist, Q1 figure save).
log "Running v2 quick integration checks..."
if python - <<'PY' 2>/dev/null
import os, tempfile
# Scrape → Bibliometric analysis
from data_acquisition.base_scraper import Paper
from bibliometrics.pop_indices import AuthorProfile
papers = [Paper(title=f"P{i}", authors=["A"], abstract="", year=2020+i,
                doi=f"10.1000/p{i}", citations_count=10*i, references=[],
                keywords=["AI"], fields_of_study=["CS"], url="",
                source="test", raw={}) for i in range(5)]
profile = AuthorProfile.from_papers(papers)
assert profile.h_index >= 1, f"h-index too low: {profile.h_index}"

# Network → Gephi viz
import networkx as nx
from gephi_viz.layouts import ForceAtlas2
from gephi_viz.statistics import NetworkStatistics
from gephi_viz.partition import Partition
g = nx.karate_club_graph()
pos = {n: (0.0, 0.0) for n in g.nodes()}
new_pos = ForceAtlas2().apply(g, pos, iterations=20)
assert len(new_pos) == g.number_of_nodes()
stats = NetworkStatistics().compute_all(g)
assert stats.total_nodes == 34 and stats.total_edges == 78
p = Partition.from_clustering(g, method="louvain")
assert p.num_groups() >= 1

# Meta-analysis end-to-end
from meta_analysis.effect_sizes import EffectSize, EffectSizeType
from meta_analysis.pooling import PoolingEngine, PoolingMethod
from meta_analysis.forest_plot import ForestPlot
es_list = [EffectSize(type=EffectSizeType.SMD, value=v, se=0.5,
                      ci_lower=v-1, ci_upper=v+1, variance=0.25,
                      study_name=f"S{i+1}")
           for i, v in enumerate([0.3, 0.5, 0.7, -0.2, 0.4])]
result = PoolingEngine.pool(es_list, method=PoolingMethod.DL)
assert result.pooled_effect is not None
fp = ForestPlot(es_list, result.pooled_effect, title="Integration MA")
assert fp.render() is not None

# PRISMA flow + checklist
from prisma.flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts
from prisma.checklist import PRISMAChecklist
counts = PRISMAStageCounts(n_records_databases=100, n_duplicates_removed=10,
                            n_records_screened=90,
                            n_records_excluded_title_abstract=70,
                            n_full_text_assessed=20,
                            n_full_text_excluded=5,
                            n_studies_included_qualitative=15,
                            n_studies_included_quantitative=12)
assert PRISMAFlowGenerator(counts).render_matplotlib() is not None
items = PRISMAChecklist().default_2020_items()
assert len(items) == 27, f"PRISMA checklist has {len(items)} items, expected 27"

# Q1 figures
import numpy as np
from q1_figures.figure_factory import Q1FigureFactory
from q1_figures.statistical_plots import StatisticalPlots
f = Q1FigureFactory(journal="nature")
fig, ax = f.new_figure_and_axes()
StatisticalPlots.boxplot(ax, [np.random.randn(20) for _ in range(3)],
                        ["A", "B", "C"], show_points=True)
with tempfile.TemporaryDirectory() as td:
    png_path = os.path.join(td, "test.png")
    svg_path = os.path.join(td, "test.svg")
    f.save(fig, png_path)
    f.save(fig, svg_path)
    assert os.path.getsize(png_path) > 100
    assert os.path.getsize(svg_path) > 100

print("v2 integration checks passed.")
PY
then
    ok "v2 integration checks passed."
else
    fail "v2 integration checks failed."
    status=1
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
if [[ "$status" -eq 0 ]]; then
    echo "${GREEN}${BOLD}All smoke tests passed.${RESET}"
else
    echo "${RED}${BOLD}Smoke tests reported failures — see above.${RESET}"
fi
exit "$status"
