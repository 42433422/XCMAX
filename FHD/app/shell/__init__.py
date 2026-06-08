"""app.shell — Shell 层模块集合。

承载从 ``backend/shell/`` 迁出的、与部署/外部集成相关的 shell 式脚本与工具
(例如 ``taiyangniao_attendance/`` 考勤数据转换、``mod_database_gate`` 等)。

使用约定:``from app.shell.<subpkg>.<module> import <symbol>``。
"""

from . import mod_database_gate  # noqa: F401  # 保持历史隐式导入行为

__all__ = ["mod_database_gate"]
