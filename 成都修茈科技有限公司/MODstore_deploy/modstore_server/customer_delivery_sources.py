"""Private production sources belong to one persisted owner/session, never a global ID."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

_LIBRARY: ContextVar[Path | None] = ContextVar("private_delivery_source_library", default=None)


def active_private_library() -> Path | None:
    return _LIBRARY.get()


def public_library() -> Path:
    from modstore_server.mod_scaffold_runner import modstore_library_path

    token = _LIBRARY.set(None)
    try:
        return Path(modstore_library_path()).resolve()
    finally:
        _LIBRARY.reset(token)


def _scope_path(owner_id: int, session_id: str) -> Path:
    if owner_id <= 0 or not re.fullmatch(r"[a-z0-9_-]{16,64}", session_id):
        raise ValueError("私有生产账号或会话身份无效")
    root = public_library().parent / "customer-delivery-sources"
    target = root / str(owner_id) / session_id
    if any(path.is_symlink() for path in (root, root / str(owner_id), target)):
        raise ValueError("私有生产目录不能使用符号链接")
    return target


def create_private_source_scope(owner_id: int, session_id: str, ticket_id: int) -> dict[str, Any]:
    if ticket_id <= 0:
        raise ValueError("私有生产必须关联原工单")
    root = _scope_path(owner_id, session_id)
    scope = {"owner_user_id": owner_id, "session_id": session_id, "ticket_id": ticket_id}
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "scope.json"
    try:
        with marker.open("x", encoding="utf-8") as output:
            json.dump(scope, output, sort_keys=True)
    except FileExistsError:
        if json.loads(marker.read_text()) != scope:
            raise ValueError("私有生产目录已经属于其他账号、会话或工单") from None
    library = root / "library"
    library.mkdir(exist_ok=True)
    return scope


def source_library(scope: dict[str, Any], owner_id: int, session_id: str, ticket_id: int) -> Path:
    expected = {"owner_user_id": owner_id, "session_id": session_id, "ticket_id": ticket_id}
    root = _scope_path(owner_id, session_id)
    if scope != expected or json.loads((root / "scope.json").read_text()) != expected:
        raise ValueError("私有生产源记录与账号、会话或工单不匹配")
    library = root / "library"
    if library.is_symlink() or not library.is_dir():
        raise ValueError("私有生产源目录无效")
    return library


@contextmanager
def private_source_context(scope: dict[str, Any]) -> Iterator[Path]:
    library = source_library(
        scope, int(scope["owner_user_id"]), str(scope["session_id"]), int(scope["ticket_id"])
    )
    token = _LIBRARY.set(library)
    try:
        yield library
    finally:
        _LIBRARY.reset(token)


def verified_snapshot_library(
    snapshot: dict[str, Any], owner_id: int, session_id: str, ticket_id: int
) -> Path:
    from modstore_server import workbench_api

    persisted = workbench_api._load_workbench_session_unlocked(session_id)
    scope = snapshot.get("source_scope")
    if (
        not persisted
        or persisted.get("id") != session_id
        or persisted.get("user_id") != owner_id
        or persisted.get("status") != "done"
        or not isinstance(scope, dict)
        or scope != persisted.get("source_scope")
        or snapshot.get("id") != session_id
    ):
        raise ValueError("私有生产源必须来自本账号已完成的持久生产会话")
    return source_library(scope, owner_id, session_id, ticket_id)


def seed_previous_delivery(scope: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Rework can restore only a verified previous package owned by this ticket."""
    import io
    import zipfile

    from modstore_server.customer_delivery_build import read_verified_artifact

    records = _previous_source_records(scope, evidence)
    with private_source_context(scope) as library:
        for record in records:
            raw, signed = read_verified_artifact(
                record, owner_id=int(scope["owner_user_id"]), ticket_id=int(scope["ticket_id"])
            )
            mid = str(signed["manifest"]["id"])
            destination = library / mid
            if destination.exists():
                continue
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for name, digest in signed["files_sha256"].items():
                    import hashlib

                    data = archive.read(name if name in archive.namelist() else f"{mid}/{name}")
                    path = (destination / name).resolve()
                    if (
                        not path.is_relative_to(destination.resolve())
                        or hashlib.sha256(data).hexdigest() != digest
                    ):
                        raise ValueError("返工源与原签包文件不一致")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
            original = destination / "source-employee-manifest.json"
            if original.is_file():
                (destination / "manifest.json").write_bytes(original.read_bytes())


def _previous_source_records(
    scope: dict[str, Any], evidence: dict[str, Any]
) -> list[dict[str, Any]]:
    from modstore_server import workbench_api

    full: list[dict[str, Any]] = []
    for run in reversed(evidence.get("runs") or []):
        if run.get("session_id") == scope["session_id"]:
            continue
        rows = run.get("verified_artifacts") or []
        if not rows and run.get("session_id"):
            persisted = workbench_api._load_workbench_session_unlocked(str(run["session_id"]))
            if (
                persisted
                and persisted.get("id") == run["session_id"]
                and persisted.get("user_id") == scope["owner_user_id"]
                and persisted.get("status") == "done"
            ):
                rows = persisted.get("verified_artifacts") or []
        full.extend(rows)
    records = list(evidence.get("delivery_artifacts") or []) or full
    failed_id = str(evidence.get("runtime_mod_id") or "") if evidence.get("runtime_failure") else ""
    if failed_id:
        records = [row for row in records if row.get("id") == failed_id]
        if not records:
            raise ValueError("失败产物缺少上一轮可信源码记录，原单等待恢复，不能从零覆盖")
    selected: list[dict[str, Any]] = []
    failed_generation = (evidence.get("resolution") or {}).get("failed_generation")
    for row in records:
        candidates = [row] if row.get("signed_package_path") else full
        match = next(
            (
                item
                for item in candidates
                if item.get("signed_package_path")
                and all(
                    item.get(key) == row.get(key)
                    for key in ("kind", "id", "version", "package_sha256")
                )
                and item.get("owner_user_id") == scope["owner_user_id"]
                and item.get("ticket_id") == scope["ticket_id"]
                and item.get("generation") != scope["session_id"]
                and (not failed_generation or item.get("generation") == failed_generation)
            ),
            None,
        )
        if match is None:
            raise ValueError("上一轮交付身份、版本或摘要没有匹配的可信源码记录，不能从零覆盖")
        if match not in selected:
            selected.append(match)
    return selected
