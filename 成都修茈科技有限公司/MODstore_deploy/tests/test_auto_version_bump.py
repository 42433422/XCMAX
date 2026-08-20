from __future__ import annotations

from modstore_server.auto_version_bump import prepend_changelog


def test_prepend_changelog_inserts_entry_after_unreleased(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## Unreleased\n\n## 1.0.0\n", encoding="utf-8")

    assert prepend_changelog(str(tmp_path), "### Bug Fixes\n- 修复版本升级") is True

    updated = changelog.read_text(encoding="utf-8")
    assert updated.index("## Unreleased") < updated.index("修复版本升级")
    assert updated.index("修复版本升级") < updated.index("## 1.0.0")
