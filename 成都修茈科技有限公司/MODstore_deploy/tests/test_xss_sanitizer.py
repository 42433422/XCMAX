from __future__ import annotations

import base64
import json
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from modstore_server.middleware_registry import register_all_middleware

_CANDIDATE_PATH = "/api/service/mac-control/training/candidates"
_SERVICE_TOKEN = "synthetic-candidate-transport-token-" + "t" * 32


def _candidate_body() -> dict:
    text = "<FIELD>keep</FIELD>\n<script>literal()</script>"
    package = base64.b64encode(b"synthetic-native-package\x00\xff").decode()
    return {
        "request_key": "opaque-transport-fixture",
        "surface": "workflow_nl_prompt",
        "resource_id": "workflow_nl_generator",
        "source_sha": "a" * 40,
        "failure_run_ids": ["workflow-customer:fixture"],
        "workflow_run_id": 1,
        "files": {
            "baseline": text,
            "candidate": text + "\nnext",
            "tests": json.dumps({"task": text, "package": package}, indent=2),
        },
        "bundle_json": json.dumps({"task": text}, indent=2),
        "result_json": json.dumps({"output": text, "package": package}, indent=2),
    }


@pytest.fixture
def candidate_transport(monkeypatch):
    """Exercise the original router/auth; capture the candidate gate's opaque inputs."""
    from modstore_server import mac_control_dispatch_api as dispatch
    from modstore_server import retort_evolution_api, retort_training_candidates

    monkeypatch.setenv(dispatch.TOKEN_DIGESTS_ENV, dispatch.token_digest(_SERVICE_TOKEN))
    submit = Mock(return_value="synthetic-candidate-request")
    monkeypatch.setattr(retort_training_candidates, "create_training_candidate", submit)
    monkeypatch.setattr(retort_evolution_api, "_advance", Mock())
    received = []

    async def capture_body(request: Request):
        received.append(await request.body())

    async def echo(request: Request):
        return {"raw": (await request.body()).decode("utf-8")}

    app = FastAPI()
    app.include_router(dispatch.router, dependencies=[Depends(capture_body)])
    for path in ("/api/{rest:path}", "/v1/{rest:path}", "/admin/{rest:path}"):
        app.add_api_route(path, echo, methods=["POST", "PUT", "PATCH", "DELETE"])
    register_all_middleware(app)
    with TestClient(app) as client:
        yield client, submit, received


def test_training_candidate_preserves_opaque_bytes_through_original_route(candidate_transport):
    client, submit, received = candidate_transport
    body = _candidate_body()
    raw = json.dumps(body, indent=2).encode("utf-8")
    response = client.post(
        _CANDIDATE_PATH,
        content=raw,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_SERVICE_TOKEN}",
        },
    )

    assert response.status_code == 202, response.text
    assert received == [raw]
    submit.assert_called_once_with(body)


@pytest.mark.parametrize("token", ["", "invalid-service-token-" + "x" * 32])
def test_training_candidate_opaque_transport_still_requires_service_token(
    candidate_transport, token
):
    client, submit, _ = candidate_transport
    response = client.post(
        _CANDIDATE_PATH,
        json=_candidate_body(),
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )

    assert response.status_code == 401, response.text
    submit.assert_not_called()


def test_training_candidate_opaque_transport_keeps_gate_rejection(candidate_transport):
    client, submit, _ = candidate_transport
    submit.side_effect = ValueError("training_reproduction_source_unbound")
    body = _candidate_body()
    response = client.post(
        _CANDIDATE_PATH,
        json=body,
        headers={"Authorization": f"Bearer {_SERVICE_TOKEN}"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "training_reproduction_source_unbound"
    submit.assert_called_once_with(body)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/ordinary-json"),
        ("POST", _CANDIDATE_PATH + "/other"),
        ("POST", _CANDIDATE_PATH + "-other"),
        ("PUT", _CANDIDATE_PATH),
        ("PATCH", "/admin/input-integrity"),
        ("DELETE", "/v1/input-integrity"),
    ],
)
def test_all_json_inputs_preserve_original_values_and_bytes(candidate_transport, method, path):
    client, submit, _ = candidate_transport
    payload = {
        "备注": '  原意 A&B <原样> &lt;原实体&gt; "引号" ',
        "code": "if a < b:\n    print('<script>literal()</script>')",
        "nested": [None, False, 0, {"<&key>": "<!DOCTYPE html><FIELD>中文</FIELD>"}],
    }
    raw = (" \n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n ").encode()
    response = client.request(
        method, path, content=raw, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["raw"].encode() == raw
    assert json.loads(response.json()["raw"]) == payload
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    submit.assert_not_called()
