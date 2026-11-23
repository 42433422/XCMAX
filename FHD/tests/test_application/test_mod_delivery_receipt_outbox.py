from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import Request

from app.application import mod_delivery_receipt_outbox as outbox
from app.application.private_mod_delivery_artifacts import DeliveryRemoteError


@pytest.fixture
def pending(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.infrastructure.mods.install_receipts.read_verified_install",
        lambda _: {
            "owner_scope": "tenant:1",
            "package_sha256": "b" * 64,
            "package_version": "1.1.0",
        },
    )
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(
        "app.application.desktop_delivery_receipt.desktop_installation_id",
        lambda: "fixture-device-123456",
    )
    monkeypatch.setattr("app.build_identity.build_identity", lambda: {"git_sha": "a" * 40})
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.get_logged_in_user",
        lambda request: SimpleNamespace(id=1),
    )
    monkeypatch.setattr(
        "app.application.tenant_workspace_prefs.resolve_workspace_owner_id",
        lambda request, user: "tenant:1",
    )
    outbox.record_installed_delivery(
        owner="tenant:1",
        ticket_id=9,
        artifact_kind="module",
        artifact_id="fixture-mod",
        version="1.1.0",
        package_sha256="b" * 64,
        receipt_token="fixture-grant-token-long",
    )
    return Request({"type": "http", "headers": []}), tmp_path


def _mock_remote_http(monkeypatch, handler):
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "app.fastapi_routes.market_account._market_api_base_url",
        lambda: "https://market.test",
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=transport, trust_env=False, **kwargs),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["installed", "running"])
@pytest.mark.parametrize("response_error", ["http_status", "invalid_body"])
async def test_unknown_remote_response_preserves_receipt_for_same_identity_retry(
    pending, monkeypatch, stage, response_error
):
    request, root = pending
    path = next(root.glob("mod-delivery-receipts/*/*.json"))
    original = json.loads(path.read_text())
    sent, accepted = [], {}
    failed = False

    def respond(remote_request):
        nonlocal failed
        payload = json.loads(remote_request.content)
        assert remote_request.method == "POST"
        assert remote_request.url.path == "/api/customer-service/custom-deliveries/9/installed"
        assert remote_request.headers["Authorization"] == "Bearer current-token"
        sent.append(payload)
        receipt_id = payload["receipt_id"]
        # The server committed this receipt even if the caller cannot read its response.
        assert accepted.setdefault(receipt_id, payload) == payload
        if payload["stage"] == stage and not failed:
            failed = True
            if response_error == "http_status":
                return httpx.Response(503, json={"detail": "response lost after commit"})
            return httpx.Response(200, json=[])
        return httpx.Response(
            200,
            json={"receipt": {"record": {"verified": payload["stage"] == "running"}}},
        )

    async def runtime(request, row):
        return row.get("runtime_payload") or dict(
            row["payload"],
            stage="running",
            receipt_id="fixture-runtime-receipt",
            observed_at="2026-11-24T00:00:00Z",
        )

    _mock_remote_http(monkeypatch, respond)
    monkeypatch.setattr(outbox, "_runtime_payload", runtime)
    assert await outbox.retry_delivery_receipts(request, "current-token") == {
        "installed_reported": int(stage == "running"),
        "runtime_reported": 0,
        "pending": 1,
    }
    unknown = json.loads(path.read_text())
    assert unknown["payload"] == original["payload"]
    assert unknown["owner"] == original["owner"] == "tenant:1"
    assert unknown["ticket_id"] == original["ticket_id"] == 9
    assert unknown["installed_reported"] is (stage == "running")
    assert unknown["runtime_reported"] is False
    assert unknown["last_error"] == "DeliveryRemoteError"
    if stage == "running":
        assert unknown["runtime_payload"] == sent[-1]

    assert await outbox.retry_delivery_receipts(request, "current-token") == {
        "installed_reported": int(stage == "installed"),
        "runtime_reported": 1,
        "pending": 0,
    }
    retried = [payload for payload in sent if payload["stage"] == stage]
    assert len(retried) == 2 and retried[0] == retried[1]
    assert len(sent) == 3 and len(accepted) == 2
    complete = json.loads(path.read_text())
    assert complete["payload"] == original["payload"]
    assert complete["runtime_payload"] == accepted["fixture-runtime-receipt"]
    assert complete["installed_reported"] is True
    assert complete["runtime_reported"] is True
    assert "last_error" not in complete
    assert await outbox.retry_delivery_receipts(request, "current-token") == {
        "installed_reported": 0,
        "runtime_reported": 0,
        "pending": 0,
    }
    assert len(sent) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, TypeError, AttributeError, KeyError])
