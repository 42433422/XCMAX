# mypy: disable-error-code="var-annotated"
"""GET /api/admin/genai/traces 查询 API 测试。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes.domains.genai_traces.routes import router
from app.infrastructure.auth.dependencies import get_logged_in_user


def _seed(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d")
    rows = [
        {
            "span_id": "s1",
            "trace_id": "t-1",
            "parent_span_id": None,
            "name": "chat",
            "start_time": time.time(),
            "end_time": time.time(),
            "duration_ms": 1.0,
            "status": "ok",
            "attributes": {"gen_ai.request.model": "m1"},
            "events": [],
        },
        {
            "span_id": "s2",
            "trace_id": "t-2",
            "parent_span_id": None,
            "name": "chat",
            "start_time": time.time(),
            "end_time": time.time(),
            "duration_ms": 2.0,
            "status": "error",
            "attributes": {"gen_ai.request.model": "m2"},
            "events": [],
        },
    ]
    (base / f"trace-{day}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setenv("XCAGI_GENAI_TRACE_DIR", str(tmp_path))
    from app.infrastructure.llm import trace_store

    trace_store.reset_trace_store()
    app = FastAPI()
    app.include_router(router)
    admin = type("U", (), {"role": "admin", "username": "root"})()
    app.dependency_overrides[get_logged_in_user] = lambda: admin
    yield TestClient(app)
    trace_store.reset_trace_store()


class TestListTraces:
    def test_admin_gets_items(self, client: TestClient):
        resp = client.get("/api/admin/genai/traces")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 2

    def test_filter_by_status(self, client: TestClient):
        resp = client.get("/api/admin/genai/traces", params={"status": "error"})
        items = resp.json()["data"]["items"]
        assert [i["span_id"] for i in items] == ["s2"]

    def test_filter_by_trace_id(self, client: TestClient):
        resp = client.get("/api/admin/genai/traces", params={"trace_id": "t-1"})
        assert resp.json()["data"]["total"] == 1

    def test_non_admin_forbidden(self, tmp_path: Path, monkeypatch):
        _seed(tmp_path)
        monkeypatch.setenv("XCAGI_GENAI_TRACE_DIR", str(tmp_path))
        from app.infrastructure.llm import trace_store

        trace_store.reset_trace_store()
        app = FastAPI()
        app.include_router(router)
        user = type("U", (), {"role": "viewer", "username": "bob"})()
        app.dependency_overrides[get_logged_in_user] = lambda: user
        resp = TestClient(app).get("/api/admin/genai/traces")
        assert resp.status_code == 403
        trace_store.reset_trace_store()
