"""Typed I/O contracts shared by employee reports and meeting orchestration."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol

from sqlalchemy.orm import Session

JsonObject = dict[str, Any]
SessionProvider = Callable[[], Callable[[], Session]]
AllHandsProgressCallback = Callable[[JsonObject], Awaitable[None]]


class EmployeePairResolver(Protocol):
    def __call__(
        self, requested_ids: list[str] | None, *, max_employees: int
    ) -> list[tuple[str, str]]: ...


class EmployeeReport(Protocol):
    async def __call__(
        self,
        *,
        pkg_id: str,
        display_name: str,
        other_employees: list[str],
        user_id: int,
        bench_provider: str,
        bench_model: str,
        with_research: bool,
        user_question: str | None = None,
    ) -> JsonObject: ...


class AnswerSynthesizer(Protocol):
    async def __call__(
        self,
        *,
        user_question: str,
        employees: list[JsonObject],
        bench_provider: str,
        bench_model: str,
        user_id: int,
    ) -> JsonObject: ...


class StandbyReport(Protocol):
    async def __call__(
        self,
        *,
        pkg_id: str,
        display_name: str,
        task_text: str,
        inp: JsonObject,
        user_id: int,
        bench_provider: str,
        bench_model: str,
    ) -> tuple[str, str, int]: ...


class StandbyPolicy(Protocol):
    def __call__(self, pkg_id: str, *, user_question: str) -> bool: ...


class ResearchBuilder(Protocol):
    async def __call__(
        self,
        *,
        brief: str,
        intent: str,
        max_repos: int,
        max_chars: int,
        max_web: int,
        user_id: int,
        rate_limit_bucket: str | None = None,
    ) -> JsonObject: ...


class EmployeeExecutor(Protocol):
    def __call__(
        self,
        employee_id: str,
        task: str,
        input_data: JsonObject,
        user_id: int,
        *,
        bench_llm_override: tuple[str, str] | None = None,
    ) -> JsonObject: ...


class BenchDispatcher(Protocol):
    async def __call__(
        self,
        session: Session,
        user_id: int,
        provider: str,
        model: str,
        messages: list[JsonObject],
        *,
        max_tokens: int | None = None,
    ) -> JsonObject: ...


class ExcerptReader(Protocol):
    def __call__(self, row: JsonObject, *, max_chars: int = 800) -> str: ...
