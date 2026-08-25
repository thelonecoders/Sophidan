# Git History — Academic Research Suite

> This document records the version-control strategy, the full annotated commit
> log, the release tags, and a step-by-step reproduction guide for the
> `v1.0.0` build of the Academic Research Suite.
>
> **Repository:** `/home/z/my-project/download/academic_research_suite/`
> **Branch:** `main`  ·  **Total commits at v1.0.0:** 18
> (17 functional commits + 1 git-history documentation commit)
> **Tags:** `v0.1.0` (alpha), `v0.2.0` (beta), `v1.0.0` (stable)

---

## 1. Strategy

The Academic Research Suite repository was built with an **atomic-commit-per-
module** strategy: each of the 14 sub-agent task outputs was committed as its
own self-contained, conventional-commit-formatted change set. This produces a
linear history that mirrors the orchestrated build plan documented in
[`WORKLOG.md`](./WORKLOG.md), so a future maintainer can read `git log` and
see exactly which agent produced which slice of the codebase.

### 1.1 Conventional-commit format

Every commit follows [Conventional Commits 1.0](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

<body — 2-5 sentences explaining what was added, why, and how it integrates>

Refs: Task ID <X> (built by sub-agent <name>)
```

Types used in this release:

| Type      | Count | Meaning                                                  |
| --------- | ----- | -------------------------------------------------------- |
| `chore`   | 3     | Repo bootstrap, worklog finalization, git-history doc    |
| `feat`    | 12    | One per module/sub-system added by a sub-agent           |
| `test`    | 1     | Smoke test suite + validation framework                  |
| `fix`     | 0     | (Commit 16 was a no-op — validation fixes were already  |
|           |       | absorbed into the module commits by the build order.)    |
| `docs`    | 2     | Documentation suite + this file                          |

### 1.2 Annotated tags

Three annotated tags (`git tag -a`) mark release milestones:

| Tag     | Commit | SHA         | Milestone                                                |
| ------- | ------ | ----------- | -------------------------------------------------------- |
| v0.1.0  | 5      | `04df31c`   | Alpha: core infrastructure + first 5 scrapers           |
| v0.2.0  | 14     | `303aca6`   | Beta: full feature set (all 14 top-level packages)       |
| v1.0.0  | HEAD   | (latest)    | First stable release: validated, documented, MIT-licensed |

Annotated tags were chosen over lightweight tags because they carry a tag
message, a tagger identity, and a timestamp — preserving a forensic record of
each release milestone for future auditing.

### 1.3 Branching strategy

For the v1.0 release the repository used a **single-branch (`main`) flow**.
This is appropriate for a one-shot orchestrated build where every commit is
already reviewed-and-validated by the corresponding sub-agent's task spec.

**For future development** the project should adopt
[GitHub Flow](https://docs.github.com/en/get-started/quickstart/github-flow)
with a long-lived `develop` branch:

```
main          ──●─────●─────●── ← only release commits, always shippable
                 │     │     │
develop    ────●─●──●─●─●───●─●── ← integration branch
                │   │   │     │
feature/X      ●─●   │   │     │   ← one branch per feature/fix
                    ●─●       ●─●
```

Recommended branch naming:
- `feature/<short-name>` — new capability (e.g. `feature/crossref-doi-batch`)
- `fix/<issue-number>` — bug fix
- `docs/<topic>` — documentation-only changes
- `release/v<MAJOR>.<MINOR>.<PATCH>` — release-stabilization branch

Conventional-commit subjects drive automatic semantic-version bumping when
combined with a tool like [`release-please`](https://github.com/googleapis/release-please)
or [`semantic-release`](https://github.com/semantic-release/semantic-release).

---

## 2. Full commit log

`git log --oneline --decorate --graph` (captured at v1.0.0):

```
* 3f43e2a (HEAD -> main, tag: v1.0.0) chore: add worklog and finalize v1.0.0
* 55e31fc docs: add README, architecture, user guide, dev guide, API reference, CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, INSTALL, FAQ, INNOVATION
* bd8384c test: add smoke tests and validation framework
* 303aca6 (tag: v0.2.0) feat(web): add Flask web server, REST API, WebSocket bridge, and dashboard templates
* b0dbf27 feat(ui): add search, network, analysis, AI chat, proxy, project explorer, settings panels + dialogs
* 82f361a feat(ui): add main window, modern theme, sidebar, dashboard, data view, welcome screen
* 9c69f4d feat(project-management): add project manager, workspace, snapshots, comparison
* 3b7d3b2 feat(database): add SQLAlchemy models, connection, FTS5 search, and vector store
* e4ef299 feat(reporting): add PDF, DOCX, PPTX, BibTeX, CSV exporters and chart generator
* fe6fb69 feat(ai-assistant): add LLM client, RAG engine, summarizer, chat engine, prompt templates
* d8f6275 feat(knowledge-graph): add citation, collaboration, temporal network, and graph algorithms
* 4f3a874 feat(data-science): add analysis engine, topic modeling, embeddings, clustering, temporal analysis, bibliometrics
* 04df31c (tag: v0.1.0) feat(data-acquisition): add Google Scholar, Crossref, DBLP, ORCID scrapers + scraping engine + DOI lookup
* 071da31 feat(data-acquisition): add base scraper and academic source scrapers (arXiv, PubMed, OpenAlex, Semantic Scholar)
* 90d8974 feat(proxy): add proxy suite — scraping, chaining, rotation, health-checking
* c19db02 feat(core): add orchestrator, task queue, event bus, and settings infrastructure
* 7d1f884 chore: initialize project skeleton
```

After `docs/GIT_HISTORY.md` is committed (see Section 4 below), the log gains
one more commit (`docs: add git history documentation and reproduction guide`)
and the `v1.0.0` tag is moved to point at it.

### 2.1 Commit ↔ sub-agent mapping

| #  | SHA       | Type  | Scope                | Refs                |
| -- | --------- | ----- | -------------------- | ------------------- |
| 1  | `7d1f884` | chore | —                    | Task ID 0           |
| 2  | `c19db02` | feat  | core                 | 1-core              |
| 3  | `90d8974` | feat  | proxy                | 1-proxy             |
| 4  | `071da31` | feat  | data-acquisition     | 1-scraper-a         |
| 5  | `04df31c` | feat  | data-acquisition     | 1-scraper-b         |
| 6  | `4f3a874` | feat  | data-science         | 1-datasci           |
| 7  | `d8f6275` | feat  | knowledge-graph      | 1-graph             |
| 8  | `fe6fb69` | feat  | ai-assistant         | 1-ai                |
| 9  | `e4ef299` | feat  | reporting            | 1-reporting         |
| 10 | `3b7d3b2` | feat  | database             | 1-db                |
| 11 | `9c69f4d` | feat  | project-management   | 1-db (shared)       |
| 12 | `82f361a` | feat  | ui                   | 1-ui-core           |
| 13 | `b0dbf27` | feat  | ui                   | 1-ui-panels         |
| 14 | `303aca6` | feat  | web                  | 1-web               |
| 15 | `bd8384c` | test  | —                    | 2-validate          |
| 16 | —         | —     | (skipped, no-op)     | 2-validate          |
| 17 | `55e31fc` | docs  | —                    | 3-docs              |
| 18 | `3f43e2a` | chore | worklog              | 4-git               |
| 19 | (HEAD)    | docs  | git-history          | 4-git               |

**Commit 16** was a no-op: the validation sub-agent's integration fixes had
already been absorbed into the file contents at the time commits 11 and 14
were created (because the validation agent ran *before* the git agent in the
orchestration order, leaving the corrected files in the working tree). Per the
spec, an empty commit was skipped rather than fabricated.

---

## 3. Tag listing

`git tag -l -n5`:

```
v0.1.0          v0.1.0 — Alpha: core infrastructure + first scrapers (commits 1-5)
v0.2.0          v0.2.0 — Beta: full feature set (commits 1-14, all modules implemented)
v1.0.0          v1.0.0 — First stable release: validated, documented, MIT-licensed
```

Each tag points at a different commit:

```
v0.1.0  →  04df31c   (commit 5  — first 5 scrapers complete)
v0.2.0  →  303aca6   (commit 14 — all 14 modules complete)
v1.0.0  →  <HEAD>    (commit 19 — after docs + worklog + GIT_HISTORY)
```

Inspect a tag with:
```bash
git show v0.1.0
git show v0.2.0
git show v1.0.0
```

---

## 4. Reproduction guide

The v1.0.0 git history can be reproduced exactly by running the following
commands in order from a clean working tree (i.e. the state left by the
14 module sub-agents + the validation agent + the docs agent).

### 4.1 Phase 1 — Repository initialization

```bash
cd /home/z/my-project/download/academic_research_suite

# Re-init cleanly if a .git directory already exists
rm -rf .git
git init -b main

git config user.name      "ARS Orchestrator"
git config user.email     "orchestrator@academic-research-suite.local"
git config commit.gpgsign false
git config core.autocrlf  false
```

### 4.2 Phase 2 — Ensure .gitignore + .gitkeep scaffolding

```bash
# Verify .gitignore exists at the project root (created by orchestrator).
test -f .gitignore

# Force-include .gitkeep files for empty-by-design directories that
# otherwise fall under the data/* ignore rules.
mkdir -p data/projects data/cache data/exports
touch data/projects/.gitkeep data/cache/.gitkeep data/exports/.gitkeep

# (Optional) add force-include lines to .gitignore for cache and exports.
# Also ignore generated SQLite databases.
```

### 4.3 Phase 2 — Atomic commits (exact sequence)

For each commit: `git add <specific paths>` then `git commit -F -` with the
exact multi-line message shown in the worklog. The pattern is:

```bash
git add <paths...>
git commit -m "$(cat <<'EOF'
<type>(<scope>): <subject>

<body>

Refs: Task ID <X>
EOF
)"
```

The 18 commits (with the 16th skipped) follow the table in Section 2.1. The
exact commit messages are documented inline in
[`docs/WORKLOG.md`](./WORKLOG.md) (Task ID 4-git entry).

### 4.4 Phase 3 — Apply annotated tags

```bash
# Capture the SHA of commit 5 (first scrapers)
v01=$(git rev-parse HEAD~13)   # 04df31c

