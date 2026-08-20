# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.services.conversation.modstore_adapter")


class __ModstorePlatformAdapterPart01MixinPart02Mixin:
    def _prepare_messages_sync(
        self,
        messages: _facade().List[_facade().Dict[str, _facade().Any]],
        provider: str,
        model: str,
    ) -> _facade().List[_facade().Dict[str, _facade().Any]]:
        from app.application.workflow.multimodal_user_content import (
            messages_have_image_parts,
            replace_image_parts_with_ocr_text,
        )

        if not messages_have_image_parts(messages):
            return messages
        support = self._model_vision_support_sync(provider, model)
        if support is True:
            return messages
        return replace_image_parts_with_ocr_text(
            messages, model_label=f"{provider}/{model}", model_confirmed_text_only=support is False
        )

    async def _prepare_messages(
        self,
        messages: _facade().List[_facade().Dict[str, _facade().Any]],
        provider: str,
        model: str,
    ) -> _facade().List[_facade().Dict[str, _facade().Any]]:
        from app.application.workflow.multimodal_user_content import (
            messages_have_image_parts,
            replace_image_parts_with_ocr_text,
        )

        if not messages_have_image_parts(messages):
            return messages
        support = await self._model_vision_support(provider, model)
        if support is True:
            return messages
        import asyncio

        return await asyncio.to_thread(
            replace_image_parts_with_ocr_text,
            messages,
            model_label=f"{provider}/{model}",
            model_confirmed_text_only=support is False,
        )

    async def chat_completion(
        self,
        messages: _facade().List[_facade().Dict[str, _facade().Any]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        provider: str | None = None,
        model: str | None = None,
        **kwargs,
    ) -> _facade().Dict[str, _facade().Any]:
        """
        通过修茈市场平台执行聊天补全

        Args:
            messages: 对话消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            provider: 供应商 (可选，不设则用默认)
            model: 模型名称 (可选，不设则用默认)
            **kwargs: 其他参数

        Returns:
            标准OpenAI格式的响应字典

        Raises:
            ValueError: 平台未配置或返回错误
            httpx.HTTPStatusError: HTTP错误
        """
        if not self.platform_url:
            raise ValueError("修茈市场平台URL未配置 (MODSTORE_PLATFORM_URL)")
        effective_provider, effective_model = self._resolve_provider_model(provider, model)
        candidates = await _facade().asyncio.to_thread(
            self._list_chat_failover_candidates_sync, effective_provider, effective_model
        )
        last_error: Exception | None = None
        for idx, (prov, mdl) in enumerate(candidates):
            prepared = await self._prepare_messages(messages, prov, mdl)
            url = f"{self.platform_url}/api/llm/chat"
            payload: _facade().Dict[str, _facade().Any] = {
                "provider": prov,
                "model": mdl,
                "messages": prepared,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "allow_failover": idx == 0,
                **kwargs,
            }
            if self.user_id:
                payload["user_id"] = self.user_id
            _facade().logger.debug(
                "[Modstore] 调用平台: %s/%s, messages=%s, user_id=%s failover=%s",
                prov,
                mdl,
                len(prepared),
                self.user_id,
                idx == 0,
            )
            t0 = _facade().time.perf_counter()
            try:
                client = await self._get_client()
                response = await client.post(url, json=payload)
                latency_ms = (_facade().time.perf_counter() - t0) * 1000.0
                status_code = _facade()._response_status_code(response)
                if status_code >= 400:
                    error_text = response.text[:500]
                    err = ValueError(f"平台错误({status_code}): {error_text}")
                    if idx + 1 < len(candidates) and _facade().is_market_chat_failoverable(
                        status_code, error_text
                    ):
                        _facade().logger.warning(
                            "[Modstore] 异步换模重试 %s/%s -> %s err=%s",
                            prov,
                            mdl,
                            candidates[idx + 1],
                            error_text[:200],
                        )
                        last_error = err
                        continue
                    _facade().logger.error(
                        "[Modstore] 平台返回错误 %s: %s", status_code, error_text
                    )
                    raise err
                result = response.json()
                used_provider = str(result.get("provider") or prov)
                used_model = str(result.get("model") or mdl)
                try:
                    from app.neuro_bus.application_neuro_bridge import (
                        neuro_notify_ai_model_roundtrip,
                    )

                    raw_usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
                    try:
                        raw_total = int(raw_usage.get("total_tokens") or 0)
                    except (TypeError, ValueError):
                        raw_total = 0
                    neuro_notify_ai_model_roundtrip(
                        model=f"modstore:{used_provider}/{used_model}",
                        latency_ms=latency_ms,
                        token_count=raw_total,
                        user_id=str(self.user_id or ""),
                    )
                except _facade().RECOVERABLE_ERRORS:
                    pass
                _facade().logger.info(
                    "[Modstore] 调用成功 [%.0fms], %s/%s key_source=%s billed=%s",
                    latency_ms,
                    used_provider,
                    used_model,
                    result.get("key_source", "unknown"),
                    result.get("billed", False),
                )
                return self._normalize_response(result, used_provider, used_model)
            except _facade().httpx.HTTPError as e:
                last_error = e
                if idx + 1 < len(candidates) and _facade().is_market_chat_failoverable(
                    None, str(e)
                ):
                    _facade().logger.warning("[Modstore] HTTP 失败换模 %s/%s: %s", prov, mdl, e)
                    continue
                _facade().logger.error("[Modstore] HTTP请求失败: %s", e)
                raise
            except ValueError:
                raise
            except _facade().RECOVERABLE_ERRORS as e:
                _facade().logger.error("[Modstore] 调用异常: %s", e, exc_info=True)
                raise
        if last_error is not None:
            raise last_error
        raise ValueError("平台聊天失败且无可用备用模型")

    async def stream_chat_completion(
        self,
        messages: _facade().List[_facade().Dict[str, _facade().Any]],
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
        if not self.platform_url:
            raise ValueError("修茈市场平台URL未配置")
        effective_provider, effective_model = self._resolve_provider_model(provider, model)
        messages = await self._prepare_messages(messages, effective_provider, effective_model)
        url = f"{self.platform_url}/api/llm/chat/stream"
        payload: _facade().Dict[str, _facade().Any] = {
            "provider": effective_provider,
            "model": effective_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **kwargs,
        }
        if self.user_id:
            payload["user_id"] = self.user_id
        _facade().logger.info(
            "[Modstream] 启动流式请求: %s/%s", effective_provider, effective_model
        )
        client = await self._get_client()
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    yield line[6:]

    def chat_completion_sync(
        self,
        messages: _facade().List[_facade().Dict[str, _facade().Any]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        provider: str | None = None,
        model: str | None = None,
        **kwargs,
    ) -> _facade().Dict[str, _facade().Any]:
        """同步版平台补全，用于现有 Planner 的 OpenAI SDK 兼容调用栈。"""
        if not self.platform_url:
            raise ValueError("修茈市场平台URL未配置 (MODSTORE_PLATFORM_URL)")
        try:
            from app.application.surface_audit_demo_account import is_local_demo_market_token
            from app.fastapi_routes.market_account import _is_local_market_base

            if is_local_demo_market_token(self.auth_token or "") and (
                not _is_local_market_base(self.platform_url)
            ):
                raise ValueError(
                    "当前会话为本地演示令牌，无法调用官网 LLM。请设置 XCAGI_USE_REMOTE_MARKET=1 重启后端并重新登录。"
                )
        except ImportError:
            pass
        effective_provider, effective_model = self._resolve_provider_model(provider, model)
        candidates = self._list_chat_failover_candidates_sync(effective_provider, effective_model)
        last_error: Exception | None = None
        for idx, (prov, mdl) in enumerate(candidates):
            prepared = self._prepare_messages_sync(messages, prov, mdl)
            try:
                return self._post_market_chat_sync(
                    provider=prov,
                    model=mdl,
                    messages=prepared,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    allow_failover=idx == 0,
                    extra=kwargs or None,
                )
            except ValueError as exc:
                last_error = exc
                status_match = _facade().re.search("平台错误\\((\\d{3})\\)", str(exc))
                status_code = int(status_match.group(1)) if status_match else None
                if idx + 1 >= len(candidates) or not _facade().is_market_chat_failoverable(
                    status_code, str(exc)
                ):
                    raise
                _facade().logger.warning(
                    "[Modstore] 桌面侧换模重试 primary=%s/%s failed=%s/%s next=%s err=%s",
                    effective_provider,
                    effective_model,
                    prov,
                    mdl,
                    candidates[idx + 1],
                    str(exc)[:240],
                )
                continue
        if last_error is not None:
            raise last_error
        raise ValueError("平台聊天失败且无可用备用模型")
