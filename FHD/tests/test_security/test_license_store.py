"""license_store 测试 — 覆盖密钥签发/吊销、会话管理、审计、白名单、访问申请等。"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from app.security import license_store


@pytest.fixture(autouse=True)
def _use_tmp_db(monkeypatch, tmp_path):
    """每个测试使用独立的临时 SQLite 文件，并重置 schema 初始化状态。"""
    from app.security.lan_config import reset_lan_config_cache

    db_path = tmp_path / "test_license.db"
    monkeypatch.setenv("LAN_LICENSE_DB_PATH", str(db_path))
    monkeypatch.setenv("LAN_GUARD_ENABLED", "0")
    # 重置 lru_cache 使 get_lan_config() 读取新的 LAN_LICENSE_DB_PATH
    reset_lan_config_cache()
    # 重置模块级 _initialized 标志，使每个测试重新创建 schema
    license_store._initialized = False
    yield
    license_store._initialized = False
    reset_lan_config_cache()


# ---------------------------------------------------------------------------
# 密钥管理
# ---------------------------------------------------------------------------


class TestIssueKey:
    def test_issue_returns_plaintext_and_key(self):
        plaintext, key = license_store.issue_key(label="test", created_by="admin")
        assert plaintext
        assert len(plaintext) > 10
        assert key.label == "test"
        assert key.created_by == "admin"
        assert key.revoked_at is None
        assert key.use_count == 0

    def test_issue_with_custom_plaintext(self):
        plaintext, key = license_store.issue_key(plaintext="my-secret-key")
        assert plaintext == "my-secret-key"
        assert key.id > 0

    def test_issue_with_expiry(self):
        exp = int(time.time()) + 3600
        _, key = license_store.issue_key(expires_at=exp)
        assert key.expires_at == exp

    def test_issue_admin_key(self):
        _, key = license_store.issue_key(is_admin=True)
        assert key.is_admin is True

    def test_issue_empty_plaintext_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            license_store.issue_key(plaintext="   ")


class TestListKeys:
    def test_empty(self):
        keys = license_store.list_keys()
        assert keys == []

    def test_includes_revoked(self):
        license_store.issue_key(label="active")
        pt, key = license_store.issue_key(label="to-revoke")
        license_store.revoke_key(key.id)
        keys = license_store.list_keys(include_revoked=True)
        assert len(keys) == 2

    def test_excludes_revoked(self):
        license_store.issue_key(label="active")
        pt, key = license_store.issue_key(label="to-revoke")
        license_store.revoke_key(key.id)
        keys = license_store.list_keys(include_revoked=False)
        assert len(keys) == 1


class TestFindKeyByPlaintext:
    def test_found(self):
        pt, _ = license_store.issue_key(plaintext="find-me")
        key = license_store.find_key_by_plaintext("find-me")
        assert key is not None
        assert key.label == ""

    def test_not_found(self):
        key = license_store.find_key_by_plaintext("nonexistent")
        assert key is None


class TestRevokeKey:
    def test_revoke_active(self):
        _, key = license_store.issue_key()
        ok = license_store.revoke_key(key.id, actor="admin", ip="127.0.0.1")
        assert ok is True
        keys = license_store.list_keys(include_revoked=False)
        assert len(keys) == 0

    def test_revoke_already_revoked(self):
        _, key = license_store.issue_key()
        license_store.revoke_key(key.id)
        ok = license_store.revoke_key(key.id)
        assert ok is False

    def test_revoke_nonexistent(self):
        ok = license_store.revoke_key(99999)
        assert ok is False


class TestMarkKeyUsed:
    def test_increments_use_count(self):
        _, key = license_store.issue_key()
        license_store.mark_key_used(key.id)
        keys = license_store.list_keys()
        assert keys[0].use_count == 1
        assert keys[0].last_used_at is not None


class TestHasAnyActiveKey:
    def test_false_when_empty(self):
        assert license_store.has_any_active_key() is False

    def test_true_after_issue(self):
        license_store.issue_key()
        assert license_store.has_any_active_key() is True

    def test_false_after_revoke(self):
        _, key = license_store.issue_key()
        license_store.revoke_key(key.id)
        assert license_store.has_any_active_key() is False


class TestHasAnyAdminKey:
    def test_false_when_no_admin(self):
        license_store.issue_key(is_admin=False)
        assert license_store.has_any_admin_key() is False

    def test_true_with_admin(self):
        license_store.issue_key(is_admin=True)
        assert license_store.has_any_admin_key() is True


# ---------------------------------------------------------------------------
# 会话管理
# ---------------------------------------------------------------------------


class TestRecordSession:
    def test_record_and_get(self):
        _, key = license_store.issue_key()
        now = int(time.time())
        sess = license_store.record_session(
            jti="jti-1",
            key_id=key.id,
            kid="kid-1",
            ip="10.0.0.1",
            user_agent="test",
            issued_at=now,
            expires_at=now + 3600,
        )
        assert sess.jti == "jti-1"
        assert sess.key_id == key.id

    def test_get_active_session(self):
        now = int(time.time())
        license_store.record_session(
            jti="jti-active",
            key_id=None,
            kid="k",
            ip="",
            user_agent="",
            issued_at=now,
            expires_at=now + 3600,
        )
        sess = license_store.get_active_session_by_jti("jti-active")
        assert sess is not None
        assert sess.jti == "jti-active"

    def test_get_revoked_session_returns_none(self):
        now = int(time.time())
        license_store.record_session(
            jti="jti-rev",
            key_id=None,
            kid="k",
            ip="",
            user_agent="",
            issued_at=now,
            expires_at=now + 3600,
        )
        license_store.revoke_session("jti-rev")
        assert license_store.get_active_session_by_jti("jti-rev") is None


class TestListSessions:
    def test_active_only(self):
        now = int(time.time())
        license_store.record_session(
            jti="jti-a",
            key_id=None,
            kid="k",
            ip="",
            user_agent="",
            issued_at=now,
            expires_at=now + 3600,
        )
        sessions = license_store.list_sessions(active_only=True)
        assert len(sessions) >= 1

    def test_all_includes_revoked(self):
        now = int(time.time())
        license_store.record_session(
            jti="jti-b",
            key_id=None,
            kid="k",
            ip="",
            user_agent="",
            issued_at=now,
            expires_at=now + 3600,
        )
        license_store.revoke_session("jti-b")
        sessions = license_store.list_sessions(active_only=False)
        assert len(sessions) >= 1


class TestRevokeSession:
    def test_revoke_active(self):
        now = int(time.time())
        license_store.record_session(
            jti="jti-r",
            key_id=None,
            kid="k",
            ip="",
            user_agent="",
            issued_at=now,
            expires_at=now + 3600,
        )
        ok = license_store.revoke_session("jti-r", actor="admin")
        assert ok is True

    def test_revoke_nonexistent(self):
        ok = license_store.revoke_session("nonexistent-jti")
        assert ok is False


class TestTouchSession:
    def test_touch(self):
        now = int(time.time())
        license_store.record_session(
            jti="jti-t",
            key_id=None,
            kid="k",
            ip="",
            user_agent="",
            issued_at=now,
            expires_at=now + 3600,
        )
        license_store.touch_session("jti-t")
        sess = license_store.get_active_session_by_jti("jti-t")
        assert sess is not None
        assert sess.last_seen_at is not None


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------


class TestWriteAudit:
    def test_write_and_list(self):
        license_store.write_audit(action="test.action", target="t1", actor="admin")
        entries = license_store.list_audit(limit=10)
        assert len(entries) >= 1
        assert entries[0].action == "test.action"


class TestListAudit:
    def test_limit(self):
        for i in range(5):
            license_store.write_audit(action=f"action-{i}")
        entries = license_store.list_audit(limit=3)
        assert len(entries) == 3


# ---------------------------------------------------------------------------
# 白名单
# ---------------------------------------------------------------------------


class TestIsIpExplicitlyAllowed:
    def test_not_allowed(self):
        assert license_store.is_ip_explicitly_allowed("10.0.0.1") is False

    def test_empty_ip(self):
        assert license_store.is_ip_explicitly_allowed("") is False

    def test_allowed_after_approve(self):
        req = license_store.create_access_request(ip="10.0.0.2")
        license_store.approve_access_request(req.id, actor="admin")
        assert license_store.is_ip_explicitly_allowed("10.0.0.2") is True


class TestTouchAllowedClient:
    def test_touch_existing(self):
        req = license_store.create_access_request(ip="10.0.0.3")
        license_store.approve_access_request(req.id, actor="admin")
        license_store.touch_allowed_client("10.0.0.3")
        clients = license_store.list_allowed_clients()
        assert len(clients) >= 1


class TestListAllowedClients:
    def test_empty(self):
        clients = license_store.list_allowed_clients()
        assert clients == []


class TestRevokeAllowedClient:
    def test_revoke(self):
        req = license_store.create_access_request(ip="10.0.0.4")
        result = license_store.approve_access_request(req.id, actor="admin")
        client_id = None
        for c in license_store.list_allowed_clients():
            if c.ip == "10.0.0.4":
                client_id = c.id
        assert client_id is not None
        ok = license_store.revoke_allowed_client(client_id, actor="admin")
        assert ok is True

    def test_revoke_nonexistent(self):
        ok = license_store.revoke_allowed_client(99999)
        assert ok is False


# ---------------------------------------------------------------------------
# 访问申请
# ---------------------------------------------------------------------------


class TestCreateAccessRequest:
    def test_create(self):
        req = license_store.create_access_request(ip="192.168.1.1", device_label="Phone")
        assert req.ip == "192.168.1.1"
        assert req.status == "pending"
        assert req.device_label == "Phone"

    def test_empty_ip_raises(self):
        with pytest.raises(ValueError):
            license_store.create_access_request(ip="")

    def test_update_existing_pending(self):
        req1 = license_store.create_access_request(ip="192.168.1.2", note="first")
        req2 = license_store.create_access_request(ip="192.168.1.2", note="updated")
        assert req2.note == "updated"
        assert req2.id == req1.id


class TestGetLatestAccessRequestByIp:
    def test_found(self):
        license_store.create_access_request(ip="192.168.1.3")
        req = license_store.get_latest_access_request_by_ip("192.168.1.3")
        assert req is not None
        assert req.ip == "192.168.1.3"

    def test_not_found(self):
        assert license_store.get_latest_access_request_by_ip("0.0.0.0") is None

    def test_empty_ip(self):
        assert license_store.get_latest_access_request_by_ip("") is None


class TestListAccessRequests:
    def test_all(self):
        license_store.create_access_request(ip="192.168.1.10")
        reqs = license_store.list_access_requests()
        assert len(reqs) >= 1

    def test_filter_by_status(self):
        license_store.create_access_request(ip="192.168.1.11")
        reqs = license_store.list_access_requests(status="pending")
        assert len(reqs) >= 1

    def test_filter_all(self):
        license_store.create_access_request(ip="192.168.1.12")
        reqs = license_store.list_access_requests(status="all")
        assert len(reqs) >= 1


class TestApproveAccessRequest:
    def test_approve(self):
        req = license_store.create_access_request(ip="192.168.1.20")
        result = license_store.approve_access_request(req.id, actor="admin", review_note="ok")
        assert result is not None
        assert result.status == "approved"

    def test_approve_nonexistent(self):
        result = license_store.approve_access_request(99999)
        assert result is None

    def test_approve_creates_allowlist_entry(self):
        req = license_store.create_access_request(ip="192.168.1.21")
        license_store.approve_access_request(req.id, actor="admin")
        assert license_store.is_ip_explicitly_allowed("192.168.1.21") is True

    def test_approve_updates_existing_allowlist(self):
        req1 = license_store.create_access_request(ip="192.168.1.22")
        license_store.approve_access_request(req1.id, actor="admin")
        req2 = license_store.create_access_request(ip="192.168.1.22", note="re-approve")
        license_store.approve_access_request(req2.id, actor="admin")
        assert license_store.is_ip_explicitly_allowed("192.168.1.22") is True


class TestRejectAccessRequest:
    def test_reject(self):
        req = license_store.create_access_request(ip="192.168.1.30")
        result = license_store.reject_access_request(req.id, actor="admin", review_note="bad")
        assert result is not None
        assert result.status == "rejected"

    def test_reject_nonexistent(self):
        result = license_store.reject_access_request(99999)
        assert result is None


# ---------------------------------------------------------------------------
# to_dict 序列化
# ---------------------------------------------------------------------------


class TestToDict:
    def test_key(self):
        _, key = license_store.issue_key(label="dict-test")
        d = license_store.to_dict_key(key)
        assert d["label"] == "dict-test"
        assert "id" in d

    def test_session(self):
        now = int(time.time())
        sess = license_store.record_session(
            jti="jti-dict",
            key_id=None,
            kid="k",
            ip="",
            user_agent="",
            issued_at=now,
            expires_at=now + 3600,
        )
        d = license_store.to_dict_session(sess)
        assert d["jti"] == "jti-dict"

    def test_audit(self):
        license_store.write_audit(action="dict.test", target="t")
        entries = license_store.list_audit(limit=1)
        d = license_store.to_dict_audit(entries[0])
        assert d["action"] == "dict.test"

    def test_access_request(self):
        req = license_store.create_access_request(ip="192.168.1.40")
        d = license_store.to_dict_access_request(req)
        assert d["ip"] == "192.168.1.40"

    def test_allowed_client(self):
        req = license_store.create_access_request(ip="192.168.1.41")
        license_store.approve_access_request(req.id, actor="admin")
        clients = license_store.list_allowed_clients()
        found = [c for c in clients if c.ip == "192.168.1.41"]
        assert len(found) == 1
        d = license_store.to_dict_allowed_client(found[0])
        assert d["ip"] == "192.168.1.41"
