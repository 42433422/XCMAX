from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import types

import pytest
from fastapi.testclient import TestClient

from modstore_server.api.app_factory import create_app, load_default_config
from modstore_server.api.deps import get_current_user


def _reset_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "management-work.sqlite"))
    # Unit tests monkeypatch the orchestrator in-process. Production defaults
    # to the killable child-process runner and has dedicated isolation tests.
    monkeypatch.setenv("MODSTORE_MANAGEMENT_WORK_EXECUTION_MODE", "in_process")
    monkeypatch.setenv(
        "MODSTORE_MANAGEMENT_EVIDENCE_HMAC_KEY", "test-evidence-key-32-bytes-minimum"
    )
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()
    return models


def _acceptance_audit_graph(
    criteria: list[dict],
    *,
    verdict: str = "PASS",
    evidence_refs: list[str] | None = None,
) -> dict:
    rows = [
        {
            "criterion_id": row["criterion_id"],
            "criterion": row["criterion"],
            "status": "pass" if verdict == "PASS" else "fail",
            "evidence_refs": list(evidence_refs or ["evidence_1"]),
            "reason": "已核对真实执行结果",
        }
        for row in criteria
    ]
    report = {
        "status": "success",
        "verdict": verdict,
        "criteria": rows,
        "summary": "独立签收员已逐条核对验收标准与证据",
        "risks": [],
    }
    return {
        "ok": True,
        "status": "completed",
        "accepted_completion": True,
        "nodes": [
            {
                "employee_id": "delivery-receipt-officer",
                "status": "success",
                "result": {
                    "result": {
                        "outputs": [
                            {
                                "handler": "llm_md",
                                "output": json.dumps(report, ensure_ascii=False),
                            }
                        ]
                    }
                },
            }
        ],
    }


def _passing_verification_receipt(task_id: str) -> tuple[str, str]:
    from modstore_server.management_work_evidence import (
        collect_independent_fact_snapshot,
        persist_fact_snapshot,
    )
    from modstore_server.management_work_service import (
        _record_verification_receipt,
        get_work_item,
    )

    item = get_work_item(task_id, include_timeline=False)
    runtime_result = {"ok": True, "status": "completed", "summary": "测试候选交付"}
    snapshot = collect_independent_fact_snapshot(
        task_id=task_id,
        employee_id=str(item["owner_employee_id"]),
        task_text="只读测试候选交付",
        task_input={"external_side_effects": False},
        runtime_result=runtime_result,
    )
    persist_fact_snapshot(
        task_id=task_id,
        attempt=int(item["attempt_count"]),
        snapshot=snapshot,
    )
    receipt = _record_verification_receipt(
        task_id=task_id,
        result_digest=str(snapshot["runtime_claim_sha256"]),
        fact_snapshot=snapshot,
        audit={"outcome": "pass", "reason": "pytest verified", "report": {}},
    )
    return str(receipt["receipt_id"]), str(snapshot["runtime_claim_sha256"])


def test_management_owner_im_never_blocks_state_transition(monkeypatch):
    import modstore_server.management_work_service as service
    import modstore_server.notification_service as notification

    started = threading.Event()
    release = threading.Event()
    notifications = []
    sent_im = {}

    monkeypatch.setattr(
        notification,
        "create_notification",
        lambda **kwargs: notifications.append(kwargs),
    )

    def _slow_im(*args, **kwargs):
        sent_im.update(args=args, kwargs=kwargs)
        started.set()
        release.wait(timeout=2)
        return False

    monkeypatch.setattr(notification, "employee_message_to_boss", _slow_im)
    before = time.monotonic()
    service._notify_owner(
        {
            "created_by_user_id": 9,
            "task_id": "mwi_non_blocking",
            "owner_employee_id": "intent-analyst",
            "status": "waiting_decision",
            "priority": "P0",
            "source_ref": "fhd:user:42:tenant:8",
        },
        title="等你决策",
        content="请选择严格验收",
        event="management_work.decision_required",
    )
    elapsed = time.monotonic() - before
    try:
        assert elapsed < 0.25
        assert notifications
        assert started.wait(timeout=1)
        assert sent_im["kwargs"]["notification"]["task_id"] == "mwi_non_blocking"
        assert sent_im["kwargs"]["notification"]["route"] == "management_work/mwi_non_blocking"
        assert sent_im["kwargs"]["notification"]["recipient_kind"] == "management_owner"
        assert sent_im["kwargs"]["notification"]["recipient_ref"] == "fhd:user:42:tenant:8"
    finally:
        release.set()


