"""Confirmed facts stay in the conversation that stated them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.application.ai_chat.confirmed_facts import try_confirmed_fact_reply
from app.application.ai_chat.dialogue_memory import conversation_key


@pytest.fixture
def memory_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    return tmp_path


def _ctx(conversation_id: str, turn: str, **extra: object) -> dict[str, object]:
    return {
        "local_user_id": 1,
        "tenant_id": 1,
        "conversation_id": conversation_id,
        "turn_id": turn,
        **extra,
    }


def _say(conversation_id: str, turn: str, text: str) -> str:
    payload = try_confirmed_fact_reply(text, _ctx(conversation_id, turn))
    assert payload is not None
    return str(payload["response"])


def test_acceptance_sequence_keeps_confirmed_numbers(memory_dir: Path) -> None:
    cid = "c13"
    assert "120" in _say(
        cid,
        "01",
        "请确认记下这些事实：客户总数120，A类70，B类50，合同总额360万元，会话标记蓝鲸-731。",
    )
    assert "70" in _say(cid, "02", "已确认的客户总数和分类是多少？")
    assert "128" in _say(cid, "03", "确认增加8个客户，其中A类5个、B类3个。")
    assert "75" in _say(cid, "04", "再问一次已确认的客户总数和分类。")
    hypo = _say(cid, "05", "假设A类再增加10个，暂时不要修改。")
    assert "138" in hypo and "128" in hypo and "已确认未改" in hypo
    assert "128" in _say(cid, "06", "已确认的客户总数是多少？")
    assert "75" in _say(cid, "06b", "已确认的客户总数和分类是多少？")
    lost = _say(cid, "07", "假设B类减少2个，暂时不要修改。")
    assert "126" in lost and "128" in lost
    assert "126" in _say(cid, "08", "把刚才增加的8个更正为增加6个，其中A类4个、B类2个。")
    assert "74" in _say(cid, "09", "已确认的客户总数和分类是多少？")
    assert "128" in _say(cid, "10", "撤销刚才的更正。")
    assert "53" in _say(cid, "11", "已确认的客户总数和分类是多少？")
    restored = _say(cid, "12", "确认恢复到最初的客户基线。")
    assert "120" in restored and "70" in restored and "50" in restored
    assert "360" in _say(cid, "13", "已确认的客户总数、分类和合同总额是多少？")
    assert "380" in _say(cid, "14", "确认合同总额改为380万元。")
    contract = _say(cid, "15", "假设合同总额420万元，暂时不要修改。")
    assert "420" in contract and "380" in contract
    assert "380" in _say(cid, "16", "实际合同总额是多少？")
    undone = _say(cid, "17", "撤销合同总额的修改。")
    assert "360" in undone and "380" not in undone


def test_hypothesis_and_replay_do_not_change_confirmed_values(memory_dir: Path) -> None:
    cid = "steady"
    _say(cid, "a", "请确认记下这些事实：客户总数10，A类6，B类4，合同总额2万元，会话标记甲-1。")
    first = _say(cid, "b", "假设A类再增加3个，暂时不要修改。")
    again = try_confirmed_fact_reply("假设A类再增加3个，暂时不要修改。", _ctx(cid, "b"))
    assert again is not None and again["response"] == first
    assert "10" in _say(cid, "c", "已确认的客户总数是多少？")
    assert try_confirmed_fact_reply("请查询企业客户库", _ctx(cid, "d")) is None


def test_sessions_and_tenants_do_not_share_facts(memory_dir: Path) -> None:
    _say("one", "1", "请确认记下这些事实：客户总数3，A类2，B类1，合同总额1万元，会话标记蓝鲸-731。")
    other = _say("two", "1", "本会话已确认的会话标记是什么？")
    assert "蓝鲸-731" not in other
    foreign = try_confirmed_fact_reply(
        "已确认的客户总数是多少？",
        _ctx("one", "2", tenant_id=2),
    )
    assert foreign is not None
    assert "3" not in foreign["response"]
    assert conversation_key(_ctx("one", "2")) != conversation_key(_ctx("one", "2", tenant_id=2))


def test_corrupt_store_and_empty_undo_are_safe(memory_dir: Path) -> None:
    key = conversation_key(_ctx("broken", "1"))
    path = memory_dir / f"{key}-facts.json"
    path.write_text("{", encoding="utf-8")
    assert "没有可撤销" in _say("broken", "1", "撤销刚才的更正。")
    path.write_text(json.dumps({"facts": "nope"}), encoding="utf-8")
    assert "没有" in _say("broken", "2", "已确认的客户总数是多少？")
