# Frequently Asked Questions

> **Companion docs:** [INSTALL.md](INSTALL.md) for install help,
> [user_guide.md](user_guide.md) for daily usage,
> [SECURITY.md](SECURITY.md) for security topics.

A growing collection of answers to questions we get asked often. If
your question isn't here, search the
[GitHub issues](https://github.com/academic-research-suite/academic_research_suite/issues)
or open a new one.

---

## Table of Contents

- [Setup](#setup)
- [Scraping](#scraping)
- [Proxy](#proxy)
- [AI](#ai)
- [Reports](#reports)
- [Performance](#performance)
- [Troubleshooting](#troubleshooting)

---

## Setup

### Q1. What Python versions does ARS support?

Python 3.10, 3.11, and 3.12. Python 3.13 should work but isn't
formally tested. Python 3.9 and earlier are NOT supported — the
codebase uses `match` statements, `from __future__ import
annotations` patterns, and PEP 604 union syntax (`X | Y`).

### Q2. Do I need PyQt5 installed, or can I use PySide2 / PySide6?

PyQt5 is the canonical binding and the one we test against.
PySide2 works via the `qtpy` shim — install it instead of PyQt5
and everything else stays the same. PySide6 / Qt 6 is on the
[v2.0.0 roadmap](../README.md#roadmap).

### Q3. Can I run ARS without a display (headless server)?

Yes. Two options:

1. **Web server mode only** — `python main.py --web` doesn't
   require Qt at all if you never touch the desktop UI.
2. **Offscreen Qt** — set `QT_QPA_PLATFORM=offscreen` so PyQt5
   creates a virtual display surface. The desktop UI code runs but
   never paints to a real window. Used by `tests/test_smoke.py`
   and `scripts/smoke_test.sh`.

### Q4. Where does ARS store my data?

Everything lives under the project directory by default:

```text
academic_research_suite/
├── data/
│   ├── ars.db               SQLite database (papers, projects, ...)
│   ├── ars.db-wal           WAL journal (don't delete while running)
│   ├── ars.db-shm           Shared memory (don't delete while running)
│   ├── cache/
│   │   └── cache.db         HTTP / scraper cache
│   ├── chroma/              ChromaDB vector store
│   └── projects/<id>/       Per-project chat history, snapshots, etc.
└── logs/
    └── ars.log              Rotating log (2 MB × 5 backups)
```

Override any of these via `config/secrets.yaml` or `ARS_*` env
vars (see [Configuration Reference in README](../README.md#configuration-reference)).

### Q5. Does ARS send telemetry?

**No.** ARS has zero telemetry, zero auto-update checks, zero
"phone home" behaviour. The only outbound network calls are the
ones you explicitly trigger via scraping or AI chat. The
Settings → Advanced → Telemetry opt-out checkbox exists only to
prevent future opt-in telemetry from being added without your
consent.

---

## Scraping

### Q6. Which sources can ARS scrape?

Eight sources ship out of the box:

| Source | API key required? | Notes |
|---|---|---|
| arXiv | No | Atom XML; ~0.33 req/s polite limit. |
| PubMed | No (email optional) | NCBI E-utilities; ~3 req/s. |
| OpenAlex | No | REST; ~10 req/s polite pool. |
| Semantic Scholar | No (key raises limit) | Bulk embeddings endpoint. |
| Crossref | No (mailto polite) | ~50 req/s polite pool. |
| DBLP | No | CS bibliography. |
| Google Scholar | No | Selenium + Chrome; captchas likely. |
| ORCID | No | Author lookup by ORCID iD. |

### Q7. Why is my Google Scholar scrape returning empty results?

Google aggressively throttles and captchas automated access. ARS
mitigates with proxies + rotation + backoff, but you should
expect partial failures. Mitigations:

1. Enable proxies (Settings → Proxy → Enable).
2. Lower the per-source rate limit (Settings → Scraping → rate
   limit / max concurrent).
3. Use the Crossref scraper instead — it covers the same
   DOI-identified corpus without captchas.

### Q8. How do I search multiple sources at once?

Use the **Search** panel — tick the checkboxes next to each
source. Under the hood, `ScrapingEngine.search_all(query,
sources=[...])` fans the query out in parallel via a
`ThreadPoolExecutor` and merges + dedups the results.

```python
from data_acquisition.scraping_engine import ScrapingEngine
from data_acquisition.arxiv_scraper import ArxivScraper
from data_acquisition.crossref_scraper import CrossrefScraper

engine = ScrapingEngine()
engine.register_scraper("arxiv", ArxivScraper())
engine.register_scraper("crossref", CrossrefScraper())
result = engine.search_all("graph neural networks",
                           sources=["arxiv", "crossref"])
```

### Q9. Can I cache scraper responses?

Yes — caching is on by default via `utils/cache.py::Cache` (SQLite
at `data/cache/cache.db`, WAL mode). Every `BaseScraper._make_request`
checks the cache before issuing an HTTP call. Set
`cache_key=None` or `use_cache=False` to bypass for a specific
call. The cache TTL is configurable per-entry; clear it via
Settings → Database → Clear Cache.

### Q10. Why does ARS say "No scrapers registered"?

You called `ScrapingEngine()` without registering any scrapers
first. Either register scrapers manually (`engine.register_scraper("arxiv",
ArxivScraper())`) or use the `ServerState.scraping_engine` lazy
property which wires up all eight defaults automatically.

---

## Proxy

### Q11. Are the free proxies ARS scrapes safe to use?

**No, not for sensitive traffic.** Free proxies can see and modify
your HTTP traffic. ARS mitigates by:

- Using HTTPS (TLS) for all upstream scraper calls — the proxy
  sees only the TLS handshake, not the payload.
- Wrapping the TLS context with `ssl.create_default_context`
  (verifies the upstream certificate).

For non-HTTP traffic or for HTTP-only sources, do not use free
proxies. Use your own paid proxies via the Import button.

### Q12. How do I bring my own proxies?

Three ways:

1. **Proxy panel → Import** — upload a TXT (one `host:port` per
   line), JSON, or CSV file. The pool auto-detects the format by
   extension.
2. **REST API**:
   ```bash
   curl -X POST http://127.0.0.1:8765/api/proxy/ \
     -H 'Content-Type: application/json' \
     -d '{"host": "1.2.3.4", "port": 8080, "protocol": "http"}'
   ```
3. **Programmatic**:
   ```python
   from proxy import ProxyManager, Proxy
   pm = ProxyManager(persist=False)
   pm.add_proxy(Proxy(host="1.2.3.4", port=8080, protocol="http"))
   ```

### Q13. What's a proxy chain and when would I use one?

A proxy chain routes your traffic through N proxies in series
(`you → proxy1 → proxy2 → ... → target`). Each hop only sees the
previous hop's IP. Use chains for:

- Maximizing anonymity when scraping captchy sources.
- Routing through jurisdictions where a specific source is
  geo-blocked.

ARS supports multi-hop SOCKS4 / SOCKS5 / HTTP-CONNECT chains via
`proxy/proxy_chain.py`. The handshakes are implemented from
scratch (RFC 1928 for SOCKS5, RFC 1929 for user/pass, etc.).

### Q14. The proxy pool comes back empty. What's wrong?

Likely causes:

1. **Firewall blocks the free-proxy sources.** Test with:
   `curl -I https://www.proxy-list.download/api/v1/get?type=http`.
2. **Geo-restriction** — some sources return empty lists for
   non-US / non-EU IPs. Try a paid proxy or VPN.
3. **All scraped proxies are unhealthy.** Set the test URL to
   something you know is reachable
   (`https://httpbin.org/ip` is the default).

---

## AI

### Q15. Do I need an OpenAI / Anthropic API key?

**No.** ARS ships with an offline echo backend
(`LLMClient(provider="none")`). It returns a deterministic
SHA-256-hash response so the entire suite runs without network or
API keys. Use it for testing, demos, or air-gapped environments.

For real LLM behaviour:

- **Ollama** — install locally, no API key, fully private.
- **OpenAI** — set `ARS_AI_API_KEY`.
- **Anthropic** — set `ARS_AI_API_KEY`.

### Q16. How does RAG work in ARS?

Retrieval-Augmented Generation:

1. Every paper's abstract is embedded via the active LLM provider
   (or the deterministic SHA-256 fallback when `provider=none`).
2. Embeddings are stored in ChromaDB at `data/chroma/`.
3. When you send a chat message with **Use RAG** enabled, ARS
   embeds your message, finds the top-k nearest papers in the
   vector store, and prepends their abstracts to the LLM prompt.
4. The LLM's response cites those papers as clickable anchors in
   the chat UI.

### Q17. Can I use a model that isn't in the default list?

Yes. The model dropdown is just a UI suggestion; you can type any
model string into `config/secrets.yaml`:

```yaml
ai_provider: "openai"
ai_model: "gpt-4o-2024-08-06"   # any valid model string
```

For Ollama, `ollama pull <model>` first, then set `ai_model:
"<model>"`.

### Q18. My chat history is huge. Can I clear it?

Yes. The **Clear History** button at the top of the AI Chat panel
wipes the conversation. The history file at
`data/projects/<id>/chat_history.json` is also deleted. Snapshot
files are NOT affected.

---

## Reports

### Q19. Which report format should I use?

| Format | Best for |
|---|---|
| PDF | Sharing with non-ARS users, formal submissions, archival. |
| DOCX | Further editing in Microsoft Word or Google Docs. |
| PPTX | Conference presentations, group meetings. |
| BibTeX | Importing into LaTeX bibliographies. |
| CSV / TSV / XLSX | Data analysis in pandas, R, Excel. |

### Q20. My PDF has Chinese characters showing as squares. How do I fix it?

Install a CJK sans-serif font and clear the matplotlib cache:

```bash
# Linux
sudo apt install fonts-noto-cjk
rm -rf ~/.cache/matplotlib

# macOS
brew install font-noto-sans-cjk-sc
rm -rf ~/.cache/matplotlib   # or ~/Library/Caches/matplotlib

# Windows — install Noto Sans SC via Font Book or:
# https://fonts.google.com/noto/specimen/Noto+Sans+SC
```

ARS's `chart_generator.py` already sets
`font.sans-serif = ['Noto Sans SC', 'DejaVu Sans', 'WenQuanYi Zen
Hei', 'LXGW WenKai']` and `axes.unicode_minus = False`. The
squares mean none of those fonts were found.

### Q21. Can I customise the report layout?

Not yet — v1.0.0 ships fixed layouts per format. A Jinja2-based
template system is on the [v1.2.0 roadmap](../README.md#roadmap).

---

## Performance

### Q22. ARS feels slow when scraping. How do I speed it up?

Most scraping time is dominated by the upstream API latency, not
by ARS. To improve throughput:

1. Increase `scraping_max_concurrent` (default 4) — but
   don't exceed your CPU core count.
2. Cache aggressively — keep `cache.db` between runs.
3. Use proxies for sources that rate-limit by IP
   (Google Scholar, Semantic Scholar without key).
4. For arXiv specifically, stay at ≤0.33 req/s — going faster
   triggers HTTP 429s that slow you down.

### Q23. SQLite feels slow with >100k papers. Should I switch to Postgres?

Probably not. SQLite with WAL journaling handles 10⁶ rows
comfortably. The slow path is usually the FTS5 query — verify
with:

```bash
sqlite3 data/ars.db "EXPLAIN QUERY PLAN SELECT * FROM papers_fts WHERE papers_fts MATCH 'transformer';"
```

If you genuinely need multi-user access, switch to Postgres via
`ARS_DATABASE_URL=postgresql+psycopg2://...`. The full schema
auto-creates on first run.

### Q24. ChromaDB is consuming too much disk space.

ChromaDB stores one float32 vector per paper. For 1000 papers
with 384-dim embeddings, that's ~1.5 MB — small. For 100k papers
it's ~150 MB. To reduce:

1. Use a smaller embedding model (e.g. `all-MiniLM-L6-v2`
   produces 384-dim vectors; `bge-small-en` produces 384-dim too).
2. Periodically run `VectorStore.clear()` and re-index only the
   papers you actually need for RAG.
3. Drop the vector store entirely if you don't use RAG — set
   `ai_provider: "none"` and ARS skips the embedding step.

---

## Troubleshooting

### Q25. I see "service_unavailable" on a /api/... endpoint.

The endpoint's backend module failed to initialize. The
`/api/health` endpoint tells you which:

```bash
curl http://127.0.0.1:8765/api/health | jq .modules
```

```json
{
  "database": true,
  "project_manager": true,
  "scraping_engine": false,        // ← broken
  "proxy_pool": true,
  "chat_engine": true,
  "event_bus": true
}
```

Then check `logs/ars.log` for the import error. Usually it's a
missing optional dependency — install via `pip install <package>`
and restart.

### Q26. The desktop UI freezes during long scrapes.

You're probably calling the scraper on the Qt main thread. Wrap
the call in a `Worker` so it runs on the `WorkerPool`:

```python
from utils import run_in_background
result = run_in_background(engine.search_all, "query",
                           on_done=lambda r: print(len(r.papers)))
```

The Search panel already does this — if you're writing custom
code that calls scrapers directly, follow the same pattern.

### Q27. My database is locked. What do I do?

```text
sqlite3.OperationalError: database is locked
```

Another process (often a previous ARS instance that crashed)
holds an exclusive lock on `data/ars.db`. Fix:

```bash
# Find the locker (Linux / macOS)
lsof data/ars.db
# Kill the offending PID, then:
rm -f data/ars.db-wal data/ars.db-shm
python main.py
```

For顽固 cases, `python main.py --reset-db` recreates the schema
(you lose all data).

### Q28. How do I reset ARS to a clean state?

```bash
# Stop ARS if running
python main.py --reset-db        # wipes the SQLite DB
rm -rf data/chroma                # wipes the vector store
rm -rf data/cache                 # wipes the HTTP cache
rm -rf data/projects              # wipes per-project chat / snapshots
rm -f logs/ars.log*               # wipes the logs
python main.py
```

This is equivalent to a fresh install — the welcome screen
reappears.

### Q29. The web server says "address already in use".

Another process is bound to port 8765. Either kill it:

```bash
lsof -i :8765    # find PID
kill <PID>
```

or use a different port:

```bash
python main.py --web --port 9000
```

### Q30. ARS crashes on launch with "Could not load the Qt platform plugin".

Most common on Linux. The fix:

```bash
# Install the X11 xcb plugin dependencies
sudo apt install libxcb-xinerama0 libxcb-icccm4 libxcb-image0 \
                 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
                 libxcb-xkb1 libxkbcommon-x11-0 libdbus-1-3

# Or run in offscreen mode (no display needed)
QT_QPA_PLATFORM=offscreen python main.py

# Or run in web-only mode (no Qt at all)
python main.py --web
```

---

*If your question isn't answered here, please open an issue at
<https://github.com/academic-research-suite/academic_research_suite/issues>
— and if you fix it yourself, contribute the answer back via a
PR to this file.*

---

## v2.0.0 Features

### Q31. How do I run a Cochrane-style systematic review end-to-end?

Use the `systematic_review/` package as a pipeline. Start with the
`ProtocolTemplateLibrary` to build a Cochrane protocol, scrape candidate
records via `ScrapingEngine.search_all()`, import them into a
`ScreeningManager`, screen title/abstract and full-text with two
reviewers, then run `CochraneRoB2.assess()` per included study. Finally,
call `PRISMAIntegration().generate_flow_diagram(mgr, "flow.pdf")` and
`PRISMAIntegration().generate_checklist(mgr, "checklist.pdf")` to produce
the PRISMA-compliant outputs.

```python
from systematic_review.screening import ScreeningManager
from systematic_review.risk_of_bias import CochraneRoB2
from systematic_review.prisma_integration import PRISMAIntegration
from data_acquisition.scraping_engine import ScrapingEngine

mgr = ScreeningManager()
mgr.load_from_search(ScrapingEngine().search_all("query", sources=["pubmed"]))
mgr.auto_dedup()
# ... screen records ...
rob = CochraneRoB2().assess({"study_id": "S1", "randomization": "low", ...})
PRISMAIntegration().generate_flow_diagram(mgr, "flow.pdf")
PRISMAIntegration().generate_checklist(mgr, "checklist.pdf")
```

### Q32. How do I compute the e-index or hm-index?

`bibliometrics.pop_indices.PoPIndices` computes both. The e-index
complements the h-index by capturing the excess citations in the
h-core (papers with ≥ h citations). The hm-index (multi-authored h)
adjusts for co-authorship by dividing each paper's citations by its
author count before computing h.

```python
from bibliometrics.pop_indices import PoPIndices
citations = [42, 28, 19, 15, 11, 8, 5, 3, 2, 1]
author_counts = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]  # authors per paper
pop = PoPIndices()
print("e-index:", pop.e_index(citations))                     # ~9.17
print("hm-index:", pop.multi_authored_h_index(citations, author_counts))
print("All indices:", pop.compute_all(citations, author_counts=author_counts))
```

### Q33. How do I generate a PRISMA flow diagram?

Use `prisma.flow_diagram.PRISMAFlowGenerator`. Construct a
`PRISMAStageCounts` dataclass with the 16 official stage counts, then
call one of `render_pdf`, `render_png`, `render_svg`, `render_html`,
or `to_dot`.

```python
from prisma.flow_diagram import PRISMAFlowGenerator, PRISMAStageCounts
counts = PRISMAStageCounts(
    n_records_databases=1248, n_duplicates_removed=180,
    n_records_screened=1105, n_full_text_assessed=213,
    n_full_text_excluded=87,
    n_excluded_with_reasons=[("Wrong outcome", 31), ("Wrong design", 22)],
    n_studies_included_qualitative=126,
    n_studies_included_quantitative=98,
)
gen = PRISMAFlowGenerator(counts, title="My SR", extension="standard")
gen.render_pdf("prisma_flow.pdf", style="bmj")
```

### Q34. How do I run a DerSimonian-Laird meta-analysis?

Use `meta_analysis.pooling.PoolingEngine.pool()` with
`method=PoolingMethod.DL`. The DL estimator is the default random-effects
method — a closed-form two-step estimator that computes τ² from the
Cochran Q excess, then re-weights studies by inverse variance plus τ².

```python
from meta_analysis.effect_sizes import EffectSizeCalculator
from meta_analysis.pooling import PoolingEngine, PoolingMethod
es_list = [EffectSizeCalculator.from_dichotomous(12, 80, 22, 78, type="OR")]
# ... add more studies ...
result = PoolingEngine.pool(es_list, method=PoolingMethod.DL, confidence=0.95)
print(result.summary_text())
# Pooled OR: 0.55 (95% CI 0.40-0.75), z = -4.21, p = 2.5e-5
# I² = 38.5%, τ² = 0.018, Q = 19.5 (df=14, p=0.144)
```

### Q35. What's the difference between RoB 2, ROBINS-I, QUADAS-2, and NOS?

ARS v2.0.0 ships four risk-of-bias tools in
`systematic_review/risk_of_bias.py`:

| Tool | Class | Use for |
|---|---|---|
| **RoB 2** | `CochraneRoB2` | Randomised trials (5 domains: randomisation, deviations, missing data, measurement, selection of reported result) |
| **ROBINS-I** | `ROBINS_I` | Non-randomised studies of interventions (7 domains covering confounding, selection, classification, deviations, missing data, measurement, reporting) |
| **QUADAS-2** | `QUADAS2` | Diagnostic accuracy studies (4 domains: patient selection, index test, reference standard, flow and timing) |
| **NOS** | `NewcastleOttawaScale` | Cohort / case-control studies (8-item star-based scale) |

Each tool has `.assess(study_data) -> RoBResult`, `.to_table(results)`,
`.to_figure(results)`, and `.traffic_light(results)`. Pick the tool
that matches your study design — using RoB 2 on a non-randomised study
will produce meaningless judgements.

### Q36. How do I detect citation bursts?

Use `innovation.citation_bursts.CitationBurstDetector`. It implements
Kleinberg's two-state automaton and detects bursts on papers, authors,
keywords, journals, and topics.

```python
from innovation.citation_bursts import CitationBurstDetector
detector = CitationBurstDetector(s=2.0, gamma=1.0)
paper_bursts   = detector.detect_papers(papers, time_window=1, threshold=2.0)
author_bursts  = detector.detect_authors(papers)
keyword_bursts = detector.detect_keywords(papers, field="keywords")
df = detector.to_dataframe(paper_bursts)
df.to_csv("bursts.csv", index=False)
```

Each `Burst` carries `entity_id`, `entity_name`, `entity_type`,
`start_year`, `end_year`, `peak_year`, `strength`, `duration`, and
`total_burst_score`. Strength > 5 ⇒ strong burst; duration > 3 years ⇒
sustained shift in attention.

### Q37. How do I generate a Nature-style figure?

Pass `journal="nature"` to `Q1FigureFactory`. Nature uses Arial, 7 pt
tick labels, 9 pt axis labels, 10 pt bold titles, and the palette
`['#E64B35', '#4DBBD5', '#00A087', '#3C5488', '#F39B7F', ...]`.

```python
from q1_figures.figure_factory import Q1FigureFactory
f = Q1FigureFactory(journal="nature", dpi=300)
f.set_size(columns="single", aspect="square")  # 3.5 × 3.5 in
fig, ax = f.new_figure_and_axes()
ax.plot(x, y, color="#E64B35")
f.set_axis_labels(ax, xlabel="X", ylabel="Y")
f.set_title(ax, "My Figure")
f.style_axes(ax, spine_top=False, spine_right=False)
f.finalize(fig)
f.save(fig, "fig_nature.svg")
```

See [Q1_FIGURES_GUIDE.md](Q1_FIGURES_GUIDE.md) for the complete export
checklist (DPI, font embedding, panel labels, etc.).

### Q38. How do I apply ForceAtlas2 layout?

Use `gephi_viz.layouts.ForceAtlas2.apply()`. ForceAtlas2 is a
force-directed layout tuned for networks with communities — it pushes
apart unconnected nodes and pulls together connected ones with
adjustable gravity and scaling.

```python
import networkx as nx
from gephi_viz.layouts import ForceAtlas2
G = nx.karate_club_graph()
fa2 = ForceAtlas2()
positions = fa2.apply(G, iterations=200)   # dict[node, (x, y)]
# Visualise via the Q1 network figure helper:
from q1_figures.network_plots import Q1NetworkPlots
fig = Q1NetworkPlots.network_figure(G, layout="fa2", figsize=(3.5, 3.5))
```

### Q39. How do I scrape from IEEE or Springer?

ARS v2.0.0 ships `data_acquisition/ieee_scraper.py` and
`data_acquisition/springer_scraper.py`. Set the API keys via the env
vars `ARS_IEEE_API_KEY` / `ARS_SPRINGER_API_KEY` (or in
`config/secrets.yaml`), then use the `ScrapingEngine` to query both
sources in parallel with rate-limiting applied per source.

```python
from data_acquisition.scraping_engine import ScrapingEngine
import os
os.environ["ARS_IEEE_API_KEY"]    = "..."
os.environ["ARS_SPRINGER_API_KEY"] = "..."
engine = ScrapingEngine()
results = engine.search_all("graph neural networks",
                            sources=["ieee", "springer"], max_results=50)
print(f"Got {len(results)} papers.")
```

### Q40. How do I use the AI writing assistant offline?

The `research_lifecycle.writing_assistant.WritingAssistant` class uses
the local LLM backend (Ollama) when configured. Set `ai_provider:
"ollama"` in `config/secrets.yaml` and pull a model via
`ollama pull llama3`. The assistant then runs entirely offline — no
API calls leave your machine. If no LLM is available, the assistant
falls back to deterministic template-based generation.

```python
from research_lifecycle.writing_assistant import WritingAssistant
wa = WritingAssistant()   # auto-detects Ollama or falls back
outline = wa.outline("Effect of SGLT2 inhibitors on HbA1c",
                     sections=["Introduction", "Methods", "Results", "Discussion"])
abstract = wa.generate_abstract(paper)
section  = wa.draft_section("Methods", "Describe study selection",
                            supporting_papers=[...], word_count=500)
bib      = wa.format_bibliography(papers, style="apa")
```

### Q41. How do I export a network to Gephi (.gexf)?

Use `networkx_pro.graph_io` (or `networkx.write_gexf`) to serialise any
networkx graph to a `.gexf` file readable by Gephi. ARS also exposes a
convenience REST endpoint `POST /api/network/export` with
`format="gexf"`.

```python
import networkx as nx
from knowledge_graph.citation_graph import CitationGraphBuilder
G = CitationGraphBuilder().build(papers)
nx.write_gexf(G, "citation_network.gexf")
# Or via REST:
# curl -X POST http://127.0.0.1:8765/api/network/export \
#   -H 'Content-Type: application/json' \
#   -d '{"graph": <node-link>, "format": "gexf"}' -o citation.gexf
```

### Q42. How do I run a network meta-analysis?

Use `meta_analysis.network_meta.NetworkMetaAnalysis`. Inputs are a list
of `TreatmentComparison` objects (each carrying one direct comparison,
with `effect_size` on the **log** scale, SE, and `n_total`). Compute
the consistency model, the inconsistency model, SUCRA scores, the league
table, and run node-splitting to localise any inconsistency.

```python
from meta_analysis.network_meta import NetworkMetaAnalysis, TreatmentComparison
comps = [
    TreatmentComparison(study_id="A1", treatment_a="Placebo",
                        treatment_b="DrugA", effect_size=0.85, se=0.18, n_total=240),
    # ... more comparisons ...
]
nma = NetworkMetaAnalysis(comps)
cons = nma.consistency_model()
inc  = nma.inconsistency_model()
print("AIC consistency =", cons.AIC)
print("AIC inconsistency =", inc.AIC)
print("SUCRA:", nma.sucra_scores())
splits = nma.node_splitting()
```

### Q43. How do I assess publication bias?

Use `meta_analysis.funnel_plot.ContourEnhancedFunnel` which implements
Egger's, Begg's, Peters', Harbord's tests plus trim-and-fill and
Rosenthal fail-safe N. Egger p < 0.10 indicates small-study bias.

```python
from meta_analysis.funnel_plot import ContourEnhancedFunnel
funnel = ContourEnhancedFunnel(es_list, pooled=result.pooled_effect)
funnel.add_significance_contours()
funnel.add_pseudo_ci(alpha=0.95)
n_filled = funnel.add_trim_fill(method="R0")
t, p, intercept = funnel.eggers_test()
n_fs = funnel.rosenthal_fail_safe_n()
print(f"Egger p={p:.4g}, trim-fill added {n_filled}, fail-safe N={n_fs}")
```

### Q44. How do I generate an SWiM (synthesis without meta-analysis) report?

Use `systematic_review.synthesis.SWiMReportingChecklist`. SWiM is the
SWiM (Synthesis Without Meta-analysis) reporting guideline — 9 items
for reporting synthesis of studies when meta-analysis is not feasible
(Campbell et al., J Clin Epidemiol 2020).

```python
from systematic_review.synthesis import SWiMReportingChecklist
swim = SWiMReportingChecklist()
swim.mark_reported(item_number=1, location_in_report="Methods §3.1")
swim.mark_reported(item_number=2, location_in_report="Methods §3.2")
print(f"Completeness: {swim.completeness():.1%}")
print(swim.to_markdown())
```

### Q45. How do I track knowledge frontiers over time?

Use `innovation.frontier_mapping.FrontierTracker` with a
`papers_per_year: Dict[int, List[Paper]]` mapping. The tracker
produces a longitudinal view of how frontiers emerge, grow, and fade.

```python
from innovation.frontier_mapping import FrontierTracker
tracker = FrontierTracker(papers_per_year={
    2018: papers_2018, 2019: papers_2019, 2020: papers_2020,
    2021: papers_2021, 2022: papers_2022,
})
emerging = tracker.emerging_topics(year=2022, lookback=3)
fading   = tracker.fading_topics(year=2022, lookback=3)
df       = tracker.track_over_time()   # tidy DataFrame
```

### Q46. How do I find the most disruptive paper in my corpus?

Use `innovation.novelty_scoring.NoveltyScorer.rank_disruptive_papers()`.
It computes the Funk-Owen-Smith CD index for every paper (positive = disruptive,
negative = consolidating) and returns the top-N.

```python
from innovation.novelty_scoring import NoveltyScorer
scorer = NoveltyScorer(papers)
disruptive = scorer.rank_disruptive_papers(top_n=10)
for ns in disruptive:
    print(f"  {ns.paper_title}: DI={ns.disruption_index:+.3f}, "
          f"atypicality={ns.atypicality_score:.3f}, "
          f"percentile={ns.percentile:.1f}")
```

### Q47. How do I run a Nature-style multi-panel figure?

Use `q1_figures.multi_panel.MultiPanelFigure` with `panel_labels="abcd"`
to get the standard a / b / c / d panel labels in the top-left of each
panel — the Q1 convention.

```python
from q1_figures.multi_panel import MultiPanelFigure
mpf = MultiPanelFigure(rows=2, cols=2, journal="nature", dpi=300,
                       panel_labels="abcd")
ax_a = mpf.add_panel(row=0, col=0); mpf.set_panel_label(0, "a")
ax_b = mpf.add_panel(row=0, col=1); mpf.set_panel_label(1, "b")
ax_c = mpf.add_panel(row=1, col=0); mpf.set_panel_label(2, "c")
ax_d = mpf.add_panel(row=1, col=1); mpf.set_panel_label(3, "d")
mpf.adjust_spacing(hspace=0.4, wspace=0.4)
mpf.finalize()
mpf.save("fig1_multipanel.svg")
```

---

*For a complete walkthrough of the v2.0.0 features, see the
[PRISMA_GUIDE.md](PRISMA_GUIDE.md), [META_ANALYSIS_GUIDE.md](META_ANALYSIS_GUIDE.md),
[Q1_FIGURES_GUIDE.md](Q1_FIGURES_GUIDE.md), and
[INNOVATION_GUIDE.md](INNOVATION_GUIDE.md) guides.*
