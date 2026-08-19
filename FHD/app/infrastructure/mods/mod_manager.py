# ruff: noqa: E402, F401
"""Core manager for scanning, loading, and managing MODs."""

import importlib
import importlib.util
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .artifact_constants import ARTIFACT_BUNDLE, ARTIFACT_EMPLOYEE_PACK, normalize_artifact
from .artifact_package import (
    validate_bundle_manifest,
    validate_employee_pack_manifest,
)
from .employee_pack_runtime import ensure_employee_pack_api_ready
from .enterprise_entitlement_restore import restore_entitlements_from_session_id
from .manifest import ModMetadata, parse_manifest, validate_dependencies
from .missing_local_state import clear_mod_missing_locally, mark_mod_missing_locally
from .package import ModPackage, ModPackageError, ModSignatureError
from .registry import get_mod_registry

logger = logging.getLogger(__name__)
_MOD_API_FAILURE_RETRY_AT: dict[str, float] = {}
_MOD_API_FAILURE_BACKOFF_SECONDS = 15.0


from app.infrastructure.mods.mod_manager_modmanager_mixin01 import _ModManagerPart01Mixin
from app.infrastructure.mods.mod_manager_modmanager_mixin02 import _ModManagerPart02Mixin
from app.infrastructure.mods.mod_manager_part01 import (
    _all_mods_roots as _all_mods_roots,
)
from app.infrastructure.mods.mod_manager_part01 import (
    _backend_path_for_mod as _backend_path_for_mod,
)
from app.infrastructure.mods.mod_manager_part01 import (
    _default_mods_root as _default_mods_root,
)
from app.infrastructure.mods.mod_manager_part01 import (
    _invoke_mod_init_hook as _invoke_mod_init_hook,
)
from app.infrastructure.mods.mod_manager_part01 import (
    _register_mod_hooks as _register_mod_hooks,
)
from app.infrastructure.mods.mod_manager_part01 import (
    _repo_layout_mods_candidates as _repo_layout_mods_candidates,
)
from app.infrastructure.mods.mod_manager_part01 import (
    _short_exc_message as _short_exc_message,
)
from app.infrastructure.mods.mod_manager_part01 import (
    _trusted_child_path as _trusted_child_path,
)
from app.infrastructure.mods.mod_manager_part01 import (
    _trusted_relative_file as _trusted_relative_file,
)
from app.infrastructure.mods.mod_manager_part01 import (
    import_mod_backend_py as import_mod_backend_py,
)
from app.infrastructure.mods.mod_manager_part01 import (
    is_mods_disabled as is_mods_disabled,
)
from app.infrastructure.mods.mod_manager_part02 import (
    ModManager as ModManager,
)

_mod_manager: ModManager | None = None


from app.infrastructure.mods.mod_manager_part03 import (
    get_mod_manager as get_mod_manager,
)

_employee_pack_routes_registered: set[str] = set()


from app.infrastructure.mods.mod_manager_part04 import (
    _entitled_client_mod_ids_for_api_mount as _entitled_client_mod_ids_for_api_mount,
)
from app.infrastructure.mods.mod_manager_part04 import (
    _mod_allowed_for_api_load as _mod_allowed_for_api_load,
)
from app.infrastructure.mods.mod_manager_part04 import (
    _register_single_mod_http_routes as _register_single_mod_http_routes,
)
from app.infrastructure.mods.mod_manager_part04 import (
    _resolve_mod_metadata_for_http as _resolve_mod_metadata_for_http,
)
from app.infrastructure.mods.mod_manager_part04 import (
    _restore_entitlements_from_session_id as _restore_entitlements_from_session_id,
)
from app.infrastructure.mods.mod_manager_part04 import (
    ensure_mod_api_ready as ensure_mod_api_ready,
)
from app.infrastructure.mods.mod_manager_part04 import (
    load_employee_pack_routes as load_employee_pack_routes,
)
from app.infrastructure.mods.mod_manager_part04 import (
    load_mod_blueprints as load_mod_blueprints,
)
from app.infrastructure.mods.mod_manager_part04 import (
    load_mod_routes as load_mod_routes,
)
from app.infrastructure.mods.mod_manager_part04 import (
    mount_entitled_client_mod_api_routes as mount_entitled_client_mod_api_routes,
)
from app.infrastructure.mods.mod_manager_part04 import (
    mount_on_disk_primary_client_mods as mount_on_disk_primary_client_mods,
)
from app.infrastructure.mods.mod_manager_part04 import (
    register_employee_pack_routes as register_employee_pack_routes,
)
