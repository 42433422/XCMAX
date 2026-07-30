"""Extracted methods for an existing public service."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_mixin_methods


class PlannerLlmSupportMixin:
    def _request_llm_completion(
        self,
        messages: list[dict[str, str]],
        *,
        context: dict[str, Any],
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any] | None:
        """Use the signed-in market model first, then the legacy direct key."""
        context = context if isinstance(context, dict) else {}
        try:
            from app.http.request_context import get_current_http_request
            from app.services.conversation.modstore_adapter import ModstorePlatformAdapter

            request = get_current_http_request()
            auth_session_id = str(context.get("_auth_session_id") or "").strip()
            if request is not None:
                adapter = ModstorePlatformAdapter.from_request(request)
            elif auth_session_id:
                adapter = ModstorePlatformAdapter.from_session(session_id=auth_session_id)
            else:
                adapter = getattr(self._ai_service, "modstore_adapter", None)

            adapter_token = getattr(adapter, "auth_token", "") if adapter is not None else ""
            if adapter is not None and isinstance(adapter_token, str) and adapter_token.strip():
                response = adapter.chat_completion_sync(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if isinstance(response, dict):
                    try:
                        from app.desktop_runtime import is_desktop_mode
                        from app.infrastructure.llm.providers.modstore_provider import (
                            ModstoreProvider,
                        )
                        from app.infrastructure.llm.providers.registry import get_llm_registry

                        if is_desktop_mode():
                            get_llm_registry().register("modstore", ModstoreProvider(adapter))
                    except RECOVERABLE_ERRORS:
                        logger.debug("桌面会话模型未写入进程级可用状态", exc_info=True)
                    response["_xcagi_planner_route"] = "session_market"
                    return response
        except RECOVERABLE_ERRORS as err:
            logger.warning("会话模型规划失败，尝试直连兼容路径: %s", err)

        api_key = getattr(self._ai_service, "api_key", "") or ""
        if not api_key:
            return None

        from app.infrastructure.llm.providers.credentials import default_chat_completions_url

        api_url = getattr(self._ai_service, "api_url", "") or default_chat_completions_url()
        response = _get_planner_http_client().post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": getattr(self._ai_service, "model", "") or "deepseek-chat",
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        if response.status_code >= 400:
            return None
        payload = response.json()
        if isinstance(payload, dict):
            payload["_xcagi_planner_route"] = "legacy_direct"
            return payload
        return None

    @staticmethod
    def _validate_required_params(plan: PlanGraph, tool_registry: dict[str, Any]) -> str | None:
        """检查节点 params 是否满足 tool_registry 的 required_params。"""
        for node in plan.nodes or []:
            tool_spec = (tool_registry or {}).get(str(node.tool_id) or "")
            if not isinstance(tool_spec, dict):
                continue
            actions = tool_spec.get("actions") or {}
            if not isinstance(actions, dict):
                continue
            action_meta = actions.get(str(node.action) or "")
            if not isinstance(action_meta, dict):
                continue
            required_params = action_meta.get("required_params") or []
            if not isinstance(required_params, list):
                required_params = []
            params = node.params or {}
            for key in required_params:
                if (
                    key not in params
                    or params.get(key) is None
                    or str(params.get(key)).strip() == ""
                ):
                    return f"节点 {node.node_id} 缺少 required_params: {key}"
        return None


sync_mixin_methods(
    PlannerLlmSupportMixin,
    target=globals(),
    source_module="app.application.workflow.planner",
    method_names=(
        "_request_llm_completion",
        "_validate_required_params",
    ),
)
