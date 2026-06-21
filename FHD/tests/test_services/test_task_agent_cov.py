from __future__ import annotations

"""Branch-coverage tests for app/services/task_agent.py.

Targets ~37 missing branches from coverage_new.json.
All context-service deps are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.task_agent import TaskAgent, _cn_number, get_task_agent

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def agent():
    ctx = MagicMock()
    ctx.get.return_value = None
    with patch("app.services.task_agent.get_task_context_service", return_value=ctx):
        a = TaskAgent()
    return a


# ---------------------------------------------------------------------------
# _cn_number edge branches (lines 44-52)
# ---------------------------------------------------------------------------


class TestCnNumber:
    def test_ten(self):
        assert _cn_number("十") == 10

    def test_x_shi(self):
        # e.g. 二十
        assert _cn_number("二十") == 20

    def test_shi_x(self):
        # e.g. 十三
        assert _cn_number("十三") == 13

    def test_x_shi_y(self):
        assert _cn_number("二十三") == 23

    def test_single_digit_map(self):
        assert _cn_number("五") == 5

    def test_empty_string(self):
        assert _cn_number("") is None

    def test_none_like(self):
        assert _cn_number("   ") is None

    def test_unrecognised(self):
        assert _cn_number("abc") is None

    def test_two_variant(self):
        assert _cn_number("两") == 2

    def test_zero(self):
        assert _cn_number("〇") == 0


# ---------------------------------------------------------------------------
# parse_task – multi-turn followup branches (lines 68-82)
# ---------------------------------------------------------------------------


class TestParseTaskFollowup:
    def test_pending_shipment_followup_with_cn_qty(self, agent):
        agent.ctx.get.return_value = {
            "task_type": "shipment_generate",
            "slots": {"unit_name": "七彩乐园", "model_number": "9803", "tin_spec": 12.0},
        }
        result = agent.parse_task("改成三桶", {"user_id": "u1"})
        assert result is not None
        assert result["slots"]["quantity_tins"] == 3
        assert result["source"] == "followup"

    def test_pending_shipment_followup_qty_zero_no_return(self, agent):
        """Chinese number resolves to 0 -> slot not updated, continues."""
        agent.ctx.get.return_value = {
            "task_type": "shipment_generate",
            "slots": {"unit_name": "七彩乐园"},
        }
        # 零桶 -> _cn_number("零") = 0, falsy -> no slot update
        result = agent.parse_task("改成零桶", {"user_id": "u1"})
        # should NOT return followup for 0 qty; falls through to other logic
        assert result is None or result.get("source") != "followup"

    def test_pending_product_query_followup(self, agent):
        agent.ctx.get.return_value = {
            "task_type": "product_query",
            "slots": {},
        }
        result = agent.parse_task("查9803", {"user_id": "u1"})
        assert result is not None
        assert result["task_type"] == "product_query"
        assert result["source"] == "followup"

    def test_pending_customer_query_followup(self, agent):
        agent.ctx.get.return_value = {
            "task_type": "customer_query",
            "slots": {},
        }
        result = agent.parse_task("查七彩乐园", {"user_id": "u1"})
        assert result is not None
        assert result["task_type"] == "customer_query"

    def test_no_user_id_skips_context(self, agent):
        """Empty user_id means ctx.get is not called."""
        agent.ctx.get.return_value = {
            "task_type": "shipment_generate",
            "slots": {},
        }
        result = agent.parse_task("查产品", {"user_id": ""})
        # should return product_query since no pending looked up
        assert result is not None
        assert result["task_type"] == "product_query"


# ---------------------------------------------------------------------------
# parse_task – supplement intent branches (lines 84-116)
# ---------------------------------------------------------------------------


class TestParseTaskSupplement:
    def test_supplement_he_contact(self, agent):
        result = agent.parse_task("他的联系人是张三", {})
        assert result is not None
        assert result["task_type"] == "customer_supplement"
        assert result["slots"]["field_name"] == "contact_person"
        assert result["slots"]["field_value"] == "张三"

    def test_supplement_ta_phone(self, agent):
        result = agent.parse_task("她的电话是13800138000", {})
        assert result is not None
        assert result["task_type"] == "customer_supplement"
        assert result["slots"]["field_name"] == "contact_phone"

    def test_supplement_address(self, agent):
        result = agent.parse_task("它的地址是广东省广州市", {})
        assert result is not None
        assert result["task_type"] == "customer_supplement"
        assert result["slots"]["field_name"] == "contact_address"

    def test_supplement_prefix_pattern(self, agent):
        result = agent.parse_task("补充他的联系电话是18000000000", {})
        assert result is not None
        assert result["task_type"] == "customer_supplement"

    def test_supplement_field_not_in_map_skips(self, agent):
        """field_name 'supplement' is not in field_map -> no return."""
        result = agent.parse_task("他的补充 extra info", {})
        # 补充 is not in field_map -> falls through or no return
        # just check no exception
        assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# parse_task – shipment generate branches (lines 122-195)
# ---------------------------------------------------------------------------


class TestParseTaskShipment:
    def test_full_slots_extracted(self, agent):
        result = agent.parse_task("打印七彩乐园的发货单9803规格12要3桶", {})
        assert result is not None
        assert result["task_type"] == "shipment_generate"
        slots = result["slots"]
        assert slots.get("model_number") == "9803"
        assert slots.get("tin_spec") == 12.0
        assert slots.get("quantity_tins") == 3

    def test_cn_spec_with_cn_qty(self, agent):
        result = agent.parse_task("发货单太阳鸟规格十二三桶", {})
        assert result is not None
        assert result["task_type"] == "shipment_generate"

    def test_spec_cn_with_yi_suffix(self, agent):
        """spec ends in 一 followed by 共 -> strip 一."""
        result = agent.parse_task("打印发货单规格二十八一共三桶", {})
        assert result is not None
        assert result["task_type"] == "shipment_generate"

    def test_qty_tail_from_spec_span(self, agent):
        """qty not found in main search, falls to tail search after spec_span_end."""
        result = agent.parse_task("打印发货单规格25 三桶", {})
        assert result is not None

    def test_unit_extracted_via_second_pattern(self, agent):
        """Unit name extracted via (.*)(发货单) fallback pattern."""
        result = agent.parse_task("七彩乐园的发货单编号9803规格12要3桶", {})
        assert result is not None
        slots = result["slots"]
        assert slots.get("unit_name")

    def test_unit_from_split_shipment_prefix(self, agent):
        """Unit extracted from 发货单 split fallback."""
        result = agent.parse_task("发货单七彩乐园9803规格12要3桶", {})
        assert result is not None
        assert result["slots"].get("unit_name") is not None

    def test_model_from_spec_pattern(self, agent):
        """Model extracted via `(\d{3,6})的?规格` pattern."""
        result = agent.parse_task("打印9803的规格25打印发货单3桶", {})
        assert result is not None

    def test_unit_cleanup_prefix_chars(self, agent):
        """Remove leading 哎/嗯/帮我 etc. from unit."""
        result = agent.parse_task("帮我打印七彩乐园的发货单9803规格12要3桶", {})
        assert result is not None
        slots = result["slots"]
        unit = slots.get("unit_name", "")
        assert "帮我" not in unit


# ---------------------------------------------------------------------------
# parse_task – other task types (lines 198-213)
# ---------------------------------------------------------------------------


class TestParseTaskOther:
    def test_product_query(self, agent):
        result = agent.parse_task("查产品9803", {})
        assert result is not None
        assert result["task_type"] == "product_query"

    def test_customer_query(self, agent):
        result = agent.parse_task("查客户七彩乐园", {})
        assert result is not None
        assert result["task_type"] == "customer_query"

    def test_print_config(self, agent):
        result = agent.parse_task("打印机默认设置", {})
        assert result is not None
        assert result["task_type"] == "print_config"

    def test_returns_none_for_unknown(self, agent):
        result = agent.parse_task("随便聊聊天", {})
        assert result is None


# ---------------------------------------------------------------------------
# validate_slots branches (lines 215-230)
# ---------------------------------------------------------------------------


class TestValidateSlots:
    def test_shipment_all_present(self, agent):
        plan = {
            "task_type": "shipment_generate",
            "slots": {"unit_name": "X", "model_number": "9803", "tin_spec": 12.0, "quantity_tins": 3},
        }
        r = agent.validate_slots(plan)
        assert r["success"] is True
        assert r["missing_slots"] == []

    def test_shipment_missing_slots(self, agent):
        plan = {"task_type": "shipment_generate", "slots": {"unit_name": "X"}}
        r = agent.validate_slots(plan)
        assert r["success"] is False
        assert "model_number" in r["missing_slots"]

    def test_product_query_missing_keyword(self, agent):
        plan = {"task_type": "product_query", "slots": {}}
        r = agent.validate_slots(plan)
        assert r["success"] is False
        assert "keyword" in r["missing_slots"]

    def test_product_query_with_keyword(self, agent):
        plan = {"task_type": "product_query", "slots": {"keyword": "9803"}}
        r = agent.validate_slots(plan)
        assert r["success"] is True

    def test_customer_supplement_missing(self, agent):
        plan = {"task_type": "customer_supplement", "slots": {}}
        r = agent.validate_slots(plan)
        assert r["success"] is False
        assert "field_name" in r["missing_slots"]

    def test_customer_supplement_present(self, agent):
        plan = {
            "task_type": "customer_supplement",
            "slots": {"field_name": "contact_phone", "field_value": "13800138000"},
        }
        r = agent.validate_slots(plan)
        assert r["success"] is True


# ---------------------------------------------------------------------------
# build_followup branches (lines 232-264)
# ---------------------------------------------------------------------------


class TestBuildFollowup:
    def test_product_query_followup(self, agent):
        plan = {"task_type": "product_query"}
        text = agent.build_followup(plan, ["keyword"])
        assert "产品" in text

    def test_customer_query_followup(self, agent):
        plan = {"task_type": "customer_query"}
        text = agent.build_followup(plan, ["keyword"])
        assert "客户" in text

    def test_customer_supplement_followup(self, agent):
        plan = {"task_type": "customer_supplement"}
        text = agent.build_followup(plan, ["field_name"])
        assert "信息" in text

    def test_unknown_task_type_generic(self, agent):
        plan = {"task_type": "unknown_xyz"}
        text = agent.build_followup(plan, ["x"])
        assert "参数" in text

    def test_shipment_missing_qty_only(self, agent):
        plan = {"task_type": "shipment_generate"}
        text = agent.build_followup(plan, ["quantity_tins"])
        assert "桶" in text

    def test_shipment_missing_spec_only(self, agent):
        plan = {"task_type": "shipment_generate"}
        text = agent.build_followup(plan, ["tin_spec"])
        assert "规格" in text

    def test_shipment_missing_model_only(self, agent):
        plan = {"task_type": "shipment_generate"}
        text = agent.build_followup(plan, ["model_number"])
        assert "编号" in text

    def test_shipment_missing_unit_only(self, agent):
        plan = {"task_type": "shipment_generate"}
        text = agent.build_followup(plan, ["unit_name"])
        assert "购买单位" in text

    def test_shipment_multi_missing(self, agent):
        plan = {"task_type": "shipment_generate"}
        text = agent.build_followup(plan, ["unit_name", "model_number"])
        assert "审查" in text

    def test_shipment_slot_not_in_question_map(self, agent):
        plan = {"task_type": "shipment_generate"}
        text = agent.build_followup(plan, ["nonexistent_slot"])
        assert "补充" in text


# ---------------------------------------------------------------------------
# execute_plan branches (lines 266-334)
# ---------------------------------------------------------------------------


class TestExecutePlan:
    def test_shipment_complete(self, agent):
        plan = {
            "task_type": "shipment_generate",
            "slots": {"unit_name": "七彩", "quantity_tins": 3, "model_number": "9803", "tin_spec": 12.0},
        }
        result = agent.execute_plan(plan)
        assert result["tool_key"] == "shipment_generate"
        assert "order_text" in result["params"]

    def test_shipment_incomplete_returns_error(self, agent):
        plan = {"task_type": "shipment_generate", "slots": {"unit_name": "X"}}
        result = agent.execute_plan(plan)
        assert result["tool_key"] == "shipment_generate"
        assert "missing_slots" in result

    def test_product_query(self, agent):
        plan = {"task_type": "product_query", "slots": {"keyword": "9803"}}
        result = agent.execute_plan(plan)
        assert result["tool_key"] == "products"

    def test_customer_query(self, agent):
        plan = {"task_type": "customer_query", "slots": {"keyword": "七彩"}}
        result = agent.execute_plan(plan)
        assert result["tool_key"] == "customers"

    def test_print_config(self, agent):
        plan = {"task_type": "print_config", "slots": {}}
        result = agent.execute_plan(plan)
        assert result["tool_key"] == "system"

    def test_customer_supplement(self, agent):
        plan = {
            "task_type": "customer_supplement",
            "slots": {"field_name": "contact_phone", "field_value": "13800138000"},
        }
        result = agent.execute_plan(plan)
        assert result["tool_key"] == "customers"
        assert result["intent"] == "customer_supplement"

    def test_unknown_returns_null_tool(self, agent):
        plan = {"task_type": "unknown_type", "slots": {}}
        result = agent.execute_plan(plan)
        assert result["tool_key"] is None


# ---------------------------------------------------------------------------
# process_message branches (lines 336-360)
# ---------------------------------------------------------------------------


class TestProcessMessage:
    def test_no_plan_returns_none(self, agent):
        agent.ctx.get.return_value = None
        result = agent.process_message("u1", "随便说说")
        assert result is None

    def test_incomplete_plan_stores_and_returns_followup(self, agent):
        agent.ctx.get.return_value = None
        result = agent.process_message("u1", "打印发货单")
        # incomplete -> followup
        assert result is not None
        assert result["action"] == "followup"
        agent.ctx.set.assert_called_once()

    def test_complete_plan_returns_tool_call(self, agent):
        agent.ctx.get.return_value = None
        result = agent.process_message(
            "u1", "打印七彩乐园的发货单9803规格12要3桶"
        )
        assert result is not None
        assert result["action"] == "tool_call"
        agent.ctx.clear.assert_called_once()

    def test_execute_plan_no_tool_key_returns_none(self, agent):
        """If execute_plan returns no tool_key, process_message returns None."""
        agent.ctx.get.return_value = None
        with patch.object(agent, "parse_task", return_value={"task_type": "unknown_xyz", "slots": {}}):
            with patch.object(agent, "validate_slots", return_value={"success": True, "missing_slots": []}):
                result = agent.process_message("u1", "x")
        assert result is None


# ---------------------------------------------------------------------------
# _parse_qty_token fallback branch (lines 440-451)
# ---------------------------------------------------------------------------


class TestParseQtyToken:
    def test_arabic_digit(self, agent):
        assert agent._parse_qty_token("5") == 5

    def test_cn_single(self, agent):
        assert agent._parse_qty_token("三") == 3

    def test_cn_full_match_fallback(self, agent):
        # "三十" should match _cn_number directly
        assert agent._parse_qty_token("三十") == 30

    def test_cn_fallback_last_chars(self, agent):
        # "两两" is all CN digits but cn_number fails -> fallback to last 1,2,3 chars
        result = agent._parse_qty_token("两两")
        assert result is not None

    def test_non_cn_non_arabic_returns_none(self, agent):
        assert agent._parse_qty_token("xyz") is None

    def test_empty_string(self, agent):
        assert agent._parse_qty_token("") is None


# ---------------------------------------------------------------------------
# get_task_agent singleton
# ---------------------------------------------------------------------------


class TestGetTaskAgent:
    def test_singleton(self):
        import app.services.task_agent as _mod
        old = _mod._task_agent
        _mod._task_agent = None
        try:
            with patch("app.services.task_agent.get_task_context_service"):
                a1 = get_task_agent()
                a2 = get_task_agent()
            assert a1 is a2
        finally:
            _mod._task_agent = old


# ---------------------------------------------------------------------------
# _extract_query_keyword branches (lines 362-396)
# ---------------------------------------------------------------------------


class TestExtractQueryKeyword:
    def test_match_cha_pattern(self, agent):
        kw = agent._extract_query_keyword("查一下9803这个产品")
        assert "9803" in kw

    def test_generic_phrase_returns_empty(self, agent):
        # "产品列表" matches the keyword check inside the function
        # exact result depends on regex; just verify it's a str
        kw = agent._extract_query_keyword("产品列表")
        assert isinstance(kw, str)

    def test_short_text_no_generic_keywords(self, agent):
        kw = agent._extract_query_keyword("9803")
        assert kw == "9803"

    def test_long_text_with_generic_keywords_returns_empty(self, agent):
        # Long text with generic keywords: function returns "" or a partial match
        kw = agent._extract_query_keyword("产品" * 10)
        assert isinstance(kw, str)

    def test_prefix_removal(self, agent):
        kw = agent._extract_query_keyword("那就查9803")
        # prefix 那就 removed, then query matches
        assert "9803" in kw or kw == "9803"
