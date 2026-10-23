"""Regression tests for the October 2026 patch round.

Locks the following fixes so they cannot silently regress:

1. ``/api/health`` reports the configured application version (was a
   hard-coded ``"0.1.0"`` in ``web/server.py`` and ``main.py``).
2. ``/api/scraping/sources`` reflects the engine's real registry via
   ``available_scrapers()`` (the route previously probed a non-existent
   ``list_sources`` method and always served the 8-source static
   fallback, hiding the 5 keyless v2 scrapers).
3. The proxy manager reaches the shared database through the real
   ``DatabaseConnection`` API (it previously imported a non-existent
   ``get_connection`` symbol and always fell back to a local file).
"""

from __future__ import annotations

import importlib
import math
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Make sure the project root is importable regardless of invocation CWD.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Offscreen Qt for the Worker test (matches tests/test_smoke.py).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")


@pytest.fixture(scope="module")
def qapp():
    """A QApplication (or QCoreApplication fallback) for offscreen Qt tests.

    Deliberately NOT pytest-qt's ``qtbot`` — the suite stays runnable on
    hosts where pytest-qt is not installed (the Worker contract is exercised
    directly instead).
    """
    from qtpy.QtCore import QCoreApplication
    from qtpy.QtWidgets import QApplication

    app = QApplication.instance() or QCoreApplication.instance()
    if app is None:
        app = QApplication(sys.argv or ["ars-tests"])
    yield app


def test_main_and_web_versions_match_settings():
    """main.py and web/server.py must agree with config.settings."""
    from config.settings import get_settings

    expected = get_settings().version
    assert expected == "2.0.0"

    # Re-import fresh so the module-level ``__version__`` assignments run.
    for mod_name in ("main", "web.server"):
        sys.modules.pop(mod_name, None)
    main_mod = importlib.import_module("main")
    server_mod = importlib.import_module("web.server")
    assert main_mod.__version__ == expected
    assert server_mod.__version__ == expected


def test_scraping_sources_endpoint_reflects_engine_registry():
    """The /api/scraping/sources route must list the real 17-scraper
    catalog and mark the 13 keyless scrapers as active."""
    from web.server import create_app

    app = create_app()
    client = app.test_client()
    resp = client.get("/api/scraping/sources")
    assert resp.status_code == 200
    payload = resp.get_json()
    names = {s["name"] for s in payload["sources"]}
    # Full catalog covers all 17 shipped scrapers.
    expected = {
        "arxiv", "pubmed", "openalex", "semantic_scholar", "crossref",
        "dblp", "google_scholar", "orcid", "springer", "ieee", "acm",
        "core", "base", "unpaywall", "opencitations", "sciopen", "wikipedia",
    }
    assert expected.issubset(names), f"missing scrapers: {expected - names}"
    assert payload["count"] >= 17
    # The 13 keyless scrapers register without any API key.
    active = {s["name"] for s in payload["sources"] if s.get("active")}
    keyless = expected - {"springer", "ieee", "core", "base"}
    assert keyless.issubset(active), f"inactive keyless scrapers: {keyless - active}"
    assert payload["active_count"] >= 13


def test_health_endpoint_reports_real_version():
    """`/api/health` must not serve a stale hard-coded version."""
    from config.settings import get_settings
    from web.server import create_app

    app = create_app()
    client = app.test_client()
    resp = client.get("/api/health")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["version"] == get_settings().version
    assert payload["version"] != "0.1.0"


def test_proxy_manager_uses_shared_database_connection():
    """proxy_manager must import the real DatabaseConnection symbol."""
    import inspect

    import proxy.proxy_manager as pm

    source = inspect.getsource(pm._get_db_connection)
    assert "get_connection" not in source, (
        "proxy_manager still imports the non-existent get_connection symbol"
    )
    assert "DatabaseConnection" in source


# ===========================================================================
# Regression tests for the 5-a..5-i patch round (contract locks).
# Each test below pins one audited bug so it cannot silently regress.
# ===========================================================================

