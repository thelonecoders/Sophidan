# Building the Windows .exe

Academic Research Suite ships as Python source. To produce a standalone
Windows `.exe`, use **PyInstaller** with the included `main.spec`.

> PyInstaller cannot cross-compile — you cannot produce a Windows `.exe`
> from Linux. You must either (a) build on a Windows host, or (b) push a
> tag to GitHub and let the included workflow build it on a Windows runner
> for you (see "Alternative: GitHub Actions Auto-Build" below).

## Prerequisites

- **Windows 10/11 (64-bit)**
- **Python 3.10+ (64-bit)** from <https://python.org>
  - During install, tick **"Add Python to PATH"**.
- **Git for Windows** — <https://git-scm.com/download/win>
- **Visual C++ Build Tools 2019 or newer** — needed to compile some Python
  wheels (e.g. `lxml`, `python-igraph`, `pyzmq`).
  - Installer: <https://visualstudio.microsoft.com/visual-cpp-build-tools/>
  - In the installer, select **"Desktop development with C++"** workload.

Disk space: ~3 GB free (deps + PyInstaller folder).

## Steps

```powershell
# 1. Clone the repository
git clone https://github.com/<your-username>/academic-research-suite.git AcademicResearchSuite
cd AcademicResearchSuite

# 2. Create + activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# If PowerShell blocks the script, run once:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# 3. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install "pyinstaller>=6.0"

# 4. Build the .exe (uses main.spec in repo root)
pyinstaller main.spec --clean --noconfirm

# 5. Test the .exe
.\dist\AcademicResearchSuite\AcademicResearchSuite.exe --version
.\dist\AcademicResearchSuite\AcademicResearchSuite.exe            # launches GUI
.\dist\AcademicResearchSuite\AcademicResearchSuite.exe --web      # launches web server

# 6. (Optional) Create an installer with Inno Setup
#    - Install Inno Setup 6 from https://jrsoftware.org/isdl.php
#    - Open installer\ars.iss in the Inno Setup Compiler
#    - Press Ctrl+9 (Compile) to produce AcademicResearchSuite_v2.0.0_Setup.exe
#    - Alternative: NSIS — compile installer\ars.nsi with `makensis installer\ars.nsi`
```

The PyInstaller folder at `dist\AcademicResearchSuite\` is fully self-contained:
you can zip it and ship it to any Windows 10/11 x64 machine — no Python install
needed on the target.

## What `main.spec` does

- `Analysis(['main.py'], pathex=['.'])` — entry point is `main.py`.
- `datas` includes `config/default_config.yaml` and `LICENSE` so the bundled
  app ships with default settings and license text.
- `hiddenimports` declares every lazy-imported v1/v2 module and every optional
  heavy dep (`PyQt5`, `matplotlib.backends.backend_qt5agg`, `scipy`, `sklearn`,
  `reportlab`, `python-docx`, `python-pptx`, `networkx`, `numpy`, `pandas`,
  and optionally `sentence_transformers`/`transformers`/`torch`/`chromadb` if
  you want the full AI stack bundled — comment them out to slim the .exe).
- `EXE(console=False, name='AcademicResearchSuite')` — no console window,
  matches the GUI app UX.
- `COLLECT(name='AcademicResearchSuite')` — folder distribution (more
  reliable than `--onefile` for an app this size; onefile would have to
  extract ~250 MB to a temp dir on every launch).

## Alternative: GitHub Actions Auto-Build

The workflow at `.github/workflows/build-windows-exe.yml` runs on every
`v*.*.*` tag push (and on manual dispatch). It will:

1. Spin up a `windows-latest` GitHub-hosted runner.
2. Install Python 3.11 + all dependencies from `requirements.txt`.
3. Run `pyinstaller main.spec --clean --noconfirm`.
4. Zip the `dist/AcademicResearchSuite/` folder.
5. Attach `AcademicResearchSuite_windows_x64.zip` to the GitHub Release.

This takes ~10 minutes after the tag push — no local Windows machine required.

```bash
# From your local clone:
git tag v2.0.0
git push origin v2.0.0
# Wait ~10 min, then check https://github.com/<you>/academic-research-suite/releases
```

## Bundle Size Reference

| Artifact | Approx. size | Notes |
|---|---|---|
| Source code (`*.zip`) | ~1.5 MB | Python source only |
| PyInstaller folder (Linux proof-of-concept) | ~600 MB | ELF binary + `_internal/` |
| PyInstaller folder on Windows | ~200-250 MB | `.exe` + `_internal/` (smaller than Linux venv here because the build host had extra packages) |
| Inno Setup installer (`.exe`) | ~80-100 MB | LZMA2-compressed single-file installer |

The Linux proof-of-concept binary at
`/home/z/my-project/download/AcademicResearchSuite_linux_x64/AcademicResearchSuite`
is provided to verify the spec is correct — it is an ELF binary, NOT a Windows
`.exe`. The same spec on Windows produces a real `.exe`.

## Troubleshooting

### `ModuleNotFoundError: No module named 'X'`

Add `X` to `hiddenimports` in `main.spec` and rebuild. Common additions:
- `PyQt5.QtPrintSupport` (if you use QPrinter)
- `sqlalchemy.dialects.sqlite` (always required for the local DB)
- `reportlab.graphics.barcode` (if you generate barcodes)

### Antivirus false positive on the `.exe`

PyInstaller bundles are sometimes flagged by AV (especially with `--onefile`).
Use the COLLECT folder distribution (already the default in `main.spec`),
and sign the `.exe` with an Authenticode certificate (`codesign_identity`
parameter in the spec).

### `.exe` crashes silently on launch

Run from `cmd.exe` to see the traceback:

```powershell
.\dist\AcademicResearchSuite\AcademicResearchSuite.exe --version
```

Common cause: a lazy-imported dep was not in `hiddenimports`. The traceback
will name the missing module.

## Updating main.spec

If you add a new module to ARS that imports a heavy third-party dep lazily,
add the dep to `hiddenimports` in `main.spec` so PyInstaller picks it up.
Rebuild and verify `--version` still works before tagging a release.
