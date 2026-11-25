"""Role-permission changes and session revocation share one host DB transaction.

The rollback case guards against committing a privilege change while leaving an
already authenticated session usable after a failed invalidation.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.application.rbac_app_service import RbacAppService
from app.db.models import Permission, Role, User, UserSession, role_permissions
from app.utils.time import utc_now_naive


@pytest.fixture
def role_host(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "rbac-atomic.sqlite"))
    for table in (
        User.__table__,
        UserSession.__table__,
        Permission.__table__,
        Role.__table__,
        role_permissions,
    ):
        table.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as db:
        reader = Permission(code="elt.read", name="Read ELT")
        executor = Permission(code="elt.execute", name="Execute ELT")
        tenant_role = Role(name="tenant:7:worker", is_system=False, permissions=[reader])
        other_role = Role(name="tenant:8:worker", is_system=False, permissions=[reader])
        db.add_all([tenant_role, other_role, executor])
        db.flush()
        alice = User(
            username="atomic-alice",
            password="not-used",
            role=tenant_role.name,
            tenant_id=7,
        )
        bob = User(
            username="atomic-bob",
            password="not-used",
            role=other_role.name,
            tenant_id=8,
        )
        db.add_all([alice, bob])
        db.flush()
        db.add_all(
            [
                UserSession(
                    user_id=alice.id,
                    session_id="alice-before-role-revocation",
                    expires_at=utc_now_naive() + timedelta(hours=1),
                ),
                UserSession(
                    user_id=bob.id,
                    session_id="bob-other-tenant",
                    expires_at=utc_now_naive() + timedelta(hours=1),
                ),
            ]
        )
        role_id, alice_id, bob_id = tenant_role.id, alice.id, bob.id
    monkeypatch.setattr("app.db.HostSessionLocal", factory)
    yield engine, factory, role_id, alice_id, bob_id
    engine.dispose()


def _readback(factory, role_id: int):
    with factory() as db:
        role = db.query(Role).filter(Role.id == role_id).one()
        codes = {p.code for p in role.permissions}
        sessions = {s.session_id for s in db.query(UserSession).all()}
        return codes, sessions


def test_permission_update_revokes_only_matching_role_sessions(role_host):
    _engine, factory, role_id, _alice_id, _bob_id = role_host
    result = RbacAppService().update_role(
        role_id, permissions=["elt.execute"], tenant_id=7
    )
    assert result["sessions_revoked"] == 1
    assert {item["code"] for item in result["permissions"]} == {"elt.execute"}
    assert _readback(factory, role_id) == (
        {"elt.execute"},
        {"bob-other-tenant"},
    )


def test_failed_session_delete_rolls_back_permission_change(role_host):
    engine, factory, role_id, _alice_id, _bob_id = role_host

    def fail_session_delete(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().lower().startswith("delete from sessions"):
            raise RuntimeError("forced session revocation failure")

    event.listen(engine, "before_cursor_execute", fail_session_delete)
    try:
        with pytest.raises(RuntimeError, match="forced session revocation failure"):
            RbacAppService().update_role(
                role_id, permissions=["elt.execute"], tenant_id=7
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_session_delete)

    assert _readback(factory, role_id) == (
        {"elt.read"},
        {"alice-before-role-revocation", "bob-other-tenant"},
    )


def test_role_assignment_and_session_revocation_share_host_transaction(role_host):
    engine, factory, _role_id, alice_id, _bob_id = role_host
    # Revocation failure must not persist a role assignment, either.
    def fail_session_delete(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().lower().startswith("delete from sessions"):
            raise RuntimeError("forced session revocation failure")

    event.listen(engine, "before_cursor_execute", fail_session_delete)
    try:
        with pytest.raises(RuntimeError, match="forced session revocation failure"):
            RbacAppService().assign_user_role(alice_id, "tenant:8:worker", tenant_id=None)
    finally:
        event.remove(engine, "before_cursor_execute", fail_session_delete)

    with factory() as db:
        assert db.query(User).filter(User.id == alice_id).one().role == "tenant:7:worker"
        assert (
            db.query(UserSession)
            .filter(UserSession.user_id == alice_id)
            .count()
            == 1
        )
