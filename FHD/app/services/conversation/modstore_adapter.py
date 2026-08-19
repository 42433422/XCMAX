# ruff: noqa: E402, F401
"""
修茈市场(MODstore)平台代理适配器

通过修茈市场统一LLM接口调用所有模型（一个密钥/接口 → 20+厂商）

特性：
- 统一入口：POST /api/llm/chat
- 自动路由：根据provider/model自动选择厂商
- 密钥管理：平台自动解析（用户BYOK > 平台密钥）
- 计费集成：自动钱包预授权/结算
- 智能降级：配额/限流失败时自动切换备用模型（桌面侧候选重试 + 市场 allow_failover）
- ✨ 会话集成：自动从FHD登录Session获取Token（无需手动配置）

使用方式：
    # 方式1: 环境变量全局配置
    set MODSTORE_PLATFORM_URL=http://127.0.0.1:8765
    set MODSTORE_AUTH_TOKEN=your_token  (可选，不设则从session获取)

    # 方式2: 代码中创建（推荐用于请求级别）
    adapter = ModstorePlatformAdapter.from_session(
        session_id="abc123",  # 从cookie或header获取
        request=request_obj   # FastAPI Request对象（可选）
    )

    # 方式3: 从环境变量创建
    adapter = create_modstore_adapter_from_env()
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, cast

import httpx

from app.infrastructure.llm import modstore_adapter_failover as _mfailover
from app.infrastructure.llm.modstore_chat_failover import is_market_chat_failoverable
from app.infrastructure.llm.modstore_response_normalize import normalize_market_chat_response
from app.infrastructure.modstore_transport import (
    httpx_sync_client as _httpx_sync_client,
)
from app.infrastructure.modstore_transport import (
    iter_market_sse_data_payloads as _iter_transport_sse_data_payloads,
)
from app.infrastructure.modstore_transport import (
    iter_market_transport_plans as _iter_market_transport_plans,  # noqa: F401
)
from app.infrastructure.modstore_transport import (
    market_connect_attempts as _market_connect_attempts,  # noqa: F401
)
from app.infrastructure.modstore_transport import (
    market_connect_timeout as _market_connect_timeout,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_VISION_HINT_RE = re.compile(
    r"vision|vl-|vlm|deepseek-vl|qwen-vl|llava|omni|gpt-4o|gpt-4\.1|"
    r"gpt-4-turbo|gemini-1\.5|gemini-2|claude-3|claude-sonnet|claude-opus|多模态",
    re.IGNORECASE,
)
_CATALOG_CACHE_TTL_SECONDS = 300.0
_CATALOG_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_CATALOG_CACHE_LOCK = threading.Lock()


def _catalog_model_vision_support(
    catalog: dict[str, Any], provider: str, model: str
) -> bool | None:
    payload = catalog.get("data") if isinstance(catalog.get("data"), dict) else catalog
    providers = payload.get("providers") if isinstance(payload, dict) else None
    if not isinstance(providers, list):
        return True if _VISION_HINT_RE.search(model or "") else None
    for block in providers:
        if not isinstance(block, dict) or str(block.get("provider") or "").lower() != provider:
            continue
        detailed = block.get("models_detailed")
        if not isinstance(detailed, list):
            break
        for row in detailed:
            if not isinstance(row, dict) or str(row.get("id") or "") != model:
                continue
            capability = row.get("capability")
            effective = (
                str(capability.get("effective_category") or "").lower()
                if isinstance(capability, dict)
                else ""
            )
            category = str(row.get("category") or effective).lower()
            if category == "vlm" or effective == "vlm":
                return True
            if _VISION_HINT_RE.search(model or ""):
                return True
            if category or effective:
                return False
            return None
    return True if _VISION_HINT_RE.search(model or "") else None


def _strip_bearer_prefix(value: str) -> str:
    token = (value or "").strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def _to_openai_object(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _to_openai_object(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_to_openai_object(v) for v in value]
    return value


def _response_status_code(response: Any, default: int = 200) -> int:
    raw = getattr(response, "status_code", default)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return default


def _normalize_stream_choice(choice: Dict[str, Any]) -> Dict[str, Any]:
    if "delta" in choice:
        return choice
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    delta: Dict[str, Any] = {}
    if not isinstance(message, dict):
        message = {}
    if message.get("content"):
        delta["content"] = message.get("content")
    if message.get("tool_calls"):
        delta["tool_calls"] = message.get("tool_calls")
    return {
        "index": choice.get("index", 0),
        "delta": delta,
        "finish_reason": choice.get("finish_reason"),
    }


def _platform_stream_payload_to_openai_chunk(data: str) -> Dict[str, Any] | None:
    raw_text = (data or "").strip()
    if not raw_text or raw_text == "[DONE]":
        return None
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError:
        return {"choices": [{"delta": {"content": raw_text}, "finish_reason": None}]}

    if isinstance(raw, dict) and raw.get("choices"):
        choices = raw.get("choices") or []
        return {
            **raw,
            "choices": [
                _normalize_stream_choice(c if isinstance(c, dict) else {}) for c in choices
            ],
        }

    if isinstance(raw, dict) and raw.get("type") == "error":
        raise ValueError(str(raw.get("message") or raw.get("error") or "平台模型流式错误"))

    if isinstance(raw, dict):
        content = raw.get("content") or raw.get("text") or raw.get("delta") or ""
        delta: Dict[str, Any] = {}
        if content:
            delta["content"] = str(content)
        tool_calls = raw.get("tool_calls")
        if tool_calls:
            delta["tool_calls"] = tool_calls
        finish_reason = raw.get("finish_reason")
        if delta or finish_reason:
            return {"choices": [{"delta": delta, "finish_reason": finish_reason}]}

    return None


def _market_sse_payload_has_content(data: str) -> bool:
    """True when a market SSE data payload carries visible delta content."""
    try:
        chunk = _platform_stream_payload_to_openai_chunk(data)
    except ValueError:
        return False
    if not chunk:
        return False
    for choice in chunk.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict) and delta.get("content"):
            return True
    return False


def _iter_market_sse_data_payloads(response: Any) -> Iterator[str]:
    yield from _iter_transport_sse_data_payloads(
        response,
        payload_has_content=_market_sse_payload_has_content,
    )


from app.services.conversation.modstore_adapter_modstoreplatformadapter_mixin01 import (
    _ModstorePlatformAdapterPart01Mixin,
)
from app.services.conversation.modstore_adapter_modstoreplatformadapter_mixin02 import (
    _ModstorePlatformAdapterPart02Mixin,
)


class ModstorePlatformAdapter(_ModstorePlatformAdapterPart01Mixin, _ModstorePlatformAdapterPart02Mixin):
    """
    修茈市场平台代理适配器

    将LLM调用请求转发给修茈市场平台，由平台统一处理：
    - 密钥解析和选择
    - 厂商路由
    - 计费结算
    - 错误处理和重试
    """































def create_modstore_adapter_from_env() -> Optional[ModstorePlatformAdapter]:
    """
    从环境变量创建修茈市场适配器

    环境变量：
    - MODSTORE_PLATFORM_URL: 平台服务地址 (必须)
    - MODSTORE_AUTH_TOKEN: 认证Token (推荐)
    - MODSTORE_USER_ID: 用户ID (可选)

    Returns:
        配置好的适配器实例，如果未配置则返回None
    """
    platform_url = os.environ.get("MODSTORE_PLATFORM_URL", "").strip()

    if not platform_url:
        logger.debug("未检测到 MODSTORE_PLATFORM_URL，跳过平台模式")
        return None

    return ModstorePlatformAdapter()


class _ModstoreOpenAICompletions:
    def __init__(self, adapter: ModstorePlatformAdapter):
        self._adapter = adapter

    def create(
        self,
        *,
        messages: List[Dict[str, Any]],
        model: str | None = None,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs,
    ) -> Any:
        if stream:
            return self._stream(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        result = self._adapter.chat_completion_sync(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            **kwargs,
        )
        return _to_openai_object(result)

    def _stream(
        self,
        *,
        messages: List[Dict[str, Any]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs,
    ) -> Iterator[Any]:
        # A protocol-valid role chunk reaches the desktop before the upstream model's
        # first token.  It keeps the stream alive while Xiuci performs routing or a
        # provider buffers its first content delta; it has no visible message content.
        yield _to_openai_object(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant"},
                        "finish_reason": None,
                    }
                ],
                "model": model or self._adapter.model_name,
            }
        )
        stream_mode = os.environ.get("XCAGI_MODSTORE_USE_NATIVE_STREAM", "").strip().lower()
        use_native_stream = stream_mode not in {"0", "false", "no", "off"}
        if not use_native_stream:
            # The local ChatView still consumes SSE, but the market stream endpoint may be
            # unavailable or proxy-buffered. Use the billed platform /api/llm/chat call and
            # adapt the completed OpenAI-compatible response into one synthetic stream chunk.
            result = self._adapter.chat_completion_sync(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                **kwargs,
            )
            choice = (result.get("choices") or [{}])[0]
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            delta: Dict[str, Any] = {}
            if message.get("content"):
                delta["content"] = message.get("content")
            if message.get("tool_calls"):
                delta["tool_calls"] = message.get("tool_calls")
            yield _to_openai_object(
                {
                    "choices": [
                        {
                            "index": choice.get("index", 0),
                            "delta": delta,
                            "finish_reason": choice.get("finish_reason"),
                        }
                    ],
                    "model": result.get("model"),
                }
            )
            return

        for data in self._adapter.stream_chat_completion_sync(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            **kwargs,
        ):
            chunk = _platform_stream_payload_to_openai_chunk(data)
            if chunk is not None:
                yield _to_openai_object(chunk)


class _ModstoreOpenAIChat:
    def __init__(self, adapter: ModstorePlatformAdapter):
        self.completions = _ModstoreOpenAICompletions(adapter)


class ModstoreOpenAICompatibleClient:
    """Small OpenAI SDK-compatible facade backed by the Xiuci platform LLM API."""

    is_modstore_openai_compatible = True

    def __init__(self, adapter: ModstorePlatformAdapter):
        self.adapter = adapter
        self.chat = _ModstoreOpenAIChat(adapter)

    @property
    def default_model(self) -> str:
        return str(self.adapter.default_model)

    @property
    def default_provider(self) -> str:
        return str(self.adapter.default_provider)


def create_modstore_openai_client_from_request(request: Any) -> ModstoreOpenAICompatibleClient:
    return ModstoreOpenAICompatibleClient(ModstorePlatformAdapter.from_request(request=request))


# 向后兼容别名
ModstoreProxyAdapter = ModstorePlatformAdapter
