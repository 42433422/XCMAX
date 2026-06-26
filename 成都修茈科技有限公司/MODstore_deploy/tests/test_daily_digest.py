"""每日摘要 HTML 构建冒烟测试。"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from types import SimpleNamespace

import modstore_server.models as models


def test_parse_daily_digest_recipient_emails() -> None:
    from modstore_server.daily_digest import parse_daily_digest_recipient_emails

    assert parse_daily_digest_recipient_emails("") == []
    assert parse_daily_digest_recipient_emails("a@b.com") == ["a@b.com"]
    assert parse_daily_digest_recipient_emails("a@b.com,c@d.com") == ["a@b.com", "c@d.com"]
    assert parse_daily_digest_recipient_emails("a@b.com; c@d.com") == ["a@b.com", "c@d.com"]


def test_count_on_duty_employees_uses_duty_roster() -> None:
    from modstore_server.daily_digest import count_on_duty_employees
    from modstore_server.duty_roster import all_planned_employee_ids

    assert count_on_duty_employees() == len(all_planned_employee_ids())


def test_build_digest_html_contains_sections(tmp_path, monkeypatch):
    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "digest.sqlite"))
    monkeypatch.setenv("MODSTORE_REPO_ROOT", str(tmp_path))
    models.init_db()

    from modstore_server.daily_digest import build_digest_html
    from modstore_server.tools import doc_consistency_checker

    def _fake_consistency(root):
        return {
            "status": "ok",
            "total_errors": 0,
            "total_issues": 0,
            "issues": [],
        }

    monkeypatch.setattr(doc_consistency_checker, "run_full_consistency_check", _fake_consistency)

    html = build_digest_html()
    assert "MODstore" in html
    assert "系统状态" in html
    assert "每日运营摘要" in html
    assert "编制在岗" in html or "在岗员工" in html
    assert "文档一致性" in html

    models._engine = None
    models._SessionFactory = None


def test_build_digest_approval_bundle_empty_pending() -> None:
    from modstore_server.daily_digest import build_digest_approval_bundle

    expires = datetime.utcnow() + timedelta(hours=36)
    batch, html_out = build_digest_approval_bundle(
        pending=[],
        auth_email="ops@example.com",
        expires_at=expires,
    )
    assert len(batch) == 1
    kinds = sorted((t.kind or "") for t in batch)
    assert kinds == ["digest_identity"]
    assert "身份校验码" in html_out
    assert "当前无待部署分支" in html_out
    assert batch[0].authorized_email == "ops@example.com"


def test_build_digest_approval_bundle_avoids_existing_token_hash(monkeypatch) -> None:
    from modstore_server.daily_digest import build_digest_approval_bundle

    candidates = iter(["a1b2c3", "d4e5f6"])
    monkeypatch.setattr("secrets.token_hex", lambda n: next(candidates))
    existing = {hashlib.sha256("A1B2C3".encode("utf-8")).hexdigest()}

    batch, html_out = build_digest_approval_bundle(
        pending=[],
        auth_email="ops@example.com",
        expires_at=datetime.utcnow() + timedelta(hours=36),
        existing_token_hashes=existing,
    )

    expected = hashlib.sha256("D4E5F6".encode("utf-8")).hexdigest()
    assert batch[0].token_hash == expected
    assert "D4E5F6" in html_out


def test_build_digest_approval_bundle_with_pending_row() -> None:
    from modstore_server.daily_digest import build_digest_approval_bundle

    expires = datetime.utcnow() + timedelta(hours=36)
    row = SimpleNamespace(
        id=42,
        branch="feat/x",
        files_changed_count=3,
        diff_summary="add foo",
    )
    batch, html_out = build_digest_approval_bundle(
        pending=[row],
        auth_email="ops@example.com",
        expires_at=expires,
    )
    assert len(batch) == 2
    kinds = sorted((t.kind or "") for t in batch)
    assert kinds == ["approve_one", "digest_identity"]
    assert "待审批改动" in html_out
    assert "feat/x" in html_out
    assert "回复本邮件" in html_out
    assert "身份校验码" in html_out
