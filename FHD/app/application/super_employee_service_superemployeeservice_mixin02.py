# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.super_employee_service")


from app.application.super_employee_service_superemployeeservice_mixin02__superemployeeservicepart02mixin_mixin01 import (
    __SuperEmployeeServicePart02MixinPart01Mixin,
)
from app.application.super_employee_service_superemployeeservice_mixin02__superemployeeservicepart02mixin_mixin02 import (
    __SuperEmployeeServicePart02MixinPart02Mixin,
)


class _SuperEmployeeServicePart02Mixin(
    __SuperEmployeeServicePart02MixinPart01Mixin, __SuperEmployeeServicePart02MixinPart02Mixin
):
    pass
