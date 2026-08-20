# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.super_employee_service")


from app.application.super_employee_service_superemployeeservice_mixin03__superemployeeservicepart03mixin_mixin01 import (
    __SuperEmployeeServicePart03MixinPart01Mixin,
)
from app.application.super_employee_service_superemployeeservice_mixin03__superemployeeservicepart03mixin_mixin02 import (
    __SuperEmployeeServicePart03MixinPart02Mixin,
)


class _SuperEmployeeServicePart03Mixin(
    __SuperEmployeeServicePart03MixinPart01Mixin, __SuperEmployeeServicePart03MixinPart02Mixin
):
    pass
