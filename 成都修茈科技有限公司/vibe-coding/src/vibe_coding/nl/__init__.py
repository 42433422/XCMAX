"""Natural-language layer of vibe coding: prompts and LLM clients.

The :mod:`.providers` subpackage ships ready-made adapters for Qwen,
Zhipu GLM, Moonshot Kimi, DeepSeek, and Anthropic Claude. Use
:func:`create_llm` to pick the right adapter from a model id or alias.
"""

from __future__ import annotations

from .llm import LLMClient, LLMError, MockLLM, OpenAILLM
from .parsing import (
    JSONParseError,
    extract_first_object,
    safe_parse_json,
    safe_parse_json_object,
)
from .prompts import (
    BRIEF_FIRST_CODE_PROMPT,
    BRIEF_FIRST_SPEC_PROMPT,
    CODE_DIRECT_PROMPT,
    CODE_HUNK_REPAIR_PROMPT,
    CODE_REPAIR_PROMPT,
    MULTI_FILE_EDIT_PROMPT,
    MULTI_FILE_REPAIR_PROMPT,
    WORKFLOW_PROMPT,
)
from .providers import (
    AnthropicLLM,
    DeepSeekLLM,
    MoonshotLLM,
    OpenAICompatibleLLM,
    QwenLLM,
    ZhipuLLM,
    create_llm,
    detect_provider,
)

__all__ = [
    "AnthropicLLM",
    "BRIEF_FIRST_CODE_PROMPT",
    "BRIEF_FIRST_SPEC_PROMPT",
    "CODE_DIRECT_PROMPT",
    "CODE_HUNK_REPAIR_PROMPT",
    "CODE_REPAIR_PROMPT",
    "DeepSeekLLM",
    "JSONParseError",
    "LLMClient",
    "LLMError",
    "MockLLM",
    "MULTI_FILE_EDIT_PROMPT",
    "MULTI_FILE_REPAIR_PROMPT",
    "MoonshotLLM",
    "OpenAICompatibleLLM",
    "OpenAILLM",
    "QwenLLM",
    "WORKFLOW_PROMPT",
    "ZhipuLLM",
    "create_llm",
    "detect_provider",
    "extract_first_object",
    "safe_parse_json",
    "safe_parse_json_object",
]
