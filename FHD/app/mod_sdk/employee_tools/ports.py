"""Small, typed inputs for each independently usable employee tool family."""

from __future__ import annotations

import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import httpx

Payload = dict[str, Any]
Tool = Callable[[Payload, Payload], Awaitable[Payload]]


class RunCommand(Protocol):
    async def __call__(
        self,
        args: list[str],
        *,
        cwd: str | Path | None = None,
        timeout: int = 120,
        env: dict[str, str] | None = None,
    ) -> Payload: ...


class RunScript(Protocol):
    async def __call__(self, script: str | Path, *args: str, **kwargs: Any) -> Payload: ...


class ApiCall(Protocol):
    async def __call__(
        self, method: str, path: str, *, api_base: str | None = None, **kwargs: Any
    ) -> Payload: ...


class AsyncClientFactory(Protocol):
    def __call__(self, *, timeout: float) -> httpx.AsyncClient: ...


class WriteGate(Protocol):
    async def __call__(
        self, employee_id: str, tool_name: str, params: Payload, ctx: Payload
    ) -> Payload: ...


@dataclass(frozen=True)
class QualityPorts:
    root: Path
    scripts: Path
    python: str
    run: RunCommand
    script: RunScript


@dataclass(frozen=True)
class ReleasePorts:
    root: Path
    run: RunCommand


@dataclass(frozen=True)
class WorkspacePorts:
    root: Path
    run: RunCommand


@dataclass(frozen=True)
class StatusPorts:
    api_base: str
    request: ApiCall


@dataclass(frozen=True)
class EmployeeFiles:
    packs: Path
    roster: Path


@dataclass(frozen=True)
class Configuration:
    root: Path
    profiles: list[Payload]
    env_keys: tuple[str, ...]
    secret_keys: frozenset[str]


@dataclass(frozen=True)
class ProviderPorts:
    profiles: list[Payload]
    client: AsyncClientFactory | None


@dataclass(frozen=True)
class ModelCatalog:
    prices: list[Payload]


@dataclass(frozen=True)
class CursorPorts:
    home: Path
    which: Callable[[str], str | None]
    run: Callable[..., subprocess.CompletedProcess[str]]
    get: Callable[..., httpx.Response]


@dataclass(frozen=True)
class TraePorts:
    home: Path
    get: Callable[..., httpx.Response]


@dataclass(frozen=True)
class DispatchPorts:
    registry: dict[str, Tool]
    allowed: Callable[[str], list[str]]
    write_tools: Callable[[], frozenset[str]]
    write_gate: WriteGate
