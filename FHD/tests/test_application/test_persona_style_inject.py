"""平台员工 Persona 风格注入守卫(小C+平台员工共享人格;员工保留岗位身份只取风格)。"""

from __future__ import annotations

from app.application import persona_style_inject as inj
from app.application.employee_runtime.agent import EmployeeAgent
from app.domain.persona.entities import PersonaProfile
from app.domain.persona.value_objects import PersonaAxes, PersonaIdentity
from app.services.persona.prompt_builder import persona_style_section


def _profile(warmth=0.8, detail=0.8, proactivity=0.8, structure=0.8) -> PersonaProfile:
    return PersonaProfile(
        user_id="1",
        identity=PersonaIdentity(name="门店管家", brief="x", business_domain="retail", industry="零售业"),
        axes=PersonaAxes(warmth=warmth, detail=detail, proactivity=proactivity, structure=structure),
    )


# ── 纯风格段 ──


def test_style_section_only_style_no_identity():
    s = persona_style_section(_profile())
    assert s.endswith("。")
    assert "用口语化表达" in s  # warmth>=0.7
    # 风格段不含身份名(身份归各实体,Persona 只管怎么说话)
    assert "门店管家" not in s


def test_style_section_low_axes_differs():
    high = persona_style_section(_profile(0.8, 0.8, 0.8, 0.8))
    low = persona_style_section(_profile(0.0, 0.0, 0.0, 0.0))
    assert high != low


# ── 同步 fail-safe 取风格 ──


def test_style_for_user_zero_or_negative_empty():
    assert inj.persona_style_for_user(0) == ""
    assert inj.persona_style_for_user(-1) == ""
    assert inj.persona_style_for_user(None) == ""  # type: ignore[arg-type]


# ── 员工 config 注入(平台员工执行路径) ──


def test_augment_appends_style_keeps_identity(monkeypatch):
    monkeypatch.setattr(inj, "persona_style_for_user", lambda uid: "语气自然随和。")
    cfg = {"cognition": {"agent": {"system_prompt": "你是网站内容编辑。"}}}
    out = EmployeeAgent._augment_config_with_persona(cfg, 5)
    sp = out["cognition"]["agent"]["system_prompt"]
    assert "你是网站内容编辑。" in sp  # 员工岗位身份保留
    assert "对当前用户的沟通风格：" in sp
    assert "语气自然随和。" in sp
    # 原 config 未被原地修改(deepcopy)
    assert cfg["cognition"]["agent"]["system_prompt"] == "你是网站内容编辑。"


def test_augment_noop_when_no_style(monkeypatch):
    monkeypatch.setattr(inj, "persona_style_for_user", lambda uid: "")
    cfg = {"cognition": {"agent": {"system_prompt": "你是网站内容编辑。"}}}
    out = EmployeeAgent._augment_config_with_persona(cfg, 5)
    assert out is cfg  # 无风格 → 原样返回,零开销
