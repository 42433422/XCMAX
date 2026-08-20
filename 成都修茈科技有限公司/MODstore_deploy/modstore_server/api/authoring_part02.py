# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.api.authoring")


@_facade().router.post("/api/mods/{mod_id}/snapshots/{snap_id}/restore")
def api_restore_mod_snapshot(
    mod_id: str, snap_id: str, user: _facade().User = _facade().Depends(_facade().require_user)
):
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    try:
        manifest, warnings = _facade().restore_manifest_snapshot(d, snap_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    return {"ok": True, "manifest": manifest, "warnings": warnings}


@_facade().router.post("/api/mods/{mod_id}/manifest/bump-patch-version")
def api_bump_mod_manifest_patch_version(
    mod_id: str, user: _facade().User = _facade().Depends(_facade().require_user)
):
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    try:
        manifest, warnings = _facade().bump_manifest_patch_version(d)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    return {"ok": True, "manifest": manifest, "warnings": warnings}


@_facade().router.post("/api/mods/{mod_id}/patch-workflow-employee-nodes")
def api_patch_workflow_employee_nodes(
    mod_id: str, user: _facade().User = _facade().Depends(_facade().require_user)
):
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    from modstore_server.mod_scaffold_runner import (
        analyze_mod_employee_readiness,
        patch_workflow_graph_employee_nodes,
    )

    sf = _facade().get_session_factory()
    with sf() as db:
        out = patch_workflow_graph_employee_nodes(db, user, mod_dir=d, workflow_results=[])
        readiness = analyze_mod_employee_readiness(db, user, d)
    return {"ok": bool(out.get("ok")), "graph_patch": out, "employee_readiness": readiness}


@_facade().router.post("/api/mods/{mod_id}/frontend/regenerate")
def api_mod_frontend_regenerate(
    mod_id: str,
    body: _facade().FrontendRegenerateDTO,
    user: _facade().User = _facade().Depends(_facade().require_user),
):
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        mod_dir = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    try:
        return _facade().regenerate_frontend(mod_dir, mod_id, body.brief)
    except ValueError as error:
        raise _facade().HTTPException(400, str(error)) from error


@_facade().router.post("/api/mods/ai-scaffold")
async def api_mod_ai_scaffold(
    body: _facade().ModAiScaffoldDTO,
    user: _facade().User = _facade().Depends(_facade().require_user),
):
    import logging

    from modstore_server.mod_scaffold_runner import run_mod_suite_ai_scaffold_async

    logger = logging.getLogger(__name__)
    sf = _facade().get_session_factory()
    try:
        with sf() as db:
            res = await run_mod_suite_ai_scaffold_async(
                db,
                user,
                brief=body.brief,
                suggested_id=body.suggested_id,
                replace=body.replace,
                industry_id=body.industry_id,
                provider=body.provider,
                model=body.model,
                manifest_override=body.manifest_override,
            )
    except _facade().RECOVERABLE_ERRORS as exc:
        logger.exception("api_mod_ai_scaffold failed")
        raise _facade().HTTPException(500, f"AI 脚手架异常：{exc}") from exc
    if not res.get("ok"):
        raise _facade().HTTPException(400, res.get("error") or "AI 生成 Mod 失败")
    return res
