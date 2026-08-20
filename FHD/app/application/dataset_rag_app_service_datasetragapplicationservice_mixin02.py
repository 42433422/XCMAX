# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.dataset_rag_app_service")


from app.application.dataset_rag_app_service_datasetragapplicationservice_mixin02__datasetragapplicationservicepart02mixin_mixin01 import (
    __DatasetRagApplicationServicePart02MixinPart01Mixin,
)
from app.application.dataset_rag_app_service_datasetragapplicationservice_mixin02__datasetragapplicationservicepart02mixin_mixin02 import (
    __DatasetRagApplicationServicePart02MixinPart02Mixin,
)


class _DatasetRagApplicationServicePart02Mixin(
    __DatasetRagApplicationServicePart02MixinPart01Mixin,
    __DatasetRagApplicationServicePart02MixinPart02Mixin,
):
    pass
