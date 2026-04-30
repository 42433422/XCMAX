from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def xcagi_root() -> Path:
    p = (os.environ.get("XCAGI_ROOT") or "").strip()
    if p:
        return Path(p).resolve()
    return (Path(os.environ.get("WORKSPACE_ROOT", os.getcwd())).resolve() / "XCAGI").resolve()


def mods_dir() -> Path:
    p = (os.environ.get("XCAGI_MODS_DIR") or "").strip()
    if p:
        return Path(p).resolve()
    return (xcagi_root() / "mods").resolve()


def read_manifest_dicts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    root = mods_dir()
    if not root.exists():
        return out
    for m in root.glob("*/manifest.json"):
        try:
            row = json.loads(m.read_text(encoding="utf-8"))
            if not isinstance(row, dict):
                continue
            seed = row.get("database_seed_sql")
            if isinstance(seed, str) and seed.strip() and not Path(seed).is_absolute():
                row["database_seed_sql"] = str((m.parent / seed).resolve())
            out.append(row)
        except Exception:
            continue
    return out
