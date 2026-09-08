"""拒绝类写请求守卫：拒绝话术不得生成/执行写入计划。

覆盖三层入口：
- looks_like_refused_write：守卫谓词本身（前缀拒绝 + 写动词 + 域内豁免）
- route_normal_mode_message：普通版分流被短路为 refused_write
- try_deterministic_chat_reply：pro 主链快路径直接确认取消，不进 planner
- try_handle_business_chat_action：受保护考勤写操作对拒绝话术不执行
"""

from __future__ import annotations

from app.application.chat_tool_intent import looks_like_refused_write
from app.application.normal_chat_dispatch import route_normal_mode_message
from app.application.workflow.chat_deterministic_fast_paths import try_deterministic_chat_reply


class TestLooksLikeRefusedWrite:
    def test_refusal_with_write_verb_blocked(self):
        assert looks_like_refused_write("不要给七彩乐园生成发货单")
        assert looks_like_refused_write("别开发货单")
        assert looks_like_refused_write("帮我不要打印标签")
        assert looks_like_refused_write("不用上传这个文件")
        assert looks_like_refused_write("不需要新增客户")
        assert looks_like_refused_write("别删除侯雪梅")
        assert looks_like_refused_write("算了，不要开单")
        assert looks_like_refused_write("不想导入这批产品")

    def test_english_refusal_blocked(self):
        assert looks_like_refused_write("don't generate the shipment")
        assert looks_like_refused_write("Do not delete the customer")

    def test_mid_sentence_negation_not_blocked(self):
        # 「不要」在句中是数量/样式限定，不是拒绝执行。
        assert not looks_like_refused_write("发货单不要超过10桶")
        assert not looks_like_refused_write("打印不要彩色的")

    def test_plain_write_requests_not_blocked(self):
        assert not looks_like_refused_write("帮我打开发货单")
        assert not looks_like_refused_write("开单")
        assert not looks_like_refused_write("删除七彩乐园")
        assert not looks_like_refused_write("查一下客户")
        assert not looks_like_refused_write("你好")
        assert not looks_like_refused_write("")

    def test_comparison_and_attendance_cancel_exempted(self):
        # 「别的…」是比较而非拒绝。
        assert not looks_like_refused_write("别的客户开发货单")
        # 考勤域销假是合法的取消写入请求，不是拒绝生成计划。
        assert not looks_like_refused_write("不用请假了")
        assert not looks_like_refused_write("假不请了")
        assert not looks_like_refused_write("取消李四明天的请假")


class TestRouteNormalModeMessageGuard:
    def test_refused_shipment_not_routed_to_write(self):
        result = route_normal_mode_message("不要给七彩乐园生成发货单")
        assert result["intent"] == "refused_write"

    def test_refused_delete_not_routed_to_write(self):
        result = route_normal_mode_message("别删除侯雪梅")
        assert result["intent"] == "refused_write"

    def test_normal_shipment_still_routed(self):
        result = route_normal_mode_message("帮我打开发货单")
        assert result["intent"] == "shipment"

    def test_mid_sentence_negation_still_routed(self):
        result = route_normal_mode_message("发货单不要超过10桶")
        assert result["intent"] == "shipment"


class TestDeterministicFastPathGuard:
    def test_refusal_short_circuits_before_planner(self):
        reply = try_deterministic_chat_reply("不要给七彩乐园生成发货单")
        assert reply is not None
        assert reply["action"] == "refused_write"
        assert reply["trace_intent"] == "refused_write"
        assert "取消" in reply["response"]

    def test_business_query_not_affected(self):
        # 正常计数问题不受守卫影响（仍走计数快路径或返回 None 交后续链路）。
        reply = try_deterministic_chat_reply("产品表一共有多少条记录")
        assert reply is None or reply.get("action") != "refused_write"


class TestBusinessSafetyGuard:
    def test_refused_leave_not_executed(self):
        from app.application.chat_business_safety import try_handle_business_chat_action

        # 「不要给李四请假」不得触发受保护请假写入。
        assert try_handle_business_chat_action("不要给李四明天请假半天，他家里有事") is None

    def test_legit_leave_write_still_classified(self):
        from app.application.chat_business_safety_core import classify_business_chat_intent

        # 合法请假话术仍被识别为 leave_write（守卫不拦截肯定式写入）。
        intent = classify_business_chat_intent("给李四登记明天请假半天")
        assert intent is not None and intent.operation == "leave_write"
