from __future__ import annotations

from datetime import datetime, timezone

import modstore_server.models as models
from modstore_server.admin_employee_autonomy_api import get_execution_coverage


def test_execution_coverage_counts_only_fresh_successful_roster_receipts(
    tmp_path, monkeypatch
) -> None:
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "coverage.sqlite"))
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BENCH_PROVIDER", "minimax")
    monkeypatch.setenv("MODSTORE_EMPLOYEE_BENCH_MODEL", "MiniMax-M2.7")
    monkeypatch.setenv("MINIMAX_API_KEY", "sk-test")
    models.init_db()
    sf = models.get_session_factory()
    with sf() as session:
        admin = models.User(
            username="coverage-admin",
            password_hash="x",
            email="coverage@example.com",
            is_admin=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        session.add_all(
            [
                models.EmployeeExecutionMetric(
                    user_id=admin.id,
                    employee_id="quality-validator",
                    task="[duty-burn-in:run-1:quality-validator]",
                    status="success",
                    created_at=datetime.now(timezone.utc),
                ),
                models.EmployeeExecutionMetric(
                    user_id=admin.id,
                    employee_id="payment-billing-reconciler",
                    task="reconcile production billing",
                    status="success",
                    created_at=datetime.now(timezone.utc),
                ),
                models.EmployeeExecutionMetric(
                    user_id=admin.id,
                    employee_id="dbops-engineer",
                    task="fresh failure",
                    status="handler_failed",
                    created_at=datetime.now(timezone.utc),
                ),
                models.EmployeeExecutionMetric(
                    user_id=admin.id,
                    employee_id="not-in-duty-roster",
                    task="irrelevant success",
                    status="success",
                    created_at=datetime.now(timezone.utc),
                ),
            ]
        )
        session.commit()
        admin_id = int(admin.id)

    with sf() as session:
        admin = session.get(models.User, admin_id)
        result = get_execution_coverage(
            window_hours=24,
            production_window_hours=720,
            _admin_user=admin,
        )

    assert result["proven_count"] == 2
    assert result["employee_ids"] == ["payment-billing-reconciler", "quality-validator"]
    assert result["burn_in_proven_count"] == 1
    assert result["burn_in_employee_ids"] == ["quality-validator"]
    assert result["production_proven_count"] == 1
    assert result["production_employee_ids"] == ["payment-billing-reconciler"]
    assert len(result["planned_employee_ids"]) == result["planned_count"]
    assert "quality-validator" not in result["unproven_employee_ids"]
    assert "payment-billing-reconciler" not in result["unproven_employee_ids"]
    assert "quality-validator" not in result["burn_in_unproven_employee_ids"]
    assert "payment-billing-reconciler" in result["burn_in_unproven_employee_ids"]
    assert "payment-billing-reconciler" not in result["production_unproven_employee_ids"]
    assert "quality-validator" in result["production_unproven_employee_ids"]
    assert result["assigned_count"] == result["planned_count"] == 55
    assert result["assignment_required_count"] == 53
    assert result["proof_required_count"] == 44
    assert result["assignment_ratio"] == 1.0
    assert result["proof_ratio"] == round(2 / 55, 4)
    assert result["burn_in_proof_ratio"] == round(1 / 55, 4)
    assert result["production_proof_ratio"] == round(1 / 55, 4)
    assert result["shell_count"] == 0
    assert result["shell_employee_ids"] == []
    assert result["workforce_ready"] is False
    assert result["production_workforce_ready"] is False
    assert result["platform_llm"] == {
        "configured": True,
        "provider": "minimax",
        "model": "MiniMax-M2.7",
    }
    models._engine = None
    models._SessionFactory = None
