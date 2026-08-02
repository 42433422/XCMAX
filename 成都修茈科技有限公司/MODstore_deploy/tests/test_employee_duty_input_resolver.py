from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from modstore_server import employee_duty_filesystem_inputs as filesystem_inputs
from modstore_server import employee_duty_input_resolver as resolver
from modstore_server.employee_duty_cron_runtime import execute_employee_cron_duty

NOW = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)


def _rows_for(statement: str, _parameters=None) -> list[dict]:
    if "FROM knowledge_documents" in statement:
        return [
            {
                "doc_id": "private-doc-id",
                "size_bytes": 128,
                "chunk_count": 2,
                "created_at": "2026-08-01 01:00:00",
            }
        ]
    if "FROM customer_value_receipts" in statement:
        return []
    if "FROM author_earnings" in statement:
        return [
            {
                "order_id": "real-order-9",
                "author_id": 42,
                "gross": "100.00",
                "platform_fee_rate": "0.3000",
                "net": "70.00",
                "status": "settled",
            }
        ]
    if "FROM users" in statement and "SELECT id, created_at" in statement:
        return [{"id": 1504, "created_at": "2026-06-05 09:27:11"}]
    if "FROM transactions" in statement and "user_id IN" in statement:
        return [
            {
                "user_id": 1504,
                "txn_type": "alipay_wallet",
                "status": "completed",
                "created_at": "2026-07-31 02:00:00",
            }
        ]
    if "FROM purchases" in statement and "user_id IN" in statement:
        return [
            {
                "user_id": 1504,
                "amount": "8.88",
                "created_at": "2026-07-30 02:00:00",
            }
        ]
    if "FROM llm_call_logs" in statement:
        return []
    if "FROM purchases" in statement:
        return [{"id": 7, "amount": "8.88"}]
    if "txn_type = 'alipay_wallet'" in statement:
        return [{"id": 8, "amount": "8.88"}]
    if "LIKE '%refund%'" in statement:
        return [{"id": 9, "amount": "1.23"}]
    raise AssertionError(f"unexpected query: {statement}")


@pytest.fixture
def receipts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "duty-input.jsonl"
    monkeypatch.setenv("MODSTORE_DUTY_INPUT_RECEIPT_FILE", str(path))
    monkeypatch.setattr(resolver, "_query_rows", _rows_for)
    return path


def test_knowledge_input_is_real_but_pseudonymous(receipts: Path) -> None:
    result = resolver.resolve_employee_duty_input("doc-knowledge-curator", now=NOW)

    assert result is not None
    fact = result["input_data"]["facts"][0]
    assert fact["verified"] is True
    assert fact["source"].startswith("database://knowledge_documents/knowledge-document-")
    assert "private-doc-id" not in json.dumps(result, ensure_ascii=False)
    assert result["receipt"]["row_count"] == 1
    assert json.loads(receipts.read_text().splitlines()[-1])["status"] == "data"


def test_authoritative_empty_delivery_is_audited_as_no_data(receipts: Path) -> None:
    result = resolver.resolve_employee_duty_input("ecosystem-delivery-reporter", now=NOW)

    assert result is not None
    assert result["input_data"]["deliveries"] == []
    assert result["receipt"]["status"] == "no_data"
    assert result["receipt"]["sources"] == ["customer_value_receipts"]
    assert receipts.exists()


def test_delivery_status_comes_from_receipt_evidence_not_a_default(
    receipts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        resolver,
        "_query_rows",
        lambda _statement, _parameters=None: [
            {
                "receipt_id": "receipt-1",
                "customer_ref": "customer-private",
                "source_employee_id": "delivery-receipt-officer",
                "evidence_json": json.dumps(
                    {"sla_status": "breached", "next_step": "escalate owner"}
                ),
                "occurred_at": "2026-08-01 02:00:00",
            },
            {
                "receipt_id": "receipt-2",
                "customer_ref": "customer-private-2",
                "source_employee_id": "delivery-receipt-officer",
                "evidence_json": "{}",
                "occurred_at": "2026-08-01 03:00:00",
            },
        ],
    )

    result = resolver.resolve_employee_duty_input("ecosystem-delivery-reporter", now=NOW)

    assert result is not None
    deliveries = result["input_data"]["deliveries"]
    assert deliveries[0]["sla_status"] == "breached"
    assert deliveries[0]["next_step"] == "escalate owner"
    assert deliveries[1]["sla_status"] == ""
    assert "customer-private" not in json.dumps(deliveries, ensure_ascii=False)


