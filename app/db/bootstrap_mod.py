"""运行时桥接 ``scripts/bootstrap_mod_dbs.py``（scripts/ 非安装包，用 importlib 加载）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BOOTSTRAP_PATH = _REPO_ROOT / "scripts" / "bootstrap_mod_dbs.py"


def load_bootstrap_mod_dbs() -> Any:
    spec = importlib.util.spec_from_file_location("xcagi_bootstrap_mod_dbs", _BOOTSTRAP_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_BOOTSTRAP_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ensure_postgres_per_mod_databases(
    *,
    mod_ids: list[str] | None = None,
    migrate_new: bool = True,
) -> list[str]:
    """见 ``scripts/bootstrap_mod_dbs.ensure_postgres_per_mod_databases``。"""
    return load_bootstrap_mod_dbs().ensure_postgres_per_mod_databases(
        mod_ids=mod_ids,
        migrate_new=migrate_new,
    )


__all__ = ["ensure_postgres_per_mod_databases", "load_bootstrap_mod_dbs"]
