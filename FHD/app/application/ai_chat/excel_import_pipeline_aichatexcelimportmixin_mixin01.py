# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat.excel_import_pipeline")


from app.application.ai_chat.excel_import_pipeline_aichatexcelimportmixin_mixin01__aichatexcelimportmixinpart01mixin_mixin01 import (
    __AIChatExcelImportMixinPart01MixinPart01Mixin,
)
from app.application.ai_chat.excel_import_pipeline_aichatexcelimportmixin_mixin01__aichatexcelimportmixinpart01mixin_mixin02 import (
    __AIChatExcelImportMixinPart01MixinPart02Mixin,
)


class _AIChatExcelImportMixinPart01Mixin(
    __AIChatExcelImportMixinPart01MixinPart01Mixin, __AIChatExcelImportMixinPart01MixinPart02Mixin
):
    pass
