"""连续对话走桌面同一条事实账，不靠测试词表，也不把假设写成确认值。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application.ai_chat.dialogue_facts import empty_state, respond
from app.application.ai_chat.dialogue_memory import (
    dialogue_reply,
    prepare_chat_turn,
    settle_chat_turn,
    should_answer_as_dialogue,
    turn_status,
)


@pytest.fixture
def memory_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    return tmp_path


def test_operational_commands_stay_on_the_business_path(memory_dir: Path) -> None:
    assert should_answer_as_dialogue("发货单 太阳鸟 5桶 20L规格", {"conversation_id": "c11"}) is False
    assert should_answer_as_dialogue("查一下客户", {"conversation_id": "c11"}) is False
    assert should_answer_as_dialogue(
        "请提交一个缺陷工单",
        {"conversation_id": "c11"},
    ) is False
    assert (
        should_answer_as_dialogue(
            "如果按这个表统计有多少行",
            {"conversation_id": "sheet", "excel_analysis": {"file_path": "/tmp/a.xlsx"}},
        )
        is False
    )
    assert should_answer_as_dialogue(
        "我们发现一个问题，在聊天过程中切换到客户管理页面，首次加载可能需要1.7秒。",
        {"conversation_id": "c11"},
    )


def _say(session: str, text: str, index: int) -> str:
    context = {"conversation_id": session, "turn_id": f"{session}-{index}"}
    replay = prepare_chat_turn(text, context)
    assert replay is None
    payload = dialogue_reply(text, context)
    assert payload is not None
    settle_chat_turn(text, context, payload, "completed")
    return str(payload["response"])


def test_same_turn_does_not_run_twice(memory_dir: Path) -> None:
    context = {"conversation_id": "retry", "turn_id": "same"}
    text = "星河科技目前有120家客户。"
    assert prepare_chat_turn(text, context) is None
    payload = dialogue_reply(text, context)
    settle_chat_turn(text, context, payload, "completed")
    again = prepare_chat_turn(text, context)
    assert again is not None
    assert "120" in str(again["response"])
    other = prepare_chat_turn("星河科技目前有1家客户。", context)
    assert other is not None and other["success"] is False


def test_abandoned_turn_is_not_a_successful_analysis(memory_dir: Path) -> None:
    context = {"conversation_id": "half", "turn_id": "open"}
    assert prepare_chat_turn("企业目前有120家客户。", context) is None
    assert turn_status("half", "open") == "processing"
    # 新进程不再把这一轮留在处理中。
    from app.application.ai_chat import dialogue_memory as memory

    memory._INFLIGHT.clear()
    prepare_chat_turn("后来新增10家客户。", {"conversation_id": "half", "turn_id": "next"})
    assert turn_status("half", "open") == "interrupted"


def test_c11_c13_c14_and_isolated_markers(memory_dir: Path) -> None:
    c11 = [
        "我们现在要对一款企业级桌面软件进行稳定性测试，产品名称叫 XCMAX，主要运行在 Windows 桌面端。",
        "这款软件主要包含聊天、员工图谱、ERP、MOD 商店和系统设置五个主要模块。",
        "当前测试重点不是安装功能，而是客户端运行过程中的稳定性。",
        "我们发现一个问题，在聊天过程中切换到客户管理页面，首次加载可能需要1.7秒。",
        "页面已经加载完成后，再次切换到同一个页面通常只需要几十毫秒。",
        "现在我们要重点检查连续切换页面、聊天历史读取、流式输出和网络中断恢复。",
        "其中页面切换测试要求连续切换100次，聊天测试要求连续进行20轮对话。",
        "如果出现消息丢失、重复消息或者不同对话之间内容串线，都应该判定为严重缺陷。",
        "你先把目前的测试范围整理一下，但不要加入安装和卸载测试。",
        "我们还需要测试三个独立聊天窗口同时运行，分别命名为A、B、C。",
        "A窗口专门讨论客户管理，B窗口讨论库存管理，C窗口讨论财务管理。",
        "A窗口的测试数据是客户数量120家，其中活跃客户80家。",
        "B窗口的测试数据是库存商品500件，其中缺货商品20件。",
        "C窗口的测试数据是本月收入50万元，支出30万元。",
        "现在我修改一下，A窗口的客户数量从120家调整为150家，活跃客户仍然是80家。",
        "B窗口的数据不变，C窗口的数据也不变。",
        "现在告诉我三个窗口分别对应什么业务，以及最新的数据是什么。",
        "如果A窗口新增30家客户，其中10家成为活跃客户，那么活跃客户数量是多少？",
        "现在撤销刚才的模拟新增操作，恢复到新增之前的数据。",
        "最后总结整个测试项目的名称、运行平台、五个模块、测试范围、三个窗口的数据以及质量判定标准。",
    ]
    replies = [_say("c11", text, index) for index, text in enumerate(c11, 1)]
    assert "150" in replies[14] and "80" in replies[14]
    assert "500" in replies[12] and "20" in replies[12]
    assert "90" in replies[17] and "150" in replies[17]
    assert "工单" not in replies[3]
    final = replies[-1]
    for token in ("XCMAX", "Windows", "聊天", "员工图谱", "ERP", "MOD 商店", "系统设置", "1.7", "几十毫秒", "100", "20"):
        assert token in final
    assert "150" in replies[16] and "80" in replies[16]
    assert "500" in replies[18] and "50" in replies[18]

    c13 = [
        "我们正在为一家名为星河科技的企业制定数字化管理方案。",
        "这家公司目前有研发部、销售部、财务部和客户服务部。",
        "研发部有12人，销售部有20人。",
        "财务部有5人，客户服务部有8人。",
        "公司目前总共有多少员工？",
        "哪个部门人数最多？",
        "哪两个部门人数加起来刚好等于20人？",
        "现在销售部增加3名员工。",
        "研发部再增加2名员工。",
        "现在公司总人数是多少？",
        "刚才销售部增加3人是错误的，实际只增加1人。",
        "研发部的人数保持不变。",
        "重新计算公司总人数。",
        "告诉我销售部和研发部目前各有多少人。",
        "公司计划招聘员工，但研发部暂时不招聘。",
        "销售部计划招聘5人，财务部计划招聘2人。",
        "客服部计划招聘3人。",
        "哪些部门可以招聘？",
        "如果研发部也允许招聘，那么总招聘人数是多少？",
        "现在恢复原来的限制，研发部不允许招聘。最终招聘人数是多少？",
        "根据之前所有信息，整理星河科技目前的组织情况，要求包含四个部门目前的人数。",
    ]
    org = [_say("c13", text, index) for index, text in enumerate(c13, 1)]
    assert "45" in org[4]
    assert "销售" in org[5]
    assert "研发" in org[6] and "客服" in org[6]
    assert "50" in org[9]
    assert "21" in org[10] and "48" in org[10]
    assert "14" in org[11]
    assert "48" in org[12]
    assert "21" in org[13] and "14" in org[13]
    assert "无法计算" in org[18]
    assert "10" in org[19]
    assert "48" in org[20] and "43" not in org[20].split("若另有清单")[0]
    assert "23" not in org[20]

    company = empty_state()
    script = Path("/opt/cursor/artifacts/c14.jsonl")
    lines = []
    if script.is_file():
        import json

        seen = []
        for line in script.read_text(encoding="utf-8").splitlines():
            user = json.loads(line)["user"]
            if user in seen[:29] and len(seen) < 58:
                continue
            seen.append(user)
            lines.append(user)
        lines = lines[:100]
    assert len(lines) == 100
    answers = []
    for text in lines:
        answers.append(respond(company, text))
    report = answers[-1]
    for token in ("135", "86", "49", "530", "3200", "18", "19000", "14000", "5000", "46", "12", "96"):
        assert token in report
    assert "90" not in answers[16] or "确认" in answers[16]
    assert company["company"]["active"] == 86
    assert company["orders"]["B"]["status"] == "cancelled"
    assert company["orders"]["C"]["amount"] == 14000

    _say("whale", "当前会话是客户管理任务，识别标记为蓝鲸-731。我们有120家客户，其中80家活跃。", 1)
    whale = _say("whale", "我之前提供的客户识别标记是什么？库存数量是多少？", 2)
    assert "蓝鲸-731" in whale and "没有库存" in whale
    _say("pine", "当前会话是库存管理任务，识别标记为松塔-284。我们有500种商品，库存总量3000件，其中20种商品缺货。", 1)
    pine = _say("pine", "如果补货500件，总库存是多少？", 2)
    assert "3500" in pine and "3000" in pine
    assert "蓝鲸" not in pine
    pine_income = _say("pine", "我之前提供的库存识别标记是什么？本月收入是多少？", 3)
    assert "松塔-284" in pine_income and "没有本月收入" in pine_income
    _say("egret", "当前会话是财务管理任务，识别标记为白鹭-916。本月收入50万元，支出30万元。", 1)
    balance = _say("egret", "计算本月结余，并给出成本控制建议。", 2)
    assert "20" in balance and "不能编造" in balance
    assert "蓝鲸" not in balance and "松塔" not in balance