def test_employee_message_internal_candidates_are_private_only(monkeypatch):
    from modstore_server.notification_service import (
        _fhd_internal_api_key,
        _fhd_internal_candidates,
    )

    monkeypatch.setenv("XCAGI_FHD_INTERNAL_URL", "https://xiu-ci.com")
    monkeypatch.setenv("FHD_INTERNAL_BASE_URL", "http://192.168.10.2:17500")
    monkeypatch.setenv("XCAGI_API_BASE_URL", "https://api.xiu-ci.com")
    monkeypatch.setenv("MODSTORE_DAILY_SURFACE_AUDIT_BASE_URL", "https://xiu-ci.com")
    candidates = _fhd_internal_candidates()
    assert "https://xiu-ci.com" not in candidates
    assert "https://api.xiu-ci.com" not in candidates
    assert "http://192.168.10.2:17500" in candidates
    assert "http://127.0.0.1:17500" in candidates

    monkeypatch.delenv("MODSTORE_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv("XCAGI_CS_INTAKE_LINK_SECRET", "unrelated-cs-secret")
    assert _fhd_internal_api_key() == ""


def test_internal_actor_ignores_cross_database_numeric_ids(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    from modstore_server.admin_management_work_api import _actor_user_id

    sf = models.get_session_factory()
    with sf() as session:
        session.query(models.User).delete()
        local_admin = models.User(
            username="local-owner",
            email="local-owner@example.test",
            password_hash="not-used",
            is_admin=True,
        )
        session.add(local_admin)
        session.commit()
        local_admin_id = int(local_admin.id)

    resolved = _actor_user_id(
        None,
        {
            "user_id": 2,
            "created_by_user_id": 3,
            "external_actor_ref": "fhd:user:2:tenant:8",
        },
    )
    assert resolved == local_admin_id


def test_management_source_ref_is_server_bound():
    from modstore_server.admin_management_work_api import _source_ref

    authenticated = types.SimpleNamespace(id=7)
    assert (
        _source_ref(authenticated, {"external_actor_ref": "fhd:user:999:tenant:4"})
        == "modstore:user:7"
    )
    assert (
        _source_ref(None, {"external_actor_ref": "fhd:user:42:tenant:8"}) == "fhd:user:42:tenant:8"
    )
    assert _source_ref(None, {}) == ""
    for invalid in (
        "fhd:user:0:tenant:8",
        "fhd:user:1:tenant:-1",
        "fhd:user:42",
        "fhd:user:42:tenant:8:extra",
        "user:42:tenant:8",
    ):
        with pytest.raises(ValueError, match="external actor"):
            _source_ref(None, {"external_actor_ref": invalid})


def test_management_internal_auth_ignores_cs_intake_secret(monkeypatch):
    from modstore_server.admin_employee_autonomy_api import (
        _internal_api_key as autonomy_internal_api_key,
    )
    from modstore_server.admin_management_work_api import (
        _internal_api_key as management_internal_api_key,
    )

    monkeypatch.delenv("MODSTORE_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)
    monkeypatch.setenv("XCAGI_CS_INTAKE_LINK_SECRET", "cs-only-secret")
    assert management_internal_api_key() == ""
    assert autonomy_internal_api_key() == ""


def test_internal_actor_fails_closed_without_local_admin(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    from fastapi import HTTPException

    from modstore_server.admin_management_work_api import _actor_user_id

    sf = models.get_session_factory()
    with sf() as session:
        session.query(models.User).delete()
        session.commit()

    with pytest.raises(HTTPException) as exc_info:
        _actor_user_id(None, {"user_id": 1, "external_actor_ref": "fhd:user:1"})
    assert exc_info.value.status_code == 503


def test_management_work_lifecycle_requires_delivery_acceptance(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        claim_work_item,
        create_work_item,
        deliver_work_item,
        get_work_item,
        heartbeat_work_item,
        request_decision,
        resolve_decision,
        review_delivery,
    )

    created = create_work_item(
        created_by_user_id=None,
        title="修复真实推送",
        description="打通员工到老板的消息",
        owner_employee_id="intent-analyst",
        acceptance_criteria=["消息落库", "桌面收到通知"],
        idempotency_key="test-push-1",
    )
    assert created["created"] is True
    task_id = created["item"]["task_id"]

    duplicate = create_work_item(
        created_by_user_id=None,
        title="不会重复创建",
        description="duplicate",
        owner_employee_id="intent-analyst",
        idempotency_key="test-push-1",
    )
    assert duplicate["created"] is False
    assert duplicate["item"]["task_id"] == task_id

    claimed = claim_work_item(task_id, employee_id="intent-analyst", lease_seconds=60)
    lease = claimed["lease_token"]
    progress = heartbeat_work_item(
        task_id,
        employee_id="intent-analyst",
        lease_token=lease,
        progress=40,
        stage="backend",
        message="后端链路已接通",
        evidence=[{"kind": "test", "value": "backend passed"}],
    )
    assert progress["status"] == "running"
    assert progress["progress"] == 40

    decision_out = request_decision(
        task_id,
        employee_id="intent-analyst",
        lease_token=lease,
        question="是否立即重启运行服务？",
        options=["立即重启", "稍后重启"],
        recommendation="立即重启",
    )
    assert decision_out["item"]["status"] == "waiting_decision"
    resolved = resolve_decision(
        decision_out["decision"]["decision_id"],
        decided_by_user_id=1,
        decision_text="立即重启",
    )
    assert resolved["item"]["status"] == "assigned"

    reclaimed = claim_work_item(task_id, employee_id="intent-analyst")
    with pytest.raises(ValueError, match="artifact, evidence"):
        deliver_work_item(
            task_id,
            employee_id="intent-analyst",
            lease_token=reclaimed["lease_token"],
            summary="完成",
        )
    receipt_id, result_digest = _passing_verification_receipt(task_id)
    delivered = deliver_work_item(
        task_id,
        employee_id="intent-analyst",
        lease_token=reclaimed["lease_token"],
        summary="推送链路已经完成",
        evidence=[{"kind": "pytest", "passed": True}],
        verification_receipt_id=receipt_id,
        candidate_result_digest=result_digest,
    )
    assert delivered["status"] == "delivered"
    assert delivered["completed_at"] is None

    accepted = review_delivery(task_id, reviewed_by_user_id=1, accepted=True)
    assert accepted["status"] == "accepted"
    assert accepted["completed_at"] is not None
    detail = get_work_item(task_id)
    assert detail is not None
    assert [event["event_type"] for event in detail["events"]] == [
        "task.created",
        "task.claimed",
        "task.progress",
        "decision.requested",
        "decision.resolved",
        "task.claimed",
        "task.verification_receipt",
        "task.delivered",
        "task.accepted",
    ]


def test_management_work_watchdog_recovers_expired_lease(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        claim_work_item,
        create_work_item,
        get_work_item,
        recover_stale_work_items,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="长任务",
        description="验证租约恢复",
        owner_employee_id="test-qa-runner",
        max_attempts=2,
    )["item"]
    claim_work_item(item["task_id"], employee_id="test-qa-runner")
    sf = models.get_session_factory()
    with sf() as session:
        row = (
            session.query(models.ManagementWorkItem)
            .filter(models.ManagementWorkItem.task_id == item["task_id"])
            .one()
        )
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    first = recover_stale_work_items()
    assert first["recovered"] == 1
    assert get_work_item(item["task_id"])["status"] == "retrying"

    with sf() as session:
        row = (
            session.query(models.ManagementWorkItem)
            .filter(models.ManagementWorkItem.task_id == item["task_id"])
            .one()
        )
        row.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    second = recover_stale_work_items()
    assert second["recovered"] == 1
    assert get_work_item(item["task_id"])["status"] == "assigned"


def test_expired_lease_rejects_late_worker_transitions_before_watchdog(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        WorkItemConflict,
        claim_work_item,
        create_work_item,
        deliver_work_item,
        fail_work_item,
        get_work_item,
        heartbeat_work_item,
        request_decision,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="过期租约禁止晚到写入",
        description="看门狗运行前，过期 worker 也不能续租或交付",
        owner_employee_id="intent-analyst",
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    sf = models.get_session_factory()
    with sf() as session:
        row = session.query(models.ManagementWorkItem).one()
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    late_writes = (
        lambda: heartbeat_work_item(
            item["task_id"],
            employee_id="intent-analyst",
            lease_token=claimed["lease_token"],
        ),
        lambda: request_decision(
            item["task_id"],
            employee_id="intent-analyst",
            lease_token=claimed["lease_token"],
            question="是否继续？",
        ),
        lambda: deliver_work_item(
            item["task_id"],
            employee_id="intent-analyst",
            lease_token=claimed["lease_token"],
            summary="晚到交付",
            evidence=[{"kind": "late"}],
        ),
        lambda: fail_work_item(
            item["task_id"],
            employee_id="intent-analyst",
            lease_token=claimed["lease_token"],
            error_kind="late",
            error="晚到失败",
        ),
    )
    for late_write in late_writes:
        with pytest.raises(WorkItemConflict, match="lease has expired"):
            late_write()

    current = get_work_item(item["task_id"])
    assert current["status"] == "running"
    assert current["progress"] == 0
    assert current["decisions"] == []


def test_management_work_retry_not_due_and_single_claim(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        WorkItemConflict,
        claim_work_item,
        create_work_item,
        fail_work_item,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="并发领取",
        description="只能有一个租约",
        owner_employee_id="test-qa-runner",
    )["item"]

    def _claim():
        try:
            return claim_work_item(item["task_id"], employee_id="test-qa-runner")
        except WorkItemConflict as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _claim(), range(2)))
    assert sum(isinstance(result, dict) for result in results) == 1
    lease = next(result["lease_token"] for result in results if isinstance(result, dict))

    failed = fail_work_item(
        item["task_id"],
        employee_id="test-qa-runner",
        lease_token=lease,
        error_kind="transient",
        error="temporary outage",
        retryable=True,
    )
    assert failed["status"] == "retrying"
    with pytest.raises(WorkItemConflict, match="not claimable|retry"):
        claim_work_item(item["task_id"], employee_id="test-qa-runner")


def test_rejection_respects_attempt_cap_and_human_retry_grants_one_attempt(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        claim_work_item,
        create_work_item,
        deliver_work_item,
        retry_work_item,
        review_delivery,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="验收退回上限",
        description="达到上限后必须等老板明确重试",
        owner_employee_id="test-qa-runner",
        max_attempts=1,
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="test-qa-runner")
    receipt_id, result_digest = _passing_verification_receipt(item["task_id"])
    delivered = deliver_work_item(
        item["task_id"],
        employee_id="test-qa-runner",
        lease_token=claimed["lease_token"],
        summary="交付内容不完整",
        evidence=[{"kind": "pytest", "passed": True}],
        verification_receipt_id=receipt_id,
        candidate_result_digest=result_digest,
    )
    assert delivered["attempt_count"] == delivered["max_attempts"] == 1

    rejected = review_delivery(
        item["task_id"],
        reviewed_by_user_id=9,
        accepted=False,
        feedback="缺少验收标准",
    )
    assert rejected["status"] == "blocked"
    assert rejected["error_kind"] == "acceptance_rejected"

    retried = retry_work_item(item["task_id"], requested_by_user_id=9, note="补齐验收标准后再执行")
    assert retried["status"] == "assigned"
    assert retried["attempt_count"] == 1
    assert retried["max_attempts"] == 2
    assert retried["error_kind"] == ""
    assert retried["error"] == ""
    reclaimed = claim_work_item(item["task_id"], employee_id="test-qa-runner")
    assert reclaimed["attempt_count"] == 2


def test_management_work_watchdog_blocks_without_detached_notification(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        claim_work_item,
        create_work_item,
        get_work_item,
        recover_stale_work_items,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="不可恢复任务",
        description="重试耗尽后必须阻塞",
        owner_employee_id="test-qa-runner",
        max_attempts=1,
    )["item"]
    claim_work_item(item["task_id"], employee_id="test-qa-runner")
    sf = models.get_session_factory()
    with sf() as session:
        row = session.query(models.ManagementWorkItem).filter_by(task_id=item["task_id"]).one()
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    out = recover_stale_work_items()
    assert out["blocked"] == 1
    assert get_work_item(item["task_id"])["status"] == "blocked"


def test_management_work_watchdog_reminds_pending_decision(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        claim_work_item,
        create_work_item,
        get_work_item,
        recover_stale_work_items,
        request_decision,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="等老板决策",
        description="决策未超时前员工应主动提醒",
        owner_employee_id="test-qa-runner",
    )["item"]
    claim = claim_work_item(item["task_id"], employee_id="test-qa-runner")
    requested = request_decision(
        item["task_id"],
        employee_id="test-qa-runner",
        lease_token=claim["lease_token"],
        question="采用 A 还是 B？",
        due_seconds=3600,
    )
    sf = models.get_session_factory()
    with sf() as session:
        decision = (
            session.query(models.ManagementDecision)
            .filter_by(decision_id=requested["decision"]["decision_id"])
            .one()
        )
        decision.last_reminded_at = datetime.now(timezone.utc) - timedelta(hours=2)
        session.commit()

    watchdog = recover_stale_work_items()
    assert watchdog["decision_reminders"] == 1
    detail = get_work_item(item["task_id"])
    assert detail["decisions"][0]["reminder_count"] == 2
    assert detail["events"][-1]["event_type"] == "decision.reminded"


def test_management_worker_executes_and_waits_for_acceptance(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        claim_work_item,
        create_work_item,
        dispatch_assigned_work_items,
        get_work_item,
        request_decision,
        resolve_decision,
    )
    import modstore_server.employee_orchestrator as orchestrator

    calls = []

    def _run(task, input_data, **kwargs):
        calls.append((task, input_data, kwargs))
        if kwargs["target_employee_id"] == "delivery-receipt-officer":
            criteria = input_data["management_acceptance_audit"]["criteria"]
            return _acceptance_audit_graph(criteria)
        return {
            "ok": True,
            "status": "completed",
            "accepted_completion": True,
            "summary": "真实员工执行完成",
            "nodes": [{"employee_id": kwargs["target_employee_id"], "status": "success"}],
        }

    monkeypatch.setattr(orchestrator, "plan_and_dispatch", _run)
    item = create_work_item(
        created_by_user_id=None,
        title="执行纵向切片",
        description="运行真实管理端员工",
        owner_employee_id="intent-analyst",
        input_data={"scope": "backend"},
    )["item"]
    assert item["employee_partition"] == "management_duty"
    first_claim = claim_work_item(item["task_id"], employee_id="intent-analyst")
    question = request_decision(
        item["task_id"],
        employee_id="intent-analyst",
        lease_token=first_claim["lease_token"],
        question="是否继续执行？",
        options=["继续", "停止"],
    )
    resolve_decision(
        question["decision"]["decision_id"],
        decided_by_user_id=1,
        decision_text="继续",
    )
    out = dispatch_assigned_work_items(limit=1, lease_seconds=60)
    assert out["processed"] == 1
    assert out["delivered"] == 1
    assert calls and calls[0][2]["target_employee_id"] == "intent-analyst"
    assert calls[0][2]["include_dependencies"] is False
    assert calls[1][2]["target_employee_id"] == "delivery-receipt-officer"
    assert calls[1][2]["include_dependencies"] is False
    assert calls[1][2]["max_concurrency"] == 1
    context = calls[0][1]["management_work"]
    assert context["task_id"] == item["task_id"]
    assert context["employee_partition"] == "management_duty"
    assert context["resolved_decisions"][0]["decision"] == "继续"
    assert calls[0][1]["task"] == "运行真实管理端员工"
    assert calls[0][1]["user_request"] == "运行真实管理端员工"
    detail = get_work_item(item["task_id"])
    assert detail["status"] == "delivered"
    assert detail["completed_at"] is None
    assert [row["kind"] for row in detail["evidence"]] == [
        "employee_runtime_result",
        "acceptance_audit",
        "independent_fact_snapshot",
        "verification_receipt",
    ]
    assert detail["evidence"][1]["outcome"] == "pass"


def test_acceptance_audit_validator_is_fail_closed() -> None:
    from modstore_server.management_work_service import _validate_acceptance_audit

    criteria = ["接口返回 200", "桌面和手机显示同一 task_id"]
    report = {
        "status": "success",
        "verdict": "PASS",
        "summary": "两条验收标准均已找到可核验证据",
        "criteria": [
            {
                "criterion_id": "criterion_1",
                "criterion": criteria[0],
                "status": "pass",
                "evidence_refs": ["evidence_1"],
            },
            {
                "criterion_id": "criterion_2",
                "criterion": criteria[1],
                "status": "pass",
                "evidence_refs": ["evidence_1"],
            },
        ],
    }
    assert (
        _validate_acceptance_audit(report, criteria=criteria, evidence_ids={"evidence_1"})[0]
        == "pass"
    )

    missing = dict(report, criteria=report["criteria"][:1])
    outcome, reason = _validate_acceptance_audit(
        missing, criteria=criteria, evidence_ids={"evidence_1"}
    )
    assert outcome == "invalid"
    assert "every criterion" in reason

    unknown_ref = json.loads(json.dumps(report, ensure_ascii=False))
    unknown_ref["criteria"][0]["evidence_refs"] = ["evidence_404"]
    outcome, reason = _validate_acceptance_audit(
        unknown_ref, criteria=criteria, evidence_ids={"evidence_1"}
    )
    assert outcome == "invalid"
    assert "unknown evidence" in reason


def test_incomplete_independent_acceptance_blocks_delivery(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        create_work_item,
        dispatch_assigned_work_items,
        get_work_item,
    )
    import modstore_server.employee_orchestrator as orchestrator

    calls = []

    def _run(_task, input_data, **kwargs):
        calls.append((input_data, kwargs))
        if kwargs["target_employee_id"] == "delivery-receipt-officer":
            criteria = input_data["management_acceptance_audit"]["criteria"]
            return _acceptance_audit_graph(criteria[:1])
        return {
            "ok": True,
            "status": "completed",
            "accepted_completion": True,
            "summary": "原执行员工已产出结果",
            "nodes": [{"employee_id": "intent-analyst", "status": "success"}],
        }

    monkeypatch.setattr(orchestrator, "plan_and_dispatch", _run)
    item = create_work_item(
        created_by_user_id=None,
        title="独立验收缺项",
        description="验收员漏一条时不能交付",
        owner_employee_id="intent-analyst",
        acceptance_criteria=["输出目标", "输出成功标准"],
        max_attempts=1,
    )["item"]

    outcome = dispatch_assigned_work_items(limit=1, lease_seconds=60)
    assert outcome["blocked"] == 1
    detail = get_work_item(item["task_id"])
    assert detail is not None
    assert detail["status"] == "blocked"
    assert detail["error_kind"] == "acceptance_verifier_invalid"
    assert not any(event["event_type"] == "task.delivered" for event in detail["events"])
    audit = next(
        row for row in reversed(detail["evidence"]) if row.get("kind") == "acceptance_audit"
    )
    assert audit["kind"] == "acceptance_audit"
    assert audit["outcome"] == "invalid"
    assert calls[1][1]["include_dependencies"] is False


def test_management_worker_persists_rejected_runtime_evidence(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        create_work_item,
        dispatch_assigned_work_items,
        get_work_item,
    )
    import modstore_server.employee_orchestrator as orchestrator

    rejected_runtime = {
        "ok": False,
        "status": "blocked",
        "accepted_completion": False,
        "error": "acceptance checklist failed",
        "nodes": [
            {
                "employee_id": "intent-analyst",
                "status": "failed",
                "result": {
                    "outputs": [
                        {
                            "handler": "llm_md",
                            "output": {
                                "status": "blocked",
                                "acceptance_checklist": [
                                    {
                                        "criterion": "输出成功标准",
                                        "status": "fail",
                                        "evidence": "缺少可验证细节",
                                    }
                                ],
                            },
                        }
                    ]
                },
            }
        ],
    }
    monkeypatch.setattr(
        orchestrator, "plan_and_dispatch", lambda *_args, **_kwargs: rejected_runtime
    )
    item = create_work_item(
        created_by_user_id=None,
        title="保留失败证据",
        description="员工不达标时必须可诊断",
        owner_employee_id="intent-analyst",
        max_attempts=1,
    )["item"]

    outcome = dispatch_assigned_work_items(limit=1, lease_seconds=60)
    assert outcome["blocked"] == 1
    detail = get_work_item(item["task_id"])
    assert detail is not None
    assert detail["status"] == "blocked"
    failure = detail["evidence"][-1]
    assert failure["kind"] == "employee_runtime_failure"
    assert failure["reason"] == "acceptance checklist failed"
    assert failure["value"]["nodes"][0]["status"] == "failed"


def test_management_work_http_contract(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    sf = models.get_session_factory()
    with sf() as session:
        session.add(
            models.User(
                username="admin",
                email="admin@local",
                password_hash="not-used",
                is_admin=True,
            )
        )
        session.commit()
    monkeypatch.setenv("MODSTORE_INTERNAL_API_KEY", "test-internal-key")
    monkeypatch.setenv("XCAGI_MARKET_INTERNAL_API_KEY", "secondary-key")
    app = create_app(load_default_config())
    admin = types.SimpleNamespace(id=7, username="admin", is_admin=True, email="admin@local")
    app.dependency_overrides[get_current_user] = lambda: admin
    client = TestClient(app, headers={"X-Internal-Api-Key": "test-internal-key"})
    try:
        response = client.post(
            "/api/admin/employee-autonomy/work-items",
            json={
                "title": "桌面发起任务",
                "description": "必须进入持久任务台账",
                "owner_employee_id": "intent-analyst",
                "idempotency_key": "desktop-1",
                "external_actor_ref": "fhd:user:2:tenant:8",
            },
        )
        assert response.status_code == 200, response.text
        task_id = response.json()["item"]["task_id"]
        claim = client.post(
            f"/api/admin/employee-autonomy/work-items/{task_id}/claim",
            json={"employee_id": "intent-analyst"},
            headers={"X-Internal-Api-Key": "test-internal-key"},
        )
        assert claim.status_code == 200, claim.text
        detail = client.get(f"/api/admin/employee-autonomy/work-items/{task_id}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "running"
        assert detail.json()["source_ref"] == "fhd:user:2:tenant:8"
        bypass = client.post(
            f"/api/admin/employee-autonomy/work-items/{task_id}/deliver",
            json={
                "employee_id": "intent-analyst",
                "lease_token": claim.json()["lease_token"],
                "summary": "伪造交付",
                "evidence": [{"kind": "employee_claim", "value": "自报完成"}],
            },
            headers={"X-Internal-Api-Key": "test-internal-key"},
        )
        assert bypass.status_code == 409
        assert "verification receipt" in bypass.text
        listing = client.get("/api/admin/employee-autonomy/work-items")
        assert listing.status_code == 200
        assert listing.json()["count"] == 1
        roster = client.get("/api/admin/employee-autonomy/work-items/employees")
        assert roster.status_code == 200
        assert roster.json()["employee_partition"] == "management_duty"
        assert any(
            row["employee_id"] == "task-router-officer" for row in roster.json()["employees"]
        )
        roster_by_id = {row["employee_id"]: row for row in roster.json()["employees"]}
        assert roster_by_id["intent-analyst"]["primary_assignable"] is True
        assert roster_by_id["task-router-officer"]["primary_assignable"] is False
        invalid = client.post(
            "/api/admin/employee-autonomy/work-items",
            json={
                "title": "错误分区",
                "description": "企业商店员工不能混进管理队列",
                "owner_employee_id": "store-customer-service-employee",
            },
        )
        assert invalid.status_code == 400
        assert "不是管理端在岗员工" in invalid.text
        unavailable = client.post(
            "/api/admin/employee-autonomy/work-items",
            json={
                "title": "不可执行岗位",
                "description": "后端必须和前端一样拒绝灰置岗位",
                "owner_employee_id": "fhd-core-maintainer",
            },
        )
        assert unavailable.status_code == 400
        assert "当前不可执行" in unavailable.text
        reserved = client.post(
            "/api/admin/employee-autonomy/work-items",
            json={
                "title": "系统保留岗位",
                "description": "验收员不能被直接派成执行负责人",
                "owner_employee_id": "delivery-receipt-officer",
            },
        )
        assert reserved.status_code == 400
        assert "不能作为主任务负责人" in reserved.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_management_auto_route_is_management_only_and_idempotent(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    import modstore_server.task_router as router
    from modstore_server.management_work_service import create_work_item, get_work_item

    calls = []

    def _route(task_description, input_data):
        calls.append((task_description, input_data))
        return {
            "employee_id": "intent-analyst",
            "strategy": "llm",
            "reason": "手机与桌面共享台账属于 FHD 核心",
            "candidates": ["intent-analyst", "daily-orchestrator"],
            "fallback_reason": "",
        }

    monkeypatch.setattr(router, "resolve_management_work_owner", _route)
    created = create_work_item(
        created_by_user_id=7,
        title="自动选人",
        description="修复手机与桌面管理任务同步",
        owner_employee_id="auto",
        idempotency_key="auto-route-once",
    )
    repeated = create_work_item(
        created_by_user_id=7,
        title="重复请求",
        description="不得再次调用路由器",
        owner_employee_id="auto",
        idempotency_key="auto-route-once",
    )

    assert created["item"]["owner_employee_id"] == "intent-analyst"
    assert repeated["created"] is False
    assert len(calls) == 1
    detail = get_work_item(created["item"]["task_id"])
    assert [event["event_type"] for event in detail["events"]][:2] == [
        "task.created",
        "task.routed",
    ]
    assert detail["events"][1]["payload"]["strategy"] == "llm"


def test_management_router_rejects_non_management_llm_output(monkeypatch):
    import modstore_server.task_router as router

    monkeypatch.setattr(
        router,
        "_call_llm",
        lambda *_args, **_kwargs: json.dumps(
            [{"employee_id": "store-customer-service-employee", "reason": "invalid"}]
        ),
    )
    decision = router.resolve_management_work_owner("检查今日运营情况")
    assert decision["employee_id"] == "intent-analyst"
    assert decision["strategy"] == "fallback"
    assert "store-customer-service-employee" not in decision["candidates"]
    assert "non-management employee" in decision["fallback_reason"]


def test_cancel_and_reassign_preserve_truthful_lifecycle(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        WorkItemConflict,
        cancel_work_item,
        claim_work_item,
        create_work_item,
        deliver_work_item,
        fail_work_item,
        finalize_requested_cancellation,
        get_work_item,
        heartbeat_work_item,
        reassign_work_item,
        request_decision,
    )

    assigned = create_work_item(
        created_by_user_id=None,
        title="取消待领取任务",
        description="应立即取消",
        owner_employee_id="test-qa-runner",
    )["item"]
    cancelled = cancel_work_item(assigned["task_id"], requested_by_user_id=7, reason="方向变更")
    assert cancelled["status"] == "cancelled"
    assert cancel_work_item(assigned["task_id"], requested_by_user_id=7)["status"] == "cancelled"
    with pytest.raises(WorkItemConflict):
        claim_work_item(assigned["task_id"], employee_id="test-qa-runner")

    running = create_work_item(
        created_by_user_id=None,
        title="取消执行中任务",
        description="当前步骤返回后停止",
        owner_employee_id="intent-analyst",
    )["item"]
    claim = claim_work_item(running["task_id"], employee_id="intent-analyst")
    requested = cancel_work_item(
        running["task_id"], requested_by_user_id=7, reason="立即停止后续步骤"
    )
    assert requested["status"] == "cancel_requested"
    for late_write in (
        lambda: heartbeat_work_item(
            running["task_id"],
            employee_id="intent-analyst",
            lease_token=claim["lease_token"],
        ),
        lambda: deliver_work_item(
            running["task_id"],
            employee_id="intent-analyst",
            lease_token=claim["lease_token"],
            summary="晚到交付",
            evidence=[{"kind": "late"}],
        ),
        lambda: fail_work_item(
            running["task_id"],
            employee_id="intent-analyst",
            lease_token=claim["lease_token"],
            error_kind="late",
            error="晚到失败",
        ),
    ):
        with pytest.raises(WorkItemConflict):
            late_write()
    final = finalize_requested_cancellation(
        running["task_id"],
        employee_id="intent-analyst",
        lease_token=claim["lease_token"],
    )
    assert final["status"] == "cancelled"
    assert get_work_item(running["task_id"])["events"][-1]["event_type"] == "task.cancelled"

    waiting = create_work_item(
        created_by_user_id=None,
        title="改派等待决策任务",
        description="原决策必须作废",
        owner_employee_id="test-qa-runner",
        max_attempts=1,
    )["item"]
    waiting_claim = claim_work_item(waiting["task_id"], employee_id="test-qa-runner")
    request_decision(
        waiting["task_id"],
        employee_id="test-qa-runner",
        lease_token=waiting_claim["lease_token"],
        question="是否继续？",
    )
    reassigned = reassign_work_item(
        waiting["task_id"],
        new_employee_id="intent-analyst",
        requested_by_user_id=7,
        reason="改由 FHD 负责人处理",
    )
    assert reassigned["status"] == "assigned"
    assert reassigned["owner_employee_id"] == "intent-analyst"
    detail = get_work_item(waiting["task_id"])
    assert detail["decisions"][0]["status"] == "superseded"
    assert detail["events"][-1]["event_type"] == "task.reassigned"


def test_dispatch_late_success_cannot_override_cancel(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        cancel_work_item,
        create_work_item,
        dispatch_assigned_work_items,
        get_work_item,
    )
    import modstore_server.employee_orchestrator as orchestrator

    item = create_work_item(
        created_by_user_id=None,
        title="晚到成功隔离",
        description="员工返回前老板停止",
        owner_employee_id="intent-analyst",
    )["item"]
    calls = []

    def _run(*_args, **kwargs):
        calls.append(kwargs["target_employee_id"])
        cancel_work_item(item["task_id"], requested_by_user_id=7, reason="中途停止")
        return {
            "ok": True,
            "status": "completed",
            "accepted_completion": True,
            "summary": "这是一个晚到成功",
        }

    monkeypatch.setattr(orchestrator, "plan_and_dispatch", _run)
    outcome = dispatch_assigned_work_items(limit=1, lease_seconds=60)
    assert outcome["cancelled"] == 1
    assert outcome["delivered"] == 0
    assert calls == ["intent-analyst"]
    detail = get_work_item(item["task_id"])
    assert detail["status"] == "cancelled"
    assert not any(event["event_type"] == "task.delivered" for event in detail["events"])


def test_claim_and_reassign_cas_have_one_winner(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        WorkItemConflict,
        claim_work_item,
        create_work_item,
        get_work_item,
        reassign_work_item,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="并发改派",
        description="领取和改派只能一个成功",
        owner_employee_id="test-qa-runner",
    )["item"]
    gate = threading.Barrier(2)

    def _claim():
        gate.wait()
        try:
            claim_work_item(item["task_id"], employee_id="test-qa-runner")
            return "claim"
        except WorkItemConflict:
            return "claim_conflict"

    def _reassign():
        gate.wait()
        try:
            reassign_work_item(
                item["task_id"],
                new_employee_id="intent-analyst",
                requested_by_user_id=7,
            )
            return "reassign"
        except WorkItemConflict:
            return "reassign_conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_claim), pool.submit(_reassign)]
        results = [future.result() for future in futures]

    assert sum(value in {"claim", "reassign"} for value in results) == 1
    detail = get_work_item(item["task_id"])
    if "claim" in results:
        assert detail["status"] == "running"
        assert detail["owner_employee_id"] == "test-qa-runner"
    else:
        assert detail["status"] == "assigned"
        assert detail["owner_employee_id"] == "intent-analyst"


@pytest.mark.parametrize(
    ("cancel_requested", "expected_error"),
    [
        (False, "ManagementExecutionTimeout"),
        (True, "ManagementExecutionCancelled"),
    ],
)
def test_management_execution_process_is_killable(monkeypatch, cancel_requested, expected_error):
    import modstore_server.management_work_service as service

    real_popen = service.subprocess.Popen
    children = []

    def _sleeping_process(_command, **kwargs):
        process = real_popen(
            [service.sys.executable, "-c", "import time; time.sleep(60)"],
            **kwargs,
        )
        children.append(process)
        return process

    monkeypatch.setattr(service.subprocess, "Popen", _sleeping_process)
    monkeypatch.setattr(service, "_task_has_cancel_request", lambda _task_id: cancel_requested)
    monkeypatch.setattr(service, "_management_execution_timeout_seconds", lambda _employee: 1)
    error_type = getattr(service, expected_error)
    started = time.monotonic()
    with pytest.raises(error_type):
        service._run_management_execution_process(
            "永远不返回的任务",
            {},
            task_id="mwi_killable_test",
            target_employee_id="intent-analyst",
            created_by_user_id=7,
            include_dependencies=False,
            max_concurrency=1,
            allow_high_risk_real_run=False,
        )
    assert time.monotonic() - started < 5
    assert children and children[0].poll() is not None


def test_management_execution_process_uses_memory_pipes(monkeypatch):
    import modstore_server.management_work_service as service

    real_popen = service.subprocess.Popen

    def _echo_process(_command, **kwargs):
        code = (
            "import json,sys;"
            "request=json.load(sys.stdin);"
            "json.dump({'ok':True,'result':{'task':request['task']}},sys.stdout)"
        )
        return real_popen([service.sys.executable, "-c", code], **kwargs)

    monkeypatch.setattr(service.subprocess, "Popen", _echo_process)
    monkeypatch.setattr(service, "_task_has_cancel_request", lambda _task_id: False)
    result = service._run_management_execution_process(
        "pipe-only task",
        {"private": "not-written-to-disk"},
        task_id="mwi_pipe_test",
        target_employee_id="intent-analyst",
        created_by_user_id=7,
        include_dependencies=False,
        max_concurrency=1,
        allow_high_risk_real_run=False,
    )

    assert result == {"task": "pipe-only task"}


def test_management_worker_returns_stable_error_without_traceback():
    import os
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "modstore_server.management_work_process"],
        input=b"not-json",
        capture_output=True,
        env=os.environ.copy(),
        check=False,
        timeout=10,
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout) == {
        "ok": False,
        "error_code": "management_worker_failed",
    }
    assert b"Traceback" not in completed.stdout
    assert b"Traceback" not in completed.stderr
