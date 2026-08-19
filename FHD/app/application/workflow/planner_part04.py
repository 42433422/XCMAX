# ruff: noqa
# mypy: ignore-errors
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.workflow.planner')

class LLMWorkflowPlanner(_facade()._LLMWorkflowPlannerPart01Mixin, _facade()._LLMWorkflowPlannerPart02Mixin):
    pass