async def test_unclassified_programming_error_is_not_saved_as_retryable_receipt(
    pending, monkeypatch, error_type
):
    request, root = pending
    path = next(root.glob("mod-delivery-receipts/*/*.json"))
    before = path.read_bytes()
    error = error_type("synthetic programming failure")

    def fail(remote_request):
        raise error

    _mock_remote_http(monkeypatch, fail)
    with pytest.raises(error_type) as raised:
        await outbox.retry_delivery_receipts(request, "current-token")
    assert raised.value is error
    assert path.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ConnectionError, DeliveryRemoteError])
async def test_response_loss_retries_same_install_id_and_body(pending, monkeypatch, failure):
    request, root = pending
    sent = []

    def post(request):
        assert request.method == "POST"
        assert request.url.path == "/api/customer-service/custom-deliveries/9/installed"
        assert request.headers["Authorization"] == "Bearer current-token"
        sent.append(json.loads(request.content))
        if len(sent) == 1:
            if failure is ConnectionError:
                raise httpx.ReadError("response lost", request=request)
            return httpx.Response(503, json={"detail": "receipt response unavailable"})
        return httpx.Response(200, json={"receipt": {"record": {"verified": False}}})

    async def no_runtime(request, row):
        return None

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: client(transport=httpx.MockTransport(post), **kwargs)
    )
    monkeypatch.setattr(outbox, "_runtime_payload", no_runtime)
    assert (await outbox.retry_delivery_receipts(request, "current-token"))["pending"] == 1
    assert (await outbox.retry_delivery_receipts(request, "current-token"))[
        "installed_reported"
    ] == 1
    assert sent[0] == sent[1]
    row = json.loads(next(root.glob("mod-delivery-receipts/*/*.json")).read_text())
    assert row["installed_reported"] is True
    assert row["runtime_reported"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, TypeError])
@pytest.mark.parametrize(
    "retry", [outbox.retry_delivery_receipts, outbox.retry_delivery_receipts_best_effort]
)
async def test_programming_error_surfaces_without_marking_receipt(
    pending, monkeypatch, retry, error_type
):
    request, root = pending
    path = next(root.glob("mod-delivery-receipts/*/*.json"))
    original = path.read_bytes()
    error = error_type("invalid internal contract")

    async def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.custom_delivery_remote_json", broken
    )
    with pytest.raises(error_type) as caught:
        await retry(request, "current-token")
    assert caught.value is error
    row = json.loads(path.read_text())
    assert row["installed_reported"] is False and row["runtime_reported"] is False
    assert "last_error" not in row
    assert path.read_bytes() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_stage", ["installed", "running"])
