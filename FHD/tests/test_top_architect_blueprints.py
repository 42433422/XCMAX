from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from fastapi import FastAPI

PACK_ROOT = Path(__file__).parents[1] / "mods" / "_employees" / "top-architect"


def _load_blueprints():
    spec = importlib.util.spec_from_file_location(
        "test_top_architect_blueprints",
        PACK_ROOT / "backend" / "blueprints.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_top_architect_manifest_backend_entry_exists() -> None:
    assert (PACK_ROOT / "backend" / "blueprints.py").is_file()


def test_top_architect_routes_register_and_execute() -> None:
    module = _load_blueprints()
    app = FastAPI()
    module.register_fastapi_routes(app, "top-architect")
    paths = set(app.openapi()["paths"])
    assert "/api/mod/top-architect/employees" in paths
    assert "/api/mod/top-architect/employees/top-architect/run" in paths
    assert "/api/mod/top-architect/employees/top-architect/status" in paths

    result = asyncio.run(
        module._dispatch_run(
            "top-architect",
            "top-architect",
            "top_architect",
            {
                "architecture": {
                    "modules": [{"name": "api", "layer": "application"}],
                    "dependencies": [],
                    "allowed_dependencies": {"application": []},
                }
            },
        )
    )
    assert result["success"] is True
    assert result["data"]["status"] == "approved"
    assert result["data"]["read_only"] is True
