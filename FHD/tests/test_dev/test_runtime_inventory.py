"""runtime-inventory 静态 check + 构建 shape。"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

FHD = Path(__file__).resolve().parents[2]
SCRIPT = FHD / "scripts" / "ops" / "runtime_inventory.py"


def _load():
    spec = importlib.util.spec_from_file_location("runtime_inventory_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_runtime_inventory_check_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "check"],
        cwd=str(FHD),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_runtime_inventory_build_shape() -> None:
    mod = _load()
    payload = mod.build_inventory(host="127.0.0.1")
    assert payload["schema"] == "xcagi.runtime_inventory/v1"
    assert "items" in payload and isinstance(payload["items"], list)
    assert payload["items"], "inventory must list topology services/processes"
    kinds = {i["kind"] for i in payload["items"]}
    assert "service" in kinds
    assert "process" in kinds
