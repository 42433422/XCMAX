# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.routes_registry")


@_facade().api_router.get("/api/mods/{mod_id}/export-employee-pack", tags=["authoring"])
def api_export_workflow_employee_pack(
    mod_id: str,
    workflow_index: int = 0,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    data, err = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    if not isinstance(rows, list) or workflow_index < 0 or workflow_index >= len(rows):
        raise _facade().HTTPException(
            400, "workflow_index 越界或 workflow_employees 非数组"
        )
    raw, build_err, pack_id = _facade().build_employee_pack_zip_from_workflow(
        mod_id,
        data,
        rows[workflow_index] if isinstance(rows[workflow_index], dict) else {},
        workflow_index=workflow_index,
        mod_dir=d,
    )
    if build_err or not raw or (not pack_id):
        raise _facade().HTTPException(400, build_err or "生成员工包失败")
    return _facade().StreamingResponse(
        _facade().io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{pack_id}.xcemp"'},
    )


@_facade().api_router.post(
    "/api/mods/{mod_id}/register-workflow-employee-catalog", tags=["authoring"]
)
async def api_register_workflow_employee_catalog(
    mod_id: str,
    body: _facade().WorkflowEmployeeCatalogDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    data, err = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    idx = int(body.workflow_index)
    if not isinstance(rows, list) or idx < 0 or idx >= len(rows):
        raise _facade().HTTPException(
            400, "workflow_index 越界或 workflow_employees 非数组"
        )
    entry = rows[idx] if isinstance(rows[idx], dict) else {}
    raw, build_err, pack_id = _facade().build_employee_pack_zip_from_workflow(
        mod_id, data, entry, workflow_index=idx, mod_dir=d
    )
    if build_err or not raw or (not pack_id):
        raise _facade().HTTPException(400, build_err or "生成员工包失败")
    audit = await _facade().run_package_audit_async(raw, {"artifact": "employee_pack"})
    if not audit.get("ok"):
        raise _facade().HTTPException(400, str(audit.get("error") or "包审核失败"))
    summary = audit.get("summary") if isinstance(audit.get("summary"), dict) else {}
    if summary and summary.get("pass") is False:
        raise _facade().HTTPException(400, "五维审核未通过，禁止登记")
    import tempfile
    from modstore_server.catalog_store import append_package
    from modstore_server.models import CatalogItem

    manifest_zip, manifest_err, _pid = _facade().build_employee_pack_zip_from_workflow(
        mod_id, data, entry, workflow_index=idx, mod_dir=d
    )
    if manifest_err or not manifest_zip:
        raise _facade().HTTPException(400, manifest_err or "生成员工包失败")
    from modstore_server.employee_pack_export import (
        build_employee_pack_manifest_from_workflow,
    )

    manifest, manifest_build_err = build_employee_pack_manifest_from_workflow(
        mod_id, data, entry, workflow_index=idx
    )
    if manifest_build_err or not manifest:
        raise _facade().HTTPException(
            400, manifest_build_err or "生成员工包 manifest 失败"
        )
    rec: _facade().Dict[str, _facade().Any] = {
        "id": pack_id,
        "name": str(manifest.get("name") or pack_id),
        "version": str(manifest.get("version") or "1.0.0"),
        "description": str(manifest.get("description") or ""),
        "artifact": "employee_pack",
        "industry": body.industry.strip() or "通用",
        "release_channel": body.release_channel,
        "commerce": {
            "mode": "free" if body.price <= 0 else "paid",
            "price": body.price,
        },
        "license": {
            "type": "personal" if body.price <= 0 else "commercial",
            "verify_url": None,
        },
        "probe_mod_id": mod_id,
    }
    with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
        tmp.write(manifest_zip)
        tmp_path = _facade().Path(tmp.name)
    try:
        saved = append_package(rec, tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    sf = _facade().get_session_factory()
    with sf() as db:
        row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
        if not row:
            row = CatalogItem(pkg_id=pack_id, author_id=user.id)
            db.add(row)
        row.version = saved.get("version") or rec["version"]
        row.name = saved.get("name") or rec["name"]
        row.description = saved.get("description") or rec["description"]
        row.price = float(body.price or 0)
        row.artifact = "employee_pack"
        row.industry = saved.get("industry") or rec["industry"]
        row.stored_filename = saved.get("stored_filename") or ""
        row.sha256 = saved.get("sha256") or ""
        db.commit()
        try:
            from modstore_server.application.employee import (
                get_default_employee_application_service,
            )

            get_default_employee_application_service().register_pack(
                author_id=user.id,
                mod_id=mod_id,
                pack_id=pack_id,
                version=saved.get("version") or rec["version"],
            )
        except RECOVERABLE_ERRORS:
            import logging

            logging.getLogger(__name__).exception(
                "EmployeeApplicationService.register_pack failed"
            )
        readiness = _facade().analyze_mod_employee_readiness(db, user, d)
    return {
        "ok": True,
        "package": saved,
        "audit": audit,
        "employee_readiness": readiness,
    }


@_facade().api_router.post(
    "/api/mods/{mod_id}/patch-workflow-employee-nodes", tags=["authoring"]
)
def api_patch_workflow_employee_nodes(
    mod_id: str, user: _facade().User = _facade().Depends(_facade()._require_user)
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    sf = _facade().get_session_factory()
    with sf() as db:
        out = _facade().patch_workflow_graph_employee_nodes(
            db, user, mod_dir=d, workflow_results=[]
        )
        readiness = _facade().analyze_mod_employee_readiness(db, user, d)
    return {
        "ok": bool(out.get("ok")),
        "graph_patch": out,
        "employee_readiness": readiness,
    }


@_facade().api_router.put("/api/mods/{mod_id}/manifest", tags=["mods"])
def api_put_manifest(
    mod_id: str,
    body: _facade().ManifestPutDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    try:
        warnings = _facade().save_manifest_validated(d, body.manifest)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    return {"ok": True, "warnings": warnings}


@_facade().api_router.get("/api/mods/{mod_id}/file", tags=["mods"])
def api_get_mod_file(
    mod_id: str,
    path: str,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    try:
        text = _facade().read_text_under_mod(d, path)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    return {"path": path.replace("\\", "/").lstrip("/"), "content": text}


@_facade().api_router.put("/api/mods/{mod_id}/file", tags=["mods"])
def api_put_mod_file(
    mod_id: str,
    body: _facade().ModFilePutDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    _facade()._assert_user_owns_mod(user, mod_id)
    d = _facade()._mod_dir(mod_id)
    try:
        p = _facade().write_text_under_mod(d, body.path, body.content)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    manifest_warnings: _facade().List[str] = []
    if p.name == "manifest.json" and p.parent.resolve() == d.resolve():
        data, err = _facade().read_manifest(d)
        if data and (not err):
            manifest_warnings = _facade().validate_manifest_dict(data)
            fn = _facade().folder_name_must_match_id(d, data)
            if fn:
                manifest_warnings = list(manifest_warnings) + [fn]
    return {"ok": True, "manifest_warnings": manifest_warnings}


@_facade().api_router.post("/api/mods/create", tags=["mods"])
def api_create_mod(
    body: _facade().CreateModDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    mid = body.mod_id.strip().lower().replace(" ", "-")
    try:
        dest = _facade().create_mod(mid, body.display_name.strip(), _facade()._lib())
        _facade().apply_industry_to_mod_dir(dest, (body.industry_id or "通用").strip())
    except FileExistsError as e:
        raise _facade().HTTPException(409, str(e)) from e
    except (FileNotFoundError, ValueError) as e:
        raise _facade().HTTPException(400, str(e)) from e
    _facade().add_user_mod(user.id, mid)
    return {
        "ok": True,
        "path": str(dest),
        "id": mid,
        "industry_id": (body.industry_id or "通用").strip(),
    }


@_facade().api_router.post("/api/mods/ai-scaffold", tags=["mods"])
async def api_mod_ai_scaffold(
    body: _facade().ModAiScaffoldDTO,
    user: _facade().User = _facade().Depends(_facade()._require_user),
):
    import logging

    logger = logging.getLogger(__name__)
    sf = _facade().get_session_factory()
    try:
        with sf() as db:
            res = await _facade().run_mod_suite_ai_scaffold_async(
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
    except RECOVERABLE_ERRORS as exc:
        logger.exception("api_mod_ai_scaffold failed")
        raise _facade().HTTPException(500, f"AI 脚手架异常：{exc}") from exc
    if not res.get("ok"):
        raise _facade().HTTPException(400, res.get("error") or "AI 生成 Mod 失败")
    return res
