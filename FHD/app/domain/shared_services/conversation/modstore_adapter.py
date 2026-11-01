"""Public market LLM adapter: explicit credential, catalog, completion and stream assembly."""

from __future__ import annotations

import asyncio as asyncio
import hashlib as hashlib
import json as json
import logging
import os
import re as re
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import aclosing
from types import SimpleNamespace as SimpleNamespace
from typing import Any, Dict, List, Optional, Self

import httpx

from app.application.market_llm import (
    account_queries,
    authentication,
    catalog,
    completions,
    multimodal,
    routing,
    streaming,
)
from app.application.market_llm.authentication import _strip_bearer_prefix as _strip_bearer_prefix
from app.application.market_llm.catalog import _VISION_HINT_RE as _VISION_HINT_RE
from app.application.market_llm.catalog import (
    _catalog_model_vision_support as _catalog_model_vision_support,
)
from app.application.market_llm.protocols import (
    ChatInput,
    CompletionPorts,
    Connection,
    OpenAIPorts,
    ResponsePorts,
    StreamPorts,
)
from app.application.market_llm.responses import _response_status_code as _status_code
from app.application.market_llm.responses import (
    neuro_notify_ai_model_roundtrip as neuro_notify_ai_model_roundtrip,
)
from app.infrastructure import modstore_transport as _transport
from app.infrastructure.llm.modstore_chat_failover import is_market_chat_failoverable
from app.infrastructure.llm.modstore_response_normalize import normalize_market_chat_response
from app.legacy.market_llm import openai_compat
from app.legacy.market_llm.openai_compat import (
    _market_sse_payload_has_content as _market_sse_payload_has_content,
)
from app.legacy.market_llm.openai_compat import _normalize_stream_choice as _normalize_stream_choice
from app.legacy.market_llm.openai_compat import (
    _platform_stream_payload_to_openai_chunk as _platform_stream_payload_to_openai_chunk,
)
from app.legacy.market_llm.openai_compat import _to_openai_object as _to_openai_object
from app.utils.operational_errors import RECOVERABLE_ERRORS as RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)
_httpx_sync_client = _transport.httpx_sync_client
_iter_transport_sse_data_payloads = _transport.iter_market_sse_data_payloads
_aiter_transport_sse_data_payloads = _transport.aiter_market_sse_data_payloads
_iter_market_transport_plans = _transport.iter_market_transport_plans
_market_connect_attempts = _transport.market_connect_attempts
_market_connect_timeout = _transport.market_connect_timeout
_CATALOG_CACHE_TTL_SECONDS = 300.0
_CATALOG_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_CATALOG_CACHE_LOCK = threading.Lock()


def _response_status_code(response: Any, default: int = 200) -> int:
    return _status_code(response, default)


def _iter_market_sse_data_payloads(response: Any) -> Iterator[str]:
    yield from _iter_transport_sse_data_payloads(
        response, payload_has_content=_market_sse_payload_has_content
    )


async def _aiter_market_sse_data_payloads(response: httpx.Response) -> AsyncIterator[str]:
    async for data in _aiter_transport_sse_data_payloads(
        response, payload_has_content=_market_sse_payload_has_content
    ):
        yield data


