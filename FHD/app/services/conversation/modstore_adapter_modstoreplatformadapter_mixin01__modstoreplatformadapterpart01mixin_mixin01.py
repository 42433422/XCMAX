# mypy: disable-error-code="no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.conversation.modstore_adapter")


class __ModstorePlatformAdapterPart01MixinPart01Mixin:
    def __init__(
        self,
        platform_url: str | None = None,
        auth_token: str | None = None,
        user_id: int | None = None,
        default_provider: str = "xiaomi",
        default_model: str = "mimo-v2.5-pro",
        timeout: float = 60.0,
    ):
        """Initialize platform transport and default model from host configuration."""
        self.platform_url = (
            platform_url
            or _facade().os.environ.get("MODSTORE_PLATFORM_URL", "http://localhost:8000")
        ).rstrip("/")
        self.auth_token = _facade()._strip_bearer_prefix(
            auth_token or _facade().os.environ.get("MODSTORE_AUTH_TOKEN", "")
        )
        self.user_id = user_id or self._parse_user_id(
            _facade().os.environ.get("MODSTORE_USER_ID", "")
        )
        self.default_provider = _facade().os.environ.get("LLM_PROVIDER", default_provider).lower()
        self.default_model = _facade().os.environ.get("LLM_MODEL", default_model)
        self.timeout = timeout
        self._source = "env"
        self._client: _facade().Optional[_facade().httpx.AsyncClient] = None
        _facade().logger.info(
            "初始化修茈市场平台代理: %s, default=%s/%s, user_id=%s",
            self.platform_url,
            self.default_provider,
            self.default_model,
            self.user_id,
        )

    @staticmethod
    def _parse_user_id(value: str) -> _facade().Optional[int]:
        """解析用户ID"""
        if not value:
            return None
        try:
            return int(value.strip())
        except (ValueError, TypeError):
            return None

    @classmethod
    def from_session(
        cls, session_id: str | None = None, request: _facade().Any = None, **kwargs
    ) -> _facade().Self:
        """Resolve this session token; fallback requires a known owner of that session."""
        platform_url = (
            kwargs.get("platform_url")
            or _facade().os.environ.get("XCAGI_MARKET_BASE_URL")
            or _facade().os.environ.get("MODSTORE_PLATFORM_URL", "http://127.0.0.1:8765")
        ).rstrip("/")
        env_token = _facade().os.environ.get("MODSTORE_AUTH_TOKEN", "").strip()
        auth_token = ""
        token_source = "env"
        if kwargs.get("auth_token"):
            auth_token = kwargs["auth_token"]
            token_source = "kwargs"
        elif env_token and not (session_id or request):
            auth_token = env_token
            token_source = "env"
        if not auth_token and (session_id or request):
            try:
                from app.fastapi_routes.market_account import (
                    _user_id_from_session,
                    latest_session_market_token,
                    session_id_from_request,
                    session_market_token,
                )

                effective_session_id = session_id or (
                    session_id_from_request(request) if request else ""
                )
                if effective_session_id:
                    token_from_session = session_market_token(effective_session_id)
                    if token_from_session:
                        auth_token = token_from_session
                        token_source = "session"
                if not auth_token:
                    fallback_user_id = _user_id_from_session(effective_session_id)
                    if fallback_user_id is not None:
                        latest_token = latest_session_market_token(user_id=fallback_user_id)
                        if latest_token:
                            auth_token = latest_token
                            token_source = "session"
            except _facade().RECOVERABLE_ERRORS:
                _facade().logger.warning("当前模型会话凭据读取失败")
        instance = cls(
            platform_url=platform_url,
            auth_token=auth_token,
            **{k: v for k, v in kwargs.items() if k not in ("platform_url", "auth_token")},
        )
        if session_id or request:
            if not auth_token:
                instance.auth_token = ""
                token_source = "session"
            instance.user_id = kwargs.get("user_id")
        instance._source = token_source
        return instance

    @classmethod
    def from_request(cls, request: _facade().Any, **kwargs) -> _facade().Self:
        """Resolve model credentials from the authenticated request session."""
        return cls.from_session(request=request, **kwargs)

    def refresh_token_from_session(
        self, session_id: str | None = None, request: _facade().Any = None
    ) -> bool:
        """Refresh only from the specified request session."""
        try:
            from app.fastapi_routes.market_account import (
                session_id_from_request,
                session_market_token,
            )

            effective_session_id = session_id or (
                session_id_from_request(request) if request else ""
            )
            if not effective_session_id:
                _facade().logger.warning("refresh_token_from_session: 无有效Session ID")
                return False
            new_token = session_market_token(effective_session_id)
            if new_token:
                old_token_len = len(self.auth_token or "")
                self.auth_token = new_token
                _facade().logger.info(
                    "Token已刷新 [%s → %s chars], 来源: session[%s...]",
                    old_token_len,
                    len(new_token),
                    effective_session_id[:8],
                )
                return True
            else:
                _facade().logger.warning("Session中未找到新Token")
                return False
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.error("刷新Token失败: %s", e, exc_info=True)
            return False

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

    async def _get_client(self) -> _facade().httpx.AsyncClient:
        """获取HTTP客户端"""
        if self._client is None or self._client.is_closed:
            self._client = _facade().httpx.AsyncClient(
                timeout=_facade().httpx.Timeout(self.timeout, connect=10.0),
                limits=_facade().httpx.Limits(max_keepalive_connections=10, max_connections=30),
                headers=self._build_headers(),
                trust_env=False,
            )
        return self._client

    def _build_headers(self) -> _facade().Dict[str, str]:
        """构建请求头"""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _list_chat_failover_candidates_sync(
        self, primary_provider: str, primary_model: str
    ) -> list[tuple[str, str]]:
        return _facade()._mfailover._list_chat_failover_candidates_sync(
            self, primary_provider, primary_model
        )

    def _post_market_chat_sync(
        self,
        *,
        provider: str,
        model: str,
        messages: _facade().List[_facade().Dict[str, _facade().Any]],
        temperature: float,
        max_tokens: int,
        allow_failover: bool,
        extra: _facade().Dict[str, _facade().Any] | None = None,
    ) -> _facade().Dict[str, _facade().Any]:
        return _facade()._mfailover._post_market_chat_sync(
            self,
            provider=provider,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            allow_failover=allow_failover,
            extra=extra,
        )

    def _normalize_response(
        self, raw_response: _facade().Dict[str, _facade().Any], provider: str, model: str
    ) -> _facade().Dict[str, _facade().Any]:
        return _facade().normalize_market_chat_response(raw_response, provider, model)

    def _resolve_provider_model(
        self, provider: str | None = None, model: str | None = None
    ) -> tuple[str, str]:
        effective_provider = (provider or self.default_provider).lower()
        effective_model = model or self.default_model
        if provider is None and isinstance(effective_model, str) and ("/" in effective_model):
            left, right = effective_model.split("/", 1)
            if left.strip() and right.strip():
                effective_provider = left.strip().lower()
                effective_model = right.strip()
        return (effective_provider, effective_model)

    def _catalog_cache_key(self) -> tuple[str, str]:
        token_fingerprint = (
            _facade().hashlib.sha256((self.auth_token or "").encode("utf-8")).hexdigest()[:16]
        )
        return (self.platform_url, token_fingerprint)

    def _cached_catalog(self) -> dict[str, _facade().Any] | None:
        key = self._catalog_cache_key()
        now = _facade().time.monotonic()
        with _facade()._CATALOG_CACHE_LOCK:
            cached = _facade()._CATALOG_CACHE.get(key)
            if cached and cached[0] > now:
                return cached[1]
            if cached:
                _facade()._CATALOG_CACHE.pop(key, None)
        return None

    def _remember_catalog(self, catalog: dict[str, _facade().Any]) -> None:
        with _facade()._CATALOG_CACHE_LOCK:
            _facade()._CATALOG_CACHE[self._catalog_cache_key()] = (
                _facade().time.monotonic() + _facade()._CATALOG_CACHE_TTL_SECONDS,
                catalog,
            )

    def _model_vision_support_sync(self, provider: str, model: str) -> bool | None:
        catalog = self._cached_catalog()
        if catalog is None:
            try:
                with _facade()._httpx_sync_client(
                    timeout=_facade().httpx.Timeout(min(self.timeout, 15.0), connect=5.0),
                    headers=self._build_headers(),
                ) as client:
                    response = client.get(f"{self.platform_url}/api/llm/catalog")
                    response.raise_for_status()
                    raw = response.json()
                if isinstance(raw, dict):
                    catalog = raw
                    self._remember_catalog(raw)
            except _facade().RECOVERABLE_ERRORS as exc:
                _facade().logger.info(
                    "[Modstore] 无法读取模型目录，图片请求将尝试本地 OCR: %s", exc
                )
        return _facade()._catalog_model_vision_support(catalog or {}, provider, model)

    async def _model_vision_support(self, provider: str, model: str) -> bool | None:
        catalog = self._cached_catalog()
        if catalog is None:
            try:
                client = await self._get_client()
                response = await client.get(f"{self.platform_url}/api/llm/catalog")
                response.raise_for_status()
                raw = response.json()
                if isinstance(raw, dict):
                    catalog = raw
                    self._remember_catalog(raw)
            except _facade().RECOVERABLE_ERRORS as exc:
                _facade().logger.info(
                    "[Modstore] 无法读取模型目录，图片请求将尝试本地 OCR: %s", exc
                )
        return _facade()._catalog_model_vision_support(catalog or {}, provider, model)
