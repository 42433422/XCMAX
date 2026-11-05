"""Typed operation boundaries shared by desktop relay components."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, ParamSpec, Protocol, Self, TypeVar

import httpx

JsonObject = dict[str, Any]
ReadConfig = Callable[[], JsonObject]
WriteConfig = Callable[[JsonObject], None]
_Params = ParamSpec("_Params")
_Result = TypeVar("_Result")


def late_callback(resolve: Callable[[], Callable[_Params, _Result]]) -> Callable[_Params, _Result]:
    """Resolve an explicit callback at the call boundary without changing arguments."""

    def call(*args: _Params.args, **kwargs: _Params.kwargs) -> _Result:
        return resolve()(*args, **kwargs)

    return call


@dataclass(frozen=True)
class RelayBinding:
    relay_id: str
    desktop_token: str
    base_url: str

    @classmethod
    def from_config(cls, config: JsonObject, default_url: str) -> Self:
        return cls(
            str(config.get("relay_id") or "").strip(),
            str(config.get("desktop_token") or "").strip(),
            str(config.get("relay_base_url") or "").strip() or default_url,
        )

    @property
    def valid(self) -> bool:
        return bool(self.relay_id and self.desktop_token)


class ConditionalConfigUpdate(Protocol):
    def __call__(self, expected: RelayBinding, changes: JsonObject) -> JsonObject | None: ...


class ApiUrlCall(Protocol):
    def __call__(self, path: str, base_url: str | None = None) -> str: ...


class HttpClient(Protocol):
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
    def post(self, url: str, *, json: JsonObject) -> httpx.Response: ...


HttpClientFactory = Callable[[float], HttpClient]


class Worker(Protocol):
    def start(self) -> None: ...
    def is_alive(self) -> bool: ...
    def join(self, timeout: float | None = None) -> None: ...


WorkerFactory = Callable[[Callable[[], None], str], Worker]


class StopSignal(Protocol):
    def set(self) -> None: ...
    def clear(self) -> None: ...
    def is_set(self) -> bool: ...
    def wait(self, timeout: float | None = None) -> bool: ...


class CompletionCall(Protocol):
    def __call__(
        self, task: JsonObject, relay_id: str, desktop_token: str, base_url: str
    ) -> None: ...


class SuperEmployee(Protocol):
    def invoke(self, *, user_id: int, message: str, context: JsonObject) -> JsonObject: ...
    def list_messages(self, *, user_id: int, limit: int) -> list[JsonObject]: ...


SuperEmployeeFactory = Callable[[], SuperEmployee]


class TerminalMessageCall(Protocol):
    def __call__(
        self, messages: list[JsonObject], *, request_id: str, task_id: str
    ) -> JsonObject | None: ...


class ClassifyResultCall(Protocol):
    def __call__(self, row: JsonObject, *, message: str) -> tuple[bool, str, str]: ...


class PollBackoffCall(Protocol):
    def __call__(
        self, failure_count: int, *, base_interval: float, max_interval: float
    ) -> float: ...
