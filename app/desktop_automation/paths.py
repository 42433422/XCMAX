"""桌面自动化数据目录（profiles / templates / yolo export）。"""

from __future__ import annotations

import os
from pathlib import Path


def _fhd_root() -> Path:
    return Path(__file__).resolve().parents[2]


def desktop_automation_data_root() -> Path:
    env = (os.environ.get("XCAGI_DATA_DIR") or os.environ.get("FHD_DATA_DIR") or "").strip()
    if env:
        root = Path(env) / "desktop_automation"
    else:
        root = _fhd_root() / "data" / "desktop_automation"
    root.mkdir(parents=True, exist_ok=True)
    return root


def profiles_dir() -> Path:
    d = desktop_automation_data_root() / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def templates_dir() -> Path:
    d = desktop_automation_data_root() / "templates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def yolo_export_dir() -> Path:
    d = desktop_automation_data_root() / "yolo_export"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_profiles_dir() -> Path:
    return _fhd_root() / "data" / "desktop_profiles"
