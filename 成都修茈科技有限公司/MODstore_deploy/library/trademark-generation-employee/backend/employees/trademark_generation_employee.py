"""Trademark generation direct_python entrypoint."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

BOUNDARY_ERRORS = (Exception,)

EMPLOYEE_ID = "trademark-generation-employee"
EMPLOYEE_LABEL = "商标生成员"
SYSTEM_PROMPT = (
    "你是商标生成员。必须生成原创商标/Logo 方向、提示词、矢量交付建议和初步近似风险自检清单。"
    "禁止模仿现有商标、IP、明星、政府标识或受保护角色。没有生图密钥时返回完整提示词和 warning。"
)
RULE_SPEC = {
    "brief": "为公司、产品、App、AI 员工和店铺生成原创商标/Logo 方向、提示词、矢量交付建议和初步近似风险自检。",
    "mode": "direct_python_trademark_generation",
    "accepted_extensions": [".json", ".txt"],
    "default_action": "generate",
    "default_output_relpath": "outputs/trademark_profile.json",
    "runtime_kind": "trademark_generation",
    "pack_id": EMPLOYEE_ID,
    "prompt_presets": [
        "brand_mark_sheet",
        "startup_combination_mark",
        "app_icon_mark",
        "package_label_mark",
    ],
}


def _ok(
    data: Any,
    *,
    warnings: Optional[List[str]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "ok": True,
        "summary": _summary(data),
        "items": data if isinstance(data, list) else [data],
        "warnings": list(warnings or []),
        "error": "",
        "meta": dict(meta or {}),
    }


def _err(
    msg: str,
    *,
    warnings: Optional[List[str]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspace_root(ctx: Dict[str, Any]) -> Path:
    """Return the server-selected workspace; request payloads cannot replace it."""

    raw = ctx.get("workspace_root") or Path.cwd()
    return Path(str(raw)).expanduser().resolve()


def _resolve_output(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Path:
    rel = str(
        payload.get("output_relpath")
        or RULE_SPEC.get("default_output_relpath")
        or "outputs/trademark_profile.json"
    ).strip()
    requested = Path(rel)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError("output_relpath must stay inside the employee workspace")
    root = _workspace_root(ctx)
    p = (root / requested).resolve()
    root_prefix = root.as_posix().rstrip("/") + "/"
    if p != root and not p.as_posix().startswith(root_prefix):
        raise ValueError("output_relpath must stay inside the employee workspace")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload or {})
    ctx = dict(ctx or {})
    action = (
        str(payload.get("action") or RULE_SPEC.get("default_action") or "generate")
        .strip()
        .lower()
    )
    if action in ("help", "说明", "status"):
        return _ok(
            {"employee": EMPLOYEE_LABEL, "rule_spec": RULE_SPEC},
            meta={"handler": "direct_python", "action": "help"},
        )
    if action not in ("generate", "convert", "run", "生成", ""):
        return _err(
            f"不支持的 action：{action}",
            meta={"handler": "direct_python", "action": action},
        )

    try:
        vendor_dir = _backend_root() / "vendor"
        if str(vendor_dir) not in sys.path:
            sys.path.insert(0, str(vendor_dir))
        from trademark_generation.convert import convert_trademark_profile

        out = _resolve_output(payload, ctx)
        result = convert_trademark_profile(
            payload, ctx, output_path=out, rule_spec=RULE_SPEC
        )
        if asyncio.iscoroutine(result):
            result = await result
        if not out.is_file():
            return _err(
                f"商标方案未生成输出文件：{out}",
                meta={"handler": "direct_python", "action": "generate"},
            )
        return _ok(
            result,
            warnings=list(result.get("warnings") or [])
            if isinstance(result, dict)
            else [],
            meta={
                "handler": "direct_python",
                "action": "generate",
                "runtime": "trademark_generation",
            },
        )
    except BOUNDARY_ERRORS as exc:  # noqa: BLE001
        return _err(
            str(exc),
            warnings=["请检查品牌名、行业、商标类型、风格描述和生图密钥配置。"],
            meta={
                "handler": "direct_python",
                "action": "generate",
                "runtime": "trademark_generation",
            },
        )
