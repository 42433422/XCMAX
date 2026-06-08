"""考勤转换相关能力（SDK re-export）。

供 ``attendance-industry`` Mod 使用（legacy: ``taiyangniao-pro``）。未来任务 B 会把 ``app.shell.taiyangniao_attendance.*``
整体搬回 ``mods/attendance-industry/backend/attendance/``，届时本模块可以被移除
或缩减为空壳（保留 import 面以避免 Mod 侧突然断裂）。
"""

from __future__ import annotations

try:
    from app.shell.taiyangniao_attendance.convert import convert_attendance_file  # noqa: F401
    from app.shell.taiyangniao_attendance.paths import attendance_workspace_root  # noqa: F401
except ModuleNotFoundError:

    def convert_attendance_file(*_args, **_kwargs):  # type: ignore[misc]
        raise RuntimeError(
            "attendance-industry mod 未安装（考勤转换不可用）。"
            "请确认 FHD/mods/attendance-industry/ 已安装。"
        )

    def attendance_workspace_root(*_args, **_kwargs):  # type: ignore[misc]
        raise RuntimeError(
            "attendance-industry mod 未安装（考勤工作区不可用）。"
            "请确认 FHD/mods/attendance-industry/ 已安装。"
        )

__all__ = ["attendance_workspace_root", "convert_attendance_file"]
