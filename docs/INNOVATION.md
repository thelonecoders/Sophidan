# Innovation & Novel Features

> **Audience:** researchers, evaluators, and prospective users
> wondering what makes Academic Research Suite (ARS) different
> from the existing landscape of reference managers, literature
> mapping tools, and bibliometric dashboards.

This document showcases the genuinely novel capabilities of ARS —
the features that distinguish it from Zotero, Mendeley, Connected
Papers, Inciteful, Publish or Perish, Lens.org, Semantic Scholar's
Graph API, VOSviewer, CiteSpace, and the dozens of other tools
academic researchers juggle daily.

---

## Table of Contents

1. [The Existing Landscape](#the-existing-landscape)
2. [What's Genuinely New in ARS](#whats-genuinely-new-in-ars)
3. [Feature-by-Feature Comparisons](#feature-by-feature-comparisons)
4. [Why ARS Is Open Source](#why-ars-is-open-source)

---

## The Existing Landscape

Academic literature tooling falls into a few well-trodden
categories:

| Category | Examples | Strengths | Weaknesses |
|---|---|---|---|
| **Reference managers** | Zotero, Mendeley, EndNote, Citavi | Bibliography management, PDF organization, citation plugins for Word/LaTeX | No scraping, no analysis, no AI, no graph view |
| **Literature discovery** | Connected Papers, Inciteful, Research Rabbit, Litmaps | Visual exploration of related work | Cloud-only, no scraping, no AI, no reports |
| **Bibliometric analysis** | VOSviewer, CiteSpace, Publish or Perish | Co-citation / co-author / keyword analysis | One-trick ponies, no scraping, no UI for exploration |
| **AI literature tools** | Elicit, Consensus, SciSpace, Scite | LLM summarization, RAG | Cloud-only, your data leaves your machine, no scraping, no reports |
| **Aggregators** | Semantic Scholar, OpenAlex, Lens.org, Google Scholar | Central indexes, search | No analysis, no AI, no reports, rate-limited APIs |
| **Scrapers** | `scholarly` (Python), `pybliometrics` (Python), `habanero` (Python) | Programmatic access | Single-source, no UI, no DB, no analysis |

Every existing tool excels at one thing. None of them cover the
full workflow of "discover → scrape → curate → analyze → chat →
report" — and the ones that try (Elicit, Scite) are cloud SaaS
with usage caps, no local-first mode, and no way to plug in your
own scraper or analysis.

---

## What's Genuinely New in ARS

ARS is the first open-source, MIT-licensed, local-first tool to
combine all six capabilities in a single binary, with a desktop
UI and a REST API:

```text
┌──────────────────────────────────────────────────────────────┐
│                  ARS — one binary, six capabilities            │
├──────────────────────────────────────────────────────────────┤
│  1. Multi-source parallel scraping                            │
│  2. Free-proxy-pool auto-management                          │
│  3. Real bibliometric analysis (h/i10/g, PageRank, HITS)      │
│  4. Citation network with temporal evolution                  │
│  5. Local-LLM RAG over your own corpus                       │
│  6. PDF / DOCX / PPTX / BibTeX / CSV report generation        │
└──────────────────────────────────────────────────────────────┘
```

### 1. Multi-source parallel scraping with proxy chaining

**Existing world.** `scholarly` only scrapes Google Scholar.
`pybliometrics` only scrapes Scopus. `habanero` only scrapes
Crossref. Every "academic scraper" tool is a single-source
specialist. To do multi-source you write glue code or you use a
commercial service like ScrapingBee.

**ARS.** The `ScrapingEngine.search_all(query, sources=[...])`
method fans a single query out across arXiv, PubMed, OpenAlex,
Semantic Scholar, Google Scholar, Crossref, DBLP, and ORCID in
parallel via a `ThreadPoolExecutor`. The results are merged and
deduplicated by DOI/title. Each source has its own rate limiter
(arXiv is held to 0.33 req/s, Crossref to 50 req/s) and optional
proxy injection. The `proxy_chain.py` module even lets you chain
multiple proxies for maximum anonymity when scraping captchy
sources.

**Why it's novel.** No existing open-source tool offers this
breadth of sources plus parallel execution plus per-source rate
limiting plus proxy chaining in a single package.

### 2. Free-proxy-pool auto-management

**Existing world.** Proxy management tools (`proxy_pool`,
`proxy-scraper-checker`, `proxypool`) exist but are standalone
scripts that don't integrate with anything else. Commercial proxy
services (BrightData, Oxylabs) are paid SaaS.

**ARS.** The `proxy/` package (six modules) is a complete
pipeline: scrape nine free-proxy sources → health-check with
geoip enrichment → rotate via five strategies → optional
multi-hop SOCKS/HTTP chaining → SQLite persistence → background
refresh daemon → import/export (TXT/JSON/CSV). All of this is
wired into the `ScrapingEngine` so any scraper automatically
rotates through the pool with one configuration flag
(`proxy_enabled: true`).

**Why it's novel.** No other academic research tool ships its
own proxy suite — most don't even have a "configure proxy"
option, and the few that do (Zotero's connector) expect you to
manage the proxy yourself.

### 3. Local-LLM RAG over scraped corpus (privacy-preserving)

**Existing world.** Elicit, Consensus, SciSpace, and Scite all
ship AI features but they're cloud SaaS — your paper abstracts,
prompts, and chat history leave your machine and are processed
on someone else's GPU. For researchers working with unpublished
data, NDAs, or sensitive pre-publication material, that's a
non-starter.

**ARS.** Plug in [Ollama](https://ollama.com), set
`ai_provider: "ollama"`, and the entire AI stack runs locally:

- The `LLMClient` lazy-imports the Ollama SDK and never sends a
  byte to the cloud.
- `RAGEngine` builds a ChromaDB vector store at `data/chroma/`
  over your scraped corpus.
- `ChatEngine` retrieves relevant papers from the vector store
  and streams the LLM response back, with citation anchors that
  link to your local DB.
- For air-gapped environments, the offline echo backend
  (`provider="none"`) returns deterministic SHA-256-hash
  responses so the entire suite runs without network or API keys.

**Why it's novel.** No other academic research tool with this
feature breadth offers a fully local LLM RAG mode. The closest
is SciSpace's "Ask AI" — but that's cloud-only.

### 4. Citation network with temporal evolution

**Existing world.** Connected Papers and Inciteful offer
beautiful citation graph visualizations but they're cloud-only,
single-source (typically OpenAlex or Semantic Scholar), and
have no temporal dimension. VOSviewer and CiteSpace offer
overlay visualizations but lack interactivity.

**ARS.** The `knowledge_graph/` package builds three graph types
from any `Paper`-like objects you feed it (so it works with
scraped data, manual entries, or imported BibTeX):

- `CitationGraph` — directed network with PageRank, HITS
  authority/hub scores, and per-node h-index.
- `CollaborationGraph` — co-authorship projection from a
  bipartite author–paper set.
- `TemporalNetwork` — year-tagged edges with snapshot /
  evolution animation / growth-curve utilities (GIF output via
  `imageio`).

Every graph class exposes `to_cytoscape(papers)` for web
embedding, `build(papers)` for the raw `networkx.Graph`, and
visually renders in the `NetworkViewWidget` (matplotlib canvas
with hover / click / drill-in).

**Why it's novel.** Combining three graph types + temporal
evolution + a real interactive UI in one tool — that's a
first for open-source academic software.

### 5. Bibliometric snapshot comparison

**Existing world.** Publish or Perish computes h-index, g-index,
and a handful of other metrics for a single author or journal.
VOSviewer does the same for one dataset at a time. Nobody offers
"compare two snapshots of the same corpus over time" out of the
box.

**ARS.** The `project_management/` package adds:

- `SnapshotManager` — freeze the state of a project at any
  moment in time (paper list, settings, color).
- `ProjectComparison` — compare two projects (or two snapshots
  of the same project) side-by-side with shared / unique paper
  sets (Venn diagram if `matplotlib-venn` is available, bar
  chart otherwise) and bibliometric deltas (paper count,
  citation total, h-index, average year).

**Why it's novel.** "How has my literature review evolved
since last quarter?" is a question every researcher asks. ARS is
the first open-source tool to answer it directly without
requiring you to write a Python script.

### 6. Single-binary desktop + web-server dual mode

**Existing world.** Desktop apps (Zotero) can't be scripted
remotely. Web apps (Elicit) require an account and a browser.
Library tools (VOSviewer, CiteSpace) are Java apps that need
the JRE.

**ARS.** One codebase, one binary, two frontends:

```bash
python main.py          # PyQt5 desktop UI
python main.py --web    # Flask + Socket.IO web server at 127.0.0.1:8765
```

Both modes share the same `ServerState` singleton, the same
SQLite DB, the same ChromaDB vector store, the same proxy pool,
the same EventBus. You can scrape from the desktop, switch to
the web UI to share a graph with a collaborator over your LAN,
then close the server and keep working offline — no data
migration, no sync, no export step.

**Why it's novel.** No existing academic tool ships dual mode.
Most are either/or (cloud SaaS OR local desktop).

---

## Feature-by-Feature Comparisons

### ARS vs. Zotero / Mendeley / EndNote

| Capability | Reference managers | ARS |
|---|---|---|
| Bibliography management | ✅ | ⚠️ (BibTeX export) |
| PDF organization | ✅ | ❌ (planned v1.1.0) |
| Citation plugins (Word/LaTeX) | ✅ | ❌ |
| **Multi-source scraping** | ❌ | ✅ (8 sources in parallel) |
| **Proxy management** | ❌ | ✅ (6-module suite) |
| **Bibliometric analysis** | ❌ | ✅ (h/i10/g, PageRank, HITS) |
| **Citation graph visualization** | ❌ | ✅ (3 graph types) |
| **AI chat / RAG** | ❌ | ✅ (local LLM via Ollama) |
| **PDF / DOCX / PPTX report generation** | ❌ | ✅ |
| Local-first / no cloud | ⚠️ | ✅ |

**Use both.** Zotero for bibliography management; ARS for
scraping, analysis, AI, and reports. ARS exports BibTeX that
Zotero can import.

### ARS vs. Connected Papers / Inciteful / Research Rabbit

| Capability | Discovery tools | ARS |
|---|---|---|
| Visual graph exploration | ✅ | ✅ |
| Multi-source corpus | ⚠️ (one source) | ✅ (8 sources) |
| Custom corpus (your own papers) | ❌ | ✅ |
| **AI chat / RAG** | ❌ | ✅ |
| **Report generation** | ❌ | ✅ |
| **Local-first** | ❌ (cloud-only) | ✅ |
| **REST API** | ❌ | ✅ |
| **Bibliometric metrics** | ⚠️ (basic) | ✅ (h/i10/g, PageRank, HITS) |

**Why pick ARS.** You want to do more than explore — you want to
analyze, chat with, and report on a corpus you control.

### ARS vs. VOSviewer / CiteSpace / Publish or Perish

| Capability | Bibliometric tools | ARS |
|---|---|---|
| Co-citation analysis | ✅ | ⚠️ (via co-citation matrix) |
| Co-author analysis | ✅ | ✅ |
| Keyword co-occurrence | ✅ | ⚠️ (planned) |
| Overlay visualizations | ✅ | ⚠️ (matplotlib) |
| **Multi-source scraping** | ❌ | ✅ |
| **AI chat / RAG** | ❌ | ✅ |
| **Snapshot comparison** | ❌ | ✅ |
| **Modern UI (Qt, not Java)** | ❌ | ✅ |
| **Open source, MIT** | ⚠️ (varies) | ✅ |

**Why pick ARS.** You're tired of Java apps from 2008 with
Visual Basic 6-style UIs and you want bibliometric metrics as
part of a modern workflow, not a standalone tool.

### ARS vs. Elicit / Consensus / SciSpace / Scite

| Capability | AI literature tools | ARS |
|---|---|---|
| LLM summarization | ✅ | ✅ |
| RAG over corpus | ✅ | ✅ |
| Citation anchors | ✅ | ✅ |
| **Local-first (no cloud)** | ❌ | ✅ (Ollama) |
| **Multi-source scraping** | ❌ | ✅ |
| **Report generation** | ⚠️ (limited) | ✅ |
| **No account / no usage caps** | ❌ | ✅ |
| **Open source** | ❌ | ✅ |
| **REST API** | ❌ | ✅ |

**Why pick ARS.** You have unpublished research data you can't
upload to a SaaS, or you've hit usage caps on Elicit, or you
want to script the AI from a notebook.

### ARS vs. raw Python (scholarly + pybliometrics + pandas + matplotlib)

| Capability | DIY Python | ARS |
|---|---|---|
| Multi-source scraping | ❌ (write glue code) | ✅ (out of the box) |
| Proxy management | ❌ (write your own) | ✅ |
| Persistent DB | ❌ (write your own) | ✅ |
| FTS5 search | ❌ (write your own) | ✅ |
| Vector store + RAG | ❌ (write your own) | ✅ |
| UI | ❌ (write your own) | ✅ (PyQt5 desktop + Flask web) |
| Report generation | ❌ (write your own) | ✅ |
| Time to first useful result | Days–weeks | Minutes |

**Why pick ARS.** You'd rather spend your time doing research
than writing scraper plumbing.

---

## Why ARS Is Open Source

We believe literature research tooling should be:

1. **Transparent** — you should be able to read every line of
   code that touches your paper corpus. ARS ships its full source
   under MIT.
2. **Local-first** — your data should never leave your machine
   unless you explicitly send it. ARS's proxy suite routes
   scraping traffic through YOUR proxies, not ours. ARS's AI
   assistant runs on YOUR GPU via Ollama, not ours.
3. **Extensible** — you should be able to add a new scraper, a
   new analysis, or a new AI provider without forking the
   project. ARS documents every extension point.
4. **Free as in beer AND free as in speech** — no paid tiers,
   no "enterprise" features, no SaaS upsells. MIT-licensed
   forever.

We're not building a startup. We're building the tool we wished
existed when we were graduate students juggling six browser tabs
of arXiv + Zotero + Mendeley + VOSviewer + Elicit + Overleaf.

If ARS saves you time, the best thank-you is a PR adding a
scraper for a source we missed, or an analysis we haven't
implemented, or a bug fix we missed.

---

*This document is intentionally opinionated. If you disagree with
any comparison, please open an issue — we'll happily correct
inaccuracies.*
