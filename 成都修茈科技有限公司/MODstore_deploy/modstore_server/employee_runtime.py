"""员工包运行时加载与 V2 解析。"""

from __future__ import annotations

import json
import os
import re
import zipfile
from typing import Any, Dict, Optional

from modstore_server.catalog_store import employee_pack_records_from_store, files_dir
from modstore_server.duty_employee_registry import get_duty_employee_record
from modstore_server.duty_roster import employee_partition_meta, is_planned_duty_employee_pack
from modstore_server.employee_config_v2_adapter import (
    needs_executor_translation,
    translate_v2_to_executor_config,
)
from modstore_server.models import CatalogItem

EXECUTOR_ACTION_HANDLERS = frozenset(
    {
        "echo",
        "llm_md",
        "http_request",
        "webhook",
        "data_sync",
        "direct_python",
        "wechat_notify",
        "openapi_tool",
        "fhd_business",
        "voice_output",
        "agent",
        "para_delegate",
        "cursor_delegate",
        "vibe_edit",
        "vibe_heal",
        "vibe_code",
        "doc_sync",
        "shell_exec",
        "ssh_exec",
    }
)


def employee_pack_runtime_issues(pack: Dict[str, Any]) -> list[str]:
    """Validate that a catalog pack has a runnable implementation for its handlers."""
    manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    handlers = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
    clean_handlers = [str(h).strip() for h in handlers if str(h).strip()]
    issues: list[str] = []
    if not clean_handlers:
        return ["员工包未声明 actions.handlers"]
    unknown = sorted(set(clean_handlers) - EXECUTOR_ACTION_HANDLERS)
    if unknown:
        issues.append("运行时不支持 handler: " + ", ".join(unknown))

    stored = str(pack.get("stored_filename") or "").strip()
    if not stored:
        issues.append("员工包缺少 stored_filename")
        return issues
    archive = files_dir() / stored
    if not archive.is_file():
        issues.append(f"员工包文件不存在: {stored}")
        return issues
    if "direct_python" not in clean_handlers:
        return issues

    pack_id = str(manifest.get("id") or pack.get("pack_id") or "").strip()
    direct = actions.get("direct_python") if isinstance(actions.get("direct_python"), dict) else {}
    module = str(direct.get("module") or "").strip()
    if not module:
        module = re.sub(r"[^a-z0-9_]+", "_", pack_id.lower()).strip("_")
    runtime_mod = re.sub(r"[^a-z0-9_]+", "_", pack_id.lower()).strip("_")
    if runtime_mod.endswith("_employee"):
        runtime_mod = runtime_mod[: -len("_employee")] or runtime_mod
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            names = {n.replace("\\", "/") for n in zf.namelist()}
            root = f"{pack_id}/"
            employee_entry = f"{root}backend/employees/{module}.py"
            vendor_entry = f"{root}backend/vendor/{runtime_mod}/convert.py"
            if employee_entry not in names:
                issues.append(f"direct_python 入口缺失: backend/employees/{module}.py")
            else:
                source = zf.read(employee_entry).decode("utf-8", errors="replace")
                if "_DISPATCH" in source and not (
                    "'direct_python':" in source or '"direct_python":' in source
                ):
                    issues.append("direct_python 入口使用了不支持该 handler 的通用分发模板")
            if vendor_entry not in names:
                issues.append(
                    f"direct_python vendor 运行时缺失: backend/vendor/{runtime_mod}/convert.py"
                )
    except (OSError, zipfile.BadZipFile):
        issues.append("员工包归档损坏或不可读取")
    return issues


def normalize_manifest_legacy_deepseek_to_auto(manifest: Dict[str, Any]) -> None:
    """入库较早的员工包 manifest 仍写死 ``deepseek``；与当前默认「自动」对齐（仅改内存中的解析结果）。"""
    if not isinstance(manifest, dict):
        return
    v2 = manifest.get("employee_config_v2")
    if not isinstance(v2, dict):
        return
    cog = v2.get("cognition")
    if not isinstance(cog, dict):
        return
    agent = cog.get("agent")
    if not isinstance(agent, dict):
        return
    model = agent.get("model")
    if not isinstance(model, dict):
        return
    if str(model.get("provider") or "").strip().lower() != "deepseek":
        return
    model["provider"] = "auto"
    model["model_name"] = "auto"


def load_employee_pack(session, pack_id: str) -> Dict[str, Any]:
    requested_id = str(pack_id or "").strip()
    row = (
        session.query(CatalogItem)
        .filter(CatalogItem.pkg_id == requested_id, CatalogItem.artifact == "employee_pack")
        .first()
    )
    if row:
        pkg_id = str(row.pkg_id)
        name = str(row.name or pkg_id)
        version = str(row.version or "")
        stored_filename = str(row.stored_filename or "")
    else:
        duty_rec = (
            get_duty_employee_record(requested_id)
            if is_planned_duty_employee_pack(requested_id, "employee_pack")
            else None
        )
        if duty_rec:
            pkg_id = str(duty_rec.get("id") or duty_rec.get("pkg_id") or requested_id).strip()
            name = str(duty_rec.get("name") or pkg_id)
            version = str(duty_rec.get("version") or "")
            stored_filename = str(duty_rec.get("stored_filename") or "")
        else:
            rec = employee_pack_records_from_store().get(requested_id)
            if not isinstance(rec, dict):
                raise ValueError(f"员工包不存在: {pack_id}")
            pkg_id = str(rec.get("id") or requested_id).strip()
            name = (str(rec.get("name") or pkg_id).strip() or pkg_id)[:256]
            version = str(rec.get("version") or "1.0.0").strip() or "1.0.0"
            stored_filename = str(rec.get("stored_filename") or "").strip()

    manifest: Dict[str, Any] = {"id": pkg_id, "name": name, "version": version}
    fn = (stored_filename or "").strip()
    if fn:
        path = files_dir() / fn
        if path.is_file() and path.suffix.lower() in (".xcemp", ".zip", ".xcmod"):
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    names = {n.replace("\\", "/") for n in zf.namelist()}
                    preferred = f"{pack_id}/manifest.json"
                    inner = preferred if preferred in names else ""
                    if not inner:
                        candidates = sorted(n for n in names if n.endswith("/manifest.json"))
                        inner = candidates[0] if candidates else ""
                    if inner:
                        manifest = json.loads(zf.read(inner).decode("utf-8"))
                        normalize_manifest_legacy_deepseek_to_auto(manifest)
            except (OSError, zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError):
                pass
    archive_mtime = 0.0
    if fn:
        try:
            archive_mtime = float((files_dir() / fn).stat().st_mtime)
        except OSError:
            archive_mtime = 0.0
    return {
        "pack_id": pkg_id,
        "name": name,
        "version": version,
        "stored_filename": stored_filename,
        "archive_mtime": archive_mtime,
        "manifest": manifest,
        **employee_partition_meta(pkg_id, "employee_pack"),
    }


