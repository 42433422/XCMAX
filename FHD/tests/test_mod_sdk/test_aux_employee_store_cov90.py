"""补充覆盖 aux_employee_store 的 _repo_mod_seed_dirs 与 install_aux_employee_pack_from_repo_seed。

聚焦此前未覆盖行: 28-52 (种子目录解析) / 120-143 (从内置种子安装)。
所有外部依赖 (环境变量/文件系统/mod_manager) 均隔离: 用 tmp_path + monkeypatch 环境变量,
patch get_mod_manager 与 shutil 以保证离线、确定性、快速。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.mod_sdk.aux_employee_store import (
    AUX_EMPLOYEE_PACK_MOD_IDS,
    _repo_mod_seed_dirs,
    install_aux_employee_pack_from_repo_seed,
)

PACK_ID = AUX_EMPLOYEE_PACK_MOD_IDS[0]


# ---------------------------------------------------------------------------
# _repo_mod_seed_dirs  (行 28-52)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_seed_env(monkeypatch):
    """默认清空所有种子相关环境变量, 避免被宿主环境污染。"""
    for key in ("XCAGI_MODS_ROOT", "XCAGI_ROOT"):
        monkeypatch.delenv(key, raising=False)
    yield


class TestRepoModSeedDirs:
    def test_includes_repo_mods_when_exists(self):
        """仓库根的 mods 目录真实存在时应被纳入 (行 31-33)。"""
        dirs = _repo_mod_seed_dirs()
        # 计算源文件 parents[2] 即仓库根
        here = Path(
            __import__("app.mod_sdk.aux_employee_store", fromlist=["__file__"]).__file__
        ).resolve()
        repo = here.parents[2]
        repo_mods = repo / "mods"
        if repo_mods.is_dir():
            resolved = {str(p.resolve()) for p in dirs}
            assert str(repo_mods.resolve()) in resolved
        else:
            # 该仓库无 mods 目录也合法, 至少返回一个 list
            assert isinstance(dirs, list)

    def test_returns_list_of_paths(self):
        dirs = _repo_mod_seed_dirs()
        assert isinstance(dirs, list)
        assert all(isinstance(p, Path) for p in dirs)

    def test_xcagi_mods_root_env_added(self, tmp_path, monkeypatch):
        """XCAGI_MODS_ROOT 指向存在目录时被加入 (行 34-38)。"""
        extra = tmp_path / "custom_mods"
        extra.mkdir()
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(extra))
        dirs = _repo_mod_seed_dirs()
        resolved = {str(p.resolve()) for p in dirs}
        assert str(extra.resolve()) in resolved

    def test_xcagi_mods_root_env_nonexistent_ignored(self, tmp_path, monkeypatch):
        """XCAGI_MODS_ROOT 指向不存在目录时被忽略 (行 37 false 分支)。"""
        missing = tmp_path / "does_not_exist"
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(missing))
        dirs = _repo_mod_seed_dirs()
        resolved = {str(p.resolve()) for p in dirs}
        assert str(missing.resolve()) not in resolved

    def test_xcagi_mods_root_blank_skipped(self, monkeypatch):
        """空白 XCAGI_MODS_ROOT 不触发 Path 解析 (行 35 false 分支)。"""
        monkeypatch.setenv("XCAGI_MODS_ROOT", "   ")
        dirs = _repo_mod_seed_dirs()
        # 仅断言未抛错且返回 list
        assert isinstance(dirs, list)

    def test_xcagi_root_env_appends_mods_subdir(self, tmp_path, monkeypatch):
        """XCAGI_ROOT/mods 存在时被加入 (行 39-43)。"""
        root = tmp_path / "xcagi"
        (root / "mods").mkdir(parents=True)
        monkeypatch.setenv("XCAGI_ROOT", str(root))
        dirs = _repo_mod_seed_dirs()
        resolved = {str(p.resolve()) for p in dirs}
        assert str((root / "mods").resolve()) in resolved

    def test_xcagi_root_env_without_mods_subdir_ignored(self, tmp_path, monkeypatch):
        """XCAGI_ROOT 下无 mods 子目录则不加入 (行 42 false 分支)。"""
        root = tmp_path / "xcagi_no_mods"
        root.mkdir()
        monkeypatch.setenv("XCAGI_ROOT", str(root))
        dirs = _repo_mod_seed_dirs()
        resolved = {str(p.resolve()) for p in dirs}
        assert str((root / "mods").resolve()) not in resolved

    def test_deduplicates_same_path(self, tmp_path, monkeypatch):
        """同一目录同时由两个环境变量指向时只出现一次 (行 44-51 去重)。"""
        shared = tmp_path / "shared_mods"
        shared.mkdir()
        # XCAGI_MODS_ROOT 指向 shared; XCAGI_ROOT 指向 tmp_path 使 tmp_path/mods... 不重复,
        # 用 XCAGI_MODS_ROOT 两次无法, 改为让 XCAGI_ROOT 的 mods 子目录就是 shared。
        root = tmp_path / "rootdir"
        root.mkdir()
        # 让 root/mods 实际指向 shared 的等价路径: 直接令 XCAGI_ROOT=tmp_path 且其 mods 即 shared？
        # 简化: 用 monkeypatch 把 _repo_mod_seed_dirs 内部解析的 repo mods 与 env 指向同一目录。
        monkeypatch.setenv("XCAGI_MODS_ROOT", str(shared))
        # 再令 XCAGI_ROOT 指向使其 mods 子目录 == shared: 创建 root/mods 为 shared 的父链不行,
        # 改用符号链接保证 resolve 相同。
        link_root = tmp_path / "linkroot"
        link_root.mkdir()
        (link_root / "mods").symlink_to(shared, target_is_directory=True)
        monkeypatch.setenv("XCAGI_ROOT", str(link_root))
        dirs = _repo_mod_seed_dirs()
        resolved = [str(p.resolve()) for p in dirs]
        assert resolved.count(str(shared.resolve())) == 1


# ---------------------------------------------------------------------------
# install_aux_employee_pack_from_repo_seed  (行 120-143)
# ---------------------------------------------------------------------------


class TestInstallAuxEmployeePackFromRepoSeed:
    def test_rejects_non_aux_pack_id(self):
        """非触点员工包 id 直接返回失败 (行 120-122)。"""
        ok, msg = install_aux_employee_pack_from_repo_seed("not-a-pack")
        assert ok is False
        assert msg == "非触点员工包"

    def test_rejects_blank_id(self):
        ok, msg = install_aux_employee_pack_from_repo_seed("   ")
        assert ok is False
        assert msg == "非触点员工包"

    def test_not_found_when_no_seed_dir_has_manifest(self, tmp_path):
        """所有种子目录都没有该包的 manifest 时返回未找到 (行 124-130)。"""
        empty = tmp_path / "empty_seed"
        empty.mkdir()
        with patch(
            "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
            return_value=[empty],
        ):
            ok, msg = install_aux_employee_pack_from_repo_seed(PACK_ID)
        assert ok is False
        assert PACK_ID in msg
        assert "未找到内置员工包" in msg

    def test_success_copies_and_loads(self, tmp_path):
        """找到种子后复制到 mods_root 并触发 load_all_mods (行 131-140)。"""
        seed_root = tmp_path / "seed"
        src = seed_root / PACK_ID
        src.mkdir(parents=True)
        manifest = {"id": PACK_ID, "name": "Pack", "version": "1.2.3"}
        (src / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (src / "extra.txt").write_text("payload", encoding="utf-8")

        mods_root = tmp_path / "live_mods"
        mods_root.mkdir()
        mm = MagicMock()
        mm.mods_root = str(mods_root)

        with (
            patch(
                "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
                return_value=[seed_root],
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mm,
            ),
        ):
            ok, msg = install_aux_employee_pack_from_repo_seed(PACK_ID)

        assert ok is True
        assert PACK_ID in msg
        assert "已从内置种子安装" in msg
        # 真实副作用: 文件被复制
        dest = mods_root / PACK_ID
        assert (dest / "manifest.json").is_file()
        assert (dest / "extra.txt").read_text(encoding="utf-8") == "payload"
        # 真实副作用: load_all_mods 被调用一次
        mm.load_all_mods.assert_called_once_with()

    def test_success_overwrites_existing_dest(self, tmp_path):
        """目标目录已存在时先 rmtree 再 copytree (行 136-138)。"""
        seed_root = tmp_path / "seed"
        src = seed_root / PACK_ID
        src.mkdir(parents=True)
        (src / "manifest.json").write_text(json.dumps({"id": PACK_ID}), encoding="utf-8")
        (src / "new_file.txt").write_text("fresh", encoding="utf-8")

        mods_root = tmp_path / "live_mods"
        dest = mods_root / PACK_ID
        dest.mkdir(parents=True)
        # 预置一个旧文件, 安装后应被清除
        (dest / "stale.txt").write_text("old", encoding="utf-8")

        mm = MagicMock()
        mm.mods_root = str(mods_root)

        with (
            patch(
                "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
                return_value=[seed_root],
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mm,
            ),
        ):
            ok, msg = install_aux_employee_pack_from_repo_seed(PACK_ID)

        assert ok is True
        # 旧文件被清除
        assert not (dest / "stale.txt").exists()
        # 新内容到位
        assert (dest / "new_file.txt").read_text(encoding="utf-8") == "fresh"

    def test_oserror_during_copy_returns_failure(self, tmp_path):
        """复制过程中抛 OSError 时捕获并返回错误信息 (行 141-143)。"""
        seed_root = tmp_path / "seed"
        src = seed_root / PACK_ID
        src.mkdir(parents=True)
        (src / "manifest.json").write_text(json.dumps({"id": PACK_ID}), encoding="utf-8")

        mods_root = tmp_path / "live_mods"
        mods_root.mkdir()
        mm = MagicMock()
        mm.mods_root = str(mods_root)

        with (
            patch(
                "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
                return_value=[seed_root],
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mm,
            ),
            patch(
                "app.mod_sdk.aux_employee_store.shutil.copytree",
                side_effect=OSError("disk full"),
            ),
        ):
            ok, msg = install_aux_employee_pack_from_repo_seed(PACK_ID)

        assert ok is False
        assert msg == "disk full"
        # 出错时不应继续 load_all_mods
        mm.load_all_mods.assert_not_called()

    def test_activate_param_does_not_change_signature_behavior(self, tmp_path):
        """activate 关键字参数被接受 (默认 True), 显式传 False 仍走相同复制逻辑。"""
        seed_root = tmp_path / "seed"
        src = seed_root / PACK_ID
        src.mkdir(parents=True)
        (src / "manifest.json").write_text(json.dumps({"id": PACK_ID}), encoding="utf-8")
        mods_root = tmp_path / "live_mods"
        mods_root.mkdir()
        mm = MagicMock()
        mm.mods_root = str(mods_root)

        with (
            patch(
                "app.mod_sdk.aux_employee_store._repo_mod_seed_dirs",
                return_value=[seed_root],
            ),
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                return_value=mm,
            ),
        ):
            ok, msg = install_aux_employee_pack_from_repo_seed(PACK_ID, activate=False)

        assert ok is True
        assert (mods_root / PACK_ID / "manifest.json").is_file()
