"""Version sync replacement, mapping, dry-run and write regressions."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dev import version_sync  # noqa: E402
from scripts.dev.verify_version_anchors import ANCHORS  # noqa: E402


class TestReplaceVersionInText:
    def test_replaces_first_match_only(self):
        text = 'version = "10.0.0"\npython_version = "3.11"\n'
        pattern = r'version\s*=\s*"([\d.]+)"'
        new_text, changed = version_sync._replace_version_in_text(text, pattern, "10.0.1")
        assert changed is True
        assert 'version = "10.0.1"' in new_text
        assert 'python_version = "3.11"' in new_text

    def test_no_change_when_already_target(self):
        text = 'version = "10.0.0"\n'
        pattern = r'version\s*=\s*"([\d.]+)"'
        new_text, changed = version_sync._replace_version_in_text(text, pattern, "10.0.0")
        assert changed is False
        assert new_text == text


class TestVersionMapping:
    def test_four_part_product_version_maps_to_three_part_toolchain_version(self):
        assert version_sync._derive_toolchain_version("1.0.0.0") == "1.0.0"

    def test_invalid_product_version_is_rejected(self):
        with pytest.raises(ValueError):
            version_sync._derive_toolchain_version("stable")

    def test_preserves_surrounding_text(self):
        text = 'FastAPI(version="9.9.9")\n'
        pattern = r'version="([\d.]+)"'
        new_text, changed = version_sync._replace_version_in_text(text, pattern, "10.0.0")
        assert changed is True
        assert new_text == 'FastAPI(version="10.0.0")\n'

    def test_no_match_returns_unchanged(self):
        text = "no version here\n"
        pattern = r'version\s*=\s*"([\d.]+)"'
        new_text, changed = version_sync._replace_version_in_text(text, pattern, "10.0.0")
        assert changed is False
        assert new_text == text


class TestSyncDryRun:
    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        anchor_file = tmp_path / "pyproject.toml"
        anchor_file.write_text('version = "9.9.9"\n', encoding="utf-8")

        fake_anchors = [("pyproject.toml", r'version\s*=\s*"([\d.]+)"', "product")]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")
        monkeypatch.setattr(version_sync, "_toolchain_version", lambda: "10.0.0")

        code = version_sync.sync(apply=False)
        assert code == 1
        assert anchor_file.read_text(encoding="utf-8") == 'version = "9.9.9"\n'

    @pytest.mark.parametrize("apply", [False, True])
    def test_all_synced_returns_0(self, tmp_path, monkeypatch, apply):
        anchor_file = tmp_path / "pyproject.toml"
        anchor_file.write_text('version = "10.0.0"\n', encoding="utf-8")

        fake_anchors = [("pyproject.toml", r'version\s*=\s*"([\d.]+)"', "product")]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")
        monkeypatch.setattr(version_sync, "_toolchain_version", lambda: "10.0.0")

        code = version_sync.sync(apply=apply)
        assert code == 0


class TestSyncApply:
    def test_apply_writes_new_version(self, tmp_path, monkeypatch):
        anchor_file = tmp_path / "pyproject.toml"
        anchor_file.write_text('version = "9.9.9"\n', encoding="utf-8")

        fake_anchors = [("pyproject.toml", r'version\s*=\s*"([\d.]+)"', "product")]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")
        monkeypatch.setattr(version_sync, "_toolchain_version", lambda: "10.0.0")

        code = version_sync.sync(apply=True)
        assert code == 0
        assert anchor_file.read_text(encoding="utf-8") == 'version = "10.0.0"\n'

    def test_apply_does_not_touch_python_version(self, tmp_path, monkeypatch):
        anchor_file = tmp_path / "pyproject.toml"
        original = 'version = "9.9.9"\npython_version = "3.11"\n'
        anchor_file.write_text(original, encoding="utf-8")

        fake_anchors = [("pyproject.toml", r'version\s*=\s*"([\d.]+)"', "product")]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")
        monkeypatch.setattr(version_sync, "_toolchain_version", lambda: "10.0.0")

        code = version_sync.sync(apply=True)
        assert code == 0
        content = anchor_file.read_text(encoding="utf-8")
        assert 'version = "10.0.0"' in content
        assert 'python_version = "3.11"' in content

    def test_apply_missing_file_returns_3(self, tmp_path, monkeypatch):
        fake_anchors = [("nonexistent.toml", r'version\s*=\s*"([\d.]+)"', "product")]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")
        monkeypatch.setattr(version_sync, "_toolchain_version", lambda: "10.0.0")

        code = version_sync.sync(apply=True)
        assert code == 3


class TestAnchorsConsistency:
    def test_anchors_is_list_of_tuples(self):
        assert isinstance(ANCHORS, list)
        assert len(ANCHORS) >= 8  # 至少 8 个锚点
        for item in ANCHORS:
            assert isinstance(item, tuple)
            assert len(item) == 3
            assert isinstance(item[0], str)
            assert isinstance(item[1], str)
            assert item[2] in {"product", "toolchain"}

    def test_version_sync_imports_same_anchors(self):
        assert version_sync.ANCHORS is ANCHORS


def test_sync_updates_a_declared_dart_part(tmp_path, monkeypatch):
    library = tmp_path / "mobile_api.dart"
    part = tmp_path / "config.part.dart"
    library.write_text("part 'config.part.dart';\n")
    part.write_text("static const versionName = '1.0.0.5';\n")
    monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
    anchors = [("mobile_api.dart", r"versionName\s*=\s*'([\d.]+)'", "product")]
    monkeypatch.setattr(version_sync, "ANCHORS", anchors)
    assert version_sync.sync(False, "1.0.0.6") == 1
    assert "1.0.0.5" in part.read_text()
    assert version_sync.sync(True, "1.0.0.6") == 0
    assert "1.0.0.6" in part.read_text()
    assert library.read_text() == "part 'config.part.dart';\n"
