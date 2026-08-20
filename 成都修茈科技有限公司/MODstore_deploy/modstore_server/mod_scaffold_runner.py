# isort: skip_file
# ruff: noqa: E402, F401
"""Mod AI 脚手架：LLM 生成 manifest + zip 导入（供 /api/mods/ai-scaffold 与工作台编排复用）。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import py_compile
import re
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modman.manifest_util import read_manifest
from modman.repo_config import load_config, resolved_library
from modman.store import import_zip
from modstore_server.employee_ai_scaffold import (
    SYSTEM_PROMPT_EMPLOYEE,
    build_employee_pack_zip,
    parse_employee_pack_llm_json,
)
from modstore_server.employee_pack_export import (
    build_employee_pack_manifest_from_workflow,
)
from modstore_server.llm_chat_proxy import chat_dispatch
from modstore_server.llm_key_resolver import (
    KNOWN_PROVIDERS,
    OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
    resolve_api_key,
    resolve_base_url,
)
from modstore_server.mod_ai_scaffold import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_SUITE,
    _normalize_frontend_app,
    _normalize_frontend_menu,
    _sanitize_industry,
    build_scaffold_zip,
    merge_employees_for_blueprint_routes,
    normalize_mod_id,
    parse_llm_manifest_json,
    parse_llm_mod_suite_json,
    render_frontend_routes_js,
    render_generated_home_vue,
    render_suite_blueprints_py,
)
from modstore_server.models import (
    CatalogItem,
    User,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    add_user_mod,
    get_session_factory,
)

logger = logging.getLogger(__name__)


from modstore_server.mod_scaffold_runner_part01 import (
    _parse_positive_int as _parse_positive_int,
    _employee_node_ids_for_workflow as _employee_node_ids_for_workflow,
    _ensure_minimal_employee_workflow_graph as _ensure_minimal_employee_workflow_graph,
    _resolve_workflow_entry_pack_id as _resolve_workflow_entry_pack_id,
    analyze_mod_employee_readiness as analyze_mod_employee_readiness,
    modstore_library_path as modstore_library_path,
    _pick_employee_pack_catalog_record as _pick_employee_pack_catalog_record,
    materialize_employee_pack_if_missing as materialize_employee_pack_if_missing,
    rehydrate_employee_pack_bundles as rehydrate_employee_pack_bundles,
    mod_compileall_warnings as mod_compileall_warnings,
    employee_pack_consistency_warnings as employee_pack_consistency_warnings,
)

_logger = logging.getLogger(__name__)


from modstore_server.mod_scaffold_runner_part02 import (
    global_registered_employee_ids as global_registered_employee_ids,
    employee_pack_compileall_errors as employee_pack_compileall_errors,
    _collect_pack_depends_on_ids as _collect_pack_depends_on_ids,
    _collect_pack_skill_paths as _collect_pack_skill_paths,
    _manifest_validation_stage as _manifest_validation_stage,
    _consistency_check_stage as _consistency_check_stage,
    _xcemp_validation_stage as _xcemp_validation_stage,
    run_employee_pack_code_validation_report as run_employee_pack_code_validation_report,
    resolve_llm_provider_model as resolve_llm_provider_model,
    resolve_llm_provider_model_auto as resolve_llm_provider_model_auto,
)


from modstore_server.mod_scaffold_runner_part03 import (
    generate_workflow_for_intent as generate_workflow_for_intent,
    run_mod_ai_scaffold_async as run_mod_ai_scaffold_async,
    _suite_blueprint_file as _suite_blueprint_file,
    _suite_validation_summary as _suite_validation_summary,
    _json_response_format as _json_response_format,
    _mod_suite_industry_card_payload as _mod_suite_industry_card_payload,
    _mod_suite_ui_shell_payload as _mod_suite_ui_shell_payload,
    _mod_suite_user_lines as _mod_suite_user_lines,
    _repair_mod_suite_json_async as _repair_mod_suite_json_async,
    generate_mod_suite_blueprint_async as generate_mod_suite_blueprint_async,
    import_mod_suite_repository as import_mod_suite_repository,
    write_mod_suite_industry_card as write_mod_suite_industry_card,
    write_mod_suite_ui_shell as write_mod_suite_ui_shell,
    _openapi_node_summary as _openapi_node_summary,
    create_mod_suite_workflows_async as create_mod_suite_workflows_async,
    run_mod_suite_workflow_sandboxes as run_mod_suite_workflow_sandboxes,
    write_mod_suite_blueprint as write_mod_suite_blueprint,
    run_mod_suite_mod_sandbox as run_mod_suite_mod_sandbox,
)


from modstore_server.mod_scaffold_runner_part04 import (
    run_mod_suite_ai_scaffold_async as run_mod_suite_ai_scaffold_async,
    _index_mod_with_vibe as _index_mod_with_vibe,
    attach_nl_workflow_to_employee_pack_dir as attach_nl_workflow_to_employee_pack_dir,
    run_employee_ai_scaffold_async as run_employee_ai_scaffold_async,
)


from modstore_server.mod_scaffold_runner_part05 import (
    register_mod_employee_packs_async as register_mod_employee_packs_async,
    _employee_node_ids_for_workflow_cfg as _employee_node_ids_for_workflow_cfg,
    _ensure_workflow_start_end_skeleton as _ensure_workflow_start_end_skeleton,
    patch_workflow_graph_employee_nodes as patch_workflow_graph_employee_nodes,
)
