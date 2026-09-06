"""考勤转换相关能力（SDK re-export）。

供 ``attendance-industry`` Mod 及 legacy ``taiyangniao-pro`` 使用。考勤转换引擎的
唯一正本是 ``FHD/XCAGI/mods/attendance-industry/backend/taiyangniao_attendance/``
（EXPORT_ONLY 运行时副本 SSOT，见 ``scripts/dev/mods_ssot.py``）；本模块通过
mods root 解析加载它（仓库与打包桌面端同源），未安装时降级为显式 RuntimeError。
"""

from __future__ import annotations

import os
import sys

_ENGINE_MOD_ID = "attendance-industry"


def ensure_attendance_engine_on_path() -> str:
    """解析 attendance-industry 的 backend 目录并插入 sys.path，返回该目录。

    复用 mod_manager 的 mods root 解析（``XCAGI_MODS_ROOT`` env → 包相邻目录 →
    仓库布局），与 mod 加载同源。幂等：已在 sys.path 时不重复插入。
    """
    from app.infrastructure.mods import mod_manager as _mm

    for root in _mm._all_mods_roots(_mm._default_mods_root()):
        backend = _mm._backend_path_for_mod(os.path.join(root, _ENGINE_MOD_ID))
        if os.path.isdir(backend):
            if backend not in sys.path:
                sys.path.insert(0, backend)
            return backend
    raise ModuleNotFoundError(f"{_ENGINE_MOD_ID} mod 未安装（考勤引擎不可用）")


try:
    ensure_attendance_engine_on_path()
    from taiyangniao_attendance.convert import convert_attendance_file  # noqa: E402
    from taiyangniao_attendance.parser import parse_attendance_workbook  # noqa: E402
    from taiyangniao_attendance.paths import attendance_workspace_root  # noqa: E402
except ModuleNotFoundError:

    def convert_attendance_file(*_args, **_kwargs):
        raise RuntimeError(
            "attendance-industry mod 未安装（考勤转换不可用）。请确认 attendance-industry 已安装。"
        )

    def attendance_workspace_root(*_args, **_kwargs):
        raise RuntimeError(
            "attendance-industry mod 未安装（考勤工作区不可用）。"
            "请确认 attendance-industry 已安装。"
        )

    def parse_attendance_workbook(*_args, **_kwargs):
        raise RuntimeError(
            "attendance-industry mod 未安装（考勤解析不可用）。请确认 attendance-industry 已安装。"
        )


__all__ = [
    "attendance_workspace_root",
    "convert_attendance_file",
    "ensure_attendance_engine_on_path",
    "parse_attendance_workbook",
]
