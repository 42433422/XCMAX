"""SQLAlchemy implementation of UserRepository."""

from __future__ import annotations

from typing import Any

from app.application.ports.user_repository import UserRepository
from app.db.models import Permission, Role, User


class SQLAlchemyUserRepository(UserRepository):
    def find_by_username(self, db: Any, username: str) -> User | None:
        return db.query(User).filter(User.username == username).first()

    def find_by_id(self, db: Any, user_id: int) -> User | None:
        return db.query(User).filter(User.id == user_id).first()

    def list_users(self, db: Any, *, include_inactive: bool = False) -> list[User]:
        query = db.query(User)
        if not include_inactive:
            query = query.filter(User.is_active.is_(True))
        return query.order_by(User.created_at.desc()).all()

    def username_exists(self, db: Any, username: str) -> bool:
        return db.query(User).filter(User.username == username).first() is not None

    def add(self, db: Any, user: User) -> User:
        db.add(user)
        db.flush()
        db.refresh(user)
        return user

    def save(self, db: Any, user: User) -> User:
        db.flush()
        db.refresh(user)
        return user

    def touch_last_login(self, db: Any, user: User) -> None:
        from app.utils.time import utc_now_naive

        user.last_login = utc_now_naive()

    def list_permission_codes(self, db: Any, user: User) -> list[str]:
        if user.role == "admin":
            perms = db.query(Permission).all()
            return [p.code for p in perms]
        role = db.query(Role).filter(Role.name == user.role).first()
        if not role:
            return []
        return [p.code for p in role.permissions]