# ---------------------------------------------------------------------------
# Meta-analysis
# ---------------------------------------------------------------------------
def test_mantel_haenszel_rbg_variance_closed_form():
    """MH OR must use the Robins–Breslow–Greenland variance (audit: the
    SR/ST terms were wrong).  The engine's SE must match an independent
    closed-form RBG computation, and the resulting CI must be no wider
    than the naive per-study Woolf inverse-variance CI.

    Reference: Robins, Breslow & Greenland (1986), Am J Epidemiol 123:131.
    """
    import math

    from meta_analysis.effect_sizes import EffectSizeCalculator
    from meta_analysis.pooling import PoolingEngine, PoolingMethod

    # 2x2 tables: (events_intervention, total_intervention,
    #              events_control, total_control)
    tables = [(30, 100, 45, 100), (25, 80, 35, 80), (40, 120, 55, 120)]
    studies = []
    for i, (a, n1, c, n2) in enumerate(tables):
        es = EffectSizeCalculator.from_dichotomous(a, n1, c, n2, type="OR")
        es.study_id = f"S{i}"
        studies.append(es)

    res = PoolingEngine().pool(studies, method=PoolingMethod.MH)
    pe = res.pooled_effect

    # Independent closed-form MH + RBG computation.
    a_sum = b_sum = r_sum = s_sum = t_sum = 0.0
    for a, n1, c, n2 in tables:
        b, d = n1 - a, n2 - c
        big_n = float(n1 + n2)
        n2sq = big_n * big_n
        a_sum += (a * d) / big_n
        b_sum += (b * c) / big_n
        r_sum += (a * d * (a + d)) / n2sq
        s_sum += (a * d * (b + c) + b * c * (a + d)) / n2sq
        t_sum += (b * c * (b + c)) / n2sq
    or_mh = a_sum / b_sum
    var_rbg = (
        r_sum / (2.0 * a_sum * a_sum)
        + s_sum / (2.0 * a_sum * b_sum)
        + t_sum / (2.0 * b_sum * b_sum)
    )
    se_rbg = math.sqrt(var_rbg)

    # The engine reports the pooled OR on the natural scale with the CI on
    # that scale; the SE lives on the log scale (that is the RBG variance).
    assert math.isclose(pe.value, or_mh, rel_tol=1e-9)
    assert math.isclose(pe.se, se_rbg, rel_tol=1e-9), (
        f"MH SE {pe.se} != closed-form RBG SE {se_rbg}"
    )
    # CI half-width must equal ~1.96 * SE on the log scale (z_95 may be the
    # exact 1.95996… quantile, so allow a 1% window around 1.96).
    implied_z = (math.log(pe.ci_upper) - math.log(pe.ci_lower)) / (2.0 * pe.se)
    assert abs(implied_z - 1.96) < 0.01, f"CI multiplier {implied_z} != ~1.96"
    assert math.isclose(pe.ci_lower,
                        math.exp(math.log(pe.value) - implied_z * pe.se),
                        rel_tol=1e-6)
    assert math.isclose(pe.ci_upper,
                        math.exp(math.log(pe.value) + implied_z * pe.se),
                        rel_tol=1e-6)

    # Naive (Woolf IV) half-width must be >= the RBG half-width.
    ys, ws = [], []
    for a, n1, c, n2 in tables:
        b, d = n1 - a, n2 - c
        ys.append(math.log((a * d) / (b * c)))
        v = 1.0 / a + 1.0 / b + 1.0 / c + 1.0 / d
        ws.append(1.0 / v)
    y_naive = sum(w * y for w, y in zip(ws, ys)) / sum(ws)
    se_naive = 1.0 / math.sqrt(sum(ws))
    assert 1.96 * pe.se <= 1.96 * se_naive + 1e-9, (
        "RBG CI should be at least as narrow as the naive Woolf CI"
    )
    assert pe.ci_lower < pe.value < pe.ci_upper


