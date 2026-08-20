# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.dataset_rag_app_service")


from app.application.dataset_rag_app_service_datasetragapplicationservice_mixin01__datasetragapplicationservicepart01mixin_mixin01 import (
    __DatasetRagApplicationServicePart01MixinPart01Mixin,
)
from app.application.dataset_rag_app_service_datasetragapplicationservice_mixin01__datasetragapplicationservicepart01mixin_mixin02 import (
    __DatasetRagApplicationServicePart01MixinPart02Mixin,
)
from app.application.dataset_rag_app_service_datasetragapplicationservice_mixin01__datasetragapplicationservicepart01mixin_mixin03 import (
    __DatasetRagApplicationServicePart01MixinPart03Mixin,
)


class _DatasetRagApplicationServicePart01Mixin(
    __DatasetRagApplicationServicePart01MixinPart01Mixin,
    __DatasetRagApplicationServicePart01MixinPart02Mixin,
    __DatasetRagApplicationServicePart01MixinPart03Mixin,
):
    pass
