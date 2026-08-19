"""Data, entitlement, and artifact helpers for employee API routes."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.duty_employee_registry import duty_employee_records
from modstore_server.duty_roster import (
    all_planned_employee_ids,
    employee_partition_meta,
    is_planned_duty_employee_pack,
)
from modstore_server.models import CatalogItem, Entitlement, User, UserPlan


def _reraise_employee_pack_not_found(exc: BaseException) -> None:
    if isinstance(exc, ValueError) and "员工包不存在" in str(exc):
        raise HTTPException(404, str(exc)) from exc


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or "/tmp/modstore_runtime").expanduser()


def _employee_download_jobs_root() -> Path:
    d = _runtime_dir() / "employee_output_downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_taiyangniao_backend(input_data: Dict[str, Any]) -> None:
    """注入太阳鸟 pro 的 backend 路径（Linux 部署常用 MODSTORE_REPO_ROOT/mods/taiyangniao-pro/backend）。"""
    if input_data.get("taiyangniao_backend_path") or input_data.get("source_backend_path"):
        return
    tb = (os.environ.get("TAIYANGNIAO_BACKEND_PATH") or "").strip()
    if not tb:
        rr = (os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
        if rr:
            cand = Path(rr).expanduser() / "mods" / "taiyangniao-pro" / "backend"
            if cand.is_dir():
                tb = str(cand)
    if not tb:
        here = Path(__file__).resolve().parent
        deploy_root = here.parent
        for cand in (
            deploy_root.parent / "mods" / "taiyangniao-pro" / "backend",
            deploy_root / "mods" / "taiyangniao-pro" / "backend",
        ):
            if cand.is_dir():
                tb = str(cand)
                break
    if tb:
        input_data["taiyangniao_backend_path"] = tb


_ARTIFACT_OUTPUT_SUFFIXES = (
    ".xlsx",
    ".xlsm",
    ".xls",
    ".json",
    ".csv",
    ".txt",
    ".md",
    ".pdf",
    ".pptx",
    ".docx",
    ".html",
)


def _gather_artifact_paths(obj: Any, acc: List[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in (
                "output",
                "input",
                "file_path",
                "filepath",
                "path",
                "json_file",
                "text_file",
            ) and isinstance(v, str):
                s = v.strip()
                if s.lower().endswith(_ARTIFACT_OUTPUT_SUFFIXES):
                    acc.append(s)
            else:
                _gather_artifact_paths(v, acc)
    elif isinstance(obj, list):
        for it in obj:
            _gather_artifact_paths(it, acc)


def _gather_spreadsheet_paths(obj: Any, acc: List[str]) -> None:
    _gather_artifact_paths(obj, acc)


def _list_session_output_files(session_dir: Path) -> List[Path]:
    out_dir = session_dir / "outputs"
    if not out_dir.is_dir():
        return []
    found: List[Path] = []
    for p in sorted(out_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in _ARTIFACT_OUTPUT_SUFFIXES:
            found.append(p)
    return found


def _collect_llm_context_text(
    session_dir: Path, exec_result: Dict[str, Any], *, max_chars: int = 120_000
) -> str:
    """在删除临时目录前，把读取员工 outputs 中的文本/JSON 汇总给工作台 LLM。"""
    parts: List[str] = []
    seen: set[str] = set()
    for rel in _list_session_output_files(session_dir):
        key = str(rel.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            if rel.suffix.lower() == ".json":
                data = json.loads(rel.read_text(encoding="utf-8"))
                body = json.dumps(data, ensure_ascii=False, indent=2)
            else:
                body = rel.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        body = (body or "").strip()
        if not body:
            continue
        label = str(rel.relative_to(session_dir)).replace("\\", "/")
        parts.append(f"### {label}\n{body}")

    if not parts:
        try:
            blob = json.dumps(exec_result, ensure_ascii=False, indent=2)
            if blob and blob not in ("{}", "null"):
                parts.append(f"### execute_result\n{blob}")
        except Exception:
            pass

    text = "\n\n".join(parts).strip()
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n…（已截断，原文约 {len(text)} 字符）"
    return text


def _is_reasonable_output_file(candidate: Path, upload_input: Path) -> bool:
    try:
        cr = candidate.resolve()
        ir = upload_input.resolve()
    except OSError:
        return False
    if cr == ir:
        return False
    name = candidate.name
    low = name.lower()
    if "模板" in name or "template" in low:
        return False
    if "考勤统计表" in name and "输出" not in name:
        return False
    if "输出" in name or "output" in low:
        return True
    return "424" in candidate.parts


def _persist_employee_outputs_for_download(
    user_id: int,
    session_dir: Path,
    upload_dest: Path,
    exec_result: Dict[str, Any],
) -> List[Dict[str, str]]:
    raw_paths: List[str] = []
    _gather_artifact_paths(exec_result, raw_paths)
    seen: set[str] = set()
    unique: List[Path] = []
    session_resolved = session_dir.resolve()
    for p in _list_session_output_files(session_dir):
        key = str(p.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(p)
    for p_raw in raw_paths:
        try:
            p = Path(p_raw).expanduser()
            if not p.is_file():
                continue
            key = str(p.resolve())
            if key in seen:
                continue
            seen.add(key)
            low = p.suffix.lower()
            under_outputs = False
            try:
                p.resolve().relative_to(session_resolved / "outputs")
                under_outputs = True
            except ValueError:
                pass
            if not under_outputs and low not in (".json", ".csv", ".txt", ".md"):
                if not _is_reasonable_output_file(p, upload_dest):
                    continue
            try:
                p.resolve().relative_to(session_resolved)
            except ValueError:
                continue
            unique.append(p)
        except OSError:
            continue
    if not unique:
        return []
    job_id = uuid.uuid4().hex
    job_dir = (_employee_download_jobs_root() / str(user_id) / job_id).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    meta: List[Dict[str, str]] = []
    for i, src in enumerate(unique):
        dest_name = src.name
        dest = job_dir / dest_name
        if dest.exists():
            stem = dest.stem
            suf = dest.suffix
            dest = job_dir / f"{stem}_{i}{suf}"
        shutil.copy2(src, dest)
        label = (
            "下载转换结果" if ("输出" in dest.name or "output" in dest.name.lower()) else dest.name
        )
        meta.append({"job_id": job_id, "filename": dest.name, "label": label})
    return meta


def sync_triggers_after_registration(manifest: Dict) -> None:
    """员工包注册/更新后，同步其 triggers 到 DB（后台静默执行）。"""
    try:
        from modstore_server.sync_employee_triggers import sync_triggers_for_manifest

        sync_triggers_for_manifest(manifest)
    except Exception:
        import logging

        logging.getLogger(__name__).exception("sync_triggers_after_registration failed")


def _user_may_execute_employee_pack(db: Session, user_id: int, pack_id: str) -> bool:
    """路径参数 ``employee_id`` 与 ``CatalogItem.pkg_id`` 一致（见 employee_runtime.load_employee_pack）。"""
    u = db.query(User).filter(User.id == user_id).first()
    if u and getattr(u, "is_admin", False):
        return True
    if is_planned_duty_employee_pack(pack_id, "employee_pack"):
        return False

    row = (
        db.query(CatalogItem)
        .filter(
            CatalogItem.pkg_id == pack_id.strip(),
            CatalogItem.artifact == "employee_pack",
        )
        .first()
    )
    if not row:
        return False
    if row.author_id is not None and int(row.author_id) == int(user_id):
        return True

    ent = (
        db.query(Entitlement)
        .filter(
            Entitlement.user_id == user_id,
            Entitlement.catalog_id == row.id,
            Entitlement.is_active.is_(True),
        )
        .first()
    )
    if ent:
        return True

    if bool(getattr(row, "is_public", False)) and float(row.price or 0) <= 0:
        return True

    now = datetime.now(timezone.utc)
    plan = (
        db.query(UserPlan)
        .filter(UserPlan.user_id == user_id, UserPlan.is_active.is_(True))
        .order_by(UserPlan.id.desc())
        .first()
    )
    if not plan:
        return False
    exp = plan.expires_at
    if exp is None:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > now


def _candidate_employee_pack_ids(employee_id: str) -> List[str]:
    raw = (employee_id or "").strip()
    if not raw:
        return []
    candidates = [raw]
    dashed = raw.replace("_", "-")
    underscored = raw.replace("-", "_")
    for item in (dashed, underscored, f"{dashed}-employee", f"{underscored}_employee"):
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def _load_employee_pack_with_aliases(db: Session, employee_id: str) -> Dict[str, Any]:
    """目录（DB + ``packages.json``）优先；未命中时可选从 Mod 库目录读取。"""
    from modstore_server.employee_runtime import load_employee_pack_resolved

    return load_employee_pack_resolved(db, employee_id)


def _employee_id_from_list_row(row: Dict[str, Any]) -> str:
    for key in ("employee_id", "pack_id", "pkg_id", "id"):
        val = row.get(key) if isinstance(row, dict) else None
        if val:
            return str(val).strip()
    return ""


def _annotate_employee_list_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row or {})
    pid = _employee_id_from_list_row(out)
    artifact = str(out.get("artifact") or "employee_pack")
    out.update(employee_partition_meta(pid, artifact))
    return out


def _list_duty_employee_rows() -> List[Dict[str, Any]]:
    records = duty_employee_records()
    rows: List[Dict[str, Any]] = []
    for pid in sorted(all_planned_employee_ids()):
        rec = dict(records.get(pid) or {})
        name = str(rec.get("name") or pid)
        version = str(rec.get("version") or "")
        row = {
            "id": pid,
            "employee_id": pid,
            "pack_id": pid,
            "pkg_id": pid,
            "name": name,
            "label": name,
            "version": version,
            "artifact": "employee_pack",
            "stored_filename": str(rec.get("stored_filename") or ""),
            "registry": "duty_employee_registry",
            "manifest_registered": bool(rec),
        }
        row.update(employee_partition_meta(pid, "employee_pack"))
        rows.append(row)
    return rows


def _assert_employee_scope_visible_to_user(employee_id: str, user: User) -> None:
    if is_planned_duty_employee_pack(employee_id, "employee_pack") and not bool(
        getattr(user, "is_admin", False)
    ):
        raise HTTPException(403, "上岗员工仅管理端可见")
