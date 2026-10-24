"""SQL profile adapter; the caller supplies an already validated mutation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol

from .ports import JsonObject

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.db.models.user import User


class ProfileRepository(Protocol):
    def find_identity(
        self, market_user_id: int, username: str
    ) -> tuple[User | None, User | None]: ...
    def save(self, user: User | None, market_user_id: int, values: JsonObject) -> JsonObject: ...
    def list_profiles(self) -> list[JsonObject]: ...


class SqlProfiles:
    def __init__(self, session: Session) -> None:
        self._db = session

    def find_identity(self, market_user_id: int, username: str) -> tuple[User | None, User | None]:
        from app.db.models.user import User

        return (
            self._db.query(User).filter(User.market_user_id == market_user_id).first(),
            self._db.query(User).filter(User.username == username).first(),
        )

    def save(self, user: User | None, market_user_id: int, values: JsonObject) -> JsonObject:
        from app.db.models.user import User

        if user is None:
            user = User(
                username=values["username"], password="", role="user", market_user_id=market_user_id
            )
            self._db.add(user)
            self._db.flush()
        else:
            user.market_user_id = market_user_id
        for name, value in values.items():
            setattr(user, name, value)
        self._db.commit()
        return {
            "market_user_id": market_user_id,
            "username": user.username,
            "tier": user.tier,
            "industry_id": user.industry_id,
            "account_tier": user.account_tier,
            "budget_range": user.budget_range,
            "entitled_industries": list(user.entitled_industries or []),
        }

    def list_profiles(self) -> list[JsonObject]:
        from app.db.models.user import User

        rows = self._db.query(
            User.market_user_id,
            User.username,
            User.tier,
            User.industry_id,
            User.account_tier,
            User.budget_range,
            User.entitled_industries,
        ).all()
        return [
            dict(
                zip(
                    (
                        "market_user_id",
                        "username",
                        "tier",
                        "industry_id",
                        "account_tier",
                        "budget_range",
                        "entitled_industries",
                    ),
                    (*row[:6], list(row[6] or [])),
                    strict=True,
                )
            )
            for row in rows
        ]


@contextmanager
def profile_repository() -> Iterator[ProfileRepository]:
    from app.db.session import get_db

    with get_db() as db:
        yield SqlProfiles(db)
