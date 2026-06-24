"""测试 version_sync.py 的单元测试。

覆盖：
- _replace_version_in_text 纯函数（count=1 行为，避免 python_version 误匹配）
- sync() dry-run 不写盘
- sync() --apply 写盘（用 monkeypatch 指向 tmp_path）
- 复用 verify_version_anchors.ANCHORS 保持一致
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.dev import version_sync  # noqa: E402
from scripts.dev.verify_version_anchors import ANCHORS  # noqa: E402


class TestReplaceVersionInText:
    """_replace_version_in_text 纯函数测试。"""

    def test_replaces_first_match_only(self):
        """count=1：只替换第一个匹配，避免 python_version 误匹配。"""
        text = 'version = "10.0.0"\npython_version = "3.11"\n'
        pattern = r'version\s*=\s*"([\d.]+)"'
        new_text, changed = version_sync._replace_version_in_text(text, pattern, "10.0.1")
        assert changed is True
        assert 'version = "10.0.1"' in new_text
        # python_version 不应被改动
        assert 'python_version = "3.11"' in new_text

    def test_no_change_when_already_target(self):
        """已是目标版本时 changed=False。"""
        text = 'version = "10.0.0"\n'
        pattern = r'version\s*=\s*"([\d.]+)"'
        new_text, changed = version_sync._replace_version_in_text(text, pattern, "10.0.0")
        assert changed is False
        assert new_text == text

    def test_preserves_surrounding_text(self):
        """保留前后缀（如 version="..." 的引号和等号）。"""
        text = 'FastAPI(version="9.9.9")\n'
        pattern = r'version="([\d.]+)"'
        new_text, changed = version_sync._replace_version_in_text(text, pattern, "10.0.0")
        assert changed is True
        assert new_text == 'FastAPI(version="10.0.0")\n'

    def test_no_match_returns_unchanged(self):
        """无匹配时 changed=False，文本不变。"""
        text = "no version here\n"
        pattern = r'version\s*=\s*"([\d.]+)"'
        new_text, changed = version_sync._replace_version_in_text(text, pattern, "10.0.0")
        assert changed is False
        assert new_text == text


class TestSyncDryRun:
    """sync() dry-run 模式测试。"""

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        """dry-run 模式不写盘。"""
        # 在 tmp_path 下造一个锚点文件，版本号旧
        anchor_file = tmp_path / "pyproject.toml"
        anchor_file.write_text('version = "9.9.9"\n', encoding="utf-8")

        # monkeypatch ANCHORS 和 REPO_ROOT 指向 tmp_path
        fake_anchors = [("pyproject.toml", r'version\s*=\s*"([\d.]+)"')]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")

        code = version_sync.sync(apply=False)
        # dry-run 且有改动 → exit 1
        assert code == 1
        # 文件未被改写
        assert anchor_file.read_text(encoding="utf-8") == 'version = "9.9.9"\n'

    def test_dry_run_all_synced_returns_0(self, tmp_path, monkeypatch):
        """所有锚点已是目标版本时 dry-run 返回 0。"""
        anchor_file = tmp_path / "pyproject.toml"
        anchor_file.write_text('version = "10.0.0"\n', encoding="utf-8")

        fake_anchors = [("pyproject.toml", r'version\s*=\s*"([\d.]+)"')]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")

        code = version_sync.sync(apply=False)
        assert code == 0


class TestSyncApply:
    """sync() --apply 模式测试。"""

    def test_apply_writes_new_version(self, tmp_path, monkeypatch):
        """--apply 真写盘，把旧版本改成新版本。"""
        anchor_file = tmp_path / "pyproject.toml"
        anchor_file.write_text('version = "9.9.9"\n', encoding="utf-8")

        fake_anchors = [("pyproject.toml", r'version\s*=\s*"([\d.]+)"')]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")

        code = version_sync.sync(apply=True)
        assert code == 0
        assert anchor_file.read_text(encoding="utf-8") == 'version = "10.0.0"\n'

    def test_apply_does_not_touch_python_version(self, tmp_path, monkeypatch):
        """--apply 不会误改 python_version = "3.11"（count=1 保护）。"""
        anchor_file = tmp_path / "pyproject.toml"
        original = 'version = "9.9.9"\npython_version = "3.11"\n'
        anchor_file.write_text(original, encoding="utf-8")

        fake_anchors = [("pyproject.toml", r'version\s*=\s*"([\d.]+)"')]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")

        code = version_sync.sync(apply=True)
        assert code == 0
        content = anchor_file.read_text(encoding="utf-8")
        assert 'version = "10.0.0"' in content
        assert 'python_version = "3.11"' in content

    def test_apply_missing_file_returns_3(self, tmp_path, monkeypatch):
        """锚点文件不存在时返回 3（EXEC 错误）。"""
        fake_anchors = [("nonexistent.toml", r'version\s*=\s*"([\d.]+)"')]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")

        code = version_sync.sync(apply=True)
        assert code == 3

    def test_apply_all_synced_returns_0(self, tmp_path, monkeypatch):
        """所有锚点已是目标版本时 --apply 返回 0（no-op）。"""
        anchor_file = tmp_path / "pyproject.toml"
        anchor_file.write_text('version = "10.0.0"\n', encoding="utf-8")

        fake_anchors = [("pyproject.toml", r'version\s*=\s*"([\d.]+)"')]
        monkeypatch.setattr(version_sync, "ANCHORS", fake_anchors)
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: "10.0.0")

        code = version_sync.sync(apply=True)
        assert code == 0


class TestAnchorsConsistency:
    """version_sync 与 verify_version_anchors 共享 ANCHORS 的一致性。"""

    def test_anchors_is_list_of_tuples(self):
        """ANCHORS 格式正确：(rel_path, pattern)。"""
        assert isinstance(ANCHORS, list)
        assert len(ANCHORS) >= 8  # 至少 8 个锚点
        for item in ANCHORS:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], str)
            assert isinstance(item[1], str)

    def test_version_sync_imports_same_anchors(self):
        """version_sync 复用的 ANCHORS 与 verify_version_anchors 是同一对象。"""
        assert version_sync.ANCHORS is ANCHORS

    def test_anchors_cover_mobile_and_download(self):
        """扩展后的锚点覆盖鸿蒙 3 文件 + 官网下载 3 字段（防发布漂移）。"""
        paths = [p for p, _ in ANCHORS]
        assert "mobile-harmony/oh-package.json5" in paths
        assert "mobile-harmony/entry/oh-package.json5" in paths
        assert "mobile-harmony/AppScope/app.json5" in paths
        assert paths.count("config/download_release.json") == 3


class TestHarmonyVersionCode:
    """harmony_version_code 公式：major*10000 + minor*100 + patch。"""

    def test_baseline(self):
        assert version_sync.harmony_version_code("10.0.0") == 100000

    def test_minor_bump(self):
        assert version_sync.harmony_version_code("10.1.0") == 100100

    def test_patch_and_mixed(self):
        assert version_sync.harmony_version_code("10.0.3") == 100003
        assert version_sync.harmony_version_code("11.2.3") == 110203


class TestSetVersion:
    """set_version（软件自定版本）：写 VERSION.md 真相源后传播。"""

    def _fake_repo(self, tmp_path, monkeypatch, *, current="10.0.0"):
        (tmp_path / "VERSION.md").write_text(
            f"| **XCAGI 总版本** | `{current}` | x |\n\n*最后更新：2026-01-01*\n",
            encoding="utf-8",
        )
        (tmp_path / "pyproject.toml").write_text(f'version = "{current}"\n', encoding="utf-8")
        monkeypatch.setattr(version_sync, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(
            version_sync, "ANCHORS", [("pyproject.toml", r'version\s*=\s*"([\d.]+)"')]
        )
        monkeypatch.setattr(version_sync, "_canonical_version", lambda: current)

    def test_invalid_semver_returns_2(self, tmp_path, monkeypatch):
        self._fake_repo(tmp_path, monkeypatch)
        assert version_sync.set_version("10.1", None, apply=True) == 2

    def test_same_version_noop_returns_0(self, tmp_path, monkeypatch):
        self._fake_repo(tmp_path, monkeypatch)
        assert version_sync.set_version("10.0.0", None, apply=True) == 0
        # 未变更
        assert "`10.0.0`" in (tmp_path / "VERSION.md").read_text(encoding="utf-8")

    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        self._fake_repo(tmp_path, monkeypatch)
        rc = version_sync.set_version("10.1.0", None, apply=False)
        assert rc == 0
        # VERSION.md 与锚点都未落盘
        assert "`10.0.0`" in (tmp_path / "VERSION.md").read_text(encoding="utf-8")
        assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == 'version = "10.0.0"\n'

    def test_apply_writes_truth_source_and_anchor(self, tmp_path, monkeypatch):
        self._fake_repo(tmp_path, monkeypatch)
        rc = version_sync.set_version("10.1.0", None, apply=True)
        assert rc == 0
        vm = (tmp_path / "VERSION.md").read_text(encoding="utf-8")
        assert "`10.1.0`" in vm  # 真相源已改
        assert "version_sync.py --set 同步至 10.1.0" in vm  # 页脚溯源
        assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == 'version = "10.1.0"\n'
