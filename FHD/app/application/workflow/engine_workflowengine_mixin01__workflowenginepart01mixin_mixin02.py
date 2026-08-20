# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.engine")


class __WorkflowEnginePart01MixinPart02Mixin:
    def _advance_router(
        self,
        node: _facade().WorkflowNode,
        output: dict[str, _facade().Any],
        pending: dict[str, _facade().WorkflowNode],
        blocked: set[str],
    ) -> str | None:
        """按 output 决定条件边后继，并屏蔽未选中的分支目标；返回选中的 target node_id。

        优先匹配 branches[].condition；无匹配则用 next；next 为空返回 None（正常结束）。
        """
        chosen = self._resolve_successor(node, output)
        candidates = self._branch_candidates(node)
        for cand in candidates:
            if cand != chosen:
                blocked.add(cand)
                pending.pop(cand, None)
        return chosen

    @staticmethod
    def _resolve_successor(
        node: _facade().WorkflowNode, output: dict[str, _facade().Any]
    ) -> str | None:
        target = _facade().WorkflowEngine.evaluate_branch(node, output)
        if target is not None:
            return target
        return node.next

    @staticmethod
    def evaluate_branch(
        node: _facade().WorkflowNode, output: dict[str, _facade().Any]
    ) -> str | None:
        """按 output 匹配 node.branches 中第一条成功的 condition，返回 target node_id；无匹配返回 None。"""
        if not isinstance(output, dict):
            output = {}
        for branch in node.branches:
            if _facade().WorkflowEngine._condition_matches(branch.condition, output):
                return branch.target
        return None

    @staticmethod
    def _condition_matches(
        condition: dict[str, _facade().Any], output: dict[str, _facade().Any]
    ) -> bool:
        if not isinstance(condition, dict):
            return False
        key = condition.get("key")
        if key is None or not isinstance(key, str):
            return False
        expected = condition.get("equals", condition.get("value"))
        return output.get(key) == expected

    @staticmethod
    def _branch_candidates(node: _facade().WorkflowNode) -> list[str]:
        cands: list[str] = []
        if node.next is not None:
            cands.append(node.next)
        for branch in node.branches:
            cands.append(branch.target)
        return cands

    def _run_agentic_loop(
        self,
        plan: _facade().PlanGraph,
        runtime_context: dict[str, _facade().Any] | None,
        max_retries: int,
        tool_registry: dict[str, _facade().Any],
        user_id: str | None,
        state_schema: _facade().StateSchema | None = None,
    ) -> _facade().WorkflowRunResult:
        from .agent_loop import run_agentic_loop

        return run_agentic_loop(
            self,
            _facade().logger,
            plan,
            runtime_context,
            max_retries,
            tool_registry,
            user_id,
            state_schema,
        )

    def _llm_decide_next_step(
        self,
        user_message: str,
        tool_registry: dict[str, _facade().Any],
        runtime_context: dict[str, _facade().Any],
        agent_history: list[dict[str, _facade().Any]],
        user_id: str | None,
    ) -> dict[str, _facade().Any] | None:
        """
        询问 LLM：下一步做什么（单步决策）。
        返回 {"action": "done"} 表示结束，或 {"tool_id": "...", "action": "...", "params": {...}, "reasoning": "..."}
        """
        ai_service = _facade().get_ai_conversation_service()
        api_key = getattr(ai_service, "api_key", "") or ""
        if not api_key:
            _facade().logger.warning("AgenticLoop 缺少 API_KEY，跳过")
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
            {"role": "user", "content": _facade().json.dumps(prompt, ensure_ascii=False)},
        ]
        try:
            from app.infrastructure.llm.providers.credentials import default_chat_completions_url

            api_url = getattr(ai_service, "api_url", "") or default_chat_completions_url()
            model = getattr(ai_service, "model", "") or "deepseek-chat"
            response = (
                _facade()
                ._get_sync_http_client()
                .post(
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
            )
            if response.status_code >= 400:
                _facade().logger.warning(
                    "AgenticLoop LLM 调用失败: status=%d", response.status_code
                )
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
            parsed = _facade().json.loads(raw)
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
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning("AgenticLoop LLM 决策失败: %s", e, exc_info=True)
            return None

    @staticmethod
    def _summarize_output(output: dict[str, _facade().Any]) -> str:
        if not isinstance(output, dict):
            return str(output)[:200]
        if output.get("success") is True:
            msg = str(output.get("message") or output.get("answer") or "").strip()
            if msg:
                return msg[:200]
            data = output.get("data")
            if data is not None:
                if isinstance(data, list):
                    return f"返回 {len(data)} 条数据"
                return str(data)[:200]
        err = str(output.get("error") or output.get("message") or "").strip()
        if err:
            return f"错误: {err[:100]}"
        return str(output)[:200]

    def _run_single_tool(
        self,
        tool_id: str,
        action: str,
        params: dict[str, _facade().Any],
        runtime_context: dict[str, _facade().Any],
        max_retries: int,
        retryable: bool = True,
    ) -> _facade().NodeExecutionResult:
        merged_params = dict(params or {})
        merged_params["_runtime_context"] = runtime_context
        retries = 0
        last_error = ""
        started_at = _facade().datetime.now(_facade().UTC).isoformat()
        started_perf = _facade().time.perf_counter()
        attempts: list[dict[str, _facade().Any]] = []
        last_output: dict[str, _facade().Any] = {}
        effective_max_retries = max_retries if retryable else 0
        while retries <= effective_max_retries:
            attempt_started = _facade().time.perf_counter()
            try:
                output = self._dispatch(tool_id=tool_id, action=action, params=merged_params)
                if isinstance(output, dict):
                    last_output = output
                if output.get("success", False):
                    finished_at = _facade().datetime.now(_facade().UTC).isoformat()
                    return _facade().NodeExecutionResult(
                        node_id=f"agent_{tool_id}_{action}",
                        success=True,
                        tool_id=tool_id,
                        action=action,
                        params=dict(params or {}),
                        output=output,
                        retries=retries,
                        retryable=retryable,
                        started_at=started_at,
                        finished_at=finished_at,
                        duration_ms=self._elapsed_ms(started_perf),
                        attempts=attempts
                        + [self._attempt_summary(retries + 1, True, "", attempt_started)],
                    )
                last_error = str(output.get("message") or output.get("error") or "unknown error")
                attempts.append(
                    self._attempt_summary(retries + 1, False, last_error, attempt_started)
                )
            except _facade().RECOVERABLE_ERRORS as err:
                last_error = str(err)
                attempts.append(
                    self._attempt_summary(retries + 1, False, last_error, attempt_started)
                )
                _facade().logger.warning(
                    "AgenticLoop 工具执行失败 %s.%s: %s", tool_id, action, err, exc_info=True
                )
            retries += 1
        finished_at = _facade().datetime.now(_facade().UTC).isoformat()
        return _facade().NodeExecutionResult(
            node_id=f"agent_{tool_id}_{action}",
            success=False,
            tool_id=tool_id,
            action=action,
            params=dict(params or {}),
            output=last_output,
            error=last_error,
            retries=max(0, retries - 1),
            retryable=retryable,
            recovery_hint=self._recovery_hint(
                tool_id=tool_id,
                action=action,
                error=last_error,
                output=last_output,
                retryable=retryable,
            ),
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=self._elapsed_ms(started_perf),
            attempts=attempts,
        )

    @staticmethod
    def _has_non_empty_param(params: dict[str, _facade().Any], keys: tuple[str, ...]) -> bool:
        for k in keys:
            v = params.get(k)
            if v is not None and str(v).strip():
                return True
        return False

    def _merge_runtime_fallback_params(
        self,
        node: _facade().WorkflowNode,
        merged_params: dict[str, _facade().Any],
        runtime_context: dict[str, _facade().Any],
    ) -> None:
        user_msg = str(runtime_context.get("message") or "").strip()
        if not user_msg:
            return
        if node.tool_id == "products" and node.action == "query":
            if not self._has_non_empty_param(
                merged_params, ("keyword", "model_number", "product_name", "name", "unit_name")
            ):
                keyword = _facade().inject_product_query_fallback(merged_params, user_msg)
                _facade().logger.info(
                    "工作流 products.query %s",
                    f"注入有效检索词: {keyword[:80]}" if keyword else "按全量列表请求执行",
                )
        elif node.tool_id == "customers" and node.action == "query":
            if not self._has_non_empty_param(
                merged_params, ("keyword", "unit_name", "customer_name", "name")
            ):
                merged_params.pop("keyword", None)
                _facade().logger.info(
                    "工作流 customers.query 无检索词，按全量列表执行（不注入用户原话）"
                )

    @staticmethod
    def _elapsed_ms(started_perf: float) -> int:
        return max(0, int((_facade().time.perf_counter() - started_perf) * 1000))
