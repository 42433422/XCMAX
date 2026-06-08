"""Golden snapshot of critical route paths (edition=essential)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.fastapi_routes import register_all_routes

GOLDEN_PATH = Path(__file__).parent / "route_golden_essential.json"

REQUIRED_PATHS = (
    "/api/health",
    "/api/ping",
    "/api/auth/session/validate",
)


@pytest.fixture
def essential_app() -> FastAPI:
    os.environ["XCAGI_SKIP_LEGACY_COMPAT_ROUTES"] = "1"
    app = FastAPI()
    register_all_routes(app)
    return app


def _collect_paths(app: FastAPI) -> list[str]:
    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
    return sorted(paths)


def test_required_paths_present(essential_app: FastAPI):
    paths = _collect_paths(essential_app)
    for required in REQUIRED_PATHS:
        assert required in paths or any(required in p for p in paths), (
            f"missing {required} in {paths[:20]}..."
        )


def test_golden_route_snapshot_essential(essential_app: FastAPI):
    paths = _collect_paths(essential_app)
    assert len(paths) >= len(REQUIRED_PATHS)
    if GOLDEN_PATH.exists():
        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        assert paths == expected
