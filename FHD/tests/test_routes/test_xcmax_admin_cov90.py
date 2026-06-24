"""Targeted coverage for app.fastapi_routes.xcmax_admin missing arcs.

Focuses on previously-uncovered lines:
  - admin_list_wallets limit/offset proxy (588-590)
  - admin_set_user_profile success path: new-user creation + field setters
    (717-718, 744, 749, 751, 753, 755, 757)
  - admin_activate_enterprise_impersonation success + ValueError (952, 957-961)
  - local_self_maintenance_governance_review success + error (1101-1108)
  - local_employee_execute empty pid / approval keys / bad user_id
    (1199, 1209, 1213-1214)
  - get_digest_vibe_prep_session empty sid (1363)
  - ops_staffing_install_local non-dict result (1561)
  - ops_staffing_close_gap onboard JSONResponse early return + non-dict
    install result (1590, 1601, 1605)
  - sync_stream StreamingResponse (1827)
  - _xcmax_market_proxy_impl self-maintenance dispatch (1850)
  - _collect_codex_usage per-file open error (2048-2049)
  - _collect_trae_usage full body + read error (2066-2134)
  - _collect_mimo_usage (2168-2187)
  - _build_token_usage_summary aggregation (2190-2213)

All external deps (DB, network, subprocess, sqlite, modstore) are mocked;
tests are deterministic and offline.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

import app.fastapi_routes.xcmax_admin as admin_routes


@pytest.fixture
def app_with_router() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_routes.router)
    return app


@pytest.fixture
def client(app_with_router: FastAPI) -> TestClient:
    return TestClient(app_with_router, raise_server_exceptions=False)


def _admin_session_ok():
    return patch(
        "app.fastapi_routes.xcmax_admin._require_market_admin_session",
        return_value=None,
    )


def _mock_request(cookies: dict | None = None, headers: dict | None = None) -> MagicMock:
    req = MagicMock(spec=Request)
    req.cookies = cookies or {}
    req.headers = headers or {}
    return req


# ---------------------------------------------------------------------------
# admin_list_wallets — lines 588-590
# ---------------------------------------------------------------------------


class TestAdminListWallets:
    def test_default_limit_offset_proxied(self, client: TestClient):
        """No query params → default limit=500 offset=0 path forwarded."""
        captured: list[str] = []

        async def fake_proxy(request, method, path, **kw):
            captured.append(path)
            return {"items": [], "total": 0}

        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            side_effect=fake_proxy,
        ):
            resp = client.get("/api/xcmax/admin/market/wallets")
        assert resp.status_code == 200
        assert captured == ["/api/admin/wallets?limit=500&offset=0"]

    def test_custom_limit_offset_forwarded(self, client: TestClient):
        """limit/offset query params propagate verbatim into upstream path."""
        captured: list[str] = []

        async def fake_proxy(request, method, path, **kw):
            captured.append(path)
            return {"items": [{"id": 1}], "total": 1}

        with patch(
            "app.fastapi_routes.xcmax_admin._market_admin_proxy",
            side_effect=fake_proxy,
        ):
            resp = client.get("/api/xcmax/admin/market/wallets?limit=20&offset=40")
        assert resp.status_code == 200
        assert captured == ["/api/admin/wallets?limit=20&offset=40"]


# ---------------------------------------------------------------------------
# admin_set_user_profile success path — new user + field setters
# lines 717-718, 744, 749, 751, 753, 755, 757
# ---------------------------------------------------------------------------


def _make_db(user):
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    db.query.return_value.filter.return_value.first.return_value = user
    return db


class TestAdminSetUserProfileSuccess:
    def test_new_user_created_and_fields_set(self, client: TestClient):
        """user is None → User(...) added + flush (717-718); tier/industry/budget
        setters run (749, 751, 753); industry merged when not provided (744);
        entitled persisted (758-759)."""
        created_users: list[Any] = []

        class FakeUser:
            # class-level attr so `User.username == name` (filter expr) works
            username = None

            def __init__(self, **kw):
                self.username = kw.get("username", "")
                self.tier = ""
                self.industry_id = ""
                self.budget_range = ""
                self.account_tier = None
                self.entitled_industries = []
                created_users.append(self)

        db = _make_db(None)  # first() returns None → triggers new-user branch

        def fake_add(u):
            # emulate the row now being attached
            pass

        db.add.side_effect = fake_add

        with (
            _admin_session_ok(),
            patch("app.db.models.user.User", FakeUser),
            patch("app.db.session.get_db", return_value=db),
            patch(
                "app.application.account_tier_derivation.normalize_account_tier",
                return_value=None,
            ),
            patch(
                "app.application.account_tier_derivation.VALID_ACCOUNT_TIERS",
                {"normal", "pro"},
            ),
            patch(
                "app.application.account_tier_derivation.should_have_account_tier",
                return_value=False,
            ),
            patch(
                "app.application.entitled_industries_init.merge_entitled_industries",
                side_effect=lambda base, extra: list(dict.fromkeys([*base, *extra])),
            ),
            patch(
                "app.application.entitled_industries_init.validate_industry_in_entitled",
                return_value=True,
            ),
        ):
            resp = client.put(
                "/api/xcmax/admin/users/9/profile",
                json={
                    "username": "newbie",
                    "tier": "personal",
                    "industry_id": "餐饮",
                    "budget_range": "low",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        # field setters ran on the freshly created user
        assert created_users, "new User should have been created"
        u = created_users[0]
        assert u.tier == "personal"
        assert u.industry_id == "餐饮"
        assert u.budget_range == "low"
        # industry_id merged into entitled when entitled not explicitly provided (744)
        assert "餐饮" in u.entitled_industries
        db.add.assert_called_once()
        db.flush.assert_called_once()
        db.commit.assert_called_once()
        assert body["data"]["industry_id"] == "餐饮"

    def test_account_tier_set_for_enterprise(self, client: TestClient):
        """norm_account_tier not None + enterprise → user.account_tier assigned (755)."""
        user = MagicMock()
        user.tier = "enterprise"
        user.industry_id = ""
        user.budget_range = ""
        user.account_tier = None
        user.entitled_industries = ["通用"]
        db = _make_db(user)

        with (
            _admin_session_ok(),
            patch("app.db.session.get_db", return_value=db),
            patch(
                "app.application.account_tier_derivation.normalize_account_tier",
                return_value="pro",
            ),
            patch(
                "app.application.account_tier_derivation.VALID_ACCOUNT_TIERS",
                {"normal", "pro"},
            ),
            patch(
                "app.application.account_tier_derivation.should_have_account_tier",
                return_value=True,
            ),
            patch(
                "app.application.entitled_industries_init.merge_entitled_industries",
                side_effect=lambda base, extra: list(dict.fromkeys([*base, *extra])),
            ),
            patch(
                "app.application.entitled_industries_init.validate_industry_in_entitled",
                return_value=True,
            ),
        ):
            resp = client.put(
                "/api/xcmax/admin/users/3/profile",
                json={"username": "ent", "tier": "enterprise", "account_tier": "pro"},
            )
        assert resp.status_code == 200
        # account_tier setter (line 755) executed
        assert user.account_tier == "pro"

    def test_account_tier_cleared_for_non_enterprise(self, client: TestClient):
        """norm None + final tier not enterprise → user.account_tier = None (757)."""
        user = MagicMock()
        user.tier = "personal"
        user.industry_id = ""
        user.budget_range = ""
        user.account_tier = "pro"  # stale value should be cleared
        user.entitled_industries = []
        db = _make_db(user)

        with (
            _admin_session_ok(),
            patch("app.db.session.get_db", return_value=db),
            patch(
                "app.application.account_tier_derivation.normalize_account_tier",
                return_value=None,
            ),
            patch(
                "app.application.account_tier_derivation.VALID_ACCOUNT_TIERS",
                {"normal", "pro"},
            ),
            patch(
                "app.application.account_tier_derivation.should_have_account_tier",
                return_value=False,
            ),
            patch(
                "app.application.entitled_industries_init.merge_entitled_industries",
                side_effect=lambda base, extra: list(dict.fromkeys([*base, *extra])),
            ),
            patch(
                "app.application.entitled_industries_init.validate_industry_in_entitled",
                return_value=True,
            ),
        ):
            resp = client.put(
                "/api/xcmax/admin/users/4/profile",
                json={"username": "person"},
            )
        assert resp.status_code == 200
        # line 757: account_tier reset to None for non-enterprise
        assert user.account_tier is None


# ---------------------------------------------------------------------------
# admin_activate_enterprise_impersonation — lines 944-961
# ---------------------------------------------------------------------------


class TestActivateEnterpriseImpersonation:
    def test_missing_token_400(self, client: TestClient):
        """Lines 944-946: no bridge_token → 400."""
        resp = client.post("/api/xcmax/admin/impersonate/activate-enterprise", json={})
        assert resp.status_code == 400
        assert "bridge_token" in resp.json()["message"]

    def test_invalid_token_400(self, client: TestClient):
        """Lines 947-951: consume returns falsy → 400."""
        with patch(
            "app.application.impersonation_bridge.consume_impersonation_bridge_token",
            return_value="",
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate/activate-enterprise",
                json={"bridge_token": "bad"},
            )
        assert resp.status_code == 400
        assert "无效" in resp.json()["message"]

    def test_success_returns_session_id(self, client: TestClient):
        """Lines 952-961: valid token + mirror succeeds → success with session_id.

        Covers reading enterprise_session_id from body (952) and the mirror
        call (957-958, 961)."""
        with (
            patch(
                "app.application.impersonation_bridge.consume_impersonation_bridge_token",
                return_value="admin-sid",
            ),
            patch(
                "app.application.impersonation_bridge."
                "mirror_admin_impersonation_to_enterprise_session",
                return_value="ent-sid-99",
            ) as mock_mirror,
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate/activate-enterprise",
                json={"bridge_token": "good", "enterprise_session_id": "from-body"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["session_id"] == "ent-sid-99"
        # enterprise_sid from body forwarded to mirror
        mock_mirror.assert_called_once_with("admin-sid", "from-body")

    def test_mirror_value_error_400(self, client: TestClient):
        """Lines 959-960: mirror raises ValueError → 400 with message."""
        with (
            patch(
                "app.application.impersonation_bridge.consume_impersonation_bridge_token",
                return_value="admin-sid",
            ),
            patch(
                "app.application.impersonation_bridge."
                "mirror_admin_impersonation_to_enterprise_session",
                side_effect=ValueError("no enterprise session"),
            ),
        ):
            resp = client.post(
                "/api/xcmax/admin/impersonate/activate-enterprise",
                json={"bridge_token": "good"},
            )
        assert resp.status_code == 400
        assert resp.json()["message"] == "no enterprise session"


# ---------------------------------------------------------------------------
# local_self_maintenance_governance_review — lines 1101-1108
# ---------------------------------------------------------------------------


class TestLocalGovernanceReview:
    def test_success(self, client: TestClient):
        """Lines 1101-1106: session present → governance_review_local result returned."""
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid",
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="Bearer tok",
            ),
            patch(
                "app.application.self_maintenance_app_service.governance_review_local",
                new=AsyncMock(return_value={"success": True, "reviewed": True}),
            ) as mock_review,
        ):
            resp = client.post(
                "/api/xcmax/local/ops/self-maintenance/governance-review",
                json={"note": "all good"},
            )
        assert resp.status_code == 200
        assert resp.json()["reviewed"] is True
        _, kwargs = mock_review.call_args
        assert kwargs["note"] == "all good"
        assert kwargs["authorization"] == "Bearer tok"

    def test_error_returns_502(self, client: TestClient):
        """Lines 1107-1108: service raises RECOVERABLE_ERRORS → 502."""
        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid",
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="tok",
            ),
            patch(
                "app.application.self_maintenance_app_service.governance_review_local",
                new=AsyncMock(side_effect=RuntimeError("loop down")),
            ),
        ):
            resp = client.post(
                "/api/xcmax/local/ops/self-maintenance/governance-review",
                json={},
            )
        assert resp.status_code == 502
        assert "loop down" in resp.json()["message"]


# ---------------------------------------------------------------------------
# local_employee_execute — lines 1199, 1209, 1213-1214
# ---------------------------------------------------------------------------


class TestLocalEmployeeExecute:
    def test_empty_pid_400(self, client: TestClient):
        """Line 1199: blank employee_id (whitespace) → 400."""
        with patch(
            "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
            return_value="sid",
        ):
            resp = client.post(
                "/api/xcmax/local/employees/%20%20/execute",
                json={"task": "run"},
            )
        assert resp.status_code == 400
        assert resp.json()["message"] == "employee_id 必填"

    def test_approval_keys_copied_and_bad_user_id(self, client: TestClient):
        """Lines 1209: approval keys promoted from body into payload;
        1213-1214: non-int user_id → 0."""
        captured: dict[str, Any] = {}

        def fake_exec(pid, task, payload, **kw):
            captured["pid"] = pid
            captured["task"] = task
            captured["payload"] = payload
            captured["user_id"] = kw.get("user_id")
            return {"success": True, "output": "ok"}

        with (
            patch(
                "app.fastapi_routes.domains.misc.helpers._session_id_from_request",
                return_value="sid",
            ),
            patch(
                "app.application.employee_runtime.executor.execute_employee_task_local",
                side_effect=fake_exec,
            ),
        ):
            resp = client.post(
                "/api/xcmax/local/employees/emp1/execute",
                json={
                    "task": "do_thing",
                    "approved_write": True,
                    "write_token": "wt-1",
                    "user_id": "not-int",
                },
            )
        assert resp.status_code == 200
        # approval keys promoted into payload (line 1208-1209)
        assert captured["payload"]["approved_write"] is True
        assert captured["payload"]["write_token"] == "wt-1"
        assert captured["payload"]["trigger"] == "admin_execute"
        # bad user_id coerced to 0 (1213-1214)
        assert captured["user_id"] == 0


# ---------------------------------------------------------------------------
# get_digest_vibe_prep_session empty sid — line 1363
# ---------------------------------------------------------------------------


class TestDigestVibePrepEmptySid:
    @pytest.mark.asyncio
    async def test_non_alnum_sid_400(self):
        """Line 1363: session_id with only non-alphanumeric chars sanitizes to
        empty → 400. Called directly because the route path requires a non-empty
        segment."""
        req = _mock_request()
        with _admin_session_ok():
            result = await admin_routes.get_digest_vibe_prep_session(req, "!!!---///")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400


# ---------------------------------------------------------------------------
# ops_staffing_install_local non-dict result — line 1561
# ---------------------------------------------------------------------------


class TestInstallLocalNonDictResult:
    def test_non_dict_non_model_result(self, client: TestClient):
        """Line 1561: _install_from_catalog returns a plain object (no model_dump,
        not a dict) → wrapped as {"result": str(result)}."""
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value="installed-ok"),
            ),
        ):
            resp = client.post(
                "/api/xcmax/ops/staffing/install-local",
                json={"employee_id": "e1"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == {"result": "installed-ok"}
        # success defaults True since data has no 'success' key
        assert body["success"] is True


# ---------------------------------------------------------------------------
# ops_staffing_close_gap — lines 1590, 1601, 1605
# ---------------------------------------------------------------------------


class TestCloseGapBranches:
    def test_onboard_jsonresponse_early_return(self, client: TestClient):
        """Line 1589-1590: onboard proxy returns JSONResponse → returned directly."""
        onboard_err = JSONResponse({"success": False, "message": "onboard fail"}, status_code=502)
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={"healthy": True}),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "missing_remote_employees": ["e1"],
                    "missing_local_employee_packs": [],
                },
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value=onboard_err),
            ),
        ):
            resp = client.post("/api/xcmax/ops/staffing/close-gap", json={})
        assert resp.status_code == 502
        assert resp.json()["message"] == "onboard fail"

    def test_install_non_dict_result_in_loop(self, client: TestClient):
        """Line 1605: install returns plain object → data = {"result": str(result)};
        loop records the install with that data."""
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={"healthy": True}),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "missing_remote_employees": [],
                    "missing_local_employee_packs": ["epkg"],
                },
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value="raw-string-result"),
            ),
        ):
            resp = client.post("/api/xcmax/ops/staffing/close-gap", json={})
        assert resp.status_code == 200
        body = resp.json()
        installs = body["data"]["install_results"]
        assert len(installs) == 1
        # data.get("success", True) defaults to True for the str-wrapped dict
        assert installs[0]["employee_id"] == "epkg"
        assert installs[0]["success"] is True

    def test_install_model_dump_result_in_loop(self, client: TestClient):
        """Line 1601: install result with model_dump() → data from model_dump."""
        model = MagicMock()
        model.model_dump.return_value = {"success": False, "message": "denied"}
        with (
            _admin_session_ok(),
            patch(
                "app.fastapi_routes.xcmax_admin._remote_duty_health",
                new=AsyncMock(return_value={"healthy": True}),
            ),
            patch(
                "app.application.ops_closure_status.build_ops_closure_status",
                return_value={
                    "missing_remote_employees": [],
                    "missing_local_employee_packs": ["epkg"],
                },
            ),
            patch(
                "app.fastapi_routes.mod_store_routes._install_from_catalog",
                new=AsyncMock(return_value=model),
            ),
        ):
            resp = client.post("/api/xcmax/ops/staffing/close-gap", json={})
        assert resp.status_code == 200
        installs = resp.json()["data"]["install_results"]
        assert installs[0]["success"] is False
        assert installs[0]["message"] == "denied"
        model.model_dump.assert_called_once()


# ---------------------------------------------------------------------------
# sync_stream — line 1827
# ---------------------------------------------------------------------------


class TestSyncStream:
    @pytest.mark.asyncio
    async def test_returns_streaming_response(self):
        """Line 1827: sync_stream returns a text/event-stream StreamingResponse."""
        req = _mock_request()
        with patch(
            "app.fastapi_routes.xcmax_admin._sync_sse_generator",
            return_value=iter([]),
        ):
            resp = await admin_routes.sync_stream(req, since_cursor=0)
        assert isinstance(resp, StreamingResponse)
        assert resp.media_type == "text/event-stream"
        assert resp.headers["Cache-Control"] == "no-cache"
        assert resp.headers["X-Accel-Buffering"] == "no"


# ---------------------------------------------------------------------------
# _xcmax_market_proxy_impl self-maintenance dispatch — line 1850
# ---------------------------------------------------------------------------


class TestMarketProxyImplSelfMaintenance:
    @pytest.mark.asyncio
    async def test_self_maintenance_path_dispatches_to_helper(self):
        """Lines 1849-1850: subpath under ops/self-maintenance/ → routed through
        _self_maintenance_local_or_proxy instead of plain proxy."""
        req = _mock_request()
        req.method = "GET"
        req.json = AsyncMock(return_value={})
        sentinel = {"routed": "self-maintenance"}
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._self_maintenance_local_or_proxy",
                new=AsyncMock(return_value=sentinel),
            ) as mock_sm,
            patch(
                "app.fastapi_routes.xcmax_admin._market_admin_proxy",
                new=AsyncMock(return_value={"plain": True}),
            ) as mock_plain,
        ):
            result = await admin_routes._xcmax_market_proxy_impl(req, "ops/self-maintenance/status")
        assert result == sentinel
        mock_sm.assert_awaited_once()
        mock_plain.assert_not_called()


# ---------------------------------------------------------------------------
# _collect_codex_usage per-file open error — lines 2048-2049
# ---------------------------------------------------------------------------


class TestCollectCodexFileError:
    def test_unreadable_file_skipped(self, tmp_path):
        """Lines 2048-2049: open() raising a recoverable error → continue,
        file contributes no tokens but does not crash collection."""
        archived = tmp_path / "archived_sessions"
        archived.mkdir()
        (archived / "broken.jsonl").write_text("ignored")

        real_open = open

        def boom_open(path, *args, **kwargs):
            if str(path).endswith("broken.jsonl"):
                raise OSError("permission denied")
            return real_open(path, *args, **kwargs)

        with (
            patch("os.path.expanduser", return_value=str(archived)),
            patch("builtins.open", side_effect=boom_open),
        ):
            result = admin_routes._collect_codex_usage()
        assert result["available"] is True
        assert result["jsonl_files"] == 1
        assert result["sessions_with_tokens"] == 0
        assert result["total_tokens"] == 0


# ---------------------------------------------------------------------------
# _collect_trae_usage — lines 2066-2134
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Minimal sqlite cursor stub driven by a queue of fetch results."""

    def __init__(self, fetchall_rows, fetchone_queue):
        self._fetchall = fetchall_rows
        self._fetchone_queue = list(fetchone_queue)
        self._last = None

    def execute(self, sql):
        self._last = sql
        return self

    def fetchall(self):
        return self._fetchall

    def fetchone(self):
        if self._fetchone_queue:
            return self._fetchone_queue.pop(0)
        return None


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


