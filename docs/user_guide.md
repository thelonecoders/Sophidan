# User Guide

> **Audience:** end-users of Academic Research Suite (ARS).
> **Companion docs:** [INSTALL.md](INSTALL.md) (install details),
> [FAQ.md](FAQ.md) (common questions),
> [api_reference.md](api_reference.md) (REST reference).

This guide walks you through every page of the desktop UI, the
optional web-server mode, and the workflows that tie them
together. By the end you should be able to scrape a corpus, build
a knowledge graph, run topic modeling, chat with an AI about your
papers, and export a publication-ready PDF.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [The Desktop Interface](#the-desktop-interface)
3. [Searching the Literature](#searching-the-literature)
4. [Working with Projects](#working-with-projects)
5. [Building Knowledge Graphs](#building-knowledge-graphs)
6. [Running Data-Science Analyses](#running-data-science-analyses)
7. [Using the AI Assistant](#using-the-ai-assistant)
8. [Configuring Proxies](#configuring-proxies)
9. [Generating Reports](#generating-reports)
10. [Web Server Mode](#web-server-mode)
11. [Keyboard Shortcuts Cheat Sheet](#keyboard-shortcuts-cheat-sheet)
12. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Install

Follow [INSTALL.md](INSTALL.md) for platform-specific instructions.
The TL;DR on Linux / macOS:

```bash
git clone https://github.com/academic-research-suite/academic_research_suite.git
cd academic_research_suite
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
cp config/default_config.yaml config/secrets.yaml
# Edit secrets.yaml — at minimum set your AI provider + key (optional)
```

Optional environment variables you may want:

```bash
export ARS_LOG_LEVEL=DEBUG         # verbose logging
export ARS_AI_PROVIDER=ollama       # use local LLM
export ARS_AI_MODEL=llama3
export ARS_AI_BASE_URL=http://localhost:11434
export NCBI_EMAIL=you@example.org   # polite-mailto for PubMed
export CROSSREF_MAILTO=you@example.org
export SEMANTIC_SCHOLAR_API_KEY=...  # optional, raises rate limit
```

### First Run

```bash
python main.py                # desktop
# or
python main.py --web          # browser at http://127.0.0.1:8765
```

On first launch the **WelcomeScreen** appears with three buttons:
*New Project*, *Open Project*, *Search*. If you skip all three, you
land on the **Dashboard** page (see below).

`[screenshot: welcome screen]`

---

## The Desktop Interface

The desktop window is split into three regions:

```text
┌─────────────────────────────────────────────────────────────────┐
│ File Edit View Tools Help       🔍 Global search…   🤖 AI  🌙     │  ← top toolbar / menu
├──────────┬──────────────────────────────────────────────────────┤
│          │                                                      │
│  🏠 Dash │                                                      │
│  🔍 Src  │              Active page (QStackedWidget)            │
│  📁 Proj  │                                                      │
│  📊 Data │              ← lazy-loaded on first access            │
│  🕸 KG    │                                                      │
│  🧮 Anly  │                                                      │
│  🤖 AI   │                                                      │
│  🌐 Proxy│                                                      │
│  📝 Rprt │                                                      │
│          │                                                      │
│  ⚙ Set   │                                                      │
│  ❓ Help │                                                      │
├──────────┴──────────────────────────────────────────────────────┤
│ ⏱ Queue: 0   ⚙ Tasks: 0   💾 DB: 0 KB              📝 Logs        │  ← status bar
└─────────────────────────────────────────────────────────────────┘
```

### Dashboard (`ui/widgets/dashboard.py`)

The landing page. Shows:

- Total papers / projects / sources scraped.
- Recent activity (last 10 tasks).
- Quick-launch buttons for Search, AI Chat, Reports.
- DB size + cache size + healthy-proxy count.

`[screenshot: dashboard view]`

### Search (`ui/widgets/search_panel.py`)

The primary scraping interface. See
[Searching the Literature](#searching-the-literature) below.

### Projects (`ui/widgets/project_explorer.py`)

Three-pane layout: project tree on the left, paper table + comparison
chart in the center, action buttons + snapshots timeline on the
right. See [Working with Projects](#working-with-projects).

### Data (`ui/widgets/data_view.py`)

Read-only browser over every paper in the database. Filter by
source, year, project; sort by any column; right-click to open the
Author Dashboard or jump to the paper's source URL.

### Knowledge Graph (`ui/widgets/network_view.py`)

A matplotlib-canvas network visualizer with a toolbar: graph type
(citation / collaboration / temporal), layout (spring / kamada /
circular / hierarchical), node-size metric (degree / betweenness /
closeness / eigenvector), min-edge filter, Re-layout, Export PNG,
Export SVG. Hover shows a tooltip; click selects; double-click
drills in. See [Building Knowledge Graphs](#building-knowledge-graphs).

### Analysis (`ui/widgets/analysis_view.py`)

The data-science workbench: pick an analysis type (topic modeling /
clustering / temporal / bibliometrics / embeddings), a method, the
parameters, and click **Run Analysis**. Results render as a
matplotlib figure + QTableWidget + HTML summary. See
[Running Data-Science Analyses](#running-data-science-analyses).

### AI Chat (`ui/widgets/ai_chat.py`)

Chat interface with the LLM of your choice. Top bar has the
provider/model selectors, a Settings… button (temperature, max
tokens, system prompt), a **Use RAG** checkbox, and a Clear
History button. Center is a scrollable area of `ChatBubble` widgets
(user right-aligned blue, AI left-aligned gray) with embedded
clickable paper-citation anchors. Bottom is a multi-line editor —
**Ctrl+Enter** to send. See [Using the AI Assistant](#using-the-ai-assistant).

### Proxy (`ui/widgets/proxy_panel.py`)

Four `StatCard`s at the top (Total / Healthy / Avg Latency / Last
Refresh), action buttons (Refresh Pool / Test All / Import /
Export) + progress bar, a sortable `QTableWidget`, a right-side
drag-and-drop chain builder + rotation-strategy combo, and a
bottom event log. See [Configuring Proxies](#configuring-proxies).

### Reports (`ui/dialogs/reporting_dashboard.py`)

A 4-step wizard: pick report type → pick scope → pick sections →
pick output file. Lazy-dispatches to the right `reporting.*`
backend. See [Generating Reports](#generating-reports).

### Settings (`ui/widgets/settings_panel.py`)

A 7-tab `QTabWidget`:

1. **General** — theme, language, data dir, log level.
2. **Scraping** — default sources, rate limit, max concurrent, cache TTL, user agent.
3. **Proxy** — enabled toggle, strategy, refresh interval, ban threshold.
4. **AI** — provider, model, API key (password field), base URL, temperature, max tokens, system prompt.
5. **Database** — DB path, vacuum, backup, restore, FTS rebuild, vector reset.
6. **Appearance** — accent color, font family, font size, sidebar collapse default.
7. **Advanced** — experimental features, debug mode, telemetry opt-out.

Save / Reset / Defaults buttons at the bottom.

---

## Searching the Literature

The **Search** panel is your gateway to the eight built-in sources:
arXiv, PubMed, OpenAlex, Semantic Scholar, Google Scholar, Crossref,
DBLP, ORCID.

### Basic search

1. Type your query into the top search box (e.g.
   `"graph neural networks"`).
2. Tick the source checkboxes you want to query.
3. (Optional) Use the filters row: year range, paper type,
   fields-of-study, open-access-only.
4. Drag the **max results** slider (10–500).
5. Press **Enter** or click **Search**.

Results populate as `ResultCard` widgets, each showing the title,
authors, year, source badge, citation count, and an abstract
preview. Click **Add to Project** on any card to attach the paper
to your active project.

`[screenshot: search results with cards]`

### Advanced search dialog

`Tools → Advanced Search…` (or `Ctrl+Shift+A`) opens the
`AdvancedSearchDialog`:

- Build field-specific boolean queries: each row has
  `AND/OR/NOT` + `field` (title / author / abstract / venue /
  keyword / DOI) + `value`.
- Add / remove conditions dynamically.
- Set year range + max results.
- **Save Query** / **Load Query** presets — stored as JSON under
  `data/advanced_search_presets/`.

The structured query dict has the shape:

```json
{
  "source": ["arxiv", "pubmed"],
  "year_from": 2018,
  "year_to": 2024,
  "max_results": 100,
  "conditions": [
    {"bool": "AND", "field": "title",    "value": "transformer"},
    {"bool": "AND", "field": "abstract", "value": "attention"}
  ]
}
```

### Filter syntax (free text)

In the basic search box you can use the field qualifiers that
arXiv understands: `au:` (author), `ti:` (title), `abs:`
(abstract), `cat:` (category). These are passed through to the
underlying scraper verbatim.

### Caching

Every scraper GET is cached under
`data/cache/cache.db` keyed by `source:hash(url+params)`. The
default TTL is 24 hours but is configurable via
`config/secrets.yaml` (`scraping_rate_limit_per_sec` controls
*rate*, not TTL — for TTL editing, see the `Cache` class). To
force a refresh, delete the cache file or run
`Settings → Database → Clear Cache`.

---

## Working with Projects

A **Project** is a named collection of papers with a color, a
description, and per-project settings. Use it to group papers for a
literature review, a course, or a single research question.

### Creating a project

`File → New Project…` (or `Ctrl+N`) opens a small dialog. Enter a
name, optional description, pick a color. The new project appears
in the Project Explorer tree on the left.

### Adding papers

From the **Search** panel: each `ResultCard` has an
**Add to Project** button — papers go to the currently selected
project in the Project Explorer. From the **Data** view:
right-click any paper → **Add to Project…** → pick from the dialog.

### Snapshots

A **Snapshot** is a time-stamped restore point of a project's
paper list. Use them to:

- Freeze a literature review at the moment you wrote a paper.
- Compare the same project at different points in time.
- Roll back after an unintended bulk-delete.

`Create Snapshot` in the Project Explorer right panel opens a
dialog (label + description). Snapshots appear in the timeline
list; double-click any snapshot to restore the paper list to that
point in time.

### Comparing projects

`Compare with…` opens a dialog that lets you pick another project.
The center view shows:

- A Venn diagram (or bar chart if `matplotlib-venn` is missing)
  of the shared / unique papers.
- A table of bibliometric deltas (paper count, citation total,
  h-index, average year).

The same comparison is available via the REST API:

```bash
curl -X POST http://127.0.0.1:8765/api/projects/compare \
  -H 'Content-Type: application/json' \
  -d '{"a": 1, "b": 2}' | jq .
```

### Import / export

Right-click a project → **Export** to write a JSON workspace file
containing the project metadata, paper list, and snapshots. Import
another workspace with the **Import** button at the top of the
Project Explorer.

---

## Building Knowledge Graphs

Open the **Knowledge Graph** page. You'll see the toolbar and an
empty matplotlib canvas.

### Choosing a graph type

The toolbar's leftmost combo box switches between three graph types:

| Type | Source module | Edges |
|---|---|---|
| Citation | `knowledge_graph/citation_graph.py` | paper → cited paper |
| Collaboration | `knowledge_graph/collaboration_graph.py` | author → author (shared paper) |
| Temporal | `knowledge_graph/temporal_network.py` | year-tagged paper → paper |

### Picking a layout

The **Layout** combo offers:

- **Spring** — Fruchterman-Reingold (default).
- **Kamada** — Kamada-Kawai path-length.
- **Circular** — nodes on a circle.
- **Hierarchical** — shell layout.

For large graphs (>500 nodes) prefer Kamada; for collaboration
graphs prefer Circular.

### Metrics

The **Node size** combo controls what node size encodes:

- **Degree** — number of immediate neighbors.
- **Betweenness** — how often the node lies on shortest paths.
- **Closeness** — inverse of average distance to others.
- **Eigenvector** — centrality weighted by neighbor centrality
  (PageRank for citation graphs).

### Filtering

Drag the **min-edge filter** slider to prune low-weight edges.
This declutters dense graphs.

### Exporting

**Export PNG** and **Export SVG** save the current figure. For
programmatic access, every graph class also exposes
`to_cytoscape(papers)` returning a JSON-serialisable dict for the
web viewer:

```python
from knowledge_graph import CitationGraph
import json
data = CitationGraph().to_cytoscape(papers)
open("graph.json", "w").write(json.dumps(data, indent=2))
```

### Metrics overlay

Click any node to populate the right-side info panel with the
paper's title, authors, year, citation count, and a list of its
graph neighbors. Double-click drills in — the canvas re-centers
on the clicked node's neighborhood.

`[screenshot: knowledge graph visualization]`

---

## Running Data-Science Analyses

Open the **Analysis** page. The left column lets you pick:

- **Topic Modeling** — method (LDA / NMF / BERTopic), num_topics
  slider (2–30), random state.
- **Clustering** — method (KMeans / DBSCAN / HDBSCAN /
  Agglomerative), n_clusters slider, optional `optimal_k` via
  silhouette.
- **Temporal** — metric (publications / citations / authors),
  year range slider.
- **Bibliometrics** — h-index, i10-index, g-index, journal metrics.
- **Embeddings** — sentence-transformers model selector, output
  dimensions.

### Running an analysis

1. Pick the analysis type from the top combo.
2. Pick the method (and any parameters).
3. Click **Run Analysis** — a `Worker` is submitted to the
   `WorkerPool`; the bottom progress bar tracks completion.
4. When finished, the center area renders three views:
   - **Matplotlib figure** — visual summary (topic word cloud,
     cluster scatter, time series).
   - **QTableWidget** — per-topic or per-cluster paper lists.
   - **QTextBrowser** — HTML summary report.
5. **Save Figure**, **Save Model** (pickles the fitted model),
   **Export CSV** let you take the result elsewhere.

### Programmatic access

```python
from data_science import TopicModeler, Clusterer, TemporalAnalyzer, Bibliometrics
from data_acquisition.scraping_engine import ScrapingEngine

papers = ScrapingEngine().search_all("transformer architecture").papers

# Topic modeling
model = TopicModeler(method="lda", num_topics=8).fit(papers)

# Clustering
result = Clusterer(method="kmeans").fit(papers, optimal_k=True)

# Temporal
series = TemporalAnalyzer().publication_series(papers)

# Bibliometrics
bib = Bibliometrics(papers)
print(f"h-index: {bib.h_index}, g-index: {bib.g_index}")
```

`[screenshot: topic-modeling analysis view]`

---

## Using the AI Assistant

Open the **AI Chat** page.

### Setting the provider

Top-bar combo box: choose **OpenAI**, **Anthropic**, or
**Ollama (local)**. The first time you pick a cloud provider, ARS
will prompt you to enter your API key — it's stored in
`config/secrets.yaml` (or `ARS_AI_API_KEY` env var).

For **Ollama**, set `ai_base_url=http://localhost:11434` and pick
a model name (e.g. `llama3`, `mistral`, `phi3`, `qwen2.5`).
Install Ollama separately from https://ollama.com.

### Chat

Type your message into the bottom editor and press **Ctrl+Enter**
to send. The AI streams its response token-by-token. Each AI
message is rendered as a `ChatBubble` widget; if the AI cites a
paper, the citation is an inline clickable anchor carrying a JSON
payload — clicking it opens the paper in the **Data** view.

### RAG (Retrieval-Augmented Generation)

Tick the **Use RAG** checkbox in the top bar. ARS will:

1. Embed your query via the active LLM provider (or the
   deterministic SHA-256 fallback when `provider=none`).
2. Look up the top-k nearest papers in the ChromaDB vector store
   at `data/chroma/`.
3. Augment your prompt with the retrieved abstracts.
4. Stream the response, with each cited paper rendered as a
   clickable anchor.

### Chat settings

The **Settings…** button opens a `ChatSettingsDialog` with:

- Temperature slider (0.0–2.0).
- Max tokens (128–8192).
- System prompt editor.

Conversation history is persisted per-project to
`data/projects/<id>/chat_history.json` and reloaded when you switch
projects.

### Programmatic summarization

```python
from ai_assistant import LLMClient, PaperSummarizer

llm = LLMClient(provider="ollama", model="llama3",
                base_url="http://localhost:11434")
summarizer = PaperSummarizer(llm)
topic = summarizer.summarize_topic(papers[:20])
print(topic.overview)
```

`[screenshot: AI chat with embedded citations]`

---

## Configuring Proxies

Open the **Proxy** page.

### Refreshing the pool

Click **Refresh Pool** to scrape fresh proxies from the nine
built-in sources, health-check them, and keep the healthy ones.
A progress bar at the top of the panel tracks the scrape → check
→ keep cycle. Targets 200 healthy proxies by default; tune via
`pool.refresh_pool(target_count=N)`.

### Testing proxies

**Test All** re-runs the health check on every proxy currently in
the pool. To test a single proxy, right-click its row → **Test
Now**. Latency, anonymity, and country fields update in place.

### Building a chain

Drag proxies from the main table into the right-side **Chain
Builder** list (it accepts `InternalMove` reordering). Pick a
rotation strategy from the combo:

- **Round Robin**
- **Random**
- **Least Used**
- **Best Latency**
- **Weighted by Success**

Click **Save Chain** to persist it. The chain is now usable by any
scraper that goes through the `ProxyManager` — chains support
multi-hop SOCKS4/SOCKS5/HTTP-CONNECT tunneling via
`proxy/proxy_chain.py`.

### Importing your own proxies

**Import** accepts TXT (one `host:port` per line), JSON, or CSV
files. Use this to bring in a paid proxy subscription. The
`Pool.import_from_file()` method auto-detects the format by
extension.

### Background refresh

`pool.start_background_refresh(interval_min=30)` starts a daemon
thread that keeps the pool topped up. Tune the interval in
`config/secrets.yaml` (`scraping_max_concurrent` controls the
in-flight request count).

`[screenshot: proxy panel with chain builder]`

---

## Generating Reports

`Tools → Reports…` (or the **Reports** sidebar entry) opens the
**Reporting Dashboard** — a 4-step wizard:

1. **Step 1 — Report type**: PDF / DOCX / PPTX / BibTeX / CSV.
2. **Step 2 — Scope**: current project / all projects / search
   results / manual selection.
3. **Step 3 — Sections** (PDF/DOCX/PPTX only): cover / abstract /
   methods / results / tables / charts / bibliography.
4. **Step 4 — Output file**: pick a path (browse button included).

Click **Generate Report**. The progress bar tracks the worker;
the resulting file is opened in your default viewer when done.

### Export Wizard

For tabular exports use `File → Export…` (or `Ctrl+E`) to open the
**Export Wizard**: choose format (CSV / JSON / BibTeX / RIS / Excel
/ Parquet), scope, columns preset, and output file. The wizard
delegates to `reporting.csv_export`, `reporting.bibtex_export`,
or `pandas` (for Excel / Parquet / JSON).

`[screenshot: reporting dashboard wizard]`

---

## Web Server Mode

ARS ships an optional local web server so you can drive the
engine from a browser, a notebook, or another language entirely.

### Starting the server

```bash
python main.py --web                 # http://127.0.0.1:8765
python main.py --web --port 9000     # custom port
python main.py --web --host 0.0.0.0  # expose to LAN (use with care)
python main.py --web --debug         # Flask debug reloader
```

### The dashboard

Open http://127.0.0.1:8765/ for the browser dashboard. The
dashboard mirrors the desktop UI: search panel, project explorer,
knowledge graph canvas, AI chat, proxy manager.

### Live API docs

Open http://127.0.0.1:8765/api/docs for an interactive HTML page
listing every endpoint with request/response schemas. See
[api_reference.md](api_reference.md) for the canonical reference.

### REST API quick tour

```bash
# Health check
curl http://127.0.0.1:8765/api/health | jq .

# Submit an async scrape
TASK=$(curl -sX POST http://127.0.0.1:8765/api/scraping/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"diffusion models","sources":["arxiv"],"max_results":50}' \
  | jq -r .task_id)

# Poll status
curl http://127.0.0.1:8765/api/scraping/tasks/$TASK | jq .

# Stream an AI chat (Server-Sent Events)
curl -N -X POST http://127.0.0.1:8765/api/ai/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Summarize the latest on retrieval-augmented generation"}'

# Export a PDF
curl -X POST http://127.0.0.1:8765/api/export/report \
  -H 'Content-Type: application/json' \
  -d '{"type":"pdf","project_id":1}' --output report.pdf
```

### WebSocket live updates

Connect to `ws://127.0.0.1:8765` (Socket.IO) and emit a
`subscribe` event with `{"task_id": "<id>"}` to join the per-task
room. The server emits `scrape:progress`, `scrape:complete`,
`scrape:error`, `scrape:cancelled`, `log:line`, `ai:token`, and
`ai:done` events on that room.

```javascript
const socket = io("http://127.0.0.1:8765");
socket.emit("subscribe", {task_id: TASK_ID});
socket.on("scrape:progress", (data) => console.log(data.progress));
```

---

## Keyboard Shortcuts Cheat Sheet

| Shortcut | Action |
|---|---|
| `Ctrl+N` | New project |
| `Ctrl+O` | Open project |
| `Ctrl+S` | Save current project |
| `Ctrl+E` | Open Export Wizard |
| `Ctrl+Q` | Quit |
| `Ctrl+K` | Jump to Search panel |
| `Ctrl+F` | Focus global search box |
| `Ctrl+,` | Open Settings panel |
| `Ctrl+Shift+T` | Toggle dark / light theme |
| `Ctrl+Enter` | Send current AI chat message |
| `Ctrl+Shift+A` | Open Advanced Search dialog |
| `F1` | Open Documentation (this guide) |
| `F9` | Toggle sidebar collapse |

---

## Troubleshooting

### Proxy failures

**Symptom:** Refresh Pool returns 0 healthy proxies.

**Cause:** Most likely your ISP or firewall is blocking outbound
connections to the free-proxy sources. Verify with:

```bash
curl -I https://www.proxy-list.download/api/v1/get?type=http
```

**Fix:** Use the **Import** button to load a paid-proxy
subscription, or set `ARS_PROXY_ENABLED=false` and run without
proxies.

### Rate limits

**Symptom:** A scraper returns `HTTP 429 Too Many Requests`.

**Cause:** You've exceeded the upstream rate limit.

**Fix:** Lower `scraping_rate_limit_per_sec` in
`config/secrets.yaml` (default is 1.0; arXiv asks for ≤0.33).
For Semantic Scholar, set `SEMANTIC_SCHOLAR_API_KEY`. For
Crossref, set `CROSSREF_MAILTO`.

### AI provider errors

**Symptom:** `AIError: provider openai returned 401`.

**Fix:** Re-enter your API key in **Settings → AI → API Key** (or
set `ARS_AI_API_KEY`). For Ollama, ensure `ollama serve` is
running and `ARS_AI_BASE_URL` matches (`http://localhost:11434`).

### Database locks

**Symptom:** `sqlite3.OperationalError: database is locked`.

**Cause:** Another process (often a previous ARS instance that
crashed) holds an exclusive lock on `data/ars.db`.

**Fix:**

```bash
# Find the locker (Linux / macOS)
lsof data/ars.db
# Kill it, then:
rm -f data/ars.db-wal data/ars.db-shm
python main.py
```

For顽固 cases, `python main.py --reset-db` recreates the schema
from scratch (you will lose all data).

### Font issues for CJK in PDFs

**Symptom:** Chinese / Japanese / Korean characters render as
squares or missing glyphs in PDF / chart figures.

**Cause:** The system font cache lacks a CJK sans-serif font.

**Fix (Linux):**

```bash
sudo apt install fonts-noto-cjk
rm -rf ~/.cache/matplotlib
python main.py
```

**Fix (macOS):** install Noto Sans SC via Font Book, or use
`brew install --cask font-noto-sans-cjk-sc`.

**Fix (Windows):** the standard Windows 10/11 fonts include
Microsoft YaHei which is in the matplotlib fallback list.

### Google Scholar captcha

**Symptom:** The Google Scholar scraper returns empty results or
HTML pages with captcha forms.

**Cause:** Google aggressively throttles / captchas automated
access.

**Fix:**

1. Enable proxies (`Settings → Proxy → Enable`).
2. Set a rotation strategy with `min_samples_before_ban=2` so the
   rotator doesn't burn through your whole pool.
3. If captchas persist, use the Crossref scraper instead — it
   covers the same DOI-identified corpus without captchas.

### Web server shows `503 service_unavailable`

**Symptom:** `/api/health` returns 200 but specific endpoints
return 503.

**Cause:** The corresponding backend module (e.g.
`ChatEngine`) failed to initialize on first access. The health
endpoint's `modules` dict tells you which one is missing.

**Fix:** Check `logs/ars.log` for the import error. Usually it's
a missing optional dependency — install via
`pip install <package>` and restart the server.

---

*If this guide doesn't answer your question, see
[FAQ.md](FAQ.md) or open an issue at
<https://github.com/academic-research-suite/academic_research_suite/issues>.*

---

## Using the Bibliometric Dashboard

ARS v2.0.0 ships a dedicated **Bibliometric Dashboard**
(`ui/widgets/bibliometric_dashboard.py`) for production-grade
scientometric analysis. Open it from the sidebar
(`Bibliometrics → Bibliometric Dashboard`) and either load a saved
project or paste a list of DOIs. The dashboard computes every
Publish-or-Perish index (h-index, e-index, g-index, i10,
contemporary h-index, AR-index, w-index, q²-index, individual /
multi-authored h-indices) in a single click, builds a VOSviewer-style
co-citation network, runs CiteSpace-style citation-burst detection,
and computes journal impact factors / SJR / SNIP for every journal in
your corpus. Use the dashboard's left panel to filter by year range,
author, journal, or topic cluster; the right panel shows live
bibliometric KPIs that update as the filter changes. The computed
indices are cached in the SQLite database and can be exported to CSV /
JSON / BibTeX from the toolbar. For programmatic access use the
[`/api/bibliometrics/*`](api_reference.md#v200-endpoints) REST
endpoints or call `bibliometrics.pop_indices.PoPIndices().compute_all(...)`
directly.

## Building a PRISMA Flow Diagram

Open `Tools → PRISMA Flow Builder` (or sidebar `Systematic Review →
PRISMA Builder`) to construct the canonical PRISMA 2020 four-stage flow
diagram. Fill in the 16 stage-count fields in the form (records from
databases, records from registers, duplicates removed, records
screened, excluded at title/abstract, full-text sought, not retrieved,
assessed, excluded with reasons, included in qualitative /
quantitative synthesis). Pick one of the seven extensions (standard,
IPD, NMA, ScR, Harms, Abstract, Diagnostic) and one of three journal
styles (BMJ navy, JAMA monochrome, Lancet red). Click "Generate PDF"
to write a publication-grade flow diagram (`prisma.flow_diagram
.PRISMAFlowGenerator.render_pdf`) — the same diagram is also available
as SVG, PNG, HTML, and GraphViz DOT. Once you've filled the 27-item
PRISMA checklist (`prisma.checklist.PRISMAChecklist`), use the
`PRISMAReport` class to bundle flow + checklist + per-study
extraction forms into a single submission-ready PDF. See
[PRISMA_GUIDE.md](PRISMA_GUIDE.md) for the full workflow.

## Running a Meta-Analysis

Open sidebar `Systematic Review → Meta-Analysis` to launch the
meta-analysis view (`ui/widgets/meta_analysis_view.py`). Load your
included studies (either by importing a CSV of 2×2 cell counts or by
pulling them from the SR screening module) and pick an effect-size
metric (MD / SMD / RR / OR / HR / RD). Choose a pooling method — fixed
(IV), DerSimonian–Laird (default random-effects), REML, ML, Mantel–
Haenszel, or Peto. The view computes the pooled effect, 95% CI,
z-statistic, p-value, I², τ², Q-statistic, and per-study weights in
real time. The bottom panel shows the forest plot (Cochrane / JAMA /
Lancet style selectable) and the funnel plot with significance
contours, pseudo-CI, and trim-and-fill imputations. Egger's, Begg's,
Peters', and Harbord's tests run automatically and report a small-study
bias verdict. Click "Leave-one-out" to run a sensitivity analysis or
"Subgroup analysis" to test a categorical moderator. Export the final
report (PDF / DOCX / Markdown) from the toolbar. See
[META_ANALYSIS_GUIDE.md](META_ANALYSIS_GUIDE.md) for the full recipe.

## Conducting a Systematic Review

Open sidebar `Systematic Review` to launch the SR view
(`ui/widgets/systematic_review_view.py`). Start by creating a
protocol — pick from one of nine built-in templates (Cochrane,
Campbell, JBI, PRISMA 2020, CONSORT, STROBE, CARE, ENTREQ, SRQR) and
fill in the PICO framework (Population, Intervention, Comparator,
Outcomes, Study design). Register the protocol with PROSPERO and
capture the registration ID. Import your scraped records (PubMed,
Embase, Cochrane CENTRAL via the multi-source scraping engine); the
screening module auto-deduplicates and starts title/abstract screening.
Two independent reviewers can screen the same record; the module
computes Cohen's kappa for inter-rater agreement. Continue to
full-text screening with a per-study exclusion reason, then run the
risk-of-bias tool (Cochrane RoB 2 for RCTs, ROBINS-I for
non-randomised, QUADAS-2 for diagnostic accuracy, NOS for cohort /
case-control). The `PRISMAIntegration` class automatically generates
the PRISMA flow diagram and 27-item checklist from the screening
counts. See [PRISMA_GUIDE.md](PRISMA_GUIDE.md) and
[MODULE_REFERENCE.md](MODULE_REFERENCE.md) for details.

## Generating Q1 Figures

Open sidebar `Q1 Figures` to launch the Q1 Figure Studio
(`ui/widgets/q1_figure_studio.py`). Pick a target journal (Nature,
Science, Cell, NEJM, Lancet, JAMA) — the studio applies the journal's
colour palette and typography automatically (Arial for Nature / Cell,
Helvetica for Science / JAMA, Times for Lancet). Choose a column width
(single 89 mm, 1.5-column 120 mm, double 183 mm) and aspect ratio
(square / wide / tall). Pick a figure type from the 16 built-in
recipes (forest, funnel, volcano, Manhattan, QQ, Kaplan-Meier, ROC,
PR-curve, boxplot, violin, raincloud, heatmap, network, Sankey,
multi-panel, custom). For multi-panel figures, the studio auto-labels
panels a / b / c / d in the top-left corner of each panel (the Q1
convention). Add significance bars, error bars, and CI bands from the
"Overlays" menu. Export to SVG (preferred for journals), PDF, PNG
(300+ DPI), or TIFF. See [Q1_FIGURES_GUIDE.md](Q1_FIGURES_GUIDE.md)
for the complete export checklist.

## Exploring Innovation & Frontiers

Open sidebar `Innovation` to launch the innovation panel
(`ui/widgets/innovation_panel.py`). Load your corpus (≥ 500 papers
recommended) and the panel runs five analyses in parallel: (1)
Kleinberg citation-burst detection on papers, authors, keywords,
journals, and topics; (2) knowledge-frontier mapping via three
complementary approaches (embedding density, topic-model boundary,
citation velocity); (3) trend forecasting (ARIMA / Prophet / linear /
exponential); (4) paper recommendation (similar, query, topic, user,
bridge, trending — with MMR diversification and explainability); and
(5) novelty scoring (Uzzi atypicality + Funk-Owen-Smith disruption
index). The "Next big topic" button runs `ResearchDirectionRecommender`
to combine the four signals into a ranked list of 10 research
directions with novelty / feasibility scores, supporting papers, and
suggested collaborators. See [INNOVATION_GUIDE.md](INNOVATION_GUIDE.md)
for the full workflow.

## Advanced Network Analysis (Gephi Mode)

Open sidebar `Gephi Advanced View` (`ui/widgets/gephi_advanced_view.py`)
for Gephi-equivalent interactive network analytics. Load a networkx
graph (from a GEXF / GraphML import, from a VOSviewer-style co-citation
analysis, or directly from a project's citation graph). The view
supports three layout algorithms (ForceAtlas2 with `barnes_hut`
optimisation, OpenOrd for large graphs, YifanHu multilevel for dense
networks), 34 network statistics (density, average clustering,
diameter, radius, modularity, betweenness / closeness / eigenvector
centrality, etc.), partition-based colouring (Louvain communities →
hex colours), ranking-based node sizing (PageRank, degree, betweenness),
and a filter chain builder (degree filter, k-core, range filter,
component filter, ego network). Apply a layout, compute statistics,
detect communities, then export to `.gexf` for further work in Gephi
itself, or render an interactive HTML preview via `gephi_viz.preview`
(requires `pyvis` — see [INSTALL.md](INSTALL.md)). The advanced view is
the recommended way to produce publication-grade network figures for
Q1 journals; for the programmatic API see the
[`/api/network/*`](api_reference.md#v200-endpoints) endpoints and the
[`q1_figures.network_plots.Q1NetworkPlots`](Q1_FIGURES_GUIDE.md#figure-recipes)
recipes.
