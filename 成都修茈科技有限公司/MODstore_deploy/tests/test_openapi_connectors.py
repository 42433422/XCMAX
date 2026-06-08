"""OpenAPI 连接器：parser / codegen / runtime / API / workflow integration."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple
from unittest.mock import patch

import httpx
import pytest

pytest.importorskip("fastapi")


SAMPLE_SPEC: Dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Sample Issue API", "version": "1.0.0"},
    "servers": [{"url": "https://example-api.invalid/v1"}],
    "paths": {
        "/projects/{project}/issues": {
            "parameters": [
                {
                    "name": "project",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ],
            "get": {
                "operationId": "listIssues",
                "summary": "List issues",
                "tags": ["issues"],
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/IssueList"}
                            }
                        },
                    }
                },
            },
            "post": {
                "summary": "Create issue (no operationId on purpose)",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Issue"}}
                    },
                },
                "responses": {"201": {"description": "created"}},
            },
        }
    },
    "components": {
        "schemas": {
            "Issue": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["title"],
            },
            "IssueList": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/Issue"},
            },
        }
    },
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parser_supports_json_and_yaml() -> None:
    from modstore_server.openapi_connector_parser import OpenApiParseError, parse_spec

    parsed = parse_spec(json.dumps(SAMPLE_SPEC))
    assert parsed.title == "Sample Issue API"
    assert parsed.base_url == "https://example-api.invalid/v1"
    assert {op.operation_id for op in parsed.operations} >= {"listIssues"}
    auto_id = next(op.operation_id for op in parsed.operations if op.method == "POST")
    assert auto_id and auto_id != "listIssues"

    with pytest.raises(OpenApiParseError):
        parse_spec("{}")
    with pytest.raises(OpenApiParseError):
        parse_spec(json.dumps({"openapi": "2.0.0", "info": {"title": "x"}, "paths": {"/": {}}}))


def test_parser_summarizes_schema() -> None:
    from modstore_server.openapi_connector_parser import parse_spec

    parsed = parse_spec(json.dumps(SAMPLE_SPEC))
    create = next(op for op in parsed.operations if op.method == "POST")
    assert create.request_body_required is True
    schema = create.request_body_schema or {}
    assert schema.get("type") == "object"
    assert "title" in (schema.get("properties") or {})


# ---------------------------------------------------------------------------
# Codegen
# ---------------------------------------------------------------------------


def test_codegen_writes_runtime_callable_module(tmp_path: Path) -> None:
    from modstore_server.openapi_connector_codegen import generate_client_files
    from modstore_server.openapi_connector_parser import parse_spec

    parsed = parse_spec(json.dumps(SAMPLE_SPEC))
    artifacts = generate_client_files(
        parsed,
        connector_id=42,
        version=1,
        artifacts_root=tmp_path,
    )
    assert artifacts.client_file.is_file()
    assert artifacts.metadata_file.is_file()
    body = artifacts.client_file.read_text(encoding="utf-8")
    assert "call_generated_operation" in body
    metadata = json.loads(artifacts.metadata_file.read_text(encoding="utf-8"))
    assert metadata["connector_id"] == 42
    assert metadata["operations"]


# ---------------------------------------------------------------------------
# Runtime safety helpers
# ---------------------------------------------------------------------------


def test_outbound_safety_blocks_loopback_and_schemes() -> None:
    from modstore_server.openapi_connector_runtime import (
        OutboundBlocked,
        assert_url_outbound_safe,
    )

    with pytest.raises(OutboundBlocked):
        assert_url_outbound_safe("file:///etc/passwd")
    with pytest.raises(OutboundBlocked):
        assert_url_outbound_safe("http://127.0.0.1/")
    with pytest.raises(OutboundBlocked):
        assert_url_outbound_safe("http://localhost/")
    with pytest.raises(OutboundBlocked):
        assert_url_outbound_safe("http://10.0.0.1/")
    # 公网域名解析成功时只要不是私有 IP 就放行；解析失败也放行
    with patch.object(socket, "getaddrinfo", return_value=[(0, 0, 0, "", ("8.8.8.8", 0))]):
        assert_url_outbound_safe("http://example.com/path")


def test_split_params_validates_required() -> None:
    from modstore_server.openapi_connector_runtime import _apply_path_params, _split_params

    spec_params = [
        {"name": "project", "in": "path", "required": True},
        {"name": "limit", "in": "query"},
        {"name": "X-Trace", "in": "header"},
    ]
    path_params, query, headers = _split_params(
        {"project": "ABC", "limit": 5, "X-Trace": "x"},
        spec_params,
    )
    assert path_params == {"project": "ABC"}
    assert query == {"limit": 5}
    assert headers == {"X-Trace": "x"}

    with pytest.raises(ValueError):
        _split_params({"limit": 5}, spec_params)

    new_path = _apply_path_params("/projects/{project}/issues", dict(path_params), spec_params)
    assert new_path == "/projects/ABC/issues"


def test_redact_headers_masks_sensitive_values() -> None:
    from modstore_server.openapi_connector_runtime import _redact_headers

    out = _redact_headers({"Authorization": "Bearer secret", "X-Trace": "abc"})
    assert out["Authorization"] == "***"
    assert out["X-Trace"] == "abc"


# ---------------------------------------------------------------------------
# Auth payload encryption
# ---------------------------------------------------------------------------


@pytest.fixture
def fernet_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    yield


def test_credential_payload_round_trip(fernet_key: None) -> None:
    from modstore_server.openapi_connector_runtime import (
        decrypt_credential_payload,
        encrypt_credential_payload,
    )

    cipher = encrypt_credential_payload("api_key", {"key": "abc", "name": "X-Api"})
    decoded = decrypt_credential_payload("api_key", cipher)
    assert decoded.config == {"key": "abc", "name": "X-Api"}
    assert decoded.auth_type == "api_key"


# ---------------------------------------------------------------------------
# REST API end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
def authed(client):
    """以 dependency_overrides 注入测试用户，避免依赖 register/login 流程。"""
    import types

    from modstore_server.api import deps as api_deps
    from modstore_server.app import _require_user, app
    from modstore_server.infrastructure import db as db_infra
    from modstore_server.models import User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        existing = session.query(User).filter(User.username == "openapi-test").first()
        if existing:
            user_id = existing.id
        else:
            user = User(
                username="openapi-test",
                email="openapi-test@pytest.local",
                password_hash="x",
                is_admin=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            user_id = user.id

    fake = types.SimpleNamespace(
        id=user_id,
        username="openapi-test",
        is_admin=True,
        email="openapi-test@pytest.local",
    )

    app.dependency_overrides[_require_user] = lambda: fake
    app.dependency_overrides[api_deps.get_current_user] = lambda: fake
    app.dependency_overrides[api_deps._get_current_user] = lambda: fake

    yield client, {}

    app.dependency_overrides.pop(_require_user, None)
    app.dependency_overrides.pop(api_deps.get_current_user, None)
    app.dependency_overrides.pop(api_deps._get_current_user, None)


def _isolate_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_OPENAPI_GEN_ROOT", str(tmp_path / "gen"))


def _patched_outbound(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 example-api.invalid 这种主机通过 outbound 安全检查。"""
    from modstore_server import openapi_connector_runtime as runtime

    monkeypatch.setattr(
        runtime,
        "assert_url_outbound_safe",
        lambda url: None,
    )


