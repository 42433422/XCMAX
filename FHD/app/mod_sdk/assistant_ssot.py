# -*- coding: utf-8 -*-
"""AI 员工三阶级 + 小C助理身份 单一真相源（SSOT）加载器。

真相源：``config/ai_workforce.json``。本模块是「员工系统 ↔ 人格系统」联系的唯一程序入口：

- 三阶级模型：assistant（小C助理，rank 1）/ super（超级员工，rank 2）/ platform（平台员工，rank 3）。
- 人格共享规则：assistant + platform 共享 Persona 引擎（四轴/rapport）；super 独立人格、不纳入。
- 调用链（单向向下）：assistant → super → platform。
- 小C身份（名字/头像/简介）：禁止在各端硬编码，一律经此读取。

设计原则与 ``app.mod_sdk.duty_roster`` 同构：LRU 缓存 + 文件缺失/损坏时 fail-safe 兜底，
保证 ``/cs/info`` 等端点即使配置缺失也返回稳定的小C身份，不抛异常。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.mod_sdk.host_profile import resolve_fhd_config_dir
from app.utils.operational_errors import RECOVERABLE_ERRORS

# 文件缺失/损坏时的 fail-safe 兜底：与 ai_workforce.json 中的声明保持一致。
_FALLBACK_DOC: dict[str, Any] = {
    "schema_version": 1,
    "tiers": [
        {
            "id": "assistant",
            "rank": 1,
            "label": "小C助理",
            "persona_shared": True,
            "can_call": ["super"],
        },
        {
            "id": "super",
            "rank": 2,
            "label": "超级员工",
            "persona_shared": False,
            "can_call": ["platform"],
        },
        {"id": "platform", "rank": 3, "label": "平台员工", "persona_shared": True, "can_call": []},
    ],
    "assistants": {
        "xiaoc": {
            "id": "xiaoc",
            "tier": "assistant",
            "display_name": "小C助理",
            "short_name": "小C",
            "avatar_letter": "C",
            "brief": "企业 AI 助手，处理搜索、问答和跨工具操作",
            "consult_title_suffix": "咨询",
            "persona": {"shared_engine": True, "fixed_identity_name": True, "identity_brief": ""},
            "conversation_surfaces": {
                "desktop": [
                    {"id": "floating", "label": "悬浮窗"},
                    {"id": "sidebar", "label": "侧栏智能对话", "route": "chat"},
                ],
                "mutual_exclusive": True,
            },
        }
    },
    "super_employees": {
        "claude-super-employee": {
            "id": "claude-super-employee",
            "tier": "super",
            "display_name": "超级员工-Claude",
            "display_tool": "Claude",
            "avatar_letter": "超",
        },
        "codex-super-employee": {
            "id": "codex-super-employee",
            "tier": "super",
            "display_name": "超级员工-Codex",
            "display_tool": "Codex",
            "avatar_letter": "超",
        },
    },
    "factory_employees": {
        "claude-factory-employee": {
            "id": "claude-factory-employee",
            "tier": "super",
            "scope": "factory",
            "visibility": "internal",
            "display_name": "工厂员工-Claude",
            "display_tool": "Claude",
            "avatar_letter": "厂",
        },
        "codex-factory-employee": {
            "id": "codex-factory-employee",
            "tier": "super",
            "scope": "factory",
            "visibility": "internal",
            "display_name": "工厂员工-Codex",
            "display_tool": "Codex",
            "avatar_letter": "厂",
        },
    },
    "contact_kinds": {
        "assistant": {"label": "小C助理", "is_employee_tier": True, "tier": "assistant"},
        "super": {"label": "超级员工", "is_employee_tier": True, "tier": "super"},
        "platform": {"label": "平台员工", "is_employee_tier": True, "tier": "platform"},
        "dedicated_cs": {"label": "专属客服", "is_employee_tier": False, "sides": ["enterprise"]},
    },
    "surfaces": {
        "desktop": {
            "enterprise": ["platform", "super", "dedicated_cs"],
            "admin": ["platform", "super"],
        },
        "mobile": {
            "enterprise": ["assistant", "dedicated_cs", "platform", "super"],
            "admin": ["assistant", "platform", "super"],
        },
    },
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except RECOVERABLE_ERRORS:
        return None


@lru_cache(maxsize=1)
def load_ai_workforce_document() -> dict[str, Any]:
    """加载 AI 员工编制文档；文件缺失或结构异常时回退到内置兜底。"""
    cfg = resolve_fhd_config_dir()
    if cfg is not None:
        doc = _read_json(cfg / "ai_workforce.json")
        if doc and isinstance(doc.get("tiers"), list) and isinstance(doc.get("assistants"), dict):
            return doc
    return _FALLBACK_DOC


# ── 三阶级模型 ────────────────────────────────────────────────────────────


def assistant_tiers() -> list[dict[str, Any]]:
    """返回按 rank 升序排列的三阶级定义。"""
    tiers = load_ai_workforce_document().get("tiers") or []
    valid = [t for t in tiers if isinstance(t, dict) and t.get("id")]
    return sorted(valid, key=lambda t: int(t.get("rank", 99)))


def get_tier(tier_id: str) -> dict[str, Any] | None:
    tid = str(tier_id or "").strip()
    for tier in assistant_tiers():
        if tier.get("id") == tid:
            return tier
    return None


# ── 人格共享规则（员工系统 ↔ 人格系统的联系）────────────────────────────


def persona_shared_tiers() -> frozenset[str]:
    """返回共享 Persona 人格引擎的阶级集合（默认 assistant + platform）。"""
    return frozenset(
        str(t["id"]) for t in assistant_tiers() if t.get("persona_shared") and t.get("id")
    )


def tier_shares_persona(tier_id: str) -> bool:
    """该阶级是否共享 Persona 人格引擎（super 返回 False）。"""
    return str(tier_id or "").strip() in persona_shared_tiers()


# ── 调用链（单向向下）────────────────────────────────────────────────────


def can_call(caller_tier: str, callee_tier: str) -> bool:
    """caller_tier 是否被允许调用 callee_tier（assistant→super→platform）。"""
    tier = get_tier(caller_tier)
    if tier is None:
        return False
    return str(callee_tier or "").strip() in (tier.get("can_call") or [])


# ── 小C助理身份 ──────────────────────────────────────────────────────────


def get_assistant(assistant_id: str = "xiaoc") -> dict[str, Any]:
    """返回指定助理实体；缺失时回退到兜底中的小C。"""
    aid = str(assistant_id or "").strip() or "xiaoc"
    assistants = load_ai_workforce_document().get("assistants") or {}
    entity = assistants.get(aid)
    if isinstance(entity, dict):
        return entity
    return _FALLBACK_DOC["assistants"]["xiaoc"]


def xiaoc() -> dict[str, Any]:
    """小C助理实体（fail-safe，永不返回 None）。"""
    return get_assistant("xiaoc")


# ── 超级员工(2级)身份 ────────────────────────────────────────────────────


def super_employees() -> dict[str, dict[str, Any]]:
    """超级员工身份注册表(id → 实体)；独立人格,不纳入 Persona。"""
    raw = load_ai_workforce_document().get("super_employees")
    if not isinstance(raw, dict):
        raw = _FALLBACK_DOC["super_employees"]
    return {k: v for k, v in raw.items() if not str(k).startswith("_") and isinstance(v, dict)}


def super_employee_ids() -> frozenset[str]:
    return frozenset(super_employees().keys())


def factory_employees() -> dict[str, dict[str, Any]]:
    """工厂版超级员工注册表（scope=factory · visibility=internal）。

    与 :func:`super_employees` **完全分离**：这些角色绝不进任何客户/管理选人器(surfaces)，
    仅出现在顶层管理端「项目工厂」控制台，运行需 FACTORY 授权。
    """
    raw = load_ai_workforce_document().get("factory_employees")
    if not isinstance(raw, dict):
        raw = _FALLBACK_DOC.get("factory_employees", {})
    return {k: v for k, v in raw.items() if not str(k).startswith("_") and isinstance(v, dict)}


def factory_employee_ids() -> frozenset[str]:
    return frozenset(factory_employees().keys())


def is_factory_employee(emp_id: str) -> bool:
    """该 id 是否为内部工厂角色（=客户/管理面绝不可见）。"""
    eid = str(emp_id or "").strip()
    if eid in factory_employees():
        return True
    # 纵深防御：即便误进了 super_employees，也按 visibility/scope 判定为内部。
    meta = super_employees().get(eid) or {}
    return (
        str(meta.get("visibility") or "").strip().lower() == "internal"
        or str(meta.get("scope") or "").strip().lower() == "factory"
    )


def xiaoc_display_name() -> str:
    """小C助理对外展示名（统一文案源，替代各端硬编码 "小C助理"）。"""
    return str(xiaoc().get("display_name") or "小C助理")


def xiaoc_consult_title() -> str:
    """小C咨询会话标题，如 "小C助理咨询"。"""
    entity = xiaoc()
    return f"{xiaoc_display_name()}{entity.get('consult_title_suffix') or '咨询'}"


def xiaoc_conversation_surfaces() -> dict[str, Any]:
    """小C智能对话的呈现入口声明：电脑端 悬浮窗 + 侧栏，二者互斥、同一会话引擎。

    与 ``surface_composition``（联系人列表组成）是不同的轴：小C不进桌面消息列表，
    但以悬浮窗 / 侧栏两种形态提供智能对话（同一 useChatView→useChatOrchestration +
    同一 /api/ai/chat → Persona + 同一 sessionId）。fail-safe，永不返回 None。
    """
    cs = xiaoc().get("conversation_surfaces")
    if isinstance(cs, dict):
        return cs
    return dict(_FALLBACK_DOC["assistants"]["xiaoc"].get("conversation_surfaces", {}))


# ── 桌面端/手机端 联系人组成（surface SSOT）────────────────────────────

_VALID_DEVICES = ("desktop", "mobile")
_VALID_SIDES = ("enterprise", "admin")


def contact_kinds() -> dict[str, Any]:
    """联系人条目种类定义（assistant/super/platform/dedicated_cs ...）。"""
    raw = load_ai_workforce_document().get("contact_kinds")
    if not isinstance(raw, dict):
        raw = _FALLBACK_DOC["contact_kinds"]
    return {k: v for k, v in raw.items() if not str(k).startswith("_")}


def dedicated_cs_label() -> str:
    """专属客服展示名(统一文案源;≠小C助理)。"""
    meta = contact_kinds().get("dedicated_cs") or {}
    return str(meta.get("label") or "专属客服")


def surface_composition(device: str, side: str) -> list[str]:
    """返回某(端 side × 设备 device)联系人固定区的有序条目种类。

    device ∈ {desktop, mobile}；side ∈ {enterprise, admin}。
    未知入参回退到兜底；过滤掉 contact_kinds 里不存在的条目。
    """
    dev = str(device or "").strip().lower()
    sd = str(side or "").strip().lower()
    surfaces = load_ai_workforce_document().get("surfaces")
    if not isinstance(surfaces, dict) or dev not in surfaces:
        surfaces = _FALLBACK_DOC["surfaces"]
    device_block = surfaces.get(dev) if isinstance(surfaces.get(dev), dict) else {}
    raw = device_block.get(sd)
    if not isinstance(raw, list):
        raw = (_FALLBACK_DOC["surfaces"].get(dev, {}) or {}).get(sd, [])
    known = contact_kinds()
    return [str(k) for k in raw if str(k) in known]


def contact_kind_sides(kind: str) -> tuple[str, ...]:
    """该条目种类允许出现的端；未声明 sides 视为两端都可。"""
    meta = contact_kinds().get(str(kind or "").strip()) or {}
    sides = meta.get("sides")
    if isinstance(sides, list) and sides:
        return tuple(str(s) for s in sides)
    return _VALID_SIDES


def platform_source_for_side(side: str) -> dict[str, Any]:
    """平台员工在某端解析到的来源(管理端=六线/企业端=四层)。"""
    sd = str(side or "").strip().lower()
    for tier in assistant_tiers():
        if tier.get("id") == "platform":
            by_side = tier.get("source_by_side")
            if isinstance(by_side, dict) and isinstance(by_side.get(sd), dict):
                return by_side[sd]
            break
    return {}


def persona_identity_for_assistant(assistant_id: str = "xiaoc") -> Any | None:
    """把助理身份桥接成 Persona ``PersonaIdentity``（人格引擎用其固定名字，不被行业名覆盖）。

    返回 ``None`` 表示该助理未声明固定身份（应退回 Persona 行业派生身份）。
    懒导入 PersonaIdentity，避免模块级耦合 persona 领域层。
    """
    entity = get_assistant(assistant_id)
    persona = entity.get("persona") or {}
    if not persona.get("fixed_identity_name"):
        return None
    from app.domain.persona.value_objects import PersonaIdentity

    return PersonaIdentity(
        name=str(entity.get("display_name") or "小C助理"),
        brief=str(persona.get("identity_brief") or entity.get("brief") or ""),
        business_domain="assistant",
        industry="",
    )


__all__ = [
    "load_ai_workforce_document",
    "assistant_tiers",
    "get_tier",
    "persona_shared_tiers",
    "tier_shares_persona",
    "can_call",
    "get_assistant",
    "xiaoc",
    "super_employees",
    "super_employee_ids",
    "factory_employees",
    "factory_employee_ids",
    "is_factory_employee",
    "xiaoc_display_name",
    "xiaoc_consult_title",
    "xiaoc_conversation_surfaces",
    "persona_identity_for_assistant",
    "contact_kinds",
    "dedicated_cs_label",
    "surface_composition",
    "contact_kind_sides",
    "platform_source_for_side",
]
