# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.sales_app_service")


from app.application.sales_app_service_salesappservice_mixin01__salesappservicepart01mixin_mixin01 import (
    __SalesAppServicePart01MixinPart01Mixin,
)
from app.application.sales_app_service_salesappservice_mixin01__salesappservicepart01mixin_mixin02 import (
    __SalesAppServicePart01MixinPart02Mixin,
)
from app.application.sales_app_service_salesappservice_mixin01__salesappservicepart01mixin_mixin03 import (
    __SalesAppServicePart01MixinPart03Mixin,
)


class _SalesAppServicePart01Mixin(
    __SalesAppServicePart01MixinPart01Mixin,
    __SalesAppServicePart01MixinPart02Mixin,
    __SalesAppServicePart01MixinPart03Mixin,
):
    pass
