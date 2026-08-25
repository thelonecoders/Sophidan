"""End-to-end smoke tests for the Academic Research Suite.

These tests run *without* any external services (no LLM API keys, no
network access required). They cover:

* Module imports for every public package (sub-agents 1-core, 1-proxy,
  1-scraper-a, 1-scraper-b, 1-datasci, 1-graph, 1-ai, 1-reporting,
  1-db, 1-ui-core, 1-ui-panels, 1-web).
* Database initialisation (SQLite, in-memory or temp file).
* Desktop UI launch (offscreen Qt).
* Web server blueprints + REST endpoints.
* End-to-end project / paper / FTS / CSV-export mini-flow.
* Cross-module integration: ScrapingEngine + ProxyManager,
  ChatEngine + LLMClient(echo), ChartGenerator + Paper dataclass,
  CitationGraph + Paper dataclass.
* web/routes/__init__.py blueprint exposure.

Run with::

    pytest tests/test_smoke.py -v

The tests are designed to be hermetic — each test that touches the
database uses its own temp directory and an isolated
:class:`DatabaseConnection` singleton keyed by URL.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

import pytest

# Make sure the project root is on sys.path so `import config`, `import
# ui.main_window`, etc. work regardless of where pytest is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Force offscreen Qt for the entire test session.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Suppress matplotlib "tight_layout" / font-cache warnings during tests.
os.environ.setdefault("MPLBACKEND", "Agg")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def tmp_db_path(tmp_path):
    """Return a fresh SQLite DB path inside the test's tmp_path."""
    return str(tmp_path / "ars_smoke.db")


@pytest.fixture()
def db(tmp_db_path):
    """Construct an isolated DatabaseConnection + init the schema."""
    from database.connection import DatabaseConnection
    conn = DatabaseConnection(db_path=tmp_db_path)
    conn.init_db()
    yield conn


# ---------------------------------------------------------------------------
# 1. Module imports
# ---------------------------------------------------------------------------
MODULES_TO_IMPORT = [
    # core / utils / config
    "config.settings", "utils.logger", "utils.config_manager",
    "utils.workers", "utils.cache", "utils.exceptions",
    "core.orchestrator", "core.task_queue", "core.events",
    # proxy
    "proxy.proxy_manager", "proxy.proxy_pool", "proxy.proxy_chain",
    "proxy.proxy_rotation", "proxy.proxy_health_check", "proxy.proxy_scraper",
    # data acquisition
    "data_acquisition.base_scraper", "data_acquisition.arxiv_scraper",
    "data_acquisition.pubmed_scraper", "data_acquisition.openalex_scraper",
    "data_acquisition.semantic_scholar_scraper",
    "data_acquisition.google_scholar_scraper",
    "data_acquisition.crossref_scraper", "data_acquisition.dblp_scraper",
    "data_acquisition.orcid_scraper", "data_acquisition.doi_lookup",
    "data_acquisition.scraping_engine",
    # data science
    "data_science.analysis_engine", "data_science.topic_modeler",
    "data_science.embeddings", "data_science.clustering",
    "data_science.temporal_analysis", "data_science.statistics",
    "data_science.visualizations",
    # knowledge graph
    "knowledge_graph.network_analyzer", "knowledge_graph.citation_graph",
    "knowledge_graph.collaboration_graph", "knowledge_graph.temporal_network",
    "knowledge_graph.graph_algorithms",
    # ai assistant
    "ai_assistant.llm_client", "ai_assistant.prompts",
    "ai_assistant.rag_engine", "ai_assistant.summarizer",
    "ai_assistant.chat_engine",
    # reporting
    "reporting.pdf_report", "reporting.docx_report",
    "reporting.pptx_report", "reporting.bibtex_export",
    "reporting.csv_export", "reporting.chart_generator",
    # database
    "database.models", "database.connection",
    "database.search", "database.vector_store",
    # project management
    "project_management.project_manager", "project_management.workspace",
    "project_management.snapshots", "project_management.comparison",
    # ui
    "ui.modern_theme", "ui.welcome_screen", "ui.main_window",
    "ui.widgets.sidebar", "ui.widgets.dashboard", "ui.widgets.data_view",
    "ui.widgets.search_panel", "ui.widgets.network_view",
    "ui.widgets.analysis_view", "ui.widgets.ai_chat",
    "ui.widgets.proxy_panel", "ui.widgets.project_explorer",
    "ui.widgets.settings_panel",
    "ui.dialogs.advanced_search", "ui.dialogs.author_dashboard",
    "ui.dialogs.reporting_dashboard", "ui.dialogs.export_wizard",
    "ui.dialogs.help_dialog",
    # web
    "web.server", "web.routes", "web.routes.papers", "web.routes.projects",
    "web.routes.scraping", "web.routes.analytics",
    # top-level
    "main",
]