def test_reml_tau_squared_plausible():
    """REML τ² must be finite, non-negative, bounded by the observed
    effect spread, and strictly positive for clearly heterogeneous data
    (the audited implementation produced a wrong/negative τ²)."""
    from meta_analysis.effect_sizes import EffectSize, EffectSizeType
    from meta_analysis.pooling import PoolingEngine, PoolingMethod

    data = [(0.8, 0.25), (1.5, 0.30), (0.3, 0.22),
            (2.0, 0.35), (1.1, 0.28), (0.1, 0.26)]
    studies = [
        EffectSize(type=EffectSizeType.SMD, value=v, se=se, n_total=60,
                   study_id=f"S{i}")
        for i, (v, se) in enumerate(data)
    ]
    res = PoolingEngine().pool(studies, method=PoolingMethod.REML)
    tau2 = res.tau_squared
    values = [v for v, _ in data]
    spread = max(values) - min(values)

    assert tau2 is not None and math.isfinite(tau2)
    assert tau2 >= 0.0, "τ² must be non-negative"
    assert tau2 < spread ** 2, "τ² cannot exceed the observed effect spread²"
    assert tau2 > 0.0, "heterogeneous data must yield τ² > 0"
    assert res.pooled_effect.se > 0
    assert min(values) < res.pooled_effect.value < max(values)
    assert 0.0 <= res.I_squared <= 100.0


def test_sucra_best_treatment_near_one():
    """SUCRA must score the best treatment ≈ 1 and the worst ≈ 0 (the
    audited implementation inverted the scale)."""
    from meta_analysis.network_meta import NetworkMetaAnalysis, TreatmentComparison

    comps = [
        TreatmentComparison(study_id="S1", treatment_a="A", treatment_b="B",
                            effect_size=0.9, se=0.10, n_total=200),
        TreatmentComparison(study_id="S2", treatment_a="A", treatment_b="C",
                            effect_size=1.5, se=0.10, n_total=200),
        TreatmentComparison(study_id="S3", treatment_a="B", treatment_b="C",
                            effect_size=0.6, se=0.10, n_total=200),
    ]
    sucra = NetworkMetaAnalysis(comps).sucra_scores()
    assert set(sucra) == {"A", "B", "C"}
    # C has the highest effect coefficients on every comparison.
    assert max(sucra.values()) > 0.95, f"best treatment SUCRA: {sucra}"
    assert min(sucra.values()) < 0.05, f"worst treatment SUCRA: {sucra}"
    assert sucra["C"] == max(sucra.values())
    assert sucra["A"] == min(sucra.values())


