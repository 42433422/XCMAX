"""User-facing output contracts for the terminal client."""

from app.cli.brain_output import format_output, terminal_text


def test_chat_prints_answer_once_without_internal_trace_ids():
    value = {
        "success": True,
        "response": "您好！\n可以开始工作。",
        "data": {"text": "您好！\n可以开始工作。"},
        "run_id": "internal",
    }
    assert format_output(value, "chat") == "您好！\n可以开始工作。"


def test_status_exposes_unready_llm_even_when_desktop_is_healthy():
    value = {
        "success": True,
        "health": {"status": "degraded", "degradedReasons": ["LLM_RUNTIME_UNAVAILABLE"]},
        "desktop": {"runtimeStatus": "healthy"},
        "draft_execution_verified": False,
    }
    output = format_output(value, "status")
    assert "degraded" in output and "LLM_RUNTIME_UNAVAILABLE" in output
    assert "healthy" in output and "尚未验证" in output


def test_text_and_diff_cannot_send_escape_sequences_to_terminal():
    attack = "hello\x1b]52;c;clipboard\x07\n\tworld\x9b31m"
    output = format_output({"success": True, "unified_diff": attack}, "diff")
    assert "\x1b" not in output and "\x07" not in output and "\x9b" not in output
    assert r"\x1b]52;c;clipboard\x07" in output
    assert "\n\tworld" in output
    assert terminal_text("error\rhidden") == r"error\x0dhidden"


def test_partial_model_failure_and_unknown_response_remain_visible():
    value = {
        "success": False,
        "installed_local_models": {"models": []},
        "cloud_catalog": {"available": False, "error": "catalog unavailable"},
    }
    output = format_output(value, "models")
    assert "暂无模型" in output and "catalog unavailable" in output
    assert "推理已就绪" in output
    assert '"unexpected": 7' in format_output({"unexpected": 7}, "analyze")


def test_edit_is_clearly_a_proposal_and_diff_remains_readable():
    value = {
        "success": True,
        "edit_id": "edit_123",
        "unified_diff": "--- a/test\n+++ b/test\n+new\n",
    }
    output = format_output(value, "edit")
    assert "edit_123" in output and "尚未写入文件" in output and "+new\n" in output


def test_cloud_catalog_preserves_provider_failure_and_fallback_origin():
    value = {
        "success": True,
        "cloud_catalog": {
            "success": True,
            "data": {
                "providers": [
                    {
                        "label": "Provider",
                        "fetch_source": "fallback_only",
                        "error": "no_api_key",
                        "models": ["catalog-model"],
                    }
                ]
            },
        },
    }
    output = format_output(value, "models")
    assert "Provider [fallback_only] — no_api_key" in output
    assert "catalog-model" in output
    assert '"providers"' not in output
