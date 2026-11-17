import json
from unittest.mock import Mock

import pytest

from scripts.autonomy import rundeck_executor as rd
from scripts.autonomy.autonomy_types import Action, ActionType

JOB = "eaf2fd6d-c7fa-48d4-9ed0-b682ad85eca1"


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setenv("XCAGI_RUNDECK_URL", "http://127.0.0.1:4440")
    monkeypatch.setenv("XCAGI_RUNDECK_TOKEN", "test-secret")
    monkeypatch.setenv("XCAGI_RUNDECK_JOBS", json.dumps({"restart_service": JOB}))
    session = Mock()
    monkeypatch.setattr(rd.requests, "Session", lambda: session)
    return session


def response(payload):
    return Mock(status_code=200, json=lambda: payload)


def test_reuse(runtime, tmp_path):
    runtime.request.side_effect = [
        response({"id": 12}),
        response({"status": "succeeded", "job": {"id": JOB}}),
        response({"status": "succeeded", "job": {"id": JOB}}),
    ]
    action = Action(
        ActionType.RESTART_SERVICE,
        idempotency_key="incident-1",
        params={"command": "not forwarded"},
    )
    assert rd.execute(action, str(tmp_path)).ok
    assert rd.execute(action, str(tmp_path)).ok
    assert [c.args[0] for c in runtime.request.call_args_list] == ["POST", "GET", "GET"]
    assert runtime.request.call_args_list[0].kwargs["json"] == {}


def test_ambiguous_no_retry(runtime, tmp_path):
    runtime.request.side_effect = rd.requests.Timeout("test-secret")
    action = Action(ActionType.RESTART_SERVICE, idempotency_key="incident-2")
    first = rd.execute(action, str(tmp_path))
    assert not first.ok and "test-secret" not in first.detail
    assert not rd.execute(action, str(tmp_path)).ok
    assert runtime.request.call_count == 1


def test_wrong_job(runtime, tmp_path):
    runtime.request.side_effect = [
        response({"id": 12}),
        response({"status": "succeeded", "job": {"id": "other"}}),
    ]
    assert not rd.execute(Action(ActionType.RESTART_SERVICE, idempotency_key="x"), str(tmp_path)).ok


def test_plaintext(runtime, monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_RUNDECK_URL", "http://example.com")
    with pytest.raises(ValueError):
        rd.execute(Action(ActionType.RESTART_SERVICE, idempotency_key="x"), str(tmp_path))
    runtime.request.assert_not_called()


def test_new_episode_requires_verified_recovery(runtime, tmp_path):
    success = response({"status": "succeeded", "job": {"id": JOB}})
    runtime.request.side_effect = [
        response({"id": 12}),
        success,
        success,
        response({"id": 13}),
        success,
    ]
    action = Action(ActionType.RESTART_SERVICE, idempotency_key="fixed-policy-key")
    assert rd.execute(action, str(tmp_path)).ok
    rd.observe_recovery(
        str(tmp_path), health_ok=False, compose_status="running", disk_usage_percent=10
    )
    assert rd.execute(action, str(tmp_path)).ok
    rd.observe_recovery(
        str(tmp_path), health_ok=True, compose_status="running", disk_usage_percent=10
    )
    assert rd.execute(action, str(tmp_path)).ok
    assert [c.args[0] for c in runtime.request.call_args_list].count("POST") == 2


def test_disabled_and_unknown_backend_fail_closed(runtime, tmp_path, monkeypatch):
    from scripts.autonomy.cvm_adapter import CvmAutonomyAdapter

    adapter = CvmAutonomyAdapter.for_test(deploy_root=str(tmp_path), audit_dir=str(tmp_path))
    adapter._action_restart_service = Mock(side_effect=AssertionError("local execution"))
    action = Action(ActionType.RESTART_SERVICE, idempotency_key="x")
    monkeypatch.setenv("XCAGI_MAINTENANCE_EXECUTOR", "rundeck")
    runtime.request.side_effect = rd.requests.ConnectionError()
    assert not adapter.execute_action(action).ok
    monkeypatch.setenv("XCAGI_MAINTENANCE_EXECUTOR", "typo")
    assert not adapter.execute_action(action).ok
    adapter._action_restart_service.assert_not_called()


def test_redirect_is_not_followed(runtime, tmp_path):
    runtime.request.return_value = Mock(status_code=302)
    assert not rd.execute(Action(ActionType.RESTART_SERVICE, idempotency_key="x"), str(tmp_path)).ok
    assert runtime.request.call_args.kwargs["allow_redirects"] is False


def test_deadline_requests_abort_not_success(runtime, tmp_path, monkeypatch):
    runtime.request.side_effect = [response({"id": 12}), response({"abort": {"status": "pending"}})]
    times = iter([0, 121])
    monkeypatch.setattr(rd.time, "monotonic", lambda: next(times))
    result = rd.execute(Action(ActionType.RESTART_SERVICE, idempotency_key="x"), str(tmp_path))
    assert not result.ok
    assert "abort_requested" in result.detail
    assert runtime.request.call_args.args[1].endswith("execution/12/abort")