def test_revenue_share_uses_recorded_author_ledger(receipts: Path) -> None:
    result = resolver.resolve_employee_duty_input("ecosystem-revenue-share-reconciler", now=NOW)

    assert result is not None
    entry = result["input_data"]["entries"][0]
    assert entry["gross_cents"] == 10_000
    assert entry["share_bps"] == 7_000
    assert entry["recorded_share_cents"] == 7_000
    assert entry["partner_id"].startswith("author-")
    assert "real-order-9" not in json.dumps(result, ensure_ascii=False)


def test_enterprise_adoption_uses_activity_without_pii(receipts: Path) -> None:
    result = resolver.resolve_employee_duty_input("enterprise-adoption-officer", now=NOW)

    assert result is not None
    tenant = result["input_data"]["tenants"][0]
    assert tenant["tenant_id"].startswith("enterprise-tenant-")
    assert tenant["active_days_30"] == 2
    assert tenant["adopted_features"] == ["billing_wallet", "modstore_purchase"]
    assert tenant["value_milestones"] == ["paid_catalog_purchase"]
    assert "1504" not in json.dumps(tenant, ensure_ascii=False)


def test_payment_input_reconciles_only_payment_domain_rows(receipts: Path) -> None:
    result = resolver.resolve_employee_duty_input("payment-billing-reconciler", now=NOW)

    assert result is not None
    ledger = result["input_data"]["ledger"]
    assert ledger["orders"][0]["amount_cents"] == 888
    assert ledger["payments"][0]["amount_cents"] == 888
    assert ledger["refunds"][0]["amount_cents"] == 123
    assert result["receipt"]["row_count"] == 3


def test_interview_input_uses_reviewed_role_contract(
    receipts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        filesystem_inputs,
        "_reviewed_candidate",
        lambda _now, **_kwargs: (
            "real-role",
            {
                "dependencies": {"xcagi": ">=1"},
                "employee_config_v2": {
                    "actions": {
                        "handlers": ["direct_python"],
                        "direct_python": {"action": "inspect"},
                    }
                },
            },
            {"mission": "inspect the real role", "risk_level": "low"},
        ),
    )

    result = resolver.resolve_employee_duty_input("employee-interview-assistant", now=NOW)

    assert result is not None
    assert result["input_data"]["target_employee_id"] == "real-role"
    assert result["input_data"]["role_context"] == {
        "mission": "inspect the real role",
        "capabilities": ["direct_python", "inspect"],
        "dependencies": ["xcagi"],
        "risk_level": "low",
        "handlers": ["direct_python"],
    }
    assert result["receipt"]["sources"] == [
        "reviewed_duty_manifest_ssot",
        "duty_employee_work_contracts",
    ]


