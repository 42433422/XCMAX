"""Agentic single-step decisions over explicitly supplied AI and HTTP ports."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Protocol

from app.utils.operational_errors import RECOVERABLE_ERRORS


class AgentSettings(Protocol):
    @property
    def api_key(self) -> str: ...
    @property
    def api_url(self) -> str: ...
    @property
    def model(self) -> str: ...


class DecisionResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    def json(self) -> dict[str, Any]: ...


class DecisionHttpClient(Protocol):
    def post(
        self, url: str, *, headers: dict[str, str], json: dict[str, Any]
    ) -> DecisionResponse: ...


class AgentDecisionClient:
    def __init__(
        self,
        ai_factory: Callable[[], AgentSettings],
        http_factory: Callable[[], DecisionHttpClient],
        event_logger: logging.Logger,
    ) -> None:
        self._ai_factory = ai_factory
        self._http_factory = http_factory
        self._logger = event_logger

    def decide(
        self,
        user_message: str,
        tool_registry: dict[str, Any],
        runtime_context: dict[str, Any],
        agent_history: list[dict[str, Any]],
        user_id: str | None,
    ) -> dict[str, Any] | None:
        """
        询问 LLM：下一步做什么（单步决策）。
        返回 {"action": "done"} 表示结束，或 {"tool_id": "...", "action": "...", "params": {...}, "reasoning": "..."}
        """
        ai_service = self._ai_factory()
        api_key = getattr(ai_service, "api_key", "") or ""
        if not api_key:
            self._logger.warning("AgenticLoop 缺少 API_KEY，跳过")
            return None
        tool_specs = []
        for tid, spec in tool_registry.items():
            if not isinstance(spec, dict):
                continue
            actions = spec.get("actions") or {}
            action_list = []
            for aname, ameta in actions.items():
                if not isinstance(ameta, dict):
                    continue
                action_list.append(
                    {
                        "action": aname,
                        "risk": ameta.get("risk", "low"),
                        "idempotent": bool(ameta.get("idempotent", False)),
                        "required_params": ameta.get("required_params", []),
                    }
                )
            tool_specs.append(
                {"tool_id": tid, "description": spec.get("description", ""), "actions": action_list}
            )
        history_lines = []
        for h in agent_history[-8:]:
            role = h.get("role", "")
            if role == "done":
                history_lines.append("Assistant: 已完成任务")
            elif role == "assistant":
                history_lines.append(
                    f"Assistant: 决定执行 {h.get('tool_id')}.{h.get('action')} (reasoning: {h.get('reasoning', '')[:80]})"
                )
            else:
                history_lines.append(f"System: {h.get('content', '')[:200]}")
        excel_analysis = runtime_context.get("excel_analysis")
        excel_info = ""
        if isinstance(excel_analysis, dict):
            fp = excel_analysis.get("file_path", "")
            excel_info = f"\n当前 Excel 文件: {fp}"
        prompt = {
            "task": "作为 Agent，决定下一步动作。",
            "rules": [
                '如果任务已完成，返回 {"action": "done"}。',
                '如果需要执行工具，返回 {"tool_id": "...", "action": "...", "params": {...}, "reasoning": "..."}。',
                "params 必须填写所有 required_params（不能留空）。",
                "优先使用低风险、幂等工具。",
                "只决定下一步，不要一次决定多步。",
            ],
            "user_message": user_message,
            "excel_context": excel_info,
            "recent_history": "\n".join(history_lines) if history_lines else "(首步决策)",
            "tool_registry": tool_specs,
            "output_schema": {
                "action": "done | execute",
                "tool_id": "string (当 action=execute 时)",
                "action_name": "string (当 action=execute 时)",
                "params": "{} (当 action=execute 时)",
                "reasoning": "string",
            },
        }
        messages = [
            {"role": "system", "content": "你是工作流 Agent，只输出 JSON。"},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        try:
            from app.infrastructure.llm.providers.credentials import default_chat_completions_url

            api_url = getattr(ai_service, "api_url", "") or default_chat_completions_url()
            model = getattr(ai_service, "model", "") or "deepseek-chat"
            response = self._http_factory().post(
                api_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 600,
                },
            )
            if response.status_code >= 400:
                self._logger.warning("AgenticLoop LLM 调用失败: status=%d", response.status_code)
                return None
            raw = (
                (response.json().get("choices") or [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            if not raw:
                return None
            parsed = json.loads(raw)
            action = str(parsed.get("action") or "").strip().lower()
            if action == "done":
                return {"action": "done"}
            tool_id = str(parsed.get("tool_id") or "").strip()
            action_name = str(
                parsed.get("action_name")
                or parsed.get("tool_action")
                or ("" if action == "execute" else action)
            ).strip()
            params = parsed.get("params") if isinstance(parsed.get("params"), dict) else {}
            reasoning = str(parsed.get("reasoning") or "").strip()
            if not tool_id or not action_name:
                return None
            return {
                "action": "execute",
                "tool_id": tool_id,
                "action_name": action_name,
                "params": params,
                "reasoning": reasoning,
            }
        except RECOVERABLE_ERRORS as e:
            self._logger.warning("AgenticLoop LLM 决策失败: %s", e, exc_info=True)
            return None
