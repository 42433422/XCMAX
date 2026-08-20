# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.planner")


from app.application.workflow.planner_llmworkflowplanner_mixin01__llmworkflowplannerpart01mixin_mixin01 import (
    __LLMWorkflowPlannerPart01MixinPart01Mixin,
)
from app.application.workflow.planner_llmworkflowplanner_mixin01__llmworkflowplannerpart01mixin_mixin02 import (
    __LLMWorkflowPlannerPart01MixinPart02Mixin,
)
from app.application.workflow.planner_llmworkflowplanner_mixin01__llmworkflowplannerpart01mixin_mixin03 import (
    __LLMWorkflowPlannerPart01MixinPart03Mixin,
)


class _LLMWorkflowPlannerPart01Mixin(
    __LLMWorkflowPlannerPart01MixinPart01Mixin,
    __LLMWorkflowPlannerPart01MixinPart02Mixin,
    __LLMWorkflowPlannerPart01MixinPart03Mixin,
):
    pass
