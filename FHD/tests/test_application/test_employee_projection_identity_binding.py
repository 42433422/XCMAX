"""Read-only employee identity must bind the canonical virtual user, not role alone."""

from __future__ import annotations

from sqlalchemy import select

from app.db.models import AiEmployeeProfile, User
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
