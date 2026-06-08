"""单测：butler_qq_bridge 的签名 / op=13 握手 / dispatch 入口。

跑：
    cd MODstore_deploy
    pytest tests/test_butler_qq_bridge.py -v

注意：依赖 pynacl；未安装时整个测试文件直接 skip。
"""

from __future__ import annotations

import importlib
import json
import os

import pytest

pytest.importorskip("nacl", reason="butler_qq_bridge 需要 pynacl；pip install pynacl 后再跑")


@pytest.fixture()
def bridge(monkeypatch):
    """配齐 env 后再 import 模块——这样 _ensure_runtime_ready 才会让 router 生效。"""
    monkeypatch.setenv("BUTLER_QQ_APP_ID", "1903977125")
    monkeypatch.setenv("BUTLER_QQ_APP_SECRET", "kRwFMH0WqvkJdhV4")
    monkeypatch.setenv("BUTLER_QQ_BOT_TOKEN", "0bDpS5jN2hN3kR9sbL5qbN9wjXLAzpfW")
    monkeypatch.setenv("BUTLER_QQ_SANDBOX", "1")
    # 让 /push 测试能拿到 admin token
    monkeypatch.setenv("MODSTORE_ADMIN_RECHARGE_TOKEN", "test-admin-token")

    if "modstore_server.butler_qq_bridge" in list(os.sys.modules):
        del os.sys.modules["modstore_server.butler_qq_bridge"]
    mod = importlib.import_module("modstore_server.butler_qq_bridge")
    return mod


def test_is_configured(bridge):
    assert bridge.is_configured() is True
    assert bridge._qq_api_base().endswith("sandbox.api.sgroup.qq.com")


def test_signature_roundtrip(bridge):
    """对 (event_ts + plain_token) 签名后，verify_key 必须能验证通过。"""
    payload = b"1700000000plain_token_demo"
    sig = bridge.sign_payload(payload)
    assert len(sig) == 64

    verify_key = bridge._signing_key().verify_key
    verify_key.verify(payload, sig)  # 不抛异常即通过


def test_verify_inbound_accepts_self_signed(bridge):
    body = json.dumps({"hello": "world"}, ensure_ascii=False).encode("utf-8")
    timestamp = "1700000123"
    sig = bridge.sign_payload(timestamp.encode("utf-8") + body).hex()

    assert bridge.verify_inbound(timestamp, body, sig) is True
    # 篡改 body 必须失败
    assert bridge.verify_inbound(timestamp, body + b"!", sig) is False
    # 错误的 hex 必须失败而不是抛
    assert bridge.verify_inbound(timestamp, body, "deadbeef") is False
    assert bridge.verify_inbound(timestamp, body, "not-hex") is False


def test_strip_at(bridge):
    assert bridge._strip_at("  <@!12345> 你好") == "你好"
    assert bridge._strip_at("<@bot> hi") == "hi"
    assert bridge._strip_at("没有 mention") == "没有 mention"


def test_extract_target_id(bridge):
    assert bridge._extract_target_id("group", {"group_openid": "G1"}) == "G1"
    assert bridge._extract_target_id("c2c", {"author": {"user_openid": "U1"}}) == "U1"
    assert bridge._extract_target_id("channel", {"channel_id": "C1"}) == "C1"
    assert bridge._extract_target_id("group", {}) == ""


def test_op13_challenge_endpoint(bridge):
    """op=13 不带签名头，必须用 Ed25519 私钥签 (event_ts + plain_token) 并原样返回。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(bridge.router)
    client = TestClient(app)

    body = {"op": 13, "d": {"plain_token": "abc123", "event_ts": "1700000999"}}
    r = client.post("/api/agent/butler/qq/webhook", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["plain_token"] == "abc123"

    # 服务端返回的 hex 签名必须能用同一对 verify_key 验证
    sig = bytes.fromhex(out["signature"])
    bridge._signing_key().verify_key.verify(b"1700000999abc123", sig)


def test_inbound_event_requires_signature(bridge):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(bridge.router)
    client = TestClient(app)

    body = {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "d": {"content": "hi"}}
    r = client.post("/api/agent/butler/qq/webhook", json=body)
    assert r.status_code == 401  # 缺签名头


def test_inbound_event_with_valid_signature_dispatches(bridge, monkeypatch):
    """合法签名的事件必须被 ack 200，且后台调度 dispatch_to_butler。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    captured: dict = {}

    async def fake_dispatch(event_type, payload):
        captured["event_type"] = event_type
        captured["payload"] = payload

    monkeypatch.setattr(bridge, "dispatch_to_butler", fake_dispatch)

    app = FastAPI()
    app.include_router(bridge.router)
    client = TestClient(app)

    body_obj = {
        "op": 0,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {"content": "<@!1> 你好", "group_openid": "G1", "id": "MSG1"},
    }
    body_bytes = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
    timestamp = "1700001000"
    sig = bridge.sign_payload(timestamp.encode("utf-8") + body_bytes).hex()

    r = client.post(
        "/api/agent/butler/qq/webhook",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Signature-Ed25519": sig,
            "X-Signature-Timestamp": timestamp,
        },
    )
    assert r.status_code == 200, r.text


