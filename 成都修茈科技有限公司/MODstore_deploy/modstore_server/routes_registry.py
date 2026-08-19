# ruff: noqa: E402, F401
from __future__ import annotations

import io
import json
import logging
import os
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import (
    APIRouter,
    Body,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from modman.blueprint_scan import scan_fastapi_router_routes
from modman.fhd_shell_export import write_fhd_shell_mods_json
from modman.industry_presets import apply_industry_to_mod_dir
from modman.manifest_util import (
    folder_name_must_match_id,
    read_manifest,
    save_manifest_validated,
    validate_manifest_dict,
    write_manifest,
)
from modman.repo_config import (
    RepoConfig,
    resolved_library,
    resolved_xcagi,
    resolved_xcagi_backend_url,
    save_config,
)
from modman.scaffold import create_mod
from modman.store import (
    deploy_to_xcagi,
    import_zip,
    iter_mod_dirs,
    list_mod_relative_files,
    list_mods,
    project_root,
    pull_from_xcagi,
    remove_mod,
    remove_mod_by_manifest_id,
)
from modman.surface_bundle import load_bundled_extension_surface
from modstore_server.api.auth_deps import assert_user_owns_mod as _assert_user_owns_mod
from modstore_server.api.auth_deps import get_optional_user as _get_optional_user
from modstore_server.api.auth_deps import require_user as _require_user
from modstore_server.api.dto import (
    ConfigDTO,
    CreateModDTO,
    ExportFhdShellDTO,
    FocusPrimaryDTO,
    FrontendRegenerateDTO,
    HealthResponse,
    ManifestPutDTO,
    ModAiScaffoldDTO,
    ModFilePutDTO,
    SandboxDTO,
    SyncDTO,
    WorkflowEmployeeCatalogDTO,
)
from modstore_server.app_helpers import (
    _assert_path_inside_fhd_repo,
    _cfg,
    _fhd_repo_root,
    _lib,
    _load_state,
    _mod_dir,
    _save_state,
)
from modstore_server.auth_service import decode_access_token, get_user_by_id
from modstore_server.authoring import slim_openapi_paths
from modstore_server.constants import DEFAULT_XCAGI_BACKEND_URL
from modstore_server.employee_pack_export import build_employee_pack_zip_from_workflow
from modstore_server.file_safe import read_text_file, resolve_under_mod, write_text_file
from modstore_server.mod_ai_scaffold import (
    render_frontend_routes_js,
    render_generated_home_vue,
)
from modstore_server.mod_scaffold_runner import (
    analyze_mod_employee_readiness,
    patch_workflow_graph_employee_nodes,
    run_mod_suite_ai_scaffold_async,
)
from modstore_server.mod_snapshots import capture_manifest_snapshot
from modstore_server.models import (
    User,
    add_user_mod,
    get_session_factory,
    get_user_mod_ids,
    remove_user_mod,
)
from modstore_server.package_sandbox_audit import run_package_audit_async
from modstore_server.workflow_employee_scaffold import (
    WorkflowEmployeeScaffoldDTO,
    run_workflow_employee_scaffold,
    scaffold_auto_merge_default,
)

_TAGS = [
    {"name": "health", "description": "服务探活"},
    {
        "name": "config",
        "description": "库路径、XCAGI 根目录、后端 URL、导出 FHD 壳层 /api/mods JSON",
    },
    {"name": "mods", "description": "Mod 列表、详情、manifest、文件读写、导入导出"},
    {"name": "sync", "description": "与 XCAGI/mods 推送与拉回"},
    {"name": "debug", "description": "沙箱目录、primary 批量标记、XCAGI 状态代理"},
    {"name": "authoring", "description": "扩展面文档、蓝图路由静态扫描、宿主 OpenAPI 合并"},
    {"name": "payment", "description": "支付、订单与会员计划"},
    {"name": "workflow", "description": "工作流编排与执行"},
    {"name": "webhooks", "description": "业务 Webhook 投递与重放"},
    {"name": "refunds", "description": "退款申请与审核"},
    {"name": "catalog", "description": "公开目录与市场检索"},
    {
        "name": "catalog-mod-sync",
        "description": "公网机器令牌：库与 XCAGI/mods 推送/拉回（/v1/mod-sync）",
    },
]

api_router = APIRouter()


from modstore_server.routes_registry_part01 import (
    _read_mod_json_file as _read_mod_json_file,
    _mod_shell_ui_row as _mod_shell_ui_row,
    _frontend_spec_for_existing_mod as _frontend_spec_for_existing_mod,
    health as health,
    get_config as get_config,
    api_export_fhd_shell_mods as api_export_fhd_shell_mods,
    put_config as put_config,
    api_list_mods as api_list_mods,
    api_mods_shell_ui as api_mods_shell_ui,
    api_get_mod as api_get_mod,
    api_authoring_extension_surface as api_authoring_extension_surface,
    api_mod_blueprint_routes as api_mod_blueprint_routes,
    api_mod_authoring_summary as api_mod_authoring_summary,
    api_mod_workflow_employee_scaffold as api_mod_workflow_employee_scaffold,
    api_export_workflow_employee_pack as api_export_workflow_employee_pack,
    api_register_workflow_employee_catalog as api_register_workflow_employee_catalog,
    api_patch_workflow_employee_nodes as api_patch_workflow_employee_nodes,
    api_put_manifest as api_put_manifest,
    api_get_mod_file as api_get_mod_file,
    api_put_mod_file as api_put_mod_file,
    api_create_mod as api_create_mod,
    api_mod_ai_scaffold as api_mod_ai_scaffold,
)


from modstore_server.routes_registry_part02 import (
    api_mod_frontend_regenerate as api_mod_frontend_regenerate,
    api_delete_mod as api_delete_mod,
    api_import_mod as api_import_mod,
    api_export_mod as api_export_mod,
    api_sync_push as api_sync_push,
    api_sync_pull as api_sync_pull,
    api_debug_sandbox as api_debug_sandbox,
    api_debug_focus_primary as api_debug_focus_primary,
    api_fhd_db_tokens_status as api_fhd_db_tokens_status,
    api_xcagi_loading_status as api_xcagi_loading_status,
    api_xcagi_installed_mods as api_xcagi_installed_mods,
    _include_optional as _include_optional,
)


_OPTIONAL_MODULES = (
    "modstore_server.llm_api",
    "modstore_server.openai_llm_gateway_api",
    "modstore_server.notification_api",
    "modstore_server.knowledge_vector_api",
    "modstore_server.knowledge_v2_api",
    "modstore_server.realtime_ws",
    "modstore_server.workflow_api",
    "modstore_server.script_workflow_api",
    "modstore_server.runtime_allowlist_api",
    "modstore_server.email_admin_api",
    "modstore_server.workbench_api",
    "modstore_server.employee_api",
    "modstore_server.analytics_api",
    "modstore_server.refund_api",
    "modstore_server.ops_api",
    "modstore_server.admin_ops_audit_api",
    "modstore_server.admin_employee_execution_api",
    "modstore_server.admin_duty_graph_api",
    "modstore_server.employee_change_request_api",
    "modstore_server.yuangon_onboard_admin_api",
    "modstore_server.webhook_api",
    "modstore_server.health_api",
    "modstore_server.openapi_connector_api",
    "modstore_server.customer_service_api",
    "modstore_server.developer_api",
    "modstore_server.developer_key_export_api",
    "modstore_server.webhook_subscription_api",
    "modstore_server.templates_api",
)


from modstore_server.routes_registry_part03 import (
    _maybe_mount_dev_docs as _maybe_mount_dev_docs,
    _maybe_mount_ui as _maybe_mount_ui,
    register_all_routes as register_all_routes,
)