class TestCollectTraeUsage:
    def test_full_parse_with_turns_and_models(self):
        """Lines 2075-2134: state.vscdb exists, accumulatedTurns summed,
        globalModelMap + model_list_map parsed, estimates computed."""
        import json as _json

        cursor = _FakeCursor(
            fetchall_rows=[
                ("ai.chat.feedback.s1.accumulatedTurns", "3"),
                ("ai.chat.feedback.s2.accumulatedTurns", "2"),
            ],
            fetchone_queue=[
                (_json.dumps({"s1": "glm-5.1"}),),  # globalModelMap
                (_json.dumps({"chat": ["m1", "m2"], "agent": ["m3"]}),),  # model_list_map
            ],
        )
        conn = _FakeConn(cursor)
        with (
            patch("os.path.expanduser", return_value="/fake/state.vscdb"),
            patch("os.path.exists", return_value=True),
            patch("sqlite3.connect", return_value=conn),
        ):
            result = admin_routes._collect_trae_usage()
        assert result["available"] is True
        assert result["total_chat_turns"] == 5
        assert result["estimated"] is True
        # 5 turns × 10_500_000 tokens/turn
        assert result["prompt_tokens"] == 5 * 10_000_000
        assert result["completion_tokens"] == 5 * 500_000
        assert result["total_tokens"] == 5 * 10_500_000
        # 3 models across two modes (2104-2106)
        assert result["available_models_count"] == 3
        assert result["current_models"] == {"s1": "glm-5.1"}

    def test_bad_model_json_ignored(self):
        """Lines 2096-2097 + 2107-2108: malformed JSON in model rows is swallowed,
        current_models stays None, available_models_count stays 0."""
        cursor = _FakeCursor(
            fetchall_rows=[("ai.chat.feedback.s1.accumulatedTurns", "1")],
            fetchone_queue=[("not-json",), ("also-not-json",)],
        )
        conn = _FakeConn(cursor)
        with (
            patch("os.path.expanduser", return_value="/fake/state.vscdb"),
            patch("os.path.exists", return_value=True),
            patch("sqlite3.connect", return_value=conn),
        ):
            result = admin_routes._collect_trae_usage()
        assert result["available"] is True
        assert result["total_chat_turns"] == 1
        assert result["current_models"] is None
        assert result["available_models_count"] == 0

    def test_sqlite_error_returns_unavailable(self):
        """Lines 2110-2111: sqlite3.connect raising → available False with reason."""
        with (
            patch("os.path.expanduser", return_value="/fake/state.vscdb"),
            patch("os.path.exists", return_value=True),
            patch("sqlite3.connect", side_effect=RuntimeError("db locked")),
        ):
            result = admin_routes._collect_trae_usage()
        assert result["available"] is False
        assert "读取 state.vscdb 失败" in result["reason"]


