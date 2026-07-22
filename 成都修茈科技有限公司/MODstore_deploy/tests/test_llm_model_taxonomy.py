"""llm_model_taxonomy 启发式分类回归。"""

from __future__ import annotations

import pytest

from modstore_server.llm_model_taxonomy import (
    build_models_detailed,
    classify_model,
    discover_model_capabilities,
    supports_trial_chat,
)


@pytest.mark.parametrize(
    "provider,mid,expected",
    [
        ("openai", "gpt-4o", "vlm"),
        ("openai", "gpt-4o-mini", "vlm"),
        ("openai", "gpt-3.5-turbo", "llm"),
        ("openai", "dall-e-3", "image"),
        ("openai", "text-embedding-3-small", "embedding"),
        ("deepseek", "deepseek-chat", "llm"),
        ("anthropic", "claude-3-5-sonnet-20241022", "vlm"),
        ("anthropic", "claude-2.1", "llm"),
        ("google", "gemini-2.0-flash", "vlm"),
        ("google", "gemini-1.0-pro", "llm"),
        ("google", "imagen-3.0-generate-002", "image"),
        ("siliconflow", "deepseek-ai/DeepSeek-V3", "llm"),
        ("siliconflow", "stabilityai/stable-diffusion-xl-base-1.0", "image"),
        ("openrouter", "openai/gpt-4o", "vlm"),
        ("dashscope", "qwen-plus", "llm"),
        ("dashscope", "qwen-vl-max", "vlm"),
        ("dashscope", "wanx-v1", "image"),
        ("moonshot", "moonshot-v1-128k-vision-preview", "vlm"),
        ("moonshot", "kimi-latest", "llm"),
        ("minimax", "abab6.5s-chat", "llm"),
        ("minimax", "MiniMax-Video-01", "video"),
        ("doubao", "doubao-1.5-pro-32k", "llm"),
        ("doubao", "doubao-1.5-vision-pro-32k", "vlm"),
        ("doubao", "doubao-seedream-4-0-250828", "image"),
        ("doubao", "doubao-seedance-1-0-lite-250528", "video"),
        ("openai", "gpt-4o-mini-tts", "audio"),
        ("openai", "whisper-1", "audio"),
        ("xiaomi", "mimo-v2.5-asr", "audio"),
        ("siliconflow", "BAAI/bge-reranker-v2-m3", "rerank"),
    ],
)
def test_classify_model(provider: str, mid: str, expected: str) -> None:
    assert classify_model(provider, mid) == expected


def test_supports_trial_chat() -> None:
    assert supports_trial_chat("llm") is True
    assert supports_trial_chat("vlm") is True
    assert supports_trial_chat("image") is False


def test_build_models_detailed_sorted() -> None:
    rows = build_models_detailed(
        "openai",
        [
            "dall-e-3",
            "gpt-4o",
            "text-embedding-3-small",
            "gpt-3.5-turbo",
            "omni-moderation-latest",
        ],
    )
    cats = [r["category"] for r in rows]
    assert cats.index("llm") < cats.index("vlm")
    assert cats.index("vlm") < cats.index("image")
    assert cats[-1] == "other"


def test_openrouter_declared_modalities_and_features_take_priority() -> None:
    profile = discover_model_capabilities(
        "openrouter",
        "vendor/native-video-model",
        {
            "architecture": {
                "input_modalities": ["text", "image"],
                "output_modalities": ["video"],
            },
            "supported_parameters": ["tools", "response_format"],
            "_catalog_origin": "provider_api",
        },
    )

    assert profile["category"] == "video"
    assert profile["output_modalities"] == ["video"]
    assert "video_generation" in profile["operations"]
    assert "tool_calling" in profile["operations"]
    assert profile["runtime_selectable"] is False
    assert profile["source"] == "provider_metadata"


def test_google_generation_methods_are_dynamic_capability_evidence() -> None:
    profile = discover_model_capabilities(
        "google",
        "gemini-future-model",
        {
            "supportedGenerationMethods": ["generateContent", "countTokens"],
            "inputTokenLimit": 123456,
            "outputTokenLimit": 8192,
            "_catalog_origin": "provider_api",
        },
    )

    assert profile["operations"] == ["chat"]
    assert profile["runtime_selectable"] is True
    assert profile["source"] == "provider_metadata"


def test_tts_capability_is_preserved_but_not_runtime_selectable() -> None:
    rows = build_models_detailed("openai", ["gpt-4o-mini-tts"])
    row = rows[0]

    assert row["category"] == "audio"
    assert row["capabilities"]["input_modalities"] == ["text"]
    assert row["capabilities"]["output_modalities"] == ["audio"]
    assert row["capabilities"]["operations"] == ["text_to_speech"]
    assert row["runtime_selectable"] is False
    assert row["capability_source"] == "model_id_inference"


def test_mimo_audio_variants_are_not_chat_runtime_models() -> None:
    rows = build_models_detailed(
        "xiaomi",
        [
            "mimo-v2.5-asr",
            "mimo-v2.5-tts-voiceclone",
            "mimo-v2.5-tts-voicedesign",
        ],
    )
    by_id = {row["id"]: row for row in rows}

    assert by_id["mimo-v2.5-asr"]["capabilities"]["operations"] == ["speech_to_text"]
    assert by_id["mimo-v2.5-asr"]["runtime_selectable"] is False
    assert (
        "voice_cloning"
        in by_id["mimo-v2.5-tts-voiceclone"]["capabilities"]["operations"]
    )
    assert (
        "audio" in by_id["mimo-v2.5-tts-voiceclone"]["capabilities"]["input_modalities"]
    )
    assert (
        "voice_design"
        in by_id["mimo-v2.5-tts-voicedesign"]["capabilities"]["operations"]
    )


def test_provider_metadata_is_sanitized_and_returned_with_limits() -> None:
    rows = build_models_detailed(
        "together",
        ["vendor/chat-model"],
        metadata_by_id={
            "vendor/chat-model": {
                "id": "vendor/chat-model",
                "type": "chat",
                "display_name": "Chat Model",
                "context_length": 32768,
                "api_key": "must-not-leak",
                "_catalog_origin": "provider_api",
            }
        },
    )
    row = rows[0]

    assert row["display_name"] == "Chat Model"
    assert row["provider_metadata"]["context_window"] == 32768
    assert "api_key" not in row["provider_metadata"]
    assert row["runtime_selectable"] is True
