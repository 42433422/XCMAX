import pytest


def test_task_agent_parse_long_colloquial_shipment():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    msg = "哎，给我打印一下七彩乐园的发货单，嗯，编号9803，规格二十八一共三桶。"
    result = agent.process_message("u_task_1", msg)

    assert result is not None
    assert result["action"] == "tool_call"
    assert result["data"]["tool_key"] == "shipment_generate"
    assert "order_text" in result["data"]["params"]
    assert "9803" in result["data"]["params"]["order_text"]
    assert "3 桶" in result["data"]["params"]["order_text"]


def test_task_agent_declines_oversized_input_before_slot_regexes():
    from app.services.task_agent import get_task_agent

    assert get_task_agent().parse_task("编号" + "0" * 100_000) is None


def test_task_agent_should_parse_spec_and_qty_without_separator():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    msg = "我打印一下七彩乐园的发货单，嗯，产品是9803规格二十八两桶"
    result = agent.process_message("u_task_1b", msg)

    assert result is not None
    assert result["action"] == "tool_call"
    assert result["data"]["tool_key"] == "shipment_generate"
    assert "9803" in result["data"]["params"]["order_text"]
    assert "28" in result["data"]["params"]["order_text"]
    assert "2 桶" in result["data"]["params"]["order_text"]


def test_task_agent_followup_then_fill_bucket():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    first = agent.process_message("u_task_2", "给我打印七彩乐园的发货单，编号9803，规格28")
    assert first is not None
    assert first["action"] == "followup"
    assert "多少桶" in first["text"]

    second = agent.process_message("u_task_2", "改成5桶")
    assert second is not None
    assert second["action"] == "tool_call"
    assert second["data"]["tool_key"] == "shipment_generate"
    assert "5 桶" in second["data"]["params"]["order_text"]


def test_task_agent_products_fallback():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    result = agent.process_message("u_task_3", "帮我看一下产品列表")
    assert result is not None
    assert result["action"] == "followup"
    assert "查哪个产品" in result["text"]


def test_task_agent_product_query_slots_should_extract():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    result = agent.process_message("u_task_4", "查一下型号9803规格28的产品")
    assert result is not None
    assert result["action"] == "tool_call"
    assert result["data"]["tool_key"] == "products"
    assert result["data"]["params"]["action"] == "search"
    assert "9803" in result["data"]["params"]["keyword"]


def test_task_agent_customer_query_followup_then_fill():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    first = agent.process_message("u_task_5", "帮我查客户")
    assert first is not None
    assert first["action"] == "followup"
    assert "查哪个客户" in first["text"]

    second = agent.process_message("u_task_5", "七彩乐园")
    assert second is not None
    assert second["action"] == "tool_call"
    assert second["data"]["tool_key"] == "customers"
    assert second["data"]["params"]["action"] == "search"
    assert second["data"]["params"]["keyword"] == "七彩乐园"


def test_task_agent_followup_should_use_chinese_slot_labels():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    result = agent.process_message("u_task_6", "打印一下七彩乐园发货单，编号9803")
    assert result is not None
    assert result["action"] == "followup"
    assert "规格" in result["text"]
    assert "多少桶" in result["text"]
    assert "tin_spec" not in result["text"]
    assert "quantity_tins" not in result["text"]
    assert "信息还不完整" not in result["text"]


def test_task_agent_followup_should_ask_natural_questions():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    result = agent.process_message("u_task_7", "打印发货单，七彩乐园")
    assert result is not None
    assert result["action"] == "followup"
    assert "审查了一下这句话" in result["text"]
    assert "编号好像还没有呢" in result["text"]
    assert "规格是多少呢" in result["text"]
    assert "多少桶呢" in result["text"]


def test_task_agent_should_parse_compact_shipment_with_qty_verb():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    msg = "发货单七彩乐园9803规格12要3桶"
    result = agent.process_message("u_task_8", msg)

    assert result is not None
    assert result["action"] == "tool_call"
    assert result["data"]["tool_key"] == "shipment_generate"
    assert "七彩乐园" in result["data"]["params"]["order_text"]
    assert "9803" in result["data"]["params"]["order_text"]
    assert "12" in result["data"]["params"]["order_text"]
    assert "3 桶" in result["data"]["params"]["order_text"]


def test_task_agent_linear_number_parser_preserves_common_shipment_grammar():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    arabic = agent.parse_task("打印七彩乐园的发货单编号9803规格12.5要3桶")
    chinese = agent.parse_task("发货单太阳鸟型号12345规格二十八一共三桶")
    assert arabic["slots"] == {
        "model_number": "9803",
        "tin_spec": 12.5,
        "quantity_tins": 3,
        "unit_name": "七彩乐园",
    }
    assert chinese["slots"] == {
        "model_number": "12345",
        "tin_spec": 28.0,
        "quantity_tins": 3,
        "unit_name": "太阳鸟",
    }


def test_task_agent_linear_number_parser_handles_near_miss_user_text():
    from app.services.task_agent import get_task_agent

    agent = get_task_agent()
    # Under the established 4096-character input limit these long numeric runs
    # must be scanned once and rejected as invalid model/spec/quantity tokens.
    near_miss = "打印单位的发货单编号" + "9" * 4000 + "规格" + "一" * 40 + "桶"
    plan = agent.parse_task(near_miss)
    assert plan is not None
    # Legacy {3,6} model grammar captured the first six digits of a longer run.
    assert plan["slots"]["model_number"] == "999999"
    assert "tin_spec" not in plan["slots"]
    # The existing colloquial fallback treats the final Chinese numeral in a
    # glued run as the quantity, so preserve that established interpretation.
    assert plan["slots"]["quantity_tins"] == 1
