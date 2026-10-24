from __future__ import annotations

"""Branch-coverage tests for app/application/workflow/planner.py."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.application.workflow.planner import (
    LLMWorkflowPlanner,
    _clean_db_slot_value,
    _extract_business_db_read_keyword,
    _extract_business_db_write_node,
    _extract_named_slot,
    _filter_tool_registry_for_profile,
    _infer_business_db_entity,
    _looks_like_business_db_write,
)
from app.application.workflow.risk_gate import HybridRiskGate
from app.application.workflow.types import PlanGraph, WorkflowNode, validate_plan_graph

_SAMPLE_REGISTRY: dict[str, Any] = {
    name: {
        "description": desc,
        "availability": "shared",
        "actions": {
            action: {
                "description": action_desc,
                "risk": "low" if action in {"query", "read", "list"} else "medium",
                "idempotent": action not in {"create", "write", "execute"},
                "availability": "shared",
                "required_params": required,
            }
            for action, (action_desc, required) in actions.items()
        },
    }
    for name, (desc, actions) in {
        "products": ("产品查询", {"query": ("查询产品", ["keyword"]), "create": ("创建产品", [])}),
        "customers": (
            "客户查询",
            {"query": ("查询客户", []), "ensure_exists": ("确保客户存在", [])},
        ),
        "business_db": ("业务数据库", {"read": ("读取", ["entity"]), "write": ("写入", [])}),
        "employee": (
            "员工执行",
            {"list": ("列出员工", []), "execute": ("执行员工任务", ["employee_id"])},
        ),
    }.items()
}


def _make_plan(nodes: list[WorkflowNode] | None = None) -> PlanGraph:
    return PlanGraph(
        "test-plan",
        "test_intent",
        todo_steps=["step1"],
        nodes=nodes
        or [
            WorkflowNode(
                "n1", "products", "query", params={"keyword": "abc"}, risk="low", idempotent=True
            )
        ],
    )


class TestCleanDbSlotValue:
    def test_strips_whitespace_and_punctuation(self) -> None:
        result = _clean_db_slot_value("  ,测试,。 ")
        assert "," not in result
        assert result.strip() == result

    def test_removes_db_keywords(self) -> None:
        assert "数据库" not in _clean_db_slot_value("产品加入数据库")

    def test_removes_leading_entity_prefixes(self) -> None:
        result = _clean_db_slot_value("新增ABC")
        assert "新增" not in result

    def test_empty_string(self) -> None:
        assert _clean_db_slot_value("") == ""

    def test_none_input(self) -> None:
        assert _clean_db_slot_value(None) == ""  # type: ignore[arg-type]


class TestExtractNamedSlot:
    def test_pattern_match_returns_value(self) -> None:
        msg = "客户：ABC公司"
        result = _extract_named_slot(msg, (r"客户[：:]\s*([^\s，,。；;]+)",))
        assert result == "ABC公司"

    def test_quoted_fallback(self) -> None:
        msg = '请查询"上海科技"的产品'
        result = _extract_named_slot(msg, (r"无法匹配的模式(.+)",))
        assert "上海科技" in result

    def test_no_match_returns_empty(self) -> None:
        msg = "没有任何匹配"
        result = _extract_named_slot(msg, (r"ZZZ(.+)",))
        assert result == ""


class TestInferBusinessDbEntity:
    @pytest.mark.parametrize(
        "messages,entity",
        [
            (("查询产品库存", "查询商品"), "products"),
            (("客户ABC", "购买单位X"), "customers"),
            (("原材料钢板", "物料库存"), "materials"),
            (("出货记录", "发货单"), "shipment_records"),
            (("随机文字",), "products"),
        ],
    )
    def test_entity_keywords(self, messages, entity):
        for message in messages:
            assert _infer_business_db_entity(message) == entity


class TestLooksLikeBusinessDbWrite:
    @pytest.mark.parametrize(
        "message,writes",
        [
            ("新增产品到数据库", True),
            ("add product to db", True),
            ("查询产品", False),
            ("新增一条消息", False),
        ],
    )
    def test_write_keywords(self, message, writes):
        assert _looks_like_business_db_write(message, message) is writes


class TestExtractBusinessDbWriteNode:
    def test_product_missing_product_name_returns_none(self) -> None:
        result = _extract_business_db_write_node("产品写入数据库")
        assert result is None

    def test_materials_entity_returns_create_node(self) -> None:
        result = _extract_business_db_write_node("原材料钢板入库数据库写入")
        assert result is not None
        assert result.tool_id == "business_db"
        assert result.params["entity"] == "materials"
        assert result.params["operation"] == "create"


class TestExtractBusinessDbReadKeyword:
    @pytest.mark.parametrize(
        "message,entity,kind",
        [
            ('查询"ABC123"', "products", "quoted"),
            ("查询产品ABC123", "products", "present"),
            ("查询客户ABC公司", "customers", "present"),
            ("查询原材料钢板", "materials", "present"),
            ("查询数据库里的东西", "unknown_entity", "string"),
            ("查ABC99X的价格", "products", "present"),
        ],
    )
    def test_keyword_cases(self, message, entity, kind):
        result = _extract_business_db_read_keyword(message, entity)
        if kind == "quoted":
            assert "ABC123" in result
        elif kind == "string":
            assert isinstance(result, str)
        else:
            assert result


class TestFilterToolRegistryForProfile:
    def _registry(self) -> dict[str, Any]:
        def spec(availability, actions):
            return {
                "availability": availability,
                "actions": {
                    name: {"availability": scope, "risk": "low", "idempotent": True}
                    for name, scope in actions.items()
                },
            }

        return {
            "tool_shared": spec("shared", {"act_shared": "shared"}),
            "tool_pro_only": spec("pro_only", {"act": "pro_only"}),
            "tool_normal_only": spec("normal_only", {"act": "normal_only"}),
            "tool_mixed": spec(
                "shared",
                {"pro_act": "pro_only", "normal_act": "normal_only", "shared_act": "shared"},
            ),
        }

    @pytest.mark.parametrize(
        "profile,key,present",
        [
            ("normal", "tool_pro_only", False),
            ("normal", "tool_normal_only", True),
            ("pro_default", "tool_normal_only", False),
            ("pro_default", "tool_pro_only", True),
            ("other", "tool_shared", True),
        ],
    )
    def test_profile_scope_cases(self, profile, key, present):
        assert (key in _filter_tool_registry_for_profile(self._registry(), profile)) == present

    def test_mixed_tool_normal_profile_keeps_shared_and_normal_actions(self) -> None:
        filtered = _filter_tool_registry_for_profile(self._registry(), "normal")
        actions = filtered.get("tool_mixed", {}).get("actions", {})
        assert "shared_act" in actions
        assert "normal_act" in actions
        assert "pro_act" not in actions

    def test_non_dict_spec_skipped(self) -> None:
        reg = {"bad_tool": "not_a_dict"}
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "bad_tool" not in filtered

    def test_tool_with_no_remaining_actions_excluded(self) -> None:
        reg = {
            "pro_only_tool": {
                "availability": "shared",
                "actions": {
                    "pro_act": {"availability": "pro_only", "risk": "low", "idempotent": True},
                },
            }
        }
        filtered = _filter_tool_registry_for_profile(reg, "normal")
        assert "pro_only_tool" not in filtered


class TestValidatePlanGraph:
    def test_valid_plan_returns_none(self):
        assert validate_plan_graph(_make_plan()) is None

    @pytest.mark.parametrize(
        "invalid",
        [
            "nodes",
            "plan_id",
            "intent",
            "duplicate_node_ids",
            "tool_id",
            "action",
            "dependency",
            "self_dependency",
        ],
    )
    def test_invalid_plan_cases(self, invalid):
        plan = _make_plan()
        if invalid in {"nodes", "plan_id", "intent"}:
            setattr(plan, invalid, [] if invalid == "nodes" else "")
        elif invalid == "duplicate_node_ids":
            plan.nodes.append(WorkflowNode(plan.nodes[0].node_id, "t", "b"))
        elif invalid in {"tool_id", "action"}:
            setattr(plan.nodes[0], invalid, "")
        else:
            plan.nodes[0].depends_on = [
                plan.nodes[0].node_id if invalid == "self_dependency" else "nonexistent"
            ]
        assert validate_plan_graph(plan) is not None

    def test_duplicate_restore_is_invalid_before_approval(self):
        nodes = [
            WorkflowNode(
                "approval",
                "system_maintenance",
                "restore_database",
                params={"backup_file": "xcagi.db.20261011_160815.bak", "require_approval": True},
            ),
            WorkflowNode(
                "restore",
                "system_maintenance",
                "restore_database",
                params={
                    "backup_file": "xcagi.db.20261011_160815.bak",
                    "execute_after_approval": True,
                },
                depends_on=["approval"],
            ),
        ]
        assert "一个 restore_database" in validate_plan_graph(_make_plan(nodes))

        with pytest.raises(ValueError, match="一个 restore_database"):
            HybridRiskGate().evaluate(_make_plan(nodes), context={})


class TestValidateRequiredParams:
    @pytest.mark.parametrize(
        "params,registered,error",
        [
            ({"keyword": "abc"}, True, False),
            ({}, True, True),
            ({"keyword": ""}, True, True),
            ({}, False, False),
            ({"keyword": None}, True, True),
        ],
        ids=[
            "all_params_present",
            "missing_required_param",
            "empty_string",
            "unregistered_tool",
            "none_param",
        ],
    )
    def test_required_params(self, params, registered, error):

        registry = (
            {"products": {"actions": {"query": {"required_params": ["keyword"]}}}}
            if registered
            else {}
        )
        result = LLMWorkflowPlanner._validate_required_params(
            _make_plan(
                [
                    WorkflowNode(
                        "n1", "products" if registered else "unknown_tool", "query", params=params
                    )
                ]
            ),
            registry,
        )
        assert (result is not None) == error
        if params == {} and registered:
            assert "keyword" in result


@pytest.mark.parametrize(
    "message",
    [
        "恢复数据库，使用备份文件 xcagi.db.20261011_160815.bak。先提交手动审批，未经批准不要执行恢复。",
        "请只恢复一次数据库，使用已有备份文件xcagi.db.20261011_160815.bak。恢复只允许执行一次，不要把提交审批和执行恢复拆成两次恢复操作。使用手动审批，先创建一张真实审批申请，批准后再恢复。",
        "请恢复数据库 xcagi.db.20261011_160815.bak，如果失败请提示原因",
        "请恢复数据库 xcagi.db.20261011_160815.bak 如果失败请提示原因",
        "请帮我恢复数据库 xcagi.db.20261011_160815.bak",
        "请你恢复数据库 xcagi.db.20261011_160815.bak",
        "现在恢复数据库 xcagi.db.20261011_160815.bak",
        "麻烦你先恢复数据库 xcagi.db.20261011_160815.bak",
        "请备份数据库。执行前先给我确认，需要审批的操作提交审批。",
        "备份数据库，不恢复",
        "请现在创建一次本机数据库备份，用于本次自动审批实测。只创建备份，不恢复、不删除、不修改业务数据。",
        "帮我生成一份本地数据库备份，执行前先给我确认。",
        "备份当前数据库。先展示计划，等待我确认后再执行。",
    ],
)
@pytest.mark.parametrize("entry", ["plan", "_fallback_plan"])
def test_actual_restore_requests_use_one_registered_high_risk_step(message, entry):
    from app.application.normal_chat_dispatch import route_normal_mode_message

    assert route_normal_mode_message(message)["intent"] == "workflow"
    registry = {
        "system_maintenance": {"actions": {"restore_database": {}, "backup_database": {}}},
        **_SAMPLE_REGISTRY,
    }
    planner = LLMWorkflowPlanner.__new__(LLMWorkflowPlanner)
    with patch.object(
        planner,
        "_plan_with_llm",
        side_effect=AssertionError("Explicit restore must not become a second LLM business write"),
    ):
        plan = getattr(planner, entry)(
            *(["actor", message, registry, {}] if entry == "plan" else ["p", message, registry])
        )
    assert len(plan.nodes) == 1 and validate_plan_graph(plan) is None
    node = plan.nodes[0]
    backup = "备份数据库" in message or "数据库备份" in message or "备份当前数据库" in message
    assert (node.tool_id, node.action) == (
        "system_maintenance",
        "backup_database" if backup else "restore_database",
    )
    assert node.params == ({} if backup else {"backup_file": "xcagi.db.20261011_160815.bak"})
    assert (node.risk, node.idempotent) == ("medium" if backup else "high", False)
    assert HybridRiskGate().evaluate(plan, context={}).requires_confirmation


@pytest.mark.parametrize(
    "message",
    [
        "如何恢复数据库",
        "不要备份数据库",
        "请不要创建一次本机数据库备份",
        "创建一次本机数据库备份应该怎么操作",
        "备份数据库失败，帮我排查",
        "不要恢复数据库",
        "不恢复数据库",
        "只查看恢复数据库的方法",
        "不要再恢复数据库，备份为 xcagi.db.20261011_160815.bak",
        "恢复数据库 xcagi.db.20261011_160815.bak 失败，帮我排查原因",
        "请排查恢复数据库 xcagi.db.20261011_160815.bak 失败的原因",
        "恢复数据库 xcagi.db.20261011_160815.bak 应该怎么操作",
        "请你先不要再恢复数据库，备份为 xcagi.db.20261011_160815.bak",
        "现在恢复数据库 xcagi.db.20261011_160815.bak 可以吗",
        "恢复数据库 test.bak 卡住了，请帮我排查",
        "恢复数据库 test.bak 发生异常，请只排查日志",
        "恢复数据库 test.bak 是什么意思",
    ],
)
def test_restore_does_not_turn_questions_negations_or_backup_into_write(message):
    from app.application.workflow.sql_execution_policy import database_maintenance_plan

    assert database_maintenance_plan(message, "p", {}) is None


@pytest.mark.parametrize(
    "message,registry",
    [
        ("恢复数据库", {"system_maintenance": {"actions": {"restore_database": {}}}}),
        (
            "恢复数据库，如果失败请分析 test.bak 日志",
            {"system_maintenance": {"actions": {"restore_database": {}}}},
        ),
        ("恢复数据库，使用xcagi.db.20261011_160815.bak", {}),
        ("请备份数据库", {}),
    ],
)
def test_restore_missing_file_or_entitlement_clarifies_without_business_write(message, registry):
    from app.application.workflow.sql_execution_policy import database_maintenance_plan

    plan = database_maintenance_plan(message, "p", registry)
    assert [(n.tool_id, n.action, n.risk) for n in plan.nodes] == [("clarify", "ask", "low")]


class _PlannerFixture:
    api_key = api_url = model = ""

    def _make_planner(self):
        ai = MagicMock(api_key=self.api_key, api_url=self.api_url, model=self.model)
        ai.get_context.return_value = None
        with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=ai):
            return LLMWorkflowPlanner()


class TestFallbackPlan(_PlannerFixture):
    def test_fallback_employee_intent_with_unknown_id(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "请员工处理订单", _SAMPLE_REGISTRY)
        assert result.intent == "employee_dispatch"
        assert any(n.action == "list" for n in result.nodes)

    def test_fallback_business_db_write(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "新增客户ABC公司到数据库写入", _SAMPLE_REGISTRY)
        assert result is not None
        assert result.plan_id == "pid"

    def test_fallback_business_db_read(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "查询数据库里的产品", _SAMPLE_REGISTRY)
        assert result is not None
        assert any(n.tool_id == "business_db" for n in result.nodes) or any(
            n.tool_id == "products" for n in result.nodes
        )

    def test_fallback_add_product_to_unit(self) -> None:
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "添加新产品到客户单位", _SAMPLE_REGISTRY)
        assert result.intent == "add_product_to_unit"

    def test_fallback_default_query_products(self) -> None:
        # 2026-09 起未命中意图不再静默 products.query，而是 clarify.ask。
        planner = self._make_planner()
        result = planner._fallback_plan("pid", "帮我看看", _SAMPLE_REGISTRY)
        assert result.intent == "clarify_ask"
        assert any(n.tool_id == "clarify" for n in result.nodes)

    def test_fallback_no_products_falls_to_customers(self) -> None:
        # 命中 customers 意图时按 tool_key 路由到 customers.query；未命中走 clarify。
        planner = self._make_planner()
        reg = {
            "customers": {
                "description": "c",
                "availability": "shared",
                "actions": {
                    "query": {
                        "risk": "low",
                        "idempotent": True,
                        "availability": "shared",
                        "required_params": [],
                    }
                },
            }
        }
        result = planner._fallback_plan("pid", "客户列表", reg)
        assert any(n.tool_id == "customers" for n in result.nodes)

    def test_fallback_risk_level_high_when_node_is_high(self) -> None:
        planner = self._make_planner()
        high_node = WorkflowNode("n", "t", "a", risk="high")
        with patch(
            "app.application.workflow.planner._extract_business_db_write_node",
            return_value=high_node,
        ):
            with patch(
                "app.application.workflow.planner._looks_like_business_db_write",
                return_value=True,
            ):
                result = planner._fallback_plan("pid", "写入数据库", _SAMPLE_REGISTRY)
        assert result.risk_level == "high"

    def test_fallback_risk_level_medium(self) -> None:
        planner = self._make_planner()
        medium_node = WorkflowNode("n", "t", "a", risk="medium")
        with patch(
            "app.application.workflow.planner._extract_business_db_write_node",
            return_value=medium_node,
        ):
            with patch(
                "app.application.workflow.planner._looks_like_business_db_write",
                return_value=True,
            ):
                result = planner._fallback_plan("pid", "写入数据库", _SAMPLE_REGISTRY)
        assert result.risk_level == "medium"


class TestPlanWithLLM(_PlannerFixture):
    api_key = "test-key"
    api_url = "https://api.example.com/v1/chat/completions"
    model = "deepseek-chat"

    def _mock_response(self, payload: dict[str, Any]) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": json.dumps(payload)}}]}
        return resp

    def _run_planner(self, planner, response, message="test", context=None):
        with patch(
            "app.application.workflow.planner.request_planner_completion",
            return_value=response.json() if response.status_code < 400 else None,
        ) as completion:
            result = planner._plan_with_llm(
                plan_id="pid",
                user_id="u1",
                message=message,
                tool_registry=_SAMPLE_REGISTRY,
                context=context or {},
            )
            completion.assert_called_once()
            return result

    def test_returns_none_when_no_api_key(self) -> None:
        planner = self._make_planner()
        planner._ai_service.api_key = planner._ai_service.api_url = planner._ai_service.model = ""

        result = planner._plan_with_llm(
            plan_id="pid",
            user_id="u1",
            message="test",
            tool_registry=_SAMPLE_REGISTRY,
            context={},
        )
        assert result is None

    @pytest.mark.parametrize("status", [500, 200], ids=["http_error", "empty_content"])
    def test_returns_none_for_failed_or_empty_response(self, status):
        planner = self._make_planner()
        response = self._mock_response({})
        response.status_code = status
        response.json.return_value = {"choices": [{"message": {"content": ""}}]}
        assert self._run_planner(planner, response) is None

    def test_successful_parse_returns_plan_graph(self) -> None:
        planner = self._make_planner()
        payload = {
            "intent": "query_products",
            "todo_steps": ["查询产品"],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "ABC"},
                    "risk": "low",
                    "idempotent": True,
                    "description": "查询产品",
                    "depends_on": [],
                }
            ],
        }
        resp = self._mock_response(payload)

        result = self._run_planner(planner, resp, "查询产品ABC", {})
        assert result is not None
        assert result.intent == "query_products"
        assert len(result.nodes) == 1

    def test_json_parse_error_returns_none(self) -> None:
        planner = self._make_planner()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"choices": [{"message": {"content": "NOT JSON"}}]}

        result = self._run_planner(planner, resp, "test", {})
        assert result is None

    def test_context_with_tool_probe_outputs_and_memory(self) -> None:
        planner = self._make_planner()
        payload = {
            "intent": "query_products",
            "todo_steps": [],
            "risk_level": "low",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": "products",
                    "action": "query",
                    "params": {"keyword": "X"},
                    "risk": "low",
                    "idempotent": True,
                    "description": "q",
                    "depends_on": [],
                }
            ],
        }
        resp = self._mock_response(payload)
        context = {
            "tool_probe_outputs": [
                {
                    "tool_id": "products",
                    "action": "query",
                    "success": True,
                    "message": "ok",
                    "data_preview": "[{...}]",
                }
            ],
            "user_memory_rag": {"summary": "用户偏好：ABC产品"},
            "memory_v2": {"summary": "已确认 active 记忆：ABC"},
        }

        result = self._run_planner(planner, resp, "查产品", context)
        assert result is not None
        assert result.metadata.get("user_memory_rag_summary") == "用户偏好：ABC产品"


class TestPlanMethod(_PlannerFixture):
    def test_plan_falls_back_to_rules_when_llm_unavailable(self) -> None:
        planner = self._make_planner()

        with (
            patch(
                "app.application.workflow.planner.resolve_tool_execution_profile",
                return_value="normal",
                create=True,
            ),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
                create=True,
            ),
        ):
            result = planner.plan(
                user_id="u1",
                message="帮我查产品",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        assert result is not None
        assert result.plan_id

    def test_plan_with_memory_import_error_swallowed(self) -> None:
        """ImportError from memory services should not propagate."""
        planner = self._make_planner()

        with (
            patch(
                "app.application.workflow.planner.resolve_tool_execution_profile",
                return_value="normal",
                create=True,
            ),
            patch(
                "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
                return_value="normal",
                create=True,
            ),
            patch(
                "app.application.workflow.planner.get_user_memory_rag_app_service",
                side_effect=ImportError("no rag"),
                create=True,
            ),
        ):
            result = planner.plan(
                user_id="u1",
                message="测试",
                tool_registry=_SAMPLE_REGISTRY,
                context={},
            )
        assert result is not None
