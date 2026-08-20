# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("modstore_server.api.authoring")


@_facade().router.get("/api/authoring/extension-surface")
def api_authoring_extension_surface(merge_host: bool = False):
    return _facade().authoring_inspection.extension_surface(merge_host)


@_facade().router.get("/api/mods/{mod_id}/blueprint-routes")
def api_mod_blueprint_routes(
    mod_id: str, user: _facade().User = _facade().Depends(_facade().require_user)
):
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    return _facade().authoring_inspection.blueprint_routes(d)


@_facade().router.get("/api/mods/{mod_id}/authoring-summary")
def api_mod_authoring_summary(
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
        return _facade().authoring_inspection.authoring_summary(
            d, mod_id, user, _facade().get_session_factory()
        )
    except ValueError as error:
        raise _facade().HTTPException(400, str(error)) from error


@_facade().router.post("/api/mods/{mod_id}/workflow-employees/scaffold")
def api_mod_workflow_employee_scaffold(
    mod_id: str,
    body: _facade().WorkflowEmployeeScaffoldDTO,
    user: _facade().User = _facade().Depends(_facade().require_user),
):
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    try:
        return _facade().run_workflow_employee_scaffold(
            d, body, allow_blueprint_merge=_facade().scaffold_auto_merge_default()
        )
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e


@_facade().router.get("/api/mods/{mod_id}/export-employee-pack")
def api_export_workflow_employee_pack(
    mod_id: str,
    workflow_index: int = 0,
    user: _facade().User = _facade().Depends(_facade().require_user),
):
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    data, err = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    if not isinstance(rows, list) or workflow_index < 0 or workflow_index >= len(rows):
        raise _facade().HTTPException(400, "workflow_index 越界或 workflow_employees 非数组")
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


@_facade().router.post("/api/mods/{mod_id}/register-workflow-employee-catalog")
async def api_register_workflow_employee_catalog(
    mod_id: str,
    body: _facade().WorkflowEmployeeCatalogDTO,
    user: _facade().User = _facade().Depends(_facade().require_user),
):
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    data, err = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    idx = int(body.workflow_index)
    if not isinstance(rows, list) or idx < 0 or idx >= len(rows):
        raise _facade().HTTPException(400, "workflow_index 越界或 workflow_employees 非数组")
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
    manifest_zip, manifest_err, _pid = _facade().build_employee_pack_zip_from_workflow(
        mod_id, data, entry, workflow_index=idx, mod_dir=d
    )
    if manifest_err or not manifest_zip:
        raise _facade().HTTPException(400, manifest_err or "生成员工包失败")
    from modstore_server.employee_pack_export import build_employee_pack_manifest_from_workflow

    manifest, manifest_build_err = build_employee_pack_manifest_from_workflow(
        mod_id, data, entry, workflow_index=idx
    )
    if manifest_build_err or not manifest:
        raise _facade().HTTPException(400, manifest_build_err or "生成员工包 manifest 失败")
    rec: _facade().Dict[str, _facade().Any] = {
        "id": pack_id,
        "name": str(manifest.get("name") or pack_id),
        "version": str(manifest.get("version") or "1.0.0"),
        "description": str(manifest.get("description") or ""),
        "artifact": "employee_pack",
        "industry": body.industry.strip() or "通用",
        "release_channel": body.release_channel,
        "commerce": {"mode": "free" if body.price <= 0 else "paid", "price": body.price},
        "license": {"type": "personal" if body.price <= 0 else "commercial", "verify_url": None},
        "probe_mod_id": mod_id,
    }
    with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
        tmp.write(manifest_zip)
        tmp_path = _facade().Path(tmp.name)
    try:
        from modstore_server.mod_scaffold_runner import analyze_mod_employee_readiness

        sf = _facade().get_session_factory()
        with sf() as db:
            saved = (
                _facade()
                .get_default_catalog_application_service()
                .register_employee_pack(
                    db,
                    author_id=user.id,
                    mod_id=mod_id,
                    pack_id=pack_id,
                    package_record=rec,
                    package_file=tmp_path,
                    price=float(body.price or 0),
                )
            )
            _facade().get_default_employee_application_service().register_pack(
                author_id=user.id,
                mod_id=mod_id,
                pack_id=pack_id,
                version=str(saved.get("version") or rec["version"]),
            )
            db.commit()
            readiness = analyze_mod_employee_readiness(db, user, d)
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"ok": True, "package": saved, "audit": audit, "employee_readiness": readiness}


