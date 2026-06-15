"""Unit tests for the multi-LLM provider system.

Each adapter is exercised with a stubbed ``urllib.request.urlopen`` so
the network is never hit. The tests focus on:

- The wire-format mapping (auth headers, request body shape).
- Provider auto-detection from model id / alias.
- Error normalisation (HTTP errors → :class:`LLMError`).

End-to-end smoke tests against real APIs are kept out of tree — they
require credentials and a network connection.
"""

from __future__ import annotations

import io
import json
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest

from vibe_coding.nl import (
    AnthropicLLM,
    DeepSeekLLM,
    LLMError,
    MoonshotLLM,
    OpenAICompatibleLLM,
    QwenLLM,
    ZhipuLLM,
    create_llm,
    detect_provider,
)
from vibe_coding.nl.providers import PROVIDER_PRESETS, ProviderInfo, register_provider


# ----------------------------------------------------- helpers


class _FakeResponse:
    def __init__(self, body: str | bytes, status: int = 200) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


@contextmanager
def _patched_urlopen(handler):
    captured: list[Any] = []

    def fake_urlopen(req, timeout=None, context=None):  # noqa: ARG001
        captured.append(req)
        return handler(req)

    with patch("urllib.request.urlopen", fake_urlopen):
        yield captured


def _openai_chat_response(content: str = "{\"ok\":true}") -> str:
    return json.dumps(
        {
            "id": "x",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}}
            ],
        }
    )


# ----------------------------------------------------- auto detection


@pytest.mark.parametrize(
    "model_or_alias,expected_provider",
    [
        ("qwen", "qwen"),
        ("qwen-max", "qwen"),
        ("qwen2-72b-instruct", "qwen"),
        ("tongyi", "qwen"),
        ("dashscope", "qwen"),
        ("zhipu", "zhipu"),
        ("glm-4", "zhipu"),
        ("glm-4-air", "zhipu"),
        ("kimi", "moonshot"),
        ("moonshot-v1-128k", "moonshot"),
        ("deepseek", "deepseek"),
        ("deepseek-coder", "deepseek"),
        ("claude", "anthropic"),
        ("claude-3-5-sonnet-latest", "anthropic"),
        ("gpt-4o-mini", "openai"),
        ("gpt", "openai"),
    ],
)
def test_detect_provider_resolves_alias_or_prefix(
    model_or_alias: str, expected_provider: str
) -> None:
    info = detect_provider(model_or_alias)
    assert info is not None
    assert info.name == expected_provider


def test_detect_provider_returns_none_for_unknown() -> None:
    assert detect_provider("totally-bespoke-model") is None


def test_register_provider_overrides_alias() -> None:
    sentinel_calls: list[Any] = []

    def fake_factory(**kw: Any):
        sentinel_calls.append(kw)

        class _C:
            def chat(self, *_a, **_k):
                return "{}"

        return _C()

    register_provider(
        ProviderInfo(
            name="custom-corp",
            factory=fake_factory,
            aliases=("corp",),
            model_prefixes=("corp-",),
            default_model="corp-base",
        )
    )
    try:
        info = detect_provider("corp")
        assert info is not None and info.name == "custom-corp"
        info2 = detect_provider("corp-large")
        assert info2 is not None and info2.name == "custom-corp"
        create_llm("corp", api_key="k")
        assert sentinel_calls and sentinel_calls[0]["model"] == "corp-base"
    finally:
        PROVIDER_PRESETS.pop("custom-corp", None)


# ----------------------------------------------------- factory


def test_create_llm_with_alias_uses_default_model() -> None:
    llm = create_llm("kimi", api_key="sk-test")
    assert isinstance(llm, MoonshotLLM)
    assert llm.model == "moonshot-v1-32k"


def test_create_llm_with_full_id_uses_id_as_model() -> None:
    llm = create_llm("qwen-max", api_key="sk-test")
    assert isinstance(llm, QwenLLM)
    assert llm.model == "qwen-max"


def test_create_llm_unknown_falls_back_to_compatible() -> None:
    llm = create_llm("acme-fancy-model", api_key="k", base_url="https://x.example/v1")
    assert isinstance(llm, OpenAICompatibleLLM)
    assert llm.model == "acme-fancy-model"


def test_create_llm_passes_through_temperature_and_max_tokens() -> None:
    llm = create_llm("kimi", api_key="k", temperature=0.7, max_tokens=2048)
    assert isinstance(llm, MoonshotLLM)
    assert llm.temperature == pytest.approx(0.7)
    assert llm.max_tokens == 2048


# ----------------------------------------------------- OpenAI-compat wire test


def test_openai_compat_sends_bearer_and_messages() -> None:
    llm = OpenAICompatibleLLM(
        api_key="sk-x", model="m1", base_url="https://gw.example/v1"
    )
    seen: dict[str, Any] = {}

    def handler(req):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization") or req.headers.get("authorization")
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(_openai_chat_response("{\"hi\":1}"))

    with _patched_urlopen(handler):
        out = llm.chat("sys", "user", json_mode=True)
    assert out == "{\"hi\":1}"
    assert seen["url"] == "https://gw.example/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-x"
    assert seen["body"]["model"] == "m1"
    assert seen["body"]["messages"][0]["role"] == "system"
    assert seen["body"]["messages"][1]["content"] == "user"
    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_openai_compat_skips_response_format_when_disabled() -> None:
    llm = OpenAICompatibleLLM(api_key="k", model="m", base_url="https://x.example/v1")

    def handler(req):
        body = json.loads(req.data.decode("utf-8"))
        assert "response_format" not in body
        return _FakeResponse(_openai_chat_response("text"))

    with _patched_urlopen(handler):
        llm.chat("s", "u", json_mode=False)


