# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.planner")


class __LLMWorkflowPlannerPart01MixinPart01Mixin:
    def __init__(self) -> None:
        self._ai_service = _facade().get_ai_conversation_service()

    def plan(
        self,
        user_id: str,
        message: str,
        tool_registry: dict[str, _facade().Any],
        context: dict[str, _facade().Any] | None = None,
    ) -> _facade().PlanGraph:
        context = dict(context or {})
        session_key = str(context.get("session_id") or context.get("conversation_id") or "").strip()
        plan_id = (
            f"wp-{session_key}-{_facade().uuid.uuid4().hex[:8]}"
            if session_key
            else f"wp-{_facade().uuid.uuid4().hex}"
        )
        from app.application.normal_chat_dispatch import resolve_tool_execution_profile

        profile = resolve_tool_execution_profile(context)
        registry_for_plan = _facade()._filter_tool_registry_for_profile(tool_registry, profile)
        from app.application.normal_chat_dispatch import route_normal_mode_message

        _route = route_normal_mode_message(str(message or ""))
        if (
            "sales" in registry_for_plan
            and str(_route.get("intent") or "") == "sales_write"
            and (str(_route.get("action") or "") == "execute_closed_loop")
            and isinstance(_route.get("payload"), dict)
            and bool(_route.get("payload"))
        ):
            from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph

            return _facade().cast(
                "PlanGraph",
                finalize_planned_graph(
                    self._decorate_plan(
                        self._fallback_plan(plan_id, message, registry_for_plan),
                        message,
                        registry_for_plan,
                    ),
                    plan_id=plan_id,
                    context=context,
                    validate=_facade().validate_plan_graph,
                    fallback_factory=lambda: self._fallback_plan(
                        plan_id, message, registry_for_plan
                    ),
                    warn=_facade().logger.warning,
                ),
            )
        try:
            from app.application import get_user_memory_rag_app_service
            from app.application.conversation_memory import resolve_vector_memory_owner_id

            memory_owner_id = resolve_vector_memory_owner_id(user_id, context)
            rag = get_user_memory_rag_app_service()
            rag_res = rag.query(user_id=memory_owner_id, query_text=message, top_k=3)
            hits = (rag_res or {}).get("hits") if isinstance(rag_res, dict) else None
            if isinstance(hits, list) and hits:
                summary = rag.format_for_prompt(
                    user_id=memory_owner_id, query_text=message, hits=hits, max_hits=4
                )
                context["user_memory_rag"] = {"summary": summary}
        except ImportError:
            _facade().logger.debug("用户记忆 RAG 服务不可用（不阻断主流程）")
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning("用户记忆 RAG 不可用（不阻断主流程）: %s", e)
        try:
            from app.application.conversation_memory import resolve_memory_owner_id
            from app.services.user_memory_service import get_user_memory_service

            memory_owner_id = resolve_memory_owner_id(user_id, context)
            memory_v2_summary = get_user_memory_service().format_memory_v2_for_prompt(
                user_id=memory_owner_id, max_items=6
            )
            if "无已确认记忆" not in memory_v2_summary:
                context["memory_v2"] = {"summary": memory_v2_summary}
        except ImportError:
            _facade().logger.debug("Memory v2 服务不可用（不阻断主流程）")
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning("Memory v2 不可用（不阻断主流程）: %s", e)
        from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph

        planned = None
        from app.application.chat_tool_intent import looks_like_erp_hr_management_intent

        if looks_like_erp_hr_management_intent(message) and "erp_hr" in registry_for_plan:
            deterministic = self._fallback_plan(plan_id, message, registry_for_plan)
            if deterministic.intent == "erp_hr_management" and deterministic.nodes:
                planned = deterministic
        if planned is None and (
            _facade()._looks_like_business_db_write(message, message.lower())
            and "business_db" in registry_for_plan
        ):
            deterministic = self._fallback_plan(plan_id, message, registry_for_plan)
            if deterministic.intent == "business_db_write" and deterministic.nodes:
                planned = deterministic
        if planned is None:
            planned = self._plan_with_react_multiagent(
                plan_id, user_id, message, registry_for_plan, context
            )
        return _facade().cast(
            "PlanGraph",
            finalize_planned_graph(
                self._decorate_plan(planned, message, registry_for_plan),
                plan_id=plan_id,
                context=context,
                validate=_facade().validate_plan_graph,
                fallback_factory=lambda: self._fallback_plan(plan_id, message, registry_for_plan),
                warn=_facade().logger.warning,
            ),
        )

    def _decorate_plan(
        self,
        plan: _facade().PlanGraph | None,
        message: str,
        tool_registry: dict[str, _facade().Any],
    ) -> _facade().PlanGraph | None:
        """对规划产出的 PlanGraph 追加确定性条件边与反问澄清节点。

        不强行依赖 LLM 输出：条件边/反问节点由规则派生，保证行为可测、向后兼容。
        """
        if plan is None:
            return None
        plan = self._apply_conditional_edge_rules(plan, message, tool_registry)
        plan = self._apply_clarify_rules(plan, tool_registry)
        return plan

    def _apply_conditional_edge_rules(
        self, plan: _facade().PlanGraph, message: str, tool_registry: dict[str, _facade().Any]
    ) -> _facade().PlanGraph:
        """确定性条件边规则：把"检查/查询 + 后续决策"表达为 branches。

        当前规则：计划含库存检查（query/read/check_stock）且消息带采购意图时，
        为检查节点挂上 ``{"key": "low_stock", "equals": true}`` → 采购节点 的条件边。
        """
        if any(k in message for k in ("库存", "stock", "Stock")):
            check_nodes = [
                n
                for n in plan.nodes
                if str(n.action or "").lower() in ("query", "read", "check", "check_stock")
                and "stock" in str(n.tool_id or "").lower()
            ]
            purchase_nodes = [
                n
                for n in plan.nodes
                if "purchase" in str(n.tool_id or "").lower() or "采购" in (n.description or "")
            ]
            if check_nodes and purchase_nodes:
                check = check_nodes[0]
                if not check.branches:
                    check.branches.append(
                        _facade().Branch(
                            target=purchase_nodes[0].node_id,
                            condition={"key": "low_stock", "equals": True},
                        )
                    )
        return plan

    def _apply_clarify_rules(
        self, plan: _facade().PlanGraph, tool_registry: dict[str, _facade().Any]
    ) -> _facade().PlanGraph:
        """确定性反问规则：写/高风险节点存在关键参数缺失或多候选歧义时，在图首部插入 clarify 节点。

        复用 ``clarification_node.needs_clarification`` 检测，并用 ``build_clarify_node``
        生成反问节点，其 ``branches`` 依据用户确认结果路由回原操作节点。
        """
        items = _facade().needs_clarification(plan, tool_registry)
        from .clarification_node import detect_erp_clarification

        items = list(items) + detect_erp_clarification(plan)
        if not items:
            return plan
        inserted: list[_facade().WorkflowNode] = []
        for item in items:
            clarify = _facade().build_clarify_node(
                item["question"], ambient={"target_node_id": item["node_id"]}
            )
            plan.nodes.insert(0, clarify)
            inserted.append(clarify)
        if _facade().validate_plan_graph(plan) is not None:
            for clarify in inserted:
                if clarify in plan.nodes:
                    plan.nodes.remove(clarify)
        return plan
