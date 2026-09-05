from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import Request

from app.application import mod_delivery_receipt_outbox as outbox


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


@pytest.mark.asyncio
async def test_response_loss_retries_same_install_id_and_body(pending, monkeypatch):
    request, root = pending
    sent = []

    async def post(token, path, *, method, payload):
        sent.append(copy.deepcopy(payload))
        if len(sent) == 1:
            raise ConnectionError("response lost")
        return {"receipt": {"record": {"verified": False}}}

    async def no_runtime(request, row):
        return None

    monkeypatch.setattr(
        "app.application.private_mod_delivery_artifacts.custom_delivery_remote_json", post
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
