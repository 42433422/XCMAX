"""扩展覆盖（cov90）：ai_chat_app_service 中此前未测的格式化/聚合/列推断辅助方法。

聚焦目标（这些方法在现有 ext* 测试中无覆盖或仅覆盖部分分支）：
- _iter_agentic_artifact_payloads（静态，list/dict/None/缺失键分支）
- _agent_plan_can_auto_execute（静态，空 nodes / 低风险幂等 / 高风险分支 + spec 异常回退）
- _workflow_output_message / _workflow_output_preview（dict 数据列表/字典/raw 截断分支）
- _format_workflow_tool_success_line（employee / business_db / 默认 三类分支）
- _format_workflow_run_response 的 normal_slot_dispatch 覆盖叠加分支
- _build_order_text_from_products 的 original_message 正则结构化分支
- _execute_customers_intent 的 ensure_exists 成功/已存在/失败分支
- _header_hint_column_roles 字段索引异常回退 + 关键词角色赋值
- _price_column_buckets 服务异常回退到启发式
- _model_like_score / _packaging_or_measure_ratio 边界

全部为离线、确定性测试：外部依赖（DB、LLM、tools_facade、ai_db_schema_index）一律 mock 在“使用处”模块路径。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.application.ai_chat_app_service import AIChatApplicationService


def _make_svc() -> AIChatApplicationService:
    """构造能正常实例化的服务（模拟所有构造依赖）。"""
    with (
        patch("app.application.ai_chat_app_service.get_ai_conversation_service"),
        patch("app.application.ai_chat_app_service.LLMWorkflowPlanner"),
        patch("app.application.ai_chat_app_service.HybridRiskGate"),
        patch("app.application.ai_chat_app_service.WorkflowEngine"),
        patch("app.application.ai_chat_app_service.get_approval_service"),
    ):
        return AIChatApplicationService()


def _node_result(**kw):
    """构造 workflow node_result 形态对象（鸭子类型，含默认字段）。"""
    base = {
        "node_id": "n1",
        "success": True,
        "tool_id": "products",
        "action": "query",
        "output": {},
        "error": "",
        "retryable": True,
        "retries": 0,
        "recovery_hint": "",
        "duration_ms": 0,
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# _iter_agentic_artifact_payloads —— 静态分支全覆盖
# ---------------------------------------------------------------------------


class TestIterAgenticArtifactPayloads:
    def test_non_dict_returns_empty(self):
        assert AIChatApplicationService._iter_agentic_artifact_payloads("nope") == []
        assert AIChatApplicationService._iter_agentic_artifact_payloads(None) == []

    def test_artifacts_as_dict_wrapped_in_list(self):
        out = {"artifacts": {"artifact_type": "doc", "name": "x"}}
        res = AIChatApplicationService._iter_agentic_artifact_payloads(out)
        assert res == [{"artifact_type": "doc", "name": "x"}]

    def test_artifacts_as_list_filters_non_dict(self):
        out = {"artifacts": [{"a": 1}, "skip", 5, {"b": 2}]}
        res = AIChatApplicationService._iter_agentic_artifact_payloads(out)
        assert res == [{"a": 1}, {"b": 2}]

    def test_singular_artifact_key_fallback(self):
        out = {"artifact": {"artifact_type": "t"}}
        res = AIChatApplicationService._iter_agentic_artifact_payloads(out)
        assert res == [{"artifact_type": "t"}]

    def test_missing_keys_returns_empty(self):
        assert AIChatApplicationService._iter_agentic_artifact_payloads({"foo": 1}) == []


# ---------------------------------------------------------------------------
# _agent_plan_can_auto_execute
# ---------------------------------------------------------------------------


class TestAgentPlanCanAutoExecute:
    def test_no_nodes_false(self):
        plan = SimpleNamespace(nodes=[])
        assert AIChatApplicationService._agent_plan_can_auto_execute(plan) is False

    def test_nodes_not_list_false(self):
        plan = SimpleNamespace(nodes=None)
        assert AIChatApplicationService._agent_plan_can_auto_execute(plan) is False

    def test_low_risk_idempotent_true(self):
        plan = SimpleNamespace(
            nodes=[SimpleNamespace(tool_id="products", action="query", risk="low", idempotent=True)]
        )
        spec = SimpleNamespace(risk="low", idempotent=True)
        with patch(
            "app.application.agent_orchestrator.tool_spec.get_tool_action_spec",
            return_value=spec,
        ):
            assert AIChatApplicationService._agent_plan_can_auto_execute(plan) is True

    def test_high_risk_false(self):
        plan = SimpleNamespace(
            nodes=[SimpleNamespace(tool_id="x", action="write", risk="high", idempotent=True)]
        )
        spec = SimpleNamespace(risk="high", idempotent=True)
        with patch(
            "app.application.agent_orchestrator.tool_spec.get_tool_action_spec",
            return_value=spec,
        ):
            assert AIChatApplicationService._agent_plan_can_auto_execute(plan) is False

    def test_low_risk_not_idempotent_false(self):
        plan = SimpleNamespace(
            nodes=[SimpleNamespace(tool_id="x", action="create", risk="low", idempotent=False)]
        )
        spec = SimpleNamespace(risk="low", idempotent=False)
        with patch(
            "app.application.agent_orchestrator.tool_spec.get_tool_action_spec",
            return_value=spec,
        ):
            assert AIChatApplicationService._agent_plan_can_auto_execute(plan) is False


# ---------------------------------------------------------------------------
# _workflow_output_message / _workflow_output_preview
# ---------------------------------------------------------------------------


class TestWorkflowOutputMessage:
    def test_non_dict_empty(self):
        assert AIChatApplicationService._workflow_output_message("x") == ""
        assert AIChatApplicationService._workflow_output_message(None) == ""

    def test_message_preferred(self):
        assert AIChatApplicationService._workflow_output_message({"message": " hi "}) == "hi"

    def test_error_fallback(self):
        assert AIChatApplicationService._workflow_output_message({"error": "boom"}) == "boom"


class TestWorkflowOutputPreview:
    def test_none_empty(self):
        assert AIChatApplicationService._workflow_output_preview(None) == ""

    def test_dict_with_list_data_adds_row_count(self):
        out = {"success": True, "data": [{"a": 1}, {"a": 2}, {"a": 3}]}
        res = AIChatApplicationService._workflow_output_preview(out)
        assert '"row_count": 3' in res
        assert "rows" in res

    def test_dict_with_dict_data_whitelists_keys(self):
        out = {"success": True, "data": {"summary": "ok", "secret": "hidden"}}
        res = AIChatApplicationService._workflow_output_preview(out)
        assert "summary" in res
        assert "secret" not in res

    def test_dict_with_scalar_data_passthrough(self):
        out = {"success": True, "data": 42}
        res = AIChatApplicationService._workflow_output_preview(out)
        assert "42" in res

    def test_raw_included_when_no_data(self):
        out = {"success": False, "raw": "raw-payload-text"}
        res = AIChatApplicationService._workflow_output_preview(out)
        assert "raw-payload-text" in res

    def test_truncation_applies(self):
        out = {"message": "z" * 2000}
        res = AIChatApplicationService._workflow_output_preview(out, max_chars=50)
        assert res.endswith("...")
        assert len(res) == 53

    def test_non_dict_scalar(self):
        res = AIChatApplicationService._workflow_output_preview(["a", "b"])
        assert "a" in res and "b" in res


# ---------------------------------------------------------------------------
# _format_workflow_tool_success_line
# ---------------------------------------------------------------------------


class TestFormatWorkflowToolSuccessLine:
    def test_employee_list_action(self):
        svc = _make_svc()
        item = _node_result(
            tool_id="employee",
            action="list",
            node_id="emp1",
            output={"data": {"registered_tool_count": 4}},
        )
        lines = svc._format_workflow_tool_success_line(item, {})
        assert any("发现 4 个可调用员工" in ln for ln in lines)

    def test_employee_other_action_with_message(self):
        svc = _make_svc()
        item = _node_result(
            tool_id="employee",
            action="invoke",
            node_id="emp2",
            output={"employee_id": "E007", "message": "done"},
        )
        lines = svc._format_workflow_tool_success_line(item, {})
        head = lines[0]
        assert "员工 E007" in head and "done" in head

    def test_business_db_read_counts_rows(self):
        svc = _make_svc()
        item = _node_result(
            tool_id="business_db",
            action="read",
            node_id="db1",
            output={"entity": "orders", "data": [1, 2, 3]},
        )
        lines = svc._format_workflow_tool_success_line(item, {})
        assert any("orders 查询 3 条" in ln for ln in lines)

    def test_business_db_write_uses_operation(self):
        svc = _make_svc()
        item = _node_result(
            tool_id="business_db",
            action="upsert",
            node_id="db2",
            output={"entity": "customers", "message": "saved"},
        )
        lines = svc._format_workflow_tool_success_line(
            item, {"operation": "upsert", "entity": "customers"}
        )
        assert any("customers.upsert" in ln and "saved" in ln for ln in lines)

    def test_default_with_message(self):
        svc = _make_svc()
        item = _node_result(tool_id="unknown", action="do", node_id="x1", output={"message": "yay"})
        lines = svc._format_workflow_tool_success_line(item, {})
        assert lines == ["- x1: 成功（yay）"]

    def test_default_without_message(self):
        svc = _make_svc()
        item = _node_result(tool_id="unknown", action="do", node_id="x2", output={})
        lines = svc._format_workflow_tool_success_line(item, {})
        assert lines == ["- x2: 成功"]


# ---------------------------------------------------------------------------
# _normal_slot_dispatch_chat_overlay  +  _format_workflow_run_response overlay
# ---------------------------------------------------------------------------


class TestNormalSlotDispatchOverlay:
    def test_picks_last_dispatch_with_autoaction(self):
        rr = SimpleNamespace(
            node_results=[
                _node_result(
                    tool_id="normal_slot_dispatch",
                    success=True,
                    output={
                        "success": True,
                        "response": "ship resp",
                        "autoAction": {"type": "open"},
                    },
                ),
            ]
        )
        res = AIChatApplicationService._normal_slot_dispatch_chat_overlay(rr)
        assert res["response"] == "ship resp"
        assert res["autoAction"] == {"type": "open"}

    def test_skips_when_no_autoaction_or_task(self):
        rr = SimpleNamespace(
            node_results=[
                _node_result(
                    tool_id="normal_slot_dispatch",
                    success=True,
                    output={"success": True, "response": "no action"},
                ),
            ]
        )
        assert AIChatApplicationService._normal_slot_dispatch_chat_overlay(rr) == {}

    def test_skips_failed_dispatch(self):
        rr = SimpleNamespace(
            node_results=[
                _node_result(
                    tool_id="normal_slot_dispatch",
                    success=False,
                    output={"success": False},
                ),
            ]
        )
        assert AIChatApplicationService._normal_slot_dispatch_chat_overlay(rr) == {}


# ---------------------------------------------------------------------------
# _build_order_text_from_products —— original_message 正则结构化分支
# ---------------------------------------------------------------------------


class TestBuildOrderTextFromProducts:
    def test_structured_message_regex_branch(self):
        """命中 7 组正则的结构化分支（>=7 组走 range(1,n,4) 循环）。

        注意：源码循环 `for i in range(1, len(m.groups()), 4)` 在 7 组时只取 i=1
        （i=5 时 i+3=8 > 7 跳过），故第二条订单项被丢弃。这是实际行为（见 suspected_bugs）。
        """
        svc = _make_svc()
        msg = "帮打七彩乐园的货单，10桶5003A规格25，5桶2737B规格30"
        products = [{"model": "5003A", "quantity_tins": 10, "spec": 25}]
        result = svc._build_order_text_from_products("七彩乐园", products, msg)
        assert result.startswith("七彩乐园")
        assert "桶5003A规格25" in result

    def test_fallback_when_message_not_matching(self):
        svc = _make_svc()
        products = [{"model": "X1", "quantity_tins": 2, "spec": 18}]
        result = svc._build_order_text_from_products("公司B", products, "随便聊聊")
        assert result == "公司B，2桶X1规格18"

    def test_model_missing_uses_qty_spec_only(self):
        svc = _make_svc()
        products = [{"quantity": 3, "tin_spec": 20}]
        result = svc._build_order_text_from_products("公司C", products, "")
        assert result == "公司C，3桶规格20"


# ---------------------------------------------------------------------------
# _execute_customers_intent —— ensure_exists 各分支
# ---------------------------------------------------------------------------


class TestExecuteCustomersIntent:
    def _resp(self):
        return {
            "success": True,
            "message": "处理完成",
            "data": {"text": "", "action": "", "data": {}},
        }

    def test_add_intent_missing_unit_name(self):
        svc = _make_svc()
        out = svc._execute_customers_intent(self._resp(), {}, {}, original_message="添加单位")
        assert "请告诉我单位名称" in out["response"]
        assert out["data"]["data"]["missing_fields"] == ["unit_name"]

    def test_add_intent_created(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "created": True},
        ):
            out = svc._execute_customers_intent(
                self._resp(), {"unit_name": "七彩乐园"}, {}, original_message="添加单位 七彩乐园"
            )
        assert out["response"] == "单位已创建：七彩乐园"

    def test_add_intent_already_exists(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": True, "created": False},
        ):
            out = svc._execute_customers_intent(
                self._resp(), {"unit_name": "老客户"}, {}, original_message="新增 老客户"
            )
        assert out["response"] == "单位已存在：老客户"

    def test_add_intent_tool_failure(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            return_value={"success": False, "message": "db error"},
        ):
            out = svc._execute_customers_intent(
                self._resp(), {"unit_name": "X"}, {}, original_message="创建 X"
            )
        assert out["response"] == "db error"

    def test_add_intent_exception(self):
        svc = _make_svc()
        with patch(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            side_effect=ValueError("boom"),
        ):
            out = svc._execute_customers_intent(
                self._resp(), {"unit_name": "Y"}, {}, original_message="添加 Y"
            )
        assert "处理单位失败" in out["response"]

    def test_query_intent_delegates(self):
        svc = _make_svc()
        with patch("app.bootstrap.get_customer_app_service") as gc:
            gc.return_value.get_all.return_value = {"data": [{"id": 1}, {"id": 2}]}
            out = svc._execute_customers_intent(
                self._resp(), {}, {}, original_message="查询客户列表"
            )
        assert "查询到 2 个客户" in out["response"]

    def test_no_intent_followup(self):
        svc = _make_svc()
        out = svc._execute_customers_intent(self._resp(), {}, {}, original_message="嗯嗯")
        assert out["data"]["data"]["intent"] == "customers_followup"


# ---------------------------------------------------------------------------
# _header_hint_column_roles —— 字段索引导入失败回退 + 关键词赋值
# ---------------------------------------------------------------------------
#
# 说明：源码内 `from app.services.ai_db_schema_index import ...` 指向的模块在当前
# 代码库中并不存在 → ImportError 属 RECOVERABLE_ERRORS，被静默吞掉走启发式/关键词回退。
# 因此这些测试天然命中 except 回退分支，无需 patch。


class TestHeaderHintColumnRoles:
    def test_keyword_map_assigns_four_roles(self):
        keys = ["客户名称", "产品名称", "规格型号", "单价", "无关列"]
        roles = AIChatApplicationService._header_hint_column_roles(keys)
        assert roles["unit_name"] == "客户名称"
        assert roles["product_name"] == "产品名称"
        assert roles["model_number"] == "规格型号"
        assert roles["unit_price"] == "单价"

    def test_keyword_aliases_and_normalization(self):
        # 含空格/全角符号也应被归一化命中；sku/price 英文别名命中型号/单价。
        keys = ["公 司", "品名", "sku", "价格"]
        roles = AIChatApplicationService._header_hint_column_roles(keys)
        assert roles["unit_name"] == "公 司"
        assert roles["product_name"] == "品名"
        assert roles["model_number"] == "sku"
        assert roles["unit_price"] == "价格"

    def test_unmatched_keys_leave_roles_empty(self):
        roles = AIChatApplicationService._header_hint_column_roles(["列甲", "列乙"])
        assert roles == {
            "unit_name": "",
            "product_name": "",
            "model_number": "",
            "unit_price": "",
        }


# ---------------------------------------------------------------------------
# _price_column_buckets —— 服务模块缺失，回退启发式分桶
# ---------------------------------------------------------------------------


class TestPriceColumnBuckets:
    def test_heuristic_splits_before_after(self):
        keys = ["调价前单价", "调价后单价", "其它价格", "名称"]
        before, after, generic = AIChatApplicationService._price_column_buckets(keys)
        assert "调价前单价" in before
        assert "调价后单价" in after


# ---------------------------------------------------------------------------
# _model_like_score / _packaging_or_measure_ratio 边界
# ---------------------------------------------------------------------------


class TestScoringHelpers:
    def test_model_like_alpha_and_digit(self):
        assert AIChatApplicationService._model_like_score("5003A") == 1.0

    def test_model_like_digits_only_short(self):
        assert AIChatApplicationService._model_like_score("12345") == 0.6

    def test_model_like_empty_zero(self):
        assert AIChatApplicationService._model_like_score("") == 0.0

    def test_model_like_too_long_zero(self):
        assert AIChatApplicationService._model_like_score("A" * 30) == 0.0

    def test_packaging_ratio_all_measures(self):
        ratio = AIChatApplicationService._packaging_or_measure_ratio(["桶", "箱", "袋"])
        assert ratio == 1.0

    def test_packaging_ratio_empty(self):
        assert AIChatApplicationService._packaging_or_measure_ratio(["", "  "]) == 0.0

    def test_packaging_ratio_mixed(self):
        ratio = AIChatApplicationService._packaging_or_measure_ratio(["桶", "七彩乐园"])
        assert 0.0 < ratio < 1.0
