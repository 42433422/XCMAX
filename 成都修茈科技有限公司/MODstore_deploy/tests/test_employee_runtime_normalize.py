"""Legacy manifest DeepSeek → auto normalization."""

from __future__ import annotations

from modstore_server.employee_runtime import normalize_manifest_legacy_deepseek_to_auto


def test_normalize_deepseek_model_to_auto():
    m = {
        "employee_config_v2": {
            "cognition": {
                "agent": {
                    "model": {"provider": "deepseek", "model_name": "deepseek-chat"},
                }
            }
        }
    }
    normalize_manifest_legacy_deepseek_to_auto(m)
    assert m["employee_config_v2"]["cognition"]["agent"]["model"]["provider"] == "auto"
    assert m["employee_config_v2"]["cognition"]["agent"]["model"]["model_name"] == "auto"


def test_normalize_skips_explicit_other_provider():
    m = {
        "employee_config_v2": {
            "cognition": {"agent": {"model": {"provider": "openai", "model_name": "gpt-4o-mini"}}}
        }
    }
    normalize_manifest_legacy_deepseek_to_auto(m)
    assert m["employee_config_v2"]["cognition"]["agent"]["model"]["provider"] == "openai"
