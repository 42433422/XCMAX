"""「账号」只是弱信号：纯账号求助仍只聊不建单；产品缺陷 + 请提交工单即使提到账号也要建单。"""

from __future__ import annotations

import pytest

from tests.test_customer_service_api import _make_user
from tests.test_customer_ticket_customer_view import INTERNAL_KEYS, _keys

pytest.importorskip("fastapi")

DEFECT = "管理端工单详情页面显示异常，分不出是哪个提交账号提的单，这是产品问题，请提交工单"
BASE = "/api/customer-service"


def test_infer_intent_account_word_is_weak_signal():
    from modstore_server.customer_service_orchestrator import (
        infer_intent,
        resolve_triage_lane,
        should_create_ticket,
    )

    assert infer_intent("我的账号怎么修改密码", {}) == "account_support"
    assert should_create_ticket("account_support", "我的账号怎么修改密码") is False
    assert infer_intent("账号登录后余额不对", {}) == "account_support"
    assert infer_intent(DEFECT, {}) == "product_issue"
    assert resolve_triage_lane("product_issue") == "product_defect"
    assert resolve_triage_lane("account_support") == "ultimate_review"
    from modstore_server.customer_service_orchestrator import TRIAGE_LANES

    assert "ops_fast_fix" in TRIAGE_LANES
    assert infer_intent("工单列表按提交账号筛选的功能问题", {}) == "product_issue"


def _chat(client, user, message):
    from modstore_server import customer_service_api
    from modstore_server.app import app

    app.dependency_overrides[customer_service_api._get_current_user] = lambda: user
    try:
        r = client.post(f"{BASE}/chat", json={"message": message, "context": {}})
        assert r.status_code == 200, r.text
        return r.json()
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)


def test_pure_account_help_chats_without_ticket(client, monkeypatch):
    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    data = _chat(client, _make_user("acct_help"), "我的账号怎么换绑手机号")
    assert data["ticket"] is None
    assert data["intent"]["intent"] == "account_support"
    assert data["intent"]["triage_lane"] == "ultimate_review"


def test_defect_with_account_word_and_escalation_creates_ticket(client, monkeypatch):
    from modstore_server import customer_service_api
    from modstore_server.app import app

    monkeypatch.setenv("MODSTORE_CS_LLM_INTENT", "0")
    owner, other = _make_user("acct_defect"), _make_user("acct_other")
    data = _chat(client, owner, DEFECT)
    assert data["intent"]["intent"] == "product_issue"
    assert data["intent"]["triage_lane"] == "product_defect"
    assert data["ticket"] is not None and data["ticket"]["intent"] == "product_issue"
    tid = data["ticket"]["id"]
    try:
        app.dependency_overrides[customer_service_api._get_current_user] = lambda: owner
        body = client.get(f"{BASE}/tickets/{tid}").json()
        assert body["ticket"]["id"] == tid
        assert not _keys(body) & INTERNAL_KEYS, _keys(body) & INTERNAL_KEYS
        app.dependency_overrides[customer_service_api._get_current_user] = lambda: other
        assert client.get(f"{BASE}/tickets/{tid}").status_code in {403, 404}
    finally:
        app.dependency_overrides.pop(customer_service_api._get_current_user, None)
