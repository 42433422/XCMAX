"""Compatibility import retaining the canonical employee admission module identity."""

from __future__ import annotations

import sys

from app.application.admin_control import employee_run as _canonical
from app.application.admin_control.employee_run import (
    EmployeeBackend as EmployeeBackend,
)
from app.application.admin_control.employee_run import (
    EmployeeRunner as EmployeeRunner,
)
from app.application.admin_control.employee_run import (
    EmployeeWork as EmployeeWork,
)
from app.application.admin_control.employee_run import (
    employee_task_id as employee_task_id,
)
from app.application.admin_control.employee_run import (
    execute_admitted_employee as execute_admitted_employee,
)
from app.application.admin_control.employee_run import (
    read_employee_receipt as read_employee_receipt,
)

sys.modules[__name__] = _canonical
