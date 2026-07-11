from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest


def _reset_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "management-facts.sqlite"))
    monkeypatch.setenv("MODSTORE_MANAGEMENT_WORK_EXECUTION_MODE", "in_process")
    monkeypatch.setenv(
        "MODSTORE_MANAGEMENT_EVIDENCE_HMAC_KEY",
        "test-management-evidence-signing-key-32-bytes",
    )
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    models.init_db()
    return models


def _audit_runtime(
    criteria: list[dict],
    *,
    fact_required: bool,
    fact_refs: list[str] | None = None,
) -> dict:
    refs = ["evidence_1", *(fact_refs or [])] if fact_required else ["evidence_1"]
    report = {
        "status": "success",
        "verdict": "PASS",
        "criteria": [
            {
                "criterion_id": row["criterion_id"],
                "criterion": row["criterion"],
                "status": "pass",
                "evidence_refs": refs,
                "reason": "已核对独立事实快照",
            }
            for row in criteria
        ],
        "summary": "独立事实与员工语义交付均已逐条核对通过",
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


def _delivered_work_with_signed_file_fact(tmp_path, monkeypatch) -> str:
    _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "authoritative-fact-workspace"
    workspace.mkdir()
    (workspace / "result.txt").write_text("authoritative result", encoding="utf-8")
    monkeypatch.setenv("MODSTORE_MANAGEMENT_EVIDENCE_ROOTS", str(workspace))
    from modstore_server.management_work_evidence import (
        collect_independent_fact_snapshot,
        persist_fact_snapshot,
    )
    from modstore_server.management_work_service import (
        _record_verification_receipt,
        claim_work_item,
        create_work_item,
        deliver_work_item,
    )

    policy = {"evidence_policy": {"required": True, "operation_required": False}}
    item = create_work_item(
        created_by_user_id=None,
        title="验收权威事实",
        description="读取并核验现有结果文件",
        owner_employee_id="intent-analyst",
        input_data=policy,
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    runtime_result = {
        "ok": True,
        "status": "completed",
        "summary": "已读取并核验现有结果文件",
        "management_evidence_claims": [
            {
                "kind": "file",
                "workspace_root": str(workspace),
                "path": "result.txt",
                "expected": {"exists": True, "text_contains": ["authoritative"]},
            }
        ],
    }
    snapshot = collect_independent_fact_snapshot(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_text=item["description"],
        task_input=policy,
        runtime_result=runtime_result,
    )
    assert snapshot["outcome"] == "pass"
    persist_fact_snapshot(
        task_id=item["task_id"],
        attempt=int(claimed["attempt_count"]),
        snapshot=snapshot,
    )
    receipt = _record_verification_receipt(
        task_id=item["task_id"],
        result_digest=str(snapshot["runtime_claim_sha256"]),
        fact_snapshot=snapshot,
        audit={"outcome": "pass", "reason": "pytest verified", "report": {}},
    )
    delivered = deliver_work_item(
        item["task_id"],
        employee_id="intent-analyst",
        lease_token=str(claimed["lease_token"]),
        summary="权威事实已交付",
        evidence=[{"kind": "pytest_authoritative_fact"}],
        verification_receipt_id=str(receipt["receipt_id"]),
        candidate_result_digest=str(snapshot["runtime_claim_sha256"]),
    )
    assert delivered["status"] == "delivered"
    return str(item["task_id"])


def test_signed_file_fact_is_collected_outside_employee_process(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifact = workspace / "result.md"
    artifact.write_text("真实结果：PASS\n", encoding="utf-8")
    monkeypatch.setenv("MODSTORE_MANAGEMENT_EVIDENCE_ROOTS", str(workspace))

    from modstore_server.management_work_evidence import (
        collect_independent_fact_snapshot,
        persist_fact_snapshot,
        verify_snapshot_signature,
    )
    from modstore_server.management_work_service import claim_work_item, create_work_item

    item = create_work_item(
        created_by_user_id=None,
        title="实现真实文件结果",
        description="写入并核验结果文件",
        owner_employee_id="intent-analyst",
        input_data={"evidence_policy": {"required": True, "operation_required": False}},
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    runtime = {
        "ok": True,
        "management_evidence_claims": [
            {
                "kind": "file",
                "workspace_root": str(workspace),
                "path": "result.md",
                "expected": {"exists": True, "text_contains": ["真实结果"]},
            }
        ],
    }
    snapshot = collect_independent_fact_snapshot(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_text="核验结果文件",
        task_input={"evidence_policy": {"required": True, "operation_required": False}},
        runtime_result=runtime,
    )
    assert snapshot["outcome"] == "pass"
    assert snapshot["strong_verified_count"] == 1
    assert snapshot["facts"][0]["sha256"]
    assert "真实结果" in snapshot["facts"][0]["text_preview"]
    assert verify_snapshot_signature(snapshot) is True
    rows = persist_fact_snapshot(
        task_id=item["task_id"],
        attempt=int(claimed["attempt_count"]),
        snapshot=snapshot,
    )
    assert len(rows) == 1
    assert rows[0]["trust_level"] == "independent_observation"
    assert rows[0]["status"] == "pass"
    tampered = {**snapshot, "outcome": "fail"}
    assert verify_snapshot_signature(tampered) is False


def test_task_input_evidence_claim_is_not_treated_as_employee_output(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "already-there.txt").write_text("old", encoding="utf-8")
    monkeypatch.setenv("MODSTORE_MANAGEMENT_EVIDENCE_ROOTS", str(workspace))
    from modstore_server.management_work_evidence import (
        collect_independent_fact_snapshot,
    )

    snapshot = collect_independent_fact_snapshot(
        task_id="mwi_input_echo",
        employee_id="intent-analyst",
        task_text="修复并发布结果",
        task_input={"external_side_effects": True},
        runtime_result={
            "ok": True,
            "input": {
                "management_evidence_claims": [
                    {
                        "kind": "file",
                        "workspace_root": str(workspace),
                        "path": "already-there.txt",
                        "expected": {"exists": True},
                    }
                ]
            },
            "summary": "已完成",
        },
    )
    assert snapshot["claim_count"] == 0
    assert snapshot["outcome"] == "inconclusive"


@pytest.mark.parametrize("claim_key", ["management_evidence_claims", "evidence_claims"])
def test_json_string_evidence_claim_is_not_treated_as_typed_output(
    tmp_path, monkeypatch, claim_key
):
    _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "already-there.txt").write_text("old", encoding="utf-8")
    monkeypatch.setenv("MODSTORE_MANAGEMENT_EVIDENCE_ROOTS", str(workspace))
    from modstore_server.management_work_evidence import (
        collect_independent_fact_snapshot,
    )

    snapshot = collect_independent_fact_snapshot(
        task_id="mwi_json_string_claim",
        employee_id="intent-analyst",
        task_text="修复并发布结果",
        task_input={"external_side_effects": True},
        runtime_result={
            "ok": True,
            "output": json.dumps(
                {
                    claim_key: [
                        {
                            "kind": "file",
                            "workspace_root": str(workspace),
                            "path": "already-there.txt",
                            "expected": {"exists": True},
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        },
    )
    assert snapshot["claim_count"] == 0
    assert snapshot["facts"] == []
    assert snapshot["strong_verified_count"] == 0
    assert snapshot["outcome"] == "inconclusive"


def test_action_claim_without_independent_fact_is_fail_closed(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_evidence import (
        collect_independent_fact_snapshot,
    )

    snapshot = collect_independent_fact_snapshot(
        task_id="mwi_fake_linux_claim",
        employee_id="intent-analyst",
        task_text="修复并部署服务",
        task_input={"external_side_effects": True},
        runtime_result={
            "ok": True,
            "summary": "PID 12345，/lib/systemd/libsystemd.so.0 已验证，部署成功",
        },
    )
    assert snapshot["required"] is True
    assert snapshot["outcome"] == "inconclusive"
    assert snapshot["strong_verified_count"] == 0


def test_task_input_cannot_waive_mutating_evidence_gate(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_evidence import (
        collect_independent_fact_snapshot,
    )

    snapshot = collect_independent_fact_snapshot(
        task_id="mwi_false_waiver",
        employee_id="intent-analyst",
        task_text="修复并部署生产服务",
        task_input={
            "external_side_effects": False,
            "evidence_policy": {
                "required": False,
                "operation_required": False,
            },
        },
        runtime_result={"ok": True, "summary": "已完成"},
    )
    assert snapshot["required"] is True
    assert snapshot["operation_required"] is True
    assert snapshot["outcome"] == "inconclusive"


def test_sensitive_file_claim_is_rejected(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text("API_KEY=must-not-leak", encoding="utf-8")
    monkeypatch.setenv("MODSTORE_MANAGEMENT_EVIDENCE_ROOTS", str(workspace))
    from modstore_server.management_work_evidence import (
        collect_independent_fact_snapshot,
    )

    snapshot = collect_independent_fact_snapshot(
        task_id="mwi_sensitive",
        employee_id="intent-analyst",
        task_text="更新配置",
        task_input={"external_side_effects": True},
        runtime_result={
            "management_evidence_claims": [
                {
                    "kind": "file",
                    "workspace_root": str(workspace),
                    "path": ".env",
                    "expected": {"exists": True},
                }
            ]
        },
    )
    assert snapshot["outcome"] == "fail"
    assert "sensitive" in snapshot["facts"][0]["error"]
    assert "must-not-leak" not in json.dumps(snapshot, ensure_ascii=False)


def test_fact_required_audit_cannot_pass_on_employee_claim_only():
    from modstore_server.management_work_service import _validate_acceptance_audit

    report = {
        "status": "success",
        "verdict": "PASS",
        "criteria": [
            {
                "criterion_id": "criterion_1",
                "criterion": "真实服务已部署",
                "status": "pass",
                "evidence_refs": ["evidence_1"],
                "reason": "员工说已完成",
            }
        ],
        "summary": "员工自报内容看起来已经完成部署",
    }
    outcome, reason = _validate_acceptance_audit(
        report,
        criteria=["真实服务已部署"],
        evidence_ids={"evidence_1", "fact_file", "fact_operation"},
        required_fact_evidence_ids={"fact_file"},
        required_operation_evidence_ids={"fact_operation"},
    )
    assert outcome == "invalid"
    assert "independent fact" in reason
    report["criteria"][0]["evidence_refs"].append("fact_file")
    assert (
        _validate_acceptance_audit(
            report,
            criteria=["真实服务已部署"],
            evidence_ids={"evidence_1", "fact_file", "fact_operation"},
            required_fact_evidence_ids={"fact_file"},
            required_operation_evidence_ids={"fact_operation"},
        )[0]
        == "invalid"
    )
    report["criteria"][0]["evidence_refs"].append("fact_operation")
    assert (
        _validate_acceptance_audit(
            report,
            criteria=["真实服务已部署"],
            evidence_ids={"evidence_1", "fact_file", "fact_operation"},
            required_fact_evidence_ids={"fact_file"},
            required_operation_evidence_ids={"fact_operation"},
        )[0]
        == "pass"
    )


def test_dispatch_blocks_fake_action_claim_before_llm_receipt(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_service import (
        create_work_item,
        dispatch_assigned_work_items,
        get_work_item,
    )
    import modstore_server.employee_orchestrator as orchestrator

    calls = []

    def _run(*_args, **kwargs):
        calls.append(kwargs["target_employee_id"])
        return {
            "ok": True,
            "status": "completed",
            "accepted_completion": True,
            "summary": "Linux PID 12345 已部署成功",
            "nodes": [{"employee_id": "intent-analyst", "status": "success"}],
        }

    monkeypatch.setattr(orchestrator, "plan_and_dispatch", _run)
    item = create_work_item(
        created_by_user_id=None,
        title="修复并部署服务",
        description="修复并部署服务，必须以真实系统状态验收",
        owner_employee_id="intent-analyst",
        input_data={"external_side_effects": True},
        max_attempts=1,
    )["item"]
    outcome = dispatch_assigned_work_items(limit=1, lease_seconds=60)
    detail = get_work_item(item["task_id"])
    assert outcome["blocked"] == 1
    assert detail["status"] == "blocked"
    assert detail["error_kind"] == "independent_fact_inconclusive"
    assert calls == ["intent-analyst"]
    assert detail["verification_receipts"][0]["status"] == "fail"
    assert not any(row["event_type"] == "task.delivered" for row in detail["events"])


def test_dispatch_delivers_only_after_file_fact_and_receipt(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    artifact = workspace / "deployed.json"
    monkeypatch.setenv("MODSTORE_MANAGEMENT_EVIDENCE_ROOTS", str(workspace))
    from modstore_server.management_work_service import (
        create_work_item,
        dispatch_assigned_work_items,
        get_work_item,
    )
    import modstore_server.employee_orchestrator as orchestrator

    def _run(_task, input_data, **kwargs):
        if kwargs["target_employee_id"] == "delivery-receipt-officer":
            audit = input_data["management_acceptance_audit"]
            return _audit_runtime(
                audit["criteria"],
                fact_required=bool(audit["independent_fact_required"]),
                fact_refs=[
                    *audit.get("required_fact_evidence_ids", []),
                    *audit.get("required_operation_evidence_ids", []),
                ],
            )
        from modstore_server.management_work_operations import (
            begin_operation,
            capture_file_compensation,
            complete_operation,
        )

        operation_context = input_data["management_work"]["operation_context"]
        content = '{"status":"ready","version":"v1"}'
        compensation = capture_file_compensation(
            artifact,
            workspace_root=workspace,
        )
        compensation["expected_after_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
        reserved = begin_operation(
            task_id=operation_context["task_id"],
            employee_id="intent-analyst",
            task_revision=operation_context["task_revision"],
            logical_step="round_1:file.write",
            kind="file.write",
            target=str(artifact),
            request={"content_sha256": compensation["expected_after_sha256"]},
            reversible=True,
            compensation=compensation,
            safe_retry=True,
            execution_attempt=operation_context["attempt"],
        )
        artifact.write_text(content, encoding="utf-8")
        operation = complete_operation(
            reserved["operation"]["operation_id"],
            execution_attempt=reserved["execution_attempt"],
            execution_nonce=reserved["execution_nonce"],
            result={"ok": True, "path": str(artifact)},
            external_ref=str(artifact),
            compensation={
                **compensation,
                "after_sha256": compensation["expected_after_sha256"],
            },
        )
        return {
            "ok": True,
            "status": "completed",
            "accepted_completion": True,
            "summary": "部署文件已经生成",
            "management_operation": operation,
            "management_evidence_claims": [
                {
                    "claim_id": "deployed_json",
                    "kind": "file",
                    "criterion_ids": ["criterion_1"],
                    "workspace_root": str(workspace),
                    "path": "deployed.json",
                    "expected": {
                        "exists": True,
                        "json_subset": {"status": "ready", "version": "v1"},
                    },
                }
            ],
            "nodes": [{"employee_id": "intent-analyst", "status": "success"}],
        }

    monkeypatch.setattr(orchestrator, "plan_and_dispatch", _run)
    item = create_work_item(
        created_by_user_id=None,
        title="部署状态文件",
        description="创建并核验部署状态文件",
        owner_employee_id="intent-analyst",
        input_data={"external_side_effects": True},
        acceptance_criteria=["部署状态必须为 ready 且版本为 v1"],
        max_attempts=1,
    )["item"]
    outcome = dispatch_assigned_work_items(limit=1, lease_seconds=60)
    detail = get_work_item(item["task_id"])
    assert outcome["delivered"] == 1
    assert detail["status"] == "delivered"
    assert detail["fact_evidence"][0]["status"] == "pass"
    assert detail["verification_receipts"][0]["status"] == "pass"
    assert detail["verification_receipts"][0]["fact_required"] is True
    assert any(row["kind"] == "operation" for row in detail["fact_evidence"])

    from modstore_server.management_work_service import (
        WorkItemConflict,
        review_delivery,
    )
    from modstore_server.models import ManagementWorkEvidence, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        for row in session.query(ManagementWorkEvidence).all():
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    with pytest.raises(WorkItemConflict, match="expired"):
        review_delivery(
            item["task_id"],
            reviewed_by_user_id=7,
            accepted=True,
        )


def test_acceptance_rejects_tampered_fact_payload(tmp_path, monkeypatch):
    task_id = _delivered_work_with_signed_file_fact(tmp_path, monkeypatch)
    from modstore_server.management_work_service import WorkItemConflict, review_delivery
    from modstore_server.models import ManagementWorkEvidence, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        fact = session.query(ManagementWorkEvidence).one()
        payload = json.loads(fact.payload_json)
        payload["text_preview"] = "tampered after verification"
        fact.payload_json = json.dumps(payload, ensure_ascii=False)
        session.commit()

    with pytest.raises(WorkItemConflict, match="payload digest mismatch"):
        review_delivery(task_id, reviewed_by_user_id=7, accepted=True)


def test_acceptance_rejects_tampered_fact_signature(tmp_path, monkeypatch):
    task_id = _delivered_work_with_signed_file_fact(tmp_path, monkeypatch)
    from modstore_server.management_work_service import WorkItemConflict, review_delivery
    from modstore_server.models import ManagementWorkEvidence, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        fact = session.query(ManagementWorkEvidence).one()
        fact.signature = "0" * 64
        session.commit()

    with pytest.raises(WorkItemConflict, match="signature is invalid"):
        review_delivery(task_id, reviewed_by_user_id=7, accepted=True)


def test_acceptance_rejects_null_fact_expiry(tmp_path, monkeypatch):
    task_id = _delivered_work_with_signed_file_fact(tmp_path, monkeypatch)
    from modstore_server.management_work_service import WorkItemConflict, review_delivery
    from modstore_server.models import ManagementWorkEvidence, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        fact = session.query(ManagementWorkEvidence).one()
        fact.expires_at = None
        session.commit()

    with pytest.raises(WorkItemConflict, match="no valid expiry"):
        review_delivery(task_id, reviewed_by_user_id=7, accepted=True)


def test_acceptance_rejects_fact_bundle_digest_mismatch(tmp_path, monkeypatch):
    task_id = _delivered_work_with_signed_file_fact(tmp_path, monkeypatch)
    from modstore_server.management_work_service import WorkItemConflict, review_delivery
    from modstore_server.models import (
        ManagementWorkVerificationReceipt,
        get_session_factory,
    )

    sf = get_session_factory()
    with sf() as session:
        receipt = session.query(ManagementWorkVerificationReceipt).one()
        receipt.fact_bundle_digest = "0" * 64
        session.commit()

    with pytest.raises(WorkItemConflict, match="fact bundle digest mismatch"):
        review_delivery(task_id, reviewed_by_user_id=7, accepted=True)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("task_id", "mwi_other", "another task"),
        ("status", "fail", "no passing independent verification receipt"),
        ("fact_outcome", "fail", "fact outcome is not passing"),
        ("audit_outcome", "fail", "audit outcome is not passing"),
        ("verifier_employee_id", "intent-analyst", "verifier is not authoritative"),
        ("result_digest", "", "result digest must be 64-character lowercase hex"),
        ("result_digest", "A" * 64, "result digest must be 64-character lowercase hex"),
        ("result_digest", "0" * 64 + " ", "result digest must be 64-character lowercase hex"),
        (
            "fact_bundle_digest",
            "0" * 63,
            "fact bundle digest must be 64-character lowercase hex",
        ),
        ("audit_json", "{", "audit payload is malformed"),
        (
            "audit_json",
            json.dumps({"outcome": "fail", "report": {}}),
            "audit outcome does not match its payload",
        ),
        (
            "audit_json",
            json.dumps({"outcome": "pass", "report": []}),
            "audit report is malformed",
        ),
    ],
)
def test_acceptance_rechecks_authoritative_receipt_fields(
    tmp_path, monkeypatch, field, value, message
):
    task_id = _delivered_work_with_signed_file_fact(tmp_path, monkeypatch)
    from modstore_server.management_work_service import WorkItemConflict, review_delivery
    from modstore_server.models import (
        ManagementWorkVerificationReceipt,
        get_session_factory,
    )

    sf = get_session_factory()
    with sf() as session:
        receipt = session.query(ManagementWorkVerificationReceipt).one()
        setattr(receipt, field, value)
        session.commit()

    with pytest.raises(WorkItemConflict, match=message):
        review_delivery(task_id, reviewed_by_user_id=7, accepted=True)


def test_operation_key_replays_success_and_rejects_changed_request(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_operations import (
        ManagementOperationConflict,
        begin_operation,
        complete_operation,
    )
    from modstore_server.management_work_service import claim_work_item, create_work_item

    item = create_work_item(
        created_by_user_id=None,
        title="幂等操作",
        description="验证副作用只执行一次",
        owner_employee_id="intent-analyst",
    )["item"]
    claim_work_item(item["task_id"], employee_id="intent-analyst")
    first = begin_operation(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_revision=1,
        logical_step="round_1:file.write",
        kind="file.write",
        target="result.md",
        request={"sha256": "a"},
        reversible=True,
    )
    assert first["action"] == "execute"
    complete_operation(
        first["operation"]["operation_id"],
        execution_attempt=first["execution_attempt"],
        execution_nonce=first["execution_nonce"],
        result={"ok": True, "path": "result.md"},
    )
    replay = begin_operation(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_revision=1,
        logical_step="round_1:file.write",
        kind="file.write",
        target="result.md",
        request={"sha256": "a"},
        reversible=True,
    )
    assert replay["action"] == "replay"
    assert replay["result"]["path"] == "result.md"
    with pytest.raises(ManagementOperationConflict, match="digest mismatch"):
        begin_operation(
            task_id=item["task_id"],
            employee_id="intent-analyst",
            task_revision=1,
            logical_step="round_1:file.write",
            kind="file.write",
            target="result.md",
            request={"sha256": "different"},
            reversible=True,
        )


def test_expired_file_operation_reconciles_postimage_without_reexecution(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "crash-gap.txt"
    from modstore_server.management_work_operations import (
        begin_operation,
        capture_file_compensation,
    )
    from modstore_server.management_work_service import claim_work_item, create_work_item

    item = create_work_item(
        created_by_user_id=None,
        title="崩溃窗口回读",
        description="写入成功但回执未落盘时不能再写一次",
        owner_employee_id="intent-analyst",
    )["item"]
    claim_work_item(item["task_id"], employee_id="intent-analyst")
    content = "after-crash"
    after_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    compensation = capture_file_compensation(
        target,
        workspace_root=workspace,
    )
    compensation["expected_after_sha256"] = after_sha
    first = begin_operation(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_revision=1,
        logical_step="round_1:file.write",
        kind="file.write",
        target=str(target),
        request={"content_sha256": after_sha},
        reversible=True,
        compensation=compensation,
        safe_retry=True,
        lease_seconds=5,
    )
    target.write_text(content, encoding="utf-8")
    sf = models.get_session_factory()
    with sf() as session:
        operation = session.query(models.ManagementWorkOperation).one()
        operation.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    reconciled = begin_operation(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_revision=1,
        logical_step="round_1:file.write",
        kind="file.write",
        target=str(target),
        request={"content_sha256": after_sha},
        reversible=True,
        compensation=compensation,
        safe_retry=True,
    )
    assert reconciled["action"] == "replay"
    assert reconciled["operation"]["operation_id"] == first["operation"]["operation_id"]
    assert reconciled["result"]["reconciled_after_worker_exit"] is True
    assert target.read_text(encoding="utf-8") == content


def test_expired_remote_operation_never_blindly_reclaims(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_operations import begin_operation
    from modstore_server.management_work_service import claim_work_item, create_work_item

    item = create_work_item(
        created_by_user_id=None,
        title="远端未知结果",
        description="HTTP 超时不能盲目重放",
        owner_employee_id="intent-analyst",
    )["item"]
    claim_work_item(item["task_id"], employee_id="intent-analyst")
    args = {
        "task_id": item["task_id"],
        "employee_id": "intent-analyst",
        "task_revision": 1,
        "logical_step": "round_1:http.post",
        "kind": "http.post",
        "target": "https://example.invalid/action",
        "request": {"value": 1},
        "reversible": False,
        "safe_retry": False,
        "lease_seconds": 5,
    }
    first = begin_operation(**args)
    sf = models.get_session_factory()
    with sf() as session:
        operation = session.query(models.ManagementWorkOperation).one()
        operation.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    second = begin_operation(**args)
    assert first["action"] == "execute"
    assert second["action"] == "blocked"
    # The remote call may already have committed even though its lease expired.
    # Mark it uncertain so a retry cannot duplicate an irreversible side effect.
    assert second["operation"]["status"] == "uncertain"


def test_file_operation_replays_and_cancel_restores_preimage(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "managed.txt"
    target.write_text("before", encoding="utf-8")
    from modstore_server.management_work_service import (
        cancel_work_item,
        claim_work_item,
        create_work_item,
        finalize_requested_cancellation,
        get_work_item,
    )
    from modstore_server.mod_employee_agent_runner import tool_write_workspace_file

    item = create_work_item(
        created_by_user_id=None,
        title="可补偿文件写入",
        description="写文件后取消必须恢复",
        owner_employee_id="intent-analyst",
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    ctx = {
        "employee_id": "intent-analyst",
        "bypass_change_request": True,
        "management_operation_step": "tool:write_workspace_file",
        "management_work_operation_context": {
            "task_id": item["task_id"],
            "task_revision": 1,
            "attempt": int(claimed["attempt_count"]),
        },
    }
    first = asyncio.run(tool_write_workspace_file(str(workspace), "managed.txt", "after", ctx))
    second = asyncio.run(tool_write_workspace_file(str(workspace), "managed.txt", "after", ctx))
    assert first["ok"] is True
    assert second["replayed"] is True
    assert target.read_text(encoding="utf-8") == "after"
    assert len(get_work_item(item["task_id"])["operations"]) == 1
    assert cancel_work_item(item["task_id"], requested_by_user_id=7)["status"] == "cancel_requested"
    final = finalize_requested_cancellation(
        item["task_id"],
        employee_id="intent-analyst",
        lease_token=claimed["lease_token"],
    )
    assert final["status"] == "cancelled"
    assert target.read_text(encoding="utf-8") == "before"
    operation = get_work_item(item["task_id"])["operations"][0]
    assert operation["compensation_status"] == "compensated"


def test_agent_round_retry_uses_stable_tool_operation_identity(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from modstore_server.management_work_service import (
        claim_work_item,
        create_work_item,
        get_work_item,
    )
    from modstore_server.mod_employee_agent_runner import EmployeeAgentRunner

    item = create_work_item(
        created_by_user_id=None,
        title="跨推理轮次幂等写入",
        description="同一任务修订、工具和目标只能有一个 operation",
        owner_employee_id="intent-analyst",
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    tool_call = json.dumps(
        {
            "tool": "write_workspace_file",
            "input": {"path": "stable.txt", "content": "same-content"},
        },
        ensure_ascii=False,
    )
    responses = [
        {"ok": True, "content": tool_call},
        {"ok": True, "content": tool_call},
        {"ok": True, "content": json.dumps({"answer": "已完成幂等写入"}, ensure_ascii=False)},
    ]

    async def _call_llm(_messages, **_kwargs):
        return responses.pop(0)

    runner = EmployeeAgentRunner(
        {
            "call_llm": _call_llm,
            "employee_id": "intent-analyst",
            "bypass_change_request": True,
            "management_work_operation_context": {
                "task_id": item["task_id"],
                "task_revision": 1,
                "attempt": int(claimed["attempt_count"]),
            },
        },
        max_rounds=4,
        workspace_root=str(workspace),
    )
    result = asyncio.run(runner.run("将同一内容写入 stable.txt"))

    assert result["ok"] is True
    assert len(result["tool_calls"]) == 2
    assert result["tool_calls"][0]["result"]["ok"] is True
    assert result["tool_calls"][1]["result"]["replayed"] is True
    assert (workspace / "stable.txt").read_text(encoding="utf-8") == "same-content"
    detail = get_work_item(item["task_id"])
    assert len(detail["operations"]) == 1
    assert detail["operations"][0]["logical_step"] == "tool:write_workspace_file"
    assert len([row for row in detail["events"] if row["event_type"] == "operation.started"]) == 1


def test_unknown_side_effect_blocks_cancel_instead_of_false_cancelled(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_operations import begin_operation
    from modstore_server.management_work_service import (
        cancel_work_item,
        claim_work_item,
        create_work_item,
        finalize_requested_cancellation,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="未知远端动作",
        description="远端动作结果未知时不能假装取消成功",
        owner_employee_id="intent-analyst",
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    begin_operation(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_revision=1,
        logical_step="round_1:http.post",
        kind="http.post",
        target="https://example.invalid/action",
        request={"value": 1},
        reversible=False,
    )
    cancel_work_item(item["task_id"], requested_by_user_id=7)
    final = finalize_requested_cancellation(
        item["task_id"],
        employee_id="intent-analyst",
        lease_token=claimed["lease_token"],
    )
    assert final["status"] == "blocked"
    assert final["error_kind"] == "side_effect_recovery_required"


def test_concurrent_operation_reservation_has_one_executor(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_operations import begin_operation
    from modstore_server.management_work_service import claim_work_item, create_work_item

    item = create_work_item(
        created_by_user_id=None,
        title="并发副作用",
        description="并发只允许一个执行者",
        owner_employee_id="intent-analyst",
    )["item"]
    claim_work_item(item["task_id"], employee_id="intent-analyst")

    def reserve():
        return begin_operation(
            task_id=item["task_id"],
            employee_id="intent-analyst",
            task_revision=1,
            logical_step="round_1:file.write",
            kind="file.write",
            target="same.txt",
            request={"sha256": "same"},
            reversible=True,
        )["action"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        actions = [future.result() for future in [pool.submit(reserve), pool.submit(reserve)]]
    assert actions.count("execute") == 1
    assert actions.count("blocked") == 1


def test_succeeded_replay_rebinds_to_current_attempt_and_rejects_stale_begin(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_operations import (
        ManagementOperationConflict,
        begin_operation,
        complete_operation,
    )
    from modstore_server.management_work_service import (
        claim_work_item,
        create_work_item,
        fail_work_item,
        get_work_item,
        retry_work_item,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="成功操作跨尝试复用",
        description="只允许服务端确认的 replay 回执进入新 attempt",
        owner_employee_id="intent-analyst",
        max_attempts=3,
    )["item"]
    first_claim = claim_work_item(item["task_id"], employee_id="intent-analyst")
    operation_args = {
        "task_id": item["task_id"],
        "employee_id": "intent-analyst",
        "task_revision": 1,
        "logical_step": "stable:file.write",
        "kind": "file.write",
        "target": "stable-result.txt",
        "request": {"sha256": "same-request"},
        "reversible": False,
    }
    first = begin_operation(
        **operation_args,
        execution_attempt=int(first_claim["attempt_count"]),
    )
    complete_operation(
        first["operation"]["operation_id"],
        execution_attempt=first["execution_attempt"],
        execution_nonce=first["execution_nonce"],
        result={"ok": True, "path": "stable-result.txt"},
    )
    failed = fail_work_item(
        item["task_id"],
        employee_id="intent-analyst",
        lease_token=first_claim["lease_token"],
        error_kind="later_step_failed",
        error="后续步骤失败",
        retryable=True,
    )
    assert failed["status"] == "retrying"
    retry_work_item(item["task_id"], requested_by_user_id=7)
    second_claim = claim_work_item(item["task_id"], employee_id="intent-analyst")
    assert int(second_claim["attempt_count"]) == int(first_claim["attempt_count"]) + 1

    with pytest.raises(ManagementOperationConflict, match="attempt changed"):
        begin_operation(
            **{**operation_args, "logical_step": "new:file.write"},
            execution_attempt=int(first_claim["attempt_count"]),
        )

    replay = begin_operation(
        **operation_args,
        execution_attempt=int(second_claim["attempt_count"]),
    )
    assert replay["action"] == "replay"
    assert replay["operation"]["attempt"] == int(second_claim["attempt_count"])
    assert replay["execution_nonce"] != first["execution_nonce"]
    replay_events = [
        row
        for row in get_work_item(item["task_id"])["events"]
        if row["event_type"] == "operation.replayed"
    ]
    assert replay_events[-1]["payload"]["previous_attempt"] == int(first_claim["attempt_count"])
    assert replay_events[-1]["payload"]["current_attempt"] == int(second_claim["attempt_count"])


def test_complete_and_fail_reject_stale_worker_after_cancel(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    from modstore_server.management_work_operations import (
        ManagementOperationConflict,
        begin_operation,
        complete_operation,
        fail_operation,
    )
    from modstore_server.management_work_service import (
        cancel_work_item,
        claim_work_item,
        create_work_item,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="过期子进程不得收口副作用",
        description="取消后 complete/fail 都必须拒绝",
        owner_employee_id="intent-analyst",
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    reserved = begin_operation(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_revision=1,
        logical_step="remote:post",
        kind="http.post",
        target="https://example.invalid/action",
        request={"value": 1},
        execution_attempt=int(claimed["attempt_count"]),
    )
    cancel_work_item(item["task_id"], requested_by_user_id=7)
    credentials = {
        "execution_attempt": reserved["execution_attempt"],
        "execution_nonce": reserved["execution_nonce"],
    }
    with pytest.raises(ManagementOperationConflict, match="not running"):
        complete_operation(
            reserved["operation"]["operation_id"],
            **credentials,
            result={"ok": True},
        )
    with pytest.raises(ManagementOperationConflict, match="not running"):
        fail_operation(
            reserved["operation"]["operation_id"],
            **credentials,
            error="late failure",
            outcome_known_no_effect=True,
        )


def test_file_write_cas_refuses_concurrent_preimage_change(tmp_path, monkeypatch):
    _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "managed.txt"
    target.write_text("before", encoding="utf-8")
    import modstore_server.management_work_operations as operations
    from modstore_server.management_work_service import (
        claim_work_item,
        create_work_item,
        get_work_item,
    )
    from modstore_server.mod_employee_agent_runner import tool_write_workspace_file

    item = create_work_item(
        created_by_user_id=None,
        title="并发写入 CAS",
        description="不得覆盖捕获 preimage 后的新写入",
        owner_employee_id="intent-analyst",
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    real_begin = operations.begin_operation

    def _begin_then_race(**kwargs):
        reserved = real_begin(**kwargs)
        if reserved.get("action") == "execute":
            target.write_text("concurrent-update", encoding="utf-8")
        return reserved

    monkeypatch.setattr(operations, "begin_operation", _begin_then_race)
    result = asyncio.run(
        tool_write_workspace_file(
            str(workspace),
            "managed.txt",
            "employee-update",
            {
                "employee_id": "intent-analyst",
                "bypass_change_request": True,
                "management_operation_step": "stable:write_workspace_file",
                "management_work_operation_context": {
                    "task_id": item["task_id"],
                    "task_revision": 1,
                    "attempt": int(claimed["attempt_count"]),
                },
            },
        )
    )
    assert result["ok"] is False
    assert "拒绝覆盖" in result["error"]
    assert target.read_text(encoding="utf-8") == "concurrent-update"
    operation = get_work_item(item["task_id"])["operations"][0]
    assert operation["status"] == "failed"
    assert "execution_nonce" not in json.dumps(result, ensure_ascii=False)


def test_existing_operation_table_is_upgraded_with_execution_nonce(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    engine = models.get_engine()
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP INDEX IF EXISTS ix_management_work_operations_execution_nonce"
        )
        connection.exec_driver_sql(
            "ALTER TABLE management_work_operations DROP COLUMN execution_nonce"
        )
        columns = connection.exec_driver_sql(
            "PRAGMA table_info(management_work_operations)"
        ).fetchall()
    assert "execution_nonce" not in {str(row[1]) for row in columns}

    from modstore_server.management_work_operations import begin_operation
    from modstore_server.management_work_service import claim_work_item, create_work_item

    item = create_work_item(
        created_by_user_id=None,
        title="旧表结构升级",
        description="运行时应补齐 execution_nonce 列",
        owner_employee_id="intent-analyst",
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    reserved = begin_operation(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_revision=1,
        logical_step="schema:write",
        kind="file.write",
        target="schema.txt",
        request={"sha256": "schema"},
        execution_attempt=int(claimed["attempt_count"]),
    )
    assert reserved["execution_nonce"]
    with engine.begin() as connection:
        columns = connection.exec_driver_sql(
            "PRAGMA table_info(management_work_operations)"
        ).fetchall()
    assert "execution_nonce" in {str(row[1]) for row in columns}


def test_cancelled_execution_cannot_persist_change_request_or_complete_operation(
    tmp_path, monkeypatch
):
    models = _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from modstore_server.employee_change_request_service import (
        defer_write_as_change_request,
    )
    from modstore_server.management_work_operations import (
        ManagementOperationConflict,
        begin_operation,
    )
    from modstore_server.management_work_service import (
        cancel_work_item,
        claim_work_item,
        create_work_item,
    )

    item = create_work_item(
        created_by_user_id=None,
        title="取消后禁止落变更申请",
        description="CR 创建与 operation succeeded 必须共用当前租约",
        owner_employee_id="intent-analyst",
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    reserved = begin_operation(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_revision=1,
        logical_step="stable:change_request.submit",
        kind="change_request.submit",
        target=str((workspace / "change.txt").resolve()),
        request={"content_sha256": hashlib.sha256(b"change").hexdigest()},
        execution_attempt=int(claimed["attempt_count"]),
    )
    cancel_work_item(item["task_id"], requested_by_user_id=7)

    with pytest.raises(ManagementOperationConflict, match="not running"):
        defer_write_as_change_request(
            "intent-analyst",
            str(workspace),
            "change.txt",
            "change",
            management_operation_id=reserved["operation"]["operation_id"],
            execution_attempt=reserved["execution_attempt"],
            execution_nonce=reserved["execution_nonce"],
        )

    sf = models.get_session_factory()
    with sf() as session:
        assert session.query(models.EmployeeChangeRequest).count() == 0
        operation = session.query(models.ManagementWorkOperation).one()
        assert operation.status == "running"


def test_stale_or_expired_execution_cannot_persist_change_request(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from modstore_server.employee_change_request_service import (
        defer_write_as_change_request,
    )
    from modstore_server.management_work_operations import (
        ManagementOperationConflict,
        begin_operation,
    )
    from modstore_server.management_work_service import claim_work_item, create_work_item

    item = create_work_item(
        created_by_user_id=None,
        title="过期执行禁止落变更申请",
        description="attempt、nonce 与租约必须同时有效",
        owner_employee_id="intent-analyst",
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    reserved = begin_operation(
        task_id=item["task_id"],
        employee_id="intent-analyst",
        task_revision=1,
        logical_step="stable:change_request.submit",
        kind="change_request.submit",
        target=str((workspace / "change.txt").resolve()),
        request={"content_sha256": hashlib.sha256(b"change").hexdigest()},
        execution_attempt=int(claimed["attempt_count"]),
    )
    operation_id = reserved["operation"]["operation_id"]

    with pytest.raises(ManagementOperationConflict, match="attempt changed"):
        defer_write_as_change_request(
            "intent-analyst",
            str(workspace),
            "change.txt",
            "change",
            management_operation_id=operation_id,
            execution_attempt=int(reserved["execution_attempt"]) + 1,
            execution_nonce=reserved["execution_nonce"],
        )
    with pytest.raises(ManagementOperationConflict, match="nonce changed"):
        defer_write_as_change_request(
            "intent-analyst",
            str(workspace),
            "change.txt",
            "change",
            management_operation_id=operation_id,
            execution_attempt=reserved["execution_attempt"],
            execution_nonce="stale-nonce",
        )

    sf = models.get_session_factory()
    with sf() as session:
        work = session.query(models.ManagementWorkItem).one()
        work.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    with pytest.raises(ManagementOperationConflict, match="lease has expired"):
        defer_write_as_change_request(
            "intent-analyst",
            str(workspace),
            "change.txt",
            "change",
            management_operation_id=operation_id,
            execution_attempt=reserved["execution_attempt"],
            execution_nonce=reserved["execution_nonce"],
        )

    with sf() as session:
        assert session.query(models.EmployeeChangeRequest).count() == 0
        operation = session.query(models.ManagementWorkOperation).one()
        assert operation.status == "running"


def test_agent_change_request_commits_with_bound_operation_receipt(tmp_path, monkeypatch):
    models = _reset_db(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from modstore_server.management_work_service import claim_work_item, create_work_item
    from modstore_server.mod_employee_agent_runner import tool_write_workspace_file

    item = create_work_item(
        created_by_user_id=None,
        title="变更申请与操作回执原子落库",
        description="runner 必须传递 attempt 与 execution nonce",
        owner_employee_id="intent-analyst",
    )["item"]
    claimed = claim_work_item(item["task_id"], employee_id="intent-analyst")
    result = asyncio.run(
        tool_write_workspace_file(
            str(workspace),
            "change.txt",
            "change",
            {
                "employee_id": "intent-analyst",
                "management_operation_step": "stable:change_request.submit",
                "management_work_operation_context": {
                    "task_id": item["task_id"],
                    "task_revision": 1,
                    "attempt": int(claimed["attempt_count"]),
                },
            },
        )
    )
    assert result["ok"] is True
    assert result["deferred"] is True
    assert "execution_nonce" not in json.dumps(result, ensure_ascii=False)
    sf = models.get_session_factory()
    with sf() as session:
        change_request = session.get(models.EmployeeChangeRequest, int(result["change_request_id"]))
        operation = session.query(models.ManagementWorkOperation).one()
        assert change_request is not None
        assert operation.status == "succeeded"
        assert operation.attempt == int(claimed["attempt_count"])
        assert operation.external_ref == f"change_request:{change_request.id}"
