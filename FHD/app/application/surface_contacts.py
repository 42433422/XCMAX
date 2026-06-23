# -*- coding: utf-8 -*-
"""按 surface SSOT 解析某端(device×side)的「固定联系人」。

平台员工(platform)是动态集合,各端经各自端点(/home mods / admin employees)提供,
不在此解析。此处只解析 assistant / dedicated_cs / super 三类固定条目,并按
``ai_workforce.json`` 的 surfaces 顺序,以 platform 为界切分为两段:
- ``top``    : 平台员工之前出现的固定条目
- ``bottom`` : 平台员工之后出现的固定条目
客户端渲染顺序 = top + 平台员工(动态) + bottom,从而与 SSOT 声明的顺序一致。

端区分语义(用户定义):
- 专属客服(dedicated_cs)只在企业端出现(它是企业端指向管理端的支持联系人);
  管理端无此条目。由 surface_composition 的端差异自动实现。
- 小C助理(assistant)= 智能对话(Persona引擎,route="assistant_chat"),
  ≠ 专属客服(route="cs", backend=enterprise-cs)。两者不再混用同一后端语义。
"""

from __future__ import annotations

from typing import Any

from app.mod_sdk import assistant_ssot


def _assistant_entry() -> dict[str, Any]:
    x = assistant_ssot.xiaoc()
    return {
        "id": "assistant",
        "kind": "assistant",
        "name": assistant_ssot.xiaoc_display_name(),
        "summary": str(x.get("brief") or "企业 AI 助手"),
        "avatar": str(x.get("avatar_letter") or "C"),
        "route": "assistant_chat",
        "backend": "assistant",
    }


def _dedicated_cs_entry() -> dict[str, Any]:
    label = (assistant_ssot.contact_kinds().get("dedicated_cs") or {}).get("label") or "专属客服"
    return {
        "id": "dedicated_cs",
        "kind": "dedicated_cs",
        "name": str(label),
        "summary": "企业账号专属服务入口",
        "avatar": "客",
        "route": "cs",
        "backend": "enterprise-cs",
    }


def _super_entries() -> list[dict[str, Any]]:
    from app.application.super_employee_service import CLAUDE_PROFILE, CODEX_PROFILE

    out: list[dict[str, Any]] = []
    for profile in (CLAUDE_PROFILE, CODEX_PROFILE):
        out.append(
            {
                "id": profile.employee_id,
                "kind": "super",
                "name": profile.employee_name,
                "summary": f"{profile.display_tool} 超级员工 · 多设备派工",
                "avatar": "超",
                "route": f"super:{profile.employee_id}",
                "backend": profile.employee_id,
            }
        )
    return out


def _resolve_kind(kind: str) -> list[dict[str, Any]]:
    if kind == "assistant":
        return [_assistant_entry()]
    if kind == "dedicated_cs":
        return [_dedicated_cs_entry()]
    if kind == "super":
        return _super_entries()
    return []  # platform 由各端动态提供,不在此解析


def fixed_contacts(device: str, side: str) -> dict[str, Any]:
    """返回某端固定联系人,按 platform 切分为 top/bottom 两段。"""
    sd = "admin" if str(side or "").strip().lower() == "admin" else "enterprise"
    comp = assistant_ssot.surface_composition(device, sd)
    top: list[dict[str, Any]] = []
    bottom: list[dict[str, Any]] = []
    seen_platform = False
    for kind in comp:
        if kind == "platform":
            seen_platform = True
            continue
        entries = _resolve_kind(kind)
        (bottom if seen_platform else top).extend(entries)
    return {"device": device, "side": sd, "top": top, "bottom": bottom}


def mobile_fixed_contacts(side: str) -> dict[str, Any]:
    """手机端固定联系人(便捷封装)。"""
    return fixed_contacts("mobile", side)


__all__ = ["fixed_contacts", "mobile_fixed_contacts"]
