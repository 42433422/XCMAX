"""employee_pack HTTP 面（共享运行时派发，MODstore 生成）。"""

from __future__ import annotations

import os

from app.mod_sdk.employee_pack_runtime import build_employee_pack

EMPLOYEE_ID = "employee-pack-curator"
STEM = "employee_pack_curator"
LABEL = "员工包策展员"

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

globals().update(build_employee_pack(EMPLOYEE_ID, STEM, LABEL, _BACKEND_DIR))
