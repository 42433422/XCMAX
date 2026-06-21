# FHD/tests/test_persona/test_unified_butler_routes.py
"""人格系统合并 + 单一派生守卫。

合并后 Persona-A 为唯一真相源：
1. 写：/infer、/interaction 不再写 butler_user_profiles（互动由对话流喂 persona）。
2. 派生：所有视图（含新用户默认）只经 persona_butler_bridge 一处派生；
   butler 侧 derive_mbti / 推断引擎已退役（不再有第二套派生）。
本测试钉死以上，防 butler 第二源/第二派生回潮。
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

from app.fastapi_routes.domains.misc import routes as misc_routes

_FAKE_PERSONA_VIEW = {
    "user_id": 7,
    "identity_primary": "考勤管家",
    "identity_composite": "考勤管家",
    "four_axes": {"warmth": 80, "verbosity": 50, "proactiveness": 60, "structuredness": 70},
    "mbti_type": "ENFJ",
    "mbti_confidence": 0.42,
    "interaction_count": 12,
    "last_inferred_at": None,
}


def _req():
    request = MagicMock()
    request.headers = {}  # _resolve_user_id_int → body/默认取 user_id
    return request


def test_infer_returns_persona_view():
    """有画像：/infer 返回 persona 派生视图（source=persona），不跑 butler 推断。"""
    with patch(
        "app.application.persona_butler_bridge.persona_view_for_user",
        return_value=_FAKE_PERSONA_VIEW,
    ):
        resp = misc_routes.butler_profile_infer(
            _req(), {"user_id": 7, "conversations": [{"user_message": "hi"}]}
        )
    assert resp["success"] is True
    assert resp["profile"] == _FAKE_PERSONA_VIEW
    assert resp["inference"]["source"] == "persona"


def test_no_persona_falls_back_to_bridge_default_not_butler():
    """无画像（新用户）：仍由桥派生中性默认视图——单一派生，杜绝 butler derive_mbti。"""
    with patch("app.application.persona_butler_bridge.persona_view_for_user", return_value=None):
        resp = misc_routes.butler_profile_infer(_req(), {"user_id": 7})
    assert resp["success"] is True
    view = resp["profile"]
    # 桥对中性 PersonaProfile(四轴0.5) 的确定性派生：四轴全 50、默认身份、MBTI 由四轴推
    assert view["four_axes"] == {
        "warmth": 50,
        "verbosity": 50,
        "proactiveness": 50,
        "structuredness": 50,
    }
    assert view["identity_primary"] == "业务管家"
    assert view["mbti_type"] == "ENFJ"  # 0.5≥0.5 → E/N/F/J
    assert resp["inference"]["source"] == "persona"


def test_interaction_does_not_write_butler():
    """/interaction 不再独立写 butler（互动由对话流喂 persona）。"""
    resp = misc_routes.butler_profile_record_interaction(
        _req(), {"user_message": "hi", "assistant_message": "hello", "interrupted": True}
    )
    assert resp["success"] is True
    assert resp.get("source") == "persona"


def test_butler_inference_engine_retired():
    """孤儿第二派生引擎 butler_profile_inference 已退役（导入应失败），防回潮。"""
    try:
        importlib.import_module("app.application.butler_profile_inference")
    except ModuleNotFoundError:
        return  # 期望：模块已删除
    raise AssertionError("butler_profile_inference 应已退役删除，但仍可导入（第二派生回潮）")