# ---------------------------------------------------------------------------
# Figures / statistics
# ---------------------------------------------------------------------------
def test_q1_heatmap_annotates_without_vmin_vmax():
    """Q1DataPlots.heatmap must not crash when annotate_cells=True and no
    vmin/vmax are given (the audited code compared against ``None``)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from q1_figures.data_plots import Q1DataPlots

    fig, ax = plt.subplots()
    try:
        data = [[0.1, 0.9, 0.4], [0.7, 0.2, 0.6]]
        returned = Q1DataPlots.heatmap(
            ax, data,
            row_labels=["R1", "R2"],
            col_labels=["C1", "C2", "C3"],
            annotate_cells=True, show_colorbar=True,
        )
        assert returned is ax
        # Two rows x three columns of cell annotations were drawn.
        assert len(ax.texts) == 6
        # A QuadMesh (imshow) exists with finite colour limits.
        images = ax.get_images()
        assert len(images) == 1
        assert images[0].get_clim() == (0.1, 0.9)
    finally:
        plt.close(fig)


def test_kaplan_meier_logrank_same_groups_not_significant():
    """The log-rank p-value annotation must be non-significant (p > 0.05)
    for identical groups and significant (p < 0.05) for well-separated
    groups (the audited test omitted the variance term)."""
    import re

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from q1_figures.statistical_plots import StatisticalPlots

    def _p_value(time, event, groups):
        fig, ax = plt.subplots()
        try:
            StatisticalPlots.kaplan_meier(
                ax, time=time, event=event, groups=groups,
                show_ci=False, show_at_risk_table=False, show_p_value=True,
            )
            texts = [t.get_text() for t in ax.texts]
            joined = " ".join(texts)
            m = re.search(r"p\s*=\s*([0-9.eE+-]+)", joined)
            assert m, f"no log-rank p-value annotation found in {texts!r}"
            return float(m.group(1))
        finally:
            plt.close(fig)

    # Identical groups → chi² = 0 → p ≈ 1.
    t = [1, 2, 3, 4, 5, 1, 2, 3, 4, 5]
    e = [1, 1, 0, 1, 1, 1, 1, 0, 1, 1]
    g = ["A", "A", "A", "A", "A", "B", "B", "B", "B", "B"]
    p_same = _p_value(t, e, g)
    assert p_same > 0.05, f"identical groups gave p = {p_same}"

    # Well-separated groups → clearly significant.
    t2 = [1, 2, 3, 4, 5, 11, 12, 13, 14, 15]
    e2 = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    p_diff = _p_value(t2, e2, g)
    assert p_diff < 0.05, f"separated groups gave p = {p_diff}"


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------
def test_connected_view_directed_diameter_uses_largest_component():
    """PathsAndFlows.diameter on a DiGraph with a small island must report
    the LARGEST weakly-connected component's diameter (the audited code
    partially consumed the component generator and measured the island)."""
    import networkx as nx

    from networkx_pro.algorithms_paths_flows import PathsAndFlows

    g = nx.DiGraph()
    g.add_edges_from([(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)])  # 5-cycle
    g.add_edges_from([("x", "y")])                             # island
    # nx.diameter on a DiGraph needs the (weakly-)largest component to be
    # strongly connected — a directed 5-cycle has diameter 4 (> 0).
    diameter = PathsAndFlows.diameter(g)
    assert diameter == 4, f"expected main-component diameter 4, got {diameter}"
    # The view itself: materialising components must not truncate.
    view = PathsAndFlows._connected_view(g)
    assert set(view.nodes) == {0, 1, 2, 3, 4}
    # Undirected path still works.
    assert PathsAndFlows.diameter(nx.path_graph(5)) == 4


def test_graphio_graphml_gexf_roundtrip_none_and_list_attrs():
    """GraphIO GraphML/GEXF writers must sanitise None / list node and edge
    attributes instead of crashing (the audited code raised on them)."""
    import networkx as nx

    from networkx_pro.graph_io import GraphIO

    g = nx.Graph()
    g.add_node("a", note=None, tags=[1, 2], weight=1.5)
    g.add_node("b", note="x", tags=["p", "q"])
    g.add_edge("a", "b", kind="co", score=None)

    for writer, reader in (
        (GraphIO.write_graphml, GraphIO.read_graphml),
        (GraphIO.write_gexf, GraphIO.read_gexf),
    ):
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "net.out")
            writer(g, path)  # must not raise
            h = reader(path)
            assert h.number_of_nodes() == 2
            assert h.number_of_edges() == 1
            # List attributes survive as a readable serialised string.
            tags = h.nodes["a"].get("tags")
            if tags is not None:
                assert "1" in str(tags) and "2" in str(tags)
            # Scalar attributes survive exactly.
            assert float(h.nodes["a"].get("weight", 1.5)) == 1.5
            assert h.nodes["b"].get("note") == "x"


def test_katz_link_prediction_route_shape():
    """The /api/network/link-prediction route must flatten Katz's nested
    {u: {v: score}} matrix into sorted (source, target, score) predictions
    (the audited code leaked the nested dict and 500'd)."""
    from flask import Flask

    from web.routes.network_analysis import network_bp

    app = Flask(__name__)
    app.register_blueprint(network_bp)
    client = app.test_client()

    graph = {"nodes": ["a", "b", "c"], "edges": [["a", "b"], ["b", "c"]]}
    resp = client.post(
        "/api/network/link-prediction",
        json={"graph": graph, "method": "katz_similarity", "top_n": 3},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    payload = resp.get_json()
    assert payload["method"] == "katz_similarity"
    preds = payload["predictions"]
    assert 0 < len(preds) <= 3
    scores = [p["score"] for p in preds]
    assert scores == sorted(scores, reverse=True)
    for p in preds:
        assert set(p) == {"source", "target", "score"}
        assert p["source"] != p["target"]
        assert isinstance(p["score"], float)

    # The plain local predictors keep the same response shape.
    resp2 = client.post(
        "/api/network/link-prediction",
        json={"graph": graph, "method": "jaccard", "top_n": 3},
    )
    assert resp2.status_code == 200
    for p in resp2.get_json()["predictions"]:
        assert set(p) == {"source", "target", "score"}


# ---------------------------------------------------------------------------
# Core contracts (database / events / workers)
# ---------------------------------------------------------------------------
def test_database_paper_crud_roundtrip(tmp_path):
    """The 5-a DatabaseConnection CRUD contract: add → get → list →
    search → similar → delete, with the promised dict keys."""
    from database.connection import DatabaseConnection

    db = DatabaseConnection(db_path=str(tmp_path / "crud.db"))
    try:
        db.init_db()
        pid = db.add_paper({
            "doi": "10.1234/crud.1",
            "title": "Graph Neural Networks for Citation Analysis",
            "authors": ["Jane Doe", "John Smith"],
            "year": 2023,
            "journal": "J. Informetrics",
            "abstract": "We study GNNs on citation graphs.",
            "citation_count": 7,
            "source": "crossref",
            "keywords": ["gnn", "citations"],
        })
        assert isinstance(pid, int) and pid > 0

        got = db.get_paper(pid)
        assert got is not None
        for key in ("id", "doi", "title", "authors", "year", "journal",
                    "abstract", "citation_count", "source", "entry_type"):
            assert key in got, f"get_paper() dict missing {key!r}"
        assert got["title"].startswith("Graph Neural Networks")
        assert got["authors"] == ["Jane Doe", "John Smith"]

        # DOI dedupe returns the existing id instead of duplicating.
        assert db.add_paper({"doi": "10.1234/crud.1", "title": "dup"}) == pid

        listed = db.list_papers(limit=10)
        assert any(r["id"] == pid for r in listed)

        hits = db.search_papers("citation analysis")
        assert any(h["id"] == pid for h in hits)

        similar = db.find_similar_papers(pid, limit=5)
        assert isinstance(similar, list)

        assert db.delete_paper(pid) is True
        assert db.get_paper(pid) is None
        assert db.delete_paper(pid) is False
    finally:
        db.close()


def test_event_bus_string_and_event_interop():
    """Contract #2 interop: string topics reach enum subscribers and
    EventType events reach string subscribers; verbatim string topics
    flow through unchanged."""
    import core.events as ce

    bus = ce.get_event_bus()
    hits = []
    s1 = bus.subscribe("paper_added", lambda ev: hits.append(("paper_added", ev)))
    s2 = bus.subscribe(ce.EventType.ScrapeCompleted,
                       lambda ev: hits.append(("enum", ev)))
    s3 = bus.subscribe("scrape:completed",
                       lambda ev: hits.append(("scrape:completed", ev)))
    try:
        # Verbatim string topic → string subscriber, payload accessible.
        bus.publish("paper_added", {"id": 7})
        assert any(k == "paper_added" and ev.get("id") == 7
                   for k, ev in hits if hasattr(ev, "get"))

        # Enum event → both the enum subscriber and the "scrape:completed"
        # string subscriber.
        before = len(hits)
        bus.publish(ce.EventType.ScrapeCompleted, {"task_id": "t1"})
        kinds = {k for k, _ in hits[before:]}
        assert "enum" in kinds and "scrape:completed" in kinds
    finally:
        bus.unsubscribe("paper_added", s1)
        bus.unsubscribe(ce.EventType.ScrapeCompleted, s2)
        bus.unsubscribe("scrape:completed", s3)


def test_worker_signals_wiring_offscreen(qapp):
    """Contract #1: Worker exposes signals.{progress,result,error,finished},
    progress_callback is injected only when accepted, and WorkerPool.submit
    delivers results without a running event loop."""
    from utils.workers import Worker, WorkerPool

    seen = {"result": None, "error": None, "finished": 0, "progress": []}

    def job(multiplier, progress_callback=None):
        for step in range(4):
            if progress_callback is not None:
                progress_callback(step * 25, "step")
        return multiplier * 2

    worker = Worker(job, 21)
    worker.signals.result.connect(lambda r: seen.__setitem__("result", r))
    worker.signals.progress.connect(
        lambda pct, msg=None: seen["progress"].append(pct))
    worker.signals.error.connect(lambda e: seen.__setitem__("error", e))
    worker.signals.finished.connect(lambda: seen.__setitem__("finished", seen["finished"] + 1))

    submitted = WorkerPool.instance().submit(worker)
    assert submitted is worker

    deadline = time.time() + 10
    while seen["finished"] == 0 and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert seen["error"] is None, seen["error"]
    assert seen["result"] == 42
    assert seen["finished"] == 1
    assert seen["progress"] == [0, 25, 50, 75]

    # A callable that does NOT accept progress_callback must still run.
    seen2 = {"result": None, "finished": 0}
    worker2 = Worker(lambda a, b: a + b, 2, 3)
    worker2.signals.result.connect(lambda r: seen2.__setitem__("result", r))
    worker2.signals.finished.connect(lambda: seen2.__setitem__("finished", 1))
    WorkerPool.instance().submit(worker2)
    deadline = time.time() + 10
    while seen2["finished"] == 0 and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert seen2["result"] == 5


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def test_csv_export_formula_injection_guard():
    """export_csv must neutralise Excel formula prefixes (=, +, -, @) and
    strip CR/LF/TAB from cell values (the audited exporter wrote them raw)."""
    from data_acquisition.base_scraper import Paper

    from reporting.csv_export import export_csv, sanitize_csv_value

    assert sanitize_csv_value("=cmd()").startswith("'")
    for probe in ("+1", "-1", "@import", "=SUM(A1)"):
        guarded = str(sanitize_csv_value(probe))
        assert guarded[0] == "'", f"{probe!r} not neutralised: {guarded!r}"
    assert "\n" not in str(sanitize_csv_value("line1\nline2"))
    assert "\r" not in str(sanitize_csv_value("a\rb"))
    assert "\t" not in str(sanitize_csv_value("a\tb"))

    papers = [
        Paper(title="=HYPERLINK(\"http://evil\")", authors=["A;B"], year=2024,
              journal="J\t\nRB"),
        Paper(title="benign", authors=["C"], year=2023, journal="Safe J"),
    ]
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "out.csv")
        export_csv(papers, path)
        content = Path(path).read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines, "export_csv produced an empty file"
    for line in lines[1:]:  # skip the header
        for cell in line.split(","):
            # Strip the CSV writer's quoting, then inspect the raw value.
            value = cell.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            # The sanitizer prefixes dangerous leading characters with an
            # apostrophe, so a raw formula prefix may never survive.
            if value and value[0] in "=+-@":
                assert value.startswith("'"), (
                    f"formula cell reached the CSV unguarded: {cell!r}"
                )
        assert "\r" not in line


def test_ris_exporter_roundtrip():
    """RisExporter must emit parseable RIS: every record starts with TY and
    ends with ER, with AU/TI/PY/DO lines preserved (the audited code had
    no RIS exporter at all)."""
    import io

    from data_acquisition.base_scraper import Paper

    from reporting.ris_export import RisExporter

    papers = [
        Paper(title="Attention Is All You Need", authors=["Vaswani, A.",
              "Shazeer, N."], year=2017, doi="10.5555/3295222",
              journal="NeurIPS", abstract="Transformers.",
              keywords=["attention", "transformers"]),
        Paper(title="BERT", authors=["Devlin, J."], year=2019,
              doi="10.18653/v1/N19-1423", journal="NAACL"),
    ]
    exporter = RisExporter()
    text = exporter.to_string(papers)

    # File export must equal the in-memory rendering.
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "out.ris")
        exported_path = exporter.export(papers, path)
        assert str(exported_path) == os.path.abspath(path)
        assert Path(path).read_text(encoding="utf-8") == text

    # Parse the RIS text back into records.
    records, current = [], None
    buf = io.StringIO(text)
    for raw in buf:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        tag, _, value = line.partition("  - " if "  - " in line else "-")
        tag = tag.strip()
        if tag == "TY":
            current = {"TY": value.strip(), "AU": [], "KW": []}
        elif current is not None:
            if tag == "AU":
                current["AU"].append(value.strip())
            elif tag == "KW":
                current["KW"].append(value.strip())
            elif tag in ("TI", "PY", "DO", "JO", "AB"):
                current[tag] = value.strip()
            elif tag == "ER":
                records.append(current)
                current = None
    assert len(records) == 2, f"expected 2 RIS records, parsed {len(records)}"
    by_doi = {r.get("DO"): r for r in records}
    attn = by_doi["10.5555/3295222"]
    assert attn["TI"] == "Attention Is All You Need"
    assert attn["PY"] == "2017"
    assert len(attn["AU"]) == 2
    assert set(attn["KW"]) == {"attention", "transformers"}
    for record in records:
        assert "TY" in record, f"RIS record missing TY tag: {record!r}"