def _stub_httpx_client(monkeypatch: pytest.MonkeyPatch, status: int, body: Dict[str, Any]) -> None:
    captured: Dict[str, Any] = {}

    class _Resp:
        def __init__(self) -> None:
            self.status_code = status
            self.headers = httpx.Headers({"content-type": "application/json"})
            self.encoding = "utf-8"
            self.content = json.dumps(body).encode("utf-8")

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured["client_kwargs"] = kwargs

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def request(self, method: str, url: str, **kwargs: Any) -> _Resp:
            captured["method"] = method
            captured["url"] = url
            captured["kwargs"] = kwargs
            return _Resp()

    from modstore_server import openapi_connector_runtime as runtime

    monkeypatch.setattr(runtime, "httpx", type(httpx)("httpx_stub"))
    runtime.httpx.Client = _Client  # type: ignore[attr-defined]
    runtime.httpx.HTTPError = httpx.HTTPError  # type: ignore[attr-defined]
    runtime.httpx.Headers = httpx.Headers  # type: ignore[attr-defined]
    runtime.httpx.Response = httpx.Response  # type: ignore[attr-defined]
    return captured  # type: ignore[return-value]


def test_import_and_test_connector(
    authed: Tuple[Any, Dict[str, str]],
    fernet_key: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers = authed
    _isolate_artifacts(tmp_path, monkeypatch)
    _patched_outbound(monkeypatch)

    r = client.post(
        "/api/openapi-connectors/import",
        headers=headers,
        json={"name": "sample-issues", "spec_text": json.dumps(SAMPLE_SPEC)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    connector_id = body["connector"]["id"]
    operations = {op["operation_id"]: op for op in body["operations"]}
    assert "listIssues" in operations
    list_op = "listIssues"

    r = client.put(
        f"/api/openapi-connectors/{connector_id}/credentials",
        headers=headers,
        json={"auth_type": "bearer", "config": {"token": "supersecret"}},
    )
    assert r.status_code == 200, r.text

    captured = _stub_httpx_client(monkeypatch, 200, {"items": []})

    r = client.post(
        f"/api/openapi-connectors/{connector_id}/operations/{list_op}/test",
        headers=headers,
        json={
            "params": {"project": "ABC", "limit": 5},
            "headers": {"X-Trace": "t"},
        },
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["ok"] is True
    assert result["status_code"] == 200
    assert isinstance(captured, dict)
    sent_kwargs = captured.get("kwargs", {})
    sent_headers = sent_kwargs.get("headers") or {}
    # bearer token 应已被注入
    assert sent_headers.get("Authorization") == "Bearer supersecret"
    # path 参数应被替换
    assert "/projects/ABC/issues" in captured.get("url", "")

    # 调用记录已落库
    r = client.get(f"/api/openapi-connectors/{connector_id}/logs", headers=headers)
    assert r.status_code == 200
    items = r.json().get("items") or []
    assert items, "expected at least one log entry"
    assert items[0]["operation_id"] == list_op
    assert items[0]["status_code"] == 200


def test_publish_to_workflow_creates_node(
    authed: Tuple[Any, Dict[str, str]],
    fernet_key: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers = authed
    _isolate_artifacts(tmp_path, monkeypatch)
    _patched_outbound(monkeypatch)

    r = client.post(
        "/api/openapi-connectors/import",
        headers=headers,
        json={"name": "sample-publish", "spec_text": json.dumps(SAMPLE_SPEC)},
    )
    connector_id = r.json()["connector"]["id"]

    wf = client.post(
        "/api/workflow/",
        headers=headers,
        json={"name": "demo-wf", "description": ""},
    )
    assert wf.status_code == 200, wf.text
    workflow_id = wf.json()["id"]

    pub = client.post(
        f"/api/openapi-connectors/{connector_id}/publish-workflow-node",
        headers=headers,
        json={"workflow_id": workflow_id, "operation_id": "listIssues"},
    )
    assert pub.status_code == 200, pub.text
    node = pub.json()["node"]
    assert node["node_type"] == "openapi_operation"
    cfg = node["config"]
    assert cfg["connector_id"] == connector_id
    assert cfg["operation_id"] == "listIssues"


def test_workflow_engine_registers_openapi_node() -> None:
    from modstore_server.workflow_engine import workflow_engine

    assert "openapi_operation" in workflow_engine.executors


def test_employee_actions_include_openapi_tool() -> None:
    """`openapi_tool` handler 已注册到 _actions_real。"""
    from modstore_server import employee_executor

    assert hasattr(employee_executor, "_action_openapi_tool")
    actions_cfg = {
        "handlers": ["openapi_tool"],
        "openapi_tool": {"connector_id": 0, "operation_id": ""},
    }
    out = employee_executor._actions_real(
        {"actions": actions_cfg},
        {"reasoning": "demo"},
        task="t",
        employee_id="e",
        user_id=0,
    )
    handler_outputs = [o for o in out["outputs"] if o.get("handler") == "openapi_tool"]
    assert handler_outputs, "openapi_tool handler should run"
    assert handler_outputs[0]["error"]