# Capture the SHA of commit 14 (full feature set)
v02=$(git rev-parse HEAD~4)     # 303aca6

# Apply tags at the right commits
git tag -a v0.1.0 "$v01" -m "v0.1.0 — Alpha: core infrastructure + first scrapers (commits 1-5)"
git tag -a v0.2.0 "$v02" -m "v0.2.0 — Beta: full feature set (commits 1-14, all modules implemented)"
git tag -a v1.0.0          -m "v1.0.0 — First stable release: validated, documented, MIT-licensed"
```

In the actual run, the SHAs were captured inline:

```bash
git tag -a v0.1.0 04df31c -m "v0.1.0 — Alpha: core infrastructure + first scrapers (commits 1-5)"
git tag -a v0.2.0 303aca6 -m "v0.2.0 — Beta: full feature set (commits 1-14, all modules implemented)"
git tag -a v1.0.0 3f43e2a -m "v1.0.0 — First stable release: validated, documented, MIT-licensed"
```

### 4.5 Phase 4 — Generate GIT_HISTORY.md and finalize v1.0.0

```bash
# (write docs/GIT_HISTORY.md — this file)

git add docs/GIT_HISTORY.md
git commit -m "$(cat <<'EOF'
docs: add git history documentation and reproduction guide

Documents the atomic-commit-per-module strategy used in the v1.0.0 build,
including the full git log, tag list, and step-by-step reproduction guide
for future maintainers.

