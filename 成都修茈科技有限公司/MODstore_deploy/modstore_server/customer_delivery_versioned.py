"""Produce a private delivery from the immutable main release's Sunbird Mod."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from modstore_server.operational_errors import BOUNDARY_ERRORS

MOD_ID = "sunbird-attendance-custom"
LEGACY_ID = "taiyangniao-pro"


def source_fingerprints(root: Path) -> tuple[dict[str, str], str]:
    """Hash every file and the ordered tree; reject links and special members."""
    if not root.is_dir() or root.is_symlink():
        raise ValueError("主线 Mod 源目录无效")
    digest = hashlib.sha256()
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError("主线 Mod 源包含不允许的链接或特殊文件")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            files[relative] = file_hash
            encoded = relative.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
            digest.update(bytes.fromhex(file_hash))
    if not files:
        raise ValueError("主线 Mod 源为空")
    return files, digest.hexdigest()


def source_sha256(root: Path) -> str:
    return source_fingerprints(root)[1]


def assert_owner_source(owner_id: int, mod_id: str) -> None:
    """A suggested ID never grants another customer's versioned source."""
    from modstore_server.models import User, get_session_factory, get_user_mod_ids

    root = Path(__file__).resolve().parents[3]
    rows = json.loads((root / "FHD/config/customer_delivery.json").read_text(encoding="utf-8"))[
        "deliveries"
    ]
    allowed = any(
        row.get("delivery_id") == "customer-taiyangniao"
        and row.get("runtime_mod_id") == mod_id == MOD_ID
        and row.get("legacy_mod_id") == LEGACY_ID
        and row.get("delivery_mode") == "private_mod"
        and row.get("customer_account") == "SUNBIRD"
        and row.get("market_user_id") == owner_id
        for row in rows
    )
    with get_session_factory()() as db:
        owner = db.get(User, owner_id)
        account = str(owner.username or "").strip().casefold() if owner else ""
    if (
        not allowed
        or account != "sunbird"
        or owner is None
        or getattr(owner, "deleted_at", None) is not None
        or str(owner.account_state or "") in {"deleted", "disabled", "suspended", "blocked"}
        or not owner.is_enterprise
        or LEGACY_ID not in get_user_mod_ids(owner_id)
    ):
        raise PermissionError("当前账号无权交付该主线私有 Mod")


def release_source() -> tuple[Path, dict[str, str]]:
    """Accept only a source tree fingerprinted by the immutable main release."""
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / ".xcmax-release.json").read_text(encoding="utf-8"))
    sha = str(manifest.get("git_sha") or "")
    expected = str(os.environ.get("MODSTORE_EXPECTED_GIT_SHA") or "")
    running = str(os.environ.get("MODSTORE_GIT_SHA") or "")
    source_row = (manifest.get("private_mod_sources") or {}).get(MOD_ID) or {}
    tree = str(source_row.get("git_tree") or "")
    wanted = str(source_row.get("sha256") or "")
    files = source_row.get("files")
    if not (
        re.fullmatch(r"[0-9a-f]{40}", sha)
        and sha == expected == running
        and re.fullmatch(r"[0-9a-f]{40}", tree)
        and re.fullmatch(r"[0-9a-f]{64}", wanted)
        and isinstance(files, dict)
        and bool(files)
    ):
        raise ValueError("主线发行身份或私有 Mod 源指纹缺失/不匹配")
    source = root / "FHD/mods" / MOD_ID
    actual_files, actual_sha = source_fingerprints(source)
    if actual_files != files or actual_sha != wanted:
        raise ValueError("主线私有 Mod 源与发行指纹不一致")
    return source, {"git_sha": sha, "git_tree": tree, "sha256": wanted}


def _copy_validated_source(library: Path, provenance: dict[str, str]) -> Path:
    source, actual = release_source()
    if actual != provenance:
        raise ValueError("生产期间主线发行身份发生变化")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    runtime = (manifest.get("frontend") or {}).get("runtime") or {}
    probe = manifest.get("delivery_verification") or {}
    if (
        manifest.get("id") != MOD_ID
        or manifest.get("artifact") != "mod"
        or manifest.get("scope") != "account"
        or manifest.get("public_listing") is not False
        or manifest.get("entitlement_mod_id") != LEGACY_ID
        or runtime.get("sdk_version") != 1
        or probe.get("handler") != "verify_delivery"
        or probe.get("case_id") != "sunbird-owner-conversion-v1"
    ):
        raise ValueError("主线 Mod 身份或交付业务探针不匹配")
    target = library / MOD_ID
    shutil.copytree(source, target)
    if source_sha256(target) != provenance["sha256"]:
        raise ValueError("私有生产源复制后摘要不匹配")
    return target


