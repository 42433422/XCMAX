# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.super_employee_service")


from app.application.super_employee_service_superemployeeservice_mixin01__superemployeeservicepart01mixin_mixin01 import (
    __SuperEmployeeServicePart01MixinPart01Mixin,
)
from app.application.super_employee_service_superemployeeservice_mixin01__superemployeeservicepart01mixin_mixin02 import (
    __SuperEmployeeServicePart01MixinPart02Mixin,
)
from app.application.super_employee_service_superemployeeservice_mixin01__superemployeeservicepart01mixin_mixin03 import (
    __SuperEmployeeServicePart01MixinPart03Mixin,
)


class _SuperEmployeeServicePart01Mixin(
    __SuperEmployeeServicePart01MixinPart01Mixin,
    __SuperEmployeeServicePart01MixinPart02Mixin,
    __SuperEmployeeServicePart01MixinPart03Mixin,
):
    pass