@pytest.mark.parametrize("module_name", MODULES_TO_IMPORT)
def test_module_imports(module_name):
    """Every public module should import without raising."""
    import importlib
    mod = importlib.import_module(module_name)
    assert mod is not None, f"import_module({module_name!r}) returned None"


# ---------------------------------------------------------------------------
# 2. Database init smoke test
# ---------------------------------------------------------------------------
def test_database_init(db):
    """init_db() should create the canonical table set."""
    engine = db.get_engine()
    with engine.connect() as conn:
        # SQLAlchemy 2.x — use inspector for table names.
        from sqlalchemy import inspect
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
    expected = {
        "papers", "authors", "projects", "keywords",
        "fields_of_study", "references", "snapshots", "proxies",
        "query_history", "embeddings",
        "paper_project_assoc", "paper_author_assoc",
        "paper_keyword_assoc", "paper_field_assoc",
    }
    missing = expected - tables
    assert not missing, f"Missing tables: {sorted(missing)}"


# ---------------------------------------------------------------------------
# 3. Desktop app launch smoke test (offscreen Qt)
# ---------------------------------------------------------------------------
def test_desktop_app_launch():
    """MainWindow should construct, show, and close under offscreen Qt."""
    from qtpy.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.modern_theme import ModernTheme
    ModernTheme.apply(app, "dark")
    from ui.main_window import MainWindow
    w = MainWindow()
    assert w is not None
    w.show()
    app.processEvents()
    w.close()
    app.processEvents()


# ---------------------------------------------------------------------------
# 4. Web server smoke test
# ---------------------------------------------------------------------------
def test_web_server_health():
    """/api/health returns 200 and reports the version."""
    from web.server import create_app
    app = create_app()
    client = app.test_client()
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "ok"
    assert "modules" in data


def test_web_server_dashboard():
    """The dashboard HTML should render and be non-empty."""
    from web.server import create_app
    app = create_app()
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert len(r.data) > 100


def test_web_server_papers_list():
    """GET /api/papers/ should return 200 (possibly empty list)."""
    from web.server import create_app
    app = create_app()
    client = app.test_client()
    r = client.get("/api/papers/")
    assert r.status_code == 200


def test_web_server_projects_list():
    """GET /api/projects/ should return 200 with a projects array."""
    from web.server import create_app
    app = create_app()
    client = app.test_client()
    r = client.get("/api/projects/")
    assert r.status_code == 200
    data = r.get_json()
    assert "projects" in data
    assert "count" in data


def test_web_server_proxy_stats():
    """GET /api/proxy/stats should return 200."""
    from web.server import create_app
    app = create_app()
    client = app.test_client()
    r = client.get("/api/proxy/stats")
    assert r.status_code == 200


def test_web_routes_init_exposes_all_blueprints():
    """web.routes should expose all expected blueprint names.

    The v1.0.0 baseline shipped 8 blueprints; the v2.0.0 v2-ui-web
    sub-agent added 7 more (bibliometrics, network, sr, ma, figures,
    innovation, lifecycle), bringing the canonical count to 15.
    """
    import web.routes as wr
    expected = [
        "papers_bp", "projects_bp", "scraping_bp", "analytics_bp",
        "ai_bp", "proxy_bp", "export_bp", "ws_bp",
        # v2.0.0 — added by v2-ui-web
        "bibliometrics_bp", "network_bp", "sr_bp", "ma_bp",
        "figures_bp", "innovation_bp", "lifecycle_bp",
    ]
    for name in expected:
        assert hasattr(wr, name), f"web.routes is missing {name}"
        bp = getattr(wr, name)
        assert bp is not None, f"web.routes.{name} is None"
        assert hasattr(bp, "name"), f"{name} is not a Blueprint"
    assert len(wr.ALL_BLUEPRINTS) == 15


