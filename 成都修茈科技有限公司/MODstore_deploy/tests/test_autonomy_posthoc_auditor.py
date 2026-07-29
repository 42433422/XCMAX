from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import modstore_server.db.base as db_base
import modstore_server.models as models
from modstore_server.autonomy_decision_audit import (
    append_autonomy_decision,
    build_autonomy_decision_evidence,
)
from modstore_server.autonomy_posthoc_auditor import run_autonomy_posthoc_audit
from modstore_server.db.employee_ops import (
    DailyDigestRecord,
    EmployeeChangeRequest,
    EmployeeSuggestion,
)
from modstore_server.db.scheduler_ops import JobRun

UTC = timezone.utc
NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    for engine in {models._engine, db_base._engine}:
        if engine is not None:
            engine.dispose()
    models._engine = None
    models._SessionFactory = None
    db_base._engine = None
    db_base._SessionFactory = None
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "posthoc.sqlite"))
    models.init_db()
    yield models.get_session_factory()
    for engine in {models._engine, db_base._engine}:
        if engine is not None:
            engine.dispose()
    models._engine = None
    models._SessionFactory = None
    db_base._engine = None
    db_base._SessionFactory = None


def _allow_metrics(sf) -> None:
    append_autonomy_decision(
        action_id="autonomy-metrics:2026-07-22",
        action="autonomy_metrics_snapshot",
        decision="allow",
        policy="autonomy_guard",
        risk_level="low",
        actor_class="system",
        source="autonomy_metrics.cron",
        occurred_at=NOW,
        session_factory=sf,
    )


def _write_metrics(path, *, complete: bool = True) -> None:
    windows = (30, 90) if complete else (30,)
    path.write_text(
        "".join(
            json.dumps(
                {
                    "snapshot_date": "2026-07-22",
                    "snapshot_at": NOW.isoformat(),
                    "window_days": window,
                    "cohort": "operational",
                    "status": "collecting",
                    "has_prohibited_miss": False,
                }
            )
            + "\n"
            for window in windows
        ),
        encoding="utf-8",
    )


