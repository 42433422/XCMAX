"""真实行为测试 (第二波)：app/services/user_cs_demand_form.py

聚焦未覆盖逻辑：
- _now_iso (line 18)
- apply_landing_submission_to_pipeline (51-76)：
  uid 无效抛 ValueError；正常落地 intake_form/erp_customer_name/submitted_at/
  landing_contact_id 各分支；company 缺失不写 erp；显式 submitted_at 透传；
  调用 set_pipeline_stage 与 save_pipeline 的副作用与返回值
- fetch_submission_by_audit_code (80-90)：code 过短抛 ValueError；正常返回 stub
- redeem_submission_by_audit_code (99-109)：串联 fetch + apply，组装 payload
- sync_intake_from_market_if_newer (118-154)：
  无 base 返回 None；HTTP >=400 返回 None；非 dict / 缺 submitted_at 返回 None；
  正常拉取并 apply；RECOVERABLE_ERRORS(网络异常) 降级返回 None

所有函数内 import 在真实模块路径处 patch；httpx/pipeline 全部 mock。离线确定性。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.user_cs_demand_form import (
    _now_iso,
    apply_landing_submission_to_pipeline,
    fetch_submission_by_audit_code,
    redeem_submission_by_audit_code,
    sync_intake_from_market_if_newer,
)

# ──────────────────────────────────────────────────────────────────────────────
# _now_iso  (line 18)
# ──────────────────────────────────────────────────────────────────────────────


class TestNowIso:
    def test_returns_parseable_utc_iso(self):
        out = _now_iso()
        assert isinstance(out, str)
        parsed = datetime.fromisoformat(out)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0


# ──────────────────────────────────────────────────────────────────────────────
# apply_landing_submission_to_pipeline  (51-76)
#   函数内 import: app.services.user_cs_pipeline.{load_pipeline,save_pipeline,
#                  set_pipeline_stage}
# ──────────────────────────────────────────────────────────────────────────────

_PIPE = "app.services.user_cs_pipeline"


class TestApplyLandingSubmissionToPipeline:
    def test_invalid_uid_raises(self):
        # uid <= 0 -> ValueError，且不触碰 pipeline
        with pytest.raises(ValueError, match="market_user_id"):
            apply_landing_submission_to_pipeline({"market_user_id": 0})

    def test_missing_uid_raises(self):
        with pytest.raises(ValueError, match="market_user_id"):
            apply_landing_submission_to_pipeline({})

    def test_full_payload_persists_intake_and_company(self):
        loaded = {"username": "alice"}
        staged = {"username": "alice", "stage": "intake_done"}
        saved = {"saved": True}
        with (
            patch(f"{_PIPE}.load_pipeline", return_value=loaded) as m_load,
            patch(f"{_PIPE}.set_pipeline_stage", return_value=staged) as m_stage,
            patch(f"{_PIPE}.save_pipeline", return_value=saved) as m_save,
        ):
            out = apply_landing_submission_to_pipeline(
                {
                    "market_user_id": "42",
                    "username": "alice",
                    "name": " Bob ",
                    "email": " b@x.io ",
                    "phone": " 123 ",
                    "company": " Acme ",
                    "message": " hi ",
                    "desktop_os": " win ",
                    "need_mobile": False,
                    "submitted_at": "2026-01-01T00:00:00+00:00",
                    "landing_contact_id": 7,
                }
            )
        assert out is saved
        # load_pipeline 收到 int uid 与 username
        m_load.assert_called_once_with(42, username="alice")
        # intake_form 各字段去空白；company 非空 -> erp_customer_name 写入；
        # landing_contact_id > 0 -> 写入；显式 submitted_at 透传
        assert loaded["intake_form"] == {
            "name": "Bob",
            "email": "b@x.io",
            "phone": "123",
            "company": "Acme",
            "message": "hi",
            "desktop_os": "win",
            "need_mobile": False,
        }
        assert loaded["erp_customer_name"] == "Acme"
        assert loaded["intake_submitted_at"] == "2026-01-01T00:00:00+00:00"
        assert loaded["landing_contact_id"] == 7
        # set_pipeline_stage 用 loaded 的 username
        m_stage.assert_called_once_with(42, "intake_done", username="alice", source="landing")
        # save_pipeline 保存的是 set_pipeline_stage 的返回值 (doc 被重新赋值)
        m_save.assert_called_once_with(staged)

    def test_no_company_skips_erp_and_no_contact_id(self):
        loaded: dict = {}
        with (
            patch(f"{_PIPE}.load_pipeline", return_value=loaded),
            patch(f"{_PIPE}.set_pipeline_stage", return_value=loaded),
            patch(f"{_PIPE}.save_pipeline", side_effect=lambda d: d),
        ):
            out = apply_landing_submission_to_pipeline(
                {"market_user_id": 5, "landing_contact_id": 0}
            )
        # company 空 -> 不写 erp_customer_name
        assert "erp_customer_name" not in out
        # landing_contact_id 不 > 0 -> 不写
        assert "landing_contact_id" not in out
        # need_mobile 默认 True
        assert out["intake_form"]["need_mobile"] is True

    def test_auto_submitted_at_when_absent(self):
        loaded: dict = {}
        with (
            patch(f"{_PIPE}.load_pipeline", return_value=loaded),
            patch(f"{_PIPE}.set_pipeline_stage", return_value=loaded),
            patch(f"{_PIPE}.save_pipeline", side_effect=lambda d: d),
            patch(
                "app.services.user_cs_demand_form._now_iso",
                return_value="GENERATED_TS",
            ),
        ):
            out = apply_landing_submission_to_pipeline({"market_user_id": 5})
        assert out["intake_submitted_at"] == "GENERATED_TS"


# ──────────────────────────────────────────────────────────────────────────────
# fetch_submission_by_audit_code  (80-90)
# ──────────────────────────────────────────────────────────────────────────────


class TestFetchSubmissionByAuditCode:
    async def test_too_short_raises(self):
        with pytest.raises(ValueError, match="审核码"):
            await fetch_submission_by_audit_code("abc")

    async def test_none_raises(self):
        with pytest.raises(ValueError, match="审核码"):
            await fetch_submission_by_audit_code(None)  # type: ignore[arg-type]

    async def test_valid_returns_stub(self):
        out = await fetch_submission_by_audit_code("  CODE1234  ")
        assert out["audit_code"] == "CODE1234"  # 去空白
        assert out["source"] == "local_stub"
        assert set(out) >= {"name", "company", "message", "submitted_at"}


# ──────────────────────────────────────────────────────────────────────────────
# redeem_submission_by_audit_code  (99-109)
# ──────────────────────────────────────────────────────────────────────────────


class TestRedeemSubmissionByAuditCode:
    async def test_assembles_payload_and_applies(self):
        submission = {
            "name": "N",
            "company": "C",
            "message": "M",
            "submitted_at": "TS",
        }
        with (
            patch(
                "app.services.user_cs_demand_form.fetch_submission_by_audit_code",
                return_value=submission,
            ) as m_fetch,
            patch(
                "app.services.user_cs_demand_form.apply_landing_submission_to_pipeline",
                return_value={"ok": True},
            ) as m_apply,
        ):
            out = await redeem_submission_by_audit_code("9", "WXYZ", username="carol")
        assert out == {"ok": True}
        m_fetch.assert_awaited_once_with("WXYZ")
        payload = m_apply.call_args.args[0]
        assert payload["market_user_id"] == 9
        assert payload["username"] == "carol"
        assert payload["name"] == "N"
        assert payload["company"] == "C"
        assert payload["message"] == "M"
        assert payload["submitted_at"] == "TS"
        assert payload["audit_code"] == "WXYZ"

    async def test_missing_submitted_at_uses_now(self):
        submission = {"name": "", "company": "", "message": "", "submitted_at": ""}
        with (
            patch(
                "app.services.user_cs_demand_form.fetch_submission_by_audit_code",
                return_value=submission,
            ),
            patch(
                "app.services.user_cs_demand_form.apply_landing_submission_to_pipeline",
                return_value={},
            ) as m_apply,
            patch(
                "app.services.user_cs_demand_form._now_iso",
                return_value="NOW_TS",
            ),
        ):
            await redeem_submission_by_audit_code(1, "ABCD")
        payload = m_apply.call_args.args[0]
        assert payload["submitted_at"] == "NOW_TS"


# ──────────────────────────────────────────────────────────────────────────────
# sync_intake_from_market_if_newer  (118-154)
#   函数内 import: httpx (patch app.services.user_cs_demand_form 模块属性不可——
#   httpx 是函数内 import，patch 真实 httpx.get)
# ──────────────────────────────────────────────────────────────────────────────


class TestSyncIntakeFromMarketIfNewer:
    async def test_no_base_returns_none(self, monkeypatch):
        monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
        out = await sync_intake_from_market_if_newer(1)
        assert out is None

    async def test_http_error_status_returns_none(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://m.x.io/")
        resp = MagicMock()
        resp.status_code = 502
        with patch("httpx.get", return_value=resp) as m_get:
            out = await sync_intake_from_market_if_newer(1)
        assert out is None
        # base 去掉尾斜杠后拼接路径
        called_url = m_get.call_args.args[0]
        assert called_url == "https://m.x.io/api/enterprise/intake-status"

    async def test_non_dict_body_returns_none(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://m.x.io")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = ["not", "a", "dict"]
        with patch("httpx.get", return_value=resp):
            out = await sync_intake_from_market_if_newer(1)
        assert out is None

    async def test_missing_submitted_at_returns_none(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://m.x.io")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"name": "x"}  # 无 submitted_at
        with patch("httpx.get", return_value=resp):
            out = await sync_intake_from_market_if_newer(1)
        assert out is None

    async def test_valid_body_applies_and_returns_result(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://m.x.io")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "submitted_at": "2026-02-02T00:00:00+00:00",
            "name": "Dora",
            "email": "d@x.io",
            "phone": "999",
            "company": "Globex",
            "message": "hello",
            "landing_contact_id": 11,
            "ignored_extra": "drop",
        }
        with (
            patch("httpx.get", return_value=resp),
            patch(
                "app.services.user_cs_demand_form.apply_landing_submission_to_pipeline",
                return_value={"applied": True},
            ) as m_apply,
        ):
            out = await sync_intake_from_market_if_newer(7, username="ed")
        assert out == {"applied": True}
        payload = m_apply.call_args.args[0]
        assert payload["market_user_id"] == 7
        assert payload["username"] == "ed"
        assert payload["company"] == "Globex"
        assert payload["landing_contact_id"] == 11
        # 仅白名单 key 被拷贝，额外字段不传
        assert "ignored_extra" not in payload

    async def test_recoverable_exception_returns_none(self, monkeypatch):
        monkeypatch.setenv("XCAGI_MARKET_BASE_URL", "https://m.x.io")
        # httpx.get 抛 ConnectionError (属 RECOVERABLE_ERRORS) -> 降级 None
        with patch("httpx.get", side_effect=ConnectionError("boom")):
            out = await sync_intake_from_market_if_newer(1)
        assert out is None
