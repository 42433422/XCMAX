# mypy: disable-error-code="arg-type"
"""Authoring / blueprint / employee pack routes."""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from modman.manifest_util import (
    read_manifest,
    save_manifest_validated,
)
from modstore_server import authoring_inspection
from modstore_server.api.auth_deps import assert_user_owns_mod, require_user
from modstore_server.api.dto import (
    AttachCatalogEmployeeDTO,
    FrontendRegenerateDTO,
    ModAiScaffoldDTO,
    ModSnapshotCaptureDTO,
    WorkflowEmployeeCatalogDTO,
    WorkflowEmployeeClosureDTO,
)
from modstore_server.application.catalog import (
    get_default_catalog_application_service,
)
from modstore_server.application.employee import (
    get_default_employee_application_service,
)
from modstore_server.authoring_frontend import regenerate_frontend
from modstore_server.employee_pack_export import build_employee_pack_zip_from_workflow
from modstore_server.infrastructure import library_paths
from modstore_server.mod_employee_closure import run_workflow_employee_closure
from modstore_server.mod_snapshots import (
    bump_manifest_patch_version,
    capture_manifest_snapshot,
    list_manifest_snapshots,
    restore_manifest_snapshot,
)
from modstore_server.models import User, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.package_sandbox_audit import run_package_audit_async
from modstore_server.workflow_employee_scaffold import (
    WorkflowEmployeeScaffoldDTO,
    run_workflow_employee_scaffold,
    scaffold_auto_merge_default,
)

router = APIRouter(tags=["authoring"])


from modstore_server.api.authoring_part01 import (
    _slug_workflow_employee_id as _slug_workflow_employee_id,
)
from modstore_server.api.authoring_part01 import (
    api_attach_catalog_employee as api_attach_catalog_employee,
)
from modstore_server.api.authoring_part01 import (
    api_authoring_extension_surface as api_authoring_extension_surface,
)
from modstore_server.api.authoring_part01 import (
    api_capture_mod_snapshot as api_capture_mod_snapshot,
)
from modstore_server.api.authoring_part01 import (
    api_export_workflow_employee_pack as api_export_workflow_employee_pack,
)
from modstore_server.api.authoring_part01 import api_list_mod_snapshots as api_list_mod_snapshots
from modstore_server.api.authoring_part01 import (
    api_mod_authoring_summary as api_mod_authoring_summary,
)
from modstore_server.api.authoring_part01 import (
    api_mod_blueprint_routes as api_mod_blueprint_routes,
)
from modstore_server.api.authoring_part01 import (
    api_mod_workflow_employee_scaffold as api_mod_workflow_employee_scaffold,
)
from modstore_server.api.authoring_part01 import (
    api_register_workflow_employee_catalog as api_register_workflow_employee_catalog,
)
from modstore_server.api.authoring_part01 import (
    api_workflow_employee_closure as api_workflow_employee_closure,
)
from modstore_server.api.authoring_part02 import (
    api_bump_mod_manifest_patch_version as api_bump_mod_manifest_patch_version,
)
from modstore_server.api.authoring_part02 import api_mod_ai_scaffold as api_mod_ai_scaffold
from modstore_server.api.authoring_part02 import (
    api_mod_frontend_regenerate as api_mod_frontend_regenerate,
)
from modstore_server.api.authoring_part02 import (
    api_patch_workflow_employee_nodes as api_patch_workflow_employee_nodes,
)
from modstore_server.api.authoring_part02 import (
    api_restore_mod_snapshot as api_restore_mod_snapshot,
)
