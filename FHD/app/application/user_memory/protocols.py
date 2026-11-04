"""Typed capabilities used by memory operations, without a service back-reference."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import wraps
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar

from app.application.user_memory.models import UserMemory

JsonObject = dict[str, Any]
_Params = ParamSpec("_Params")
_Result = TypeVar("_Result")


def late_callback(resolve: Callable[[], Callable[_Params, _Result]]) -> Callable[_Params, _Result]:
    def call(*args: _Params.args, **kwargs: _Params.kwargs) -> _Result:
        return resolve()(*args, **kwargs)

    return call


class MemoryStore(Protocol):
    def transaction(self) -> AbstractContextManager[None]: ...
    def get_memory(self, user_id: str) -> UserMemory | None: ...
    def save_memory(self, user_id: str, memory: UserMemory) -> None: ...


@dataclass(frozen=True)
class MemoryAccess:
    transaction: Callable[[], AbstractContextManager[None]]
    get_memory: Callable[[str], UserMemory | None]
    save_memory: Callable[[str, UserMemory], None]
    new_memory: Callable[[str], UserMemory]
    now: Callable[[], str]


class MemoryOperation(Protocol):
    access: MemoryAccess


_Operation = TypeVar("_Operation", bound=MemoryOperation)


def memory_transaction(
    method: Callable[Concatenate[_Operation, str, _Params], _Result],
) -> Callable[Concatenate[_Operation, str, _Params], _Result]:
    @wraps(method)
    def wrapped(
        self: _Operation, user_id: str, *args: _Params.args, **kwargs: _Params.kwargs
    ) -> _Result:
        with self.access.transaction():
            return method(self, user_id, *args, **kwargs)

    return wrapped


class PreferenceLookup(Protocol):
    def __call__(self, user_id: str, key: str, default: Any = None) -> Any: ...


class MemoryListing(Protocol):
    def __call__(
        self, user_id: str, *, status: str | None = None, memory_type: str | None = None
    ) -> list[JsonObject]: ...


class CandidateGovernance(Protocol):
    def __call__(
        self, *, source: str, confidence: float, evidence: list[JsonObject] | None
    ) -> JsonObject: ...


class CandidateProposal(Protocol):
    def __call__(
        self,
        user_id: str,
        memory_type: str,
        key: str,
        value: Any,
        *,
        source: str = "agent_observation",
        confidence: float = 0.5,
        evidence: list[JsonObject] | None = None,
    ) -> JsonObject: ...


class MemoryStatusUpdate(Protocol):
    def __call__(
        self, user_id: str, memory_id: str, status: str, *, reason: str = ""
    ) -> JsonObject: ...
