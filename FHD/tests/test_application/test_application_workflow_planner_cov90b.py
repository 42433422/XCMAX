"""Second-wave coverage tests for app/application/workflow/planner.py.

Targets gaps NOT covered by tests/test_application/test_planner_cov90.py:

- LLMWorkflowPlanner.plan() entry method incl. user-memory RAG / memory-v2
  injection success + ImportError + RECOVERABLE_ERRORS branches (1502-1544).
- _execute_import_excel_tool smart-price-resolver exception handlers
  (ImportError / ValueError / RuntimeError, 1239-1244) and the explicit
  price_column second-pass loop (1256-1260).
- _plan_with_react_multiagent probe-enrichment branches: products.query +
  customers.query keyword backfill, TaskAgent RuntimeError init, probe-skip
  guards, and probe execution exception handlers (1610-1716, 1634-1636,
  1751-1756).
- _critic_repair_with_llm: non-dict action_meta skip during tool_specs build
  (1849) and RuntimeError handler (1987-1988).
- _fallback_plan employee-dispatch branch incl. non-dict item skip and the
  ImportError/RuntimeError guard around build_employee_tools_status
  (2197-2208).

All external dependencies (LLM HTTP, services, TaskAgent, memory services,
Excel resolver) are mocked. Excel I/O uses a real openpyxl workbook under
tmp_path for determinism; nothing touches the network or a real DB.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import openpyxl
import pytest

from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _execute_import_excel_tool,
)
from app.application.workflow.types import PlanGraph, WorkflowNode

# ---------------------------------------------------------------------------
# Helpers (kept independent of test_planner_cov90.py to avoid cross-file deps)
# ---------------------------------------------------------------------------


def _make_planner() -> LLMWorkflowPlanner:
    with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_get:
        mock_get.return_value = MagicMock()
        planner = LLMWorkflowPlanner()
    ai = MagicMock()
    ai.api_key = "sk-test"
    ai.api_url = "http://llm.test/v1/chat/completions"
    ai.model = "deepseek-chat"
    ai.get_context.return_value = None
    planner._ai_service = ai
    return planner


def _llm_response(content: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def _write_xlsx(path, headers, rows) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    wb.save(str(path))
    return str(path)


def _node(tool_id: str, action: str, params: dict, *, risk="low", idempotent=True) -> WorkflowNode:
    return WorkflowNode(
        node_id="n1",
        tool_id=tool_id,
        action=action,
        params=params,
        risk=risk,
        idempotent=idempotent,
    )


def _plan_with(node: WorkflowNode, intent="查询") -> PlanGraph:
    return PlanGraph(
        plan_id="p",
        intent=intent,
        todo_steps=[intent],
        nodes=[node],
        risk_level="low",
    )


def _valid_plan_json(intent="查询") -> str:
    """A single-node plan JSON that passes validate_plan_graph so plan() returns
    it directly (no critic repair / HTTP) — used to isolate the memory branches."""
    return json.dumps(
        {
            "intent": intent,
            "todo_steps": ["查询"],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "k"},
                }
            ],
        }
    )


# ---------------------------------------------------------------------------
# plan() entry method — memory RAG / memory-v2 injection + degrade branches
# ---------------------------------------------------------------------------


class TestPlanEntryMemoryInjection:
    def test_memory_rag_and_v2_summaries_injected(self) -> None:
        """Both memory sources return content -> summaries flow into context and
        are projected into the final plan metadata by _plan_with_llm."""
        planner = _make_planner()

        rag = MagicMock()
        rag.query.return_value = {"hits": [{"id": 1}]}
        rag.format_for_prompt.return_value = "RAG命中摘要"

        mem_v2 = MagicMock()
        mem_v2.format_memory_v2_for_prompt.return_value = "已确认偏好：喜欢山竹"

        client = MagicMock()
        client.post.return_value = _llm_response(
            json.dumps(
                {
                    "intent": "查询",
                    "todo_steps": ["查询"],
                    "risk_level": "low",
                    "nodes": [
                        {
                            "node_id": "n1",
                            "tool_id": "products",
                            "action": "query",
                            "params": {"keyword": "k"},
                        }
                    ],
                }
            )
        )
        registry = {
            "products": {
                "description": "产品",
                "actions": {"query": {"risk": "low", "idempotent": True, "required_params": []}},
            }
        }
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="pro_default",
            ),
            patch(
                "app.application.get_user_memory_rag_app_service",
                return_value=rag,
            ),
            patch(
                "app.services.user_memory_service.get_user_memory_service",
                return_value=mem_v2,
            ),
            patch(
                "app.application.workflow.planner._get_planner_http_client",
                return_value=client,
            ),
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                return_value={"success": True, "data": [], "message": ""},
            ),
        ):
            plan = planner.plan("u1", "查产品", registry, context={})

        # The plan came back from the LLM path (not fallback).
        assert plan.metadata["planner"] == "llm"
        assert plan.metadata["user_memory_rag_summary"] == "RAG命中摘要"
        assert plan.metadata["memory_v2_summary"] == "已确认偏好：喜欢山竹"
        rag.query.assert_called_once()
        mem_v2.format_memory_v2_for_prompt.assert_called_once()

    def test_memory_v2_no_confirmed_skipped(self) -> None:
        """memory-v2 returns the '无已确认记忆' sentinel -> summary not injected."""
        planner = _make_planner()
        rag = MagicMock()
        rag.query.return_value = {"hits": []}  # empty hits -> rag summary skipped
        mem_v2 = MagicMock()
        mem_v2.format_memory_v2_for_prompt.return_value = "无已确认记忆"

        client = MagicMock()
        client.post.return_value = _llm_response(_valid_plan_json())
        registry = {
            "products": {
                "description": "产品",
                "actions": {"query": {"risk": "low", "idempotent": True, "required_params": []}},
            }
        }
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="pro_default",
            ),
            patch(
                "app.application.get_user_memory_rag_app_service",
                return_value=rag,
            ),
            patch(
                "app.services.user_memory_service.get_user_memory_service",
                return_value=mem_v2,
            ),
            patch(
                "app.application.workflow.planner._get_planner_http_client",
                return_value=client,
            ),
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                return_value={"success": True, "data": [], "message": ""},
            ),
        ):
            plan = planner.plan("u1", "随便问问", registry, context={})

        assert plan.metadata["user_memory_rag_summary"] == ""
        assert plan.metadata["memory_v2_summary"] == ""

    def test_memory_services_importerror_degrade(self) -> None:
        """Both memory getters raise ImportError -> degrade, plan still produced."""
        planner = _make_planner()
        client = MagicMock()
        client.post.return_value = _llm_response(_valid_plan_json(intent="x"))
        registry = {
            "products": {
                "description": "产品",
                "actions": {"query": {"risk": "low", "idempotent": True, "required_params": []}},
            }
        }
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="pro_default",
            ),
            patch(
                "app.application.get_user_memory_rag_app_service",
                side_effect=ImportError("no rag"),
            ),
            patch(
                "app.services.user_memory_service.get_user_memory_service",
                side_effect=ImportError("no mem"),
            ),
            patch(
                "app.application.workflow.planner._get_planner_http_client",
                return_value=client,
            ),
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                return_value={"success": True, "data": [], "message": ""},
            ),
        ):
            plan = planner.plan("u1", "查产品", registry, context={})

        assert plan.metadata["user_memory_rag_summary"] == ""
        assert plan.metadata["memory_v2_summary"] == ""

    def test_memory_services_recoverable_error_degrade(self) -> None:
        """Memory getters raise a RECOVERABLE error (ValueError) -> warning branch,
        main flow not blocked."""
        planner = _make_planner()
        rag = MagicMock()
        rag.query.side_effect = ValueError("rag transient")
        mem_v2 = MagicMock()
        mem_v2.format_memory_v2_for_prompt.side_effect = ValueError("mem transient")
        client = MagicMock()
        client.post.return_value = _llm_response(_valid_plan_json(intent="x"))
        registry = {
            "products": {
                "description": "产品",
                "actions": {"query": {"risk": "low", "idempotent": True, "required_params": []}},
            }
        }
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="pro_default",
            ),
            patch(
                "app.application.get_user_memory_rag_app_service",
                return_value=rag,
            ),
            patch(
                "app.services.user_memory_service.get_user_memory_service",
                return_value=mem_v2,
            ),
            patch(
                "app.application.workflow.planner._get_planner_http_client",
                return_value=client,
            ),
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                return_value={"success": True, "data": [], "message": ""},
            ),
        ):
            plan = planner.plan("u1", "查产品", registry, context={})

        # Degraded but still produced a valid plan from the LLM path.
        assert plan.metadata["user_memory_rag_summary"] == ""
        assert plan.metadata["memory_v2_summary"] == ""

    def test_invalid_llm_plan_falls_back_to_rules(self) -> None:
        """LLM returns a plan that fails validate_plan_graph -> rule fallback runs.

        We force _plan_with_react_multiagent to yield a graph with a dangling
        depends_on (validation failure) so plan() takes the fallback branch.
        """
        planner = _make_planner()
        bad_plan = PlanGraph(
            plan_id="p",
            intent="x",
            todo_steps=["x"],
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="products",
                    action="query",
                    params={"keyword": "k"},
                    risk="low",
                    idempotent=True,
                    depends_on=["does_not_exist"],
                )
            ],
            risk_level="low",
        )
        registry = {
            "products": {
                "description": "产品",
                "actions": {"query": {"risk": "low", "idempotent": True, "required_params": []}},
            }
        }
        with (
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="pro_default",
            ),
            patch(
                "app.application.get_user_memory_rag_app_service",
                side_effect=ImportError,
            ),
            patch(
                "app.services.user_memory_service.get_user_memory_service",
                side_effect=ImportError,
            ),
            patch.object(planner, "_plan_with_react_multiagent", return_value=bad_plan),
        ):
            plan = planner.plan("u1", "查产品", registry, context={})

        # Fallback plan replaces the invalid LLM plan.
        assert plan.metadata["planner"] == "fallback"


# ---------------------------------------------------------------------------
# _execute_import_excel_tool — smart price resolver exception handlers
# ---------------------------------------------------------------------------


class TestImportExcelResolverExceptions:
    def _services(self):
        products = MagicMock()
        products.get_products.return_value = {"success": True, "data": []}
        products.create_product.return_value = {"success": True}
        customers = MagicMock()
        customers.match_purchase_unit.return_value = None
        customers.create.return_value = {"success": True}
        return products, customers

    @pytest.mark.parametrize(
        "exc",
        [ImportError("no ai service"), ValueError("bad arg"), RuntimeError("resolver boom")],
    )
    def test_resolver_exceptions_fall_back_to_simple_match(self, tmp_path, exc) -> None:
        """When the AI price resolver raises, the function logs and falls back to
        the simple header-keyword match instead of crashing."""
        fp = _write_xlsx(
            tmp_path / "res_exc.xlsx",
            ["产品名称", "型号", "含税单价", "购买单位"],
            [["灯具A", "9803", 12.5, "七彩乐园"]],
        )
        products, customers = self._services()
        with (
            patch("app.bootstrap.get_products_service", return_value=products),
            patch("app.bootstrap.get_customer_app_service", return_value=customers),
            patch(
                "app.application.ai_chat_app_service.AIChatApplicationService"
                "._merge_user_intent_for_price_resolution",
                side_effect=exc,
            ),
        ):
            out = _execute_import_excel_tool({"file_path": fp})
        assert out["success"] is True
        # Simple match still found the price column by keyword.
        assert out["price_column_used"] == "含税单价"
        assert out["created_products"] == 1

    def test_explicit_price_column_absent_from_headers(self, tmp_path) -> None:
        """An explicit price_column that does not match any header keeps price_col
        None through both passes; unit_price stays 0 and price_column_used reports
        '未指定' (since price_col is never resolved)."""
        fp = _write_xlsx(
            tmp_path / "missing_col.xlsx",
            ["产品名称", "型号", "购买单位"],
            [["灯具A", "9803", "七彩乐园"]],
        )
        products, customers = self._services()
        with (
            patch("app.bootstrap.get_products_service", return_value=products),
            patch("app.bootstrap.get_customer_app_service", return_value=customers),
        ):
            out = _execute_import_excel_tool({"file_path": fp, "price_column": "不存在的列名"})
        assert out["success"] is True
        assert out["price_column_used"] == "未指定"
        created_args = products.create_product.call_args[0][0]
        assert created_args["unit_price"] == 0.0


# ---------------------------------------------------------------------------
# _plan_with_react_multiagent — probe enrichment & guard branches
# ---------------------------------------------------------------------------


def _registry_no_required(tool_id="products", action="query"):
    return {
        tool_id: {
            "description": "tool",
            "actions": {action: {"risk": "low", "idempotent": True, "required_params": []}},
        }
    }


class TestProbeEnrichmentBranches:
    def test_products_query_keyword_backfill_via_router(self) -> None:
        """products.query with empty params triggers route_normal_mode_message
        slot backfill (1677-1697)."""
        planner = _make_planner()
        reg = _registry_no_required("products", "query")
        candidate = _plan_with(_node("products", "query", {}))
        final = _plan_with(_node("products", "query", {}), intent="final")

        captured = {}

        def fake_exec(*, tool_id, action, params):
            captured["params"] = dict(params)
            return {"success": True, "data": [{"id": 1}], "message": "ok"}

        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, final]),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                return_value={"intent": "product_query", "slots": {"keyword": "9803"}},
            ) as mock_route,
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                side_effect=fake_exec,
            ),
            patch("app.services.task_agent.TaskAgent", return_value=MagicMock()),
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="查 9803",
                tool_registry=reg,
                context={},
            )
        assert result is final
        mock_route.assert_called_once()
        # The backfilled keyword reached the executed probe.
        assert captured["params"].get("keyword") == "9803"

    def test_products_query_router_importerror_fallback_keyword(self) -> None:
        """route_normal_mode_message raises ImportError -> message used as
        keyword fallback (1698-1701)."""
        planner = _make_planner()
        reg = _registry_no_required("products", "query")
        candidate = _plan_with(_node("products", "query", {}))
        final = _plan_with(_node("products", "query", {}), intent="final")

        captured = {}

        def fake_exec(*, tool_id, action, params):
            captured["params"] = dict(params)
            return {"success": True, "data": [], "message": ""}

        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, final]),
            patch(
                "app.application.normal_chat_dispatch.route_normal_mode_message",
                side_effect=ImportError("router gone"),
            ),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                side_effect=fake_exec,
            ),
            patch("app.services.task_agent.TaskAgent", return_value=MagicMock()),
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="找一下灯具",
                tool_registry=reg,
                context={},
            )
        assert result is final
        assert captured["params"].get("keyword") == "找一下灯具"

    def test_customers_query_slot_backfill_via_task_agent(self) -> None:
        """customers.query with empty params + available TaskAgent triggers
        _extract_customer_query_slots backfill (1703-1713)."""
        planner = _make_planner()
        reg = _registry_no_required("customers", "query")
        candidate = _plan_with(_node("customers", "query", {}))
        final = _plan_with(_node("customers", "query", {}), intent="final")

        agent = MagicMock()
        agent._extract_customer_query_slots.return_value = {"customer_name": "七彩乐园"}

        captured = {}

        def fake_exec(*, tool_id, action, params):
            captured["params"] = dict(params)
            return {"success": True, "data": [{"id": 9}], "message": "hit"}

        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, final]),
            patch("app.services.task_agent.TaskAgent", return_value=agent),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                side_effect=fake_exec,
            ),
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="查客户七彩乐园",
                tool_registry=reg,
                context={},
            )
        assert result is final
        agent._extract_customer_query_slots.assert_called_once()
        assert captured["params"].get("customer_name") == "七彩乐园"

    def test_task_agent_runtime_error_init(self) -> None:
        """TaskAgent() raises RuntimeError during init -> task_agent stays None,
        probe still executed (1634-1636)."""
        planner = _make_planner()
        reg = _registry_no_required("products", "query")
        candidate = _plan_with(_node("products", "query", {"keyword": "k"}))
        final = _plan_with(_node("products", "query", {"keyword": "k"}), intent="final")

        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, final]),
            patch("app.services.task_agent.TaskAgent", side_effect=RuntimeError("init fail")),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                return_value={"success": True, "data": [{"id": 1}], "message": "ok"},
            ) as mock_exec,
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="查 k",
                tool_registry=reg,
                context={},
            )
        assert result is final
        mock_exec.assert_called_once()

    def test_probe_missing_required_param_skipped(self) -> None:
        """Node passes the act-filter but lacks a required_param -> skipped in the
        execution loop, no probe runs (1655-1667)."""
        planner = _make_planner()
        reg = {
            "products": {
                "description": "产品",
                "actions": {
                    "query": {
                        "risk": "low",
                        "idempotent": True,
                        "required_params": ["model_number"],
                    }
                },
            }
        }
        # candidate (probed) carries only keyword -> missing model_number, so the
        # probe is skipped; final carries model_number so it passes validation and
        # is returned directly (no critic repair / HTTP).
        candidate = _plan_with(_node("products", "query", {"keyword": "k"}))
        final = _plan_with(_node("products", "query", {"model_number": "9803"}), intent="final")
        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, final]),
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
            ) as mock_exec,
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="查 k",
                tool_registry=reg,
                context={},
            )
        assert result is final
        mock_exec.assert_not_called()

    def test_action_not_in_probe_allowlist_skipped(self) -> None:
        """A low-risk idempotent action that is not in the probe allow-list
        (e.g. 'create') is filtered out during extraction (1598-1610)."""
        planner = _make_planner()
        reg = {
            "products": {
                "description": "产品",
                "actions": {"create": {"risk": "low", "idempotent": True, "required_params": []}},
            }
        }
        candidate = _plan_with(_node("products", "create", {}))
        final = _plan_with(_node("products", "create", {}), intent="final")
        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, final]),
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
            ) as mock_exec,
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="新增产品",
                tool_registry=reg,
                context={},
            )
        assert result is final
        mock_exec.assert_not_called()

    def test_probe_execution_value_error_skipped(self) -> None:
        """execute_registered_workflow_tool raises ValueError -> probe skipped,
        no probe output injected, final plan still returned (1751-1753)."""
        planner = _make_planner()
        reg = _registry_no_required("products", "query")
        candidate = _plan_with(_node("products", "query", {"keyword": "k"}))
        final = _plan_with(_node("products", "query", {"keyword": "k"}), intent="final")
        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, final]) as mock_llm,
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                side_effect=ValueError("bad probe params"),
            ),
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="查 k",
                tool_registry=reg,
                context={},
            )
        assert result is final
        compose_ctx = mock_llm.call_args_list[1].kwargs["context"]
        assert "tool_probe_outputs" not in compose_ctx

    def test_probe_execution_runtime_error_skipped(self) -> None:
        """execute_registered_workflow_tool raises RuntimeError -> probe skipped
        via the RuntimeError handler (1754-1756)."""
        planner = _make_planner()
        reg = _registry_no_required("products", "query")
        candidate = _plan_with(_node("products", "query", {"keyword": "k"}))
        final = _plan_with(_node("products", "query", {"keyword": "k"}), intent="final")
        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, final]) as mock_llm,
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                side_effect=RuntimeError("probe boom"),
            ),
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="查 k",
                tool_registry=reg,
                context={},
            )
        assert result is final
        compose_ctx = mock_llm.call_args_list[1].kwargs["context"]
        assert "tool_probe_outputs" not in compose_ctx

    def test_probe_unsuccessful_output_not_injected(self) -> None:
        """Probe runs but returns success=False -> no probe output injected (the
        `if out.success is True` guard at 1739)."""
        planner = _make_planner()
        reg = _registry_no_required("products", "query")
        candidate = _plan_with(_node("products", "query", {"keyword": "k"}))
        final = _plan_with(_node("products", "query", {"keyword": "k"}), intent="final")
        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, final]) as mock_llm,
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                return_value={"success": False, "error": "denied"},
            ),
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="查 k",
                tool_registry=reg,
                context={},
            )
        assert result is final
        compose_ctx = mock_llm.call_args_list[1].kwargs["context"]
        assert "tool_probe_outputs" not in compose_ctx

    def test_react_repaired_plan_returned_when_validation_fails(self) -> None:
        """final plan fails validation, repair returns a valid plan -> repaired is
        returned (1781-1796). We patch _critic_repair_with_llm directly because the
        real method has a known AttributeError bug (see suspected_bugs)."""
        planner = _make_planner()
        reg = _registry_no_required("products", "query")
        candidate = _plan_with(_node("products", "query", {"keyword": "k"}))
        # final plan is invalid: dangling depends_on
        invalid_final = PlanGraph(
            plan_id="p",
            intent="bad",
            todo_steps=["x"],
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="products",
                    action="query",
                    params={"keyword": "k"},
                    risk="low",
                    idempotent=True,
                    depends_on=["ghost"],
                )
            ],
            risk_level="low",
        )
        good_repaired = _plan_with(_node("products", "query", {"keyword": "k"}), intent="repaired")
        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, invalid_final]),
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                return_value={"success": True, "data": [], "message": ""},
            ),
            patch.object(planner, "_critic_repair_with_llm", return_value=good_repaired),
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="查 k",
                tool_registry=reg,
                context={},
            )
        assert result is good_repaired

    def test_react_repair_returns_none_when_repair_invalid(self) -> None:
        """final invalid, repair also returns invalid plan -> overall None
        (1791-1799)."""
        planner = _make_planner()
        reg = _registry_no_required("products", "query")
        candidate = _plan_with(_node("products", "query", {"keyword": "k"}))
        invalid_final = PlanGraph(
            plan_id="p",
            intent="bad",
            todo_steps=["x"],
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="products",
                    action="query",
                    params={"keyword": "k"},
                    risk="low",
                    idempotent=True,
                    depends_on=["ghost"],
                )
            ],
            risk_level="low",
        )
        invalid_repaired = PlanGraph(
            plan_id="p",
            intent="still-bad",
            todo_steps=["x"],
            nodes=[
                WorkflowNode(
                    node_id="n1",
                    tool_id="products",
                    action="query",
                    params={"keyword": "k"},
                    risk="low",
                    idempotent=True,
                    depends_on=["ghost2"],
                )
            ],
            risk_level="low",
        )
        with (
            patch.object(planner, "_plan_with_llm", side_effect=[candidate, invalid_final]),
            patch("app.services.task_agent.TaskAgent", side_effect=ImportError),
            patch(
                "app.application.facades.tools_facade.execute_registered_workflow_tool",
                return_value={"success": True, "data": [], "message": ""},
            ),
            patch.object(planner, "_critic_repair_with_llm", return_value=invalid_repaired),
        ):
            result = planner._plan_with_react_multiagent(
                plan_id="p",
                user_id="u1",
                message="查 k",
                tool_registry=reg,
                context={},
            )
        assert result is None


# ---------------------------------------------------------------------------
# _critic_repair_with_llm — tool_specs build skip + RuntimeError handler
# ---------------------------------------------------------------------------


class TestCriticRepairToolSpecsAndErrors:
    def test_non_dict_action_meta_skipped_in_tool_specs(self) -> None:
        """A non-dict action_meta in the registry is skipped while building
        tool_specs (1848-1849). The request still fails downstream on the
        known _strip_json_code_fence bug, which we assert as the real behaviour."""
        planner = _make_planner()
        registry = {
            "products": {
                "description": "产品",
                "actions": {
                    "query": {"risk": "low", "idempotent": True, "required_params": []},
                    "broken": "not-a-dict",  # skipped at 1848-1849
                },
            }
        }
        invalid = PlanGraph(plan_id="p", intent="i", todo_steps=[], nodes=[])
        client = MagicMock()
        client.post.return_value = _llm_response(
            json.dumps({"intent": "r", "todo_steps": [], "risk_level": "low", "nodes": []})
        )
        with (
            patch(
                "app.application.workflow.planner._get_planner_http_client",
                return_value=client,
            ),
            pytest.raises(AttributeError, match="_strip_json_code_fence"),
        ):
            planner._critic_repair_with_llm("p", "u1", "msg", registry, {}, "err", invalid)
        # Confirm the non-dict action did not break prompt construction: the HTTP
        # call was reached (post invoked) before the bug surfaced.
        client.post.assert_called_once()

    def test_no_api_key_returns_none(self) -> None:
        """Empty api_key short-circuits to None (1838-1840)."""
        planner = _make_planner()
        planner._ai_service.api_key = ""
        invalid = PlanGraph(plan_id="p", intent="i", todo_steps=[], nodes=[])
        out = planner._critic_repair_with_llm(
            "p", "u1", "msg", _registry_no_required(), {}, "err", invalid
        )
        assert out is None

    def test_runtime_error_during_post_returns_none(self) -> None:
        """The HTTP client raising RuntimeError is caught by the RuntimeError
        handler (1986-1988)."""
        planner = _make_planner()
        invalid = PlanGraph(plan_id="p", intent="i", todo_steps=[], nodes=[])
        client = MagicMock()
        client.post.side_effect = RuntimeError("network down")
        with patch(
            "app.application.workflow.planner._get_planner_http_client",
            return_value=client,
        ):
            out = planner._critic_repair_with_llm(
                "p", "u1", "msg", _registry_no_required(), {}, "err", invalid
            )
        assert out is None


# ---------------------------------------------------------------------------
# _fallback_plan — employee-dispatch branch (2189-2232)
# ---------------------------------------------------------------------------


class TestFallbackEmployeeDispatch:
    def _registry(self):
        return {"employee": {"description": "员工", "actions": {}}}

    def test_employee_execute_when_pack_id_in_message(self) -> None:
        """build_employee_tools_status yields a pack whose id appears in the
        message -> an employee.execute node is built (2197-2220)."""
        planner = _make_planner()
        status = {
            "employee_pack_tools": [
                "not-a-dict",  # exercises the non-dict skip at 2201-2202
                {"pack_id": "emp-sales"},
            ]
        }
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value=status,
        ):
            plan = planner._fallback_plan("p", "把任务交给员工 emp-sales 处理", self._registry())
        assert plan.intent == "employee_dispatch"
        assert len(plan.nodes) == 1
        node = plan.nodes[0]
        assert node.tool_id == "employee"
        assert node.action == "execute"
        assert node.params["employee_id"] == "emp-sales"
        assert node.params["task"] == "把任务交给员工 emp-sales 处理"

    def test_employee_list_when_no_pack_match(self) -> None:
        """No pack id matches the message -> falls back to employee.list (2221-2232)."""
        planner = _make_planner()
        status = {"employee_pack_tools": [{"pack_id": "emp-finance"}]}
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            return_value=status,
        ):
            plan = planner._fallback_plan("p", "调用员工帮忙", self._registry())
        assert plan.intent == "employee_dispatch"
        assert len(plan.nodes) == 1
        assert plan.nodes[0].action == "list"

    def test_employee_status_importerror_falls_back_to_list(self) -> None:
        """build_employee_tools_status raises ImportError -> employee_id stays
        empty, employee.list node produced (2207-2208)."""
        planner = _make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            side_effect=ImportError("registry gone"),
        ):
            plan = planner._fallback_plan("p", "交给员工处理", self._registry())
        assert plan.intent == "employee_dispatch"
        assert plan.nodes[0].action == "list"

    def test_employee_status_runtime_error_falls_back_to_list(self) -> None:
        """build_employee_tools_status raises RuntimeError -> caught, list node."""
        planner = _make_planner()
        with patch(
            "app.mod_sdk.employee_tool_registry.build_employee_tools_status",
            side_effect=RuntimeError("boom"),
        ):
            plan = planner._fallback_plan("p", "调用员工", self._registry())
        assert plan.nodes[0].action == "list"
