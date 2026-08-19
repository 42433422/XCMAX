"""运行时真相清单（应用层入口）：委托 FHD/scripts/ops/runtime_inventory.py。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, cast


def _load_ops_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "runtime_inventory.py"
    spec = importlib.util.spec_from_file_location("fhd_ops_runtime_inventory", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runtime_inventory script: {script}")
    mod = importlib.util.module_from_spec(spec)
    # Avoid polluting sys.modules permanently under a colliding name.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def build_runtime_inventory(*, host: str = "127.0.0.1") -> dict[str, Any]:
    return cast("dict[str, Any]", _load_ops_module().build_inventory(host=host))


def write_runtime_inventory_projection(
    snapshot: dict[str, Any] | None = None, *, host: str = "127.0.0.1"
) -> dict[str, Any]:
    mod = _load_ops_module()
    payload = snapshot if snapshot is not None else mod.build_inventory(host=host)
    publication = mod.write_projection(payload)
    return {"snapshot": payload, "publication": publication}
