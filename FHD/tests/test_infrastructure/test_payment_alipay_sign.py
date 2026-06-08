"""Tests for app.infrastructure.payment.alipay — coverage ramp C3.3-b.

Covers:
* Credential resolution: ``alipay_app_id`` falls back from ``ALIPAY_APP_ID`` to
  ``ALIPAY_PID``; private/public key sources (env / path / bundled / missing).
* ``credentials_ready`` / ``alipay_ui_ready`` composition.
* ``_notify_url_path_ok`` returns True only for ``/api/model-payment/notify/alipay``.
* ``warn_notify_url_path_once`` warns when path mismatches and is idempotent.
* ``sdk_import_error`` returns string when SDK missing, None otherwise.
* ``precreate_order`` short-circuits on missing credentials.
* ``query_order`` / ``refund_order`` / ``close_order`` / ``query_refund``
  reject when both id params missing, and accept when at least one is set.
* ``create_pay_order`` UA-based routing (mobile → wap, desktop → page).
* ``diagnostics_snapshot`` exposes only metadata, no secret material.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.payment import alipay as alipay_mod


@pytest.fixture
def clear_alipay_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every ``ALIPAY_*`` env var so the module returns to defaults."""
    for key in list(os.environ):
        if key.startswith("ALIPAY_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def reset_warn_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset module-level warning latch between tests."""
    monkeypatch.setattr(alipay_mod, "_warned_notify_url", False)


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


class TestAlipayAppId:
    def test_prefers_alipay_app_id(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        monkeypatch.setenv("ALIPAY_PID", "20219999")
        assert alipay_mod.alipay_app_id() == "20210001"

    def test_falls_back_to_pid(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_PID", "20218888")
        assert alipay_mod.alipay_app_id() == "20218888"

    def test_empty_when_neither_set(self, clear_alipay_env):
        assert alipay_mod.alipay_app_id() == ""


class TestPrivateKeyPem:
    def test_from_env_inline(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv(
            "ALIPAY_APP_PRIVATE_KEY",
            "-----BEGIN PRIVATE KEY-----\\nXXX\\n-----END PRIVATE KEY-----",
        )
        pem = alipay_mod.app_private_key_pem()
        assert "BEGIN PRIVATE KEY" in pem
        assert "\\n" not in pem  # escaped sequences normalized

    def test_missing_returns_empty(self, clear_alipay_env):
        assert alipay_mod.app_private_key_pem() == ""

    def test_falls_back_to_path(self, clear_alipay_env, monkeypatch, tmp_path):
        pem_path = tmp_path / "priv.pem"
        pem_path.write_text("-----BEGIN PRIVATE KEY-----\nZZZ\n-----END PRIVATE KEY-----\n")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY_PATH", str(pem_path))
        # also clear the inline env explicitly via clear_alipay_env; set just PATH
        assert "BEGIN PRIVATE KEY" in alipay_mod.app_private_key_pem()

    def test_path_missing_file_returns_empty(self, clear_alipay_env, monkeypatch, tmp_path):
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY_PATH", str(tmp_path / "absent.pem"))
        assert alipay_mod.app_private_key_pem() == ""


class TestAlipayDebug:
    def test_truthy_variants(self, clear_alipay_env, monkeypatch):
        for val in ("1", "true", "yes", "TRUE"):
            monkeypatch.setenv("ALIPAY_DEBUG", val)
            assert alipay_mod.alipay_debug() is True

    def test_falsy(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_DEBUG", "no")
        assert alipay_mod.alipay_debug() is False

    def test_unset(self, clear_alipay_env):
        assert alipay_mod.alipay_debug() is False


class TestNotifyUrlDefault:
    def test_returns_env(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv(
            "ALIPAY_NOTIFY_URL",
            "https://example.com/api/model-payment/notify/alipay",
        )
        assert (
            alipay_mod.notify_url_default() == "https://example.com/api/model-payment/notify/alipay"
        )

    def test_unset_returns_none(self, clear_alipay_env):
        assert alipay_mod.notify_url_default() is None


# ---------------------------------------------------------------------------
# notify_url validation
# ---------------------------------------------------------------------------


class TestNotifyUrlPathOk:
    def test_exact_match(self) -> None:
        assert (
            alipay_mod._notify_url_path_ok("https://example.com/api/model-payment/notify/alipay")
            is True
        )

    def test_trailing_slash_still_ok(self) -> None:
        assert (
            alipay_mod._notify_url_path_ok("https://example.com/api/model-payment/notify/alipay/")
            is True
        )

    def test_wrong_path(self) -> None:
        assert alipay_mod._notify_url_path_ok("https://example.com/api/other") is False

    def test_empty_or_none(self) -> None:
        assert alipay_mod._notify_url_path_ok("") is False
        assert alipay_mod._notify_url_path_ok(None) is False  # type: ignore[arg-type]


class TestWarnNotifyUrl:
    def test_no_url_no_warning(self, clear_alipay_env, caplog, reset_warn_flag):
        alipay_mod.warn_notify_url_path_once()
        assert "ALIPAY_NOTIFY_URL" not in caplog.text

    def test_wrong_path_warns(self, clear_alipay_env, caplog, reset_warn_flag, monkeypatch):
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://example.com/api/wrong")
        alipay_mod.warn_notify_url_path_once()
        assert "ALIPAY_NOTIFY_URL 的 path 应为" in caplog.text

    def test_correct_path_no_warning(self, clear_alipay_env, caplog, reset_warn_flag, monkeypatch):
        monkeypatch.setenv(
            "ALIPAY_NOTIFY_URL",
            "https://example.com/api/model-payment/notify/alipay",
        )
        alipay_mod.warn_notify_url_path_once()
        assert "ALIPAY_NOTIFY_URL" not in caplog.text

    def test_idempotent(self, clear_alipay_env, caplog, reset_warn_flag, monkeypatch):
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://example.com/api/wrong")
        alipay_mod.warn_notify_url_path_once()
        alipay_mod.warn_notify_url_path_once()
        # only first call warns — latch is sticky
        assert caplog.text.count("ALIPAY_NOTIFY_URL 的 path 应为") == 1


# ---------------------------------------------------------------------------
# SDK + readiness
# ---------------------------------------------------------------------------


class TestSdkImportError:
    def test_returns_none_when_sdk_present(self, monkeypatch):
        fake_sdk = MagicMock()
        with patch.dict("sys.modules", {"alipay": fake_sdk}):
            assert alipay_mod.sdk_import_error() is None

    def test_returns_string_when_missing(self, monkeypatch):
        # Force the import to fail
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "alipay":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            err = alipay_mod.sdk_import_error()
        assert err is not None
        assert "python-alipay-sdk" in err


class TestCredentialsReady:
    def test_false_when_appid_missing(self, clear_alipay_env, monkeypatch, tmp_path):
        pem_path = tmp_path / "priv.pem"
        pem_path.write_text("-----BEGIN PRIVATE KEY-----\nX\n-----END PRIVATE KEY-----\n")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY_PATH", str(pem_path))
        assert alipay_mod.credentials_ready() is False

    def test_false_when_private_key_missing(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        assert alipay_mod.credentials_ready() is False

    def test_true_when_all_set(self, clear_alipay_env, monkeypatch, tmp_path):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        pem = tmp_path / "priv.pem"
        pem.write_text("-----BEGIN PRIVATE KEY-----\nX\n-----END PRIVATE KEY-----\n")
        pub = tmp_path / "pub.pem"
        pub.write_text("-----BEGIN PUBLIC KEY-----\nY\n-----END PUBLIC KEY-----\n")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY_PATH", str(pem))
        monkeypatch.setenv("ALIPAY_ALIPAY_PUBLIC_KEY_PATH", str(pub))
        assert alipay_mod.credentials_ready() is True


# ---------------------------------------------------------------------------
# precreate_order — short-circuit paths
# ---------------------------------------------------------------------------


class TestPrecreateOrderShortCircuit:
    def test_missing_credentials(self, clear_alipay_env):
        out = alipay_mod.precreate_order(out_trade_no="O1", subject="测试", total_amount="0.01")
        assert out["success"] is False
        assert out["qr_code"] is None
        assert "ALIPAY_APP_ID" in out["message"]

    def test_sdk_missing(self, clear_alipay_env, monkeypatch, tmp_path):
        pem = tmp_path / "priv.pem"
        pem.write_text("X")
        pub = tmp_path / "pub.pem"
        pub.write_text("Y")
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY_PATH", str(pem))
        monkeypatch.setenv("ALIPAY_ALIPAY_PUBLIC_KEY_PATH", str(pub))

        # Force SDK import to fail
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "alipay":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            out = alipay_mod.precreate_order(out_trade_no="O1", subject="测试", total_amount="0.01")
        assert out["success"] is False
        assert "python-alipay-sdk" in out["message"]


# ---------------------------------------------------------------------------
# query_order / refund_order / close_order / query_refund — input validation
# ---------------------------------------------------------------------------


class TestQueryOrderValidation:
    def test_both_missing_rejected(self) -> None:
        out = alipay_mod.query_order()
        assert out["success"] is False
        assert "至少提供一个" in out["message"]

    def test_with_out_trade_no_short_circuits(self) -> None:
        fake_client = MagicMock()
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            fake_client.api_alipay_trade_query.return_value = {
                "code": "10000",
                "tradeStatus": "TRADE_SUCCESS",
            }
            out = alipay_mod.query_order(out_trade_no="O1")
        assert out["success"] is True
        assert out["raw"]["tradeStatus"] == "TRADE_SUCCESS"
        fake_client.api_alipay_trade_query.assert_called_once_with(out_trade_no="O1")

    def test_sdk_failure_returns_message(self) -> None:
        with patch.object(alipay_mod, "build_client", side_effect=RuntimeError("no sdk")):
            out = alipay_mod.query_order(out_trade_no="O1")
        assert out["success"] is False
        assert "no sdk" in out["message"]

    def test_remote_exception_caught(self) -> None:
        fake_client = MagicMock()
        fake_client.api_alipay_trade_query.side_effect = ConnectionError("net fail")
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.query_order(out_trade_no="O1")
        assert out["success"] is False
        assert "net fail" in out["message"]

    def test_non_dict_response(self) -> None:
        fake_client = MagicMock()
        fake_client.api_alipay_trade_query.return_value = "garbled"
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.query_order(out_trade_no="O1")
        assert out["success"] is False
        assert "格式异常" in out["message"]

    def test_code_not_10000(self) -> None:
        fake_client = MagicMock()
        fake_client.api_alipay_trade_query.return_value = {
            "code": "40004",
            "sub_msg": "ACQ.TRADE_NOT_EXIST",
        }
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.query_order(out_trade_no="O1")
        assert out["success"] is False
        assert out["message"] == "ACQ.TRADE_NOT_EXIST"


class TestRefundOrderValidation:
    def test_both_missing_rejected(self) -> None:
        out = alipay_mod.refund_order(refund_amount="0.01")
        assert out["success"] is False
        assert "至少提供一个" in out["message"]

    def test_with_out_trade_no(self) -> None:
        fake_client = MagicMock()
        fake_client.api_alipay_trade_refund.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.refund_order(out_trade_no="O1", refund_amount="0.01")
        assert out["success"] is True
        kwargs = fake_client.api_alipay_trade_refund.call_args.kwargs
        assert kwargs["out_trade_no"] == "O1"
        assert kwargs["refund_amount"] == "0.01"
        # out_request_no defaults to out_trade_no only when not explicitly set;
        # not asserted here to keep the surface small.

    def test_explicit_out_request_no(self) -> None:
        fake_client = MagicMock()
        fake_client.api_alipay_trade_refund.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.refund_order(
                out_trade_no="O1",
                out_request_no="R1",
                refund_amount="0.01",
                refund_reason="用户取消",
            )
        assert out["success"] is True
        kwargs = fake_client.api_alipay_trade_refund.call_args.kwargs
        assert kwargs["out_request_no"] == "R1"
        assert kwargs["refund_reason"] == "用户取消"


class TestCloseOrderValidation:
    def test_both_missing_rejected(self) -> None:
        out = alipay_mod.close_order()
        assert out["success"] is False
        assert "至少提供一个" in out["message"]

    def test_success(self) -> None:
        fake_client = MagicMock()
        fake_client.api_alipay_trade_close.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.close_order(out_trade_no="O1")
        assert out["success"] is True


class TestQueryRefundValidation:
    def test_missing_out_trade_no(self) -> None:
        out = alipay_mod.query_refund(out_trade_no="")  # type: ignore[arg-type]
        assert out["success"] is False
        assert "out_trade_no 必填" in out["message"]

    def test_default_out_request_no(self) -> None:
        fake_client = MagicMock()
        fake_client.api_alipay_trade_fastpay_refund_query.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.query_refund(out_trade_no="O1")
        assert out["success"] is True
        # first positional arg == out_trade_no (when out_request_no omitted)
        args, kwargs = fake_client.api_alipay_trade_fastpay_refund_query.call_args
        assert args[0] == "O1"
        assert kwargs["out_trade_no"] == "O1"

    def test_explicit_out_request_no(self) -> None:
        fake_client = MagicMock()
        fake_client.api_alipay_trade_fastpay_refund_query.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.query_refund(out_trade_no="O1", out_request_no="R1")
        assert out["success"] is True
        args, _ = fake_client.api_alipay_trade_fastpay_refund_query.call_args
        assert args[0] == "R1"


# ---------------------------------------------------------------------------
# verify_notify (signature check)
# ---------------------------------------------------------------------------


class TestVerifyNotify:
    def test_valid_signature_returns_true(self) -> None:
        fake_client = MagicMock()
        fake_client.verify.return_value = True
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            ok = alipay_mod.verify_notify({"out_trade_no": "O1"}, "good-sig")
        assert ok is True
        fake_client.verify.assert_called_once_with({"out_trade_no": "O1"}, "good-sig")

    def test_invalid_signature_returns_false(self) -> None:
        fake_client = MagicMock()
        fake_client.verify.return_value = False
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            ok = alipay_mod.verify_notify({"out_trade_no": "O1"}, "bad-sig")
        assert ok is False


# ---------------------------------------------------------------------------
# create_pay_order — UA-driven routing
# ---------------------------------------------------------------------------


class TestCreatePayOrderRouting:
    def test_desktop_ua_uses_page_pay(self) -> None:
        page_result = {
            "success": True,
            "order_string": "x=1",
            "gateway": "https://openapi.alipay.com/gateway.do",
        }
        with (
            patch.object(alipay_mod, "_try_page_pay", return_value=page_result) as page_mock,
            patch.object(alipay_mod, "_try_wap_pay") as wap_mock,
            patch.object(alipay_mod, "_try_precreate") as pr_mock,
        ):
            out = alipay_mod.create_pay_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                user_agent="Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0",
            )
        assert out["success"] is True
        assert out["type"] == "page"
        assert out["redirect_url"] == "https://openapi.alipay.com/gateway.do?x=1"
        wap_mock.assert_not_called()
        pr_mock.assert_not_called()
        page_mock.assert_called_once()

    def test_mobile_ua_uses_wap_pay(self) -> None:
        wap_result = {
            "success": True,
            "order_string": "x=2",
            "gateway": "https://openapi.alipay.com/gateway.do",
        }
        with (
            patch.object(alipay_mod, "_try_wap_pay", return_value=wap_result) as wap_mock,
            patch.object(alipay_mod, "_try_page_pay") as page_mock,
            patch.object(alipay_mod, "_try_precreate") as pr_mock,
        ):
            out = alipay_mod.create_pay_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
            )
        assert out["success"] is True
        assert out["type"] == "wap"
        page_mock.assert_not_called()
        pr_mock.assert_not_called()
        wap_mock.assert_called_once()

    def test_wap_failure_falls_back_to_page(self) -> None:
        wap_result = {"success": False, "order_string": None, "gateway": "", "message": "denied"}
        page_result = {
            "success": True,
            "order_string": "x=3",
            "gateway": "https://openapi.alipay.com/gateway.do",
        }
        with (
            patch.object(alipay_mod, "_try_wap_pay", return_value=wap_result),
            patch.object(alipay_mod, "_try_page_pay", return_value=page_result) as page_mock,
            patch.object(alipay_mod, "_try_precreate") as pr_mock,
        ):
            out = alipay_mod.create_pay_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                user_agent="iPhone",
            )
        assert out["success"] is True
        assert out["type"] == "page"
        page_mock.assert_called_once()
        pr_mock.assert_not_called()

    def test_all_fail_falls_back_to_precreate(self) -> None:
        page_result = {"success": False, "order_string": None, "gateway": "", "message": "no perm"}
        precreate_result = {"success": True, "qr_code": "https://qr.alipay.com/x"}
        with (
            patch.object(alipay_mod, "_try_wap_pay", return_value={"success": False, "message": "x"}),
            patch.object(alipay_mod, "_try_page_pay", return_value=page_result),
            patch.object(alipay_mod, "_try_precreate", return_value=precreate_result),
        ):
            out = alipay_mod.create_pay_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                user_agent="iPhone",
            )
        assert out["success"] is True
        assert out["type"] == "precreate"
        assert out["qr_code"] == "https://qr.alipay.com/x"
        assert out["redirect_url"] is None

    def test_all_three_fail(self) -> None:
        with (
            patch.object(alipay_mod, "_try_wap_pay", return_value={"success": False, "message": "x"}),
            patch.object(alipay_mod, "_try_page_pay", return_value={"success": False, "message": "y"}),
            patch.object(alipay_mod, "_try_precreate", return_value={"success": False, "message": "z"}),
        ):
            out = alipay_mod.create_pay_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                user_agent="iPhone",
            )
        assert out["success"] is False
        assert out["type"] == ""


# ---------------------------------------------------------------------------
# diagnostics_snapshot
# ---------------------------------------------------------------------------


class TestDiagnosticsSnapshot:
    def test_snapshot_shape(self, clear_alipay_env, monkeypatch, tmp_path):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        pem = tmp_path / "priv.pem"
        pem.write_text("X")
        pub = tmp_path / "pub.pem"
        pub.write_text("Y")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY_PATH", str(pem))
        monkeypatch.setenv("ALIPAY_ALIPAY_PUBLIC_KEY_PATH", str(pub))
        snap = alipay_mod.diagnostics_snapshot()
        assert "alipay_configured" in snap
        assert snap["app_id_set"] is True
        assert snap["private_key_source"] == "path"
        assert snap["public_key_source"] == "path"
        assert snap["notify_url_path_expected"] == "/api/model-payment/notify/alipay"
        assert "debug_mode" in snap
        # No secret material leaks
        assert "PRIVATE KEY" not in str(snap)
        assert "PUBLIC KEY" not in str(snap)

    def test_snapshot_missing_everything(self, clear_alipay_env):
        snap = alipay_mod.diagnostics_snapshot()
        assert snap["alipay_configured"] is False
        assert snap["app_id_set"] is False
        assert snap["private_key_source"] == "missing"
        assert snap["public_key_source"] == "missing"
        assert snap["notify_url"] is None
        assert snap["notify_url_path_ok"] is False