# ---------------------------------------------------------------------------
# _collect_mimo_usage — lines 2168-2187
# ---------------------------------------------------------------------------


class TestCollectMimoUsage:
    def test_returns_static_credits(self):
        """Lines 2171-2187: static mimo data with computed usage_percent."""
        result = admin_routes._collect_mimo_usage()
        assert result["available"] is True
        assert result["credits_used"] == 22_070_888_859
        assert result["credits_quota"] == 38_000_000_000
        assert result["total_tokens"] == 80_621_905
        # usage_percent = round(22070888859 / 38000000000 * 100, 1)
        assert result["usage_percent"] == pytest.approx(58.1, abs=0.05)
        assert result["estimated"] is True
        assert result["prompt_tokens"] == 0


# ---------------------------------------------------------------------------
# _build_token_usage_summary — lines 2190-2213
# ---------------------------------------------------------------------------


class TestBuildTokenUsageSummary:
    def test_aggregates_all_sources(self):
        """Lines 2192-2213: aggregates 5 collectors, attaches cost, sums grand totals."""
        with (
            patch(
                "app.fastapi_routes.xcmax_admin._collect_local_ledger",
                return_value={
                    "available": True,
                    "total_tokens": 100,
                    "prompt_tokens": 60,
                    "completion_tokens": 40,
                    "cost_units": 200,
                },
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_cursor_usage",
                return_value={
                    "available": True,
                    "total_tokens": 50,
                    "prompt_tokens": 30,
                    "completion_tokens": 20,
                    "cost_cents": 150,
                },
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_codex_usage",
                return_value={"available": False, "reason": "no dir"},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_trae_usage",
                return_value={"available": False, "reason": "no db"},
            ),
            patch(
                "app.fastapi_routes.xcmax_admin._collect_mimo_usage",
                return_value={
                    "available": True,
                    "total_tokens": 80,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                },
            ),
            patch("time.strftime", return_value="2026-06-24 12:00:00"),
        ):
            result = admin_routes._build_token_usage_summary()

        assert result["success"] is True
        # grand totals: 100 + 50 + 0 + 0 + 80
        assert result["grand_total_tokens"] == 230
        assert result["grand_prompt_tokens"] == 90
        assert result["grand_completion_tokens"] == 60
        # every source got an estimated_cost_usd injected (2199-2200)
        for src in result["sources"].values():
            assert "estimated_cost_usd" in src
        # local cost 200/100 = 2.0; cursor 150/100 = 1.5; mimo 0 → grand 3.5
        assert result["grand_cost_usd"] == pytest.approx(3.5)
        assert result["collected_at"] == "2026-06-24 12:00:00"
        assert result["sources"]["codex"]["available"] is False
