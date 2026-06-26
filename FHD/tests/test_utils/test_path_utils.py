"""
工具函数测试
"""

import os

import pytest

from app.utils.path_utils import (
    ensure_dir,
    get_base_dir,
    get_data_dir,
    get_desktop_state_dir,
)


class TestPathUtils:
    """路径工具测试"""

    def test_get_data_dir(self):
        data_dir = get_data_dir()
        assert data_dir is not None
        assert isinstance(data_dir, str)

    def test_get_base_dir(self):
        base_dir = get_base_dir()
        assert base_dir is not None
        assert os.path.exists(base_dir)

    def test_ensure_dir(self):
        test_dir = os.path.join(get_data_dir(), "test_dir_" + str(os.getpid()))
        try:
            result = ensure_dir(test_dir)
            assert os.path.exists(test_dir)
        finally:
            if os.path.exists(test_dir):
                os.rmdir(test_dir)


class TestDesktopStateDir:
    """桌面态目录：必须稳定，绝不回落到源码/仓库目录（云中继配对凭证分裂的根因防回归）。"""

    def test_honours_explicit_desktop_env(self, monkeypatch, tmp_path):
        target = tmp_path / "desktop-state"
        monkeypatch.setenv("XCAGI_DESKTOP_DATA_DIR", str(target))
        assert get_desktop_state_dir() == str(target)
        assert target.is_dir()

    def test_falls_back_to_data_env(self, monkeypatch, tmp_path):
        target = tmp_path / "data-state"
        monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)
        monkeypatch.setenv("XCAGI_DATA_DIR", str(target))
        assert get_desktop_state_dir() == str(target)

    def test_never_returns_repo_source_dir(self, monkeypatch):
        # 关键不变量：源码直跑时也绝不能落在仓库根（否则桌面会以与手机已配对 relay
        # 不同的身份去轮询，手机派单永远卡在「排队中」）。
        monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)
        monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
        state_dir = get_desktop_state_dir()
        assert isinstance(state_dir, str)
        assert os.path.isdir(state_dir)
        assert os.path.realpath(state_dir) != os.path.realpath(get_base_dir())
        assert state_dir.rstrip(os.sep).endswith("XCAGI")

    def test_stable_across_cwd_changes(self, monkeypatch, tmp_path):
        monkeypatch.delenv("XCAGI_DESKTOP_DATA_DIR", raising=False)
        monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
        first = get_desktop_state_dir()
        prev = os.getcwd()
        try:
            os.chdir(tmp_path)
            assert get_desktop_state_dir() == first
        finally:
            os.chdir(prev)
