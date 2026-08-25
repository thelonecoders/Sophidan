# Developer Guide

> **Audience:** contributors to Academic Research Suite (ARS).
> **Companion docs:** [architecture.md](architecture.md) (system
> overview), [api_reference.md](api_reference.md) (REST reference),
> [CONTRIBUTING.md](../CONTRIBUTING.md) (PR workflow).

This document explains how to set up a development environment,
the code style we enforce, the layout of the source tree, and how
to extend ARS by adding new scrapers, analyses, report formats,
and AI providers.

---

## Table of Contents

1. [Development Environment Setup](#development-environment-setup)
2. [Code Style](#code-style)
3. [Project Layout](#project-layout)
4. [Adding a New Scraper](#adding-a-new-scraper)
5. [Adding a New Analysis](#adding-a-new-analysis)
6. [Adding a New Report Format](#adding-a-new-report-format)
7. [Adding a New AI Provider](#adding-a-new-ai-provider)
8. [Testing](#testing)
9. [Building the Desktop Binary](#building-the-desktop-binary)
10. [Releasing](#releasing)
11. [Debugging Tips](#debugging-tips)
12. [Contributing Workflow](#contributing-workflow)

---

## Development Environment Setup

```bash
# 1. Clone
git clone https://github.com/academic-research-suite/academic_research_suite.git
cd academic_research_suite

# 2. Create venv (Python 3.10+)
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate

# 3. Install runtime deps
pip install -r requirements.txt

# 4. Install dev tooling (pytest, black, ruff, mypy, pytest-qt, pytest-cov)
pip install -e ".[dev]"

# 5. Verify
pytest tests/                       # 117 cases pass
./scripts/smoke_test.sh             # full end-to-end smoke
python main.py --version            # prints version banner
```

The dev extras (defined in `pyproject.toml` under
`[project.optional-dependencies].dev`) are:

- `pytest>=8.0`, `pytest-qt>=4.3`, `pytest-cov>=4.1` — testing.
- `black>=24.2`, `ruff>=0.3`, `mypy>=1.9` — formatting, linting, type-checking.

### Headless Qt for CI

Set these env vars so Qt and matplotlib don't try to open a window:

```bash
export QT_QPA_PLATFORM=offscreen
export MPLBACKEND=Agg
```

Both are already set inside `tests/test_smoke.py` and
`scripts/smoke_test.sh`.

---

## Code Style

ARS follows a strict, modern Python style. Every PR is checked by
the CI workflow described in [Contributing Workflow](#contributing-workflow).

### PEP 8 + line length 100

`pyproject.toml` configures `black` and `ruff` to a 100-column
line length:

```toml
[tool.black]
line-length = 100
target-version = ["py310", "py311", "py312"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP"]
ignore = ["E501"]   # black handles line wrapping; ruff E501 disabled
```

Run the formatters before committing:

```bash
black .
ruff check . --fix
```

### Type hints REQUIRED on every public function signature

Every public function and method must declare its parameter and
return types. `mypy` runs in `ignore_missing_imports=true` mode
(we don't want to ship third-party stubs) but every ARS-authored
signature must be annotated.

```python
def search(self, query: str, *, max_results: int = 25) -> ScraperResult:
    ...
```

### Google-style docstrings

Every public class and function must carry a Google-style
docstring. Example:

```python
def build(self, papers: List[Paper]) -> nx.DiGraph:
    """Build the citation graph from a list of papers.

    Args:
        papers: List of :class:`Paper` objects. Each paper's
            ``references`` attribute is interpreted as the list
            of DOIs / source-IDs it cites.

    Returns:
        A directed :class:`networkx.DiGraph` with one node per
        paper and one edge per citation.

    Raises:
        ValueError: If two papers share the same DOI.
    """
```

### Lazy imports for heavy / optional deps

Third-party modules that are *optional* (selenium, sentence-transformers,
bertopic, chromadb, hdbscan, umap-learn, pyLDAvis, openai, anthropic,
ollama, etc.) MUST be imported lazily inside the function body, never
at module scope. This guarantees `python -c "import <pkg>"` never
raises on a minimal install.

```python
# GOOD
def cluster(self, papers, method="kmeans"):
    from sklearn.cluster import KMeans   # lazy
    ...

# BAD
from sklearn.cluster import KMeans      # at module scope — fails if sklearn missing
```

For the same reason, every `__init__.py` uses PEP 562
`__getattr__` to defer sub-module imports.

### No `print()` in production code

Use `logging.getLogger(__name__)` exclusively. The `print()`
function is reserved for the entry-point banner in `main.py`
(interactive use only).

### Module header

Every `.py` file starts with the module docstring and the MIT
header:

```python
"""<one-paragraph module docstring>"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
```

---

## Project Layout

Refer to [architecture.md](architecture.md) for the full module
dependency graph and component descriptions. The 30 000-foot view:

```text
academic_research_suite/
├── main.py                       Entry point (--web or desktop)
├── config/                       Settings + YAML loader
├── core/                         Orchestrator · TaskQueue · EventBus
├── utils/                        logger · cache · workers · config_manager
├── data_acquisition/             9 scrapers + ScrapingEngine
├── proxy/                        6-module proxy suite
├── data_science/                 7 modules: topics, clustering, ...
├── knowledge_graph/              5 modules: citation, collaboration, ...
├── ai_assistant/                 5 modules: llm_client, rag, ...
├── reporting/                    7 modules: pdf, docx, pptx, ...
├── project_management/           4 modules
├── database/                     4 modules: models, connection, ...
├── ui/                           main_window + widgets/ + dialogs/
├── web/                          Flask app + 8 route blueprints
├── tests/                        test_smoke.py (117 cases)
├── scripts/                      smoke_test.sh
└── docs/                         this directory
```

Every top-level package is **independently importable**. To verify
this invariant, run:

```bash
python -c "import config, core, utils, data_acquisition, proxy, \
data_science, knowledge_graph, ai_assistant, reporting, \
project_management, database, ui, web"
```

---

## Adding a New Scraper

This is the canonical extension point. The same pattern applies to
adding a new analysis, report format, or AI provider — see the
sections below.

### Step 1 — Subclass `BaseScraper`

Create `data_acquisition/my_source_scraper.py`:

```python
"""Scraper for the MySource academic API."""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from typing import Any, List, Optional

from .base_scraper import BaseScraper, Paper, ScraperResult

logger = logging.getLogger(__name__)


class MySourceScraper(BaseScraper):
    """Scraper for MySource.

    The MySource API is a JSON REST API at https://api.mysource.org/v1
    with no required API key (rate-limited to 5 req/s in the polite pool).
    """

    SOURCE_NAME = "mysource"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(rate_limit=5.0, **kwargs)

    def search(self, query: str, **kwargs: Any) -> ScraperResult:
        """Search MySource for papers matching ``query``.

        Args:
            query: Search string.
            **kwargs: ``max_results`` (default 25), ``year_lo``,
                ``year_hi``.

        Returns:
            A :class:`ScraperResult`.
        """
        max_results = int(kwargs.get("max_results", 25))
        params = {"q": query, "limit": max_results}
        resp = self._make_request(
            "GET", "https://api.mysource.org/v1/search",
            params=params, cache_key=f"mysource:{query}:{max_results}",
        )
        data = self._handle_response(resp)
        papers: List[Paper] = []
        for item in data.get("results", []):
            papers.append(Paper(
                title=item["title"],
                authors=[a["name"] for a in item.get("authors", [])],
                year=item.get("year"),
                doi=item.get("doi"),
                abstract=item.get("abstract", ""),
                source=self.SOURCE_NAME,
                external_id=str(item["id"]),
                citation_count=item.get("citation_count", 0),
                raw_payload=item,
            ))
        return ScraperResult(
            source=self.SOURCE_NAME, query=query,
            total_results=data.get("total", len(papers)),
            papers=papers, raw_response=data,
        )

    def fetch_by_id(self, paper_id: str) -> Optional[Paper]:
        """Fetch a single paper by MySource ID."""
        resp = self._make_request(
            "GET", f"https://api.mysource.org/v1/papers/{paper_id}",
            cache_key=f"mysource:id:{paper_id}",
        )
        item = self._handle_response(resp)
        if not item:
            return None
        return Paper(
            title=item["title"],
            authors=[a["name"] for a in item.get("authors", [])],
            year=item.get("year"),
            doi=item.get("doi"),
            abstract=item.get("abstract", ""),
            source=self.SOURCE_NAME,
            external_id=str(item["id"]),
            raw_payload=item,
        )
```

### Step 2 — Register with `ScrapingEngine`

Either manually in your own code:

```python
from data_acquisition.scraping_engine import ScrapingEngine
from data_acquisition.my_source_scraper import MySourceScraper

engine = ScrapingEngine()
engine.register_scraper("mysource", MySourceScraper())
```

Or as a default by editing the engine factory in `web/server.py`
and `ui/widgets/search_panel.py` — both have a list of default
scrapers they register on first use.

### Step 3 — Add a UI source checkbox

In `ui/widgets/search_panel.py`, `SearchPanel._build_source_checkboxes`
defines the source list. Add `("mysource", "MySource")` to the
list. The checkbox is rendered automatically.

### Step 4 — Add a web route entry

In `web/routes/scraping.py::_default_scrapers`, add a new entry:

```python
{"name": "mysource", "display": "MySource",
 "supports": ["search", "metadata"],
 "rate_limit": "5 req/s", "requires_proxy": False},
```

### Step 5 — Write tests

Create `tests/test_mysource.py`:

```python
"""Tests for MySourceScraper."""
from data_acquisition.my_source_scraper import MySourceScraper


def test_source_name():
    assert MySourceScraper().name == "mysource"

def test_search_returns_scraper_result(monkeypatch):
    # Patch BaseScraper._make_request to return a canned response
    ...
```

Add the module to the `MODULES_TO_IMPORT` list in
`tests/test_smoke.py` and to the same list in
`scripts/smoke_test.sh` so the import-sweep covers every module.

### Step 6 — Document

Update the README's [Features → Data Acquisition](../README.md#data-acquisition)
table, and add a row to the Web API Reference table if you added a
new endpoint.

---

## Adding a New Analysis

### Step 1 — Implement the analyzer

Create `data_science/my_analysis.py`:

```python
"""My custom analysis — network influence scoring."""
from __future__ import annotations
from typing import List
from data_acquisition.base_scraper import Paper


class NetworkInfluenceAnalyzer:
    """Compute a per-paper influence score from the citation network."""

    def __init__(self, db=None) -> None:
        self.db = db

    def analyze(self, project_id: int, **kwargs) -> dict:
        """Run the analysis.

        Args:
            project_id: Project whose papers to analyze.
            **kwargs: ``decay=0.85`` (PageRank damping).

        Returns:
            ``{"scores": {paper_id: float}, "top": [(paper_id, score)]}``.
        """
        from knowledge_graph import CitationGraph   # lazy
        papers = self._load_papers(project_id)
        graph = CitationGraph().build(papers)
        scores = graph.pagerank(alpha=kwargs.get("decay", 0.85))
        return {
            "scores": scores,
            "top": sorted(scores.items(), key=lambda kv: -kv[1])[:10],
        }

    def _load_papers(self, project_id: int) -> List[Paper]:
        ...
```

### Step 2 — Wire into `AnalysisViewWidget`

In `ui/widgets/analysis_view.py`, add a new entry to the analysis-type
combo box (`"Network Influence"`) and extend the dispatch table that
maps the selected analysis type to its implementation class. The
widget already lazy-imports the heavy modules.

### Step 3 — Add a web route (optional)

In `web/routes/analytics.py`, add:

```python
@analytics_bp.route("/influence", methods=["POST"])
def influence():
    payload = request.get_json(silent=True) or {}
    project_id = payload.get("project_id")
    result, err = _run_analysis(
        "data_science.my_analysis", "NetworkInfluenceAnalyzer",
        project_id=project_id,
    )
    if err:
        return jsonify({"error": "analysis_failed", "message": err}), 502
    return jsonify({"project_id": project_id, "result": result})
```

### Step 4 — Tests + docs

Add tests, add the module to the import sweep, update the README's
Data Science feature table.

---

## Adding a New Report Format

### Step 1 — Implement the report class

Create `reporting/markdown_report.py`:

```python
"""Markdown report generator."""
from __future__ import annotations
import io
from typing import Any


class MarkdownReport:
    """Generate a Markdown report for a project."""

    def __init__(self, project_manager, db) -> None:
        self.pm = project_manager
        self.db = db

    def generate(self, project_id: int, sections=None) -> io.BytesIO:
        """Generate the report.

        Args:
            project_id: Project ID.
            sections: Optional list of section names
                (default: ``["summary", "papers"]``).

        Returns:
            A :class:`io.BytesIO` containing the Markdown text.
        """
        sections = sections or ["summary", "papers"]
        buf = io.BytesIO()
        ...
        return buf
```

### Step 2 — Register in `ReportingDashboard`

In `ui/dialogs/reporting_dashboard.py`, extend the Step 1 report-type
list and the dispatch table that maps type → (module_path, class_name).

### Step 3 — Add a web route entry

In `web/routes/export.py::export_report`, extend the `module_map` dict:

```python
"markdown": ("reporting.markdown_report", "MarkdownReport",
              "text/markdown", "report.md"),
```

### Step 4 — Tests + docs

Same as before — add tests, add to import sweep, update README.

---

## Adding a New AI Provider

### Step 1 — Add to `LLMProvider` enum

In `ai_assistant/llm_client.py`:

```python
class LLMProvider(Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    NONE = "none"
    MISTRAL = "mistral"   # new
```

### Step 2 — Implement the provider-specific methods

Inside `LLMClient`, add a `_mistral_chat` method that lazy-imports
the Mistral SDK and implements the provider-specific request. Wire
it into the dispatch in `_sync_chat` and `_stream_chat`.

```python
def _mistral_chat(self, messages, temperature=0.7, max_tokens=2000, stream=False):
    from mistralai.client import MistralClient  # lazy
    client = MistralClient(api_key=self.api_key)
    ...
```

### Step 3 — Add string aliases

Update the `_PROVIDER_ALIASES` dict so that `"mistral"` and
`"mistral-large"` map to `LLMProvider.MISTRAL`.

### Step 4 — Tests + docs

Add a smoke test that constructs `LLMClient(provider="mistral")`
with a fake key and verifies the alias resolution. Update the
README's API Key Setup section.

---

## Testing

### Running the suite

```bash
# Full suite
pytest tests/

# Verbose
pytest tests/test_smoke.py -v

# A specific test
pytest tests/test_smoke.py::test_database_init

# Coverage (requires pytest-cov)
pytest tests/ --cov=. --cov-report=term-missing --cov-report=html
```

### Test conventions

- Every test must be hermetic — no network, no API keys. Use
  `LLMClient(provider="none")` for AI tests.
- Every DB-touching test uses its own `tmp_path` and an isolated
  `DatabaseConnection` keyed by URL.
- Offscreen Qt is set in `tests/test_smoke.py` via
  `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`.
- New code MUST include tests; coverage is reviewed on every PR.

### Smoke runner

`./scripts/smoke_test.sh` runs four stages:

1. Import every public module (catches circular imports + missing
   optional deps).
2. `pytest tests/test_smoke.py -q`.
3. Boot the Flask test client and ping `/api/health`, `/api/papers/`,
   `/api/projects/`, `/api/proxy/stats`, `/`.
4. Launch the PyQt5 `MainWindow` offscreen, `show()`, `close()`.

Exit 0 means all four stages passed. Use `--quick` to skip the
import sweep.

### Writing a new test file

```python
"""Tests for my new feature."""
from __future__ import annotations

import pytest

from data_acquisition.my_source_scraper import MySourceScraper


class TestMySourceScraper:
    """Unit tests for MySourceScraper."""

    def test_source_name(self):
        assert MySourceScraper().name == "mysource"

    def test_search_returns_scraper_result(self, monkeypatch):
        scraper = MySourceScraper()
        # Patch _make_request to return a fake response
        ...
```

Add the new file to `tests/` — pytest discovers it automatically
via `testpaths = ["tests"]` in `pyproject.toml`.

---

## Building the Desktop Binary

ARS can be packaged as a single-file executable with PyInstaller.
A canonical `main.spec` file is on the v1.1.0 roadmap; until then,
use the following recipe:

```bash
pip install pyinstaller

pyinstaller \
  --name "academic-research-suite" \
  --windowed \
  --onedir \
  --add-data "config/default_config.yaml:config" \
  --add-data "ui:ui" \
  --add-data "web/templates:web/templates" \
  --hidden-import qtpy \
  --hidden-import PyQt5 \
  main.py

# The bundled app lands in dist/academic-research-suite/
```

**Notes:**

- `--onedir` is preferred over `--onefile` for a project this
  size; startup time is much better and debugging is easier.
- Use `--add-data` for every non-Python file (YAML, QSS, HTML
  templates). The syntax is `source:dest` (Linux/macOS) or
  `source;dest` (Windows).
- Hidden imports are needed for any package that's loaded lazily
  via `importlib.import_module` — PyInstaller's static analyzer
  won't see them.
- A formal `main.spec` will be added in v1.1.0; tracked under
  [Roadmap in README](../README.md#roadmap).

---

## Releasing

The release process is automated but human-gated.

### Versioning

ARS follows [Semantic Versioning](https://semver.org/):

- **Patch** (`v1.0.1`): bug fixes only, no API changes.
- **Minor** (`v1.1.0`): backwards-compatible features.
- **Major** (`v2.0.0`): breaking changes.

The version is recorded in three places:

1. `pyproject.toml` → `version = "1.0.0"`.
2. `config/default_config.yaml` → `version: "1.0.0"`.
3. `docs/CHANGELOG.md` → new entry on release day.

The `main.py` module declares `__version__ = "0.1.0"` for the
desktop banner — keep this in sync on release.

### Release checklist

1. Update version in `pyproject.toml` and
   `config/default_config.yaml`.
2. Update `docs/CHANGELOG.md` with the new section under
   `Added` / `Changed` / `Fixed` / `Removed` / `Deprecated`.
3. Run the full test suite + smoke tests on all three platforms
   (Linux, macOS, Windows).
4. `git tag vX.Y.Z` and `git push --tags`.
5. (Future) Build sdist + wheel:
   ```bash
   python -m build
   twine upload dist/*
   ```
   PyPI publication is **TBD** — v1.0.0 is shipped as a GitHub
   source release only.

### Branching

- `main` — the released branch. Tags are cut here.
- `develop` — integration branch for the next release.
- Feature branches: `feat/<short-desc>`, `fix/<short-desc>`,
  `docs/<short-desc>`.

---

## Debugging Tips

### Verbose logging

```bash
ARS_LOG_LEVEL=DEBUG python main.py
```

Or edit `config/secrets.yaml`:

```yaml
log_level: "DEBUG"
```

Logs land in `logs/ars.log` (rotating, 2 MB × 5 backups) and on
stderr.

### Qt verbose logging

```bash
QT_LOGGING_RULES='*=true' python main.py
```

Dumps every Qt-internal log line. Useful for tracking down
widget lifecycle bugs.

### Flask debug mode

```bash
python main.py --web --debug
```

Enables the Werkzeug reloader + interactive debugger. The
debugger is **insecure** — only use on `127.0.0.1`.

### The `--debug` CLI flag

The desktop mode currently treats `--debug` as a pass-through to
`Logging.basicConfig(level=DEBUG)`. Web mode passes it to
`socketio.run(debug=True)`.

### Live log viewer

`Status bar → Logs` button opens a `LogViewer` widget — a
10 000-line ring buffer attached to the root logger. Useful when
you don't want to leave a terminal open.

### Database inspection

```bash
sqlite3 data/ars.db
> .tables
> SELECT COUNT(*) FROM papers;
> SELECT * FROM papers_fts WHERE papers_fts MATCH 'transformer';
```

To re-init the FTS index after a manual DB edit, run
`Settings → Database → Rebuild FTS Index` (calls
`FullTextSearch.rebuild_index()`).

### Web API inspection

Open <http://127.0.0.1:8765/api/docs> for the live HTML API docs,
or `curl http://127.0.0.1:8765/api/health | jq .` for the per-module
health report.

---

## Contributing Workflow

We follow the standard fork → branch → PR workflow.

### 1. Fork & branch

```bash
gh repo fork academic-research-suite/academic_research_suite --clone
cd academic_research_suite
git checkout -b feat/my-feature develop
```

### 2. Commit

Use [Conventional Commits](https://www.conventionalcommits.org/)
prefixes:

- `feat(scraper): add MySource scraper` — new feature.
- `fix(proxy): retry on ECONNRESET` — bug fix.
- `docs(readme): document new env var` — documentation.
- `refactor(core): extract SignalHub into its own class` — refactor.
- `test(ai): add chat_engine tests` — test-only.
- `chore(deps): bump pandas to 2.2.2` — housekeeping.

Atomic commits — one logical change per commit. Each commit message
body should answer "why?" rather than "what?" (the diff already
shows the what).

### 3. Push & open a PR

```bash
git push -u origin feat/my-feature
gh pr create --fill
```

### 4. CI checks

The CI workflow runs on every PR:

- `black --check .`
- `ruff check .`
- `pytest tests/`
- `./scripts/smoke_test.sh`

All four must be green before merge.

### 5. Review

Two maintainer approvals are required for `develop`. Squash-merges
are the default. The PR description should reference the issue
(e.g. `Closes #42`) so the issue auto-closes on merge.

### 6. Update docs

Every PR that adds a user-visible feature must update:

- `README.md` — feature table + usage example.
- `docs/user_guide.md` — walkthrough.
- `docs/CHANGELOG.md` — entry under `Added` / `Changed` / `Fixed`.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full contribution
guidelines and code of conduct.

---

*For implementation-level details not covered here, see the
module docstrings in the source tree — every public class and
function is documented in Google style.*
