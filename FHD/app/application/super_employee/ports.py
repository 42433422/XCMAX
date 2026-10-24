"""Typed, bounded capabilities used by super-employee components.

Adapters receive functions for the effects they own. No component depends on
the public service, and callback adapters preserve existing override seams.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.application.execution_scope import CapabilityGrant
from app.application.workspaces import WorkspaceRegistry

JsonObject = dict[str, Any]
CliResult = tuple[int, str, str, str]
CliRunner = Callable[..., subprocess.CompletedProcess[str]]
IdleRunner = Callable[[list[str], str, float, float], CliResult]


@dataclass
class ExecutionContext:
    grant: CapabilityGrant = field(default_factory=CapabilityGrant.product)
    relay_cli_trusted: bool = False


class GitCall(Protocol):
    def __call__(
        self, cwd: str, *args: str, timeout: float = 60.0
    ) -> subprocess.CompletedProcess[str]: ...


class ParaRequest(Protocol):
    def __call__(
        self,
        client: httpx.Client,
        api_url: str,
        token: str,
        method: str,
        path: str,
        *,
        json_body: JsonObject | None = None,
    ) -> JsonObject: ...


class OutboxWriter(Protocol):
    def __call__(
        self, request: JsonObject, *, status: str, accepted: bool, reason: str
    ) -> JsonObject: ...


class ResultUpdater(Protocol):
    def __call__(
        self, *, user_id: int, dispatch_row: JsonObject, task: JsonObject, rows: list[JsonObject]
    ) -> bool: ...


@dataclass(frozen=True)
class WorkspacePorts:
    registry: Callable[[], WorkspaceRegistry]
    verified_relay_root: Callable[[JsonObject], str]
    relay_workspace: Callable[[JsonObject], str]


@dataclass(frozen=True)
class CliPorts:
    runner: Callable[[], CliRunner]
    apply_scope: Callable[[list[str]], list[str]]
    environment: Callable[[], dict[str, str] | None]
    idle_timeout: Callable[[], float]
    hard_cap: Callable[[], float]
    run_idle: IdleRunner


@dataclass(frozen=True)
class ConversationPorts:
    data_dir: Callable[[], Path]
    workspace: Callable[[JsonObject], str]
    git: GitCall
    is_git_repo: Callable[[str], bool]
    get_session: Callable[[str], JsonObject]
    set_session: Callable[[str, JsonObject], None]
    run_idle: IdleRunner
    idle_timeout: Callable[[], float]
    hard_cap: Callable[[], float]
    apply_scope: Callable[[list[str]], list[str]]


@dataclass(frozen=True)
class WorktreePorts:
    git: GitCall
    is_git_repo: Callable[[str], bool]
    resolve_branch: Callable[[str, str], str]
    persistent_path: Callable[[], str]


@dataclass(frozen=True)
class DevelopmentPorts:
    prepare: Callable[[str, str, str], tuple[str, str] | None]
    verify: Callable[[str], tuple[bool, str]]
    commit: Callable[[str, str, str], tuple[bool, str]]
    remove: Callable[[str, str], None]
    run_once: Callable[[str, str, str], str]
    work_prompt: Callable[[str, str], str]
    fix_prompt: Callable[[str, str], str]
    hard_cap: Callable[[], float]


@dataclass(frozen=True)
class ParaPorts:
    client: Callable[[], httpx.Client]
    api_url: Callable[[], str]
    token: Callable[[httpx.Client, str], str]
    request: ParaRequest


@dataclass(frozen=True)
class MessageSyncPorts:
    fetch_task: Callable[[str], JsonObject | None]
    direct_reply: Callable[[str], str]
    should_reply: Callable[[str, JsonObject], bool]
    compose_reply: Callable[[str, JsonObject], tuple[str, str]]
    refresh: Callable[[JsonObject, JsonObject], bool]
    upsert_result: ResultUpdater
    write_rows: Callable[[list[JsonObject]], None]