def test_openai_compat_extracts_list_content() -> None:
    """Some providers return ``content`` as a list of typed parts."""
    llm = OpenAICompatibleLLM(api_key="k", model="m")

    def handler(req):  # noqa: ARG001
        return _FakeResponse(
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "hello "},
                                    {"type": "text", "text": "world"},
                                ]
                            }
                        }
                    ]
                }
            )
        )

    with _patched_urlopen(handler):
        out = llm.chat("s", "u")
    assert out == "hello \nworld"


def test_openai_compat_http_error_raises_llm_error() -> None:
    import urllib.error

    llm = OpenAICompatibleLLM(api_key="k", model="m")

    def handler(req):
        raise urllib.error.HTTPError(
            req.full_url,
            429,
            "Too Many Requests",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"error":"rate_limit"}'),
        )

    with _patched_urlopen(handler):
        with pytest.raises(LLMError) as exc_info:
            llm.chat("s", "u")
    assert "429" in str(exc_info.value)


# ----------------------------------------------------- vendor specifics


def test_qwen_default_endpoint_and_extra_search_flag() -> None:
    llm = QwenLLM(api_key="sk", enable_search=True)

    def handler(req):
        body = json.loads(req.data.decode("utf-8"))
        assert "compatible-mode" in req.full_url
        assert body["extra_body"]["enable_search"] is True
        return _FakeResponse(_openai_chat_response("ok"))

    with _patched_urlopen(handler):
        llm.chat("s", "u", json_mode=False)


def test_zhipu_default_endpoint() -> None:
    llm = ZhipuLLM(api_key="sk")

    def handler(req):
        assert "open.bigmodel.cn" in req.full_url
        return _FakeResponse(_openai_chat_response("ok"))

    with _patched_urlopen(handler):
        llm.chat("s", "u", json_mode=False)


def test_moonshot_default_endpoint() -> None:
    llm = MoonshotLLM(api_key="sk")

    def handler(req):
        assert "api.moonshot.cn" in req.full_url
        return _FakeResponse(_openai_chat_response("ok"))

    with _patched_urlopen(handler):
        llm.chat("s", "u", json_mode=False)


def test_deepseek_default_endpoint() -> None:
    llm = DeepSeekLLM(api_key="sk")

    def handler(req):
        assert "api.deepseek.com" in req.full_url
        return _FakeResponse(_openai_chat_response("ok"))

    with _patched_urlopen(handler):
        llm.chat("s", "u", json_mode=False)


# ----------------------------------------------------- env fallback


def test_qwen_picks_dashscope_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "from-env")
    llm = QwenLLM()
    assert llm.api_key == "from-env"


def test_kimi_picks_moonshot_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOONSHOT_API_KEY", "from-moonshot")
    llm = MoonshotLLM()
    assert llm.api_key == "from-moonshot"


def test_zhipu_picks_zhipuai_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZHIPUAI_API_KEY", "from-zhipuai")
    llm = ZhipuLLM()
    assert llm.api_key == "from-zhipuai"


# ----------------------------------------------------- Anthropic


def test_anthropic_uses_x_api_key_header() -> None:
    llm = AnthropicLLM(api_key="sk-ant", model="claude-3-5-sonnet-latest")

    seen: dict[str, Any] = {}

    def handler(req):
        seen["api_key"] = req.headers.get("X-api-key") or req.headers.get("x-api-key")
        seen["version"] = req.headers.get("Anthropic-version") or req.headers.get(
            "anthropic-version"
        )
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(
            json.dumps(
                {
                    "content": [
                        {"type": "text", "text": "{\"ok\":true}"},
                    ]
                }
            )
        )

    with _patched_urlopen(handler):
        out = llm.chat("system prompt", "user msg", json_mode=True)
    assert out == "{\"ok\":true}"
    assert seen["api_key"] == "sk-ant"
    assert seen["version"]
    assert seen["body"]["model"] == "claude-3-5-sonnet-latest"
    assert seen["body"]["messages"][0]["role"] == "user"
    # JSON-mode is enforced via system-prompt addendum.
    assert "JSON" in seen["body"]["system"]


def test_anthropic_trims_markdown_fences_in_json_mode() -> None:
    llm = AnthropicLLM(api_key="sk-ant")

    def handler(req):  # noqa: ARG001
        return _FakeResponse(
            json.dumps(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": "Sure, here is the JSON:\n```json\n{\"v\":1}\n```\n",
                        }
                    ]
                }
            )
        )

    with _patched_urlopen(handler):
        out = llm.chat("s", "u", json_mode=True)
    assert json.loads(out) == {"v": 1}