def _slug_workflow_employee_id(raw: str, fallback: str = "emp") -> str:
    import re

    x = (raw or "").strip().lower()
    x = re.sub("[^a-z0-9_-]+", "-", x)
    x = re.sub("-{2,}", "-", x).strip("-")
    if not x or not x[0].isalpha():
        x = fallback
    return x[:64]


@_facade().router.post("/api/mods/{mod_id}/attach-catalog-employee")
def api_attach_catalog_employee(
    mod_id: str,
    body: _facade().AttachCatalogEmployeeDTO,
    user: _facade().User = _facade().Depends(_facade().require_user),
):
    """将 AI 市场 employee_pack 写入 manifest.workflow_employees（含 catalog_pkg_id）。"""
    from modstore_server.models import CatalogItem

    _facade().assert_user_owns_mod(user, mod_id)
    pkg_id = (body.pkg_id or "").strip()
    if not pkg_id:
        raise _facade().HTTPException(400, "pkg_id 不能为空")
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    sf = _facade().get_session_factory()
    with sf() as db:
        q = db.query(CatalogItem).filter(
            CatalogItem.artifact == "employee_pack", CatalogItem.compliance_status != "delisted"
        )
        if body.catalog_item_id:
            item = q.filter(CatalogItem.id == int(body.catalog_item_id)).first()
        else:
            item = q.filter(CatalogItem.pkg_id == pkg_id).first()
        if not item:
            raise _facade().HTTPException(404, "员工包不存在或未上架")
        pkg_id = str(item.pkg_id or pkg_id).strip()
        name = str(item.name or pkg_id).strip() or pkg_id
        desc = str(item.description or "").strip()
    data, err = _facade().read_manifest(d)
    if err or not data:
        raise _facade().HTTPException(400, err or "manifest 无效")
    rows = data.get("workflow_employees")
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if isinstance(row, dict) and str(row.get("catalog_pkg_id") or "").strip() == pkg_id:
            raise _facade().HTTPException(400, "该员工包已在当前 Mod 中")
    taken = {
        str(x.get("id") or "").strip()
        for x in rows
        if isinstance(x, dict) and str(x.get("id") or "").strip()
    }
    internal_id = _facade()._slug_workflow_employee_id(pkg_id, "emp")
    if internal_id in taken:
        for i in range(2, 200):
            candidate = f"{internal_id[:58]}x{i}"
            if candidate not in taken:
                internal_id = candidate
                break
    rows.append(
        {
            "id": internal_id,
            "label": name[:200],
            "panel_title": name[:200],
            "panel_summary": (desc or f"来自 AI 市场员工包「{pkg_id}」。")[:8000],
            "catalog_pkg_id": pkg_id,
        }
    )
    data["workflow_employees"] = rows
    save_err = _facade().save_manifest_validated(d, data)
    if save_err:
        raise _facade().HTTPException(400, save_err)
    return {
        "ok": True,
        "mod_id": mod_id,
        "pkg_id": pkg_id,
        "workflow_index": len(rows) - 1,
        "entry": rows[-1],
    }


@_facade().router.post("/api/mods/{mod_id}/workflow-employee-closure")
async def api_workflow_employee_closure(
    mod_id: str,
    body: _facade().WorkflowEmployeeClosureDTO,
    user: _facade().User = _facade().Depends(_facade().require_user),
):
    """一键员工闭环：批量登记未登记包 + 画布对齐 + 可执行性报告。"""
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    sf = _facade().get_session_factory()
    with sf() as db:
        result = await _facade().run_workflow_employee_closure(
            db,
            user,
            mod_dir=d,
            register_missing=body.register_missing,
            patch_canvas=body.patch_canvas,
            industry=body.industry.strip() or "通用",
        )
    return {"ok": bool(result.get("ok")), **result}


@_facade().router.get("/api/mods/{mod_id}/snapshots")
def api_list_mod_snapshots(
    mod_id: str, user: _facade().User = _facade().Depends(_facade().require_user)
):
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    return {"ok": True, "snapshots": _facade().list_manifest_snapshots(d)}


@_facade().router.post("/api/mods/{mod_id}/snapshots")
def api_capture_mod_snapshot(
    mod_id: str,
    body: _facade().ModSnapshotCaptureDTO,
    user: _facade().User = _facade().Depends(_facade().require_user),
):
    _facade().assert_user_owns_mod(user, mod_id)
    try:
        d = _facade().library_paths.mod_dir(mod_id)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    except FileNotFoundError as e:
        raise _facade().HTTPException(404, str(e)) from e
    try:
        snap = _facade().capture_manifest_snapshot(d, body.label)
    except ValueError as e:
        raise _facade().HTTPException(400, str(e)) from e
    return {"ok": True, "snapshot": snap}
