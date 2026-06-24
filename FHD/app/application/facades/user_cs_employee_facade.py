"""用户客服员工域门面：路由层通过本门面访问 user_cs_employee_runner，不直接依赖 app.services。"""

from app.services.user_cs_employee_runner import EMPLOYEE_MOD_ID, run_user_cs_employee

__all__ = [
    "EMPLOYEE_MOD_ID",
    "run_user_cs_employee",
]