async def start_versioned_main_run(
    *, user_id: int, ticket_id: int, evidence: dict[str, Any], attempt: int
) -> dict[str, Any]:
    from modstore_server import workbench_api as workbench
    from modstore_server.customer_delivery_sources import (
        create_private_source_scope,
        source_library,
    )
    from modstore_server.workbench_delivery_bridge import get_workbench_session_snapshot

    assert_owner_source(user_id, str(evidence.get("suggested_id") or ""))
    _, provenance = release_source()
    session_id = uuid.uuid4().hex[:24]
    scope = create_private_source_scope(user_id, session_id, ticket_id)
    steps = [
        {"id": "source", "label": "核验主线源码", "status": "pending"},
        {"id": "mod_sandbox", "label": "校验并签署私有 Mod", "status": "pending"},
    ]
    async with workbench._SESSION_LOCK:
        workbench.WORKBENCH_SESSIONS[session_id] = {
            "id": session_id,
            "user_id": user_id,
            "intent": "mod",
            "status": "running",
            "steps": steps,
            "artifact": None,
            "error": None,
            "source_scope": scope,
        }
        workbench._persist_workbench_session_unlocked(session_id)

    async def produce() -> None:
        step = "source"
        try:
            await workbench._set_step(session_id, "source", "running")
            library = source_library(scope, user_id, session_id, ticket_id)
            target = await asyncio.to_thread(_copy_validated_source, library, provenance)
            await workbench._set_step(session_id, "source", "done", "发行源码摘要一致")
            step = "mod_sandbox"
            await workbench._set_step(session_id, "mod_sandbox", "running")
            from modstore_server.mod_scaffold_runner import mod_compileall_warnings

            def compile_separate_copy() -> list[str]:
                with tempfile.TemporaryDirectory(prefix="sunbird-source-check-") as temporary:
                    source_copy = shutil.copytree(target, Path(temporary) / MOD_ID)
                    return cast(list[str], mod_compileall_warnings(source_copy))

            warnings = await asyncio.to_thread(compile_separate_copy)
            if warnings:
                raise ValueError("Mod Python 编译失败：" + "; ".join(warnings)[:800])
            if source_sha256(target) != provenance["sha256"]:
                raise ValueError("私有生产源在签包前发生变化")
            artifact = {
                "mod_id": MOD_ID,
                "validation_summary": {"ok": True, "python_warnings": []},
                "source_provenance": provenance,
            }
            await workbench._set_step(
                session_id, "mod_sandbox", "done", "源码校验通过，开始正式签包"
            )
            await workbench._finalize_session_done(session_id, artifact)
            snapshot = await get_workbench_session_snapshot(session_id, user_id)
            if not snapshot:
                raise ValueError("私有生产会话快照不存在")
            from modstore_server.customer_delivery_build import prepare_private_artifact

            signed = await asyncio.to_thread(
                prepare_private_artifact,
                ticket_id,
                user_id,
                {
                    **evidence,
                    "delivery_generation": session_id,
                    "source_git_sha": provenance["git_sha"],
                    "source_git_tree": provenance["git_tree"],
                    "source_sha256": provenance["sha256"],
                },
                snapshot,
            )
            async with workbench._SESSION_LOCK:
                workbench.WORKBENCH_SESSIONS[session_id]["verified_artifacts"] = [signed]
                workbench._persist_workbench_session_unlocked(session_id)
        except asyncio.CancelledError:
            await workbench._fail_session(session_id, step, "主线私有生产任务已中断")
            raise
        except BOUNDARY_ERRORS as exc:
            await workbench._fail_session(session_id, step, str(exc)[:1000])

    task = asyncio.create_task(produce())
    task.add_done_callback(workbench._pipeline_task_failsafe(session_id))
    return {
        "kind": "module",
        "attempt": attempt,
        "session_id": session_id,
        "status": "running",
        "created_at": datetime.now(UTC).isoformat(),
    }
