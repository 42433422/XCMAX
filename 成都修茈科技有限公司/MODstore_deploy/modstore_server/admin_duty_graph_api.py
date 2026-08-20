# isort: skip_file
# ruff: noqa: E402, F401
"""管理员：在岗员工图执行能力与图级编排运行 API。"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    Tuple,
)

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from modstore_server.api.deps import require_admin
from modstore_server.catalog_quality import resolve_employee_pack_dir
from modstore_server.catalog_store import norm_pkg_id
from modstore_server.employee_executor import list_employees as list_employees_exec
from modstore_server.employee_runtime import (
    employee_pack_runtime_issues,
    load_employee_pack,
    parse_employee_config_v2,
)
from modstore_server.integrations.ops_action_handlers import OPS_COMMAND_REGISTRY
from modstore_server.llm_crypto import fernet_configured
from modstore_server.llm_key_resolver import KNOWN_PROVIDERS, credential_status
from modstore_server.models import (
    DutyGraphRun,
    DutyGraphRunNode,
    EmployeeExecutionMetric,
    OpsActionAuditLog,
    User,
    get_session_factory,
)
from modstore_server.services.employee import get_default_employee_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-duty-graph"])

_HIGH_RISK_HANDLERS = frozenset(
    {
        "shell_exec",
        "ssh_exec",
        "vibe_edit",
        "vibe_heal",
        "vibe_code",
        "openapi_tool",
        "agent",
    }
)
_LLM_FREE_HANDLERS = frozenset({"echo", "webhook"})
_MAX_RUN_INPUT_BYTES = 100_000
_MAX_RESULT_BYTES = 60_000


from modstore_server.admin_duty_graph_api_part01 import (
    _json_dumps as _json_dumps,
    _json_loads as _json_loads,
    _as_str as _as_str,
    _extract_manifest_dependencies as _extract_manifest_dependencies,
    _clean_handlers as _clean_handlers,
    _provider_has_usable_key as _provider_has_usable_key,
    _build_provider_status_map as _build_provider_status_map,
    _resolve_llm_state as _resolve_llm_state,
    _detect_risk as _detect_risk,
    _latest_metric as _latest_metric,
    _latest_ops_audits as _latest_ops_audits,
    _load_manifest_for_employee as _load_manifest_for_employee,
    _analyze_employee_capability as _analyze_employee_capability,
    _topo_sort as _topo_sort,
    _serialize_run as _serialize_run,
    get_employee_execution_capability as get_employee_execution_capability,
    post_employee_execution_capabilities as post_employee_execution_capabilities,
    get_duty_graph_no_key_employees as get_duty_graph_no_key_employees,
)


from modstore_server.admin_duty_graph_api_part02 import (
    execute_duty_graph_programmatic as execute_duty_graph_programmatic,
    create_duty_graph_run as create_duty_graph_run,
    get_duty_graph_run as get_duty_graph_run,
    duty_graph_health as duty_graph_health,
)
