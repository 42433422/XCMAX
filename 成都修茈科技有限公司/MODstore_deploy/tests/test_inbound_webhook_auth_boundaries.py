"""Real routers plus CSRF middleware; execution is mocked, no external requests."""

import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modstore_server import inbound_webhook_api as inbound
from modstore_server.api.csrf import CSRFMiddleware
from modstore_server.api.xss_sanitizer import XSSSanitizerMiddleware
from modstore_server.workflow_api import hooks

SECRET = "synthetic-webhook-test-secret"
BODY = b'{"task_description": "synthetic \\u4e00 task<script>unsafe()</script>"}'


@pytest.fixture
def boundary(monkeypatch):
    monkeypatch.setenv("MODSTORE_DISABLE_CSRF", "0")
    monkeypatch.setenv("MODSTORE_DINGTALK_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("WORKFLOW_WEBHOOK_DEFAULT_SECRET", raising=False)
    enqueue = Mock(return_value="synthetic-job")
    run = Mock(return_value={"ok": True})
    monkeypatch.setattr(inbound, "_resolve_actor_user_id", lambda: 7)
    monkeypatch.setattr(inbound, "_enqueue_orchestrate_job", enqueue)
    monkeypatch.setattr(hooks, "run_workflow_for_trigger", run)
    trigger = SimpleNamespace(config_json="{}", workflow_id=11, user_id=7)
    query = Mock()
    query.filter.return_value.first.return_value = trigger
    db = Mock()
    db.query.return_value = query
    app = FastAPI()
    app.include_router(inbound.router)
    app.include_router(hooks.workflow_hooks_router)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(XSSSanitizerMiddleware)
    app.dependency_overrides[hooks.get_db] = lambda: db
    with TestClient(app, headers={"Content-Type": "application/json"}) as client:
        yield client, trigger, enqueue, run


def ding_headers(timestamp=None):
    timestamp = str(int(time.time() * 1000) if timestamp is None else timestamp)
    signature = base64.b64encode(
        hmac.new(SECRET.encode(), f"{timestamp}\n{SECRET}".encode(), hashlib.sha256).digest()
    ).decode()
    return {"timestamp": timestamp, "sign": signature}


def csrf(client):
    client.cookies.set("csrf_token", "synthetic-csrf")
    return {"X-CSRF-Token": "synthetic-csrf"}


@pytest.mark.parametrize("missing", [("timestamp", "sign"), ("timestamp",), ("sign",)])
def test_dingtalk_requires_both_signature_headers(boundary, missing):
    client, _, enqueue, _ = boundary
    headers = ding_headers()
    for name in missing:
        del headers[name]
    response = client.post(
        "/api/inbound/webhooks/dingtalk", content=BODY, headers=headers | csrf(client)
    )
    assert response.status_code == 401
    enqueue.assert_not_called()


@pytest.mark.parametrize("timestamp", ["not-a-number", "0", "9" * 30])
def test_dingtalk_rejects_invalid_or_expired_signed_timestamp(boundary, timestamp):
    client, _, enqueue, _ = boundary
    response = client.post(
        "/api/inbound/webhooks/dingtalk",
        content=BODY,
        headers=ding_headers(timestamp) | csrf(client),
    )
    assert response.status_code == 401
    enqueue.assert_not_called()


def test_workflow_without_secret_never_executes(boundary):
    client, _, _, run = boundary
    response = client.post(
        "/api/workflow-hooks/webhook/synthetic", content=BODY, headers=csrf(client)
    )
    assert response.status_code == 503
    run.assert_not_called()


@pytest.mark.parametrize("provider", ["dingtalk", "workflow"])
def test_signed_machine_request_works_but_browser_cookie_still_needs_csrf(boundary, provider):
    client, trigger, enqueue, run = boundary
    trigger.config_json = json.dumps({"secret": SECRET})
    path, headers = (
        ("/api/inbound/webhooks/dingtalk", ding_headers())
        if provider == "dingtalk"
        else (
            "/api/workflow-hooks/webhook/synthetic",
            {
                "X-Webhook-Signature": "sha256="
                + hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
            },
        )
    )
    assert client.post(path, content=BODY, headers=headers).status_code == 200
    if provider == "workflow":
        assert run.call_args.kwargs["user_id"] == 7
        assert run.call_args.kwargs["input_data"]["task_description"] == "synthetic 一 task"
    enqueue.reset_mock()
    run.reset_mock()
    client.cookies.set("session", "ambient-browser-session")
    assert client.post(path, content=BODY, headers=headers).status_code == 403
    enqueue.assert_not_called()
    run.assert_not_called()
    assert client.post(path, content=BODY, headers=headers | csrf(client)).status_code == 200


@pytest.mark.parametrize("provider", ["dingtalk", "workflow"])
def test_unsigned_machine_request_never_executes(boundary, provider):
    client, trigger, enqueue, run = boundary
    trigger.config_json = json.dumps({"secret": SECRET})
    path = (
        "/api/inbound/webhooks/dingtalk"
        if provider == "dingtalk"
        else "/api/workflow-hooks/webhook/synthetic"
    )
    assert client.post(path, content=BODY).status_code in (401, 403)
    enqueue.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize("provider", ["github", "feishu", "generic"])
def test_other_protocol_receivers_still_authenticate_without_cookies(
    boundary, monkeypatch, provider
):
    client, _, enqueue, _ = boundary
    env = {
        "github": "MODSTORE_GITHUB_WEBHOOK_SECRET",
        "feishu": "MODSTORE_FEISHU_VERIFY_TOKEN",
        "generic": "MODSTORE_GENERIC_WEBHOOK_TOKEN",
    }
    monkeypatch.setenv(env[provider], SECRET)
    path = f"/api/inbound/webhooks/{provider}"
    assert client.post(path, content=BODY).status_code == 401
    enqueue.assert_not_called()
    body, headers = BODY, {}
    if provider == "github":
        headers = {
            "X-Hub-Signature-256": "sha256="
            + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        }
    elif provider == "feishu":
        body = json.dumps({"header": {"token": SECRET, "event_type": "synthetic"}}).encode()
    else:
        headers = {"X-MODSTORE-TOKEN": SECRET}
    assert client.post(path, content=body, headers=headers).status_code == 200
    enqueue.assert_called_once()
    enqueue.reset_mock()
    client.cookies.set("session", "ambient-browser-session")
    assert client.post(path, content=body, headers=headers).status_code == 403
    enqueue.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        "/api/inbound/webhooks/unknown",
        "/api/inbound/webhooks/status",
        "/api/workflow-hooks/webhook/",
        "/api/workflow-hooks/webhook/a/b",
        "/api/admin/users",
    ],
)
def test_machine_csrf_exception_does_not_cover_other_paths(boundary, path):
    client, _, _, _ = boundary
    assert client.post(path, content=BODY, follow_redirects=False).status_code == 403