# ---------------------------------------------------------------------------
# 5. End-to-end mini-flow
# ---------------------------------------------------------------------------
def test_e2e_project_paper_fts_csv(db, tmp_path):
    """ProjectManager + PaperModel + FullTextSearch + CSVExporter end-to-end."""
    from project_management.project_manager import ProjectManager
    from database.models import PaperModel
    from database.search import FullTextSearch
    from reporting.csv_export import CSVExporter
    from data_acquisition.base_scraper import Paper

    # 1. Create a project.
    pm = ProjectManager(db)
    proj = pm.create_project(
        name="E2E Validation Project",
        description="end-to-end smoke test",
    )
    assert proj.id is not None

    # 2. Construct FTS (creates the virtual table) and add a paper.
    fts = FullTextSearch(db)
    with db.get_db() as session:
        p = PaperModel(
            title="Quantum Neural Networks for Drug Discovery",
            abstract="We propose a novel architecture combining quantum "
                     "computing with neural networks for drug discovery.",
            year=2024,
            doi="10.9999/e2e-quantum",
            source="manual",
            citations_count=0,
            journal="Journal of Validation Studies",
        )
        session.add(p)
        session.flush()
        paper_id = p.id
        fts.index_paper(p, session=session)
    assert paper_id >= 1

    # 3. Attach the paper to the project.
    added = pm.add_papers_to_project(proj.id, [paper_id])
    assert added == 1

    # 4. FTS search should find the paper.
    hits = fts.search("quantum neural")
    assert any(h.id == paper_id for h in hits), \
        "FTS search did not find the inserted paper"

    # 5. CSV export from a Paper dataclass built off the DB row.
    paper_dto = Paper(
        title=p.title,
        authors=["Alice Author", "Bob Researcher"],
        abstract=p.abstract or "",
        year=p.year,
        doi=p.doi,
        source=p.source or "",
        citations_count=p.citations_count,
        journal=p.journal,
    )
    exporter = CSVExporter()
    out_path = str(tmp_path / "e2e_export.csv")
    written = exporter.export([paper_dto], out_path)
    assert os.path.isfile(written)
    with open(written, "r", encoding="utf-8-sig") as fh:
        body = fh.read()
    assert "Quantum Neural Networks" in body
    assert "Alice Author" in body


# ---------------------------------------------------------------------------
# 6. Cross-module integration
# ---------------------------------------------------------------------------
def test_scraping_engine_with_proxy_manager():
    """ScrapingEngine should accept a ProxyManager via the proxy_manager kwarg."""
    from data_acquisition.scraping_engine import ScrapingEngine
    from proxy.proxy_manager import ProxyManager

    pm = ProxyManager(persist=False)
    engine = ScrapingEngine(proxy_manager=pm)
    assert engine.proxy_manager is pm


def test_chat_engine_with_echo_llm_client():
    """ChatEngine should accept an LLMClient(provider='none', model='echo')."""
    from ai_assistant.chat_engine import ChatEngine
    from ai_assistant.llm_client import LLMClient

    llm = LLMClient(provider="none", model="echo")
    ce = ChatEngine(llm_client=llm)
    assert ce.llm_client is llm
    # Echo backend should return a non-empty string for any prompt.
    resp = ce.llm_client.chat([{"role": "user", "content": "hello world"}])
    assert isinstance(resp, str)
    assert len(resp) > 0


def test_chart_generator_with_paper_dataclass():
    """ChartGenerator.publications_per_year should accept Paper instances."""
    from reporting.chart_generator import ChartGenerator
    from data_acquisition.base_scraper import Paper

    papers = [
        Paper(title="P1", authors=["A"], year=2020, doi="10.0/p1",
              citations_count=5, journal="J1"),
        Paper(title="P2", authors=["B"], year=2021, doi="10.0/p2",
              citations_count=10, journal="J2"),
        Paper(title="P3", authors=["A", "B"], year=2022, doi="10.0/p3",
              citations_count=2, journal="J1"),
    ]
    cg = ChartGenerator()
    fig = cg.publications_per_year(papers)
    assert fig is not None
    assert len(fig.axes) >= 1


