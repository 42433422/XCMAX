# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat.excel_import_pipeline")


from app.application.ai_chat.excel_import_pipeline_aichatexcelimportmixin_mixin02__aichatexcelimportmixinpart02mixin_mixin01 import (
    __AIChatExcelImportMixinPart02MixinPart01Mixin,
)
from app.application.ai_chat.excel_import_pipeline_aichatexcelimportmixin_mixin02__aichatexcelimportmixinpart02mixin_mixin02 import (
    __AIChatExcelImportMixinPart02MixinPart02Mixin,
)


class _AIChatExcelImportMixinPart02Mixin(
    __AIChatExcelImportMixinPart02MixinPart01Mixin, __AIChatExcelImportMixinPart02MixinPart02Mixin
):
    pass
