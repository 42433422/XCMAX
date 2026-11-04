"""
测试 AI 数字管家 Butler API。

运行：
    cd MODstore_deploy
    pytest tests/test_agent_butler_api.py -v
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, create_autospec, patch

import pytest
from fastapi.testclient import TestClient

# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def app():
    """创建 FastAPI app 实例（跳过数据库迁移，仅注册路由）。"""
    from fastapi import FastAPI

    from modstore_server.agent_butler_api import router

    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app)


@pytest.fixture()
def mock_user():
    user = MagicMock()
    user.id = 42
    user.is_admin = False
    user.default_llm_json = json.dumps({"provider": "openai", "model": "gpt-4o-mini"})
    return user


@pytest.fixture()
def mock_db():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.add = MagicMock()
    db.commit = MagicMock()
    db.flush = MagicMock()
    return db


# ─── Helper ────────────────────────────────────────────────────────


def _auth_overrides(app, mock_user, mock_db):
    from modstore_server.api.deps import _get_current_user
    from modstore_server.infrastructure.db import get_db

    app.dependency_overrides[_get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    return app


@pytest.mark.parametrize(
    "stream,failed,byok,reported_usage",
    [
        pytest.param(
            stream,
            failed,
            byok,
            True,
            id=f"{'stream' if stream else 'chat'}-{'release' if failed else 'settle'}-{'byok' if byok else 'platform'}",
        )
        for stream in (False, True)
        for failed in (False, True)
        for byok in (False, True)
    ]
    + [
        pytest.param(True, False, False, False, id="stream-estimated-full-text"),
        pytest.param(True, "interrupted", False, True, id="stream-interrupted"),
    ],
)
def test_butler_wallet_contract(
    monkeypatch, mock_user, mock_db, stream, failed, byok, reported_usage
):
    from fastapi import HTTPException, Request

    from modstore_server import agent_butler_api as butler
    from modstore_server.llm_billing_values import UsageMeter
    from modstore_server.llm_wallet_client import JavaWalletClient

    monkeypatch.setenv("PAYMENT_BACKEND", "java")
    wallet = JavaWalletClient()
    wallet._post = AsyncMock(return_value={"hold": {"hold_no": "test-hold", "amount": "0.05"}})
    monkeypatch.setattr(butler, "JavaWalletClient", lambda: wallet)
    monkeypatch.setattr(
        butler,
        "_resolve_butler_credentials",
        lambda *_: (
            "test",
            "model",
            "key",
            "user_override" if byok else "platform",
            "",
        ),
    )
    messages = [
        {"role": "system", "content": "private context"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "controlled prompt"},
    ]
    monkeypatch.setattr(butler, "_build_messages", lambda *a, **kw: messages)
    monkeypatch.setattr(butler, "new_request_id", lambda: "test-request")
    monkeypatch.setattr(butler, "enforce_risk_limits", lambda *_: None)
    monkeypatch.setattr(butler, "estimate_preauthorization", lambda *_: Decimal("0.05"))
    charge_calculator = MagicMock(return_value=Decimal("0.02"))
    monkeypatch.setattr(butler, "calculate_charge", charge_calculator)
    expected_charge = 0.0 if byok else 0.02
    monkeypatch.setattr(butler, "_partition_butler_tool_calls", lambda *a, **kw: ([], ""))
    conversation = butler.ChatConversation(id=81, user_id=mock_user.id)
    mock_db.query.return_value.filter.return_value.first.return_value = conversation
    answer = "answer " * 8
    upstream = {"ok": True, "content": answer}
    if reported_usage:
        upstream["usage"] = {
            "prompt_tokens": 2,
            "completion_tokens": 1,
            "total_tokens": 3,
        }
    error = RuntimeError("controlled upstream failure")
    monkeypatch.setattr(
        butler,
        "chat_dispatch",
        AsyncMock(side_effect=error) if failed else AsyncMock(return_value=upstream),
    )

    async def chunks(
        provider,
        *,
        api_key,
        base_url,
        model,
        messages,
        max_tokens=None,
        tools=None,
        tool_choice=None,
    ):
        yield {"type": "delta", "delta": answer[:10]}
        yield {"type": "delta", "delta": answer[10:]}
        if upstream.get("usage"):
            yield {"type": "usage", "usage": upstream["usage"]}
        if failed == "interrupted":
            raise error
        if failed:
            yield {"type": "error", "error": str(error)}

    stream_dispatch = create_autospec(butler.chat_dispatch_stream, side_effect=chunks)
    monkeypatch.setattr(butler, "chat_dispatch_stream", stream_dispatch)
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer test-only")]})
    body = butler.ButlerChatDTO(messages=messages, conversation_id=81, max_tokens=16)

    async def invoke():
        if stream:
            response = await butler.butler_chat_stream(request, body, db=mock_db, user=mock_user)
            events = [
                json.loads(chunk.removeprefix("data: ").strip())
                async for chunk in response.body_iterator
            ]
            assert events[-1]["done"] is True
            assert sum(event.get("done") is True for event in events) == 1
            assert "".join(event.get("text", "") for event in events) == answer
            if failed:
                assert events[-1]["error"] == str(error)
                assert "conversation_id" not in events[-1]
                assert "charge_amount" not in events[-1]
            else:
                assert events[-1]["conversation_id"] == 81
                assert events[-1]["charge_amount"] == expected_charge
        elif failed:
            with pytest.raises(HTTPException) as caught:
                await butler.butler_chat(request, body, db=mock_db, user=mock_user)
            assert caught.value.status_code == 500
            assert str(error) in caught.value.detail
        else:
            result = await butler.butler_chat(request, body, db=mock_db, user=mock_user)
            assert result["conversation_id"] == 81
            assert result["charge_amount"] == expected_charge
            assert result["billed"] is (not byok)

    asyncio.run(invoke())
    if stream:
        stream_dispatch.assert_called_once_with(
            "test",
            api_key="key",
            base_url="",
            model="model",
            messages=messages,
            max_tokens=16,
        )
    else:
        stream_dispatch.assert_not_called()
    if byok:
        wallet._post.assert_not_awaited()
    else:
        assert wallet._post.await_count == 2
        preauth, final = [call.args for call in wallet._post.await_args_list]
        assert preauth == (
            "/api/wallet/ai/preauthorize",
            "Bearer test-only",
            {
                "amount": "0.05",
                "provider": "test",
                "model": "model",
                "request_id": "test-request",
                "idempotency_key": "test-request:preauth",
            },
        )
        assert final == (
            f"/api/wallet/ai/{'release' if failed else 'settle'}",
            "Bearer test-only",
            {
                "hold_no": "test-hold",
                **({"reason": str(error)} if failed else {"actual_amount": "0.02"}),
                "idempotency_key": f"test-request:{'release' if failed else 'settle'}",
            },
        )
    rows = [call.args[0] for call in mock_db.add.call_args_list]
    assert not any(isinstance(row, butler.ChatConversation) for row in rows)
    assistants = [
        row for row in rows if isinstance(row, butler.ChatMessage) and row.role == "assistant"
    ]
    assert len(assistants) == (0 if failed else 1)
    if assistants:
        assert assistants[0].content == answer
        assert assistants[0].conversation_id == 81
        assert assistants[0].charge_amount == expected_charge
    new_messages = [row for row in rows if isinstance(row, butler.ChatMessage)]
    assert [(row.role, row.content) for row in new_messages] == (
        [] if failed else [("user", "controlled prompt"), ("assistant", answer)]
    )
    assert all(row.conversation_id == 81 and row.user_id == mock_user.id for row in new_messages)
    logs = [row for row in rows if isinstance(row, butler.LlmCallLog)]
    assert len(logs) == 1
    assert logs[0].hold_no == ("byok-test-request" if byok else "test-hold")
    assert logs[0].status == ("failed" if failed else "success")
    if failed:
        charge_calculator.assert_not_called()
    else:
        expected_usage = (
            UsageMeter(2, 1, 3, estimated=False)
            if reported_usage
            else UsageMeter(16, 15, 31, estimated=True)
        )
        if byok:
            charge_calculator.assert_not_called()
        else:
            charge_calculator.assert_called_once_with(mock_db, "test", "model", expected_usage)
            assert isinstance(charge_calculator.call_args.args[-1], UsageMeter)
        assert json.loads(assistants[0].usage_json) == expected_usage.__dict__
        assert (
            logs[0].prompt_tokens,
            logs[0].completion_tokens,
            logs[0].total_tokens,
            logs[0].estimated,
        ) == (
            expected_usage.prompt_tokens,
            expected_usage.completion_tokens,
            expected_usage.total_tokens,
            expected_usage.estimated,
        )
        assert logs[0].charge_amount == expected_charge
    mock_db.commit.assert_called_once()


# ─── Tests: /actions ──────────────────────────────────────────────


class TestButlerActions:
    def test_record_action_ok(self, app, mock_user, mock_db):
        _auth_overrides(app, mock_user, mock_db)
        client = TestClient(app)
        resp = client.post(
            "/api/agent/butler/actions",
            json={
                "action": "navigate",
                "route": "/plans",
                "risk": "low",
                "status": "success",
            },
        )
        assert resp.status_code == 200
        assert resp.json().get("ok") is True

    def test_record_action_creates_db_entry(self, app, mock_user, mock_db):
        _auth_overrides(app, mock_user, mock_db)
        client = TestClient(app)
        client.post(
            "/api/agent/butler/actions",
            json={
                "action": "click",
                "route": "/wallet",
                "risk": "medium",
                "status": "success",
            },
        )
        # ButlerAction 应被添加
        mock_db.add.assert_called()
        mock_db.commit.assert_called()


# ─── Tests: /skills ───────────────────────────────────────────────


class TestButlerSkills:
    def test_list_skills_empty(self, app, mock_user, mock_db):
        _auth_overrides(app, mock_user, mock_db)
        client = TestClient(app)

        with (
            patch("modstore_server.agent_butler_api.db")
            if False
            else patch.object(
                mock_db.query.return_value.filter.return_value, "all", return_value=[]
            )
        ):
            resp = client.get("/api/agent/butler/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data

    def test_update_skill_requires_admin(self, app, mock_user, mock_db):
        mock_user.is_admin = False
        _auth_overrides(app, mock_user, mock_db)
        client = TestClient(app)
        resp = client.patch("/api/agent/butler/skills/1", json={"is_active": True})
        assert resp.status_code == 403

    def test_update_skill_ok_for_admin(self, app, mock_user, mock_db):
        mock_user.is_admin = True
        skill_mock = MagicMock()
        skill_mock.id = 1
        mock_db.query.return_value.filter.return_value.first.return_value = skill_mock
        _auth_overrides(app, mock_user, mock_db)
        client = TestClient(app)
        resp = client.patch("/api/agent/butler/skills/1", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json().get("ok") is True


# ─── Tests: /all-hands-report/sessions ─────────────────────────────


class TestAllHandsReportSession:
    def test_start_all_hands_session_requires_admin(self, app, mock_user, mock_db):
        mock_user.is_admin = False
        _auth_overrides(app, mock_user, mock_db)
        client = TestClient(app)
        resp = client.post("/api/agent/butler/all-hands-report/sessions", json={})
        assert resp.status_code == 403

    def test_start_all_hands_session_ok_for_admin(self, app, mock_user, mock_db):
        mock_user.is_admin = True
        _auth_overrides(app, mock_user, mock_db)
        client = TestClient(app)
        with patch(
            "modstore_server.agent_butler_api._run_all_hands_report_session",
            new=AsyncMock(return_value=None),
        ):
            resp = client.post(
                "/api/agent/butler/all-hands-report/sessions",
                json={"with_research": False, "max_employees": 2, "concurrency": 1},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("session_id"), str) and len(data["session_id"]) >= 16
        assert data.get("status") == "running"

    def test_run_all_hands_report_session_includes_meeting_minutes_email(self, monkeypatch):
        """后台会话结束时 artifact 含 meeting_minutes，并按早报收件人列表发信。"""
        monkeypatch.setenv("MODSTORE_DAILY_DIGEST_EMAIL", "boss@example.com,other@example.com")

        from modstore_server import agent_butler_api as ab
        from modstore_server.workbench_api import _SESSION_LOCK, WORKBENCH_SESSIONS

        sid = "0123456789abcdef01234567"

        fake_report = {
            "ok": True,
            "employees": [
                {
                    "employee_id": "p1",
                    "name": "A",
                    "status": "ok",
                    "report_markdown": "汇报摘要",
                },
            ],
            "summary": {
                "total": 1,
                "ok": 1,
                "error": 0,
                "bench_provider": "openai",
                "bench_model": "gpt-4o-mini",
                "user_question": "",
            },
            "synthesized_answer": None,
        }

        async def fake_build(**kwargs):
            return fake_report

        async def fake_minutes(*, report, user_id):
            return {
                "text": (
                    "会议摘要\n一、会议主题：单元测试\n二、会议主要内容：测\n"
                    "三、现存问题\n- 无\n四、后续工作计划\n- 无\n五、其他说明：无"
                ),
                "generated_at": "2026-01-01T00:00:00Z",
                "model": "openai/gpt-4o-mini",
                "error": "",
            }

        sent: list[str] = []

        def fake_send_html(to_email, subject, html_body):
            sent.append(to_email)
            assert "员工大会会议摘要" in subject or "会议摘要" in subject
            return {"delivered": True, "mode": "debug"}

        monkeypatch.setattr("modstore_server.all_hands_report.build_all_hands_report", fake_build)
        monkeypatch.setattr(
            "modstore_server.all_hands_report.synthesize_meeting_minutes", fake_minutes
        )
        monkeypatch.setattr("modstore_server.email_service.send_simple_html_email", fake_send_html)

        steps = ab._all_hands_session_steps(with_synthesize=False)

        async def exercise():
            async with _SESSION_LOCK:
                WORKBENCH_SESSIONS[sid] = {
                    "id": sid,
                    "user_id": 1,
                    "intent": "butler_all_hands_report",
                    "status": "running",
                    "steps": [dict(s) for s in steps],
                    "planning_record": {"progress": {}},
                    "artifact": None,
                    "error": None,
                    "validate_warnings": None,
                    "sandbox_report": None,
                    "script_result": None,
                }
            await ab._run_all_hands_report_session(
                sid,
                user_id=1,
                payload={"max_employees": 8, "concurrency": 2, "with_research": True},
            )
            async with _SESSION_LOCK:
                sess = WORKBENCH_SESSIONS.get(sid)
                assert sess is not None
                assert sess["status"] == "done"
                art = sess.get("artifact") or {}
                assert "会议摘要" in (art.get("meeting_minutes") or {}).get("text", "")
                mme = art.get("meeting_minutes_email") or {}
                assert mme.get("any_delivered") is True
                assert mme.get("recipients_count") == 2
                assert len(sent) == 2
                assert set(sent) == {"boss@example.com", "other@example.com"}
                WORKBENCH_SESSIONS.pop(sid, None)

        asyncio.run(exercise())


# ─── Tests: system prompt 注入 ─────────────────────────────────────


class TestButlerSystemPrompt:
    def test_butler_system_prompt_content(self):
        from modstore_server.agent_butler_api import BUTLER_SYSTEM_PROMPT

        assert "数字管家" in BUTLER_SYSTEM_PROMPT
        assert "低风险" in BUTLER_SYSTEM_PROMPT
        assert "高风险" in BUTLER_SYSTEM_PROMPT

    def test_butler_tools_has_navigate(self):
        from modstore_server.agent_butler_api import BUTLER_TOOLS

        tool_names = [t["function"]["name"] for t in BUTLER_TOOLS]
        assert "navigate" in tool_names
        assert "click" in tool_names
        assert "fill" in tool_names
        assert "read" in tool_names

    def test_admin_readonly_tools_merged_only_for_admin(self):
        from types import SimpleNamespace

        from modstore_server.agent_butler_api import (
            ADMIN_READONLY_TOOL_NAMES,
            _butler_tools_for_user,
        )

        admin = SimpleNamespace(is_admin=True)
        user = SimpleNamespace(is_admin=False)
        admin_names = {t["function"]["name"] for t in _butler_tools_for_user(admin)}
        user_names = {t["function"]["name"] for t in _butler_tools_for_user(user)}
        assert ADMIN_READONLY_TOOL_NAMES.issubset(admin_names)
        assert not (ADMIN_READONLY_TOOL_NAMES & user_names)

    def test_execute_readonly_rejects_non_admin(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from modstore_server.agent_butler_api import _execute_admin_readonly_tool

        user = SimpleNamespace(id=1, is_admin=False)
        out = _execute_admin_readonly_tool("get_my_account_snapshot", {}, user=user, db=MagicMock())
        assert "仅管理员" in out

    def test_execute_ops_update_brief_and_self_tickets(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from modstore_server.agent_butler_api import (
            _execute_admin_readonly_tool,
            _partition_butler_tool_calls,
        )

        admin = SimpleNamespace(
            id=42,
            username="boss",
            email="boss@x.com",
            is_admin=True,
            is_enterprise=False,
        )
        digest = SimpleNamespace(
            id=1,
            day="2026-07-21",
            subject="日更标题",
            body_text="今日更新了运维推送",
            meeting_minutes_html="",
            recipients_json="[]",
            delivery_json="[]",
            delivered=True,
            source="test",
            created_at=None,
            vibe_prep_meta_json="",
            vibe_prep_line_dispatch_json="",
            vibe_line_execute_json="",
            vibe_prep_updates_md="",
            vibe_prep_patches_md="",
            vibe_prep_pw_md="",
            vibe_prep_ps_md="",
            vibe_prep_app_md="",
            vibe_prep_sr_md="",
        )
        ticket = SimpleNamespace(
            id=9,
            session_id=1,
            ticket_no="T-1",
            assigned_admin_id=None,
            title="本人工单",
            intent="general",
            subject_type="",
            subject_id="",
            status="open",
            priority="normal",
            evidence_json="{}",
            summary="",
            decision_status="",
            automation_level="",
            user_id=42,
            created_at=None,
            updated_at=None,
            closed_at=None,
        )

        db = MagicMock()

        def _query(model):
            q = MagicMock()
            name = getattr(model, "__name__", str(model))
            if "DailyDigest" in name:
                q.order_by.return_value.limit.return_value.all.return_value = [digest]
            elif "Ticket" in name:
                # ensure filter chained and forced to self
                q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
                    ticket
                ]
            else:
                q.filter.return_value.order_by.return_value.first.return_value = None
                q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
            return q

        db.query.side_effect = _query

        with patch(
            "modstore_server.release_train.snapshot_public",
            return_value={
                "current": "1.0.0.0",
                "product_version": "1.0.0.0",
                "day_index": 1,
            },
        ):
            brief = _execute_admin_readonly_tool(
                "get_ops_update_brief", {"limit": 2}, user=admin, db=db
            )
        assert "运维更新" in brief
        assert "日更标题" in brief or "2026-07-21" in brief
        assert "1.0.0.0" in brief

        tickets = _execute_admin_readonly_tool("get_my_tickets", {"limit": 5}, user=admin, db=db)
        assert "T-1" in tickets
        assert "本人工单" in tickets

        page, readonly = _partition_butler_tool_calls(
            [
                {"name": "navigate", "args": {"route": "/wallet"}},
                {"name": "get_ops_update_brief", "args": {}},
            ],
            user=admin,
            db=db,
        )
        assert len(page) == 1 and page[0]["name"] == "navigate"
        assert "运维更新" in readonly

    def test_build_messages_injects_system(self):
        from modstore_server.agent_butler_api import (
            ButlerChatDTO,
            ButlerMessageDTO,
            _build_messages,
        )

        body = ButlerChatDTO(
            messages=[ButlerMessageDTO(role="user", content="你好")],
            page_context="当前页面: 首页",
        )
        msgs = _build_messages(body, body.page_context)
        assert msgs[0]["role"] == "system"
        assert "数字管家" in msgs[0]["content"]
        assert "当前页面: 首页" in msgs[0]["content"]
        assert any(m["role"] == "user" for m in msgs)


# ─── Tests: intake draft validation ───────────────────────────────


class TestIntakeDraftValidation:
    def test_validate_accepts_known_enums(self):
        from modstore_server.agent_butler_api import _validate_intake_draft

        draft = _validate_intake_draft(
            {
                "userRole": "业务或销售",
                "primaryGoal": "重复录入太累",
                "directions": ["少做表格单据", "invalid-dir", "上AI助手"],
                "timeline": "1 个月内",
                "needIntegration": "yes",
                "roleSummary": "跟单录入",
                "email": "not-an-email-but-kept-as-text",
            }
        )
        assert draft["userRole"] == "业务或销售"
        assert draft["primaryGoal"] == "重复录入太累"
        assert draft["directions"] == ["少做表格单据", "上AI助手"]
        assert draft["timeline"] == "1 个月内"
        assert draft["needIntegration"] == "yes"
        assert "invalid-dir" not in draft.get("directions", [])

    def test_validate_rejects_bad_enums(self):
        from modstore_server.agent_butler_api import _validate_intake_draft

        draft = _validate_intake_draft(
            {"userRole": "黑客", "primaryGoal": "随便写", "needIntegration": "maybe"}
        )
        assert "userRole" not in draft
        assert "primaryGoal" not in draft
        assert "needIntegration" not in draft


# ─── Tests: _safe_json ────────────────────────────────────────────


class TestSafeJson:
    def test_string_input(self):
        from modstore_server.agent_butler_api import _safe_json

        result = _safe_json('{"key": "val"}')
        assert result == {"key": "val"}

    def test_dict_input(self):
        from modstore_server.agent_butler_api import _safe_json

        result = _safe_json({"key": "val"})
        assert result == {"key": "val"}

    def test_invalid_json(self):
        from modstore_server.agent_butler_api import _safe_json

        result = _safe_json("invalid json {")
        assert result == {}


# ─── Tests: corp-chat credentials follow llm-ops runtime route ────


class TestResolveCorpCredentials:
    def test_prefers_platform_runtime_route_when_corp_unset(self, monkeypatch, mock_db):
        from modstore_server.agent_butler_api import _resolve_corp_credentials

        monkeypatch.delenv("BUTLER_CORP_PROVIDER", raising=False)
        monkeypatch.delenv("BUTLER_CORP_API_KEY", raising=False)
        monkeypatch.delenv("BUTLER_CORP_MODEL", raising=False)

        with (
            patch(
                "modstore_server.services.llm.resolve_platform_bench_llm",
                return_value=("minimax", "MiniMax-M2.7"),
            ),
            patch(
                "modstore_server.llm_key_resolver.platform_api_key",
                return_value="sk-minimax-ok",
            ),
            patch(
                "modstore_server.llm_key_resolver.platform_base_url",
                return_value="https://api.minimaxi.com",
            ),
        ):
            provider, model, api_key, base_url = _resolve_corp_credentials(mock_db)

        assert provider == "minimax"
        assert model == "MiniMax-M2.7"
        assert api_key == "sk-minimax-ok"
        assert base_url == "https://api.minimaxi.com"

    def test_explicit_corp_pin_beats_runtime_route(self, monkeypatch, mock_db):
        from modstore_server.agent_butler_api import _resolve_corp_credentials

        monkeypatch.setenv("BUTLER_CORP_PROVIDER", "deepseek")
        monkeypatch.setenv("BUTLER_CORP_API_KEY", "sk-corp-pin")
        monkeypatch.setenv("BUTLER_CORP_MODEL", "deepseek-chat")

        with patch(
            "modstore_server.services.llm.resolve_platform_bench_llm",
            return_value=("minimax", "MiniMax-M2.7"),
        ):
            provider, model, api_key, _base = _resolve_corp_credentials(mock_db)

        assert provider == "deepseek"
        assert model == "deepseek-chat"
        assert api_key == "sk-corp-pin"
