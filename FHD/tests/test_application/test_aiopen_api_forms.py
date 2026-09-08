"""Authenticated form and multipart protocol round trips with real XLSX bytes."""

import hashlib
import json
from io import BytesIO

import pytest
from fastapi import Request
from openpyxl import load_workbook

from app.application.aiopen import api_artifacts, api_request_body
from app.application.aiopen.service import _tool_api_call
from app.db.models.user import Session
from app.request_active_mod_ctx import get_request_active_mod_id
from tests.test_application.test_aiopen_api_artifacts import export_app as export_app
from tests.test_application.test_aiopen_api_execution import application as application
from tests.test_application.test_aiopen_api_execution import caller
from tests.test_application.test_aiopen_api_execution import host as host


@pytest.fixture
def form_app(export_app):
    app, content = export_app
    calls = []

    @app.api_route("/api/test/form", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def form_endpoint(request: Request):
        async with request.form() as form:
            fields, files = [], []
            for key, value in form.multi_items():
                if isinstance(value, str):
                    fields.append([key, value])
                else:
                    raw = await value.read()
                    workbook = load_workbook(BytesIO(raw), read_only=True)
                    files.append(
                        {
                            "field": key,
                            "name": value.filename,
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "customer": workbook.active["A201"].value,
                        }
                    )
                    workbook.close()
            calls.append({"fields": fields, "files": files})
            return {"success": True, "fields": fields, "files": files}

    return app, content, calls


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_form_repeated_unicode_and_empty_fields_survive_real_parser(form_app, method):
    app, _, calls = form_app
    with caller({"X-Session-ID": "login-3"}):
        result = _tool_api_call(
            app,
            {
                "path": "/api/test/form",
                "method": method,
                "form": {"客户": ["张三 & 李四", ""], "flag": "0"},
            },
        )
    assert result["success"], result
    assert result["data"]["fields"] == [["客户", "张三 & 李四"], ["客户", ""], ["flag", "0"]]
    assert len(calls) == 1


def test_export_to_multipart_preserves_files_fields_and_source_entitlement(form_app, host):
    app, content, calls = form_app
    with caller({"X-Session-ID": "login-3"}):
        exported = _tool_api_call(app, {"path": "/api/test/export", "mod_id": "mod-a"})
        artifact_id = exported["artifacts"][0]["artifact_id"]
        args = {
            "path": "/api/test/form",
            "method": "POST",
            "mod_id": "",
            "form": {"mode": ["preview", "确认"]},
            "files": [{"field": "files", "artifact_id": artifact_id}] * 2,
        }
        result = _tool_api_call(app, args)
        assert result["success"], result
        assert result["execution_scope"]["mod_id"] == ""
        assert result["data"]["fields"] == [["mode", "preview"], ["mode", "确认"]]
        assert (
            result["data"]["files"]
            == [
                {
                    "field": "files",
                    "name": "客户.xlsx",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "customer": "客户-199",
                }
            ]
            * 2
        )
        assert get_request_active_mod_id() == ""
        with host.begin() as db:
            db.get(Session, 3).entitled_mod_ids_json = "[]"
        denied = _tool_api_call(app, args)
        assert not denied["success"] and denied["code"] == "INVALID_API_BODY"
        assert get_request_active_mod_id() == ""
    assert len(calls) == 1


@pytest.mark.parametrize("state", ["other_account", "expired", "corrupt", "aggregate_limit"])
def test_invalid_attachment_never_reaches_target(form_app, monkeypatch, state):
    app, content, calls = form_app
    with caller({"X-Session-ID": "login-3"}):
        artifact = _tool_api_call(app, {"path": "/api/test/export"})["artifacts"][0]
    artifact_id = artifact["artifact_id"]
    root = api_artifacts._root()
    if state == "expired":
        manifest = root / f"{artifact_id}.json"
        metadata = json.loads(manifest.read_text())
        metadata["expires_at"] = 0
        manifest.write_text(json.dumps(metadata))
    if state == "corrupt":
        (root / f"{artifact_id}.bin").write_bytes(b"corrupt")
    if state == "aggregate_limit":
        monkeypatch.setattr(api_request_body, "MAX_UPLOAD_BYTES", len(content))
    with caller({"X-Session-ID": "login-4" if state == "other_account" else "login-3"}):
        result = _tool_api_call(
            app,
            {
                "path": "/api/test/form",
                "method": "POST",
                "files": [{"field": "file", "artifact_id": artifact_id}] * 2,
            },
        )
    assert not result["success"] and result["code"] == "INVALID_API_BODY", result
    assert not calls


@pytest.mark.parametrize(
    "payload",
    [
        {"body": None, "form": {}},
        {"body": {}, "files": []},
        {"form": {"number": 1}},
        {"form": {"nested": {}}},
        {"form": {"bool": False}},
        {"form": {"bad\nname": "x"}},
        {"form": []},
        {"files": {}},
        {"files": [{"field": "file", "path": "/etc/passwd"}]},
        {"files": [{"field": "file", "artifact_id": "https://example.invalid"}]},
        {"files": [{"field": "file", "artifact_id": "a" * 32}] * 17},
    ],
)
def test_invalid_or_ambiguous_body_is_rejected_before_business_action(form_app, payload):
    app, _, calls = form_app
    with caller({"X-Session-ID": "login-3"}):
        result = _tool_api_call(app, {"path": "/api/test/form", "method": "POST", **payload})
    assert not result["success"] and result["code"] == "INVALID_API_BODY", result
    assert not calls
