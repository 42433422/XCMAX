"""AI 员工三阶级 + 小C助理 SSOT 守卫测试。

覆盖：
1. 真相源 ``config/ai_workforce.json`` 结构完整（三阶级 + 小C身份字段）。
2. 人格共享规则：assistant + platform 共享、super 独立（员工系统↔人格系统的联系）。
3. 调用链：assistant → super → platform，单向向下。
4. 小C身份文案统一从 SSOT 派生（display_name / consult_title / persona identity 固定名）。
5. 防漂移 ratchet：mobile_api_extensions.py 不再硬编码 "小C助理" 字面量。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.mod_sdk import assistant_ssot

_FHD = Path(__file__).resolve().parents[2]
_SSOT_FILE = _FHD / "config" / "ai_workforce.json"


# ── 1. 真相源文件结构 ────────────────────────────────────────────────────


def test_ssot_file_structure_intact():
    doc = json.loads(_SSOT_FILE.read_text(encoding="utf-8"))
    assert doc.get("schema_version") == 1
    tiers = doc["tiers"]
    assert {t["id"] for t in tiers} == {"assistant", "super", "platform"}
    assert sorted(t["rank"] for t in tiers) == [1, 2, 3]
    xiaoc = doc["assistants"]["xiaoc"]
    for field in ("id", "tier", "display_name", "short_name", "avatar_letter", "brief"):
        assert xiaoc.get(field), f"小C缺字段 {field}"
    assert xiaoc["tier"] == "assistant"


def test_loader_matches_file():
    """加载器读出的小C身份与磁盘真相源一致（非仅兜底）。"""
    doc = json.loads(_SSOT_FILE.read_text(encoding="utf-8"))
    assert assistant_ssot.xiaoc_display_name() == doc["assistants"]["xiaoc"]["display_name"]


# ── 2. 人格共享规则（员工系统 ↔ 人格系统）────────────────────────────────


def test_persona_sharing_rule():
    shared = assistant_ssot.persona_shared_tiers()
    assert "assistant" in shared
    assert "platform" in shared
    assert "super" not in shared  # 超级员工独立人格、不纳入
    assert assistant_ssot.tier_shares_persona("assistant") is True
    assert assistant_ssot.tier_shares_persona("super") is False


# ── 3. 调用链（单向向下）────────────────────────────────────────────────


def test_call_chain_top_down():
    # 允许：assistant → super → platform
    assert assistant_ssot.can_call("assistant", "super") is True
    assert assistant_ssot.can_call("super", "platform") is True
    # 禁止：跨级 / 反向 / 末级外呼
    assert assistant_ssot.can_call("assistant", "platform") is False
    assert assistant_ssot.can_call("super", "assistant") is False
    assert assistant_ssot.can_call("platform", "super") is False
    assert assistant_ssot.can_call("platform", "assistant") is False


# ── 4. 小C身份派生 ──────────────────────────────────────────────────────


def test_xiaoc_identity_helpers():
    assert assistant_ssot.xiaoc_display_name() == "小C助理"
    assert assistant_ssot.xiaoc_consult_title() == "小C助理咨询"
    assert assistant_ssot.xiaoc().get("avatar_letter") == "C"


def test_persona_identity_fixed_name():
    """小C以固定名字接入 Persona 人格引擎（不被行业派生名覆盖）。"""
    ident = assistant_ssot.persona_identity_for_assistant("xiaoc")
    assert ident is not None
    assert ident.name == "小C助理"
    assert ident.business_domain == "assistant"


# ── 5. 防漂移 ratchet ────────────────────────────────────────────────────


def test_no_hardcoded_xiaoc_in_mobile_routes():
    """已接 SSOT 的路由文件不得再出现硬编码的 "小C助理" 字面量。"""
    routes = _FHD / "app" / "fastapi_routes" / "mobile_api_extensions.py"
    text = routes.read_text(encoding="utf-8")
    assert "小C助理" not in text, "mobile_api_extensions.py 仍硬编码小C名，请改用 assistant_ssot"


# ── 6. 桌面端/手机端 联系人组成矩阵 ──────────────────────────────────────


def test_surface_composition_matrix():
    """四格组成与用户定义的目标矩阵一致。"""
    assert assistant_ssot.surface_composition("desktop", "enterprise") == [
        "platform",
        "super",
        "dedicated_cs",
    ]
    assert assistant_ssot.surface_composition("desktop", "admin") == ["platform", "super"]
    assert assistant_ssot.surface_composition("mobile", "enterprise") == [
        "assistant",
        "dedicated_cs",
        "platform",
        "super",
    ]
    assert assistant_ssot.surface_composition("mobile", "admin") == [
        "assistant",
        "platform",
        "super",
    ]


def test_dedicated_cs_enterprise_only_invariant():
    """专属客服只在企业端出现;管理端任何端都不得含它(它就是被指向的管理端)。"""
    assert assistant_ssot.contact_kind_sides("dedicated_cs") == ("enterprise",)
    for device in ("desktop", "mobile"):
        assert "dedicated_cs" not in assistant_ssot.surface_composition(device, "admin")
        assert "dedicated_cs" in assistant_ssot.surface_composition(device, "enterprise")


def test_xiaoc_desktop_is_floating_not_in_message_list():
    """小C是电脑端悬浮助手,不进消息页列表;但进手机端联系人。"""
    assert "assistant" not in assistant_ssot.surface_composition("desktop", "enterprise")
    assert "assistant" not in assistant_ssot.surface_composition("desktop", "admin")
    assert "assistant" in assistant_ssot.surface_composition("mobile", "enterprise")
    assert "assistant" in assistant_ssot.surface_composition("mobile", "admin")


def test_xiaoc_conversation_surfaces_floating_and_sidebar():
    """小C智能对话=电脑端 悬浮窗 + 侧栏 两个互斥入口,同一会话引擎。

    这是「对话入口」轴(≠联系人列表轴):小C不进桌面消息列表,但以悬浮窗/侧栏提供智能对话。
    """
    cs = assistant_ssot.xiaoc_conversation_surfaces()
    desktop = cs.get("desktop") or []
    assert {s.get("id") for s in desktop} == {"floating", "sidebar"}
    assert cs.get("mutual_exclusive") is True
    # 与"小C不进桌面消息列表"不矛盾:对话入口 ≠ 联系人条目
    assert "assistant" not in assistant_ssot.surface_composition("desktop", "admin")


def test_platform_employees_differ_by_side():
    """管理端平台员工(六线) ≠ 企业端平台员工(四层):来源声明必须不同。"""
    admin_src = assistant_ssot.platform_source_for_side("admin")
    ent_src = assistant_ssot.platform_source_for_side("enterprise")
    assert admin_src and ent_src
    assert admin_src.get("where") != ent_src.get("where")
    assert "departments" in admin_src.get("where", "")
    assert "enterprise_employees" in ent_src.get("where", "")


# ── 7. 超级员工(2级)身份 SSOT ────────────────────────────────────────────


def test_super_employees_ssot_ids():
    assert assistant_ssot.super_employee_ids() == {
        "claude-super-employee",
        "codex-super-employee",
        "cursor-super-employee",
        "trae-super-employee",
    }
    sup = assistant_ssot.super_employees()
    assert sup["claude-super-employee"]["display_name"] == "超级员工-Claude"
    assert sup["codex-super-employee"]["display_name"] == "超级员工-Codex"


def test_super_employee_ssot_matches_service_profiles():
    """SSOT 身份与 super_employee_service 运行 profile 不漂移(id/名一致)。"""
    from app.application.super_employee_service import CLAUDE_PROFILE, CODEX_PROFILE

    sup = assistant_ssot.super_employees()
    for profile in (CLAUDE_PROFILE, CODEX_PROFILE):
        assert profile.employee_id in sup
        assert sup[profile.employee_id]["display_name"] == profile.employee_name
