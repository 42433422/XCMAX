"""平台办公文件解析：统一调度 office full-read 员工 Mod。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

OFFICE_UPLOAD_SUFFIXES = frozenset(
    {".xlsx", ".xlsm", ".xls", ".csv", ".docx", ".doc", ".pdf", ".pptx", ".ppt"}
)

EMPLOYEE_BY_SUFFIX: dict[str, str] = {
    ".xlsx": "excel-full-read-employee",
    ".xlsm": "excel-full-read-employee",
    ".xls": "excel-full-read-employee",
    ".csv": "csv-full-read-employee",
    ".docx": "word-full-read-employee",
    ".doc": "word-full-read-employee",
    ".pdf": "pdf-full-read-employee",
    ".pptx": "ppt-full-read-employee",
    ".ppt": "ppt-full-read-employee",
}


def resolve_office_read_employee(filename: str) -> str:
    suffix = Path(str(filename or "")).suffix.lower()
    return EMPLOYEE_BY_SUFFIX.get(suffix, "")


def is_office_docking_file(filename: str) -> bool:
    return Path(str(filename or "")).suffix.lower() in OFFICE_UPLOAD_SUFFIXES


async def run_office_read_employee(
    employee_id: str,
    *,
    file_path: str,
    workspace_root: str,
    output_relpath: str | None = None,
) -> dict[str, Any]:
    """调用已加载 employee_pack 的 /run 语义（进程内 dispatch）。"""
    from app.mod_sdk.mods_bus import import_mod_backend_py

    mod_id = str(employee_id or "").strip()
    if not mod_id:
        raise ValueError("缺少 employee_id")

    mod_path = ""
    try:
        from app.infrastructure.mods.mod_manager import get_mod_manager

        meta = get_mod_manager().get_mod_metadata(mod_id)
        mod_path = str(getattr(meta, "mod_path", "") or "")
    except RECOVERABLE_ERRORS:
        logger.debug("office parse mod lookup failed mod=%s", mod_id, exc_info=True)

    if not mod_path:
        from pathlib import Path as _Path

        guess = _Path(__file__).resolve().parents[2] / "mods" / "_employees" / mod_id
        if guess.is_dir():
            mod_path = str(guess)
    if not mod_path:
        raise RuntimeError(f"办公员工 Mod 未找到: {mod_id}")

    payload: dict[str, Any] = {
        "file_path": file_path,
        "workspace_root": workspace_root,
        "action": "convert",
    }
    if output_relpath:
        payload["output_relpath"] = output_relpath

    stem = mod_id.replace("-", "_")
    blueprints = import_mod_backend_py(mod_path, mod_id, "blueprints")
    dispatch = getattr(blueprints, "_dispatch_run", None) if blueprints else None
    if not callable(dispatch):
        raise RuntimeError(f"员工 Mod 缺少 dispatch: {mod_id}")
    result = await dispatch(mod_id, mod_id, stem, payload)
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(str(result.get("message") or result.get("error") or "员工执行失败"))
    data = result.get("data") if isinstance(result, dict) else result
    return data if isinstance(data, dict) else {"raw": data}


def read_workspace_output_files(
    workspace_root: str,
    file_paths: list[str],
    *,
    max_bytes: int = 2_097_152,
) -> list[dict[str, Any]]:
    from app.mod_sdk.workspace import resolve_safe_workspace_relpath

    out: list[dict[str, Any]] = []
    for raw in file_paths:
        rel = str(raw or "").strip().lstrip("/")
        if not rel:
            continue
        try:
            path = resolve_safe_workspace_relpath(rel)
        except ValueError as exc:
            out.append({"path": rel, "kind": "text", "error": str(exc)})
            continue
        if not path.is_file():
            out.append({"path": rel, "kind": "text", "error": "file_not_found"})
            continue
        try:
            blob = path.read_bytes()[:max_bytes]
        except OSError as exc:
            out.append({"path": rel, "kind": "text", "error": str(exc)})
            continue
        suffix = path.suffix.lower()
        if suffix == ".json":
            import json

            try:
                parsed = json.loads(blob.decode("utf-8", errors="replace"))
                out.append(
                    {
                        "path": rel,
                        "kind": "json",
                        "json": parsed if isinstance(parsed, dict) else {"value": parsed},
                    }
                )
                continue
            except json.JSONDecodeError:
                pass
        text = blob.decode("utf-8", errors="replace")
        out.append({"path": rel, "kind": "text", "text": text})
    return out
