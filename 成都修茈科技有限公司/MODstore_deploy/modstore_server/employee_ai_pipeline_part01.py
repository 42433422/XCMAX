# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations


from modstore_server.employee_ai_pipeline_part01_part01 import (
    _facade as _facade,
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
    stage_suggest_pricing as stage_suggest_pricing,
    stage_assemble as stage_assemble,
    _build_vibe_coding_prompt as _build_vibe_coding_prompt,
    GeneratedCode as GeneratedCode,
)