async def test_http_response_loss_retries_original_durable_receipt(
    pending, monkeypatch, failed_stage
):
    request, root = pending
    sent = []
    lost = False

    def respond(remote_request):
        nonlocal lost
        payload = json.loads(remote_request.content)
        sent.append(payload)
        if payload["stage"] == failed_stage and not lost:
            lost = True
            return httpx.Response(503, json={"detail": "response lost after server commit"})
        return httpx.Response(
            200, json={"receipt": {"record": {"verified": payload["stage"] == "running"}}}
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(respond), **kwargs),
    )
    monkeypatch.setattr(
        "app.fastapi_routes.market_account._market_api_base_url", lambda: "http://market.test"
    )

    async def runtime(request, row):
        return dict(row["payload"], stage="running", receipt_id="original-runtime-receipt")

    monkeypatch.setattr(outbox, "_runtime_payload", runtime)
    first = await outbox.retry_delivery_receipts(request, "current-token")
    assert first == {
        "installed_reported": int(failed_stage == "running"),
        "runtime_reported": 0,
        "pending": 1,
    }
    path = next(root.glob("mod-delivery-receipts/*/*.json"))
    row = json.loads(path.read_text())
    assert row["last_error"] == "DeliveryRemoteError"
    assert row["installed_reported"] is (failed_stage == "running")
    assert row["runtime_reported"] is False

    second = await outbox.retry_delivery_receipts(request, "current-token")
    assert second == {
        "installed_reported": int(failed_stage == "installed"),
        "runtime_reported": 1,
        "pending": 0,
    }
    retried = [payload for payload in sent if payload["stage"] == failed_stage]
    assert len(retried) == 2 and retried[0] == retried[1]
    row = json.loads(path.read_text())
    assert row["runtime_reported"] is True
    assert "last_error" not in row


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["send", "probe"])
@pytest.mark.parametrize("best_effort", [False, True])
async def test_programming_error_propagates_without_rewriting_receipt(
    pending, monkeypatch, boundary, best_effort
):
    request, root = pending
    path = next(root.glob("mod-delivery-receipts/*/*.json"))
    if boundary == "probe":
        row = json.loads(path.read_text())
        row["installed_reported"] = True
        outbox._save(path, row)
    original = path.read_bytes()
    error = RuntimeError("unexpected implementation failure")
    calls = []

    async def post(*args, **kwargs):
        calls.append("send")
        raise error

    async def runtime(*args):
        calls.append("probe")
        raise error

    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.custom_delivery_remote_json", post
    )
    monkeypatch.setattr(outbox, "_runtime_payload", runtime)
    retry = (
        outbox.retry_delivery_receipts_best_effort
        if best_effort
        else outbox.retry_delivery_receipts
    )
    with pytest.raises(RuntimeError) as failure:
        await retry(request, "current-token")
    assert failure.value is error
    assert calls == [boundary]
    assert path.read_bytes() == original


@pytest.mark.asyncio
async def test_unverified_server_runtime_stays_pending_until_verified(pending, monkeypatch):
    request, _ = pending
    verified = False

    async def post(token, path, *, method, payload):
        return {"receipt": {"record": {"verified": verified and payload["stage"] == "running"}}}

    async def runtime(request, row):
        return dict(row["payload"], stage="running", receipt_id="stable-runtime-id")

    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.custom_delivery_remote_json", post
    )
    monkeypatch.setattr(outbox, "_runtime_payload", runtime)
    first = await outbox.retry_delivery_receipts(request, "current-token")
    assert first == {"installed_reported": 1, "runtime_reported": 0, "pending": 1}
    verified = True
    second = await outbox.retry_delivery_receipts(request, "current-token")
    assert second == {"installed_reported": 0, "runtime_reported": 1, "pending": 0}


@pytest.mark.asyncio
async def test_account_switch_does_not_report_other_owners_grant(pending, monkeypatch):
    request, _ = pending
    monkeypatch.setattr(
        "app.application.tenant_workspace_prefs.resolve_workspace_owner_id",
        lambda request, user: "tenant:2",
    )

    async def unexpected(*args, **kwargs):
        pytest.fail("another owner's receipt must not be sent")

    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.custom_delivery_remote_json", unexpected
    )
    assert await outbox.retry_delivery_receipts(request, "account-two-token") == {
        "installed_reported": 0,
        "runtime_reported": 0,
        "pending": 0,
    }