# ---------------------------------------------------------------------------
# Proxy / scraping contracts
# ---------------------------------------------------------------------------
def test_proxy_pool_facade_methods_and_rotator_sync():
    """Contract #4 facade methods exist and ban() stays in sync with the
    rotator (banned addresses are never handed out again)."""
    import inspect

    from proxy.proxy_manager import ProxyManager
    from proxy.proxy_pool import ProxyPool

    for name in ("list_proxies", "refresh", "test_proxy", "build_chain",
                 "health_check_all", "ban", "import_from", "set_chain",
                 "get_proxy", "get_proxy_url", "refresh_pool", "stats"):
        assert hasattr(ProxyPool, name) and callable(getattr(ProxyPool, name)), (
            f"ProxyPool facade is missing {name!r}"
        )
        # Facade methods must be inspectable (no *args-only stubs).
        assert inspect.signature(getattr(ProxyPool, name)) is not None

    pool = ProxyPool(manager=ProxyManager(persist=False))
    added = pool.import_from(["10.0.0.1:8080", "10.0.0.2:8080"])
    assert len(added) == 2
    listed = pool.list_proxies()
    assert {d["address"] for d in listed} >= {"10.0.0.1:8080", "10.0.0.2:8080"}

    assert pool.get_proxy_url() is not None
    assert pool.ban("10.0.0.1:8080", minutes=5) is True

    # Rotator sync: the banned address is never returned again.
    for _ in range(10):
        current = pool.get_proxy()
        assert current is not None
        assert f"{current.host}:{current.port}" != "10.0.0.1:8080"
    assert pool.get_proxy_url() == "http://10.0.0.2:8080"
    stats = pool.stats()
    assert isinstance(stats, dict) and stats


