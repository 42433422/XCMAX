"""approval_dispatcher：部署链顺序与 reject_all。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.release_gate

import modstore_server.models as models
from modstore_server import approval_dispatcher as ad


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "approval.sqlite"))
    models.init_db()
    yield tmp_path
    models._engine = None
    models._SessionFactory = None


def test_deploy_staged_runs_three_commands_in_order(fresh_db, monkeypatch):
    sf = models.get_session_factory()
    with sf() as s:
        row = models.OpsStagedChange(
            branch="auto/daily-test",
            base_commit="a" * 7,
            head_commit="b" * 7,
            files_changed_count=1,
            diff_summary="x",
            status="pending",
        )
        s.add(row)
        s.commit()
        sid = int(row.id)

    calls: list[str] = []

    def fake_run_cmd(command_id: str, args: dict) -> dict:
        calls.append(command_id)
        return {"ok": True, "audit_log_id": len(calls)}

    monkeypatch.setattr(ad, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(
        "modstore_server.post_deploy_smoke.run_post_deploy_smoke",
        lambda: {"ok": True, "skipped": False, "probes": []},
    )
    res = ad.deploy_staged_change(sid)
    assert res["ok"] is True
    assert calls == ["git-push-branch", "local-sync-deploy", "http-probe-after-deploy"]


def test_reject_all_marks_pending(fresh_db, monkeypatch):
    sf = models.get_session_factory()
    exp = datetime.utcnow() + timedelta(hours=10)
    with sf() as s:
        s.add(
            models.OpsStagedChange(
                branch="b1",
                base_commit="a",
                head_commit="b",
                status="pending",
            )
        )
        tok = models.OpsApprovalToken(
            token_hash="a" * 64,
            kind="reject_all",
            payload_json="{}",
            authorized_email="u@qq.com",
            expires_at=exp,
        )
        s.add(tok)
        s.commit()
        tid = int(tok.id)

    r = ad.handle_token_row(tid, message_id="<m1@test>")
    assert r.get("ok") is True
    assert int(r.get("rejected") or 0) >= 1

    with sf() as s:
        row = s.query(models.OpsStagedChange).one()
        assert row.status == "rejected"
        t2 = s.get(models.OpsApprovalToken, tid)
        assert t2 is not None
        assert t2.used_at is not None


def test_digest_identity_ack_only(fresh_db):
    import hashlib

    plain = "A1B2C3"
    th = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    sf = models.get_session_factory()
    exp = datetime.utcnow() + timedelta(hours=10)
    with sf() as s:
        tok = models.OpsApprovalToken(
            token_hash=th,
            kind="digest_identity",
            payload_json='{"scope":"daily_digest"}',
            authorized_email="u@qq.com",
            expires_at=exp,
        )
        s.add(tok)
        s.commit()
        tid = int(tok.id)

    r = ad.handle_token_row(tid, message_id="<m2@test>")
    assert r.get("ok") is True
    assert r.get("identity_ack") is True
