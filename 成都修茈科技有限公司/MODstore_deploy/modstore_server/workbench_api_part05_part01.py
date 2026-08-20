# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


from modstore_server.workbench_api_part05_part01_part01 import (
    employee_ai_draft as employee_ai_draft,
    employee_ai_refine_prompt as employee_ai_refine_prompt,
    EmployeeBenchRequest as EmployeeBenchRequest,
    EmployeePublishRequest as EmployeePublishRequest,
    employee_bench_test as employee_bench_test,
    employee_publish as employee_publish,
    EmployeeSyncTestRequest as EmployeeSyncTestRequest,
)
from modstore_server.workbench_api_part05_part01_part02 import (
    employee_sync_test as employee_sync_test,
    EmployeeSaveBody as EmployeeSaveBody,
)
