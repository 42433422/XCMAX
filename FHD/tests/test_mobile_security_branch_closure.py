"""Branch coverage for mobile pairing and LAN credential safety boundaries.

These tests deliberately exercise the fail-closed paths that are easy to miss
in route-level happy-path tests: stale rate-limit state, expired one-time codes,
unsafe runtime secret snapshots, and Redis degradation during JWT rotation.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.fastapi_routes.mobile_extensions import pairing_helpers
from app.security import local_runtime_secret as runtime_secret
from app.security import mobile_jwt, mobile_pairing


@pytest.fixture(autouse=True)
def _reset_mobile_security_state():
    with mobile_pairing._lock:
        mobile_pairing._nonces.clear()
        mobile_pairing._short_codes.clear()
        mobile_pairing._pairing_failures.clear()
    with mobile_jwt._used_refresh_lock:
        mobile_jwt._used_refresh_jti.clear()
    yield
    with mobile_pairing._lock:
        mobile_pairing._nonces.clear()
        mobile_pairing._short_codes.clear()
        mobile_pairing._pairing_failures.clear()
    with mobile_jwt._used_refresh_lock:
        mobile_jwt._used_refresh_jti.clear()


def _request(host: str) -> SimpleNamespace:
    return SimpleNamespace(headers={"host": host})


def _nonce_record(*, exp: int, short_code: str = "123456") -> dict[str, object]:
    return {
        "host": "192.168.10.2",
        "port": 17500,
        "nonce": "nonce-1",
        "shortCode": short_code,
        "exp": exp,
    }


def test_pairing_failure_window_prunes_stale_state_and_honors_existing_lock(monkeypatch):
    monkeypatch.setattr(mobile_pairing.time, "time", lambda: 1_000.0)
    mobile_pairing._pairing_failures.update(
        {
            "locked": {"attempts": [999.0], "locked_until": 1_010.2},
            "active": {"attempts": [999.0], "locked_until": 0.0},
            "stale": {"attempts": [100.0], "locked_until": 0.0},
        }
    )

    assert mobile_pairing.pairing_failure_retry_after(["locked", "active", "stale", ""]) == 11
    assert mobile_pairing._pairing_failures["active"]["attempts"] == [999.0]
    assert "stale" not in mobile_pairing._pairing_failures

    assert mobile_pairing.record_pairing_failure(["locked", ""]) == 11
    mobile_pairing.clear_pairing_failures(["locked", ""])
    assert "locked" not in mobile_pairing._pairing_failures


def test_pairing_shortcode_collision_and_exhaustion_fallback(monkeypatch):
    mobile_pairing._short_codes["100001"] = "existing"
    values = iter((1, 2))
    monkeypatch.setattr(mobile_pairing.secrets, "randbelow", lambda _limit: next(values))
    assert mobile_pairing._gen_short_code() == "100002"

    monkeypatch.setattr(mobile_pairing.secrets, "randbelow", lambda _limit: 1)
    fallback = mobile_pairing._gen_short_code()
    assert fallback == "100002"
    assert fallback not in mobile_pairing._short_codes


def test_pairing_shortcode_is_reserved_atomically(monkeypatch):
    issued_codes: list[str] = []

    def _record_locked_generation() -> str:
        assert mobile_pairing._lock.locked()
        code = f"{100_001 + len(issued_codes):06d}"
        issued_codes.append(code)
        return code

    monkeypatch.setattr(mobile_pairing, "_gen_short_code", _record_locked_generation)

    payload = mobile_pairing.issue_pairing_nonce(
        host="192.168.10.2",
        port=17500,
        issuer_user_id=7,
        subject_user_id=7,
        subject_username="admin",
        tenant_id=11,
        company_brand="tenant-11",
    )

    assert payload["shortCode"] == "100001"
    assert mobile_pairing._short_codes["100001"] == payload["nonce"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"issuer_user_id": 0}, "有效管理用户"),
        ({"account_kind": "admin", "token_scope": "enterprise_pairing"}, "无效"),
    ],
)
def test_pairing_nonce_rejects_unbound_or_cross_scope_issue(overrides, message):
    kwargs = {
        "host": "192.168.10.2",
        "port": 17500,
        "issuer_user_id": 7,
        "subject_user_id": 7,
        "subject_username": "admin",
        "tenant_id": 11,
        "company_brand": "tenant-11",
    }
    kwargs.update(overrides)

    with pytest.raises(ValueError, match=message):
        mobile_pairing.issue_pairing_nonce(**kwargs)


def test_pairing_nonce_store_fails_closed_for_missing_expired_and_malformed_codes(
    monkeypatch,
):
    monkeypatch.setattr(mobile_pairing.time, "time", lambda: 1_000.0)

    assert mobile_pairing.consume_pairing_nonce("missing") is None
    assert mobile_pairing.lookup_pairing_nonce("") is None
    assert mobile_pairing.lookup_pairing_nonce("missing") is None
    assert mobile_pairing.lookup_by_shortcode("abc") is None
    assert mobile_pairing.lookup_by_shortcode("000000") is None
    assert mobile_pairing.consume_by_shortcode("000000") is None

    expired = _nonce_record(exp=999)
    mobile_pairing._nonces["nonce-1"] = expired
    mobile_pairing._short_codes["123456"] = "nonce-1"
    assert mobile_pairing.lookup_pairing_nonce("nonce-1") is None
    assert mobile_pairing.lookup_by_shortcode("123456") is None
    assert mobile_pairing.consume_pairing_nonce("nonce-1") is None

    # Old payloads may lack a short code.  They remain consumable by nonce and
    # must not try to mutate the short-code index.
    mobile_pairing._nonces["legacy"] = _nonce_record(exp=1_001, short_code="")
    assert mobile_pairing.consume_pairing_nonce("legacy")["nonce"] == "nonce-1"


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX ownership check")
def test_runtime_secret_rejects_non_file_foreign_owner_and_broken_shell_value(
    tmp_path,
    monkeypatch,
):
    directory = tmp_path / "snapshot-dir"
    directory.mkdir(mode=0o700)
    assert runtime_secret._safe_snapshot(directory) is False

    snapshot = tmp_path / "runtime.env"
    snapshot.write_text(
        "# ignored\nBROKEN\nXCAGI_MARKET_INTERNAL_API_KEY='unterminated\n",
        encoding="utf-8",
    )
    snapshot.chmod(0o600)
    assert runtime_secret._safe_snapshot(snapshot) is True
    monkeypatch.setattr(os, "getuid", lambda: snapshot.stat().st_uid + 1)
    assert runtime_secret._safe_snapshot(snapshot) is False

    monkeypatch.setattr(os, "getuid", lambda: snapshot.stat().st_uid)
    monkeypatch.setenv("MODSTORE_DAILY_ENV_SNAPSHOT", str(snapshot))
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)
    assert runtime_secret.local_runtime_secret("XCAGI_MARKET_INTERNAL_API_KEY") == ""


def test_runtime_secret_continues_in_priority_order_and_handles_open_failure(
    tmp_path,
    monkeypatch,
):
    snapshot = tmp_path / "runtime.env"
    snapshot.write_text(
        "XCAGI_MARKET_INTERNAL_API_KEY='second-key'\n",
        encoding="utf-8",
    )
    snapshot.chmod(0o600)
    monkeypatch.setenv("MODSTORE_DAILY_ENV_SNAPSHOT", str(snapshot))
    monkeypatch.delenv("MODSTORE_INTERNAL_API_KEY", raising=False)
    monkeypatch.delenv("XCAGI_MARKET_INTERNAL_API_KEY", raising=False)
    assert (
        runtime_secret.local_runtime_secret(
            "MODSTORE_INTERNAL_API_KEY", "XCAGI_MARKET_INTERNAL_API_KEY"
        )
        == "second-key"
    )

    broken = SimpleNamespace(open=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(runtime_secret, "_snapshot_path", lambda: broken)
    monkeypatch.setattr(runtime_secret, "_safe_snapshot", lambda _path: True)
    assert runtime_secret.local_runtime_secret("MODSTORE_INTERNAL_API_KEY") == ""


class _RedisProbe:
    def __init__(self, *, get_result=None, error: bool = False):
        self.get_result = get_result
        self.error = error
        self.set_calls: list[tuple[str, str, int]] = []

    def get(self, _key):
        if self.error:
            raise OSError("redis unavailable")
        return self.get_result

    def set(self, key, value, *, ttl):
        if self.error:
            raise OSError("redis unavailable")
        self.set_calls.append((key, value, ttl))


def test_mobile_refresh_blacklist_uses_redis_and_degrades_to_process_memory(monkeypatch):
    import app.utils.redis_cache as redis_cache

    monkeypatch.setattr(redis_cache, "get_redis_cache", lambda: (_ for _ in ()).throw(OSError()))
    assert mobile_jwt._redis_blacklist() is None

    seen = _RedisProbe(get_result="1")
    monkeypatch.setattr(mobile_jwt, "_redis_blacklist", lambda: seen)
    assert mobile_jwt._refresh_jti_seen("seen") is True

    unavailable = _RedisProbe(error=True)
    monkeypatch.setattr(mobile_jwt, "_redis_blacklist", lambda: unavailable)
    assert mobile_jwt._refresh_jti_seen("local") is False
    mobile_jwt._mark_refresh_jti_used("local", 30)
    assert mobile_jwt._refresh_jti_seen("local") is True

    healthy = _RedisProbe()
    monkeypatch.setattr(mobile_jwt, "_redis_blacklist", lambda: healthy)
    mobile_jwt._mark_refresh_jti_used("stored", 45)
    assert healthy.set_calls == [("mobile_refresh_used:stored", "1", 45)]


def test_mobile_jwt_rejects_non_numeric_binding_and_incomplete_refresh(monkeypatch):
    assert (
        mobile_jwt._relay_token_is_current(
            {
                "session_id": "mobile-management-invalid",
                "user_id": "not-an-int",
                "paired_by_user_id": 7,
            }
        )
        is False
    )
    assert (
        mobile_jwt._relay_token_is_current(
            {
                "session_id": "mobile-relay-invalid",
                "user_id": 7,
                "paired_by_user_id": "not-an-int",
            }
        )
        is False
    )

    monkeypatch.setattr(
        mobile_jwt,
        "verify_mobile_jwt",
        lambda _token: {
            "typ": "refresh",
            "jti": "fresh-jti",
            "user_id": None,
            "session_id": "mobile-relay-current",
        },
    )
    monkeypatch.setattr(mobile_jwt, "_refresh_jti_seen", lambda _jti: False)
    assert mobile_jwt.refresh_mobile_access_token("token") is None
    assert mobile_jwt._optional_int("not-an-int") is None


def test_pairing_helpers_cover_runtime_and_environment_port_fallbacks(tmp_path, monkeypatch):
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    port_file = runtime / "api.port"
    port_file.write_text("17500", encoding="utf-8")
    monkeypatch.setattr(pairing_helpers, "_REPO_ROOT", tmp_path)
    assert pairing_helpers._read_runtime_api_port(5000) == 17500

    port_file.write_text("invalid", encoding="utf-8")
    assert pairing_helpers._read_runtime_api_port(5000) == 5000
    assert pairing_helpers._request_host_port(_request("host:not-a-port")) == 0

    monkeypatch.setattr(pairing_helpers, "_read_runtime_api_port", lambda: 0)
    monkeypatch.setenv("XCAGI_API_PORT", "17501")
    assert pairing_helpers._pairing_issue_port(_request("host"), 0) == 17501
    monkeypatch.setenv("XCAGI_API_PORT", "invalid")
    monkeypatch.delenv("FASTAPI_PORT", raising=False)
    assert pairing_helpers._pairing_issue_port(_request("host"), 0) == 5000


def test_pairing_helpers_normalize_default_ports_hosts_and_payload_without_code(monkeypatch):
    assert pairing_helpers._pairing_reachable_port(None, 0) == 5000
    assert pairing_helpers._pairing_api_base_url("https://192.168.1.2/path?q=1", 0) == (
        "http://192.168.1.2:5000/"
    )
    assert pairing_helpers._host_is_private_or_loopback("192.168.1.2") is True
    assert pairing_helpers._host_is_private_or_loopback("8.8.8.8") is False
    assert pairing_helpers._host_is_private_or_loopback("localhost") is True
    assert pairing_helpers._host_is_private_or_loopback("printer.local") is True
    assert pairing_helpers._host_is_private_or_loopback("example.com") is False

    monkeypatch.setattr(pairing_helpers, "_backend_listens_loopback_only", lambda: False)
    enriched = pairing_helpers._enrich_pairing_payload(
        {
            "host": "192.168.1.2",
            "port": 17500,
            "nonce": "nonce",
            "issuer_user_id": 7,
            "tenant_id": 11,
        }
    )
    assert "code" not in enriched
    assert "issuer_user_id" not in enriched
    assert "tenant_id" not in enriched
    assert enriched["qr_json"]["code"] == ""


def test_backend_listen_host_respects_both_environment_names(monkeypatch):
    monkeypatch.delenv("XCAGI_API_HOST", raising=False)
    monkeypatch.setenv("FASTAPI_HOST", "127.0.0.1")
    assert pairing_helpers._backend_listen_host() == "127.0.0.1"
    assert pairing_helpers._backend_listens_loopback_only() is True

    monkeypatch.setenv("XCAGI_API_HOST", "0.0.0.0")
    assert pairing_helpers._backend_listen_host() == "0.0.0.0"
    assert pairing_helpers._backend_listens_loopback_only() is False
