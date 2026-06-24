"""真实行为测试: app/fastapi_routes/ocr.py 未覆盖分支。

策略:
- 纯函数 helper (_allowed_file/_ocr_user_id/_ocr_status/_agent_node_output/
  _resolve_ocr_path/_get_ocr_service) 直接调用并断言返回值/副作用。
- 路由分支 (空路径 / 成功 / 异常) 通过 TestClient + patch(_run_ocr_agent),
  绕开 AgentOrchestrator,只验证本模块的状态码/payload 组装逻辑。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.fastapi_routes.ocr as ocr_mod


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ocr_mod.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# _get_ocr_service (lines 31, 33) + lru_cache
# ---------------------------------------------------------------------------
def test_get_ocr_service_imports_facade_and_caches():
    ocr_mod._get_ocr_service.cache_clear()
    fake = Mock(name="ocr_service")
    try:
        with patch(
            "app.application.facades.ocr_facade.get_ocr_service",
            return_value=fake,
        ) as facade:
            first = ocr_mod._get_ocr_service()
            second = ocr_mod._get_ocr_service()
        assert first is fake
        # lru_cache(maxsize=1): facade import path only invoked once
        assert second is first
        assert facade.call_count == 1
    finally:
        ocr_mod._get_ocr_service.cache_clear()


# ---------------------------------------------------------------------------
# _allowed_file (line 37)
# ---------------------------------------------------------------------------
def test_allowed_file_accepts_known_extension_case_insensitive():
    assert ocr_mod._allowed_file("photo.JPG") is True
    assert ocr_mod._allowed_file("scan.tiff") is True


def test_allowed_file_rejects_unknown_and_extensionless():
    assert ocr_mod._allowed_file("note.txt") is False
    assert ocr_mod._allowed_file("noextension") is False


# ---------------------------------------------------------------------------
# _ocr_user_id (lines 40-48, incl. 42)
# ---------------------------------------------------------------------------
def test_ocr_user_id_returns_default_when_request_none():
    assert ocr_mod._ocr_user_id(None) == "ocr-route"


def test_ocr_user_id_reads_header_and_falls_back():
    req = Mock()
    req.headers.get.side_effect = lambda key: {"X-User-Id": "tenant-9"}.get(key)
    assert ocr_mod._ocr_user_id(req) == "tenant-9"

    req2 = Mock()
    req2.headers.get.return_value = None
    assert ocr_mod._ocr_user_id(req2) == "ocr-route"


# ---------------------------------------------------------------------------
# _ocr_status (lines 113-118)
# ---------------------------------------------------------------------------
def test_ocr_status_success_returns_200():
    assert ocr_mod._ocr_status({"success": True}) == 200


def test_ocr_status_exception_error_code_returns_500():
    assert ocr_mod._ocr_status({"success": False, "error_code": "ocr_exception"}) == 500


def test_ocr_status_other_failure_returns_400():
    assert ocr_mod._ocr_status({"success": False, "error_code": "bad_input"}) == 400
    assert ocr_mod._ocr_status({}) == 400


# ---------------------------------------------------------------------------
# _agent_node_output (lines 92-110, incl. 97-100, 102, 104)
# ---------------------------------------------------------------------------
def test_agent_node_output_reads_node_outputs():
    run = Mock(
        final_output={"node_outputs": {"n1": {"success": True, "text": "hi"}}},
        run_id="r1",
        status="completed",
        error="",
    )
    out = ocr_mod._agent_node_output(run, "n1")
    assert out["success"] is True
    assert out["text"] == "hi"
    assert out["run_id"] == "r1"
    assert out["agent_run_id"] == "r1"
    assert out["agent_status"] == "completed"


def test_agent_node_output_falls_back_to_matching_step():
    step = Mock(node_id="n2", output={"success": True, "value": 42})
    run = Mock(final_output=None, steps=[step], run_id="r2", status="completed", error="")
    out = ocr_mod._agent_node_output(run, "n2")
    assert out["value"] == 42
    assert out["success"] is True
    assert out["run_id"] == "r2"


def test_agent_node_output_step_loop_skips_nonmatching():
    # First step does not match node_id (exercises the loop's continue path),
    # second matches.
    other = Mock(node_id="zzz", output={"success": True, "value": "wrong"})
    match = Mock(node_id="target", output={"success": True, "value": "right"})
    run = Mock(
        final_output=None,
        steps=[other, match],
        run_id="r3",
        status="completed",
        error="",
    )
    out = ocr_mod._agent_node_output(run, "target")
    assert out["value"] == "right"


def test_agent_node_output_synthesizes_success_from_status():
    # No node_outputs, no steps -> output defaults to {"success": status==completed}
    run = Mock(final_output=None, steps=[], run_id="", status="completed", error="")
    out = ocr_mod._agent_node_output(run, "missing")
    assert out["success"] is True
    assert out["agent_status"] == "completed"
    # empty run_id => run_id/agent_run_id keys not added
    assert "run_id" not in out


def test_agent_node_output_merges_error_message_on_failure():
    run = Mock(final_output=None, steps=[], run_id="r4", status="failed", error="boom")
    out = ocr_mod._agent_node_output(run, "missing")
    assert out["success"] is False
    assert out["message"] == "boom"
    assert out["run_id"] == "r4"
    assert out["agent_status"] == "failed"


def test_agent_node_output_keeps_existing_message_over_error():
    # output already has success/message -> error not overwritten (line 103 guard)
    run = Mock(
        final_output={"node_outputs": {"n": {"success": False, "message": "explicit"}}},
        run_id="r5",
        status="failed",
        error="ignored-error",
    )
    out = ocr_mod._agent_node_output(run, "n")
    assert out["message"] == "explicit"


# ---------------------------------------------------------------------------
# _resolve_ocr_path (lines 121-127, incl. 126)
# ---------------------------------------------------------------------------
def test_resolve_ocr_path_uploads_image():
    img = Mock(filename="receipt.png")
    with patch(
        "app.fastapi_routes.ocr.save_upload_file",
        new=AsyncMock(return_value="/uploads/ocr/receipt.png"),
    ) as saver:
        result = asyncio.run(ocr_mod._resolve_ocr_path(None, img))
    assert result == "/uploads/ocr/receipt.png"
    saver.assert_awaited_once()


def test_resolve_ocr_path_returns_file_path_without_image():
    result = asyncio.run(ocr_mod._resolve_ocr_path("/tmp/doc.png", None))
    assert result == "/tmp/doc.png"


def test_resolve_ocr_path_image_without_filename_falls_back():
    img = Mock(filename="")
    result = asyncio.run(ocr_mod._resolve_ocr_path("/fallback.png", img))
    assert result == "/fallback.png"


# ---------------------------------------------------------------------------
# /recognize route (lines 136-155)
# ---------------------------------------------------------------------------
def test_recognize_missing_path_returns_400():
    resp = _client().post("/api/ocr/recognize", data={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert body["message"] == "请提供图像文件或文件路径"


def test_recognize_success_path():
    fake_run = object()
    with (
        patch("app.fastapi_routes.ocr._run_ocr_agent", return_value=fake_run) as agent,
        patch(
            "app.fastapi_routes.ocr._agent_node_output",
            return_value={"success": True, "text": "hello", "run_id": "r1"},
        ),
    ):
        resp = _client().post("/api/ocr/recognize", data={"file_path": "/tmp/a.png"})
    assert resp.status_code == 200
    assert resp.json()["text"] == "hello"
    kwargs = agent.call_args.kwargs
    assert kwargs["action"] == "recognize"
    assert kwargs["node_id"] == "ocr_recognize"
    assert kwargs["params"] == {"file_path": "/tmp/a.png"}


def test_recognize_recoverable_error_returns_500():
    with patch(
        "app.fastapi_routes.ocr._run_ocr_agent",
        side_effect=RuntimeError("orchestrator down"),
    ):
        resp = _client().post("/api/ocr/recognize", data={"file_path": "/tmp/a.png"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert "识别失败" in body["message"]
    assert "orchestrator down" in body["message"]


# ---------------------------------------------------------------------------
# /extract route (lines 159-175)
# ---------------------------------------------------------------------------
def test_extract_empty_text_returns_400():
    resp = _client().post("/api/ocr/extract", json={"text": ""})
    assert resp.status_code == 400
    assert resp.json()["message"] == "文本不能为空"


def test_extract_success_path():
    with (
        patch("app.fastapi_routes.ocr._run_ocr_agent", return_value=object()) as agent,
        patch(
            "app.fastapi_routes.ocr._agent_node_output",
            return_value={"success": True, "data": {"order_no": "SO-1"}},
        ),
    ):
        resp = _client().post("/api/ocr/extract", json={"text": "订单 SO-1"})
    assert resp.status_code == 200
    assert resp.json()["data"]["order_no"] == "SO-1"
    assert agent.call_args.kwargs["action"] == "extract"
    assert agent.call_args.kwargs["params"] == {"text": "订单 SO-1"}


def test_extract_recoverable_error_returns_500():
    with patch(
        "app.fastapi_routes.ocr._run_ocr_agent",
        side_effect=ValueError("bad parse"),
    ):
        resp = _client().post("/api/ocr/extract", json={"text": "abc"})
    assert resp.status_code == 500
    assert "提取失败" in resp.json()["message"]


# ---------------------------------------------------------------------------
# /analyze route (lines 179-195)
# ---------------------------------------------------------------------------
def test_analyze_empty_text_returns_400():
    resp = _client().post("/api/ocr/analyze", json={})
    assert resp.status_code == 400
    assert resp.json()["message"] == "文本不能为空"


def test_analyze_success_path():
    with (
        patch("app.fastapi_routes.ocr._run_ocr_agent", return_value=object()) as agent,
        patch(
            "app.fastapi_routes.ocr._agent_node_output",
            return_value={"success": True, "data": {"text_type": "invoice"}},
        ),
    ):
        resp = _client().post("/api/ocr/analyze", json={"text": "发票内容"})
    assert resp.status_code == 200
    assert resp.json()["data"]["text_type"] == "invoice"
    assert agent.call_args.kwargs["action"] == "analyze"
    assert agent.call_args.kwargs["node_id"] == "ocr_analyze"
    assert agent.call_args.kwargs["params"] == {"text": "发票内容"}


def test_analyze_recoverable_error_returns_500():
    with patch(
        "app.fastapi_routes.ocr._run_ocr_agent",
        side_effect=RuntimeError("analyzer crash"),
    ):
        resp = _client().post("/api/ocr/analyze", json={"text": "some text"})
    assert resp.status_code == 500
    assert "分析失败" in resp.json()["message"]


# ---------------------------------------------------------------------------
# /recognize-and-extract route (lines 199-222)
# ---------------------------------------------------------------------------
def test_recognize_and_extract_missing_path_returns_400():
    resp = _client().post("/api/ocr/recognize-and-extract", data={})
    assert resp.status_code == 400
    assert resp.json()["message"] == "请提供图像文件或文件路径"


def test_recognize_and_extract_success_path():
    with (
        patch("app.fastapi_routes.ocr._run_ocr_agent", return_value=object()) as agent,
        patch(
            "app.fastapi_routes.ocr._agent_node_output",
            return_value={"success": True, "text": "T", "analysis": {"k": "v"}},
        ),
    ):
        resp = _client().post("/api/ocr/recognize-and-extract", data={"file_path": "/tmp/b.png"})
    assert resp.status_code == 200
    assert resp.json()["analysis"]["k"] == "v"
    assert agent.call_args.kwargs["action"] == "recognize_and_extract"
    assert agent.call_args.kwargs["node_id"] == "ocr_recognize_and_extract"


def test_recognize_and_extract_recoverable_error_returns_500():
    with patch(
        "app.fastapi_routes.ocr._run_ocr_agent",
        side_effect=OSError("disk gone"),
    ):
        resp = _client().post("/api/ocr/recognize-and-extract", data={"file_path": "/tmp/b.png"})
    assert resp.status_code == 500
    assert "处理失败" in resp.json()["message"]


# ---------------------------------------------------------------------------
# /test route (lines 225-232)
# ---------------------------------------------------------------------------
def test_ocr_test_returns_active_backend():
    svc = Mock()
    svc.get_active_ocr_backend.return_value = "paddle"
    with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
        resp = _client().get("/api/ocr/test")
    assert resp.status_code == 200
    assert resp.json()["active_backend"] == "paddle"


def test_ocr_test_falls_back_to_unknown_on_error():
    svc = Mock()
    svc.get_active_ocr_backend.side_effect = RuntimeError("backend probe failed")
    with patch("app.fastapi_routes.ocr._get_ocr_service", return_value=svc):
        resp = _client().get("/api/ocr/test")
    assert resp.status_code == 200
    assert resp.json()["active_backend"] == "unknown"
