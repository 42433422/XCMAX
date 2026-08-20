# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.planner")


class __LLMWorkflowPlannerPart01MixinPart03Mixin:
    def _critic_repair_with_llm(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, _facade().Any],
        context: dict[str, _facade().Any],
        error: str,
        invalid_plan: _facade().PlanGraph,
    ) -> _facade().PlanGraph | None:
        """CriticAgent：LLM 修复无效 PlanGraph（只重试一次）。"""
        api_key = getattr(self._ai_service, "api_key", "") or ""
        if not api_key:
            return None
        try:
            tool_specs = []
            for tool_id, spec in tool_registry.items():
                actions = spec.get("actions") or {}
                action_specs = []
                for action_name, action_meta in actions.items():
                    if not isinstance(action_meta, dict):
                        continue
                    action_specs.append(
                        {
                            "action": action_name,
                            "risk": action_meta.get("risk", "low"),
                            "idempotent": bool(action_meta.get("idempotent", False)),
                            "required_params": action_meta.get("required_params", []),
                        }
                    )
                tool_specs.append(
                    {
                        "tool_id": tool_id,
                        "description": spec.get("description", ""),
                        "actions": action_specs,
                    }
                )
            invalid_dict = {
                "plan_id": invalid_plan.plan_id,
                "intent": invalid_plan.intent,
                "todo_steps": invalid_plan.todo_steps,
                "risk_level": invalid_plan.risk_level,
                "nodes": [
                    {
                        "node_id": n.node_id,
                        "tool_id": n.tool_id,
                        "action": n.action,
                        "params": n.params,
                        "risk": n.risk,
                        "idempotent": n.idempotent,
                        "description": n.description,
                        "depends_on": n.depends_on,
                    }
                    for n in invalid_plan.nodes or []
                ],
            }
            prompt = {
                "task": "修复一个无效的工作流 PlanGraph JSON，使其满足 validate_plan_graph 规则且满足 required_params 约束。",
                "rules": [
                    "只输出 JSON，不要 markdown。",
                    "node_id 必须唯一且非空。",
                    "所有 nodes 项必须包含 tool_id/action/params/risk/idempotent/description/depends_on 结构字段。",
                    "对于 required_params：必须在 params 中提供非空值（若无法从 user_message 推断，仍需给出最合理的非空占位/默认值，保证结构字段不缺失）。",
                    "员工相关意图优先使用 employee.list/employee.execute；不知道 employee_id 时先 list，不要伪造员工 ID。",
                    "数据库读写必须使用 business_db.read/write 的 entity/operation/payload 结构，不得生成 sql/raw_sql/query_sql。",
                    "business_db.write 只在用户明确要求新增/添加/写入/入库/删除/更新时使用；普通查询使用 business_db.read。",
                ],
                "validation_error": error,
                "invalid_plan": invalid_dict,
                "user_message": message,
                "context": context,
                "tool_registry": tool_specs,
                "output_schema": {
                    "intent": "string",
                    "todo_steps": ["string"],
                    "risk_level": "low|medium|high",
                    "nodes": [
                        {
                            "node_id": "string",
                            "tool_id": "string",
                            "action": "string",
                            "params": {},
                            "risk": "low|medium|high",
                            "idempotent": "bool",
                            "description": "string",
                            "depends_on": ["node_id"],
                        }
                    ],
                },
            }
            messages = [
                {"role": "system", "content": "你是工作流计划修复器，只输出可执行 JSON。"},
                {"role": "user", "content": _facade().json.dumps(prompt, ensure_ascii=False)},
            ]
            from app.infrastructure.llm.providers.credentials import default_chat_completions_url

            api_url = getattr(self._ai_service, "api_url", "") or default_chat_completions_url()
            response = (
                _facade()
                ._get_planner_http_client()
                .post(
                    api_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": getattr(self._ai_service, "model", "") or "deepseek-chat",
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": 1000,
                    },
                )
            )
            if response.status_code >= 400:
                return None
            response_data = response.json()
            raw = (
                (response_data.get("choices") or [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if not raw:
                return None
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = _facade().json.loads(raw)
            nodes: list[_facade().WorkflowNode] = []
            for idx, node in enumerate(parsed.get("nodes", []), start=1):
                nodes.append(
                    _facade().WorkflowNode(
                        node_id=str(node.get("node_id") or f"node_{idx}"),
                        tool_id=str(node.get("tool_id") or ""),
                        action=str(node.get("action") or ""),
                        params=node.get("params") or {},
                        risk=_facade().normalize_workflow_risk(str(node.get("risk") or "low")),
                        idempotent=bool(node.get("idempotent", False)),
                        description=str(node.get("description") or ""),
                        depends_on=[str(x) for x in node.get("depends_on") or []],
                    )
                )
            return _facade().PlanGraph(
                plan_id=plan_id,
                intent=str(parsed.get("intent") or invalid_plan.intent or "dynamic_workflow"),
                todo_steps=[
                    str(x) for x in parsed.get("todo_steps") or invalid_plan.todo_steps or []
                ],
                nodes=nodes,
                risk_level=_facade().normalize_workflow_risk(
                    str(parsed.get("risk_level") or invalid_plan.risk_level or "low")
                ),
                metadata={"planner": "critic_repair", "message": message},
            )
        except (ValueError, TypeError) as e:
            _facade().logger.debug("CriticAgent 修复参数错误: %s", e)
            return None
        except RuntimeError as e:
            _facade().logger.warning("CriticAgent 修复运行时错误: %s", e)
            return None

    def _plan_with_llm(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, _facade().Any],
        context: dict[str, _facade().Any],
    ) -> _facade().PlanGraph | None:
        try:
            tool_specs = []
            for tool_id, spec in tool_registry.items():
                actions = spec.get("actions", {})
                action_specs = []
                for action_name, action_meta in actions.items():
                    action_specs.append(
                        {
                            "action": action_name,
                            "risk": action_meta.get("risk", "low"),
                            "idempotent": bool(action_meta.get("idempotent", False)),
                            "required_params": action_meta.get("required_params", []),
                        }
                    )
                tool_specs.append(
                    {
                        "tool_id": tool_id,
                        "description": spec.get("description", ""),
                        "actions": action_specs,
                    }
                )
            recent_messages = []
            conv_ctx = self._ai_service.get_context(user_id)
            if conv_ctx and conv_ctx.conversation_history:
                recent_messages = conv_ctx.conversation_history[-6:]
            prompt = {
                "task": "根据用户意图生成可执行工作流计划（JSON）。",
                "rules": [
                    "只输出 JSON，不要 markdown。",
                    "优先使用 tool_registry 中已有工具与 action。",
                    "如果步骤有依赖，写到 depends_on。",
                    "todo_steps 要贴合用户语义，不要模板化。",
                    "risk_level 按节点最高风险确定。",
                    "员工相关意图：若用户只是问有哪些员工，使用 employee.list；若明确指定 employee_id/pack_id 并要求执行，使用 employee.execute 并填写 task；不知道员工 ID 时先 list，不要编造。",
                    "数据库相关意图：读数据库/查库使用 business_db.read，并填写 entity；写入/新增/更新/删除/入库才使用 business_db.write，并填写 entity、operation、payload。",
                    "business_db 只能访问 customers/products/materials/shipment_records；禁止生成 sql/raw_sql/query_sql 或任意 SQL。",
                    "对 products.query：必须在 params 填入 keyword 或 model_number 等检索词；对 customers.query：列表/计数问法可不填 keyword（空=全部客户）；指名查询再填 keyword，从用户话中提取（如「七彩乐园的9803」→ keyword 含单位+型号），禁止留空对象 {}。",
                    "如果 context 中包含 tool_probe_outputs 且其中 success=true，请优先使用其中 data_preview 的信息来补全 nodes.params。",
                    "如果 context 中包含 memory_v2.summary，只能把其中已确认 active 记忆用于补全偏好、客户别名、产品习惯或任务上下文；禁止使用未确认候选或编造记忆。",
                    "若 context 中 tool_execution_profile 为 normal 或 ui_surface 为 normal 且 intent_channel 为 pro：仅可使用 availability 为 shared 或 normal_only 的工具；产品查询优先 normal_slot_dispatch.product_query 或 products.query。",
                    "若 context 为全专业链路（未带上述混合标记）：仅使用 shared 或 pro_only，勿选 normal_only。",
                ],
                "user_message": message,
                "recent_messages": recent_messages,
                "context": context,
                "tool_probe_outputs": (context or {}).get("tool_probe_outputs")
                if isinstance(context, dict)
                else [],
                "tool_registry": tool_specs,
                "output_schema": {
                    "intent": "string",
                    "todo_steps": ["string"],
                    "risk_level": "low|medium|high",
                    "nodes": [
                        {
                            "node_id": "string",
                            "tool_id": "string",
                            "action": "string",
                            "params": {},
                            "risk": "low|medium|high",
                            "idempotent": "bool",
                            "description": "string",
                            "depends_on": ["node_id"],
                        }
                    ],
                },
            }
            messages = [
                {"role": "system", "content": "你是工作流规划器，只输出可执行 JSON。"},
                {"role": "user", "content": _facade().json.dumps(prompt, ensure_ascii=False)},
            ]
            response_data = _facade().request_planner_completion(
                ai_service=self._ai_service,
                context=context,
                messages=messages,
                http_client_factory=_facade()._get_planner_http_client,
            )
            if response_data is None:
                return None
            raw = (
                (response_data.get("choices") or [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if not raw:
                return None
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            parsed = _facade().json.loads(raw)
            nodes: list[_facade().WorkflowNode] = []
            for idx, node in enumerate(parsed.get("nodes", []), start=1):
                nodes.append(
                    _facade().WorkflowNode(
                        node_id=str(node.get("node_id") or f"node_{idx}"),
                        tool_id=str(node.get("tool_id") or ""),
                        action=str(node.get("action") or ""),
                        params=node.get("params") or {},
                        risk=_facade().normalize_workflow_risk(str(node.get("risk") or "low")),
                        idempotent=bool(node.get("idempotent", False)),
                        description=str(node.get("description") or ""),
                        depends_on=[str(x) for x in node.get("depends_on") or []],
                    )
                )
            tool_probe_outputs: list[dict[str, _facade().Any]] = []
            user_memory_rag_summary = ""
            memory_v2_summary = ""
            try:
                if isinstance(context, dict):
                    user_memory_rag = context.get("user_memory_rag")
                    if isinstance(user_memory_rag, dict):
                        user_memory_rag_summary = str(user_memory_rag.get("summary") or "").strip()
                    memory_v2 = context.get("memory_v2")
                    if isinstance(memory_v2, dict):
                        memory_v2_summary = str(memory_v2.get("summary") or "").strip()
                    tpo = context.get("tool_probe_outputs")
                    if isinstance(tpo, list):
                        tool_probe_outputs = []
                        for item in tpo[:2]:
                            if not isinstance(item, dict):
                                continue
                            tool_probe_outputs.append(
                                {
                                    "tool_id": item.get("tool_id"),
                                    "action": item.get("action"),
                                    "success": bool(item.get("success")),
                                    "message": str(item.get("message") or "").strip()[:120],
                                    "data_preview": str(item.get("data_preview") or "").strip()[
                                        :160
                                    ],
                                }
                            )
            except (ImportError, RuntimeError):
                tool_probe_outputs = []
                user_memory_rag_summary = ""
                memory_v2_summary = ""
            return _facade().PlanGraph(
                plan_id=plan_id,
                intent=str(parsed.get("intent") or "dynamic_workflow"),
                todo_steps=[str(x) for x in parsed.get("todo_steps") or []],
                nodes=nodes,
                risk_level=_facade().normalize_workflow_risk(
                    str(parsed.get("risk_level") or "low")
                ),
                metadata={
                    "planner": "llm",
                    "message": message,
                    "user_memory_rag_summary": user_memory_rag_summary,
                    "memory_v2_summary": memory_v2_summary,
                    "tool_probe_outputs": tool_probe_outputs,
                },
            )
        except (ValueError, TypeError) as err:
            _facade().logger.debug("LLM 规划参数错误，回退规则规划: %s", err)
            return None
        except RuntimeError as err:
            _facade().logger.warning("LLM 规划运行时错误，回退规则规划: %s", err)
            return None
