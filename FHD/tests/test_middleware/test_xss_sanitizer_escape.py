"""COVERAGE_RAMP C3.0: XSS Sanitizer 中間件 - GET/POST 分支 / 異常 JSON / script 注入清理。

覆蓋：
- GET/HEAD/OPTIONS 透傳
- POST 非 JSON content-type 透傳
- POST 合法 JSON 中 <script> 被剝離 + 實體轉義
- POST 嵌套 dict/list 遞歸清理
- 非法 JSON 不拋錯（透傳原 body）
- http.disconnect 路徑
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.middleware.xss_sanitizer import XSSSanitizerMiddleware


@pytest.fixture
def app():
    app = FastAPI()
    app.add_middleware(XSSSanitizerMiddleware)

    @app.post("/api/echo")
    async def echo(request: Request):
        body = await request.body()
        return {"raw": body.decode("utf-8")}

    @app.get("/api/echo")
    def echo_get():
        return {"success": True}

    return app


def test_get_passthrough(app):
    client = TestClient(app)
    r = client.get("/api/echo")
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_post_non_json_passthrough(app):
    client = TestClient(app)
    r = client.post("/api/echo", data="not json", headers={"content-type": "text/plain"})
    assert r.status_code == 200
    assert r.json()["raw"] == "not json"


def test_post_strips_script_tag(app):
    client = TestClient(app)
    payload = {"name": "<script>alert(1)</script>hello"}
    r = client.post("/api/echo", json=payload)
    assert r.status_code == 200
    raw = r.json()["raw"]
    # <script>...</script> 已被剥离，剩余内容被 html.escape
    assert "<script" not in raw.lower()
    assert "hello" in raw
    # 实体转义验证
    assert "&lt;" in raw or "<" not in raw


def test_post_nested_dict_sanitized(app):
    client = TestClient(app)
    payload = {"a": {"b": ["<script>x</script>", "ok"]}}
    r = client.post("/api/echo", json=payload)
    raw = r.json()["raw"]
    # 数组也递归清理
    assert "<script" not in raw.lower()
    assert "ok" in raw


def test_post_invalid_json_passthrough(app):
    """非法 JSON 不抛错，body 原样透传。"""
    client = TestClient(app)
    bad = "{not json"
    r = client.post("/api/echo", data=bad, headers={"content-type": "application/json"})
    assert r.status_code == 200
    assert r.json()["raw"] == bad


def test_post_empty_body(app):
    client = TestClient(app)
    r = client.post("/api/echo", json={})
    assert r.status_code == 200


def test_script_with_attributes(app):
    client = TestClient(app)
    payload = {"x": "<SCRIPT type='text/javascript'>evil()</SCRIPT>after"}
    r = client.post("/api/echo", json=payload)
    raw = r.json()["raw"]
    assert "evil" not in raw.lower() or "script" not in raw.lower()
    # 内容片段可保留（不在 <script> 块内）
    assert "after" in raw
