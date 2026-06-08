"""太阳鸟考勤员 employee_pack 实现。

纯 Python 脚本型封装：直接导入 taiyangniao-pro 的考勤转换模块并在本机文件路径上执行，
不依赖网页上传，也不调用 HTTP 接口。
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

EMPLOYEE_ID = "taiyangniao-attendance"
EMPLOYEE_LABEL = "太阳鸟考勤员"
SOURCE_MOD_ID = "taiyangniao-pro"

DEFAULT_OUTPUT_RELPATH = "424/考勤转换输出.xlsx"
DEFAULT_TEMPLATE_RELPATH = "424/考勤-2026-3月份考勤统计表.xlsx"

SYSTEM_PROMPT = (
    "你是太阳鸟考勤员。你直接使用 taiyangniao-pro 的 Python 考勤转换模块；"
    "没有真实文件或无法导入模块时必须返回明确错误，不能声称已经转换。"
)


def _ok(data: Any, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "ok": True,
        "summary": _summary(data),
        "items": data if isinstance(data, list) else [data],
        "warnings": list(warnings or []),
        "error": "",
        "meta": dict(meta or {}),
    }


def _err(msg: str, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "ok": False,
        "summary": msg[:400],
        "items": [],
        "warnings": list(warnings or []),
        "error": msg[:1000],
        "meta": dict(meta or {}),
    }


def _summary(data: Any) -> str:
    if isinstance(data, str):
        return data[:4000]
    try:
        return json.dumps(data, ensure_ascii=False)[:4000]
    except TypeError:
        return str(data)[:4000]


def _action(payload: Dict[str, Any]) -> str:
    raw = payload.get("action") or payload.get("task") or payload.get("intent") or ""
    text = str(raw).strip().lower()
    if text in {"rules", "rule", "规则", "考勤规则"}:
        return "rules"
    if text in {"convert", "upload", "转换", "上传转换", "上传并转换"}:
        return "convert"
    if text in {"help", "说明", "status", "状态", ""}:
        return "help"
    if any(k in text for k in ("规则", "rule")):
        return "rules"
    if any(k in text for k in ("转换", "上传", "excel", "xlsx", "考勤")):
        return "convert"
    return "help"


def _find_file_path(payload: Dict[str, Any]) -> str:
    for key in ("file_path", "filepath", "path", "attendance_file", "excel_path"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    files = payload.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                value = item.get("path") or item.get("file_path")
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _workspace_root(ctx: Dict[str, Any], payload: Dict[str, Any]) -> Path:
    raw = (
        payload.get("workspace_root")
        or ctx.get("workspace_root")
        or os.environ.get("WORKSPACE_ROOT")
        or os.environ.get("FHD_WORKSPACE_ROOT")
        or os.environ.get("EMPLOYEE_WORKSPACE_ROOT")
        or "e:/FHD"
    )
    return Path(str(raw)).expanduser()


def _resolve_path(path: str, ctx: Dict[str, Any], payload: Dict[str, Any]) -> Tuple[Optional[Path], str]:
    if not path:
        return None, "缺少 file_path：请提供钉钉导出的 .xlsx/.xlsm/.xls 文件路径。"

    raw = Path(path).expanduser()
    candidates = [raw]
    if not raw.is_absolute():
        candidates.insert(0, _workspace_root(ctx, payload) / path)

    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate, ""
        except OSError as exc:
            return None, f"读取路径失败：{candidate}：{exc}"
    return None, f"文件不存在：{path}"


def _resolve_output_path(raw_path: str, ctx: Dict[str, Any], payload: Dict[str, Any]) -> Path:
    raw = Path(raw_path).expanduser()
    if raw.is_absolute():
        return raw
    return _workspace_root(ctx, payload) / raw_path


def _resolve_template_path(raw_path: str, ctx: Dict[str, Any], payload: Dict[str, Any]) -> Path:
    raw = Path(raw_path).expanduser()
    if raw.is_absolute():
        return raw
    workspace_candidate = _workspace_root(ctx, payload) / raw_path
    if workspace_candidate.is_file():
        return workspace_candidate
    bundled_candidate = Path(__file__).resolve().parent.parent / "templates" / raw_path
    if bundled_candidate.is_file():
        return bundled_candidate
    return workspace_candidate


def _candidate_backend_dirs(ctx: Dict[str, Any], payload: Dict[str, Any]) -> List[Path]:
    explicit = payload.get("taiyangniao_backend_path") or payload.get("source_backend_path") or os.environ.get("TAIYANGNIAO_BACKEND_PATH")
    repo_root = (os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
    here = Path(__file__).resolve()
    roots = [
        payload.get("fhd_root"),
        ctx.get("fhd_root"),
        os.environ.get("FHD_ROOT"),
        os.environ.get("WORKSPACE_ROOT"),
        "e:/FHD",
    ]
    # Prefer the copy bundled inside this employee pack so deploys do not depend on taiyangniao-pro being present.
    out: List[Path] = [here.parent.parent / "vendor"]
    if explicit:
        out.append(Path(str(explicit)).expanduser())
    if repo_root:
        r = Path(repo_root).expanduser()
        out.append(r / "mods" / "taiyangniao-pro" / "backend")
        out.append(r / "XCAGI" / "mods" / "taiyangniao-pro" / "backend")
    for root in roots:
        if not root:
            continue
        r = Path(str(root)).expanduser()
        out.append(r / "mods" / "taiyangniao-pro" / "backend")
        out.append(r / "XCAGI" / "mods" / "taiyangniao-pro" / "backend")
    for parent in here.parents:
        out.append(parent / "mods" / "taiyangniao-pro" / "backend")
        out.append(parent / "FHD" / "mods" / "taiyangniao-pro" / "backend")
    dedup: List[Path] = []
    seen = set()
    for p in out:
        key = str(p)
        if key not in seen:
            seen.add(key)
            dedup.append(p)
    return dedup


def _load_taiyangniao_modules(ctx: Dict[str, Any], payload: Dict[str, Any]) -> Tuple[Any, Any, str]:
    errors: List[str] = []
    for backend_dir in _candidate_backend_dirs(ctx, payload):
        pkg_dir = backend_dir / "taiyangniao_attendance"
        if not pkg_dir.is_dir():
            continue
        backend_str = str(backend_dir)
        if backend_str not in sys.path:
            sys.path.insert(0, backend_str)
        try:
            convert_mod = importlib.import_module("taiyangniao_attendance.convert")
            rules_mod = importlib.import_module("taiyangniao_attendance.rules")
            return convert_mod, rules_mod, backend_str
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{backend_dir}: {exc}")
    detail = "; ".join(errors[-3:]) if errors else "未找到 taiyangniao-pro/backend/taiyangniao_attendance"
    raise ImportError(detail)


def _rules_payload(rules_mod: Any) -> Dict[str, Any]:
    lines = [
        "优先读取钉钉「每日统计」，再用「原始记录」补充打卡时间与去重。",
        "重复打卡按上午/下午/晚上分段去重，优先保留每段的有效边界打卡。",
        "目标文件会在固定模板基础上回填「明细」工作表。",
        "周一到周六正班固定为 08:00-12:00、13:30-17:30；周日算加班。",
    ]
    saturday = getattr(rules_mod, "SATURDAY_COMPANY_FACTORY_WORK_RANGES", None)
    saturday_label = ""
    try:
        first = list(saturday or [])[0]
        saturday_label = f"{first.start.strftime('%H:%M')} - {first.end.strftime('%H:%M')}"
    except Exception:
        saturday_label = "13:30 - 16:00"
    return {
        "lines": lines,
        "saturday_window_label": saturday_label,
        "config": {
            "default_header_row": 0,
            "default_output_relpath": DEFAULT_OUTPUT_RELPATH,
            "default_template_relpath": DEFAULT_TEMPLATE_RELPATH,
            "accepted_extensions": [".xlsx", ".xlsm", ".xls"],
            "runtime": "direct_python",
        },
    }


def _offline_help(payload: Dict[str, Any]) -> Dict[str, Any]:
    example = {
        "action": "convert",
        "file_path": "uploads/dingtalk-attendance.xlsx",
        "output_relpath": DEFAULT_OUTPUT_RELPATH,
        "template_relpath": DEFAULT_TEMPLATE_RELPATH,
        "use_personnel_roster": True,
        "workspace_root": "e:/FHD",
        "taiyangniao_backend_path": "e:/FHD/mods/taiyangniao-pro/backend",
    }
    return _ok(
        {
            "employee": EMPLOYEE_LABEL,
            "source_mod_id": SOURCE_MOD_ID,
            "available_actions": ["help", "rules", "convert"],
            "runtime": "direct_python",
            "required_for_convert": [
                "file_path 指向钉钉导出的 Excel",
                "template_relpath 指向固定模板",
                "员工包内置 taiyangniao_attendance 转换模块",
            ],
            "example_payload": example,
            "received": payload,
        },
        meta={"handler": "help"},
    )


async def _rules(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        _convert_mod, rules_mod, backend_dir = _load_taiyangniao_modules(ctx, payload)
    except Exception as exc:  # noqa: BLE001
        return _err(
            "无法导入太阳鸟 pro 考勤规则模块：" + str(exc),
            meta={"handler": "direct_python", "action": "rules", "source_mod_id": SOURCE_MOD_ID},
        )
    data = _rules_payload(rules_mod)
    return _ok(data, meta={"handler": "direct_python", "action": "rules", "source_mod_id": SOURCE_MOD_ID, "backend_dir": backend_dir})


async def _convert(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    file_path = _find_file_path(payload)
    src_path, file_err = _resolve_path(file_path, ctx, payload)
    if file_err:
        return _err(
            file_err,
            warnings=["纯 Python 模式需要传入本机可读的真实 Excel 文件路径。"],
            meta={"handler": "direct_python", "action": "convert"},
        )
    assert src_path is not None
    if src_path.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
        return _err(f"不支持的文件类型：{src_path.suffix or '(无后缀)'}", meta={"handler": "direct_python", "action": "convert"})

    try:
        convert_mod, _rules_mod, backend_dir = _load_taiyangniao_modules(ctx, payload)
    except Exception as exc:  # noqa: BLE001
        return _err(
            "无法导入太阳鸟 pro 转换模块：" + str(exc),
            warnings=["可通过 payload.taiyangniao_backend_path 指定 e:/FHD/mods/taiyangniao-pro/backend。"],
            meta={"handler": "direct_python", "action": "convert", "source_mod_id": SOURCE_MOD_ID},
        )

    out_rel = str(payload.get("output_relpath") or DEFAULT_OUTPUT_RELPATH).strip() or DEFAULT_OUTPUT_RELPATH
    tpl_rel = str(payload.get("template_relpath") or DEFAULT_TEMPLATE_RELPATH).strip() or DEFAULT_TEMPLATE_RELPATH
    out_path = _resolve_output_path(out_rel, ctx, payload)
    tpl_path = _resolve_template_path(tpl_rel, ctx, payload)
    if not tpl_path.is_file():
        return _err(
            f"模板文件不存在：{tpl_path}",
            meta={"handler": "direct_python", "action": "convert", "template_relpath": tpl_rel},
        )

    try:
        result = convert_mod.convert_attendance_file(
            str(src_path),
            str(out_path),
            template_path=str(tpl_path),
            month=str(payload.get("month") or "") or None,
            header_row=int(payload.get("header_row") if payload.get("header_row") is not None else 0),
            use_llm=bool(payload.get("use_llm")),
            personnel_roster=None,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(
            "太阳鸟 pro Python 转换执行异常：" + str(exc),
            meta={"handler": "direct_python", "action": "convert", "backend_dir": backend_dir},
        )
    if not isinstance(result, dict) or not result.get("success"):
        return _err(
            str((result or {}).get("error") or "转换失败"),
            meta={"handler": "direct_python", "action": "convert", "backend_dir": backend_dir},
        )
    return _ok(
        {
            "message": "转换完成",
            "input": str(src_path),
            "output": str(out_path),
            "output_relpath": out_rel,
            "rows_in": result.get("rows_in"),
            "rows_used_for_template": result.get("rows_used_for_template"),
            "rows_stats": result.get("rows_stats"),
            "employees_total": result.get("employees_total"),
            "employees_matched": result.get("employees_matched"),
            "unmatched_names": result.get("unmatched_names"),
            "header_info": result.get("header_info"),
            "used_llm": result.get("used_llm"),
            "output_sheet_names": result.get("output_sheet_names"),
            "raw": result,
        },
        meta={"handler": "direct_python", "action": "convert", "source_mod_id": SOURCE_MOD_ID, "backend_dir": backend_dir},
    )


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    payload = payload or {}
    ctx = ctx or {}
    requested_handler = str(payload.get("handler") or "direct_python").strip()
    if requested_handler == "echo":
        return _ok({"echo": payload}, meta={"handler": "echo"})

    action = _action(payload)
    if action == "rules":
        return await _rules(payload, ctx)
    if action == "convert":
        return await _convert(payload, ctx)
    return _offline_help(payload)
