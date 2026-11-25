"""Read-only employee identity must bind the canonical virtual user, not role alone."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import AiEmployeeProfile, User
from app.db.models.employee_run_log import EmployeeRunLog
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_enterprise_projection import get, world  # noqa: F401


def test_employee_projection_refuses_misbound_virtual_user(world):
    service, sessions, _clock, _permissions = world
    with sessions() as db:
        db.add(
            User(
                id=10,
                username="ai-employee:another-employee",
                password="hash",
                tenant_id=11,
                role="ai_employee",
                is_active=True,
            )
        )
        db.commit()

    wrong = get(service, "employee", "employee-a", force_refresh=True)["state"]
    assert wrong["role"] is None and wrong["identity_active"] is None

    with sessions() as db:
        identity = db.get(User, 10)
        assert identity is not None
        identity.username = "ai-employee:employee-a"
        db.commit()
    bound = get(service, "employee", "employee-a", force_refresh=True)["state"]
    assert bound["role"] == "ai_employee"
    assert bound["identity_active"] is True

    with sessions() as db:
        identity = db.get(User, 10)
        assert identity is not None
        identity.is_active = False
        db.commit()
    stopped = get(service, "employee", "employee-a", force_refresh=True)["state"]
    assert stopped["role"] == "ai_employee"
    assert stopped["identity_active"] is False

    with sessions() as db:
        identity = db.get(User, 10)
        assert identity is not None
        identity.role = "user"
        db.commit()
    revoked = get(service, "employee", "employee-a", force_refresh=True)["state"]
    assert revoked["role"] is None
    assert revoked["identity_active"] is None
    with sessions() as db:
        profile = db.scalar(select(AiEmployeeProfile))
        assert profile is not None and profile.employee_id == "employee-a"


def test_employee_performance_is_scoped_persisted_and_not_business_acceptance(world):
    service, sessions, _clock, _permissions = world
    finished = datetime.now(UTC)
    with sessions() as db:
        for status, verified, ended in (
            ("success", 1, finished),
            ("completed", 1, finished),
            ("success", 0, finished),
            ("success", 1, None),
            ("failed", 0, finished),
            ("unknown", 1, finished),
            ("running", 0, None),
        ):
            db.add(
                EmployeeRunLog(
                    employee_id="employee-a",
                    tenant_id=11,
                    user_id=1,
                    status=status,
                    verified=verified,
                    finished_at=ended,
                )
            )
        db.add(
            EmployeeRunLog(
                employee_id="employee-a",
                tenant_id=11,
                user_id=3,
                status="success",
                verified=1,
                finished_at=finished,
            )
        )
        db.commit()
    with tenant_scope(22), sessions() as db:
        db.add(
            EmployeeRunLog(
                employee_id="employee-a",
                tenant_id=22,
                user_id=2,
                status="success",
                verified=1,
                finished_at=finished,
            )
        )
        db.commit()

    performance = get(service, "employee", "employee-a", force_refresh=True)["state"]["performance"]
    assert performance["status"] == "observed"
    assert performance["recorded_runs"] == 7
    assert performance["finished_terminal_counts"] == {"succeeded": 3, "failed": 1}
    assert performance["contract_verified_success_count"] == 2
    assert performance["unverified_success_count"] == 1
    assert performance["incomplete_terminal_count"] == 1
    assert performance["independent_business_verified"] is False
    assert performance["cost_attribution"] == "unknown"

    # A different Mod's audit records cannot be attributed through this scope.
    with sessions() as db:
        db.scalar(select(AiEmployeeProfile)).mod_id = "sales"
        db.commit()
    other = get(service, "employee", "employee-a", force_refresh=True)["state"]["performance"]
    assert other["status"] == "unknown"
    assert "recorded_runs" not in other
