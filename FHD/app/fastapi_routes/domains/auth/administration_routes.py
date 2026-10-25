"""Permission-gated administration of user accounts."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Body, Depends, Query, Request

from app.db.models.user import User
from app.domain.auth.ports import JsonObject

from .user_administration import UserAdministration


class AdministrationRoutes:
    """Permission-gated administration of user accounts."""

    def __init__(
        self, *, users: Callable[[], UserAdministration], require_admin: Callable[[Request], User]
    ) -> None:
        router = self.router = APIRouter()

        @router.get("/api/users", response_model=None)
        def users_list(
            include_inactive: str = Query(default="false"), _user: User = Depends(require_admin)
        ) -> object:
            return users().list(include_inactive, _user)

        self.users_list = users_list

        @router.get("/api/users/{user_id}", response_model=None)
        def users_get(user_id: int, _user: User = Depends(require_admin)) -> object:
            return users().get(user_id, _user)

        self.users_get = users_get

        @router.post("/api/users", response_model=None)
        def users_create(
            body: JsonObject = Body(default_factory=dict), _user: User = Depends(require_admin)
        ) -> object:
            return users().create(body, _user)

        self.users_create = users_create

        @router.put("/api/users/{user_id}", response_model=None)
        def users_update(
            user_id: int,
            body: JsonObject = Body(default_factory=dict),
            _user: User = Depends(require_admin),
        ) -> object:
            return users().update(user_id, body, _user)

        self.users_update = users_update

        @router.delete("/api/users/{user_id}", response_model=None)
        def users_delete(user_id: int, user: User = Depends(require_admin)) -> object:
            return users().delete(user_id, user)

        self.users_delete = users_delete

        @router.post("/api/users/{user_id}/reset-password", response_model=None)
        def users_reset_password(
            user_id: int,
            body: JsonObject = Body(default_factory=dict),
            _user: User = Depends(require_admin),
        ) -> object:
            return users().reset_password(user_id, body, _user)

        self.users_reset_password = users_reset_password
