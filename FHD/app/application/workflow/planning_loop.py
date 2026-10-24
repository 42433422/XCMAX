"""Read-only plan probes followed by validation and at most one critic repair."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

from app.application.workflow.planner_tool_dispatch import RegisteredToolExecutor
from app.application.workflow.types import PlanGraph

logger = logging.getLogger(__name__)


class GeneratePlan(Protocol):
    def __call__(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, Any],
        context: dict[str, Any],
    ) -> PlanGraph | None: ...


class RepairPlan(Protocol):
    def __call__(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, Any],
        context: dict[str, Any],
        error: str,
        invalid_plan: PlanGraph,
    ) -> PlanGraph | None: ...


class PlanningLoop:
    def __init__(
        self,
        generate: GeneratePlan,
        repair: RepairPlan,
        execute_probe: RegisteredToolExecutor,
        validate: Callable[[PlanGraph], str | None],
        validate_params: Callable[[PlanGraph, dict[str, Any]], str | None],
    ) -> None:
        self.generate = generate
        self.repair = repair
        self.execute_probe = execute_probe
        self.validate = validate
        self.validate_params = validate_params

    def plan(
        self,
        plan_id: str,
        user_id: str,
        message: str,
        tool_registry: dict[str, Any],
        context: dict[str, Any],
    ) -> PlanGraph | None:
        """
        多步 ReAct/CoT 风格规划（简化实现）：
        1) 先用 LLM 生成候选 PlanGraph（DecomposerAgent）。
        2) 基于候选 PlanGraph 抽取低风险只读节点做 ToolProbe（真实工具调用）。
        3) 将探测结果注入 prompt 再次规划得到最终 PlanGraph（PlanComposerAgent）。
        4) validate_plan_graph；失败则降级 fallback（CriticAgent）。
        """
        candidate = self.generate(
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
        probe_requests: list[dict[str, Any]] = []
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
        probe_outputs: list[dict[str, Any]] = []
        task_agent = None
        try:
            from app.services.task_agent import TaskAgent

            task_agent = TaskAgent()
        except ImportError:
            logger.debug("TaskAgent 服务不可用")
            task_agent = None
        except RuntimeError as e:
            logger.warning("TaskAgent 初始化失败: %s", e)
            task_agent = None
        for pr in probe_requests:
            try:
                tool_id = str(pr.get("tool_id") or "").strip()
                action = str(pr.get("action") or "").strip()
                raw_params = pr.get("params")
                params: dict[str, Any] = dict(raw_params) if isinstance(raw_params, dict) else {}
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

                merged_params = dict(params or {})
                merged_params["_runtime_context"] = dict(runtime_context_for_probe)
                out = self.execute_probe(tool_id=tool_id, action=action, params=merged_params)
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
                logger.debug("ToolProbe 参数错误（将跳过注入）: %s", e)
                continue
            except RuntimeError as e:
                logger.warning("ToolProbe 运行时错误（将跳过注入）: %s", e)
                continue
        context_for_compose = dict(context or {})
        if probe_outputs:
            context_for_compose["tool_probe_outputs"] = probe_outputs
        final_plan = self.generate(
            plan_id=plan_id,
            user_id=user_id,
            message=message,
            tool_registry=tool_registry,
            context=context_for_compose,
        )
        if final_plan is None:
            return None
        err = self.validate(final_plan)
        if err is None:
            err = self.validate_params(final_plan, tool_registry)
        if err is None:
            return final_plan
        logger.warning("CriticAgent 校验失败，尝试 LLM 修复（最多 1 次）: %s", err)
        repaired = self.repair(
            plan_id=plan_id,
            user_id=user_id,
            message=message,
            tool_registry=tool_registry,
            context=context_for_compose,
            error=err,
            invalid_plan=final_plan,
        )
        if repaired is not None:
            err2 = self.validate(repaired)
            if err2 is None:
                err2 = self.validate_params(repaired, tool_registry)
            if err2 is None:
                return repaired
        logger.warning("CriticAgent 修复失败（回退 fallback）: %s", err)
        return None
