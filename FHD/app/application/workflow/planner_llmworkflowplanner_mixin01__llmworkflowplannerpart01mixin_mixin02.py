# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.planner")


class __LLMWorkflowPlannerPart01MixinPart02Mixin:
    def _plan_with_react_multiagent(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, _facade().Any],
        context: dict[str, _facade().Any],
    ) -> _facade().PlanGraph | None:
        """
        多步 ReAct/CoT 风格规划（简化实现）：
        1) 先用 LLM 生成候选 PlanGraph（DecomposerAgent）。
        2) 基于候选 PlanGraph 抽取低风险只读节点做 ToolProbe（真实工具调用）。
        3) 将探测结果注入 prompt 再次规划得到最终 PlanGraph（PlanComposerAgent）。
        4) validate_plan_graph；失败则降级 fallback（CriticAgent）。
        """
        candidate = self._plan_with_llm(
            plan_id=plan_id,
            user_id=user_id,
            message=message,
            tool_registry=tool_registry,
            context=context,
        )
        if candidate is None:
            return None
        runtime_context_for_probe = dict(context or {})
        runtime_context_for_probe["message"] = str(message or "")
        probe_requests: list[dict[str, _facade().Any]] = []
        for node in candidate.nodes or []:
            tid = str(node.tool_id or "").strip()
            act = str(node.action or "").strip()
            if not tid or not act:
                continue
            tool_spec = tool_registry.get(tid)
            if not isinstance(tool_spec, dict):
                continue
            actions = tool_spec.get("actions") or {}
            if not isinstance(actions, dict):
                continue
            meta = actions.get(act)
            if not isinstance(meta, dict):
                continue
            risk = str(meta.get("risk") or "").strip().lower()
            idempotent = bool(meta.get("idempotent", False))
            if risk != "low" or not idempotent:
                continue
            if act not in (
                "query",
                "exists",
                "list",
                "read",
                "view",
                "preview",
                "decompose",
                "extract",
                "refresh_contact_cache",
                "refresh_messages_cache",
            ):
                continue
            probe_requests.append({"tool_id": tid, "action": act, "params": node.params or {}})
        probe_requests = probe_requests[:3]
        probe_outputs: list[dict[str, _facade().Any]] = []
        task_agent = None
        try:
            from app.services.task_agent import TaskAgent

            task_agent = TaskAgent()
        except ImportError:
            _facade().logger.debug("TaskAgent 服务不可用")
            task_agent = None
        except RuntimeError as e:
            _facade().logger.warning("TaskAgent 初始化失败: %s", e)
            task_agent = None
        for pr in probe_requests:
            try:
                tool_id = str(pr.get("tool_id") or "").strip()
                action = str(pr.get("action") or "").strip()
                raw_params = pr.get("params")
                params: dict[str, _facade().Any] = (
                    dict(raw_params) if isinstance(raw_params, dict) else {}
                )
                tool_spec = tool_registry.get(tool_id) or {}
                actions = tool_spec.get("actions") or {}
                action_meta = actions.get(action) if isinstance(actions, dict) else None
                if not isinstance(action_meta, dict):
                    continue
                risk = str(action_meta.get("risk") or "").strip().lower()
                idempotent = bool(action_meta.get("idempotent", False))
                if risk != "low" or not idempotent:
                    continue
                required_params = action_meta.get("required_params") or []
                if not isinstance(required_params, list):
                    required_params = []
                missing_required = []
                for k in required_params:
                    if (
                        k not in (params or {})
                        or params.get(k) is None
                        or str(params.get(k)).strip() == ""
                    ):
                        missing_required.append(k)
                if missing_required:
                    continue
                if tool_id == "products" and action == "query":
                    if not (
                        (params or {}).get("keyword")
                        or (params or {}).get("model_number")
                        or (params or {}).get("unit_name")
                    ):
                        try:
                            from app.application.normal_chat_dispatch import (
                                route_normal_mode_message,
                            )

                            rr = route_normal_mode_message(message)
                            if rr.get("intent") == "product_query":
                                slots = rr.get("slots") or {}
                                (params or {}).update(
                                    {
                                        "keyword": slots.get("keyword")
                                        or (params or {}).get("keyword")
                                        or "",
                                        "model_number": slots.get("model_number")
                                        or (params or {}).get("model_number")
                                        or "",
                                        "unit_name": slots.get("unit_name")
                                        or (params or {}).get("unit_name")
                                        or "",
                                    }
                                )
                        except (ImportError, RuntimeError):
                            if not (params or {}).get("keyword"):
                                params["keyword"] = str(message or "").strip()[:80]
                if tool_id == "customers" and action == "query":
                    if (
                        not ((params or {}).get("keyword") or params.get("customer_name"))
                        and task_agent is not None
                    ):
                        try:
                            cust_slots = task_agent._extract_customer_query_slots(
                                str(message or "")
                            )
                            if isinstance(cust_slots, dict):
                                extracted_kw = str(
                                    cust_slots.get("keyword")
                                    or cust_slots.get("customer_name")
                                    or ""
                                ).strip()
                                msg_trim = str(message or "").strip()
                                if extracted_kw and extracted_kw != msg_trim:
                                    params["keyword"] = extracted_kw
                        except (ImportError, RuntimeError):
                            (params or {}).pop("keyword", None)
                from app.application.facades.tools_facade import execute_registered_workflow_tool

                merged_params = dict(params or {})
                merged_params["_runtime_context"] = dict(runtime_context_for_probe)
                out = execute_registered_workflow_tool(
                    tool_id=tool_id, action=action, params=merged_params
                )
                data_preview = ""
                if isinstance(out, dict):
                    data_value = out.get("data")
                    if isinstance(data_value, list):
                        data_preview = str(data_value[:3])[:600]
                    elif data_value is not None:
                        data_preview = str(data_value)[:600]
                    elif out.get("raw") is not None:
                        data_preview = str(out.get("raw"))[:600]
                    else:
                        data_preview = str(out)[:600]
                if isinstance(out, dict) and out.get("success") is True:
                    probe_outputs.append(
                        {
                            "tool_id": tool_id,
                            "action": action,
                            "success": True,
                            "message": str(
                                (out or {}).get("message") or (out or {}).get("error") or ""
                            ),
                            "data_preview": data_preview,
                        }
                    )
            except (ValueError, TypeError) as e:
                _facade().logger.debug("ToolProbe 参数错误（将跳过注入）: %s", e)
                continue
            except RuntimeError as e:
                _facade().logger.warning("ToolProbe 运行时错误（将跳过注入）: %s", e)
                continue
        context_for_compose = dict(context or {})
        if probe_outputs:
            context_for_compose["tool_probe_outputs"] = probe_outputs
        final_plan = self._plan_with_llm(
            plan_id=plan_id,
            user_id=user_id,
            message=message,
            tool_registry=tool_registry,
            context=context_for_compose,
        )
        if final_plan is None:
            return None
        err = _facade().validate_plan_graph(final_plan)
        if err is None:
            err = self._validate_required_params(final_plan, tool_registry)
        if err is None:
            return final_plan
        _facade().logger.warning("CriticAgent 校验失败，尝试 LLM 修复（最多 1 次）: %s", err)
        repaired = self._critic_repair_with_llm(
            plan_id=plan_id,
            user_id=user_id,
            message=message,
            tool_registry=tool_registry,
            context=context_for_compose,
            error=err,
            invalid_plan=final_plan,
        )
        if repaired is not None:
            err2 = _facade().validate_plan_graph(repaired)
            if err2 is None:
                err2 = self._validate_required_params(repaired, tool_registry)
            if err2 is None:
                return repaired
        _facade().logger.warning("CriticAgent 修复失败（回退 fallback）: %s", err)
        return None

    @staticmethod
    def _validate_required_params(
        plan: _facade().PlanGraph, tool_registry: dict[str, _facade().Any]
    ) -> str | None:
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