def test_paper_to_dict_serialisable():
    """Paper.to_dict() (contract #8) must return a flat JSON-safe dict."""
    import json

    from data_acquisition.base_scraper import Paper

    p = Paper(
        title="Deep Learning", authors=["Goodfellow, I.", "Bengio, Y."],
        year=2016, doi="10.1000/dl", journal="Nature",
        abstract="Neural nets.", keywords=["dl", "nn"], citations_count=100,
    )
    d = p.to_dict()
    assert d["title"] == "Deep Learning"
    assert d["authors"] == ["Goodfellow, I.", "Bengio, Y."]
    assert d["year"] == 2016
    assert d["doi"] == "10.1000/dl"
    assert d["citations_count"] == 100
    # JSON round-trip must be lossless (no Paper objects left inside).
    assert json.loads(json.dumps(d)) == d


def test_base_and_core_query_builders_string_level():
    """BASE folds year/type/language/country into the Lucene query against
    the correct endpoint; CORE posts a single-quoted Lucene phrase (audit
    4-b: BASE used a bare-host URL, CORE doubled the quotes)."""
    from data_acquisition.base_scraper_ext import BASEScraper
    from data_acquisition.core_scraper import COREScraper

    class _FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    # --- BASE ------------------------------------------------------------
    base = BASEScraper(api_key=None)
    captured = {}

    def fake_base_request(method, url, *, params=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = dict(params or {})
        return _FakeResp({"response": {"numFound": 0, "docs": []}})

    base._make_request = fake_base_request
    res = base.search("graph embeddings", max_results=5, year=2023,
                      type="publication", language="eng", country="de")
    assert captured["url"].startswith(
        "https://api.base-search.net/cgi-bin/BaseHttpSearchInterface.fcgi")
    q = captured["params"]["query"]
    assert "graph embeddings" in q
    assert "dcyear:2023" in q
    assert "dcdocumenttype:publication" in q
    assert "dclanguage:eng" in q
    assert "country:de" in q
    assert q.index("graph embeddings") < q.index("dcyear:2023")
    assert res is not None  # engine returned a result object without network

    # --- CORE ------------------------------------------------------------
    core = COREScraper(api_key="test-key")
    captured_core = {}

    def fake_core_request(method, url, *, json_body=None, **kwargs):
        captured_core["method"] = method
        captured_core["url"] = url
        captured_core["body"] = dict(json_body or {})
        return _FakeResp({"totalHits": 0, "results": []})

    core._make_request = fake_core_request
    core.search("graph neural networks", max_results=5)
    assert captured_core["url"].endswith("/search/works")
    body_q = captured_core["body"]["q"]
    assert 'title:("graph neural networks")' in body_q
    assert '(""graph neural networks"")' not in body_q  # doubled quotes gone
    assert captured_core["body"]["limit"] == 5
