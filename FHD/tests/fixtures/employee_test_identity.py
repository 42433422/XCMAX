"""Seed the real signed employee-test identity in an isolated database."""

from datetime import timedelta

from sqlalchemy.orm import sessionmaker

from app.db.db_base import Base
from app.db.models.permission import Permission, Role
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.utils.time import utc_now_naive


def seed_employee_identity(engine, *, session_id: str, username: str):
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        role = Role(name="admin")
        role.permissions.append(Permission(code="customer.view", name="查看客户"))
        db.add_all(
            [
                role,
                User(
                    id=11,
                    username=username,
                    password="unused",
                    tenant_id=11,
                    role="admin",
                    tier="enterprise",
                ),
            ]
        )
        db.flush()
        db.add(
            UserSession(
                session_id=session_id, user_id=11, expires_at=utc_now_naive() + timedelta(hours=1)
            )
        )
    return factory
