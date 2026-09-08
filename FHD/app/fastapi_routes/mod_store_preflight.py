"""Account-scoped inputs for read-only Mod package preflight."""

from typing import Any

from fastapi import HTTPException, Request


async def package_preflight(request: Request, package_file: str) -> dict[str, Any]:
    from app.application.agent_orchestrator.task_mod_scope import (
        TaskModScopeError,
        capture_task_mod_scope,
    )
    from app.application.mod_package_preflight import inspect_catalog_package
    from app.application.tenant_workspace_prefs import resolve_workspace_owner_id
    from app.infrastructure.auth.dependencies import get_logged_in_user
    from app.infrastructure.mods.install_receipts import read_verified_install
    from app.infrastructure.mods.registry import get_mod_registry
    from app.infrastructure.request_context import reset_current_request, set_current_request

    user = get_logged_in_user(request)
    owner = resolve_workspace_owner_id(request, user)
    if not owner:
        raise HTTPException(401, "无法确定当前工作空间")
    versions = {}
    registry = get_mod_registry()
    token = set_current_request(request)
    try:
        for mod_id in registry.list_mod_ids():
            receipt = read_verified_install(mod_id)
            if receipt and receipt.get("owner_scope") and receipt["owner_scope"] != owner:
                continue
            try:
                capture_task_mod_scope(str(user.id), str(user.tenant_id), mod_id=mod_id)
            except TaskModScopeError:
                continue
            metadata = registry.get_mod_metadata(mod_id)
            if metadata:
                versions[mod_id] = metadata.version
    finally:
        reset_current_request(token)
    return await inspect_catalog_package(package_file, versions)
