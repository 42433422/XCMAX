# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


from modstore_server.workbench_api_part01_part01_part01 import (
    _contains_uploaded_docx as _contains_uploaded_docx,
    _canonical_workbench_intent as _canonical_workbench_intent,
    _employee_asset_publish_catalog_from_env as _employee_asset_publish_catalog_from_env,
    _enrich_artifact_skill_aliases as _enrich_artifact_skill_aliases,
    _workbench_session_store_dir as _workbench_session_store_dir,
    _workbench_session_file as _workbench_session_file,
    _persist_workbench_session_unlocked as _persist_workbench_session_unlocked,
    _load_workbench_session_unlocked as _load_workbench_session_unlocked,
    _hydrate_workbench_session_unlocked as _hydrate_workbench_session_unlocked,
    _persist_workbench_session as _persist_workbench_session,
    EmployeeAiDraftBody as EmployeeAiDraftBody,
    EmployeeAiRefinePromptBody as EmployeeAiRefinePromptBody,
    WorkbenchResearchBody as WorkbenchResearchBody,
    WorkbenchWebSearchBody as WorkbenchWebSearchBody,
    WorkbenchSessionCreateBody as WorkbenchSessionCreateBody,
    _parse_workbench_session_create as _parse_workbench_session_create,
)
from modstore_server.workbench_api_part01_part01_part02 import (
    _default_steps as _default_steps,
    _set_step as _set_step,
    _record_craft_step_skip_metric as _record_craft_step_skip_metric,
    _fail_session as _fail_session,
    _finalize_session_done as _finalize_session_done,
)
