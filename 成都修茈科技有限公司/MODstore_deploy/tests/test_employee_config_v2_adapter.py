"""employee_config_v2 → executor 适配层。"""

from __future__ import annotations

from modstore_server.employee_config_v2_adapter import (
    needs_executor_translation,
    translate_v2_to_executor_config,
)


def test_translate_vision_sets_image_type():
    v2 = {
        "identity": {"id": "p1", "name": "Test"},
        "perception": {"vision": {"enabled": True, "supported_formats": ["png"]}},
        "cognition": {
            "agent": {
                "system_prompt": "Hello",
                "model": {"provider": "deepseek", "model_name": "deepseek-chat"},
            }
        },
    }
    assert needs_executor_translation(v2) is True
    out = translate_v2_to_executor_config(v2)
    assert out["perception"]["type"] == "image"


def test_translate_document_priority_over_vision():
    v2 = {
        "identity": {"id": "p1"},
        "perception": {
            "vision": {"enabled": True},
            "document": {"enabled": True, "supported_formats": ["pdf"]},
        },
        "cognition": {"agent": {"system_prompt": "x"}},
    }
    out = translate_v2_to_executor_config(v2)
    assert out["perception"]["type"] == "document"


def test_translate_preserves_web_rankings():
    v2 = {"perception": {"type": "web_rankings"}, "actions": {"handlers": ["echo"]}}
    assert needs_executor_translation(v2) is False
    out = translate_v2_to_executor_config(v2)
    assert out["perception"]["type"] == "web_rankings"


def test_translate_merges_role_rules_few_shot_into_system_prompt():
    v2 = {
        "identity": {"id": "x"},
        "cognition": {
            "agent": {
                "system_prompt": "用户段",
                "role": {"name": "助手", "persona": "耐心", "tone": "friendly", "expertise": ["A"]},
                "behavior_rules": ["规则1", {"name": "R2", "description": "说明"}],
                "few_shot_examples": [{"input": "hi", "output": "hey", "explanation": "礼貌"}],
                "model": {"provider": "deepseek", "model_name": "deepseek-chat"},
            }
        },
    }
    out = translate_v2_to_executor_config(v2)
    sp = out["cognition"]["agent"]["system_prompt"]
    assert "【角色设定】" in sp
    assert "助手" in sp
    assert "【行为约束】" in sp and "规则1" in sp
    assert "【少样本示例】" in sp and "hi" in sp
    assert "用户段" in sp
    assert sp.index("【角色设定】") < sp.index("用户段")


def test_translate_voice_output_adds_handler():
    v2 = {
        "identity": {"id": "z"},
        "actions": {
            "handlers": ["echo"],
            "voice_output": {"enabled": True, "tts": {"provider": "aliyun"}},
        },
    }
    out = translate_v2_to_executor_config(v2)
    assert "voice_output" in out["actions"]["handlers"]


def test_translate_default_handlers_echo_when_missing():
    v2 = {
        "identity": {"id": "z"},
        "actions": {"voice_output": {"enabled": True, "tts": {"provider": "aliyun"}}},
    }
    out = translate_v2_to_executor_config(v2)
    assert out["actions"]["handlers"][0] == "echo"
    assert "voice_output" in out["actions"]["handlers"]
