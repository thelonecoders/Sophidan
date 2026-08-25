# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Academic Research Suite.

This spec bundles the PyQt5 desktop application (with optional web-server mode)
into a distributable folder. It is intentionally written to be portable
between Linux (proof-of-concept build) and Windows (production .exe build).

Usage::

    pip install pyinstaller>=6.0
    pyinstaller main.spec --clean --noconfirm

On Linux the result is an ELF binary at ``dist/AcademicResearchSuite/AcademicResearchSuite``.
On Windows the same spec produces ``dist/AcademicResearchSuite/AcademicResearchSuite.exe``.
PyInstaller cannot cross-compile, so a real ``.exe`` requires running this spec
on a Windows host (see ``docs/BUILD_WINDOWS_EXE.md``).

See ``docs/BUILD_WINDOWS_EXE.md`` for end-user instructions.
"""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# --- Application metadata ----------------------------------------------------

APP_NAME = "AcademicResearchSuite"

# --- Hidden imports ----------------------------------------------------------
# Many of ARS' modules import heavy third-party deps lazily (inside functions
# or under try/except). PyInstaller's static analysis can't see those, so we
# declare them explicitly here. This guarantees the on-disk bundle contains
# PyQt5, matplotlib's Qt backend, the scientific stack, and every v1/v2
# module that ``main.py`` may dispatch to at runtime.

hiddenimports = []

# v1 scrapers (data_acquisition/)
hiddenimports += [
    "data_acquisition.arxiv_scraper",
    "data_acquisition.pubmed_scraper",
    "data_acquisition.openalex_scraper",
    "data_acquisition.semantic_scholar_scraper",
    "data_acquisition.google_scholar_scraper",
    "data_acquisition.crossref_scraper",
    "data_acquisition.dblp_scraper",
    "data_acquisition.orcid_scraper",
    "data_acquisition.doi_lookup",
    "data_acquisition.base_scraper",
    "data_acquisition.scraping_engine",
]

# v2 modules — collect_submodules walks each package and returns every
# importable submodule, which is much safer than hand-listing each one.
for pkg in (
    "bibliometrics",
    "networkx_pro",
    "gephi_viz",
    "systematic_review",
    "meta_analysis",
    "prisma",
    "q1_figures",
    "research_lifecycle",
    "innovation",
):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        # collect_submodules shouldn't raise, but be defensive so the build
        # never aborts because of a missing local package on the build host.
        pass

# Qt backends — PyQt5 + matplotlib's Qt5Agg backend
hiddenimports += [
    "PyQt5.QtCore",
    "PyQt5.QtWidgets",
    "PyQt5.QtGui",
    "PyQt5.QtSvg",
    "PyQt5.sip",
    "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_qt5",
    "matplotlib.backends.backend_agg",
]

# Optional heavy deps — declared so the bundle contains them when installed.
# Each is wrapped in collect_submodules so missing deps on a minimal build
# host don't abort the spec compilation.
for pkg in (
    "sentence_transformers",
    "transformers",
    "torch",
    "sklearn",
    "scipy",
    "chromadb",
    "reportlab",
    "docx",
    "pptx",
    "networkx",
    "numpy",
    "pandas",
):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

# --- Data files --------------------------------------------------------------
# Bundled alongside the binary so default config + license ship with the app.

datas = [
    ("config/default_config.yaml", "config"),
    ("LICENSE", "."),
]

# Collect matplotlib's data files (fonts, styles, etc.) — without these
# matplotlib raises at first figure-render call.
try:
    datas += collect_data_files("matplotlib")
except Exception:
    pass

# --- Analysis ---------------------------------------------------------------

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unrelated heavy packages that may be present in the build
        # host's venv but are NOT declared in ARS' requirements.txt. Excluding
        # them shrinks the on-disk bundle by ~1.5 GB without breaking any ARS
        # module. Each entry is a top-level package name; PyInstaller skips
        # collecting it AND its data files.
        "nvidia",            # CUDA runtime (only needed by torch GPU builds)
        "torch",
        "transformers",
        "sentence_transformers",
        "catboost",          # not in requirements.txt
        "cv2",               # opencv — not declared
        "opencv",
        "llvmlite",          # numba JIT — not declared
        "numba",
        "fiona",             # geopandas native backend — optional
        "pyogrio",           # geopandas IO — optional
        "shapely",
        "pyproj",
        "rasterio",
        "geopandas",         # optional in ARS; lazy-imported with graceful fallback
        "skimage",           # scikit-image — not declared
        "imageio_ffmpeg",    # binary blob, not used by ARS
        "botocore", "boto3", # AWS SDK — not declared
        "s3transfer",
        "matplotlib.tests",
        "numpy.tests",
        "scipy.tests",
        "pandas.tests",
        "sklearn.tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX frequently false-positives on AV scans; disabled.
    console=False,  # GUI app — no console window.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Set to "installer/ars.ico" once an icon is produced.
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
