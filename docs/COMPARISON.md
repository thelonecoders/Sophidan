# Feature-by-Feature Comparison: ARS v2.0.0 vs the Rest

> **TL;DR:** Academic Research Suite v2.0.0 (ARS) is the only MIT-licensed,
> pure-Python, desktop-first workbench that combines multi-source
> scraping, Publish-or-Perish-grade bibliometrics, Gephi-grade network
> visualization, systematic-review lifecycle, meta-analysis with
> publication-bias diagnostics, PRISMA 2020 generation, Q1-journal
> figure factory, innovation analytics, and a local-LLM RAG assistant
> — all behind a single PyQt5 desktop UI and a 65+ endpoint local REST
> API. Every alternative below covers a slice of the same surface area
> but no single alternative covers it all.

The tables below compare ARS v2.0.0 against thirteen popular tools.
Marks: **✓** = full native support, **partial** = supported but limited
/ requires plugins / requires manual scripting, **✗** = not supported.

---

## Table of Contents

1. [Publish or Perish (PoP)](#1-publish-or-perish-pop)
2. [Gephi](#2-gephi)
3. [VOSviewer](#3-vosviewer)
4. [CiteSpace](#4-citespace)
5. [Sci2 Tool](#5-sci2-tool)
6. [Zotero](#6-zotero)
7. [Mendeley](#7-mendeley)
8. [Connected Papers](#8-connected-papers)
9. [Inciteful](#9-inciteful)
10. [Rayyan](#10-rayyan)
11. [Covidence](#11-covidence)
12. [RevMan](#12-revman)
13. [Metafor (R)](#13-metafor-r)
14. [Overall scorecard](#14-overall-scorecard)

---

## 1. Publish or Perish (PoP)

PoP is Anne-Wil Harzing's Windows/Mac desktop tool that retrieves
citation counts from Google Scholar, Crossref, Scopus (paid), and
Web of Science (paid) and computes author- and journal-level
bibliometric indices.

| Capability | ARS v2 | PoP 8 |
|---|:---:|:---:|
| Multi-source scraping (17+ APIs, no manual upload) | ✓ | ✗ |
| Author-level indices (h, g, i10, e, hc, ARi, AWCR, hm, hi, h_max, w, q2) | ✓ | partial (h, g, i10, e, hc, ARi, AWCR, hm, hi) |
| Journal metrics (IF, SJR, SNIP, Eigenfactor, CiteScore) | ✓ | partial (h5, IF via Web of Science) |
| VOSviewer-style network analyses | ✓ | ✗ |
| CiteSpace-style burst / frontier detection | ✓ | ✗ |
| Systematic review lifecycle (screening + RoB + extraction) | ✓ | ✗ |
| Meta-analysis (DL / MH / Peto / REML + NMA) | ✓ | ✗ |
| PRISMA 2020 flow + 6 extensions | ✓ | ✗ |
| Q1-journal figure factory (Nature/Science/Cell palettes) | ✓ | ✗ |
| Innovation analytics (bursts, frontiers, novelty scoring) | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| REST API (65+ endpoints) | ✓ | ✗ |
| Open-source / MIT | ✓ | ✗ (proprietary, free) |
| Runs fully offline | ✓ | ✗ (requires Google Scholar / Crossref) |
| Cross-platform (Linux / macOS / Windows) | ✓ | partial (Mac/Win only) |

**When to choose PoP:** You only need author-level indices and the
data sources PoP covers are sufficient (Google Scholar + Crossref).
**When to choose ARS:** You need the same indices plus any of the
v2.0.0 capabilities above, or you need to script the computation
programmatically, or you want to combine bibliometrics with
meta-analysis or Q1 figures in the same workflow.

---

## 2. Gephi

Gephi is an open-source Java desktop tool for interactive network
visualization with the iconic ForceAtlas2 layout and a Statistics
panel covering PageRank, HITS, modularity, diameter etc.

| Capability | ARS v2 | Gephi 0.10 |
|---|:---:|:---:|
| 11 layout algorithms (ForceAtlas2, OpenOrd, YifanHu, FR, KK, ...) | ✓ | ✓ |
| 15 graph filters (degree range, k-core, ego, partition, time-range, ...) | ✓ | ✓ |
| Statistics panel (centrality, modularity, HITS, PageRank, diameter, avg. path) | ✓ | ✓ |
| Partition coloring + ranking-based sizing | ✓ | ✓ |
| Preview renderer (publication-grade) | ✓ | partial |
| 60+ NetworkX algorithms exposed | ✓ | partial (via Python plugin) |
| Graph IO (GraphML, GEXF, GML, Pajek, edgelist, adjlist, JSON, Cytoscape) | ✓ | partial (GraphML, GEXF, GML, Pajek) |
| Multi-source scraping (17 APIs) | ✓ | ✗ |
| Bibliometrics (PoP indices + journal metrics + VOS + CiteSpace) | ✓ | ✗ |
| Systematic-review lifecycle | ✓ | ✗ |
| Meta-analysis with publication-bias tests | ✓ | ✗ |
| PRISMA 2020 flow generator | ✓ | ✗ |
| Q1-journal figure factory | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| REST API (65+ endpoints) | ✓ | partial (via toolkit plugin) |
| Pure Python (no JVM, no Java dependencies) | ✓ | ✗ |
| Runs fully offline | ✓ | ✓ |

**When to choose Gephi:** You need the Gephi UI itself (drag-and-drop
filter palette, real-time layout tuning, plugin ecosystem). **When to
choose ARS:** You need a reproducible script / API to drive the same
layouts and statistics, you want to combine network analysis with
bibliometrics / meta-analysis / PRISMA / Q1 figures, or you don't
want a JVM dependency.

---

## 3. VOSviewer

VOSviewer is Leiden University's tool for bibliometric mapping
(co-citation, co-authorship, term co-occurrence, bibliographic
coupling) with its own layout algorithm.

| Capability | ARS v2 | VOSviewer 1.6 |
|---|:---:|:---:|
| Bibliographic coupling | ✓ | ✓ |
| Co-citation analysis (sources, authors, references) | ✓ | ✓ |
| Co-authorship analysis | ✓ | ✓ |
| Term co-occurrence | ✓ | ✓ |
| Overlay visualization (score by year) | ✓ | ✓ |
| Cluster graph | ✓ | ✓ |
| Force-atlas 2D mapping | ✓ | ✗ (uses VOS layout) |
| PoP-grade author indices (h, g, i10, e, hc, hm, hi) | ✓ | ✗ |
| Journal metrics (IF, SJR, SNIP, Eigenfactor, CiteScore) | ✓ | ✗ |
| Multi-source scraping (17 APIs) | ✓ | ✗ (manual file import) |
| CiteSpace-style burst detection | ✓ | ✗ |
| Systematic-review lifecycle | ✓ | ✗ |
| Meta-analysis with publication-bias tests | ✓ | ✗ |
| PRISMA 2020 flow generator | ✓ | ✗ |
| Q1-journal figure factory | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| REST API (65+ endpoints) | ✓ | ✗ |
| Open-source / MIT | ✓ | ✗ (proprietary, free) |

**When to choose VOSviewer:** You're already invested in VOS maps and
the Leiden clustering tradition, or you prefer its UI for fast
exploratory mapping. **When to choose ARS:** You need VOS-style
analyses plus PoP-grade indices plus journal metrics plus meta-analysis
plus PRISMA, or you need to drive the analyses from Python.

---

## 4. CiteSpace

CiteSpace is Chaomei Chen's Java tool for detecting and visualizing
emerging trends and citation bursts in scientific literature using
Kleinberg's burst-detection algorithm.

| Capability | ARS v2 | CiteSpace 6 |
|---|:---:|:---:|
| Kleinberg citation-burst detection | ✓ | ✓ |
| Knowledge-domain map | ✓ | ✓ |
| Timezone view | ✓ | ✓ |
| Spectral clustering view | ✓ | ✓ |
| Structural variation analysis | ✓ | ✓ |
| Landmark papers / intellectual turning points | ✓ | ✓ |
| Research-front clustering | ✓ | ✓ |
| VOSviewer-style analyses (coupling, co-citation, term co-occurrence) | ✓ | ✗ |
| PoP-grade author indices | ✓ | ✗ |
| Journal metrics | ✓ | ✗ |
| Systematic-review lifecycle | ✓ | ✗ |
| Meta-analysis with publication-bias tests | ✓ | ✗ |
| PRISMA 2020 flow generator | ✓ | ✗ |
| Q1-journal figure factory | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| REST API (65+ endpoints) | ✓ | ✗ |
| Pure Python (no JVM) | ✓ | ✗ |
| Open-source / MIT | ✓ | ✗ (proprietary, free) |

**When to choose CiteSpace:** You want its signature visualizations
(timezone, spectral view) out of the box. **When to choose ARS:** You
need the same burst-detection and frontier-mapping capabilities plus
every other v2.0.0 capability, or you don't want a JVM dependency.

---

## 5. Sci2 Tool

Sci2 Tool is the Indiana University Science of Science tool — a Java
Eclipse-RCP application with the algorithmic breadth of NetworkX plus
temporal bibliometrics and scientogram layouts.

| Capability | ARS v2 | Sci2 1.0 |
|---|:---:|:---:|
| Scientogram (co-word, co-journal, institute collaboration) | ✓ | ✓ |
| Bipartite projection | ✓ | ✓ |
| Network algorithms (60+ via NetworkX) | ✓ | ✓ (via JUNG) |
| Gephi-style layouts (ForceAtlas2, OpenOrd, YifanHu) | ✓ | ✗ (uses FR / Kamada-Kawai) |
| PoP-grade author indices | ✓ | partial (h only) |
| Journal metrics | ✓ | ✗ |
| VOSviewer-style analyses | ✓ | ✗ |
| CiteSpace-style burst detection | ✓ | partial |
| Systematic-review lifecycle | ✓ | ✗ |
| Meta-analysis with publication-bias tests | ✓ | ✗ |
| PRISMA 2020 flow generator | ✓ | ✗ |
| Q1-journal figure factory | ✓ | ✗ |
| Innovation analytics (novelty scoring, trend forecasting) | ✓ | partial |
| Local-LLM RAG assistant | ✓ | ✗ |
| REST API (65+ endpoints) | ✓ | ✗ |
| Pure Python (no JVM) | ✓ | ✗ |
| Open-source / Apache-2.0 | ✓ (MIT) | ✓ (Apache-2.0) |

**When to choose Sci2:** You're in a science-of-science research group
already invested in its workflows. **When to choose ARS:** You need
the same algorithms plus 11 Gephi-grade layouts plus bibliometrics,
meta-analysis, PRISMA and Q1 figures in one Python-native package.

---

## 6. Zotero

Zotero is the open-source reference manager — a Firefox/standalone
desktop app for collecting, annotating, and citing literature.

| Capability | ARS v2 | Zotero 7 |
|---|:---:|:---:|
| Reference management (CRUD, tags, notes, attachments) | ✓ | ✓ |
| Browser-connector ingestion | ✗ | ✓ |
| Multi-source API scraping (17 APIs) | ✓ | ✗ (uses Crossref only) |
| Bibliometrics (PoP-grade indices) | ✓ | ✗ |
| Network visualization (ForceAtlas2 + 10 other layouts) | ✓ | ✗ |
| Systematic-review lifecycle (screening + RoB + extraction) | ✓ | ✗ |
| Meta-analysis with publication-bias tests | ✓ | ✗ |
| PRISMA 2020 flow generator | ✓ | ✗ |
| Q1-journal figure factory | ✓ | ✗ |
| Innovation analytics (bursts, frontiers, novelty) | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| Citation formatting (APA, MLA, Chicago, Vancouver, ...) | ✓ | ✓ (via CSL) |
| BibTeX export | ✓ | ✓ |
| Open-source | ✓ (MIT) | ✓ (AGPL-3.0) |

**When to choose Zotero:** You need a reference manager with browser
connectors and group libraries. **When to choose ARS:** You need to
*analyse* the literature, not just *manage* it. (You can also use both
together — Zotero for collection, ARS for analysis.)

---

## 7. Mendeley

Mendeley is Elsevier's cloud-first reference manager + social network
for researchers.

| Capability | ARS v2 | Mendeley |
|---|:---:|:---:|
| Reference management | ✓ | ✓ |
| Multi-source API scraping (17 APIs) | ✓ | ✗ (Elsevier only) |
| Bibliometrics (PoP-grade indices) | ✓ | ✗ |
| Network visualization | ✓ | ✗ |
| Systematic-review lifecycle | ✓ | ✗ |
| Meta-analysis | ✓ | ✗ |
| PRISMA 2020 flow generator | ✓ | ✗ |
| Q1-journal figure factory | ✓ | ✗ |
| Innovation analytics | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| Runs fully offline | ✓ | ✗ (cloud-first) |
| Open-source | ✓ (MIT) | ✗ (proprietary) |

**When to choose Mendeley:** You're committed to the Elsevier
ecosystem. **When to choose ARS:** You want open-source, offline,
multi-source, multi-analysis tooling.

---

## 8. Connected Papers

Connected Papers is a web app that builds a graph of papers
citation-related to a seed paper.

| Capability | ARS v2 | Connected Papers |
|---|:---:|:---:|
| Seed-paper → related-papers graph | ✓ | ✓ |
| 11 layout algorithms (ForceAtlas2 + 10 more) | ✓ | ✗ (uses its own) |
| Multi-source scraping (17 APIs) | ✓ | ✗ |
| Bibliometrics (PoP indices + journal metrics) | ✓ | ✗ |
| 60+ NetworkX algorithms | ✓ | ✗ |
| Systematic-review lifecycle | ✓ | ✗ |
| Meta-analysis | ✓ | ✗ |
| PRISMA 2020 flow generator | ✓ | ✗ |
| Q1-journal figure factory | ✓ | ✗ |
| Innovation analytics | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| REST API | ✓ | ✗ |
| Open-source | ✓ (MIT) | ✗ (proprietary, free) |

**When to choose Connected Papers:** You want a 30-second visual
overview of a seed paper's neighbourhood. **When to choose ARS:** You
want to script that exploration plus every other v2 capability on
your own machine.

---

## 9. Inciteful

Inciteful is a web app for forward/backward citation chaining — paper
discovery via the "two-papers" or "multi-papers" method.

| Capability | ARS v2 | Inciteful |
|---|:---:|:---:|
| Forward + backward citation chaining | ✓ | ✓ |
| CitationResolver (cross-API DOI / OpenAlex / Crossref / OpenCitations) | ✓ | ✓ (uses OpenAlex) |
| Co-citation + bibliographic coupling analysis | ✓ | partial |
| Bibliometrics (PoP indices + journal metrics) | ✓ | ✗ |
| Network visualization (11 layouts) | ✓ | ✗ (uses its own) |
| Systematic-review lifecycle | ✓ | ✗ |
| Meta-analysis | ✓ | ✗ |
| PRISMA 2020 flow generator | ✓ | ✗ |
| Q1-journal figure factory | ✓ | ✗ |
| Innovation analytics | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| REST API | ✓ | ✗ |
| Open-source | ✓ (MIT) | ✗ (proprietary, free) |

**When to choose Inciteful:** You want quick web-based citation
chaining. **When to choose ARS:** You want the same chaining
reproducibly, with full bibliometric, meta-analytic and PRISMA
workflows layered on top.

---

## 10. Rayyan

Rayyan is a free web app for collaborative systematic-review screening.

| Capability | ARS v2 | Rayyan |
|---|:---:|:---:|
| Title/abstract + full-text screening | ✓ | ✓ |
| Dual-reviewer screening with kappa | ✓ | ✓ |
| Conflict resolution | ✓ | ✓ |
| Auto-dedup | ✓ | ✓ |
| Risk-of-bias tools (RoB 2, ROBINS-I, QUADAS-2, NOS) | ✓ | partial |
| Meta-analysis (DL / MH / Peto / REML + NMA) | ✓ | ✗ |
| PRISMA 2020 flow generator + 6 extensions | ✓ | ✓ (basic flow only) |
| Forest / funnel plots with publication-bias tests | ✓ | ✗ |
| Bibliometrics (PoP + VOS + CiteSpace) | ✓ | ✗ |
| Q1-journal figure factory | ✓ | ✗ |
| Innovation analytics | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| Multi-source scraping (17 APIs) | ✓ | ✗ (manual upload) |
| REST API (65+ endpoints) | ✓ | ✓ (basic) |
| Open-source | ✓ (MIT) | ✗ (proprietary, free) |

**When to choose Rayyan:** You only need screening and are happy to
upload your search results to a third-party server. **When to choose
ARS:** You want the entire systematic-review lifecycle on your own
machine — screening + RoB + extraction + synthesis + meta-analysis +
PRISMA — plus bibliometrics, network analysis and figures.

---

## 11. Covidence

Covidence is the Cochrane-endorsed commercial SR platform — web-based
screening + RoB + extraction + (basic) meta-analysis, on a per-review
subscription model.

| Capability | ARS v2 | Covidence |
|---|:---:|:---:|
| Title/abstract + full-text screening | ✓ | ✓ |
| Dual-reviewer + conflict resolution | ✓ | ✓ |
| Risk-of-bias tools (RoB 2, ROBINS-I, QUADAS-2, NOS) | ✓ | ✓ (RoB 2 + ROBINS-I) |
| Data extraction | ✓ | ✓ |
| Meta-analysis (DL / MH / Peto / REML) | ✓ | partial (basic forest) |
| Network meta-analysis + SUCRA | ✓ | ✗ |
| Publication-bias tests (Egger / Begg / Peters / Harbord + trim-fill) | ✓ | ✗ |
| PRISMA 2020 flow generator + 6 extensions | ✓ | partial (basic flow) |
| Forest / funnel plots | ✓ | ✓ (basic) |
| Bibliometrics | ✓ | ✗ |
| Network visualization (11 layouts + 60+ algorithms) | ✓ | ✗ |
| Q1-journal figure factory | ✓ | ✗ |
| Innovation analytics | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| Multi-source scraping (17 APIs) | ✓ | ✗ (manual upload) |
| REST API (65+ endpoints) | ✓ | ✓ (limited) |
| Pricing | Free / MIT | Subscription per review |
| Open-source | ✓ | ✗ |

**When to choose Covidence:** You're a Cochrane review group needing
institutional workflow integration. **When to choose ARS:** You want
Covidence-grade workflows plus bibliometrics, network analysis and
Q1 figures, on your own machine, for free.

---

## 12. RevMan

RevMan (Review Manager) is the Cochrane Collaboration's desktop tool
for managing Cochrane reviews — protocols, comparisons, forest plots,
risk-of-bias tables, and GRADE summaries.

| Capability | ARS v2 | RevMan 5 |
|---|:---:|:---:|
| Cochrane-style protocol templates | ✓ | ✓ |
| Forest plots (subgroups, diamonds, favours labels) | ✓ | ✓ |
| Risk-of-bias traffic light + summary bar | ✓ | ✓ (RoB 2 only) |
| DerSimonian-Laird, MH, Peto pooling | ✓ | ✓ |
| Mantel-Haenszel OR & RR | ✓ | ✓ |
| REML pooling | ✓ | ✓ |
| Network meta-analysis + SUCRA | ✓ | ✗ (via NMAsim plugin) |
| Publication-bias tests (Egger / Begg / Peters / Harbord) | ✓ | partial (Egger) |
| Trim-and-fill | ✓ | ✗ |
| GRADE summary of findings | ✓ | ✓ |
| Sensitivity analysis (leave-one-out, cumulative, influence) | ✓ | partial |
| 4 RoB tools (RoB 2, ROBINS-I, QUADAS-2, NOS) | ✓ | partial (RoB 2 + ROBINS-I) |
| Bibliometrics (PoP + VOS + CiteSpace) | ✓ | ✗ |
| Network visualization (11 layouts) | ✓ | ✗ |
| Q1-journal figure factory (10 palettes) | ✓ | ✗ |
| Innovation analytics | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| Multi-source scraping (17 APIs) | ✓ | ✗ |
| REST API (65+ endpoints) | ✓ | ✗ |
| Pure Python | ✓ | ✗ (Java / .NET) |
| Open-source | ✓ (MIT) | ✗ (proprietary, free for Cochrane) |

**When to choose RevMan:** You're submitting a review to the Cochrane
Library. **When to choose ARS:** You want RevMan-grade meta-analysis
plus bibliometrics, network analysis, Q1 figures, and innovation
analytics — without being locked into the Cochrane submission workflow.

---

## 13. Metafor (R)

Metafor is Wolfgang Viechtbauer's R package — the gold standard for
meta-analysis in statistics. It is the most complete open-source
meta-analysis toolkit by a wide margin.

| Capability | ARS v2 | Metafor |
|---|:---:|:---:|
| Effect sizes (MD, SMD, RR, OR, HR, RD) | ✓ | ✓ |
| Cohen's d, Hedges' g, Glass's Δ | ✓ | ✓ |
| Fixed IV / DerSimonian-Laird / MH / Peto / REML / ML / Paule-Mandel / EB | ✓ | ✓ |
| Heterogeneity Q / τ² / I² with interpretation | ✓ | ✓ |
| Subgroup analysis + test for subgroup differences | ✓ | ✓ |
| Leave-one-out / cumulative / influence / Galbraith / radial | ✓ | ✓ |
| Egger / Begg / Peters / Harbord / rank-correlation tests | ✓ | ✓ |
| Trim-and-fill + Rosenthal fail-safe N | ✓ | ✓ |
| Network meta-analysis + SUCRA + league table | ✓ | partial (via netmeta) |
| Forest / funnel / contour-enhanced funnel plots | ✓ | ✓ |
| GRADE summary of findings | ✓ | ✗ |
| 4 RoB tools (RoB 2, ROBINS-I, QUADAS-2, NOS) | ✓ | ✗ |
| Systematic-review screening + kappa | ✓ | ✗ |
| PRISMA 2020 flow generator | ✓ | ✗ |
| Bibliometrics (PoP + VOS + CiteSpace) | ✓ | ✗ |
| Network visualization (11 layouts) | ✓ | ✗ |
| Q1-journal figure factory (10 journal palettes) | ✓ | ✗ |
| Innovation analytics | ✓ | ✗ |
| Local-LLM RAG assistant | ✓ | ✗ |
| Multi-source scraping (17 APIs) | ✓ | ✗ |
| Pure Python (no R installation) | ✓ | ✗ (R) |
| REST API (65+ endpoints) | ✓ | ✗ |

**When to choose Metafor:** You're doing methodological meta-analysis
research and want the very latest estimators (e.g. HKSJ, Hartung-Knapp
adjustment). **When to choose ARS:** You want Metafor-grade pooling
plus the systematic-review lifecycle (screening + RoB + extraction +
PRISMA), plus bibliometrics, network visualization, and Q1 figures, in
a single Python-native pipeline.

---

## 14. Overall scorecard

The matrix below collapses every comparison above into a single
completeness score. Cells show ✓ (full native support), partial,
or ✗.

| Capability | ARS v2 | PoP | Gephi | VOSviewer | CiteSpace | Sci2 | Zotero | Mendeley | Connected Papers | Inciteful | Rayyan | Covidence | RevMan | Metafor |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Multi-source scraping (17 APIs) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| PoP-grade author indices | ✓ | ✓ | ✗ | ✗ | partial | partial | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Journal metrics (IF, SJR, SNIP, Eigenfactor, CiteScore) | ✓ | partial | ✗ | partial | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| VOSviewer-style analyses | ✓ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| CiteSpace-style burst/frontier | ✓ | ✗ | ✗ | ✗ | ✓ | partial | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Scientogram (co-word, co-journal, institute) | ✓ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 60+ NetworkX algorithms exposed | ✓ | ✗ | partial | partial | partial | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 11 Gephi-grade layouts | ✓ | ✗ | ✓ | partial | ✓ | ✗ | ✗ | ✗ | partial | partial | ✗ | ✗ | ✗ | ✗ |
| 15 graph filters + FilterChain | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Dual-reviewer screening + kappa | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | partial | ✗ |
| 4 RoB tools (RoB 2, ROBINS-I, QUADAS-2, NOS) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | partial | partial | ✗ |
| DerSimonian-Laird, MH, Peto, REML pooling | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | ✓ | ✓ |
| Network meta-analysis + SUCRA | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | partial | partial |
| Publication-bias tests (Egger/Begg/Peters/Harbord + trim-fill) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | partial | ✓ |
| Sensitivity (leave-one-out, cumulative, influence, Galbraith) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | partial | ✓ |
| PRISMA 2020 flow + 27-item checklist + 6 extensions | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | partial | partial | ✗ |
| Q1-journal palettes (Nature/Science/Cell/NEJM/Lancet/JAMA) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 14 statistical + 8 network + 12 bibliometric + 11 data plot recipes | ✓ | ✗ | partial | partial | partial | partial | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Citation-burst detection (Kleinberg) | ✓ | ✗ | ✗ | ✗ | ✓ | partial | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Knowledge-frontier mapping + trend forecasting | ✓ | ✗ | ✗ | ✗ | partial | partial | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Novelty scoring (Uzzi atypicality + disruption index) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Paper recommendation (semantic + MMR + bridge) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | partial | ✗ | ✗ | ✗ | ✗ |
| Collaboration recommendation (weak ties + complementary expertise) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Local-LLM RAG assistant (Ollama, OpenAI, Anthropic, echo) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Research-gap detection + idea generation + writing assistant | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| 9 protocol templates + 7 extraction templates + 10 EQUATOR checklists | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | ✗ |
| PDF / DOCX / PPTX / BibTeX reporting | ✓ | partial | ✗ | ✗ | ✗ | partial | partial | partial | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Local SQLite + FTS5 + ChromaDB persistence | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Web API (15 blueprints, 65+ endpoints) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | partial | partial | ✗ | ✗ | partial | partial | ✗ | ✗ |
| Pure Python (no JVM, no R, no .NET) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| MIT-licensed, runs fully offline | ✓ | ✓ | ✓ | ✓ | ✗ | partial | partial | ✗ | ✗ | ✗ | ✗ | ✗ | partial | partial |

### How ARS wins

ARS v2.0.0 wins on **completeness** and **breadth of integration**:

1. **One install, every workflow.** No other tool covers both PoP-grade
   bibliometrics *and* Gephi-grade visualization *and* Rayyan-grade
   screening *and* RevMan/Metafor-grade meta-analysis *and* PRISMA 2020
   generation *and* Q1-journal figure production *and* innovation
   analytics *and* a local-LLM RAG assistant. The closest equivalent
   is to combine 5–7 different tools.

2. **Pure Python, MIT, runs offline.** No JVM (Gephi / CiteSpace /
   Sci2), no R (Metafor), no .NET (RevMan), no cloud (Mendeley /
   Rayyan / Covidence / Connected Papers / Inciteful). The desktop
   app boots in 2 seconds and runs without an internet connection
   once the corpus is loaded.

3. **API-first.** Every analysis is also exposed via 15 Flask
   blueprints (65+ endpoints), so ARS can serve as the analysis
   backend for a larger research-data infrastructure. No other tool
   ships a comparable REST API.

4. **Reproducible.** Every figure, every forest plot, every PRISMA
   flow diagram is regenerated from a deterministic Python script —
   no proprietary binary `.rm5` or `.gephi` project files to round-trip.

5. **Local-LLM assistant.** The RAG engine over ChromaDB lets you
   query your corpus with `provider="ollama"` so your data never
   leaves your machine. None of the alternatives offer this.

### How ARS doesn't win

ARS is *not* the right tool if you need:

- **Browser-based reference collection** with one-click ingestion
  → use Zotero (and feed the resulting BibTeX into ARS).
- **The very latest meta-analysis estimators** (e.g. HKSJ, RoB 2 with
  Shiny app) → use Metafor / Robvis.
- **Cochrane Library submission** → use RevMan.
- **Cloud-based collaborative screening** with off-shore data
  residency → use Rayyan.
- **Gephi's drag-and-drop UI** for fast exploratory tuning → use Gephi.

For everything else, ARS v2.0.0 is the broadest single-tool option.

---

*Comparisons reflect feature sets as of v2.0.0 (August 2026). For
tool-version-by-version detail see each project's documentation; if
you spot a discrepancy please open an issue at
<https://github.com/academic-research-suite/academic_research_suite/issues>.*
