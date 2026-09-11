"""规划层原始 SQL 拒绝闸 + 兜底路由去静默化回归（2026-09-05 审计：AI 意图与工具路由 46/100）。

覆盖两个根因修复：
1. 原始 SQL 不进入写规划：规划入口主闸由 sql_execution_policy（#1815）承担
   （显式执行语境直接拒绝）；本文件覆盖写路径双保险
   （looks_like_raw_sql → business_db_write 短路 + _extract_business_db_write_node 拒写）
   与裸 SQL 的 clarify 兜底行为。
2. 废除「未匹配一律 products.query」的静默默认路由，改为规则意图服务两级路由 + clarify 兜底。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.services.conversation.chat_tool_intent import (
    looks_like_business_db_write,
    looks_like_raw_sql,
)

RAW_SQL_POSITIVES = [
    "执行 DELETE FROM customers 清空客户表",
    "帮我在数据库里执行 DELETE FROM customers 清空客户表",
    "SELECT * FROM users",
    "DROP TABLE orders",
    "update customers set name=x where 1=1",
    "TRUNCATE TABLE products",
    "insert into customers (unit_name) values ('测试')",
    "执行　DELETE　FROM　customers",  # 全角空格
    "DELETE  FROM  customers",  # 多个半角空格
]

BUSINESS_NEGATIVES = [
    "删除客户张三",
    "把库存改成 50",
    "新增产品螺丝",
    "查询客户列表",
    "从数据库读取客户信息",
    "修改产品 A100 的单价",
]


# ---------------------------------------------------------------------------
# 任务 A：looks_like_raw_sql / looks_like_business_db_write 拒绝闸
# ---------------------------------------------------------------------------


class TestLooksLikeRawSql:
    @pytest.mark.parametrize("text", RAW_SQL_POSITIVES)
    def test_positive_forms(self, text: str) -> None:
        assert looks_like_raw_sql(text) is True

    @pytest.mark.parametrize("text", BUSINESS_NEGATIVES)
    def test_business_phrases_not_flagged(self, text: str) -> None:
        assert looks_like_raw_sql(text) is False

    def test_empty_and_none_safe(self) -> None:
        assert looks_like_raw_sql("") is False
        assert looks_like_raw_sql(None) is False  # type: ignore[arg-type]

    @pytest.mark.parametrize("text", RAW_SQL_POSITIVES)
    def test_sql_never_enters_write_planning(self, text: str) -> None:
        assert looks_like_business_db_write(text) is False


# ---------------------------------------------------------------------------
# planner 层：_extract_business_db_write_node 双保险
# ---------------------------------------------------------------------------


class TestExtractWriteNodeDefense:
    @pytest.mark.parametrize(
        "text",
        [
            "执行 DELETE FROM customers 清空客户表",
            "update customers set name=x where 1=1",
            "DROP TABLE orders",
        ],
    )
    def test_raw_sql_returns_none(self, text: str) -> None:
        from app.application.workflow.planner import _extract_business_db_write_node

        assert _extract_business_db_write_node(text) is None

    def test_normal_write_still_produced(self) -> None:
        from app.application.workflow.planner import _extract_business_db_write_node

        node = _extract_business_db_write_node("请把客户 星光贸易 写入数据库")
        assert node is not None
        assert (node.tool_id, node.action) == ("business_db", "write")


# ---------------------------------------------------------------------------
# plan() 级：拒绝闸与默认路由
# ---------------------------------------------------------------------------


def _make_planner() -> MagicMock:
    from app.application.workflow.planner import LLMWorkflowPlanner

    with patch("app.application.workflow.planner.get_ai_conversation_service") as mock_svc:
        ai = MagicMock()
        ai.api_key = ""
        ai.get_context.return_value = None
        mock_svc.return_value = ai
        planner = LLMWorkflowPlanner()
    return planner


def _full_registry() -> dict:
    from app.application.workflow.planner import get_tool_registry

    return get_tool_registry()


def _plan_offline(planner: MagicMock, message: str) -> MagicMock:
    with (
        patch.object(planner, "_plan_with_react_multiagent", return_value=None),
        patch(
            "app.application.normal_chat_dispatch.resolve_tool_execution_profile",
            return_value="full",
        ),
        patch("app.application.get_user_memory_rag_app_service", side_effect=ImportError),
    ):
        return planner.plan("test-user", message, _full_registry(), {})


class TestPlanRejectsRawSql:
    @pytest.mark.parametrize(
        "message",
        [
            "帮我在数据库里执行 DELETE FROM customers 清空客户表",
            "执行 DELETE FROM customers 清空客户表",
            "SELECT * FROM users",
            "update customers set name=x where 1=1",
        ],
    )
    def test_no_business_db_write_node(self, message: str) -> None:
        planner = _make_planner()
        plan = _plan_offline(planner, message)
        assert not any(n.tool_id == "business_db" and n.action == "write" for n in plan.nodes), (
            plan.nodes
        )
        assert not any(n.tool_id == "customers" and n.action == "delete" for n in plan.nodes)

    def test_explicit_sql_execution_rejected_by_policy_gate(self) -> None:
        # 显式要求执行 SQL：规划入口主闸（#1815 sql_execution_policy）直接拒绝（无节点计划）。
        planner = _make_planner()
        plan = _plan_offline(planner, "帮我在数据库里执行 DELETE FROM customers 清空客户表")
        assert plan.intent == "rejected_sql_execution"
        assert plan.nodes == []
        assert plan.metadata.get("refusal_code") == "raw_sql_execution_not_supported"

    def test_bare_sql_falls_to_clarify_without_write_plan(self) -> None:
        # 裸 SQL 形态（无执行语境）：主闸不拒（不误伤 SQL 讨论），两级兜底路由 → clarify。
        planner = _make_planner()
        plan = _plan_offline(planner, "SELECT * FROM users")
        assert not any(n.tool_id == "business_db" and n.action == "write" for n in plan.nodes)
        assert plan.nodes and all(n.tool_id == "clarify" for n in plan.nodes)


class TestPlanDefaultRoutingNoSilentProducts:
    def test_customer_list_routes_to_customers(self) -> None:
        planner = _make_planner()
        plan = _plan_offline(planner, "客户列表")
        assert not any(n.tool_id == "products" for n in plan.nodes), plan.nodes
        assert any(n.tool_id == "customers" and n.action == "query" for n in plan.nodes)

    def test_weather_message_clarifies(self) -> None:
        planner = _make_planner()
        plan = _plan_offline(planner, "今天天气怎么样")
        assert not any(n.tool_id == "products" for n in plan.nodes), plan.nodes
        assert plan.nodes and all(n.tool_id == "clarify" for n in plan.nodes)
        assert plan.nodes[0].action == "ask"


class TestFallbackPlanTwoLevelRouting:
    def _fallback(self, message: str, registry: dict | None = None):
        planner = _make_planner()
        return planner._fallback_plan("pid", message, registry or _full_registry())

    def test_customers_intent(self) -> None:
        plan = self._fallback("查一下客户 星光贸易 的信息")
        assert any(n.tool_id == "customers" and n.action == "query" for n in plan.nodes)
        assert not any(n.tool_id == "products" for n in plan.nodes)

    def test_materials_intent(self) -> None:
        plan = self._fallback("查库存5003")
        assert any(n.tool_id == "materials" and n.action == "query" for n in plan.nodes)

    def test_unmatched_clarifies(self) -> None:
        plan = self._fallback("今天天气怎么样")
        assert plan.intent == "clarify_ask"
        assert [n.tool_id for n in plan.nodes] == ["clarify"]

    def test_intent_service_failure_falls_to_clarify(self) -> None:
        planner = _make_planner()
        with patch(
            "app.services.intent_service.recognize_intents",
            side_effect=RuntimeError("boom"),
        ):
            plan = planner._fallback_plan("pid", "随便看看", _full_registry())
        assert plan.intent == "clarify_ask"
        assert not any(n.tool_id == "products" for n in plan.nodes)

    def test_negated_message_not_routed(self) -> None:
        planner = _make_planner()
        with patch(
            "app.services.intent_service.recognize_intents",
            return_value={"tool_key": "customers", "is_negated": True},
        ):
            plan = planner._fallback_plan("pid", "不要查客户", _full_registry())
        assert plan.intent == "clarify_ask"

    def test_mapped_tool_missing_from_registry_clarifies(self) -> None:
        plan = self._fallback("客户列表", registry={"products": _full_registry()["products"]})
        assert plan.intent == "clarify_ask"
        assert not any(n.tool_id == "products" for n in plan.nodes)