Refs: Task ID 4-git
EOF
)"

# Move v1.0.0 to the new HEAD (commit 19)
git tag -d v1.0.0
git tag -a v1.0.0 -m "v1.0.0 — First stable release: validated, documented, MIT-licensed"
```

### 4.6 Phase 5 — Verify

```bash
git log --oneline --decorate --graph | head -30
git tag -l -n5
git status                       # should be clean
wc -l docs/GIT_HISTORY.md docs/WORKLOG.md
git rev-parse HEAD               # final SHA
```

---

## 5. Notes & anomalies

1. **Commit 16 was skipped.** The validation sub-agent (Task ID 2-validate)
   fixed integration bugs in `web/server.py`, `web/routes/projects.py`, and
   `project_management/project_manager.py`, but did so *before* the git
   agent ran. By the time commits 11 and 14 were created, the fixed file
   contents were already staged. An empty `fix:` commit would have served no
   forensic purpose, so it was omitted per spec.

2. **`.gitignore` was extended.** The orchestrator's `.gitignore` only
   force-included `data/projects/.gitkeep`. The git agent added matching
   `!data/cache/.gitkeep` and `!data/exports/.gitkeep` exceptions, plus
   `data/*.db*` (to ignore the runtime SQLite database that the validation
   agent created during smoke testing). These changes were committed as part
   of commit 1 (`chore: initialize project skeleton`).

3. **`ui/resources/` was scaffolded with `.gitkeep` files.** The directory
   tree (`ui/resources/{icons,themes}/`) was created empty by the UI agent;
   the git agent added `.gitkeep` markers so the directory structure is
   preserved in version control even though it contains no assets yet.
   Committed as part of commit 12.

4. **No remote was configured.** This is a local-only repository. To publish,
   create a GitHub/GitLab repo and run:
   ```bash
   git remote add origin <url>
   git push -u origin main --tags
   ```

5. **No GPG signing.** `commit.gpgsign` is set to `false` for the local
   orchestrator identity. Enable signing for production releases by running
   `git config commit.gpgsign true` and configuring a GPG key.

---

## 6. Quick reference

```bash
# Show this history
git log --oneline --decorate --graph

# Show files changed in a specific commit
git show --stat <sha>

# Show all commits between two tags
git log v0.1.0..v0.2.0 --oneline

# List all tags with their commit subjects
git tag -l -n5

# Checkout a specific release
git checkout v1.0.0

# Create a release tarball
git archive --format=tar.gz --prefix=academic-research-suite-1.0.0/ \
    v1.0.0 > academic-research-suite-1.0.0.tar.gz
```

---

*This file is maintained by the git/version-control sub-agent (Task ID 4-git).
For the full multi-agent build narrative, see [`WORKLOG.md`](./WORKLOG.md).*
