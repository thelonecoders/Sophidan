# Contributing to Academic Research Suite

First off — **thank you** for taking the time to contribute! 🎉

Academic Research Suite (ARS) is a community-driven open-source
project released under the MIT license. This document explains how
to report bugs, propose features, submit pull requests, and what we
expect from contributors in terms of code style, tests, and
documentation.

> **Companion docs:** [docs/development.md](docs/development.md)
> (developer setup, extension tutorials),
> [docs/architecture.md](docs/architecture.md) (system overview),
> [docs/CODE_OF_CONDUCT.md](docs/CODE_OF_CONDUCT.md) (Code of
> Conduct).

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Reporting Bugs](#reporting-bugs)
3. [Suggesting Features](#suggesting-features)
4. [Submitting Pull Requests](#submitting-pull-requests)
5. [Code Style Requirements](#code-style-requirements)
6. [Testing Requirements](#testing-requirements)
7. [Documentation Requirements](#documentation-requirements)
8. [Review Process](#review-process)

---

## Code of Conduct

Participation in this project is governed by the
[Contributor Covenant 2.1](docs/CODE_OF_CONDUCT.md). By
participating you are expected to uphold this code. Please report
unacceptable behaviour to
<conduct@academic-research-suite.org>.

---

## Reporting Bugs

Bugs are tracked as [GitHub issues](https://github.com/academic-research-suite/academic_research_suite/issues).
Before opening a new issue:

1. **Search existing issues** — your bug may already be reported.
2. **Reproduce on `main`** — make sure the bug exists on the latest
   `main` branch, not just your local fork.
3. **Collect the diagnostics** — paste the output of:
   ```bash
   python main.py --version
   python -c "import sys, platform; print(sys.version, platform.platform())"
   curl -s http://127.0.0.1:8765/api/health | jq .   # if web mode
   ```

When you open the issue, use the **Bug Report** template and
include:

- **Summary** — one sentence describing the bug.
- **Steps to reproduce** — numbered list, copy-pasteable commands
  preferred.
- **Expected behavior** — what you expected.
- **Actual behavior** — what you saw (include stack traces,
  screenshots, log excerpts).
- **Environment** — OS, Python version, ARS version, Qt binding
  (`PyQt5` / `PySide2`), and any non-default config.
- **Logs** — relevant lines from `logs/ars.log` (paste, don't
  screenshot).

The more reproducible your report, the faster we can fix it.

---

## Suggesting Features

Feature requests are also tracked as GitHub issues (use the
**Feature Request** template). A good feature request:

1. **States the problem** — what are you trying to do that ARS
   currently makes hard or impossible?
2. **Describes the solution** — what would the ideal UX look like?
   Sketches / ASCII mockups welcome.
3. **Lists alternatives** — what workarounds have you tried?
4. **States the audience** — is this for a single researcher, a
   research group, or a course?

Features that fit ARS's scope (academic literature research,
scraping, analysis, knowledge graphs, AI assistance, reporting,
local-first desktop / local-server) are likely to be accepted.
Features that pull ARS towards SaaS, cloud lock-in, or non-MIT
dependencies are likely to be declined.

If you want to discuss before opening an issue, start a
[Discussion](https://github.com/academic-research-suite/academic_research_suite/discussions)
or drop by our community chat (link in the README).

---

## Submitting Pull Requests

We follow the standard fork → branch → PR workflow.

### 1. Fork & branch

```bash
gh repo fork academic-research-suite/academic_research_suite --clone
cd academic_research_suite
git checkout -b feat/my-feature develop
```

Branch off `develop` (the integration branch), not `main` (the
released branch). Use a descriptive branch name prefixed by
category:

- `feat/<short-desc>` — new feature.
- `fix/<short-desc>` — bug fix.
- `docs/<short-desc>` — documentation only.
- `refactor/<short-desc>` — refactor only, no behaviour change.
- `test/<short-desc>` — test-only.
- `chore/<short-desc>` — housekeeping (deps, CI config, etc.).

### 2. Make atomic commits

Use [Conventional Commits](https://www.conventionalcommits.org/)
prefixes:

```text
feat(scraper): add MySource scraper

Adds a new data_acquisition module that queries the MySource JSON
API. Wires it into the ScrapingEngine default registration, the
search panel source checkboxes, and the web /api/scraping/sources
fallback list. Closes #42.
```

Atomic commits — one logical change per commit. The commit body
should answer **why** rather than **what** (the diff already shows
the what).

### 3. Run CI checks locally

Before pushing:

```bash
black .
ruff check . --fix
pytest tests/
./scripts/smoke_test.sh
```

All four must be green. If you added a new module, also add it to
the `MODULES_TO_IMPORT` list in `tests/test_smoke.py` and the
`MODULES` heredoc in `scripts/smoke_test.sh` so the import sweep
covers every module.

### 4. Push & open a PR

```bash
git push -u origin feat/my-feature
gh pr create --fill
```

The PR description should include:

- **Summary** — what does this PR do?
- **Motivation** — link the issue(s): `Closes #42`.
- **Changes** — bullet list of the meaningful diffs.
- **Tests** — how did you verify? (e.g. "added
  `tests/test_mysource.py` with 8 cases").
- **Docs** — which docs did you update?

### 5. Address review feedback

Reviewers may request changes. Push more commits to the same
branch (don't force-push unless explicitly asked — we use
squash-merges so the final history is clean anyway).

---

## Code Style Requirements

ARS enforces a strict, modern Python style. The full guide is in
[docs/development.md#code-style](docs/development.md#code-style); the
short version:

- **PEP 8** + 100-column line length (enforced by `black` and
  `ruff`).
- **Type hints REQUIRED** on every public function signature.
  Internal helpers may omit them when the type is genuinely
  dynamic, but every public API surface must be annotated.
- **Google-style docstrings** on every public class and function
  with `Args:`, `Returns:`, `Raises:` sections where applicable.
- **Lazy imports** for heavy / optional deps (selenium,
  sentence-transformers, bertopic, chromadb, hdbscan, umap-learn,
  pyLDAvis, openai, anthropic, ollama, etc.). Move them inside the
  function body, never at module scope. Every module must remain
  importable even when its heaviest optional dep is missing.
- **No `print()` in production code.** Use
  `logging.getLogger(__name__)`. The only exception is the
  interactive banner in `main.py`.
- **Module header** — every `.py` file starts with the module
  docstring and the MIT header:
  ```python
  """<one-paragraph module docstring>"""
  #
  # MIT License — Academic Research Suite
  # Copyright (c) 2026 — see /LICENSE for full text.
  #
  ```

### Format & lint config

`pyproject.toml` configures `black`, `ruff`, and `mypy`. Run:

```bash
black .                    # format
ruff check . --fix         # lint + auto-fix
mypy .                     # type-check (best-effort)
```

`mypy` runs in `ignore_missing_imports=true` mode — third-party
stubs are not required, but ARS-authored signatures must be
annotated.

---

## Testing Requirements

**New code MUST include tests.** Coverage is reviewed on every
PR; we don't enforce a percentage threshold, but every new public
function or class must have at least one test that exercises its
happy path.

### Test layout

- `tests/test_smoke.py` — 117-case hermetic suite covering module
  imports, DB init, web endpoints, MainWindow launch, and
  cross-module integration.
- Per-feature tests live in `tests/test_<feature>.py`. Use
  `pytest` fixtures, classes for grouping, and the standard
  `assert` statement.

### Test conventions

1. **Hermetic** — no network, no API keys. Use
   `LLMClient(provider="none")` for AI tests; use
   `tmp_path` for filesystem tests; use
   `DatabaseConnection(db_path=str(tmp_path / "test.db"))`
   for DB tests.
2. **Offscreen Qt** — `tests/test_smoke.py` already sets
   `QT_QPA_PLATFORM=offscreen` and `MPLBACKEND=Agg`; per-feature
   tests inherit these via `conftest.py`.
3. **No sleeps** — never `time.sleep(...)` to wait for async work;
   use `WorkerPool.wait_all(timeout_ms=...)` or
   `Future.result(timeout=...)` instead.

### Running tests

```bash
pytest tests/                          # full suite
pytest tests/test_smoke.py -v          # verbose
pytest tests/test_smoke.py::test_db    # single test
pytest tests/ --cov=. --cov-report=term-missing
./scripts/smoke_test.sh                # full smoke
```

CI runs `pytest tests/` and `./scripts/smoke_test.sh` on every
PR. Both must pass.

---

## Documentation Requirements

**Every user-visible feature must be reflected in documentation.**
At minimum:

- **README.md** — add a row to the relevant Features table
  (Data Acquisition / Proxy / Data Science / Knowledge Graphs /
  AI Assistant / Reporting / Project Management / Database /
  Web Server).
- **docs/user_guide.md** — add a subsection under the relevant
  page walkthrough.
- **docs/CHANGELOG.md** — add an entry under `[Unreleased]` →
  `Added` / `Changed` / `Fixed` / `Removed` / `Deprecated`.
- **docs/api_reference.md** — if you added or changed a REST
  endpoint, document it with method, path, request schema,
  response schema, status codes, and an example.

For internal refactors that don't change user-visible behaviour,
a CHANGELOG entry under `Changed` is sufficient; no README or
user_guide update is needed.

### Doc style

- Match the user's language (English in v1.0.0; 简体中文
  translation tracked under [v1.2.0 roadmap](README.md#roadmap)).
- Use proper Markdown — headings, tables, code blocks with
  language tags, lists, blockquotes.
- Every code example must be runnable (no placeholder Python that
  wouldn't execute).
- Link between docs using relative paths
  (e.g. `[architecture](docs/architecture.md)`).
- For Mermaid diagrams, use ` ```mermaid ` code fences.
- For directory trees, use ` ```text ` code fences.
- Be **accurate** — if you don't know a class's exact API, look
  it up via Grep or describe it at a high level without inventing
  method names. Zero hallucination.

---

## Review Process

### What reviewers look for

1. **Correctness** — does the change do what the PR description
   claims? Are edge cases handled?
2. **Tests** — are there tests? Do they pass? Do they cover the
   happy path and at least one failure mode?
3. **Style** — black, ruff, type hints, docstrings, lazy imports.
4. **Docs** — README / user_guide / CHANGELOG updated where
   applicable.
5. **Scope** — is the PR focused on one logical change? If you
   bundled five unrelated fixes, split into five PRs.
6. **Backwards compatibility** — does the PR break any public
   API? If so, call it out in the PR description and consider a
   deprecation cycle.

### Approvals & merge

- **Two maintainer approvals** required for `develop`.
- **One maintainer approval** sufficient for documentation-only
  PRs.
- **Squash-merge** is the default — the PR's commits are squashed
  into one on `develop`. Force-push to your branch is fine during
  review.
- **Release branch** — `main` is updated from `develop` on each
  tagged release; never commit directly to `main`.

### Release cycle

- PRs merge into `develop`.
- Roughly monthly, `develop` is tagged as `vX.Y.0` and merged to
  `main`. See [docs/CHANGELOG.md](docs/CHANGELOG.md) for the
  cadence.
- Bug-fix releases (`vX.Y.Z` with Z > 0) are cut from `main`
  branches off the relevant tag.

---

## Quick Reference

| Task | Where to look |
|---|---|
| Set up dev environment | [docs/development.md#development-environment-setup](docs/development.md#development-environment-setup) |
| Add a scraper | [docs/development.md#adding-a-new-scraper](docs/development.md#adding-a-new-scraper) |
| Add an analysis | [docs/development.md#adding-a-new-analysis](docs/development.md#adding-a-new-analysis) |
| Add a report format | [docs/development.md#adding-a-new-report-format](docs/development.md#adding-a-new-report-format) |
| Add an AI provider | [docs/development.md#adding-a-new-ai-provider](docs/development.md#adding-a-new-ai-provider) |
| Debug something | [docs/development.md#debugging-tips](docs/development.md#debugging-tips) |
| Run tests | [docs/development.md#testing](docs/development.md#testing) |
| Build a binary | [docs/development.md#building-the-desktop-binary](docs/development.md#building-the-desktop-binary) |
| Cut a release | [docs/development.md#releasing](docs/development.md#releasing) |

---

*Happy hacking! If you get stuck, open a
[Discussion](https://github.com/academic-research-suite/academic_research_suite/discussions)
or ping us in the issue tracker.*
