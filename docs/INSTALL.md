# Installation Guide

> **Audience:** end-users installing Academic Research Suite (ARS).
> **Companion docs:** [../README.md](../README.md#quick-start) for
> the 5-minute quick start,
> [user_guide.md](user_guide.md) for daily usage,
> [FAQ.md](FAQ.md) for troubleshooting.

This document covers per-OS install instructions, optional
dependencies, virtual-environment setup, and first-run checks.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Linux (apt / dnf)](#linux-apt--dnf)
3. [macOS (Homebrew)](#macos-homebrew)
4. [Windows (WSL recommended)](#windows-wsl-recommended)
5. [Optional Dependencies](#optional-dependencies)
6. [Virtual Environment Setup](#virtual-environment-setup)
7. [First-Run Checks](#first-run-checks)
8. [Upgrading](#upgrading)
9. [Uninstalling](#uninstalling)

---

## Prerequisites

ARS requires **Python 3.10 or newer**. Verify:

```bash
python --version
# Python 3.10.x, 3.11.x, or 3.12.x — all supported.
```

You also need:

- **pip** (bundled with Python ≥ 3.4).
- **git** (for cloning the repo; alternatively, download a release
  tarball).
- ~1.5 GB free disk space for the dependencies + chromadb models +
  matplotlib font cache.
- ~150 MB RAM at idle; expect 500 MB – 2 GB when scraping and
  running analyses concurrently.

Optional but recommended:

- **Tesseract OCR** — for OCR on scanned PDFs in the planned
  bulk-PDF ingestion feature (v1.1.0).
- **Ollama** — for the local-LLM RAG assistant.
- **Google Chrome / Chromium** — required by the Google Scholar
  Selenium scraper.

---

## Linux (apt / dnf)

### Ubuntu / Debian (apt)

```bash
# 1. System packages
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-dev \
                     build-essential git libssl-dev libffi-dev \
                     libxml2-dev libxslt1-dev zlib1g-dev \
                     libjpeg-dev libfreetype6-dev libpng-dev \
                     pkg-config

# Optional: Tesseract OCR + CJK fonts
sudo apt install -y tesseract-ocr tesseract-ocr-chi-sim \
                     fonts-noto-cjk

# Optional: Chrome for Google Scholar scraper
wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb

# 2. Clone & venv
git clone https://github.com/academic-research-suite/academic_research_suite.git
cd academic_research_suite
python3 -m venv venv
source venv/bin/activate

# 3. Install
pip install --upgrade pip wheel
pip install -r requirements.txt
pip install -e ".[dev]"   # optional dev tooling

# 4. First run
python main.py
```

### Fedora / RHEL (dnf)

```bash
sudo dnf install -y python3 python3-devel python3-pip \
                    gcc gcc-c++ make git openssl-devel libffi-devel \
                    libxml2-devel libxslt-devel zlib-devel \
                    libjpeg-devel freetype-devel libpng-devel \
                    pkgconfig

# Optional
sudo dnf install -y tesseract google-noto-sans-cjk-fonts

# Chrome: install via dnf from Google's repo (see above) or use chromium
sudo dnf install -y chromium

git clone https://github.com/academic-research-suite/academic_research_suite.git
cd academic_research_suite
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
python main.py
```

### Arch Linux

```bash
sudo pacman -S --needed python python-pip python-virtualenv \
                       base-devel git openssl libffi libxml2 \
                       libxslt zlib libjpeg-turbo freetype2 \
                       fontconfig ttf-noto-cjk

# Optional
sudo pacman -S --needed tesseract chromium

git clone https://github.com/academic-research-suite/academic_research_suite.git
cd academic_research_suite
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## macOS (Homebrew)

```bash
# 1. Install Homebrew if missing
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. System packages
brew install python@3.12 git openssl@3 libffi libxml2 libxslt \
             zlib jpeg-turbo freetype pkg-config

# Optional: Tesseract OCR + CJK fonts + Chrome
brew install tesseract font-noto-sans-cjk-sc google-chrome

# 3. Clone & venv
git clone https://github.com/academic-research-suite/academic_research_suite.git
cd academic_research_suite
python3 -m venv venv
source venv/bin/activate

# 4. Install
pip install --upgrade pip wheel
pip install -r requirements.txt
pip install -e ".[dev]"

# 5. First run
python main.py
```

### macOS notes

- **XQuartz** is NOT required — ARS uses Qt's native Cocoa backend.
- **Apple Silicon (M1/M2/M3)** works out of the box; all
  dependencies ship arm64 wheels. If you hit an architecture
  mismatch, run `pip install --upgrade --force-reinstall <pkg>`.
- **Ollama** install for local LLM:
  ```bash
  brew install ollama
  ollama serve &
  ollama pull llama3
  ```

---

## Windows (WSL recommended)

ARS runs natively on Windows but several features (Tesseract OCR,
multi-process scraping, file paths > 260 chars) are smoother under
WSL2.

### Option A: Native Windows (Python.org distribution)

1. Install **Python 3.10+** from <https://www.python.org/downloads/windows/>
   — tick "Add python.exe to PATH" during install.
2. Install **git** from <https://git-scm.com/download/win>.
3. (Optional) Install **Tesseract** from
   <https://github.com/UB-Mannheim/tesseract/wiki> and add its
   `bin` directory to PATH.
4. (Optional) Install **Google Chrome** from
   <https://www.google.com/chrome/>.

```powershell
git clone https://github.com/academic-research-suite/academic_research_suite.git
cd academic_research_suite
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip wheel
pip install -r requirements.txt
python main.py
```

### Option B: WSL2 (recommended for power users)

1. Install WSL2 + Ubuntu:

   ```powershell
   wsl --install -d Ubuntu-24.04
   ```

2. Inside the WSL shell, follow the
   [Linux (apt) instructions](#linux-apt--dnf) above.

3. To display the PyQt5 GUI from WSL, you have three options:

   - **Windows 11 (Build 22000+)** — native WSLg support works
     out of the box. `python main.py` just works.
   - **Windows 10** — install **VcXsrv** or **X410** and set
     `export DISPLAY=$(ipconfig.exe | grep -A1 WSL | tail -1 |
     awk '{print $NF}'):0`.
   - **Run in web mode only** — `python main.py --web` and open
     <http://127.0.0.1:8765> from a Windows browser. No X server
     needed.

WSL is the best-supported Windows path because it sidesteps
native-Windows quirks with `multiprocessing`, `sqlite-journal-mode=WAL`,
and `chromadb`.

---

## Optional Dependencies

ARS ships with lazy imports — every optional dependency is loaded
inside the function that needs it, so `python -c "import <pkg>"`
never raises. Install the ones you actually use.

### Tesseract OCR (planned v1.1.0 bulk PDF ingestion)

| OS | Install |
|---|---|
| Ubuntu / Debian | `sudo apt install tesseract-ocr tesseract-ocr-chi-sim` |
| Fedora / RHEL | `sudo dnf install tesseract` |
| Arch | `sudo pacman -S tesseract` |
| macOS | `brew install tesseract` |
| Windows | <https://github.com/UB-Mannheim/tesseract/wiki> |

Verify: `tesseract --version` prints `tesseract 5.x.x`.

### Ollama (local LLM)

For the privacy-preserving local AI assistant:

| OS | Install |
|---|---|
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` |
| macOS | `brew install ollama` or download from <https://ollama.com> |
| Windows | Download from <https://ollama.com> |

Start the daemon: `ollama serve`. Pull a model:

```bash
ollama pull llama3         # 8B params, ~5GB
ollama pull mistral        # 7B params, ~4GB
ollama pull phi3           # 3.8B params, ~2GB (smaller / faster)
ollama pull qwen2.5        # Alibaba's Qwen2.5
```

Configure ARS in `config/secrets.yaml`:

```yaml
ai_provider: "ollama"
ai_model: "llama3"
ai_base_url: "http://localhost:11434"
```

### PostgreSQL (multi-user, planned v1.1.0)

For a single user the default SQLite is plenty (handles up to ~10⁶
papers comfortably). For a small research group sharing a server:

```bash
# Linux
sudo apt install postgresql postgresql-contrib
sudo -u postgres createuser --createdb ars
sudo -u postgres createdb --owner=ars academic_research_suite

# Configure ARS to use it:
export ARS_DATABASE_URL="postgresql+psycopg2://ars:password@localhost/academic_research_suite"
python main.py
```

ARSee will auto-create the schema on first run via
`DatabaseConnection.init_db()`.

### Chrome / Chromium (Selenium scraping)

Required by `data_acquisition/google_scholar_scraper.py`. Install:

- **Linux**: see OS-specific instructions above.
- **macOS**: `brew install --cask google-chrome`.
- **Windows**: download from <https://www.google.com/chrome/>.

The scraper uses `selenium` with the bundled chromedriver manager
— no manual chromedriver install is needed.

### Chrome Headless Shell

If you run ARS on a headless server, you may prefer Chrome
Headless Shell to full Chrome:

```bash
# Linux x64
wget https://dl.google.com/chrome/chrome-headless-shell/latest/chrome-headless-shell-linux64.zip
unzip chrome-headless-shell-linux64.zip -d /opt/
export CHROME_BIN=/opt/chrome-headless-shell-linux64/chrome-headless-shell
```

The Google Scholar scraper will pick up `CHROME_BIN` automatically.

---

## Virtual Environment Setup

We **strongly** recommend a virtualenv to avoid dependency conflicts
with your system Python. ARS pins its dependencies in
`requirements.txt`; mixing them with system packages can produce
subtle incompatibilities.

### venv (built-in)

```bash
python -m venv venv
source venv/bin/activate           # Linux/macOS
# venv\Scripts\activate            # Windows
```

### uv (faster, modern alternative)

If you have [`uv`](https://github.com/astral-sh/uv) installed:

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### conda

```bash
conda create -n ars python=3.12
conda activate ars
pip install -r requirements.txt
```

---

## First-Run Checks

After installation, verify the install is healthy:

```bash
# 1. Version banner
python main.py --version

# 2. Settings load
python -c "from config.settings import get_settings; s = get_settings(); print(s)"

# 3. DB init
python -c "
from database.connection import DatabaseConnection
db = DatabaseConnection()
db.init_db()
print('DB OK:', db.url)
"

# 4. Test suite (hermetic, ~5s)
pytest tests/

# 5. Smoke runner (imports + pytest + web ping + Qt launch)
./scripts/smoke_test.sh

# 6. Web server health
python main.py --web &
sleep 2
curl http://127.0.0.1:8765/api/health | jq .
kill %1

# 7. Desktop UI launch
python main.py
```

If all seven steps pass, your install is healthy.

### Common first-run issues

- **`ModuleNotFoundError: qtpy`** — `pip install qtpy PyQt5`.
- **`qt.qpa.plugin: Could not load the Qt platform plugin`** — on
  Linux, install `libxcb-xinerama0` (`apt install
  libxcb-xinerama0`); on Windows, ensure the `PyQt5` wheel matches
  your Python version (32-bit vs 64-bit).
- **`sqlite3.OperationalError: unable to open database file`** —
  the `data/` directory is missing. Run `mkdir -p data` and try
  again, or set `ARS_DATA_DIR=/some/writable/path`.
- **CJK characters render as squares** — install `fonts-noto-cjk`
  (Linux) or `font-noto-sans-cjk-sc` (macOS) and clear the
  matplotlib cache: `rm -rf ~/.cache/matplotlib`.

---

## Upgrading

To upgrade to a new version:

```bash
cd academic_research_suite
git pull origin main

# Reactivate venv
source venv/bin/activate

# Reinstall (deps may have changed)
pip install -r requirements.txt --upgrade

# Run any pending DB migrations (idempotent)
python -c "
from database.connection import DatabaseConnection
DatabaseConnection().init_db()
"

# Verify
pytest tests/
python main.py --version
```

ARS uses `init_db()` which is idempotent — existing tables are
untouched and new ones are created as needed. For breaking schema
changes (planned only in v2.0.0), a migration script will be
shipped alongside the release.

### Backing up before upgrade

Always back up `data/ars.db` before upgrading:

```bash
sqlite3 data/ars.db "VACUUM INTO 'backups/ars-pre-$(date +%Y%m%d).db'"
```

Or via the UI: `Settings → Database → Backup`.

---

## Uninstalling

ARS is a self-contained directory — no system files are written
outside the project tree (except the standard `~/.cache/matplotlib`
and `~/.local/share/RecentDocuments` entries the underlying
libraries write).

To uninstall:

```bash
# 1. Quit ARS if running
# 2. Remove the project directory
cd ..
rm -rf academic_research_suite

# 3. (Optional) remove the venv you created elsewhere
rm -rf ~/venvs/ars    # if you put the venv outside the project

# 4. (Optional) remove user-level cache
rm -rf ~/.cache/matplotlib
rm -rf ~/.academic_research_suite   # proxy_manager's fallback DB
```

No residual files remain. If you used `pip install -e .` to add
the `ars` console-script, remove it with:

```bash
pip uninstall academic-research-suite
```

---

*If the install doesn't go smoothly, see [FAQ.md](FAQ.md) or open
an issue at
<https://github.com/academic-research-suite/academic_research_suite/issues>.*

---

## v2.0.0 Optional Dependencies

ARS v2.0.0 introduces nine new packages whose default install is
intentionally lightweight — every optional dependency is **lazy-imported**
inside the function that needs it, so `python -c "import <pkg>"` never
raises. Install only the optional packages for the features you use.

### `prophet` — for trend forecasting

Used by `innovation.trend_forecasting.TrendForecaster` when the user
requests `method="prophet"`. Prophet handles long-horizon (3–5 year)
forecasts with seasonality better than ARIMA. When `prophet` is not
installed, the forecaster falls back silently to ARIMA and logs a
warning.

```bash
pip install prophet        # ~120 MB; pulls in cmdstanpy + a C++ toolchain
```

Verify: `python -c "from prophet import Prophet; print(Prophet)"`.

### `faiss-cpu` — for fast paper recommendation

Used by `innovation.paper_recommendation.PaperRecommender.index_papers()`
to build a vector index over paper embeddings. Faiss provides
approximate-nearest-neighbour search at ~10× the speed of NumPy for
corpora above 10,000 papers. When `faiss-cpu` is not installed, the
recommender falls back to NumPy's `cosine_similarity` (slower but
correct).

```bash
pip install faiss-cpu      # ~30 MB; pre-built wheel for Linux / macOS / Windows
```

Verify: `python -c "import faiss; print(faiss.IndexFlatL2)"`.

### `pyvis` — for interactive HTML network visualisations

Used by `gephi_viz.preview.InteractivePreview` (lazy import inside the
function). Without `pyvis`, the interactive HTML preview is replaced by
a static SVG export.

```bash
pip install pyvis          # ~5 MB; depends on networkx + jinja2
```

Verify: `python -c "from pyvis.network import Network; print(Network)"`.

### `sentence-transformers` — already in v1 for embeddings

Already declared in v1's `requirements.txt` and used by
`data_science.embeddings.EmbeddingsModel`. The v2.0.0 innovation module
reuses the same embedder for `KnowledgeFrontier`, `PaperRecommender`,
`NoveltyScorer`, and `ResearchDirectionRecommender`. No additional
install needed if v1 was already set up correctly.

Verify: `python -c "from sentence_transformers import SentenceTransformer; print(SentenceTransformer)"`.

### `networkx>=3.0` — for community detection

v2.0.0 requires networkx ≥ 3.0 because the new
`networkx_pro.algorithms_communities.CommunityDetection` class uses
the built-in `networkx.community.louvain_communities()` function added
in networkx 3.0. Earlier networkx versions will raise `ImportError`
when the SR / bibliometric / innovation modules are first accessed.

```bash
pip install --upgrade "networkx>=3.0"
```

Verify: `python -c "import networkx as nx; print(nx.__version__); print(nx.community.louvain_communities)"`.

### API keys for new v2.0.0 scrapers

ARS v2.0.0 adds four new scrapers under `data_acquisition/`. Each has
its own key requirements (set in `config/secrets.yaml` or via the
`ARS_*` env vars):

| Scraper | Module | API key | How to obtain |
|---|---|---|---|
| **Springer** | `data_acquisition/springer_scraper.py` | `ARS_SPRINGER_API_KEY` | <https://dev.springernature.com/> — free, instant signup |
| **IEEE Xplore** | `data_acquisition/ieee_scraper.py` | `ARS_IEEE_API_KEY` | <https://developer.ieee.org/> — free, requires institutional email |
| **CORE** | `data_acquisition/core_scraper.py` | `ARS_CORE_API_KEY` | <https://core.ac.uk/api-keys/register> — free, instant signup |
| **BASE** | `data_acquisition/base_scraper_ext.py` | none required | BASE is accessed via the OpenAlex aggregator (no separate key) |

**Unpaywall** requires only an email address (used as the API "key" —
set `ARS_UNPAYWALL_EMAIL`):
```bash
export ARS_UNPAYWALL_EMAIL="your-email@your-institution.edu"
```

**OpenCitations** requires no key at all — it is fully open.

Configure keys in `config/secrets.yaml`:
```yaml
springer_api_key: "abc123..."
ieee_api_key:     "def456..."
core_api_key:     "ghi789..."
unpaywall_email:  "your-email@your-institution.edu"
```

Verify each scraper:
```bash
python -c "from data_acquisition.springer_scraper import SpringerScraper; print('OK')"
python -c "from data_acquisition.ieee_scraper import IEEEXploreScraper; print('OK')"
python -c "from data_acquisition.core_scraper import COREScraper; print('OK')"
python -c "from data_acquisition.unpaywall_scraper import UnpaywallScraper; print('OK')"
python -c "from data_acquisition.opencitations_scraper import OpenCitationsScraper; print('OK')"
python -c "from data_acquisition.base_scraper_ext import BASEScraper; print('OK')"
```

---

*For v1.0.0 optional dependencies (Tesseract, Ollama, PostgreSQL,
Chrome / Chromium, Chrome Headless Shell), see the
[Optional Dependencies](#optional-dependencies) section above. For
troubleshooting, see [FAQ.md](FAQ.md).*
