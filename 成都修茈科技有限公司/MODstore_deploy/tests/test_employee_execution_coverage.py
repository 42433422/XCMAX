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
                    task="fresh success",
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
        result = get_execution_coverage(window_hours=24, _admin_user=admin)

    assert result["proven_count"] == 1
    assert result["employee_ids"] == ["quality-validator"]
    assert result["platform_llm"] == {
        "configured": True,
        "provider": "minimax",
        "model": "MiniMax-M2.7",
    }
    models._engine = None
    models._SessionFactory = None