def library_manifest_fallback_enabled() -> bool:
    """未登记到 ``catalog_items`` / ``packages.json`` 时，是否允许从 Mod 库目录读取 ``manifest.json``。

    默认开启（``1``），便于「做员工」流水线 ``publish_to_catalog=False`` 后仍能打开工作台。
    多租户部署若共享同一库目录且需禁止按 id 探测草稿包，可设 ``MODSTORE_EMPLOYEE_MANIFEST_LIBRARY_FALLBACK=0``。
    """
    raw = (os.environ.get("MODSTORE_EMPLOYEE_MANIFEST_LIBRARY_FALLBACK") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _candidate_employee_pack_ids(pack_id: str) -> list[str]:
    raw = (pack_id or "").strip()
    if not raw:
        return []
    candidates = [raw]
    dashed = raw.replace("_", "-")
    underscored = raw.replace("-", "_")
    for item in (dashed, underscored, f"{dashed}-employee", f"{underscored}_employee"):
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def load_employee_pack_resolved(session, pack_id: str) -> Dict[str, Any]:
    """catalog_items / packages.json 优先；未登记时回退 Mod 库 manifest（与 employee_api 一致）。"""
    last_error: Optional[Exception] = None
    for candidate in _candidate_employee_pack_ids(pack_id):
        try:
            return load_employee_pack(session, candidate)
        except ValueError as exc:
            last_error = exc
    for candidate in _candidate_employee_pack_ids(pack_id):
        pack = try_load_employee_pack_from_library(candidate)
        if pack:
            return pack
    cand_txt = ", ".join(repr(c) for c in _candidate_employee_pack_ids(pack_id)) or "(无)"
    if library_manifest_fallback_enabled():
        lib_hint = "已在 Mod 库目录按上述 id 查找，未找到有效 manifest.json。"
    else:
        lib_hint = "已跳过 Mod 库查找（MODSTORE_EMPLOYEE_MANIFEST_LIBRARY_FALLBACK=0）。"
    raise ValueError(
        f"员工包不存在: 原始请求 id={pack_id!r}；已尝试: {cand_txt}。"
        f"未在 catalog_items / packages.json 登记。{lib_hint}"
        "请在工作台发布到目录、或运行 seed_*_employees.py --set-public --force。"
    ) from last_error


def try_load_employee_pack_from_library(pack_id: str) -> Optional[Dict[str, Any]]:
    """当目录无登记时，从 ``resolved_library(load_config())`` 下定位包目录并读取 ``manifest.json``。"""
    if not library_manifest_fallback_enabled():
        return None
    pid = str(pack_id or "").strip()
    if not pid:
        return None
    try:
        from modman.manifest_util import read_manifest
        from modman.repo_config import load_config, resolved_library
        from modman.store import find_mod_dir_by_manifest_id
    except Exception:
        return None
    try:
        lib = resolved_library(load_config())
        lib.mkdir(parents=True, exist_ok=True)
        mod_dir = find_mod_dir_by_manifest_id(lib, pid)
    except (OSError, ValueError, FileNotFoundError):
        return None
    data, err = read_manifest(mod_dir)
    if err or not isinstance(data, dict):
        return None
    mid = str(data.get("id") or "").strip() or pid
    name = str(data.get("name") or mid)[:256]
    version = str(data.get("version") or "1.0.0").strip() or "1.0.0"
    manifest = dict(data)
    normalize_manifest_legacy_deepseek_to_auto(manifest)
    return {
        "pack_id": mid,
        "name": name,
        "version": version,
        "stored_filename": "",
        "manifest": manifest,
        **employee_partition_meta(mid, "employee_pack"),
    }


def parse_employee_config_v2(manifest: Dict[str, Any]) -> Dict[str, Any]:
    v2 = manifest.get("employee_config_v2") if isinstance(manifest, dict) else None
    if isinstance(v2, dict):
        if needs_executor_translation(v2):
            return translate_v2_to_executor_config(v2)
        return v2
    employee: Any = manifest.get("employee") if isinstance(manifest, dict) else {}
    if not isinstance(employee, dict):
        employee = {}
    label = employee.get("label") if isinstance(employee, dict) else None
    return {
        "perception": {"type": "text"},
        "memory": {"type": "session"},
        "cognition": {
            "system_prompt": f"你是员工助手：{label or (manifest.get('name') if isinstance(manifest, dict) else None) or 'assistant'}",
            "reasoning_mode": "default",
        },
        "actions": {"handlers": ["echo"]},
    }


def build_employee_context(employee_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "employee_id": employee_id,
        "input_data": input_data or {},
    }
