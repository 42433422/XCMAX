"""Deep coverage tests for app.infrastructure.payment.alipay.

Targets remaining uncovered branches:
- _env, _pem_from_env, _read_file_from_env edge cases
- alipay_app_id with ALIPAY_PID fallback
- app_private_key_pem path fallback
- alipay_public_key_pem path fallback
- alipay_debug truthy variants
- notify_url_default returns None when empty
- warn_notify_url_path_once (warning path, idempotent)
- sdk_import_error
- credentials_ready
- precreate_order wrapper
- query_order (uncovered)
- _notify_url_path_ok
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


# ── _env / _pem_from_env / _read_file_from_env ──────────────────────────────


class TestEnvHelpers:
    def test_env_strips_whitespace(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_TEST", "  value  ")
        assert alipay_mod._env("ALIPAY_TEST") == "value"

    def test_env_missing_returns_empty(self, clear_alipay_env):
        assert alipay_mod._env("ALIPAY_NONEXISTENT") == ""

    def test_env_none_value_returns_empty(self, clear_alipay_env, monkeypatch):
        # os.environ.get returns None → ""
        assert alipay_mod._env("ALIPAY_NONEXISTENT") == ""

    def test_pem_from_env_empty(self, clear_alipay_env):
        assert alipay_mod._pem_from_env("ALIPAY_NONEXISTENT") == ""

    def test_pem_from_env_converts_escaped_newlines(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_TEST_KEY", "line1\\nline2\\nline3")
        result = alipay_mod._pem_from_env("ALIPAY_TEST_KEY")
        assert result == "line1\nline2\nline3"

    def test_pem_from_env_preserves_real_newlines(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_TEST_KEY", "line1\nline2")
        result = alipay_mod._pem_from_env("ALIPAY_TEST_KEY")
        # Real newlines are preserved (no \\n to replace)
        assert result == "line1\nline2"

    def test_read_file_from_env_empty_path(self, clear_alipay_env):
        assert alipay_mod._read_file_from_env("ALIPAY_NONEXISTENT") == ""

    def test_read_file_from_env_reads_file(self, clear_alipay_env, monkeypatch, tmp_path):
        f = tmp_path / "key.pem"
        f.write_text("  file content  \n")
        monkeypatch.setenv("ALIPAY_TEST_PATH", str(f))
        assert alipay_mod._read_file_from_env("ALIPAY_TEST_PATH") == "file content"

    def test_read_file_from_env_os_error_returns_empty(
        self, clear_alipay_env, monkeypatch, tmp_path
    ):
        # Point to a path that can't be read (directory)
        monkeypatch.setenv("ALIPAY_TEST_PATH", str(tmp_path))  # directory, not file
        # open() on a directory raises IsADirectoryError (subclass of OSError)
        result = alipay_mod._read_file_from_env("ALIPAY_TEST_PATH")
        # Either returns "" (OSError caught) or the open fails
        assert result == ""


# ── alipay_app_id / app_private_key_pem / alipay_public_key_pem ─────────────


class TestCredentialResolvers:
    def test_app_id_uses_alipay_pid_fallback(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_PID", "20210002")
        assert alipay_mod.alipay_app_id() == "20210002"

    def test_app_id_prefers_app_id_over_pid(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        monkeypatch.setenv("ALIPAY_PID", "20210002")
        assert alipay_mod.alipay_app_id() == "20210001"

    def test_app_id_empty_when_neither_set(self, clear_alipay_env):
        assert alipay_mod.alipay_app_id() == ""

    def test_app_private_key_pem_from_env(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY", "key\\ncontent")
        assert "key\ncontent" in alipay_mod.app_private_key_pem()

    def test_app_private_key_pem_from_path(self, clear_alipay_env, monkeypatch, tmp_path):
        f = tmp_path / "priv.pem"
        f.write_text("path key content")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY_PATH", str(f))
        assert alipay_mod.app_private_key_pem() == "path key content"

    def test_app_private_key_pem_empty_when_missing(self, clear_alipay_env):
        assert alipay_mod.app_private_key_pem() == ""

    def test_public_key_pem_from_env(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_ALIPAY_PUBLIC_KEY", "pub\\nkey")
        assert "pub\nkey" in alipay_mod.alipay_public_key_pem()

    def test_public_key_pem_from_path(self, clear_alipay_env, monkeypatch, tmp_path):
        f = tmp_path / "pub.pem"
        f.write_text("path pub key")
        monkeypatch.setenv("ALIPAY_ALIPAY_PUBLIC_KEY_PATH", str(f))
        assert alipay_mod.alipay_public_key_pem() == "path pub key"

    def test_public_key_pem_from_bundled(self, clear_alipay_env, monkeypatch):
        with patch.object(
            alipay_mod, "_default_bundled_alipay_public_key", return_value="bundled"
        ):
            assert alipay_mod.alipay_public_key_pem() == "bundled"

    def test_public_key_pem_empty_when_all_missing(self, clear_alipay_env, monkeypatch):
        with patch.object(
            alipay_mod, "_default_bundled_alipay_public_key", return_value=""
        ):
            assert alipay_mod.alipay_public_key_pem() == ""


# ── alipay_debug ────────────────────────────────────────────────────────────


class TestAlipayDebug:
    @pytest.mark.parametrize("val", ["1", "true", "yes", "TRUE", "YES"])
    def test_debug_truthy_values(self, clear_alipay_env, monkeypatch, val):
        monkeypatch.setenv("ALIPAY_DEBUG", val)
        assert alipay_mod.alipay_debug() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "", "random"])
    def test_debug_falsy_values(self, clear_alipay_env, monkeypatch, val):
        monkeypatch.setenv("ALIPAY_DEBUG", val)
        assert alipay_mod.alipay_debug() is False

    def test_debug_empty(self, clear_alipay_env):
        assert alipay_mod.alipay_debug() is False


# ── notify_url_default ──────────────────────────────────────────────────────


class TestNotifyUrlDefault:
    def test_returns_url_when_set(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://x.com/notify")
        assert alipay_mod.notify_url_default() == "https://x.com/notify"

    def test_returns_none_when_empty(self, clear_alipay_env):
        assert alipay_mod.notify_url_default() is None

    def test_returns_stripped_when_whitespace(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "   https://x.com/notify   ")
        # _env strips, so whitespace is removed
        assert alipay_mod.notify_url_default() == "https://x.com/notify"


# ── warn_notify_url_path_once ───────────────────────────────────────────────


class TestWarnNotifyUrlPathOnce:
    def test_warns_on_mismatched_path(self, clear_alipay_env, monkeypatch, reset_warn_flag, caplog):
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://x.com/wrong/path")
        with caplog.at_level("WARNING"):
            alipay_mod.warn_notify_url_path_once()
        assert any("ALIPAY_NOTIFY_URL" in r.message for r in caplog.records)

    def test_no_warn_on_correct_path(self, clear_alipay_env, monkeypatch, reset_warn_flag, caplog):
        monkeypatch.setenv(
            "ALIPAY_NOTIFY_URL",
            "https://x.com/api/model-payment/notify/alipay",
        )
        with caplog.at_level("WARNING"):
            alipay_mod.warn_notify_url_path_once()
        assert not any("ALIPAY_NOTIFY_URL" in r.message for r in caplog.records)

    def test_no_warn_when_no_url(self, clear_alipay_env, reset_warn_flag, caplog):
        with caplog.at_level("WARNING"):
            alipay_mod.warn_notify_url_path_once()
        assert not any("ALIPAY_NOTIFY_URL" in r.message for r in caplog.records)

    def test_idempotent_only_warns_once(
        self, clear_alipay_env, monkeypatch, reset_warn_flag, caplog
    ):
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://x.com/wrong")
        with caplog.at_level("WARNING"):
            alipay_mod.warn_notify_url_path_once()
            first_count = len(caplog.records)
            alipay_mod.warn_notify_url_path_once()
            second_count = len(caplog.records)
        assert second_count == first_count  # no additional warning

    def test_warns_with_empty_path(self, clear_alipay_env, monkeypatch, reset_warn_flag, caplog):
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://x.com")
        with caplog.at_level("WARNING"):
            alipay_mod.warn_notify_url_path_once()
        assert any("ALIPAY_NOTIFY_URL" in r.message for r in caplog.records)


# ── sdk_import_error ────────────────────────────────────────────────────────


class TestSdkImportError:
    def test_returns_none_when_sdk_available(self, monkeypatch):
        fake_alipay = MagicMock()
        with patch.dict("sys.modules", {"alipay": fake_alipay}):
            assert alipay_mod.sdk_import_error() is None

    def test_returns_message_when_sdk_missing(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "alipay":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=fake_import):
            result = alipay_mod.sdk_import_error()
        assert result is not None
        assert "python-alipay-sdk" in result


# ── credentials_ready ───────────────────────────────────────────────────────


class TestCredentialsReady:
    def test_false_when_all_missing(self, clear_alipay_env):
        assert alipay_mod.credentials_ready() is False

    def test_false_when_partial(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        # Missing private key and public key
        assert alipay_mod.credentials_ready() is False

    def test_true_when_all_present(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY", "key")
        monkeypatch.setenv("ALIPAY_ALIPAY_PUBLIC_KEY", "pub")
        assert alipay_mod.credentials_ready() is True


# ── precreate_order (wrapper) ───────────────────────────────────────────────


class TestPrecreateOrder:
    def test_delegates_to_try_precreate(self, clear_alipay_env):
        # When credentials missing, returns failure
        result = alipay_mod.precreate_order(
            out_trade_no="O1", subject="s", total_amount="0.01"
        )
        assert result["success"] is False
        assert "ALIPAY_APP_ID" in result["message"]

    def test_passes_notify_url(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY", "key")
        monkeypatch.setenv("ALIPAY_ALIPAY_PUBLIC_KEY", "pub")

        with patch.object(alipay_mod, "_try_precreate", return_value={"success": True}) as mock:
            alipay_mod.precreate_order(
                out_trade_no="O1",
                subject="s",
                total_amount="0.01",
                notify_url="https://custom/notify",
            )
        call_kwargs = mock.call_args.kwargs
        assert call_kwargs["notify_url"] == "https://custom/notify"


# ── query_order ─────────────────────────────────────────────────────────────


class TestQueryOrder:
    def test_both_ids_missing(self):
        result = alipay_mod.query_order()
        assert result["success"] is False
        assert "至少提供一个" in result["message"]

    def test_build_client_failure(self, monkeypatch):
        with patch.object(alipay_mod, "build_client", side_effect=RuntimeError("no sdk")):
            result = alipay_mod.query_order(out_trade_no="O1")
        assert result["success"] is False
        assert "no sdk" in result["message"]

    def test_success_with_out_trade_no(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_query.return_value = {"code": "10000", "trade_status": "TRADE_SUCCESS"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            result = alipay_mod.query_order(out_trade_no="O1")
        assert result["success"] is True
        call_kwargs = fake_client.api_alipay_trade_query.call_args.kwargs
        assert call_kwargs["out_trade_no"] == "O1"

    def test_success_with_trade_no(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_query.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            result = alipay_mod.query_order(trade_no="T1")
        assert result["success"] is True
        call_kwargs = fake_client.api_alipay_trade_query.call_args.kwargs
        assert call_kwargs["trade_no"] == "T1"

    def test_success_with_both_ids(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_query.return_value = {"code": "10000"}
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            result = alipay_mod.query_order(out_trade_no="O1", trade_no="T1")
        assert result["success"] is True

    def test_failure_with_sub_msg(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_query.return_value = {
            "code": "40004",
            "sub_msg": "交易不存在",
        }
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            result = alipay_mod.query_order(out_trade_no="O1")
        assert result["success"] is False
        assert result["message"] == "交易不存在"

    def test_remote_exception(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_query.side_effect = ConnectionError("net fail")
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            result = alipay_mod.query_order(out_trade_no="O1")
        assert result["success"] is False
        assert "net fail" in result["message"]

    def test_non_dict_response(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.api_alipay_trade_query.return_value = "garbled"
        with patch.object(alipay_mod, "build_client", return_value=fake_client):
            result = alipay_mod.query_order(out_trade_no="O1")
        assert result["success"] is False
        assert "格式异常" in result["message"]


# ── _notify_url_path_ok ─────────────────────────────────────────────────────


class TestNotifyUrlPathOk:
    def test_correct_path(self):
        assert alipay_mod._notify_url_path_ok(
            "https://x.com/api/model-payment/notify/alipay"
        ) is True

    def test_correct_path_with_trailing_slash(self):
        assert alipay_mod._notify_url_path_ok(
            "https://x.com/api/model-payment/notify/alipay/"
        ) is True

    def test_wrong_path(self):
        assert alipay_mod._notify_url_path_ok("https://x.com/wrong") is False

    def test_empty_url(self):
        assert alipay_mod._notify_url_path_ok("") is False

    def test_none_url(self):
        assert alipay_mod._notify_url_path_ok(None) is False

    def test_no_path(self):
        assert alipay_mod._notify_url_path_ok("https://x.com") is False


# ── _repo_root ──────────────────────────────────────────────────────────────


class TestRepoRoot:
    def test_returns_path(self):
        result = alipay_mod._repo_root()
        assert isinstance(result, Path)
        # Should end with FHD
        assert result.name == "FHD"


# ── _default_bundled_alipay_public_key deep ─────────────────────────────────


class TestDefaultBundledKeyDeep:
    def test_returns_empty_when_not_a_file(self, monkeypatch):
        with patch.object(alipay_mod, "_repo_root", return_value=Path("/nonexistent")):
            assert alipay_mod._default_bundled_alipay_public_key() == ""

    def test_returns_content_when_file_exists(self, tmp_path, monkeypatch):
        bundled_dir = tmp_path / "424"
        bundled_dir.mkdir()
        (bundled_dir / "alipayPublicKey_RSA2.txt").write_text("  content  \n")
        with patch.object(alipay_mod, "_repo_root", return_value=tmp_path):
            assert alipay_mod._default_bundled_alipay_public_key() == "content"


# ── diagnostics_snapshot deep ───────────────────────────────────────────────


class TestDiagnosticsSnapshotDeep:
    def test_with_path_based_keys(self, clear_alipay_env, monkeypatch, tmp_path):
        priv = tmp_path / "priv.pem"
        priv.write_text("private key")
        pub = tmp_path / "pub.pem"
        pub.write_text("public key")
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY_PATH", str(priv))
        monkeypatch.setenv("ALIPAY_ALIPAY_PUBLIC_KEY_PATH", str(pub))

        fake_alipay = MagicMock()
        with patch.dict("sys.modules", {"alipay": fake_alipay}):
            snap = alipay_mod.diagnostics_snapshot()
        assert snap["alipay_configured"] is True
        assert snap["private_key_source"] == "path"
        assert snap["public_key_source"] == "path"

    def test_with_bundled_key(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY", "key")
        with patch.object(
            alipay_mod, "_default_bundled_alipay_public_key", return_value="bundled"
        ):
            fake_alipay = MagicMock()
            with patch.dict("sys.modules", {"alipay": fake_alipay}):
                snap = alipay_mod.diagnostics_snapshot()
        assert snap["public_key_source"] == "bundled"

    def test_with_wrong_notify_url(self, clear_alipay_env, monkeypatch):
        monkeypatch.setenv("ALIPAY_APP_ID", "20210001")
        monkeypatch.setenv("ALIPAY_APP_PRIVATE_KEY", "key")
        monkeypatch.setenv("ALIPAY_ALIPAY_PUBLIC_KEY", "pub")
        monkeypatch.setenv("ALIPAY_NOTIFY_URL", "https://x.com/wrong")

        fake_alipay = MagicMock()
        with patch.dict("sys.modules", {"alipay": fake_alipay}):
            snap = alipay_mod.diagnostics_snapshot()
        assert snap["notify_url_path_ok"] is False
        assert snap["notify_url"] == "https://x.com/wrong"