@pytest.mark.asyncio
async def test_business_failure_is_reported_once_to_original_ticket_without_runtime_success(
    pending, monkeypatch
):
    request, root = pending
    sent = []

    async def post(token, path, *, method, payload):
        sent.append((path, copy.deepcopy(payload)))
        return {
            "receipt": {
                "record": {
                    "verified": False,
                    "failure_recorded": payload["stage"] == "verification_failed",
                }
            }
        }

    async def failed_runtime(request, row):
        return dict(row["payload"], stage="verification_failed", receipt_id="failed-runtime-id")

    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.custom_delivery_remote_json", post
    )
    monkeypatch.setattr(outbox, "_runtime_payload", failed_runtime)
    result = await outbox.retry_delivery_receipts(request, "current-token")
    assert result["runtime_reported"] == 0
    assert result["pending"] == 0
    assert len(sent) == 2
    assert all(path == "/api/customer-service/custom-deliveries/9/installed" for path, _ in sent)
    await outbox.retry_delivery_receipts(request, "current-token")
    assert len(sent) == 2
    row = json.loads(next(root.glob("mod-delivery-receipts/*/*.json")).read_text())
    assert row["failure_reported"] is True
    assert row["runtime_reported"] is False


@pytest.mark.asyncio
async def test_concurrent_refresh_does_not_resend_inflight_receipt_or_change_body(
    pending, monkeypatch
):
    import asyncio

    request, _ = pending
    entered, release = asyncio.Event(), asyncio.Event()
    sent = []

    async def post(token, path, *, method, payload):
        sent.append(copy.deepcopy(payload))
        entered.set()
        await release.wait()
        return {}

    async def no_runtime(request, row):
        return None

    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.custom_delivery_remote_json", post
    )
    monkeypatch.setattr(outbox, "_runtime_payload", no_runtime)
    task = asyncio.create_task(outbox.retry_delivery_receipts(request, "token"))
    await entered.wait()
    assert (await outbox.retry_delivery_receipts(request, "token"))["pending"] == 1
    assert len(sent) == 1
    release.set()
    await task


@pytest.mark.asyncio
async def test_corrupt_row_does_not_stop_other_durable_receipts(pending, monkeypatch):
    request, root = pending
    directory = next(root.glob("mod-delivery-receipts/*"))
    (directory / "corrupt.json").write_text("{not-json")

    async def post(*args, **kwargs):
        return {}

    async def no_runtime(*args):
        return None

    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.custom_delivery_remote_json", post
    )
    monkeypatch.setattr(outbox, "_runtime_payload", no_runtime)
    result = await outbox.retry_delivery_receipts(request, "token")
    assert result == {"installed_reported": 1, "runtime_reported": 0, "pending": 2}
    assert (directory / "corrupt.json").read_text() == "{not-json"


@pytest.mark.asyncio
async def test_saved_grant_without_installation_never_claims_installed(pending, monkeypatch):
    request, _ = pending
    monkeypatch.setattr(
        "app.infrastructure.mods.install_receipts.read_verified_install", lambda _: None
    )

    async def unexpected(*args, **kwargs):
        pytest.fail("a grant is not installed-package evidence")

    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.custom_delivery_remote_json", unexpected
    )
    assert await outbox.retry_delivery_receipts(request, "token") == {
        "installed_reported": 0,
        "runtime_reported": 0,
        "pending": 1,
    }


@pytest.mark.asyncio
async def test_revoked_probe_entitlement_stays_pending_and_does_not_trigger_rework(
    pending, monkeypatch
):
    from fastapi import HTTPException

    request, _ = pending
    sent = []

    async def post(token, path, *, method, payload):
        sent.append(payload["stage"])
        return {}

    async def denied(*args):
        raise HTTPException(403, "entitlement revoked")

    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.custom_delivery_remote_json", post
    )
    monkeypatch.setattr(outbox, "_runtime_payload", denied)
    assert (await outbox.retry_delivery_receipts(request, "token"))["pending"] == 1
    assert sent == ["installed"]
