"""HTTP-level ACK loss, original-request readback and remaining fleet work."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from tests.test_application.test_super_employee_dispatch_recovery import _ack, _service


def receipt(body, index):
    payload = {key: value for key, value in body.items() if key != "client_request_id"}
    return {
        "task": {"id": "task-original", "status": "running"},
        "subtask": {
            "id": f"sub-{index}",
            "task_id": "task-original",
            "device_id": body["device_id"],
        },
        "request": {
            "client_request_id": body["client_request_id"],
            "payload_sha256": hashlib.sha256(
                json.dumps(
                    payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest(),
        },
    }


def server(tmp_path, monkeypatch, *, devices=1, lost_index=1):
    created = {}
    state = {"available": False}

    def submit(request):
        body = json.loads(request.content)
        key = body["client_request_id"]
        assert key not in created, "replayed a device dispatch"
        result = receipt(body, len(created) + 1)
        created[key] = (body, result)
        if len(created) == lost_index:
            raise httpx.ReadTimeout("server committed, acknowledgement lost", request=request)
        return httpx.Response(200, json=result)

    def read(request):
        if not state["available"]:
            return httpx.Response(404, json={"error": "request_not_found"})
        key = request.url.path.rsplit("/", 1)[-1]
        result = deepcopy(created[key][1])
        if mutate := state.get("mutate"):
            mutate(result)
        return httpx.Response(200, json=result)

    create, requests = _service(
        tmp_path, monkeypatch, submit, devices=devices, receipt_handler=read
    )
    return create, requests, created, state


def test_fresh_service_recovers_first_ack_from_original_key_without_post(tmp_path, monkeypatch):
    create, requests, created, state = server(tmp_path, monkeypatch)
    context = {"request_id": "lost-first-ack", "mode": "code"}
    result = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert result["dispatch"]["status"] == "dispatch_unknown"
    state["available"] = True
    # Reading history is the existing polling consumer, including after restart.
    messages = create().list_messages(user_id=7)
    row = next(item for item in messages if item["role"] == "system")
    assert row["task_id"] == "task-original" and row["status"] == "running"
    recovered = create().read_dispatch_receipt(
        user_id=7, request_id=context["request_id"], task_id=""
    )
    assert recovered["dispatch"]["task_id"] == "task-original"
    assert len(created) == requests.count(("POST", "para.test", "/api/tasks")) == 1
    assert not any(host == "hook.test" for _, host, _ in requests)


def test_second_ack_readback_keeps_both_original_subtasks(tmp_path, monkeypatch):
    create, requests, created, state = server(tmp_path, monkeypatch, devices=2, lost_index=2)
    context = {"request_id": "lost-second-ack", "mode": "code", "para_tier": 2}
    first = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert len(first["dispatch"]["devices"]) == 1
    state["available"] = True
    replay = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert replay["dispatch"]["accepted"] is True
    assert [item["subtask_id"] for item in replay["dispatch"]["devices"]] == ["sub-1", "sub-2"]
    assert len(created) == requests.count(("POST", "para.test", "/api/tasks")) == 2


def test_read_only_recovery_never_dispatches_remaining_devices(tmp_path, monkeypatch):
    create, requests, created, state = server(tmp_path, monkeypatch, devices=2)
    context = {"request_id": "partly-sent", "mode": "code", "para_tier": 2}
    first = create().invoke(user_id=7, message="修复登录问题", context=context)
    original = Path(first["dispatch"]["outbox_path"]).read_bytes()
    state["available"] = True
    before = len(requests)
    result = create().read_dispatch_receipt(user_id=7, request_id=context["request_id"], task_id="")
    assert result["dispatch"]["status"] == "dispatch_pending"
    assert result["dispatch"]["accepted"] is False
    assert result["dispatch"]["reconciliation_required"] is False
    assert all(method == "GET" for method, _, _ in requests[before:])
    assert Path(first["dispatch"]["outbox_path"]).read_bytes() == original
    assert len(created) == 1
    # An authorized continuation sends only the previously unsent frozen plan.
    monkeypatch.setenv("MODSTORE_PARA_BASE_BRANCH", "different-after-restart")
    resumed = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert resumed["dispatch"]["accepted"] is True
    bodies = [entry[0] for entry in created.values()]
    assert len(bodies) == 2 and bodies[1]["task_id"] == "task-original"
    assert bodies[1]["branch"] == bodies[0]["branch"]
    assert requests.count(("POST", "para.test", "/api/tasks")) == 2


@pytest.mark.parametrize("field", ["client_request_id", "payload_sha256", "task_id", "device_id"])
def test_mismatched_original_receipt_stays_unknown(tmp_path, monkeypatch, field):
    create, requests, created, state = server(tmp_path, monkeypatch)
    context = {"request_id": "bad-receipt", "mode": "code"}
    create().invoke(user_id=7, message="修复登录问题", context=context)
    state["available"] = True
    state["mutate"] = lambda value: value[
        "request" if field in {"client_request_id", "payload_sha256"} else "subtask"
    ].update({field: "unrelated"})
    result = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert result["dispatch"]["status"] == "dispatch_unknown"
    assert not result["dispatch"]["accepted"]
    assert len(created) == requests.count(("POST", "para.test", "/api/tasks")) == 1
    original = Path(result["dispatch"]["outbox_path"]).read_bytes()
    observed = create().read_dispatch_receipt(
        user_id=7, request_id=context["request_id"], task_id=""
    )
    assert observed["dispatch"]["status"] == "dispatch_unknown"
    assert observed["dispatch"]["reconciliation_required"] is True
    assert Path(result["dispatch"]["outbox_path"]).read_bytes() == original
    assert len(created) == requests.count(("POST", "para.test", "/api/tasks")) == 1


def test_another_local_user_cannot_reconcile_original_request(tmp_path, monkeypatch):
    create, requests, _, state = server(tmp_path, monkeypatch)
    create().invoke(
        user_id=7, message="修复登录问题", context={"request_id": "owner-bound", "mode": "code"}
    )
    state["available"] = True
    before = len(requests)
    assert create().read_dispatch_receipt(user_id=8, request_id="owner-bound", task_id="") is None
    assert len(requests) == before


@pytest.mark.parametrize("version", [None, 0, 2, True, "1"])
def test_old_server_is_blocked_before_dispatch_and_can_resume_after_upgrade(
    tmp_path, monkeypatch, version
):
    create, requests = _service(tmp_path, monkeypatch, _ack, recovery_version=version)
    context = {"request_id": "requires-server-contract", "mode": "code"}
    result = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert result["dispatch"]["status"] == "dispatch_error"
    assert result["dispatch"]["queued"] is False
    assert result["dispatch"]["reason"] == "para_original_request_recovery_unavailable"
    assert not any(method == "POST" for method, _, _ in requests)
    upgraded, upgraded_requests = _service(tmp_path, monkeypatch, _ack)
    resumed = upgraded().invoke(user_id=7, message="修复登录问题", context=context)
    assert resumed["dispatch"]["accepted"] is True
    assert upgraded_requests.count(("POST", "para.test", "/api/tasks")) == 1


@pytest.mark.parametrize("field", ["client_request_id", "payload_sha256", "task_id", "device_id"])
def test_first_post_must_return_bound_original_receipt(tmp_path, monkeypatch, field):
    def submit(request):
        value = _ack(request).json()
        value["request" if field in {"client_request_id", "payload_sha256"} else "subtask"][
            field
        ] = "unrelated"
        return httpx.Response(200, json=value)

    create, requests = _service(tmp_path, monkeypatch, submit)
    context = {"request_id": "bad-initial-ack", "mode": "code"}
    for _ in range(2):
        result = create().invoke(user_id=7, message="修复登录问题", context=context)
        assert result["dispatch"]["status"] == "dispatch_unknown"
        assert not result["dispatch"]["accepted"]
    assert requests.count(("POST", "para.test", "/api/tasks")) == 1


def test_restart_after_last_device_ack_only_finalizes_original_receipt(tmp_path, monkeypatch):
    create, requests = _service(tmp_path, monkeypatch, _ack)
    first = create()
    persist = first._dispatching._persist_receipt

    def stop_before_accepted(request, result):
        if result.get("status") == "accepted":
            raise SystemExit("last acknowledgement saved, final projection not yet saved")
        return persist(request, result)

    monkeypatch.setattr(first._dispatching, "_persist_receipt", stop_before_accepted)
    context = {"request_id": "last-ack-saved", "mode": "code"}
    with pytest.raises(SystemExit):
        first.invoke(user_id=7, message="修复登录问题", context=context)
    resumed = create().invoke(user_id=7, message="修复登录问题", context=context)
    assert resumed["dispatch"]["accepted"] is True
    assert resumed["dispatch"]["devices"][0]["subtask_id"] == "sub-1"
    assert requests.count(("POST", "para.test", "/api/tasks")) == 1
