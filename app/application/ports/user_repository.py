"""User and auth persistence port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.db.models import User


class UserRepository(ABC):
    @abstractmethod
    def find_by_username(self, db: Any, username: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def find_by_id(self, db: Any, user_id: int) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def list_users(self, db: Any, *, include_inactive: bool = False) -> list[User]:
        raise NotImplementedError

    @abstractmethod
    def username_exists(self, db: Any, username: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def add(self, db: Any, user: User) -> User:
        raise NotImplementedError

    @abstractmethod
    def save(self, db: Any, user: User) -> User:
        raise NotImplementedError

    @abstractmethod
    def touch_last_login(self, db: Any, user: User) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_permission_codes(self, db: Any, user: User) -> list[str]:
        raise NotImplementedError
