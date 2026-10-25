"""Typed ports for group persistence, employee adapters and message workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

Row = dict[str, Any]
Rows = list[Row]


class SuperEmployee(Protocol):
    def invoke(self, *, user_id: int, message: str, context: Row | None = None) -> Row: ...
    def list_messages(self, *, user_id: int, limit: int = 200) -> Rows: ...


class MobileRelay(Protocol):
    def list_desktops(self, *, user_id: int) -> Rows: ...
    def create_task(
        self, *, user_id: int, relay_id: str, kind: str, payload: Row
    ) -> Row | None: ...
    def get_task(self, *, user_id: int, task_id: str) -> Row | None: ...


class ResolveGroup(Protocol):
    def __call__(self, *, user_id: int, group_id: str) -> str: ...


class MessageFactory(Protocol):
    def __call__(
        self,
        *,
        user_id: int,
        group_id: str,
        role: str,
        sender_id: str,
        sender_name: str,
        sender_avatar: str,
        body: str,
        kind: str = "chat",
        status: str = "",
        work_order_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class SyncProgress(Protocol):
    def __call__(self, *, user_id: int, group_id: str) -> None: ...


class GetMessages(Protocol):
    def __call__(
        self, *, user_id: int, group_id: str, limit: int = 100
    ) -> list[dict[str, Any]]: ...


class AiReply(Protocol):
    async def __call__(
        self,
        group: dict[str, Any],
        member: dict[str, Any],
        history: list[dict[str, Any]],
        *,
        user_id: int,
    ) -> str: ...


class SuperDiscussionReply(Protocol):
    async def __call__(
        self,
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        history: list[dict[str, Any]],
        discussion_turns: list[dict[str, str]],
        round_index: int,
    ) -> str: ...


class RouteDiscussion(Protocol):
    async def __call__(
        self,
        *,
        group: dict[str, Any],
        task: str,
        candidates: list[dict[str, Any]],
        discussion_turns: list[dict[str, str]],
        mentions: list[str] | None,
    ) -> tuple[list[dict[str, Any]], str]: ...


class RunDiscussion(Protocol):
    async def __call__(
        self,
        *,
        group: dict[str, Any],
        task: str,
        candidates: list[dict[str, Any]],
        user_id: int,
        history: list[dict[str, Any]],
        mentions: list[str] | None,
        persist: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...


class DispatchWork(Protocol):
    async def __call__(
        self,
        *,
        group: dict[str, Any],
        members: list[dict[str, Any]],
        task: str,
        user_id: int,
        sender_name: str,
        branch_context: str = "",
        persist: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...


class ExecuteWork(Protocol):
    async def __call__(
        self,
        *,
        group: dict[str, Any],
        member: dict[str, Any],
        task: str,
        assigned_task: str,
        assignment_focus: str,
        work_order_id: str,
        user_id: int,
        sender_name: str,
        branch_context: str = "",
    ) -> dict[str, Any]: ...


class InvokeSuperTask(Protocol):
    def __call__(
        self, *, employee_id: str, task: str, input_data: dict[str, Any], user_id: int
    ) -> dict[str, Any]: ...


class CreateRelayTask(Protocol):
    def __call__(
        self, *, employee_id: str, task: str, input_data: dict[str, Any], user_id: int
    ) -> dict[str, Any] | None: ...


class AppendReport(Protocol):
    def __call__(self, *, task: dict[str, Any]) -> dict[str, Any] | None: ...


class AppendFollowup(Protocol):
    def __call__(self, *, user_id: int, group_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class GroupStore:
    all: Callable[[], Rows]
    for_user: Callable[[int], Rows]
    append: Callable[[Row], None]
    rewrite: Callable[[Rows], None]
    resolve: ResolveGroup
    compact: Callable[[], None]


@dataclass(frozen=True)
class MessageStore:
    read: Callable[[], Rows]
    append: Callable[[Rows], None]
    rewrite: Callable[[Rows], None]
    previews: Callable[[int], dict[str, Row]]


@dataclass(frozen=True)
class EmployeeProviders:
    relay: Callable[[], MobileRelay]
    super_employee: Callable[[str], SuperEmployee]


@dataclass(frozen=True)
class DirectoryActions:
    seed: Callable[[int], Rows]
    backfill: Callable[[Rows], None]


@dataclass(frozen=True)
class ProgressSources:
    relay: SyncProgress
    super_employee: SyncProgress


@dataclass(frozen=True)
class ConversationActions:
    history: GetMessages
    reply: AiReply
    discuss: RunDiscussion
    dispatch: DispatchWork
    followup: AppendFollowup