def test_status_endpoint(bridge):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(bridge.router)
    client = TestClient(app)

    r = client.get("/api/agent/butler/qq/status")
    assert r.status_code == 200
    data = r.json()
    assert data["configured"] is True
    assert data["sandbox"] is True
    assert data["app_id"] == "1903977125"


def test_resolve_llm_prefers_own_brain(monkeypatch, bridge):
    """配了 BUTLER_QQ_LLM_* 时，数字管家不再去问 db，直接用自己的钥匙。"""
    monkeypatch.setenv("BUTLER_QQ_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("BUTLER_QQ_LLM_API_KEY", "sk-fake-butler-own")
    monkeypatch.setenv("BUTLER_QQ_LLM_MODEL", "deepseek-chat")

    import asyncio

    provider, model, api_key, base_url = asyncio.run(bridge._resolve_llm_for_butler())
    assert provider == "deepseek"
    assert model == "deepseek-chat"
    assert api_key == "sk-fake-butler-own"
    assert base_url is None


def test_resolve_llm_errors_if_nothing_configured(monkeypatch, bridge):
    """既没自持钥匙也没指 BRIDGE_USER_ID 时必须抱怨。"""
    monkeypatch.delenv("BUTLER_QQ_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("BUTLER_QQ_LLM_API_KEY", raising=False)
    monkeypatch.delenv("BUTLER_QQ_BRIDGE_USER_ID", raising=False)

    import asyncio

    with pytest.raises(RuntimeError, match="LLM 钥匙"):
        asyncio.run(bridge._resolve_llm_for_butler())


def test_status_reports_own_brain(monkeypatch, bridge):
    monkeypatch.setenv("BUTLER_QQ_LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("BUTLER_QQ_LLM_API_KEY", "sk-fake-butler-own")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(bridge.router)
    client = TestClient(app)

    r = client.get("/api/agent/butler/qq/status")
    assert r.status_code == 200
    data = r.json()
    assert data["has_own_brain"] is True
    assert data["own_brain_provider"] == "deepseek"


def test_push_requires_admin_token(bridge):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(bridge.router)
    client = TestClient(app)

    body = {"kind": "group", "target_id": "G1", "content": "hi"}
    # 缺令牌 → 403
    r = client.post("/api/agent/butler/qq/push", json=body)
    assert r.status_code == 403
    # 错令牌 → 403
    r = client.post(
        "/api/agent/butler/qq/push",
        json=body,
        headers={"X-Modstore-Recharge-Token": "wrong"},
    )
    assert r.status_code == 403


# ─── 一等公民 QQ 渠道：剩下两位老员工 + 通用 by-employee 入口 ──────────


def test_resolve_webhook_app_id_legacy_employees(bridge):
    """``task-router`` / ``employee-interview`` 两条历史 URL 必须直接映射到
    各自的 (app_id, employee_id)，不再返回空 employee_id。"""
    aid, eid = bridge._resolve_webhook_app_id("task-router")
    assert aid == "1903978019"
    assert eid == "task-router-officer"

    aid, eid = bridge._resolve_webhook_app_id("employee-interview")
    assert aid == "1903979052"
    assert eid == "employee-interview-assistant"


def test_resolve_webhook_app_id_unknown_returns_empty(bridge):
    aid, eid = bridge._resolve_webhook_app_id("not-an-employee")
    assert aid == ""
    assert eid == ""


def test_specific_app_secret_via_env(monkeypatch, bridge):
    """两位老员工的 AppSecret 优先从 ENV 读取，找不到才回落账号池。"""
    monkeypatch.setenv("TASK_ROUTER_QQ_APP_SECRET", "fake-secret-tr")
    monkeypatch.setenv("EMPLOYEE_INTERVIEW_QQ_APP_SECRET", "fake-secret-ei")

    assert bridge._specific_app_secret("task-router") == "fake-secret-tr"
    assert bridge._specific_app_secret("employee-interview") == "fake-secret-ei"
    assert bridge._specific_app_secret("never-existed") == ""


def test_specific_bot_token_via_env(monkeypatch, bridge):
    monkeypatch.setenv("TASK_ROUTER_QQ_BOT_TOKEN", "tok-tr")
    monkeypatch.setenv("EMPLOYEE_INTERVIEW_QQ_BOT_TOKEN", "tok-ei")
    assert bridge._specific_bot_token("task-router") == "tok-tr"
    assert bridge._specific_bot_token("employee-interview") == "tok-ei"
    assert bridge._specific_bot_token("nope") == ""


def test_all_known_app_secrets_always_merges_specific_from_env(monkeypatch, bridge):
    """老员工 AppSecret 必须通过 _specific_app_secret 写入映射，且优先生效。
    避免账号池里同名 app_id 留下旧值后 block 掉 ENV。
    """
    monkeypatch.setenv("TASK_ROUTER_QQ_APP_SECRET", "secret-tr-env")
    monkeypatch.setenv("EMPLOYEE_INTERVIEW_QQ_APP_SECRET", "secret-ei-env")
    m = bridge._all_known_app_secrets()
    assert m.get("1903978019") == "secret-tr-env"
    assert m.get("1903979052") == "secret-ei-env"


def test_status_lists_first_class_employees(bridge):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(bridge.router)
    client = TestClient(app)

    r = client.get("/api/agent/butler/qq/status")
    assert r.status_code == 200
    data = r.json()
    fc = data.get("first_class_employees") or []
    by_id = {row["employee_id"]: row for row in fc}
    assert "task-router-officer" in by_id
    assert "employee-interview-assistant" in by_id
    assert by_id["task-router-officer"]["webhook_path"].endswith("/task-router/webhook")
    assert by_id["task-router-officer"]["by_employee_path"].endswith(
        "/by-employee/task-router-officer/webhook"
    )
    assert by_id["task-router-officer"]["uses_executor"] is True
    assert by_id["task-router-officer"]["bot_token_env"] == "TASK_ROUTER_QQ_BOT_TOKEN"
    assert "bot_token_present" in by_id["task-router-officer"]


def test_legacy_specific_webhook_passes_employee_id_hint(bridge, monkeypatch):
    """命中 ``/task-router/webhook`` 的合法事件必须带 employee_id_hint 调度。

    用拦截 ``asyncio.create_task`` 的方式直接捕获参数，避免 TestClient
    收尾时事件循环已关闭、后台 task 还没机会执行的时序问题。
    """
    import asyncio

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv(
        "TASK_ROUTER_QQ_APP_SECRET", "kRwFMH0WqvkJdhV4"
    )  # 与默认 BotSecret 同串只为复用 sign_payload

    captured_args: list = []
    real_create_task = asyncio.create_task

    def spy_create_task(coro, *a, **kw):
        # dispatch_to_employee(...) 的协程对象，先 close 掉防 RuntimeWarning
        try:
            args = getattr(coro, "cr_frame", None)
            if args is not None:
                captured_args.append(dict(args.f_locals))
        finally:
            coro.close()

        async def _noop():
            return None

        return real_create_task(_noop())

    monkeypatch.setattr(bridge.asyncio, "create_task", spy_create_task)

    app = FastAPI()
    app.include_router(bridge.router)
    client = TestClient(app)

    body_obj = {
        "op": 0,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {"content": "<@!1> 路由测试", "group_openid": "G2", "id": "MSG2"},
    }
    body_bytes = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
    timestamp = "1700002000"
    sig = bridge.sign_payload(timestamp.encode("utf-8") + body_bytes).hex()

    r = client.post(
        "/api/agent/butler/qq/task-router/webhook",
        content=body_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Signature-Ed25519": sig,
            "X-Signature-Timestamp": timestamp,
        },
    )
    assert r.status_code == 200, r.text
    assert captured_args, "dispatch_to_employee 未被调度"
    locals_snapshot = captured_args[0]
    assert locals_snapshot.get("employee_id_hint") == "task-router-officer"
    assert locals_snapshot.get("app_id") == "1903978019"


def test_resolve_reply_uses_executor_for_non_butler(bridge, monkeypatch):
    """非管家员工必须先尝试 execute_employee_task 抽出回复文本。"""
    import asyncio

    captured: dict = {}

    def fake_execute(*, employee_id, task, input_data, user_id):
        captured["employee_id"] = employee_id
        captured["task"] = task
        return {
            "result": {
                "outputs": [{"handler": "echo", "output": "执行器回复 OK"}],
                "summary": "executed 1 handlers",
            },
            "reasoning_excerpt": "应当不会被用到",
        }

    class _FakeClient:
        def execute_task(self, **kw):
            return fake_execute(**kw)

    monkeypatch.setattr(
        "modstore_server.services.employee.get_default_employee_client",
        lambda: _FakeClient(),
    )

    reply = asyncio.run(bridge._resolve_reply("task-router-officer", "你好"))
    assert reply == "执行器回复 OK"
    assert captured["employee_id"] == "task-router-officer"
    assert captured["task"] == "你好"


def test_resolve_reply_falls_back_to_persona_if_executor_empty(bridge, monkeypatch):
    """执行器返回空文本时，必须回退到 _employee_chat 保命，不返回空字符串。"""
    import asyncio

    class _FakeClient:
        def execute_task(self, **kw):
            return {"result": {"outputs": [], "summary": ""}}

    monkeypatch.setattr(
        "modstore_server.services.employee.get_default_employee_client",
        lambda: _FakeClient(),
    )

    async def fake_persona(text, *, employee_id):
        return f"persona-fallback for {employee_id}: {text}"

    monkeypatch.setattr(bridge, "_employee_chat", fake_persona)

    reply = asyncio.run(bridge._resolve_reply("employee-interview-assistant", "汇报"))
    assert reply.startswith("persona-fallback for employee-interview-assistant")
