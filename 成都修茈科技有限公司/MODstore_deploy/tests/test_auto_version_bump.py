from __future__ import annotations

import modstore_server.auto_version_bump as auto_version_bump_module
from modstore_server.auto_version_bump import auto_version_bump, prepend_changelog


def test_prepend_changelog_inserts_entry_after_unreleased(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## Unreleased\n\n## 1.0.0\n", encoding="utf-8")

    assert prepend_changelog(str(tmp_path), "### Bug Fixes\n- 修复版本升级") is True

    updated = changelog.read_text(encoding="utf-8")
    assert updated.index("## Unreleased") < updated.index("修复版本升级")
    assert updated.index("修复版本升级") < updated.index("## 1.0.0")


def test_daily_bump_skips_before_writing_when_version_request_is_pending(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        auto_version_bump_module,
        "_pending_version_change_request_id",
        lambda: 204,
    )
    monkeypatch.setattr(
        auto_version_bump_module,
        "get_current_version",
        lambda _root: (_ for _ in ()).throw(AssertionError("must not inspect or write source")),
    )

    result = auto_version_bump(str(tmp_path))

    assert result == {
        "ok": True,
        "skipped": True,
        "reason": "pending version change request",
        "change_request_id": 204,
    }