def test_quality_validator_indexes_actual_pack_files(
    receipts: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fhd_root = tmp_path / "FHD"
    config_path = fhd_root / "config" / "duty_employee_work_contracts.json"
    pack_root = fhd_root / "mods" / "_employees" / "real-role"
    (pack_root / "backend" / "employees").mkdir(parents=True)
    (pack_root / "manifest.json").write_text("{}", encoding="utf-8")
    (pack_root / "backend" / "employees" / "real_role.py").write_text(
        "def run(): pass\n", encoding="utf-8"
    )
    manifest = {
        "id": "real-role",
        "employee_config_v2": {"actions": {"handlers": ["direct_python"]}},
    }
    monkeypatch.setattr(
        filesystem_inputs,
        "_reviewed_candidate",
        lambda _now, **_kwargs: ("real-role", manifest, {}),
    )
    monkeypatch.setattr(
        "modstore_server.duty_workforce_contracts.resolve_work_contracts_path",
        lambda: config_path,
    )

    result = resolver.resolve_employee_duty_input("quality-validator", now=NOW)

    assert result is not None
    assert result["input_data"]["pack"]["manifest"] == manifest
    assert result["input_data"]["pack"]["files"] == [
        "backend/employees/real_role.py",
        "manifest.json",
    ]
    assert result["receipt"]["row_count"] == 2


def test_architecture_input_extracts_real_python_dependency_graph(
    receipts: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package_root = tmp_path / "modstore_server"
    (package_root / "api").mkdir(parents=True)
    (package_root / "services").mkdir(parents=True)
    resolver_file = package_root / "employee_duty_filesystem_inputs.py"
    resolver_file.write_text("", encoding="utf-8")
    (package_root / "services" / "orders.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package_root / "api" / "orders.py").write_text(
        "from modstore_server.services import orders\n", encoding="utf-8"
    )
    monkeypatch.setattr(filesystem_inputs, "__file__", str(resolver_file))

    result = resolver.resolve_employee_duty_input("top-architect", now=NOW)

    assert result is not None
    architecture = result["input_data"]["architecture"]
    assert {
        "source": "modstore_server.api.orders",
        "target": "modstore_server.services.orders",
    } in architecture["dependencies"]
    assert {item["layer"] for item in architecture["modules"]} >= {
        "application",
        "interface",
        "infrastructure",
    }
    assert result["receipt"]["sources"] == [
        "modstore_server_python_source_tree",
        "architecture_dependency_policy_v1",
    ]


def test_legacy_archive_input_uses_immutable_release_manifest(
    receipts: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = tmp_path / ".xcmax-release.json"
    manifest.write_text(
        json.dumps({"git_sha": "a" * 40, "release_id": "a" * 40}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MODSTORE_RELEASE_MANIFEST", str(manifest))

    result = resolver.resolve_employee_duty_input("legacy-archive-curator", now=NOW)

    assert result is not None
    inventory = result["input_data"]["inventory"]
    assert inventory[0]["path"] == f"releases/{'a' * 40}"
    assert inventory[0]["referenced_by"] == ["current"]
    assert inventory[0]["recovery_path"] == f"git:{'a' * 40}"
    assert result["receipt"]["sources"] == ["immutable_release_manifest"]


def test_investor_portal_input_uses_public_scorecard_only(
    receipts: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    projection = {
        "dimensions": [
            {"id": "code", "progress": 100, "next_gap": "keep proving"},
            {"id": "customer", "progress": 25, "next_gap": "real payment"},
        ]
    }
    (tmp_path / "download-founder-autonomy.json").write_text(
        json.dumps(projection), encoding="utf-8"
    )
    monkeypatch.setenv("XCMAX_PUBLIC_SITE_STATE_DIR", str(tmp_path))

    result = resolver.resolve_employee_duty_input("ecosystem-investor-portal-officer", now=NOW)

    assert result is not None
    assert result["input_data"]["milestones"] == [
        {
            "id": "code",
            "status": "complete",
            "progress_pct": 100.0,
            "evidence_ref": "public-founder-autonomy:code",
        },
        {
            "id": "customer",
            "status": "in_progress",
            "progress_pct": 25.0,
            "evidence_ref": "public-founder-autonomy:customer",
        },
    ]
    assert result["input_data"]["risks"] == [
        {
            "id": "gap-customer",
            "severity": "high",
            "status": "open",
            "mitigation": "real payment",
        }
    ]


def test_llm_ops_input_is_local_and_secret_free(
    receipts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        resolver,
        "_query_rows",
        lambda _statement, _parameters=None: [
            {
                "provider": "minimax",
                "model": "MiniMax-M2.7",
                "status": "success",
                "total_tokens": 321,
                "created_at": NOW,
            }
        ],
    )
    monkeypatch.setattr(
        "modstore_server.services.llm.resolve_platform_bench_llm",
        lambda: ("minimax", "MiniMax-M2.7"),
    )
    monkeypatch.setattr(
        "modstore_server.llm_key_resolver.platform_api_key",
        lambda _provider: "must-never-appear",
    )
    monkeypatch.setattr(
        "modstore_server.duty_roster.all_planned_employee_ids",
        lambda: ["llm-ops-engineer"],
    )

    result = resolver.resolve_employee_duty_input("llm-ops-engineer", now=NOW)

    assert result is not None
    snapshot = result["input_data"]["llm_ops_snapshot"]
    assert snapshot["secrets_redacted"] is True
    assert snapshot["providers"][0]["health"] == "healthy"
    assert snapshot["current_route"] == {
        "provider": "minimax",
        "model": "MiniMax-M2.7",
    }
    assert "must-never-appear" not in json.dumps(result, ensure_ascii=False)
    assert result["receipt"]["sources"] == [
        "llm_call_logs",
        "platform_runtime_route",
        "duty_roster",
    ]


def test_unsupported_employee_preserves_existing_execution_path(receipts: Path) -> None:
    assert resolver.resolve_employee_duty_input("unmapped-employee", now=NOW) is None
    assert not receipts.exists()


def test_receipt_ledger_rotates_before_growth(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "duty-input.jsonl"
    path.write_text("old\n", encoding="utf-8")
    monkeypatch.setenv("MODSTORE_DUTY_INPUT_RECEIPT_FILE", str(path))
    monkeypatch.setattr(resolver, "_receipt_max_bytes", lambda: 1)

    resolver._append_receipt({"schema": "test", "status": "data"})

    assert path.with_suffix(".jsonl.1").read_text(encoding="utf-8") == "old\n"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "data"


def test_cron_execution_injects_resolved_input_and_returns_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}
    tracked = []

    @contextmanager
    def fake_track(job_id):
        tracked.append(job_id)
        yield

    receipt = {
        "schema": "xcagi.employee_duty_input_receipt/v1",
        "employee_id": "payment-billing-reconciler",
        "status": "data",
        "row_count": 1,
    }
    monkeypatch.setattr(
        "modstore_server.employee_duty_input_resolver.resolve_employee_duty_input",
        lambda _employee_id: {
            "input_data": {
                "ledger": {"orders": [], "payments": [], "refunds": []},
                "_duty_input_receipt": receipt,
            },
            "receipt": receipt,
        },
    )
    monkeypatch.setattr("modstore_server.scheduler_runtime.track_job_run", fake_track)
    monkeypatch.setattr(
        "modstore_server.services.llm.resolve_platform_bench_llm", lambda: ("p", "m")
    )

    def fake_execute(employee_id, task, input_data, user_id=0, **kwargs):
        captured.update(
            employee_id=employee_id,
            task=task,
            input_data=input_data,
            user_id=user_id,
            kwargs=kwargs,
        )
        return {"ok": True, "status": "no_data"}

    monkeypatch.setattr("modstore_server.employee_executor.execute_employee_task", fake_execute)

    result = execute_employee_cron_duty(
        employee_id="payment-billing-reconciler",
        task_brief="reconcile",
        work_contract={"risk_level": "low", "acceptance": ["receipt"]},
        schedule_source="duty_work_contract",
        project_root="",
    )

    assert tracked == ["employee_cron:payment-billing-reconciler"]
    assert captured["input_data"]["ledger"]["orders"] == []
    assert captured["input_data"]["_duty_input_receipt"] == receipt
    assert result["status"] == "no_data"
    assert result["duty_input_receipt"] == receipt


def test_retention_cron_uses_bounded_dry_run_instead_of_unapproved_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracked = []
    calls = []

    @contextmanager
    def fake_track(job_id):
        tracked.append(job_id)
        yield

    monkeypatch.setattr("modstore_server.scheduler_runtime.track_job_run", fake_track)
    monkeypatch.setattr(
        "modstore_server.services.llm.resolve_platform_bench_llm", lambda: ("p", "m")
    )

    def fake_retention(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "status": "success", "report_md": "dry-run receipt"}

    monkeypatch.setattr(
        "modstore_server.file_retention_janitor.run_retention_janitor",
        fake_retention,
    )
    monkeypatch.setattr(
        "modstore_server.employee_executor.execute_employee_task",
        lambda *_args, **_kwargs: pytest.fail("generic employee executor must not run"),
    )

    result = execute_employee_cron_duty(
        employee_id="retention-officer",
        task_brief="audit retention",
        work_contract={"risk_level": "medium"},
        schedule_source="duty_work_contract",
        project_root="",
    )

    assert tracked == ["employee_cron:retention-officer"]
    assert calls == [{"dry_run": True, "notification_dry_run": True}]
    assert result["handler"] == "file_retention_janitor"
    assert result["read_only"] is True
