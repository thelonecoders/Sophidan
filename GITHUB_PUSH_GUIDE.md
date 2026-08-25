# Pushing Academic Research Suite to GitHub

This guide walks through publishing the bundled repo on GitHub and
triggering the auto-build of the Windows `.exe` via GitHub Actions.

## Quick Start

1. **Create a new GitHub repository** at <https://github.com/new>
   - Name: `academic-research-suite`
   - Visibility: **Public** (recommended — MIT-licensed) or Private.
   - Don't initialize with README/LICENSE/.gitignore — the bundle already
     has them.

2. **Download the github-ready bundle** from the v2.0.0 release page:

   ```
   academic_research_suite_v2.0.0_github_ready.zip   (~4.5 MB)
   ```

3. **Unzip and verify**:

   ```bash
   unzip academic_research_suite_v2.0.0_github_ready.zip
   cd academic_research_suite
   git log --oneline | wc -l         # should be 34
   git tag -l                         # should show: v0.1.0  v0.2.0  v1.0.0  v2.0.0
   git rev-parse HEAD                 # matches the v2.0.0 release SHA
   ```

4. **Add remote and push**:

   ```bash
   git remote add origin https://github.com/<your-username>/academic-research-suite.git
   git branch -M main
   git push -u origin main
   git push origin --tags
   ```

5. **Verify on GitHub**:
   - Browse to `https://github.com/<your-username>/academic-research-suite`
   - Tags appear at `https://github.com/<your-username>/academic-research-suite/tags`

## Setting up CI

The bundle includes `.github/workflows/` with one Windows-build workflow:

| Workflow | Triggers | What it does |
|---|---|---|
| `build-windows-exe.yml` | tag `v*.*.*` push, OR manual `workflow_dispatch` | Builds the `.exe` on `windows-latest`, zips it, uploads as artifact + attaches to GitHub Release |

No additional setup required — the workflow will run automatically on the
first `v*.*.*` tag push. You can also trigger it manually from the
**Actions** tab → **Build Windows .exe** → **Run workflow**.

> **Note**: The workflow needs `contents: write` permission to attach files
> to the GitHub Release — this is already declared in the YAML. For organisation
> repos, an admin may need to enable "Allow GitHub Actions to create and
> approve pull requests" + "Read and write permissions" under
> **Settings → Actions → General**.

## Releasing v2.0.0

After `git push origin --tags`, GitHub creates a Release page for `v2.0.0`.
The `build-windows-exe.yml` workflow runs (~10 min) and attaches
`AcademicResearchSuite_windows_x64.zip` to the release automatically.

To verify the release assets:

1. Go to <https://github.com/<your-username>/academic-research-suite/releases>
2. Click **v2.0.0**
3. You should see `AcademicResearchSuite_windows_x64.zip` (~200-250 MB) listed
   under **Assets**.

If the workflow fails, click into the run, scroll to the failing step, and
consult `docs/BUILD_WINDOWS_EXE.md` (Troubleshooting section) — the most
common cause is a missing module in `hiddenimports`.

## Repository Settings (Recommended)

For a public open-source release:

- **About** (top-right of repo page):
  - Description: *"All-in-one desktop + web app for academic research:
    bibliometrics, systematic reviews, meta-analysis, PRISMA, Q1 figures,
    citation-graph analysis. PyQt5 + Flask."*
  - Website: (your project URL, if any)
  - Topics: `academic-research`, `bibliometrics`, `meta-analysis`,
    `systematic-review`, `prisma`, `pyqt5`, `python`, `mit-license`,
    `citation-network`, `research-tools`
- **Settings → General**:
  - Features: tick **Issues**, **Discussions** (untick **Projects** if you
    don't use the GitHub Projects board), **Wiki** (optional).
- **Settings → Branches**:
  - Add branch protection rule for `main`:
    - Require pull request before merging (1 approval).
    - Require status checks to pass (select `build-windows` once it has run once).
    - Require branches to be up to date before merging.
- **Settings → Actions → General**:
  - Allow all actions and reusable workflows.
  - Workflow permissions: **Read and write permissions**.
- **Settings → Pages**:
  - Source: **Deploy from a branch** → `main` → `/docs` folder.
  - Your `docs/*.md` files will be served as a static site at
    `https://<your-username>.github.io/academic-research-suite/`.

## Worklog Exclusion

The orchestrator's multi-agent build worklog at
`/home/z/my-project/worklog.md` (the file outside this repo) is internal
build documentation and is **NOT** shipped in any bundle.

Previously, a copy was committed at `docs/WORKLOG.md` in v1.0.0. Per the
v2.0.0 release policy ("worklog is for orchestrator eyes only"),
`docs/WORKLOG.md` has been removed from git tracking via `git rm` and added
to `.gitignore`. References to it in `docs/GIT_HISTORY.md` and
`docs/GIT_HISTORY_V2.md` remain as historical footnotes — they describe
the build process, not the file itself.

If you want to ship the build narrative publicly, restore it with:

```bash
git checkout v1.0.0 -- docs/WORKLOG.md
git commit -m "docs: restore WORKLOG.md for public build history"
```

## Updating the Workflow

If you change `main.spec` or add new optional deps, push a `v*.*.*` tag
to trigger a fresh build. The workflow always rebuilds from `main.spec`
on the tagged commit.

For a manual rebuild of an existing tag (e.g. after a hotfix), use
**Actions → Build Windows .exe → Run workflow** and pick the tag from
the dropdown.
