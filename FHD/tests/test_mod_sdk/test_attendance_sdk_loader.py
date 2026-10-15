"""考勤 SDK loader（app.mod_sdk.attendance）单一正本与降级行为门禁。

引擎唯一正本：``FHD/XCAGI/mods/attendance-industry/backend/attendance_engine/``
（EXPORT_ONLY 运行时副本 SSOT）。本文件守护三件事：
1. SDK 导出面（convert/paths/parser）全部解析到 mod 正本；
2. ``ensure_attendance_engine_on_path`` 幂等；
3. mod 缺失时降级为显式 RuntimeError（不静默、不误指 taiyangniao-pro）。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_BACKEND = (REPO_ROOT / "XCAGI" / "mods" / "attendance-industry" / "backend").resolve()


def test_engine_exports_resolve_to_mod_copy():
    sdk = importlib.import_module("app.mod_sdk.attendance")
    assert callable(sdk.convert_attendance_file)
    assert callable(sdk.attendance_workspace_root)
    assert callable(sdk.parse_attendance_workbook)

    import attendance_engine.convert as engine_convert

    assert Path(engine_convert.__file__).resolve().is_relative_to(ENGINE_BACKEND)


def test_ensure_attendance_engine_on_path_idempotent():
    from app.mod_sdk.attendance import ensure_attendance_engine_on_path

    backend = ensure_attendance_engine_on_path()
    assert Path(backend).is_dir()
    first_index = sys.path.index(backend)

    assert ensure_attendance_engine_on_path() == backend
    assert sys.path.count(backend) == 1
    assert sys.path.index(backend) == first_index


def test_missing_mod_falls_back_to_runtime_error(monkeypatch):
    from app.infrastructure.mods import mod_manager

    monkeypatch.setattr(mod_manager, "_default_mods_root", lambda: "")
    monkeypatch.setattr(mod_manager, "_all_mods_roots", lambda _primary: [])
    # sys.modules 与父包属性必须同步还原：`import a.b.c as x` 绑定的是父包属性，
    # 而 from-import 解析的是 sys.modules——只清一边会让两个口径拿到不同对象。
    monkeypatch.delitem(sys.modules, "app.mod_sdk.attendance", raising=False)
    import app.mod_sdk as mod_sdk_pkg

    monkeypatch.delattr(mod_sdk_pkg, "attendance", raising=False)

    sdk = importlib.import_module("app.mod_sdk.attendance")
    with pytest.raises(RuntimeError, match="attendance-industry mod 未安装"):
        sdk.convert_attendance_file()
    with pytest.raises(RuntimeError, match="attendance-industry mod 未安装"):
        sdk.parse_attendance_workbook()
