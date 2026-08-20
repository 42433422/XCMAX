# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_ai_pipeline")


from modstore_server.employee_ai_pipeline_part01_part01_part01 import (
    Intent as Intent,
    WorkflowChoice as WorkflowChoice,
    EmployeeConfigV2 as EmployeeConfigV2,
    SuggestedSkill as SuggestedSkill,
    _is_project_analysis_intent as _is_project_analysis_intent,
    PricingHint as PricingHint,
    _parse_json as _parse_json,
    stage_parse_intent as stage_parse_intent,
    stage_resolve_workflow as stage_resolve_workflow,
    stage_design_v2 as stage_design_v2,
    _build_employee_runtime_prompt as _build_employee_runtime_prompt,
    _quality_gate_system_prompt as _quality_gate_system_prompt,
    stage_suggest_skills as stage_suggest_skills,
)
from modstore_server.employee_ai_pipeline_part01_part01_part02 import (
    stage_suggest_pricing as stage_suggest_pricing,
    stage_assemble as stage_assemble,
    _build_vibe_coding_prompt as _build_vibe_coding_prompt,
    GeneratedCode as GeneratedCode,
)
