# -*- mode: python ; coding: utf-8 -*-

import json
import os
from pathlib import Path

import setuptools
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path.cwd().resolve()

FRONTEND_INDEX = ROOT / "templates" / "vue-dist" / "index.html"
if not FRONTEND_INDEX.is_file():
    raise FileNotFoundError(
        "Required desktop frontend asset missing: templates/vue-dist/index.html. "
        "Run the SKU frontend build before PyInstaller."
    )


def add_data(relative_path: str):
    """Bundle data for PyInstaller.

    Files must use the *parent* as dest (often ``.``). Using the filename as
    dest creates ``_MEIPASS/<name>/<name>`` and breaks frozen lookups such as
    ``_MEIPASS/alembic.ini``.
    """
    src = ROOT / relative_path
    if not src.exists():
        return []
    if src.is_file():
        parent = str(Path(relative_path).parent).replace("\\", "/")
        dest = "." if parent in ("", ".") else parent
        return [(str(src), dest)]
    return [(str(src), relative_path)]


datas = []
for item in [
    "templates/vue-dist",
    "static",
    "resources",
    "config",
    "alembic",
    ".env.example",
    "alembic.ini",
    "scripts/backup",
]:
    datas.extend(add_data(item))

_staged_mods = (os.environ.get("XCAGI_STAGED_MODS_DIR") or "").strip()
if _staged_mods and Path(_staged_mods).is_dir():
    datas.append((str(Path(_staged_mods).resolve()), "mods"))
    _sku_file = Path(_staged_mods).parent.parent / "build" / "product-sku.json"
    if _sku_file.is_file():
        datas.append((str(_sku_file.resolve()), "."))
else:
    datas.extend(add_data("mods"))

_staged_industry = (os.environ.get("XCAGI_STAGED_INDUSTRY_SEEDS_DIR") or "").strip()
if _staged_industry and Path(_staged_industry).is_dir():
    datas.append((str(Path(_staged_industry).resolve()), "industry-seeds"))

# PyInstaller pkg_resources hook reads jaraco.text demo data at startup.
jaraco_text = Path(setuptools.__file__).resolve().parent / "_vendor" / "jaraco" / "text"
if jaraco_text.is_dir():
    datas.append((str(jaraco_text), "setuptools/_vendor/jaraco/text"))
try:
    datas += collect_data_files("setuptools", include_py_files=False)
except Exception:
    pass

hiddenimports = []
for module in [
    "appdirs",
    "app.desktop_runtime",
    "app.fastapi_app",
    "app.fastapi_routes",
    "app.db",
    "app.db.models",
    "app.middleware",
    "app.infrastructure.mods",
    "app.mod_sdk",
    "uvicorn",
    "fastapi",
    "sqlalchemy",
    "alembic",
]:
    hiddenimports.extend(collect_submodules(module))

# v10-A: fast-start bootstrap imports these lazily; collect_submodules can miss them
# on some Windows trees, causing deliverable-status 404 in frozen desktop builds.
hiddenimports.extend(
    [
        "app.fastapi_routes.platform_shell_routes",
        "app.mod_sdk.deliverable_status",
        "app.mod_sdk.desktop_deliverable",
        "app.mod_sdk.platform_shell",
        "app.mod_sdk.decoupling_progress",
        "app.mod_sdk.edition_policy",
        "app.mod_sdk.edition_bootstrap",
        "app.mod_sdk.product_skus",
    ]
)
# de-dupe while preserving order
_seen = set()
_deduped = []
for _name in hiddenimports:
    if _name not in _seen:
        _seen.add(_name)
        _deduped.append(_name)
hiddenimports = _deduped

desktop_excludes = [
    "altair",
    "av",
    "bitsandbytes",
    "IPython",
    "black",
    "bokeh",
    "chromadb",
    "cv2",
    "dash",
    "datasets",
    "faster_whisper",
    "gradio",
    "grpc",
    "h5py",
    "jedi",
    "keyring",
    "langchain",
    "librosa",
    "lightgbm",
    "llvmlite",
    "matplotlib",
    "mypy",
    "nbformat",
    "numba",
    "onnxruntime",
    "OpenGL",
    "opentelemetry",
    "patsy",
    "plotly",
    "playwright",
    "prophet",
    "pygame",
    "pyarrow",
    "pypdfium2",
    "pytest",
    "scipy",
    "selenium",
    "skimage",
    "sklearn",
    "soundfile",
    "statsmodels",
    "tensorflow",
    "tensorflow_cpu",
    "tests",
    "timm",
    "tkinter",
    "torch",
    "torchaudio",
    "torchvision",
    "transformers",
    "yapf",
]

a = Analysis(
    [str(ROOT / "XCAGI" / "run_fastapi.py")],
    pathex=[str(ROOT), str(ROOT / "XCAGI")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=desktop_excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="xcagi-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=os.environ.get("XCAGI_PYINSTALLER_UPX", "").strip().lower() in {"1", "true", "yes", "on"},
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=os.environ.get("XCAGI_PYINSTALLER_UPX", "").strip().lower() in {"1", "true", "yes", "on"},
    upx_exclude=[],
    name="xcagi-backend",
)
