"""HTTPException 的结构化 detail 不能以 Python repr 形式显示到界面。"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.middleware.error_handler import register_exception_handlers


def _client(detail) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise HTTPException(status_code=403, detail=detail)

    return TestClient(app)


def test_structured_detail_keeps_code_and_message():
    body = (
        _client({"code": "ELT_CENTER_DISABLED", "message": "数据对接中心尚未启用"})
        .get("/boom")
        .json()
    )
    assert body["success"] is False
    assert body["error_code"] == "ELT_CENTER_DISABLED"
    assert body["message"] == "数据对接中心尚未启用"
    assert "{" not in body["message"]


def test_nested_message_dict_is_unwrapped():
    body = (
        _client({"success": False, "message": {"code": "UNAUTHORIZED", "message": "请先登录"}})
        .get("/boom")
        .json()
    )
    assert body["error_code"] == "UNAUTHORIZED"
    assert body["message"] == "请先登录"


def test_structured_detail_without_message_falls_back_to_generic_text():
    body = _client({"code": "SOME_INTERNAL_CODE"}).get("/boom").json()
    assert body["error_code"] == "SOME_INTERNAL_CODE"
    assert body["message"] == "请求失败"


def test_plain_string_detail_is_unchanged():
    body = _client("权限不足").get("/boom").json()
    assert body["error_code"] == "http_403"
    assert body["message"] == "权限不足"
