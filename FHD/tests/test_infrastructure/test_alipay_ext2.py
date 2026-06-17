"""Tests for app.infrastructure.payment.alipay — coverage ramp ext2.

Covers ``build_client``, ``_build_common_kwargs``, ``_try_precreate``,
``_try_page_pay``, ``_try_wap_pay``, ``create_pay_order``, ``verify_notify``,
``_standard_api_result``, ``_private_key_source``, ``_public_key_source``,
``diagnostics_snapshot``, and the bundled-key fallback path.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.payment import alipay as alipay_mod


@pytest.fixture
def clear_alipay_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("ALIPAY_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def reset_warn_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(alipay_mod, "_warned_notify_url", False)


@pytest.fixture
def full_credentials(clear_alipay_env, monkeypatch, tmp_path):
    """Provide complete credentials (env-based)."""
    monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
    monkeypatch.setenv(
        "ALIPAY_APP_PRIVATE_KEY",
        "-----BEGIN PRIVATE KEY-----\\nXXX\\n-----END PRIVATE KEY-----",
    )
    monkeypatch.setenv(
        "ALIPAY_ALIPAY_PUBLIC_KEY",
        "-----BEGIN PUBLIC KEY-----\\nYYY\\n-----END PUBLIC KEY-----",
    )


# ── build_client ─────────────────────────────────────────────────────────────


class TestBuildClient:
    def test_raises_when_sdk_missing(self, full_credentials, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "alipay":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            with pytest.raises(RuntimeError, match="python-alipay-sdk"):
                alipay_mod.build_client()

    def test_raises_when_credentials_missing(self, clear_alipay_env):
        with pytest.raises(RuntimeError, match="支付宝配置不完整"):
            alipay_mod.build_client()

    def test_builds_client_when_ready(self, full_credentials, monkeypatch):
        fake_alipay = MagicMock()
        fake_alipay.AliPay = MagicMock(return_value=MagicMock())
        with patch.dict("sys.modules", {"alipay": fake_alipay}):
            client = alipay_mod.build_client()
        assert client is not None
        fake_alipay.AliPay.assert_called_once()
        call_kwargs = fake_alipay.AliPay.call_args.kwargs
        assert call_kwargs["appid"] == "20210001"
        assert call_kwargs["sign_type"] == "RSA2"


# ── _build_common_kwargs ─────────────────────────────────────────────────────


class TestBuildCommonKwargs:
    def test_basic(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://x.com/notify")
        out = alipay_mod._build_common_kwargs(
            out_trade_no="O1", subject="subj", total_amount="0.01"
        )
        assert out["out_trade_no"] == "O1"
        assert out["total_amount"] == "0.01"
        assert out["subject"] == "subj"
        assert out["notify_url"] == "https://x.com/notify"

    def test_subject_truncated(self, clear_alipay_env):
        long_subj = "x" * 300
        out = alipay_mod._build_common_kwargs(
            out_trade_no="O1", subject=long_subj, total_amount="0.01"
        )
        assert len(out["subject"]) == 256

    def test_explicit_notify_url_overrides(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://default/notify")
        out = alipay_mod._build_common_kwargs(
            out_trade_no="O1",
            subject="subj",
            total_amount="0.01",
            notify_url="https://custom/notify",
        )
        assert out["notify_url"] == "https://custom/notify"

    def test_no_notify_url(self, clear_alipay_env):
        out = alipay_mod._build_common_kwargs(
            out_trade_no="O1", subject="subj", total_amount="0.01"
        )
        assert "notify_url" not in out


# ── _try_precreate ───────────────────────────────────────────────────────────


class TestTryPrecreate:
    def test_missing_credentials(self, clear_alipay_env):
        out = alipay_mod._try_precreate(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert out["qr_code"] is None
        assert "ALIPAY_APP_ID" in out["message"]

    def test_build_client_failure(self, full_credentials, monkeypatch):
        with patch.object(alipay_mod, "build_client", side_effect=RuntimeError("no sdk")):
            out = alipay_mod._try_precreate(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert "no sdk" in out["message"]

    def test_success_with_qr_code(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_precreate.return_value = {
            "code": "10000",
            "qr_code": "https://qr.alipay.com/abc",
        }
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_precreate(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is True
        assert out["qr_code"] == "https://qr.alipay.com/abc"

    def test_failure_with_sub_msg(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_precreate.return_value = {
            "code": "40004",
            "sub_msg": "业务失败",
            "msg": "fail",
        }
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_precreate(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert out["message"] == "业务失败"

    def test_failure_with_msg_only(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_precreate.return_value = {
            "code": "40004",
            "msg": "fail",
        }
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_precreate(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert out["message"] == "fail"

    def test_failure_default_message(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_precreate.return_value = {"code": "40004"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_precreate(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert out["message"] == "预下单失败"

    def test_non_dict_response(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_precreate.return_value = "garbled"
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_precreate(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert "格式异常" in out["message"]

    def test_remote_exception(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_precreate.side_effect = ConnectionError("net fail")
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_precreate(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert "net fail" in out["message"]


# ── _try_page_pay ────────────────────────────────────────────────────────────


class TestTryPagePay:
    def test_missing_credentials(self, clear_alipay_env):
        out = alipay_mod._try_page_pay(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert out["order_string"] is None

    def test_build_client_failure(self, full_credentials, monkeypatch):
        with patch.object(alipay_mod, "build_client", side_effect=RuntimeError("no sdk")):
            out = alipay_mod._try_page_pay(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert "no sdk" in out["message"]

    def test_success(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_page_pay.return_value = "order_string_value"
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_page_pay(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                return_url="https://x.com/return",
            )
        assert out["success"] is True
        assert out["order_string"] == "order_string_value"
        assert "openapi.alipay.com" in out["gateway"]

    def test_success_debug_mode(self, full_credentials, monkeypatch):
        monkeypatch.setenv("ALIPAY_DEBUG", "1")
        fake_client = MagicMock()
        fake_client.api_alipay_trade_page_pay.return_value = "order_string_value"
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_page_pay(out_trade_no="O1", subject="s", total_amount="0.01")
        assert "sandbox" in out["gateway"]

    def test_remote_exception(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_page_pay.side_effect = ConnectionError("net fail")
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_page_pay(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert "net fail" in out["message"]


# ── _try_wap_pay ─────────────────────────────────────────────────────────────


class TestTryWapPay:
    def test_missing_credentials(self, clear_alipay_env):
        out = alipay_mod._try_wap_pay(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False

    def test_build_client_failure(self, full_credentials, monkeypatch):
        with patch.object(alipay_mod, "build_client", side_effect=RuntimeError("no sdk")):
            out = alipay_mod._try_wap_pay(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert "no sdk" in out["message"]

    def test_success(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_wap_pay.return_value = "wap_order_string"
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_wap_pay(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                quit_url="https://x.com/quit",
                return_url="https://x.com/return",
            )
        assert out["success"] is True
        assert out["order_string"] == "wap_order_string"

    def test_remote_exception(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_wap_pay.side_effect = ConnectionError("net fail")
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod._try_wap_pay(out_trade_no="O1", subject="s", total_amount="0.01")
        assert out["success"] is False
        assert "net fail" in out["message"]


# ── create_pay_order ─────────────────────────────────────────────────────────


class TestCreatePayOrder:
    def test_mobile_uses_wap_pay(self, full_credentials, monkeypatch):
        with patch.object(
            alipay_mod,
            "_try_wap_pay",
            return_value={
                "success": True,
                "order_string": "wap_str",
                "gateway": "https://g",
                "message": None,
                "raw": {"order_string": "wap_str"},
            },
        ) as mock_wap:
            out = alipay_mod.create_pay_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                user_agent="Mozilla iPhone",
            )
        assert out["success"] is True
        assert out["type"] == "wap"
        assert out["redirect_url"] == "https://g?wap_str"
        mock_wap.assert_called_once()

    def test_mobile_wap_failure_falls_back_to_page(self, full_credentials, monkeypatch):
        with (
            patch.object(
                alipay_mod,
                "_try_wap_pay",
                return_value={
                    "success": False,
                    "order_string": None,
                    "gateway": "",
                    "message": "wap fail",
                    "raw": None,
                },
            ),
            patch.object(
                alipay_mod,
                "_try_page_pay",
                return_value={
                    "success": True,
                    "order_string": "page_str",
                    "gateway": "https://g",
                    "message": None,
                    "raw": {"order_string": "page_str"},
                },
            ) as mock_page,
        ):
            out = alipay_mod.create_pay_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                user_agent="Mozilla iPhone",
            )
        assert out["success"] is True
        assert out["type"] == "page"
        mock_page.assert_called_once()

    def test_pc_uses_page_pay(self, full_credentials, monkeypatch):
        with patch.object(
            alipay_mod,
            "_try_page_pay",
            return_value={
                "success": True,
                "order_string": "page_str",
                "gateway": "https://g",
                "message": None,
                "raw": {"order_string": "page_str"},
            },
        ) as mock_page:
            out = alipay_mod.create_pay_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                user_agent="Mozilla Windows",
            )
        assert out["success"] is True
        assert out["type"] == "page"
        mock_page.assert_called_once()

    def test_page_failure_falls_back_to_precreate(self, full_credentials, monkeypatch):
        with (
            patch.object(
                alipay_mod,
                "_try_page_pay",
                return_value={
                    "success": False,
                    "order_string": None,
                    "gateway": "",
                    "message": "page fail",
                    "raw": None,
                },
            ),
            patch.object(
                alipay_mod,
                "_try_precreate",
                return_value={
                    "success": True,
                    "qr_code": "https://qr.alipay.com/abc",
                    "message": None,
                    "raw": {"qr_code": "abc"},
                },
            ) as mock_pre,
        ):
            out = alipay_mod.create_pay_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                user_agent="Mozilla Windows",
            )
        assert out["success"] is True
        assert out["type"] == "precreate"
        assert out["qr_code"] == "https://qr.alipay.com/abc"
        mock_pre.assert_called_once()

    def test_all_failures(self, full_credentials, monkeypatch):
        with (
            patch.object(
                alipay_mod,
                "_try_page_pay",
                return_value={
                    "success": False,
                    "order_string": None,
                    "gateway": "",
                    "message": "page fail",
                    "raw": None,
                },
            ),
            patch.object(
                alipay_mod,
                "_try_precreate",
                return_value={
                    "success": False,
                    "qr_code": None,
                    "message": "pre fail",
                    "raw": None,
                },
            ),
        ):
            out = alipay_mod.create_pay_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                user_agent="Mozilla Windows",
            )
        assert out["success"] is False
        assert out["type"] == ""
        assert out["message"] == "page fail"

    def test_mobile_ua_variants(self, full_credentials, monkeypatch):
        for ua in (
            "Mozilla Android",
            "Mozilla iPhone",
            "Mozilla iPad",
            "Mozilla iPod",
            "Mozilla Windows Phone",
        ):
            with patch.object(
                alipay_mod,
                "_try_wap_pay",
                return_value={
                    "success": True,
                    "order_string": "wap_str",
                    "gateway": "https://g",
                    "message": None,
                    "raw": {},
                },
            ) as mock_wap:
                alipay_mod.create_pay_order(
                    out_trade_no="O1",
                    subject="s",
                    total_amount="0.01",
                    user_agent=ua,
                )
            mock_wap.assert_called_once()


# ── verify_notify ────────────────────────────────────────────────────────────


class TestVerifyNotify:
    def test_returns_bool(self, full_credentials, monkeypatch):
        fake_client = MagicMock()
        fake_client.verify.return_value = True
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.verify_notify({"k": "v"}, "sig")
        assert out is True
        fake_client.verify.assert_called_once_with({"k": "v"}, "sig")


# ── _standard_api_result ─────────────────────────────────────────────────────


class TestStandardApiResult:
    def test_non_dict(self):
        out = alipay_mod._standard_api_result("garbled", "default")
        assert out["success"] is False
        assert "格式异常" in out["message"]

    def test_success_code(self):
        out = alipay_mod._standard_api_result({"code": "10000", "k": "v"}, "default")
        assert out["success"] is True
        assert out["message"] is None

    def test_failure_with_sub_msg(self):
        out = alipay_mod._standard_api_result(
            {"code": "40004", "sub_msg": "失败", "msg": "fail"}, "default"
        )
        assert out["success"] is False
        assert out["message"] == "失败"

    def test_failure_with_msg_only(self):
        out = alipay_mod._standard_api_result({"code": "40004", "msg": "fail"}, "default")
        assert out["success"] is False
        assert out["message"] == "fail"

    def test_failure_default(self):
        out = alipay_mod._standard_api_result({"code": "40004"}, "default error")
        assert out["success"] is False
        assert out["message"] == "default error"


# ── refund_order / close_order / query_refund ────────────────────────────────


class TestRefundOrder:
    def test_both_ids_missing(self):
        out = alipay_mod.refund_order(refund_amount="0.01")
        assert out["success"] is False
        assert "至少提供一个" in out["message"]

    def test_build_client_failure(self, monkeypatch):
        with patch.object(alipay_mod, "build_client", side_effect=RuntimeError("no sdk")):
            out = alipay_mod.refund_order(out_trade_no="O1", refund_amount="0.01")
        assert out["success"] is False
        assert "no sdk" in out["message"]

    def test_success(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_refund.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.refund_order(
                out_trade_no="O1",
                refund_amount="0.01",
                out_request_no="R1",
                refund_reason="测试",
            )
        assert out["success"] is True
        call_kwargs = fake_client.api_alipay_trade_refund.call_args.kwargs
        assert call_kwargs["refund_amount"] == "0.01"
        assert call_kwargs["out_trade_no"] == "O1"
        assert call_kwargs["out_request_no"] == "R1"
        assert call_kwargs["refund_reason"] == "测试"

    def test_remote_exception(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_refund.side_effect = ConnectionError("net fail")
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.refund_order(out_trade_no="O1", refund_amount="0.01")
        assert out["success"] is False
        assert "net fail" in out["message"]


class TestCloseOrder:
    def test_both_ids_missing(self):
        out = alipay_mod.close_order()
        assert out["success"] is False
        assert "至少提供一个" in out["message"]

    def test_build_client_failure(self, monkeypatch):
        with patch.object(alipay_mod, "build_client", side_effect=RuntimeError("no sdk")):
            out = alipay_mod.close_order(out_trade_no="O1")
        assert out["success"] is False

    def test_success(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_close.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.close_order(out_trade_no="O1", trade_no="T1")
        assert out["success"] is True
        call_kwargs = fake_client.api_alipay_trade_close.call_args.kwargs
        assert call_kwargs["out_trade_no"] == "O1"
        assert call_kwargs["trade_no"] == "T1"

    def test_remote_exception(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_close.side_effect = ConnectionError("net fail")
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.close_order(out_trade_no="O1")
        assert out["success"] is False
        assert "net fail" in out["message"]


class TestQueryRefund:
    def test_missing_out_trade_no(self):
        out = alipay_mod.query_refund(out_trade_no="")
        assert out["success"] is False
        assert "out_trade_no 必填" in out["message"]

    def test_build_client_failure(self, monkeypatch):
        with patch.object(alipay_mod, "build_client", side_effect=RuntimeError("no sdk")):
            out = alipay_mod.query_refund(out_trade_no="O1")
        assert out["success"] is False

    def test_success_with_explicit_request_no(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_fastpay_refund_query.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.query_refund(out_trade_no="O1", out_request_no="R1")
        assert out["success"] is True
        fake_client.api_alipay_trade_fastpay_refund_query.assert_called_once_with(
            "R1", out_trade_no="O1"
        )

    def test_success_default_request_no(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_fastpay_refund_query.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.query_refund(out_trade_no="O1")
        assert out["success"] is True
        fake_client.api_alipay_trade_fastpay_refund_query.assert_called_once_with(
            "O1", out_trade_no="O1"
        )

    def test_remote_exception(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_fastpay_refund_query.side_effect = ConnectionError("net fail")
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            out = alipay_mod.query_refund(out_trade_no="O1")
        assert out["success"] is False
        assert "net fail" in out["message"]


# ── _private_key_source / _public_key_source ─────────────────────────────────


class TestPrivateKeySource:
    def test_env(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv(
            "ALIPAY_APP_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----\\nX\\n-----END PRIVATE KEY-----"
        )
        assert alipay_mod._private_key_source() == "env"

    def test_path(self, clear_alipay_env, monkeypatch, tmp_path):
        pem = tmp_path / "priv.pem"
        pem.write_text("-----BEGIN PRIVATE KEY-----\nX\n-----END PRIVATE KEY-----\n")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY_PATH", str(pem))
        assert alipay_mod._private_key_source() == "path"

    def test_missing(self, clear_alipay_env):
        assert alipay_mod._private_key_source() == "missing"

    def test_path_set_but_file_missing(self, clear_alipay_env, monkeypatch, tmp_path):
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY_PATH", str(tmp_path / "absent.pem"))
        assert alipay_mod._private_key_source() == "missing"


class TestPublicKeySource:
    def test_env(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv(
            "ALIPAY_ALIPAY_PUBLIC_KEY", "-----BEGIN PUBLIC KEY-----\\nY\\n-----END PUBLIC KEY-----"
        )
        assert alipay_mod._public_key_source() == "env"

    def test_path(self, clear_alipay_env, monkeypatch, tmp_path):
        pub = tmp_path / "pub.pem"
        pub.write_text("-----BEGIN PUBLIC KEY-----\nY\n-----END PUBLIC KEY-----\n")
        monkeypatch.setenv("ALIPAY_ALIPAY_PUBLIC_KEY_PATH", str(pub))
        assert alipay_mod._public_key_source() == "path"

    def test_bundled(self, clear_alipay_env, monkeypatch, tmp_path):
        # Patch _default_bundled_alipay_public_key to return non-empty
        with patch.object(
            alipay_mod, "_default_bundled_alipay_public_key", return_value="bundled_key"
        ):
            assert alipay_mod._public_key_source() == "bundled"

    def test_missing(self, clear_alipay_env, monkeypatch):
        with patch.object(alipay_mod, "_default_bundled_alipay_public_key", return_value=""):
            assert alipay_mod._public_key_source() == "missing"


# ── _default_bundled_alipay_public_key ───────────────────────────────────────


class TestDefaultBundledKey:
    def test_returns_empty_when_no_file(self, monkeypatch):
        with patch.object(alipay_mod, "_repo_root", return_value=Path("/nonexistent")):
            assert alipay_mod._default_bundled_alipay_public_key() == ""

    def test_reads_file(self, tmp_path, monkeypatch):
        bundled_dir = tmp_path / "424"
        bundled_dir.mkdir()
        (bundled_dir / "alipayPublicKey_RSA2.txt").write_text("bundled_key_content")
        with patch.object(alipay_mod, "_repo_root", return_value=tmp_path):
            assert alipay_mod._default_bundled_alipay_public_key() == "bundled_key_content"

    def test_handles_read_error(self, tmp_path, monkeypatch):
        bundled_dir = tmp_path / "424"
        bundled_dir.mkdir()
        key_file = bundled_dir / "alipayPublicKey_RSA2.txt"
        key_file.write_text("content")
        with (
            patch.object(alipay_mod, "_repo_root", return_value=tmp_path),
            patch("pathlib.Path.read_text", side_effect=OSError("perm")),
        ):
            assert alipay_mod._default_bundled_alipay_public_key() == ""


# ── diagnostics_snapshot ─────────────────────────────────────────────────────


class TestDiagnosticsSnapshot:
    def test_full_snapshot(self, clear_alipay_env, monkeypatch, tmp_path):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        monkeypatch.setenv(
            "ALIPAY_APP_PRIVATE_KEY",
            "-----BEGIN PRIVATE KEY-----\\nX\\n-----END PRIVATE KEY-----",
        )
        monkeypatch.setenv(
            "ALIPAY_ALIPAY_PUBLIC_KEY",
            "-----BEGIN PUBLIC KEY-----\\nY\\n-----END PUBLIC KEY-----",
        )
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://x.com/api/model-payment/notify/alipay")
        monkeypatch.setenv("ALIPAY_DEBUG", "1")

        fake_alipay = MagicMock()
        with patch.dict("sys.modules", {"alipay": fake_alipay}):
            snap = alipay_mod.diagnostics_snapshot()
        assert snap["alipay_configured"] is True
        assert snap["sdk_installed"] is True
        assert snap["app_id_set"] is True
        assert snap["private_key_source"] == "env"
        assert snap["public_key_source"] == "env"
        assert snap["notify_url"] == "https://x.com/api/model-payment/notify/alipay"
        assert snap["notify_url_path_ok"] is True
        assert snap["notify_url_path_expected"] == "/api/model-payment/notify/alipay"
        assert snap["debug_mode"] is True

    def test_empty_snapshot(self, clear_alipay_env, monkeypatch):
        # Force SDK missing
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "alipay":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            snap = alipay_mod.diagnostics_snapshot()
        assert snap["alipay_configured"] is False
        assert snap["sdk_installed"] is False
        assert snap["sdk_import_error"] is not None
        assert snap["app_id_set"] is False
        assert snap["private_key_source"] == "missing"
        assert snap["public_key_source"] in ("missing", "bundled")
        assert snap["notify_url"] is None
        assert snap["notify_url_path_ok"] is False
        assert snap["debug_mode"] is False


# ── alipay_ui_ready ──────────────────────────────────────────────────────────


class TestAlipayUiReady:
    def test_false_when_credentials_missing(self, clear_alipay_env, monkeypatch):
        # Force SDK missing
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "alipay":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            assert alipay_mod.alipay_ui_ready() is False

    def test_true_when_ready(self, full_credentials, monkeypatch):
        fake_alipay = MagicMock()
        with patch.dict("sys.modules", {"alipay": fake_alipay}):
            assert alipay_mod.alipay_ui_ready() is True