def test_citation_graph_build_with_paper_dataclass():
    """CitationGraph.build() should accept Paper instances and return a DiGraph."""
    from knowledge_graph.citation_graph import CitationGraph
    from data_acquisition.base_scraper import Paper

    papers = [
        Paper(title="Alpha", authors=["A"], year=2020, doi="10.0/alpha",
              references=["10.0/beta"]),
        Paper(title="Beta", authors=["B"], year=2021, doi="10.0/beta",
              references=["10.0/gamma"]),
        Paper(title="Gamma", authors=["C"], year=2022, doi="10.0/gamma"),
    ]
    cg = CitationGraph()
    g = cg.build(papers)
    assert g.number_of_nodes() == 3
    assert g.number_of_edges() == 2  # Alpha→Beta, Beta→Gamma


# ---------------------------------------------------------------------------
# 7. ProjectManager convenience methods (used by web routes)
# ---------------------------------------------------------------------------
def test_project_manager_list_with_query(db):
    """list_projects(query=) should filter by substring."""
    from project_management.project_manager import ProjectManager
    pm = ProjectManager(db)
    pm.create_project(name="Alpha Project")
    pm.create_project(name="Beta Initiative")
    hits = pm.list_projects(query="Alpha")
    assert len(hits) == 1
    assert hits[0].name == "Alpha Project"


def test_project_manager_update_project(db):
    """update_project should accept a partial dict payload."""
    from project_management.project_manager import ProjectManager
    pm = ProjectManager(db)
    proj = pm.create_project(name="Update Me")
    updated = pm.update_project(proj.id, {"description": "new desc",
                                          "color": "#FF0000"})
    assert updated is not None
    assert updated.description == "new desc"
    assert updated.color == "#FF0000"


def test_project_manager_create_snapshot_delegate(db):
    """create_snapshot(project_id, payload) should delegate to SnapshotManager."""
    from project_management.project_manager import ProjectManager
    pm = ProjectManager(db)
    proj = pm.create_project(name="Snapshot Project")
    snap = pm.create_snapshot(proj.id, {"name": "v1", "description": "first"})
    assert snap is not None
    snaps = pm.list_snapshots(proj.id)
    assert len(snaps) == 1


def test_project_manager_compare_projects_delegate(db):
    """compare_projects should delegate to ProjectComparison."""
    from project_management.project_manager import ProjectManager
    pm = ProjectManager(db)
    a = pm.create_project(name="Cmp A")
    b = pm.create_project(name="Cmp B")
    result = pm.compare_projects(a.id, b.id)
    assert result is not None
    # ComparisonResult exposes .to_dict() per the worklog.
    assert hasattr(result, "to_dict")
    d = result.to_dict()
    assert isinstance(d, dict)


# ---------------------------------------------------------------------------
# 8. requirements.txt hygiene
# ---------------------------------------------------------------------------
def test_requirements_no_duplicates():
    """requirements.txt should contain each package line at most once."""
    req_path = PROJECT_ROOT / "requirements.txt"
    assert req_path.is_file(), "requirements.txt not found"
    seen = set()
    dupes = []
    with req_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Use package name (lowercased) as the dedup key.
            pkg_key = stripped.split()[0].lower()
            if pkg_key in seen:
                dupes.append(stripped)
            else:
                seen.add(pkg_key)
    assert not dupes, f"Duplicate packages in requirements.txt: {dupes}"


def test_requirements_includes_pytest():
    """requirements.txt should declare pytest under a TESTING header."""
    req_path = PROJECT_ROOT / "requirements.txt"
    body = req_path.read_text(encoding="utf-8")
    assert "pytest>=" in body
    assert "# === TESTING ===" in body


# ---------------------------------------------------------------------------
# 9. Package __init__.py audit
# ---------------------------------------------------------------------------
EXPECTED_PACKAGES = [
    "ui/widgets", "ui/dialogs", "web/routes", "core", "proxy",
    "data_acquisition", "data_science", "knowledge_graph",
    "ai_assistant", "reporting", "project_management", "database",
    "utils", "config", "tests", "docs",
]


@pytest.mark.parametrize("rel", EXPECTED_PACKAGES)
def test_package_has_init_py(rel):
    """Every package directory should contain an __init__.py file."""
    pkg = PROJECT_ROOT / rel
    assert pkg.is_dir(), f"{rel}/ is not a directory"
    init = pkg / "__init__.py"
    assert init.is_file(), f"{rel}/__init__.py is missing"
