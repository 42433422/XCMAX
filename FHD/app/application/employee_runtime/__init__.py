"""employee_pack 运行时：磁盘加载、V2 解析、EmployeeAgent 执行器。"""

from app.application.employee_runtime.executor import execute_employee_task_local
from app.application.employee_runtime.loader import (
    DIRECT_PYTHON_RUNTIME_MISSING_MSG,
    load_employee_pack_from_disk,
    pack_has_direct_python_runtime,
    parse_employee_config_v2,
    resolve_pack_dir,
)


def __getattr__(name: str):
    # 惰性导出 EmployeeAgent，避免 import 期与 executor 形成环。
    if name == "EmployeeAgent":
        from app.application.employee_runtime.agent import EmployeeAgent

        return EmployeeAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DIRECT_PYTHON_RUNTIME_MISSING_MSG",
    "EmployeeAgent",
    "execute_employee_task_local",
    "load_employee_pack_from_disk",
    "pack_has_direct_python_runtime",
    "parse_employee_config_v2",
    "resolve_pack_dir",
]
