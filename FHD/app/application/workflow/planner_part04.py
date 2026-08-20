"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from app.application.workflow.planner_llmworkflowplanner_mixin01 import (
    _LLMWorkflowPlannerPart01Mixin,
)
from app.application.workflow.planner_llmworkflowplanner_mixin02 import (
    _LLMWorkflowPlannerPart02Mixin,
)


def _facade():
    return importlib.import_module("app.application.workflow.planner")


class LLMWorkflowPlanner(_LLMWorkflowPlannerPart01Mixin, _LLMWorkflowPlannerPart02Mixin):
    pass
