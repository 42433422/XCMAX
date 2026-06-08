"""llm_model_taxonomy 启发式分类回归。"""

from __future__ import annotations

import pytest

from modstore_server.llm_model_taxonomy import (
    build_models_detailed,
    classify_model,
    supports_trial_chat,
)


@pytest.mark.parametrize(
    "provider,mid,expected",
    [
        ("openai", "gpt-4o", "vlm"),
        ("openai", "gpt-4o-mini", "vlm"),
        ("openai", "gpt-3.5-turbo", "llm"),
        ("openai", "dall-e-3", "image"),
        ("openai", "text-embedding-3-small", "other"),
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
        ["dall-e-3", "gpt-4o", "text-embedding-3-small", "gpt-3.5-turbo"],
    )
    cats = [r["category"] for r in rows]
    assert cats.index("llm") < cats.index("vlm")
    assert cats.index("vlm") < cats.index("image")
    assert cats[-1] == "other"
