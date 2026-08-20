# isort: skip_file
# ruff: noqa: E402, F401
"""工作流API模块，提供工作流的CRUD操作和执行监控功能。"""

from __future__ import annotations

import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from modman.manifest_util import read_manifest
from modman.repo_config import load_config, resolved_library
from modman.store import iter_mod_dirs
from modstore_server.api.deps import _get_current_user
from modstore_server.infrastructure.db import get_db
from modstore_server.models import (
    User,
    Workflow,
    WorkflowEdge,
    WorkflowExecution,
    WorkflowNode,
    WorkflowSandboxRun,
    WorkflowTrigger,
    WorkflowVersion,
    get_session_factory,
    get_user_mod_ids,
)
from modstore_server.quota_middleware import consume_llm_credit, require_llm_credit
from modstore_server.workflow_event_runner import run_workflow_for_trigger
from modstore_server.workflow_sandbox_state import (
    record_workflow_sandbox_run,
    sandbox_status_for_workflow,
    workflow_graph_fingerprint,
)

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


from modstore_server.workflow_api_part01 import (
    _guess_employee_id_from_empty_workflow as _guess_employee_id_from_empty_workflow,
    _repair_empty_employee_workflow_graph as _repair_empty_employee_workflow_graph,
)

workflow_hooks_router = APIRouter(prefix="/api/workflow-hooks", tags=["workflow-hooks"])


from modstore_server.workflow_api_part02 import (
    CreateWorkflowBody as CreateWorkflowBody,
    WorkflowExecuteBody as WorkflowExecuteBody,
    SandboxRunBody as SandboxRunBody,
    UpdateWorkflowBody as UpdateWorkflowBody,
    AddWorkflowNodeBody as AddWorkflowNodeBody,
    AddWorkflowEdgeBody as AddWorkflowEdgeBody,
    PatchWorkflowNodeBody as PatchWorkflowNodeBody,
    WorkflowTriggerBody as WorkflowTriggerBody,
    PublishVersionBody as PublishVersionBody,
    _serialize_workflow_snapshot as _serialize_workflow_snapshot,
    _restore_workflow_from_snapshot as _restore_workflow_from_snapshot,
    _parse_positive_int as _parse_positive_int,
    _workflow_summary as _workflow_summary,
    _employee_id_matches as _employee_id_matches,
    _employee_matches_manifest_entry as _employee_matches_manifest_entry,
    create_workflow as create_workflow,
    list_workflows as list_workflows,
    list_employee_eligible_workflows as list_employee_eligible_workflows,
    list_workflows_by_employee as list_workflows_by_employee,
    get_workflow as get_workflow,
    update_workflow as update_workflow,
    delete_workflow as delete_workflow,
    add_workflow_node as add_workflow_node,
    update_workflow_node as update_workflow_node,
    delete_workflow_node as delete_workflow_node,
    add_workflow_edge as add_workflow_edge,
    delete_workflow_edge as delete_workflow_edge,
    validate_workflow_endpoint as validate_workflow_endpoint,
    sandbox_run_workflow as sandbox_run_workflow,
)


from modstore_server.workflow_api_part03 import (
    execute_workflow as execute_workflow,
    get_workflow_executions as get_workflow_executions,
    list_workflow_triggers as list_workflow_triggers,
    create_workflow_trigger as create_workflow_trigger,
    delete_workflow_trigger as delete_workflow_trigger,
    webhook_run_workflow as webhook_run_workflow,
    publish_workflow_version as publish_workflow_version,
    list_workflow_versions as list_workflow_versions,
    get_workflow_version as get_workflow_version,
    rollback_workflow_version as rollback_workflow_version,
    get_execution_detail as get_execution_detail,
    public_webhook_run_workflow as public_webhook_run_workflow,
)
