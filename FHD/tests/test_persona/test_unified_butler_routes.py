# FHD/tests/test_persona/test_unified_butler_routes.py
"""人格系统合并守卫：butler 写端点(/infer、/interaction)不再写 butler_user_profiles，

Persona-A 为单一真相源。读端点(/profile)已 persona-first（见 test_persona_butler_bridge）。
本测试钉死「写路径已并入 persona」——防止 butler 第二源写回潮。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.fastapi_routes.domains.misc import routes as misc_routes

_FAKE_PERSONA_VIEW = {
    "user_id": 7,
    "identity_primary": "业务管家",
    "identity_composite": "业务管家",
    "four_axes": {"warmth": 80, "verbosity": 50, "proactiveness": 60, "structuredness": 70},
    "mbti_type": "ENFJ",
    "mbti_confidence": 0.42,
    "interaction_count": 12,
    "last_inferred_at": None,
}


def _req():
    request = MagicMock()
    request.headers = {}  # _resolve_user_id_int → 默认/ body 取 user_id
    return request


def test_infer_returns_persona_view_and_does_not_write_butler():
    butler_spy = MagicMock()
    with (
        patch(
            "app.application.persona_butler_bridge.persona_view_for_user",
            return_value=_FAKE_PERSONA_VIEW,
        ),
        patch.object(misc_routes, "_butler_profile_service", return_value=butler_spy),
    ):
        resp = misc_routes.butler_profile_infer(
            _req(),
            {"user_id": 7, "conversations": [{"user_message": "hi"}], "mod_hints": ["考勤"]},
        )

    assert resp["success"] is True
    assert resp["profile"] == _FAKE_PERSONA_VIEW  # 返回 persona 派生视图
    assert resp["inference"]["source"] == "persona"
    # 关键：未触碰 butler（无 MBTI 推断 / 写 butler_user_profiles）
    butler_spy.get_or_create_profile.assert_not_called()
    butler_spy.update_profile.assert_not_called()


def test_infer_falls_back_to_butler_view_only_when_no_persona():
    """无 persona 画像（新用户未对话）时回退 butler 默认视图——这是读回退，非写。"""
    butler_spy = MagicMock()
    butler_spy.get_profile_view.return_value = {"user_id": 7, "identity_primary": "业务管家"}
    with (
        patch("app.application.persona_butler_bridge.persona_view_for_user", return_value=None),
        patch.object(misc_routes, "_butler_profile_service", return_value=butler_spy),
    ):
        resp = misc_routes.butler_profile_infer(_req(), {"user_id": 7})

    assert resp["success"] is True
    butler_spy.get_profile_view.assert_called_once()  # 只读默认
    butler_spy.update_profile.assert_not_called()  # 仍不写


def test_interaction_does_not_write_butler():
    butler_spy = MagicMock()
    with patch.object(misc_routes, "_butler_profile_service", return_value=butler_spy):
        resp = misc_routes.butler_profile_record_interaction(
            _req(),
            {"user_message": "hi", "assistant_message": "hello", "interrupted": True},
        )

    assert resp["success"] is True
    butler_spy.record_interaction.assert_not_called()  # 互动由对话流喂 persona，不写 butler
