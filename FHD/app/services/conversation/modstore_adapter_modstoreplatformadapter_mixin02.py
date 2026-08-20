# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.conversation.modstore_adapter")


class _ModstorePlatformAdapterPart02Mixin:
    def stream_chat_completion_sync(
        self,
        messages: _facade().List[_facade().Dict[str, _facade().Any]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        provider: str | None = None,
        model: str | None = None,
        **kwargs,
    ) -> _facade().Iterator[str]:
        """同步版平台流式补全，逐条产出 SSE data payload。"""
        if not self.platform_url:
            raise ValueError("修茈市场平台URL未配置")
        (effective_provider, effective_model) = self._resolve_provider_model(provider, model)
        candidates = self._list_chat_failover_candidates_sync(effective_provider, effective_model)
        last_error: Exception | None = None
        for idx, (prov, mdl) in enumerate(candidates):
            prepared = self._prepare_messages_sync(messages, prov, mdl)
            url = f"{self.platform_url}/api/llm/chat/stream"
            payload: _facade().Dict[str, _facade().Any] = {
                "provider": prov,
                "model": mdl,
                "messages": prepared,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
                "allow_failover": idx == 0,
                **kwargs,
            }
            if self.user_id:
                payload["user_id"] = self.user_id
            _facade().logger.info(
                "[Modstream] 启动同步流式请求: %s/%s (attempt %s/%s)",
                prov,
                mdl,
                idx + 1,
                len(candidates),
            )
            retry_next = False
            with _facade()._httpx_sync_client(
                timeout=_facade().httpx.Timeout(
                    self.timeout, connect=_facade()._market_connect_timeout()
                ),
                limits=_facade().httpx.Limits(max_keepalive_connections=10, max_connections=30),
                headers=self._build_headers(),
            ) as client:
                with client.stream("POST", url, json=payload) as response:
                    status_code = _facade()._response_status_code(response)
                    if status_code >= 400:
                        error_text = response.read().decode("utf-8", errors="ignore")[:500]
                        err = ValueError(f"平台错误({status_code}): {error_text}")
                        if idx + 1 < len(candidates) and _facade().is_market_chat_failoverable(
                            status_code, error_text
                        ):
                            _facade().logger.warning(
                                "[Modstream] 流式换模 %s/%s -> %s", prov, mdl, candidates[idx + 1]
                            )
                            last_error = err
                            retry_next = True
                        else:
                            _facade().logger.error(
                                "[Modstream] 平台同步流式返回错误 %s: %s", status_code, error_text
                            )
                            raise err
                    else:
                        yield from _facade()._iter_market_sse_data_payloads(response)
                        return
            if retry_next:
                continue
        if last_error is not None:
            raise last_error
        raise ValueError("平台流式聊天失败且无可用备用模型")

    async def get_available_providers(self) -> _facade().List[_facade().Dict[str, _facade().Any]]:
        """
        获取当前可用的供应商列表（通过平台API）

        Returns:
            供应商信息列表
        """
        url = f"{self.platform_url}/api/llm/providers"
        try:
            client = await self._get_client()
            response = await client.get(url)
            status_code = _facade()._response_status_code(response)
            if status_code == 200:
                return _facade().cast("list[dict[str, Any]]", response.json().get("providers", []))
            else:
                _facade().logger.warning("[Modstore] 获取供应商列表失败: %s", status_code)
                return []
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.error("[Modstore] 查询供应商异常: %s", e)
            return []

    async def get_credential_status(
        self, provider: str | None = None
    ) -> _facade().Dict[str, _facade().Any]:
        """
        获取指定供应商的密钥状态

        Args:
            provider: 供应商名称

        Returns:
            密钥状态信息
        """
        effective_provider = provider or self.default_provider
        url = f"{self.platform_url}/api/llm/credential-status/{effective_provider}"
        try:
            client = await self._get_client()
            response = await client.get(url)
            status_code = _facade()._response_status_code(response)
            if status_code == 200:
                return _facade().cast("dict[str, Any]", response.json())
            else:
                return {"error": f"HTTP {status_code}"}
        except _facade().RECOVERABLE_ERRORS as e:
            return {"error": str(e)}

    async def close(self):
        """关闭连接"""
        if self._client and (not self._client.is_closed):
            await self._client.aclose()

    def __repr__(self) -> str:
        configured = "✅" if self.is_configured else "❌"
        source = getattr(self, "_source", "unknown")
        token_len = len(self.auth_token or "")
        return f"<ModstorePlatformAdapter {configured} url={self.platform_url}, default={self.default_provider}/{self.default_model}, source={source}, token={'*' * min(token_len, 8)} ({token_len} chars), user={self.user_id}>"
