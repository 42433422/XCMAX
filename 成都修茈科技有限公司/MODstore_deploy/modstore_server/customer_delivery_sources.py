"""Private production sources belong to one persisted owner/session, never a global ID."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator, cast

_LIBRARY: ContextVar[Path | None] = ContextVar("private_delivery_source_library", default=None)
_SESSION_ID = re.compile(r"[0-9a-f]{16,32}\Z")


def migrate_private_delivery_state(
    legacy_deploy: Path,
    runtime_root: Path,
    *,
    library: Path | None = None,
    legacy_library: Path | None = None,
    bootstrap_source: Path | None = None,
    releases_root: Path | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Copy a caller-selected trusted release after complete validation, never overwrite."""
    from modstore_server.catalog_publication_policy import stable_version
    from modstore_server.customer_delivery_build import _verify_artifact_record
    from modstore_server.customer_delivery_versioned import source_fingerprints

    legacy_deploy, runtime_root = Path(legacy_deploy).absolute(), Path(runtime_root).absolute()
    library = Path(library).absolute() if library else runtime_root / "library"
    legacy_library = (
        Path(legacy_library).absolute() if legacy_library else legacy_deploy / "library"
    )
    bootstrap_source = Path(bootstrap_source).absolute() if bootstrap_source else None
    releases_root = Path(releases_root).absolute() if releases_root else None
    for path in (
        legacy_deploy,
        runtime_root,
        library,
        legacy_library,
        bootstrap_source,
        releases_root,
    ):
        if path is None:
            continue
        for member in reversed((path, *path.parents)):
            if member.is_symlink():
                raise ValueError(f"迁移目录不接受符号链接: {member}")
    legacy_deploy, runtime_root, library, legacy_library = (
        path.resolve() for path in (legacy_deploy, runtime_root, library, legacy_library)
    )
    release = legacy_deploy.parents[1]
    for path in (release, legacy_deploy.parent, legacy_deploy):
        _require_directory(path)
    bootstrap = release.parent.name != "releases" or not re.fullmatch(r"[0-9a-f]{40}", release.name)
    if bootstrap:
        if (
            bootstrap_source is None
            or releases_root is None
            or bootstrap_source.resolve() != release
        ):
            raise ValueError("迁移必须显式指定受信不可变发行目录或原 SOURCE_ROOT")
        if (release / ".git").is_symlink():
            raise ValueError("bootstrap Git 元数据不能为链接")
        git = subprocess.run(
            ["git", "-C", str(release), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if git.returncode or Path(git.stdout.strip()).resolve() != release:
            raise ValueError("bootstrap 来源不是原 SOURCE_ROOT Git checkout")
        manifest = {}
    else:
        if releases_root and releases_root.resolve() != release.parent:
            raise ValueError("旧发行不属于已声明 releases 根")
        releases_root = release.parent
        manifest = _read_regular_json(release / ".xcmax-release.json")
        if manifest.get("git_sha") != release.name:
            raise ValueError("迁移来源发行身份不匹配")
    assert releases_root is not None
    releases_root = releases_root.resolve()
    if any(
        path.is_relative_to(releases_root) or "releases" in path.parts
        for path in (runtime_root, library, library.parent)
    ):
        raise ValueError("持久目标不能位于任何发行目录内")
    config = legacy_deploy / ".modstore-config.json"
    configured = (
        _read_regular_json(config).get("library_root")
        if config.exists() or config.is_symlink()
        else ""
    )
    if configured and Path(configured).expanduser().absolute() != legacy_library:
        raise ValueError("旧发行显式 library_root 与已核验真实库路径不一致")
    roots = (
        (
            legacy_deploy / "modstore_server/data/workbench_sessions",
            runtime_root / "workbench_sessions",
        ),
        (legacy_library, library),
        (
            legacy_library.parent / "customer-delivery-sources",
            library.parent / "customer-delivery-sources",
        ),
        (
            legacy_library.parent / "customer-delivery-artifacts",
            library.parent / "customer-delivery-artifacts",
        ),
    )
    targets = [target for _, target in roots]
    if any(
        first.is_relative_to(second) or second.is_relative_to(first)
        for index, first in enumerate(targets)
        for second in targets[index + 1 :]
    ):
        raise ValueError("持久会话、库、私有源码和签包目录不能重叠")
    pending: list[tuple[Path, Path, str]] = []
    conflicts = []

    def digest(path: Path) -> str:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("迁移不接受链接或特殊文件")
            return hashlib.file_digest(handle, "sha256").hexdigest()

    for old, target in roots:
        if target.is_relative_to(release):
            raise ValueError("持久目标不能位于发行目录内")
        for directory in (old, *old.parents, target, *target.parents):
            if directory.is_symlink():
                raise ValueError(f"迁移目录不接受符号链接: {directory}")
        if not old.exists():
            continue
        _require_directory(old)
        for path in sorted(old.rglob("*")):
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise ValueError(f"迁移不接受链接或特殊文件: {path}")
            destination = target / path.relative_to(old)
            if destination.is_symlink():
                raise ValueError(f"迁移目标不接受符号链接: {destination}")
            if path.is_dir():
                if destination.exists() and not destination.is_dir():
                    conflicts.append(str(destination))
                continue
            source_digest = digest(path)
            if destination.exists() and (
                not destination.is_file() or digest(destination) != source_digest
            ):
                conflicts.append(str(destination))
            pending.append((path, destination, source_digest))

    if bootstrap and any(old.exists() and any(old.iterdir()) for old, _ in roots[2:]):
        raise ValueError("无发行锚的 bootstrap 不能迁移任何私有源码或签包")
    session_root = roots[0][0]
    for session in session_root.glob("*.json") if session_root.is_dir() else ():
        snapshot = _read_regular_json(session)
        sid = session.stem
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("id") != sid
            or not _SESSION_ID.fullmatch(sid)
        ):
            raise ValueError("迁移会话身份无效")
        if bootstrap and (
            snapshot.get("delivery_source_mode") == "versioned_main"
            or snapshot.get("source_scope")
            or snapshot.get("verified_artifacts")
        ):
            raise ValueError("无发行锚的 bootstrap 不能迁移私有生产会话")
        if snapshot.get("delivery_source_mode") != "versioned_main":
            continue
        owner, ticket = int(snapshot.get("user_id") or 0), int(snapshot.get("ticket_id") or 0)
        _validate_identity(owner, sid)
        scope = {"owner_user_id": owner, "session_id": sid, "ticket_id": ticket}
        source_root = roots[2][0] / str(owner) / sid
        if (
            ticket <= 0
            or snapshot.get("source_scope") != scope
            or _read_scope(source_root) != scope
        ):
            raise ValueError("迁移缺少原账号、工单或私有源码记录")
        records = snapshot.get("verified_artifacts") or []
        if snapshot.get("status") != "done" or not records:
            raise ValueError("主线交付迁移缺少已完成原会话和签名包")
        for record in records:
            mod_id, version = str(record.get("id") or ""), str(record.get("version") or "")
            stable_version(version)
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", mod_id):
                raise ValueError("迁移产物身份无效")
            package = roots[3][0] / str(owner) / mod_id / f"{mod_id}-{version}.xcmod"
            if (
                record.get("generation") != sid
                or Path(str(record.get("signed_package_path") or "")) != package
            ):
                raise ValueError("迁移产物不属于原会话固定发行路径")
            if not package.is_file():
                raise ValueError("迁移缺少原正式签名包")
            _verify_artifact_record(package.read_bytes(), record, owner_id=owner, ticket_id=ticket)
            pinned = (manifest.get("private_mod_sources") or {}).get(mod_id) or {}
            actual_files, actual_hash = source_fingerprints(source_root / "library" / mod_id)
            if (
                record.get("source_git_sha") != release.name
                or record.get("source_git_tree") != pinned.get("git_tree")
                or record.get("source_sha256") != actual_hash
                or actual_hash != pinned.get("sha256")
                or actual_files != pinned.get("files")
            ):
                raise ValueError("迁移私有源码与原主线发行指纹不匹配")
    if conflicts:
        raise ValueError("持久状态迁移冲突，未复制任何文件: " + ", ".join(conflicts))
    if not dry_run:
        staged = []
        try:
            for source, destination, expected in pending:
                if digest(source) != expected:
                    raise ValueError("迁移期间原文件已变化")
                if destination.exists():
                    if digest(destination) != expected:
                        raise ValueError(f"持久状态迁移冲突: {destination}")
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
                    temporary = Path(handle.name)
                    staged.append((temporary, destination, expected))
                    fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    with os.fdopen(fd, "rb") as original:
                        shutil.copyfileobj(original, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                if digest(temporary) != expected:
                    raise ValueError("迁移副本与原文件摘要不一致")
            for _, destination, expected in staged:
                if destination.exists() and digest(destination) != expected:
                    raise ValueError(f"持久状态迁移冲突: {destination}")
            for temporary, destination, expected in staged:
                if not destination.exists():
                    os.link(temporary, destination, follow_symlinks=False)
        finally:
            for temporary, _, _ in staged:
                temporary.unlink(missing_ok=True)
    return {
        "ok": True,
        "dry_run": dry_run,
        "validated_files": len(pending),
        "source_release": release.name,
        "bootstrap": bool(bootstrap),
    }


def _validate_identity(owner_id: int, session_id: str) -> None:
    if owner_id <= 0 or not _SESSION_ID.fullmatch(session_id):
        raise ValueError("私有生产账号或会话身份无效")


def _child_entry(parent: Path, name: str) -> Path | None:
    """Return a direct child from the directory listing, never a joined name."""
    try:
        with os.scandir(parent) as entries:
            for item in entries:
                if item.name == name:
                    return Path(item.path)
    except OSError:
        return None
    return None


def _require_directory(path: Path) -> None:
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError:
        raise ValueError("私有生产目录无效") from None
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("私有生产目录不能使用符号链接")


def _read_scope(root: Path) -> dict[str, Any]:
    marker = _child_entry(root, "scope.json")
    if marker is None:
        raise ValueError("私有生产目录记录无效")
    return _read_regular_json(marker, max_bytes=4096)


def _read_regular_json(marker: Path, *, max_bytes: int | None = None) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(marker, flags)
    except OSError:
        raise ValueError("私有生产目录记录无效") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (max_bytes is not None and info.st_size > max_bytes):
            raise ValueError("私有生产目录记录无效")
        stream = os.fdopen(fd, "r", encoding="utf-8")
    except (OSError, ValueError):
        os.close(fd)
        raise
    with stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("私有生产目录记录无效")
    return cast(dict[str, Any], payload)


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
    _validate_identity(owner_id, session_id)
    root = public_library().parent / "customer-delivery-sources"
    target = root / str(owner_id) / session_id
    if any(path.is_symlink() for path in (root, root / str(owner_id), target)):
        raise ValueError("私有生产目录不能使用符号链接")
    return target


def _existing_scope_path(owner_id: int, session_id: str) -> Path:
    """Resolve an existing scope through directory listings only.

    The returned path never contains caller-supplied path segments, so a
    crafted owner/session value cannot redirect a later read or check.
    """
    _validate_identity(owner_id, session_id)
    delivery_root = _child_entry(public_library().parent, "customer-delivery-sources")
    owner_root = _child_entry(delivery_root, str(owner_id)) if delivery_root else None
    target = _child_entry(owner_root, session_id) if owner_root else None
    if delivery_root is None or owner_root is None or target is None:
        raise ValueError("私有生产目录不存在")
    for path in (delivery_root, owner_root, target):
        _require_directory(path)
    return target


def create_private_source_scope(owner_id: int, session_id: str, ticket_id: int) -> dict[str, Any]:
    if ticket_id <= 0:
        raise ValueError("私有生产必须关联原工单")
    created = _scope_path(owner_id, session_id)
    scope = {
        "owner_user_id": owner_id,
        "session_id": session_id,
        "ticket_id": ticket_id,
    }
    created.mkdir(parents=True, exist_ok=True)
    root = _existing_scope_path(owner_id, session_id)
    marker = root / "scope.json"
    if marker.is_symlink():
        raise ValueError("私有生产目录不能使用符号链接")
    try:
        with marker.open("x", encoding="utf-8") as output:
            json.dump(scope, output, sort_keys=True)
    except FileExistsError:
        if _read_scope(root) != scope:
            raise ValueError("私有生产目录已经属于其他账号、会话或工单") from None
    library = _child_entry(root, "library")
    if library is None:
        (root / "library").mkdir()
        library = _child_entry(root, "library")
    if library is None:
        raise ValueError("私有生产源目录无效")
    _require_directory(library)
    return scope


def source_library(scope: dict[str, Any], owner_id: int, session_id: str, ticket_id: int) -> Path:
    expected = {
        "owner_user_id": owner_id,
        "session_id": session_id,
        "ticket_id": ticket_id,
    }
    root = _existing_scope_path(owner_id, session_id)
    if scope != expected or _read_scope(root) != expected:
        raise ValueError("私有生产源记录与账号、会话或工单不匹配")
    library = _child_entry(root, "library")
    if library is None:
        raise ValueError("私有生产源目录无效")
    _require_directory(library)
    return library


@contextmanager
def private_source_context(scope: dict[str, Any]) -> Iterator[Path]:
    library = source_library(
        scope,
        int(scope["owner_user_id"]),
        str(scope["session_id"]),
        int(scope["ticket_id"]),
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
    versioned_main = snapshot.get("delivery_source_mode") == "versioned_main"
    if (
        not persisted
        or persisted.get("id") != session_id
        or persisted.get("user_id") != owner_id
        or persisted.get("status") != "done"
        or (
            versioned_main
            and (
                persisted.get("ticket_id") != ticket_id
                or persisted.get("delivery_source_mode") != "versioned_main"
                or persisted.get("delivery_runtime_identity")
                != snapshot.get("delivery_runtime_identity")
                or (persisted.get("verified_artifacts") or [])
                != (snapshot.get("verified_artifacts") or [])
                or persisted.get("artifact") != snapshot.get("artifact")
            )
        )
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
                record,
                owner_id=int(scope["owner_user_id"]),
                ticket_id=int(scope["ticket_id"]),
            )
            mid = str(signed["manifest"]["id"])
            destination = library / mid
            if destination.exists():
                continue
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for name, digest in signed["files_sha256"].items():
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
