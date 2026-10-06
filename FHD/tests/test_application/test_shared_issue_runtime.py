from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.application import shared_issue_runtime as bridge


@pytest.fixture
def host(monkeypatch, tmp_path):
    monkeypatch.setattr("app.utils.path_io.path_utils.get_app_data_dir", lambda: str(tmp_path))
    identity = {"git_sha": "a" * 40, "product_version": "1.2.3"}
    target = {
        "host_sha": "a" * 40,
        "release_id": "release-1",
        "signed_metadata_sha256": "b" * 64,
        "case_id": "case-1",
    }
    remote = AsyncMock(return_value={"items": [{"id": 7, "ready": True, "target": target}]})
    monkeypatch.setattr(bridge, "build_identity", lambda: identity)
    monkeypatch.setattr(bridge, "desktop_installation_id", lambda: "actual-client")
    monkeypatch.setattr(bridge, "get_logged_in_user", lambda _: SimpleNamespace(id=1))
    monkeypatch.setattr(
        bridge, "_private_delivery_market_token", AsyncMock(return_value="fixture-token")
    )
    monkeypatch.setattr(bridge, "custom_delivery_remote_json", remote)
    return Request({"type": "http", "headers": []}), remote, identity, target


@pytest.mark.asyncio
async def test_automatic_receipt_uses_actual_host_and_never_confirms_the_customer_result(host):
    request, remote, _, _ = host
    await bridge.report_ready_issue_identities(request)
    payload = remote.await_args.kwargs["payload"]
    assert payload["host_sha"] == "a" * 40
    assert payload["client_instance_id"] == "actual-client"
    assert payload["customer_confirmed"] is False
    assert payload["confirmation_note"] == ""


@pytest.mark.asyncio
async def test_confirmation_requires_note_and_matching_release_with_stable_retry_identity(host):
    request, remote, _, target = host
    with pytest.raises(HTTPException) as caught:
        await bridge.report_issue(request, 7, confirmed=True, note="好")
    assert caught.value.status_code == 400
    assert remote.await_count == 0
    await bridge.report_issue(request, 7, confirmed=True, note="订单现在可以保存")
    first = dict(remote.await_args.kwargs["payload"])
    await bridge.report_issue(request, 7, confirmed=True, note="订单现在可以保存")
    assert remote.await_args.kwargs["payload"] == first
    assert first["customer_confirmed"] is True
    target["host_sha"] = "c" * 40
    with pytest.raises(HTTPException) as caught:
        await bridge.report_issue(request, 7, confirmed=True, note="订单现在可以保存")
    assert caught.value.status_code == 409


@pytest.mark.asyncio
async def test_unknown_host_and_missing_market_identity_cannot_report_delivery(host, monkeypatch):
    request, remote, identity, _ = host
    identity["git_sha"] = "unknown"
    assert await bridge.pending_issues(request) == {"items": [], "runtime_unverified": True}
    assert remote.await_count == 0
    monkeypatch.setattr(bridge, "_private_delivery_market_token", AsyncMock(return_value=""))
    with pytest.raises(HTTPException) as caught:
        await bridge.pending_issues(request)
    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_confirmation_response_loss_replays_saved_payload_after_ticket_leaves_pending(host):
    request, remote, _, target = host
    pending = {"items": [{"id": 7, "ready": True, "target": target}]}
    remote.side_effect = [
        pending,
        ConnectionError("server committed but response lost"),
        {"replayed": True},
    ]
    with pytest.raises(ConnectionError):
        await bridge.report_issue(request, 7, confirmed=True, note="订单现在可以保存")
    original = dict(remote.await_args.kwargs["payload"])
    result = await bridge.report_issue(request, 7, confirmed=True, note="订单现在可以保存")
    assert result == {"replayed": True}
    assert remote.await_count == 3  # retry POST does not require a still-pending ticket
    assert remote.await_args.kwargs["payload"] == original


@pytest.mark.asyncio
async def test_list_flags_only_fixes_running_here_and_decision_forwards_owner_note(host):
    request, remote, _, target = host
    mine = {"items": [{"id": 7, "state": "awaiting_customer_verification"}, {"id": 8}]}
    remote.side_effect = [mine, {"items": [{"id": 7, "ready": True, "target": target}]}]
    listed = await bridge.list_issues(request)
    assert [(row["id"], row["ready"]) for row in listed["items"]] == [(7, True), (8, False)]
    assert remote.await_args_list[0].args[1] == "/api/customer-service/issues/mine"
    with pytest.raises(HTTPException) as caught:
        await bridge.decide_issue(
            request, 8, decision="reopen", note="不行", idempotency_key="k" * 8
        )
    assert caught.value.status_code == 400
    remote.side_effect, remote.return_value = None, {"success": True}
    await bridge.decide_issue(
        request, 8, decision="reopen", note=" 导出还是报错 ", idempotency_key="k" * 8
    )
    assert remote.await_args.args[1] == "/api/customer-service/issues/8/decision"
    assert remote.await_args.kwargs["payload"] == {
        "decision": "reopen",
        "note": "导出还是报错",
        "idempotency_key": "k" * 8,
    }


@pytest.mark.asyncio
async def test_route_surfaces_market_refusal_instead_of_internal_error(host):
    from app.fastapi_routes import issue_runtime_routes as routes

    request, remote, _, _ = host
    remote.side_effect = RuntimeError("工单仍在处理中，请等处理结果出来后再决定")
    body = routes.IssueDecision(decision="reopen", note="导出还是报错", idempotency_key="k" * 8)
    with pytest.raises(HTTPException) as caught:
        await routes.submit_issue_decision(8, body, request)
    assert (caught.value.status_code, caught.value.detail) == (
        502,
        "工单仍在处理中，请等处理结果出来后再决定",
    )
