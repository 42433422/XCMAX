"""考勤转换相关能力（SDK re-export）。

兼容既有 Mod import；客户转换实现由独立 ``sunbird-attendance-custom`` 包提供，
共享考勤包仅承载通用工作区和文件格式解析。
"""

from __future__ import annotations

try:
    from app.shell.taiyangniao_attendance.convert import convert_attendance_file  # noqa: F401
    from app.shell.taiyangniao_attendance.paths import attendance_workspace_root  # noqa: F401
except ModuleNotFoundError:

    def convert_attendance_file(*_args, **_kwargs):
        raise RuntimeError("太阳鸟考勤转换 Mod 未安装，请在当前账号的私有交付中安装。")

    def attendance_workspace_root(*_args, **_kwargs):
        raise RuntimeError("太阳鸟考勤转换 Mod 未安装，请在当前账号的私有交付中安装。")


__all__ = ["attendance_workspace_root", "convert_attendance_file"]
