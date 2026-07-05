"""Avatar generation direct_python entrypoint."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

EMPLOYEE_ID = "avatar-generation-employee"
EMPLOYEE_LABEL = "头像生成员"
SYSTEM_PROMPT = (
    "你是头像生成员。必须覆盖人类常用头像类型，按 AI 员工职能生成原创头像方案、提示词和可选生图结果。"
    "内置 AI 员工批量头像表、小 C 人形鱼系助理、单员工移动端联系人头像三套预设提示词。"
    "没有生图密钥时返回完整提示词和 warning，禁止声称已经生成图片。"
)
RULE_SPEC = {
    "brief": "覆盖真人、关系、动漫游戏、插画化本人、职业品牌、宠物吉祥物、兴趣符号、抽象氛围、默认极简九类头像。",
    "mode": "direct_python_avatar_generation",
    "accepted_extensions": [".json", ".txt"],
    "default_action": "generate",
    "default_output_relpath": "outputs/avatar_profile.json",
    "runtime_kind": "avatar_generation",
    "pack_id": EMPLOYEE_ID,
    "prompt_presets": [
        "employee_avatar_sheet",
        "xiaoc_human_aquatic",
        "mobile_contact_avatar",
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


def _workspace_root(ctx: Dict[str, Any], payload: Dict[str, Any]) -> Path:
    raw = payload.get("workspace_root") or ctx.get("workspace_root") or Path.cwd()
    return Path(str(raw)).expanduser()


def _resolve_output(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Path:
    rel = str(
        payload.get("output_relpath")
        or RULE_SPEC.get("default_output_relpath")
        or "outputs/avatar_profile.json"
    ).strip()
    p = Path(rel).expanduser()
    if not p.is_absolute():
        p = _workspace_root(ctx, payload) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload or {})
    ctx = dict(ctx or {})
    action = str(payload.get("action") or RULE_SPEC.get("default_action") or "generate").strip().lower()
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
        from avatar_generation.convert import convert_avatar_profile

        out = _resolve_output(payload, ctx)
        result = convert_avatar_profile(payload, ctx, output_path=out, rule_spec=RULE_SPEC)
        if asyncio.iscoroutine(result):
            result = await result
        if not out.is_file():
            return _err(
                f"头像方案未生成输出文件：{out}",
                meta={"handler": "direct_python", "action": "generate"},
            )
        return _ok(
            result,
            warnings=list(result.get("warnings") or []) if isinstance(result, dict) else [],
            meta={"handler": "direct_python", "action": "generate", "runtime": "avatar_generation"},
        )
    except Exception as exc:  # noqa: BLE001
        return _err(
            str(exc),
            warnings=["请检查员工姓名、头像类型、风格描述和生图密钥配置。"],
            meta={"handler": "direct_python", "action": "generate", "runtime": "avatar_generation"},
        )