def test_correlates_allow_later_job_receipt_and_durable_artifact(
    session_factory,
    tmp_path,
):
    _allow_metrics(session_factory)
    artifact = tmp_path / "autonomy-metrics.jsonl"
    _write_metrics(artifact)
    with session_factory() as session:
        session.add(
            JobRun(
                job_id="autonomy_metrics_snapshot",
                status="success",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=2),
                duration_ms=2000,
                error="",
            )
        )
        session.commit()

    result = run_autonomy_posthoc_audit(
        metrics_path=artifact,
        now=NOW + timedelta(seconds=3),
        session_factory=session_factory,
    )
    repeat = run_autonomy_posthoc_audit(
        metrics_path=artifact,
        now=NOW + timedelta(seconds=4),
        session_factory=session_factory,
    )
    evidence = build_autonomy_decision_evidence(
        now=NOW + timedelta(seconds=5),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 1
    assert result["append_only_evidence_written"] is True
    assert repeat["audited_count"] == 0
    assert evidence["has_prohibited_miss"] is False
    assert evidence["posthoc_coverage_rate"] == 100.0
    posthoc = next(item for item in evidence["items"] if item["record_type"] == "posthoc_anomaly")
    assert posthoc["source"] == "autonomy-posthoc-auditor.v2"
    assert posthoc["evidence_ref"].startswith("scheduler-job:")


def test_incomplete_artifact_remains_unknown(session_factory, tmp_path):
    _allow_metrics(session_factory)
    artifact = tmp_path / "autonomy-metrics.jsonl"
    _write_metrics(artifact, complete=False)
    with session_factory() as session:
        session.add(
            JobRun(
                job_id="autonomy_metrics_snapshot",
                status="success",
                started_at=NOW,
                finished_at=NOW + timedelta(seconds=1),
                duration_ms=1000,
                error="",
            )
        )
        session.commit()

    result = run_autonomy_posthoc_audit(
        metrics_path=artifact,
        now=NOW + timedelta(seconds=2),
        session_factory=session_factory,
    )
    evidence = build_autonomy_decision_evidence(
        now=NOW + timedelta(seconds=3),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 0
    assert result["incomplete"] == [
        {
            "action_id": "autonomy-metrics:2026-07-22",
            "reason": "metrics_windows_incomplete",
        }
    ]
    assert evidence["has_prohibited_miss"] is None
    assert evidence["posthoc_coverage_rate"] == 0.0


def _allow_daily_digest(sf, day: str = "2026-07-22") -> None:
    append_autonomy_decision(
        action_id=f"daily-digest:{day}",
        action="daily_digest",
        decision="allow",
        policy="autonomy_guard",
        risk_level="low",
        actor_class="system",
        source="daily_digest.cron",
        occurred_at=NOW,
        session_factory=sf,
    )


def test_daily_digest_requires_coherent_later_delivery_receipt(
    session_factory,
    monkeypatch,
):
    monkeypatch.setenv("MODSTORE_DAILY_DIGEST_EMAIL", "owner@example.com")
    _allow_daily_digest(session_factory)
    with session_factory() as session:
        session.add(
            DailyDigestRecord(
                day="2026-07-22",
                subject="MODstore 每日摘要 · 2026-07-22",
                body_html="<p>bounded digest</p>",
                recipients_json='["owner@example.com"]',
                delivery_json=json.dumps(
                    [
                        {
                            "to": "owner@example.com",
                            "delivered": True,
                            "mode": "smtp",
                            "error": "",
                        }
                    ]
                ),
                delivered=True,
                source="daily_digest",
                created_at=NOW + timedelta(seconds=1),
            )
        )
        session.commit()

    result = run_autonomy_posthoc_audit(
        now=NOW + timedelta(seconds=2),
        session_factory=session_factory,
    )
    evidence = build_autonomy_decision_evidence(
        now=NOW + timedelta(seconds=3),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 1
    assert result["incomplete_count"] == 0
    assert evidence["has_prohibited_miss"] is False
    posthoc = next(item for item in evidence["items"] if item["record_type"] == "posthoc_anomaly")
    assert posthoc["evidence_ref"].startswith("daily-digest-record:")
    assert "owner@example.com" not in posthoc["evidence_ref"]


@pytest.mark.parametrize(
    ("record_kwargs", "reason"),
    [
        (
            {
                "recipients_json": '["owner@example.com"]',
                "delivery_json": '[{"to":"owner@example.com","delivered":false,"mode":"smtp"}]',
                "delivered": False,
            },
            "daily_digest_delivery_receipt_missing",
        ),
        (
            {
                "recipients_json": '["owner@example.com"]',
                "delivery_json": '[{"to":"other@example.com","delivered":true,"mode":"smtp"}]',
                "delivered": True,
            },
            "daily_digest_delivery_receipt_incoherent",
        ),
    ],
)
def test_daily_digest_incomplete_or_contradictory_receipt_stays_unknown(
    session_factory,
    monkeypatch,
    record_kwargs,
    reason,
):
    monkeypatch.setenv("MODSTORE_DAILY_DIGEST_EMAIL", "owner@example.com")
    _allow_daily_digest(session_factory)
    with session_factory() as session:
        session.add(
            DailyDigestRecord(
                day="2026-07-22",
                subject="MODstore 每日摘要 · 2026-07-22",
                body_html="<p>bounded digest</p>",
                source="daily_digest",
                created_at=NOW + timedelta(seconds=1),
                **record_kwargs,
            )
        )
        session.commit()

    result = run_autonomy_posthoc_audit(
        now=NOW + timedelta(seconds=2),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 0
    assert result["incomplete"] == [
        {
            "action_id": "daily-digest:2026-07-22",
            "reason": reason,
        }
    ]


def _allow_code_write(sf, change_request_id: int) -> None:
    append_autonomy_decision(
        action_id=f"change-request:{change_request_id}:apply",
        action="code_write",
        decision="allow",
        policy="autonomy_guard",
        risk_level="high",
        actor_class="system",
        source="modstore.auto_approve_policy",
        occurred_at=NOW,
        session_factory=sf,
    )


def _allow_merge(sf, run_id: str) -> str:
    action_id = f"loop:{run_id}:self_maintenance_l1_merge"
    append_autonomy_decision(
        action_id=action_id,
        action="self_maintenance_l1_merge",
        decision="allow",
        policy="autonomy_guard",
        risk_level="low",
        actor_class="system",
        source="self_maintenance_loop.remote_merge_request",
        occurred_at=NOW,
        session_factory=sf,
    )
    return action_id


def test_code_write_narrow_ci_failure_proves_no_effect(session_factory, tmp_path):
    change_request_id = 171
    _allow_code_write(session_factory, change_request_id)
    with session_factory() as session:
        session.add(
            EmployeeChangeRequest(
                id=change_request_id,
                source_employee_id="code-employee",
                change_kind="file_edit",
                workspace_root_hint=str(tmp_path),
                target_paths_json="[]",
                diff_summary="",
                diff_blob="{}",
                status="failed",
                risk_level="medium",
                error="narrow_ci_failed:py_compile",
                created_at=NOW,
            )
        )
        session.add(
            EmployeeSuggestion(
                source_employee_id="evolution-engine",
                target_employee_ids_json='["code-employee"]',
                kind="cr_narrow_ci_failure",
                payload_json=json.dumps(
                    {
                        "change_request_id": change_request_id,
                        "validation": {"failed_step": "py_compile"},
                    }
                ),
                risk_level="low",
                status="dispatched",
                created_at=NOW + timedelta(seconds=1),
            )
        )
        session.commit()

    result = run_autonomy_posthoc_audit(
        metrics_path=tmp_path / "unused.jsonl",
        now=NOW + timedelta(seconds=2),
        session_factory=session_factory,
    )
    evidence = build_autonomy_decision_evidence(
        now=NOW + timedelta(seconds=3),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 1
    assert evidence["has_prohibited_miss"] is False
    posthoc = next(item for item in evidence["items"] if item["record_type"] == "posthoc_anomaly")
    assert posthoc["evidence_ref"].startswith("employee-suggestion:")


def test_code_write_without_later_receipt_remains_unknown(session_factory, tmp_path):
    change_request_id = 172
    _allow_code_write(session_factory, change_request_id)
    with session_factory() as session:
        session.add(
            EmployeeChangeRequest(
                id=change_request_id,
                source_employee_id="code-employee",
                change_kind="file_edit",
                workspace_root_hint=str(tmp_path),
                target_paths_json="[]",
                diff_summary="",
                diff_blob="{}",
                status="pending",
                risk_level="medium",
                created_at=NOW,
            )
        )
        session.commit()

    result = run_autonomy_posthoc_audit(
        now=NOW + timedelta(seconds=2),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 0
    assert result["incomplete"] == [
        {
            "action_id": f"change-request:{change_request_id}:apply",
            "reason": "terminal_no_effect_receipt_missing",
        }
    ]


def test_terminal_vetoed_merge_proves_no_effect(session_factory, tmp_path):
    run_id = "06a59f24-ddd6-4278-834a-09259ac654e1"
    task_id = "3999745d-f4eb-4856-ab46-416cca2acb14"
    _allow_merge(session_factory, run_id)
    ledger = tmp_path / "self-maintenance.jsonl"
    ledger.write_text(
        json.dumps(
            {
                "event": "merge_requested",
                "run_id": run_id,
                "para_task_id": task_id,
                "created_at": (NOW + timedelta(seconds=1)).isoformat(),
                "ok": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_autonomy_posthoc_audit(
        self_maintenance_ledger_path=ledger,
        para_task_fetcher=lambda _task_id: {
            "status": "merge_conflict",
            "merge_commit_sha": "",
        },
        now=NOW + timedelta(seconds=2),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 1
    assert result["incomplete_count"] == 0


def test_merged_action_requires_same_sha_production_receipt(session_factory, tmp_path):
    run_id = "02b3e3c8-1dc7-4449-a348-b375694be9a8"
    task_id = "7bb72aeb-1755-4a1c-845b-5d9c54c44565"
    merge_sha = "455e6162e4e85aedb51282bdeffbe891b08316d1"
    _allow_merge(session_factory, run_id)
    records = [
        {
            "event": "merge_requested",
            "run_id": run_id,
            "para_task_id": task_id,
            "created_at": (NOW + timedelta(seconds=1)).isoformat(),
            "ok": True,
        },
        {
            "event": "post_deploy_verified",
            "run_id": run_id,
            "created_at": (NOW + timedelta(seconds=2)).isoformat(),
            "environment": "production",
            "status": "verified",
            "merge_sha": merge_sha,
            "workflow_run_id": "30278861121",
            "identity_verified": True,
            "ok": True,
        },
        {
            "event": "merge_completed",
            "run_id": run_id,
            "created_at": (NOW + timedelta(seconds=2)).isoformat(),
            "status": "completed_merged",
            "merge_sha": merge_sha,
            "ok": True,
        },
    ]
    ledger = tmp_path / "self-maintenance.jsonl"
    ledger.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    result = run_autonomy_posthoc_audit(
        self_maintenance_ledger_path=ledger,
        para_task_fetcher=lambda _task_id: {
            "status": "merged",
            "merge_commit_sha": merge_sha,
        },
        now=NOW + timedelta(seconds=2),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 1
    assert result["incomplete_count"] == 0


def test_merge_sha_mismatch_remains_unknown(session_factory, tmp_path):
    run_id = "a4a0774b-ada7-423a-8974-8f0f8af1003e"
    task_id = "6748f024-952e-4361-a497-c2af84b6c893"
    _allow_merge(session_factory, run_id)
    ledger = tmp_path / "self-maintenance.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "merge_requested",
                        "run_id": run_id,
                        "para_task_id": task_id,
                        "created_at": (NOW + timedelta(seconds=1)).isoformat(),
                        "ok": True,
                    }
                ),
                json.dumps(
                    {
                        "event": "post_deploy_verified",
                        "run_id": run_id,
                        "created_at": (NOW + timedelta(seconds=2)).isoformat(),
                        "environment": "production",
                        "status": "verified",
                        "merge_sha": "b" * 40,
                        "workflow_run_id": "30054859876",
                        "identity_verified": True,
                        "ok": True,
                    }
                ),
                json.dumps(
                    {
                        "event": "merge_completed",
                        "run_id": run_id,
                        "created_at": (NOW + timedelta(seconds=2)).isoformat(),
                        "status": "completed_merged",
                        "merge_sha": "b" * 40,
                        "ok": True,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = run_autonomy_posthoc_audit(
        self_maintenance_ledger_path=ledger,
        para_task_fetcher=lambda _task_id: {
            "status": "merged",
            "merge_commit_sha": "a" * 40,
        },
        now=NOW + timedelta(seconds=2),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 0
    assert result["incomplete"] == [
        {
            "action_id": f"loop:{run_id}:self_maintenance_l1_merge",
            "reason": "exact_production_receipt_missing",
        }
    ]


def test_unsupported_allow_contract_remains_unknown(session_factory):
    append_autonomy_decision(
        action_id="future-action:1",
        action="future_high_risk_action",
        decision="allow",
        policy="autonomy_guard",
        risk_level="high",
        actor_class="system",
        source="future.worker",
        occurred_at=NOW,
        session_factory=session_factory,
    )

    result = run_autonomy_posthoc_audit(
        now=NOW + timedelta(seconds=2),
        session_factory=session_factory,
    )

    assert result["audited_count"] == 0
    assert result["incomplete"] == [
        {"action_id": "future-action:1", "reason": "unsupported_contract"}
    ]