class ModstorePlatformAdapter:
    """Forward model requests through market routing, credentials and billing."""

    def __init__(
        self,
        platform_url: str | None = None,
        auth_token: str | None = None,
        user_id: int | None = None,
        default_provider: str = "xiaomi",
        default_model: str = "mimo-v2.5-pro",
        timeout: float = 60.0,
    ):
        """初始化市场地址、凭据、默认模型和连接超时；显式值保持原环境回退规则。"""
        self.platform_url = (
            platform_url or os.environ.get("MODSTORE_PLATFORM_URL", "http://localhost:8000")
        ).rstrip("/")
        # None → env fallback; explicit "" means "no token" (session-bound isolation).
        self.auth_token = _strip_bearer_prefix(
            os.environ.get("MODSTORE_AUTH_TOKEN", "") if auth_token is None else auth_token
        )
        self.user_id = (
            self._parse_user_id(os.environ.get("MODSTORE_USER_ID", ""))
            if user_id is None
            else user_id
        )
        self.default_provider = os.environ.get("LLM_PROVIDER", default_provider).lower()
        self.default_model = os.environ.get("LLM_MODEL", default_model)
        self.timeout = timeout
        self._use_account_default = False
        self._account_default: tuple[Connection, tuple[str, str]] | None = None
        self._default_route_lock = threading.Lock()
        self._source = "env"
        self._client: Optional[httpx.AsyncClient] = None
        logger.info(
            "初始化修茈市场平台代理: %s, default=%s/%s, user_id=%s",
            self.platform_url,
            self.default_provider,
            self.default_model,
            self.user_id,
        )

    @staticmethod
    def _parse_user_id(value: str) -> Optional[int]:
        """解析用户ID"""
        if not value:
            return None
        try:
            return int(value.strip())
        except (ValueError, TypeError):
            return None

    @classmethod
    def from_session(cls, session_id: str | None = None, request: Any = None, **kwargs) -> Self:
        """从显式配置或 FHD 会话取得市场凭据；最近令牌回退限定为已解析的会话所有者。"""
        platform_url = (
            kwargs.get("platform_url")
            or os.environ.get("XCAGI_MARKET_BASE_URL")
            or os.environ.get("MODSTORE_PLATFORM_URL", "http://127.0.0.1:8765")
        ).rstrip("/")
        credential = authentication.resolve_credential(
            kwargs.get("auth_token", ""),
            os.environ.get("MODSTORE_AUTH_TOKEN", "").strip(),
            session_id,
            request,
            authentication.load_session_ports,
            logger,
        )
        instance = cls(
            platform_url=platform_url,
            auth_token=credential.token,
            **{
                key: value
                for key, value in kwargs.items()
                if key not in ("platform_url", "auth_token")
            },
        )
        instance._source = credential.source
        instance._use_account_default = not any(
            kwargs.get(key) for key in ("default_provider", "default_model")
        )
        for key in ("default_provider", "default_model"):
            if kwargs.get(key):
                value = str(kwargs[key]).strip()
                setattr(instance, key, value.lower() if key == "default_provider" else value)
        # Request/session scoped construction must not inherit the host account id.
        if (session_id or request) and "user_id" not in kwargs:
            instance.user_id = None
        return instance

    @classmethod
    def from_request(cls, request: Any, **kwargs) -> Self:
        """使用 FastAPI 请求中的本地会话创建市场适配器；Authorization 不直接作为市场令牌。"""
        return cls.from_session(request=request, **kwargs)

    def refresh_token_from_session(
        self, session_id: str | None = None, request: Any = None
    ) -> bool:
        """刷新市场令牌；后续请求使用新凭据，已开始的请求保留其凭据快照。"""
        token = authentication.refresh_credential(
            session_id, request, authentication.load_session_ports, logger
        )
        if not token:
            return False
        self.auth_token = token
        return True

    @property
    def provider_name(self) -> str:
        return f"modstore-{self.default_provider}"

    @property
    def model_name(self) -> str:
        return self.default_model

    @property
    def is_configured(self) -> bool:
        """检查是否已配置（有platform_url即可）"""
        return bool(self.platform_url)

    async def _get_client(self) -> httpx.AsyncClient:
        """获取HTTP客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=30),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                trust_env=False,
            )
        return self._client

    def _build_headers(self) -> Dict[str, str]:
        """构建请求头"""
        return self._connection().headers()

    def _list_chat_failover_candidates_sync(
        self, primary_provider: str, primary_model: str, connection: Connection | None = None
    ) -> list[tuple[str, str]]:
        connection = connection or self._connection()
        cached = self._account_default
        return routing.FailoverDiscovery(
            connection,
            self._catalog_gateway(connection).read_sync,
            _httpx_sync_client,
            {"provider": cached[1][0], "model": cached[1][1]}
            if cached is not None and cached[0] == connection
            else None,
        ).candidates(primary_provider, primary_model)

    def _post_market_chat_sync(
        self,
        *,
        provider: str,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        allow_failover: bool,
        extra: Dict[str, Any] | None = None,
        connection: Connection | None = None,
    ) -> Dict[str, Any]:
        return completions.post_sync(
            connection or self._connection(),
            (provider, model),
            ChatInput(messages, temperature, max_tokens, extra or {}),
            allow_failover,
            _httpx_sync_client,
            self._response_ports(),
        )

    def _normalize_response(
        self, raw_response: Dict[str, Any], provider: str, model: str
    ) -> Dict[str, Any]:
        return normalize_market_chat_response(raw_response, provider, model)

    def resolve_default_route(self, connection: Connection | None = None) -> tuple[str, str]:
        if not self._use_account_default:
            return self.default_provider, self.default_model
        with self._default_route_lock:
            connection = connection or self._connection()
            if self._account_default is None or self._account_default[0] != connection:
                route = routing.resolve_account_default(connection, _httpx_sync_client)
                self._account_default = (connection, route)
            return self._account_default[1]

    def _resolve_provider_model(
        self,
        provider: str | None = None,
        model: str | None = None,
        *,
        connection: Connection | None = None,
    ) -> tuple[str, str]:
        if self._use_account_default and not provider and not model:
            return self.resolve_default_route(connection)
        effective_provider = (provider or self.default_provider).lower()
        effective_model = model or self.default_model
        if provider is None and isinstance(effective_model, str) and ("/" in effective_model):
            left, right = effective_model.split("/", 1)
            if left.strip() and right.strip():
                effective_provider = left.strip().lower()
                effective_model = right.strip()
        return (effective_provider, effective_model)

    async def _resolve_provider_model_async(
        self, provider: str | None, model: str | None, connection: Connection
    ) -> tuple[str, str]:
        if self._use_account_default and not provider and not model:
            return await asyncio.to_thread(self.resolve_default_route, connection)
        return self._resolve_provider_model(provider, model)

    def _catalog_cache_key(self) -> tuple[str, str]:
        return catalog.cache_key(self._connection())

    def _cached_catalog(self) -> dict[str, Any] | None:
        return self._catalog_cache().read(self._catalog_cache_key())

    def _remember_catalog(self, catalog: dict[str, Any]) -> None:
        self._catalog_cache().remember(self._catalog_cache_key(), catalog)

    def _model_vision_support_sync(self, provider: str, model: str) -> bool | None:
        value = self._catalog_gateway().read_sync()
        return _catalog_model_vision_support(value or {}, provider, model)

    async def _model_vision_support(self, provider: str, model: str) -> bool | None:
        value = await self._catalog_gateway().read_async()
        return _catalog_model_vision_support(value or {}, provider, model)

    def _prepare_messages_sync(
        self, messages: List[Dict[str, Any]], provider: str, model: str
    ) -> List[Dict[str, Any]]:
        return multimodal.prepare_sync(messages, (provider, model), self._model_vision_support_sync)

    async def _prepare_messages(
        self, messages: List[Dict[str, Any]], provider: str, model: str
    ) -> List[Dict[str, Any]]:
        return await multimodal.prepare_async(
            messages, (provider, model), self._model_vision_support
        )

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        provider: str | None = None,
        model: str | None = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """执行异步平台补全，沿已配置候选链处理可重试的配额错误并返回 OpenAI 响应。"""
        connection = self._connection()
        return await completions.complete_async(
            connection,
            await self._resolve_provider_model_async(provider, model, connection),
            ChatInput(messages, temperature, max_tokens, kwargs),
            self._completion_ports(connection),
        )

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        provider: str | None = None,
        model: str | None = None,
        **kwargs,
    ):
        """
        流式聊天补全（SSE）

        Yields:
            SSE数据行
        """
        connection = self._connection()
        source = streaming.stream_async(
            connection,
            await self._resolve_provider_model_async(provider, model, connection),
            ChatInput(messages, temperature, max_tokens, kwargs),
            self._stream_ports(connection),
        )
        async with aclosing(source) as chunks:
            async for chunk in chunks:
                yield chunk

    def chat_completion_sync(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        provider: str | None = None,
        model: str | None = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """同步版平台补全，用于现有 Planner 的 OpenAI SDK 兼容调用栈。"""
        connection = self._connection()
        return completions.complete_sync(
            connection,
            self._resolve_provider_model(provider, model, connection=connection),
            ChatInput(messages, temperature, max_tokens, kwargs),
            self._completion_ports(connection),
        )

    def stream_chat_completion_sync(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        provider: str | None = None,
        model: str | None = None,
        **kwargs,
    ) -> Iterator[str]:
        """同步版平台流式补全，逐条产出 SSE data payload。"""
        connection = self._connection()
        yield from streaming.stream_sync(
            connection,
            self._resolve_provider_model(provider, model, connection=connection),
            ChatInput(messages, temperature, max_tokens, kwargs),
            self._stream_ports(connection),
        )

    async def get_available_providers(self) -> List[Dict[str, Any]]:
        """获取当前凭据可用的供应商列表。"""
        return await account_queries.available_providers(
            self._connection(), self._get_client, logger
        )

    async def get_credential_status(self, provider: str | None = None) -> Dict[str, Any]:
        """获取指定供应商的密钥状态。"""
        return await account_queries.credential_status(
            self._connection(), provider or self.default_provider, self._get_client
        )

    async def close(self):
        """关闭连接"""
        client, self._client = (self._client, None)
        if client is not None and (not client.is_closed):
            await client.aclose()

    def __repr__(self) -> str:
        configured = "✅" if self.is_configured else "❌"
        source = getattr(self, "_source", "unknown")
        token_len = len(self.auth_token or "")
        return f"<ModstorePlatformAdapter {configured} url={self.platform_url}, default={self.default_provider}/{self.default_model}, source={source}, token={'*' * min(token_len, 8)} ({token_len} chars), user={self.user_id}>"

    def _connection(self) -> Connection:
        return Connection(
            self.platform_url, _strip_bearer_prefix(self.auth_token), self.user_id, self.timeout
        )

    def _catalog_cache(self) -> catalog.CatalogCache:
        return catalog.CatalogCache(
            _CATALOG_CACHE, _CATALOG_CACHE_LOCK, time.monotonic, _CATALOG_CACHE_TTL_SECONDS
        )

    def _catalog_gateway(self, connection: Connection | None = None) -> catalog.CatalogGateway:
        return catalog.CatalogGateway(
            connection or self._connection(),
            self._catalog_cache(),
            _httpx_sync_client,
            self._get_client,
            logger,
        )

    def _response_ports(self) -> ResponsePorts:
        return ResponsePorts(
            self._normalize_response, neuro_notify_ai_model_roundtrip, time.perf_counter, logger
        )

    def _completion_ports(self, connection: Connection) -> CompletionPorts:
        return CompletionPorts(
            lambda provider, model: self._list_chat_failover_candidates_sync(
                provider, model, connection
            ),
            self._prepare_messages_sync,
            self._prepare_messages,
            lambda **kwargs: self._post_market_chat_sync(connection=connection, **kwargs),
            self._get_client,
            is_market_chat_failoverable,
            self._response_ports(),
            _response_status_code,
        )

    def _stream_ports(self, connection: Connection) -> StreamPorts:
        return StreamPorts(
            lambda provider, model: self._list_chat_failover_candidates_sync(
                provider, model, connection
            ),
            self._prepare_messages_sync,
            self._prepare_messages,
            _httpx_sync_client,
            self._get_client,
            _iter_market_sse_data_payloads,
            _aiter_market_sse_data_payloads,
            is_market_chat_failoverable,
            _market_connect_timeout,
            _response_status_code,
            logger,
        )


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
            messages=messages, temperature=temperature, max_tokens=max_tokens, model=model, **kwargs
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
        ports = OpenAIPorts(
            self._adapter.chat_completion_sync,
            self._adapter.stream_chat_completion_sync,
            self._adapter.model_name,
        )
        yield from openai_compat.stream_response(
            ports,
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            extra=kwargs,
        )


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
        return self.adapter.resolve_default_route()[1]

    @property
    def default_provider(self) -> str:
        return self.adapter.resolve_default_route()[0]


def create_modstore_openai_client_from_request(request: Any) -> ModstoreOpenAICompatibleClient:
    return ModstoreOpenAICompatibleClient(ModstorePlatformAdapter.from_request(request=request))


ModstoreProxyAdapter = ModstorePlatformAdapter