@pytest.mark.parametrize("provider", ["dingtalk", "workflow"])
def test_bad_signature_and_tampered_workflow_body_are_rejected(boundary, provider):
    client, trigger, enqueue, run = boundary
    trigger.config_json = json.dumps({"secret": SECRET})
    path, headers = (
        ("/api/inbound/webhooks/dingtalk", ding_headers() | {"sign": "wrong"})
        if provider == "dingtalk"
        else (
            "/api/workflow-hooks/webhook/synthetic",
            {
                "X-Webhook-Signature": "sha256="
                + hmac.new(SECRET.encode(), b"{}", hashlib.sha256).hexdigest()
            },
        )
    )
    assert client.post(path, content=BODY, headers=headers).status_code in (401, 403)
    enqueue.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize(
    "offset,expected",
    [(-3600001, 401), (-3600000, 200), (0, 200), (3600000, 200), (3600001, 401)],
)
def test_dingtalk_timestamp_window_boundaries(boundary, monkeypatch, offset, expected):
    from datetime import UTC, datetime

    now = 1800000000000
    monkeypatch.setattr(
        inbound,
        "datetime",
        SimpleNamespace(now=lambda tz: datetime.fromtimestamp(now / 1000, UTC)),
    )
    client, _, enqueue, _ = boundary
    response = client.post(
        "/api/inbound/webhooks/dingtalk",
        content=BODY,
        headers=ding_headers(now + offset),
    )
    assert response.status_code == expected
    assert enqueue.call_count == (expected == 200)


def test_workflow_default_secret_is_verified_before_execution(boundary, monkeypatch):
    client, _, _, run = boundary
    monkeypatch.setenv("WORKFLOW_WEBHOOK_DEFAULT_SECRET", SECRET)
    headers = {
        "X-Hub-Signature-256": "sha256="
        + hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
    }
    assert (
        client.post(
            "/api/workflow-hooks/webhook/synthetic", content=BODY, headers=headers
        ).status_code
        == 200
    )
    assert run.call_args.kwargs["input_data"]["task_description"] == "synthetic 一 task"


@pytest.mark.parametrize("provider", ["dingtalk", "workflow"])
def test_non_ascii_signature_rejected_without_execution(boundary, provider):
    client, trigger, enqueue, run = boundary
    trigger.config_json = json.dumps({"secret": SECRET})
    path = (
        "/api/inbound/webhooks/dingtalk"
        if provider == "dingtalk"
        else "/api/workflow-hooks/webhook/synthetic"
    )
    headers = [
        (b"timestamp", str(int(time.time() * 1000)).encode()),
        (b"sign" if provider == "dingtalk" else b"X-Webhook-Signature", b"\xff"),
    ]
    assert client.post(path, content=BODY, headers=headers).status_code in (401, 403)
    enqueue.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_machine_csrf_exception_is_post_only(boundary, method):
    client, _, enqueue, _ = boundary
    assert getattr(client, method)("/api/inbound/webhooks/dingtalk").status_code == 403
    enqueue.assert_not_called()
