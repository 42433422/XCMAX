# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


async def run_asset_employee_scaffold_async(
    db: _facade().Any,
    user: _facade().User,
    *,
    session_id: str,
    brief: str,
    raw_files: _facade().List[_facade().Dict[str, _facade().Any]],
    replace: bool = True,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    publish_to_catalog: bool = False,
    force_llm_codegen: bool = False,
    payload: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.artifact_generator_blueprint import (
        artifact_generator_preflight,
    )
    from modstore_server.craft_failure_signals import (
        _employee_trigger_limits,
        emit_craft_step_failure,
    )
    from modstore_server.employee_pipeline_routing import (
        is_direct_python_template_runtime,
    )
    from modstore_server.vibecoding_convert_loop import (
        is_llm_codegen_source,
        run_vibecoding_codegen_loop,
    )

    _limits = _employee_trigger_limits("artifact-generator")
    _max_repair_rounds = max(1, int(_limits.get("max_patch_steps") or 4))
    bp_preflight = artifact_generator_preflight(payload=payload, brief=brief)
    if bp_preflight.get("status") == "error":
        emit_craft_step_failure(
            step_id="generate",
            error=str(bp_preflight.get("error") or "上游蓝图校验失败"),
            employee_id="artifact-generator",
            user_id=int(user.id),
            extra={
                "missing_fields": bp_preflight.get("missing_fields") or [],
                "validation_result": bp_preflight.get("validation_result"),
                "downstream_context": "pack-registrar 需完整 manifest 后再入库",
            },
        )
        return {
            "ok": False,
            "error": bp_preflight.get("error"),
            "status": "error",
            "generation_mode": bp_preflight.get("generation_mode"),
            "artifact_paths": [],
            "validation_result": bp_preflight.get("validation_result"),
            "warnings": [],
            "missing_fields": bp_preflight.get("missing_fields") or [],
        }
    _paths_ok, _path_errors, _paths_checked = _facade()._preflight_scaffold_write_access(
        session_id=session_id, user_id=int(user.id)
    )
    if not _paths_ok:
        _perm_msg = "；".join(_path_errors[:5])
        emit_craft_step_failure(
            step_id="generate",
            error=_perm_msg,
            employee_id="artifact-generator",
            user_id=int(user.id),
            extra={
                "paths_checked": _paths_checked,
                "escalate_to_human": True,
                "downstream_context": "pack-registrar：路径不可写时勿尝试注册包",
            },
        )
        return {
            "ok": False,
            "error": _perm_msg,
            "status": "error",
            "generation_mode": "asset",
            "artifact_paths": [],
            "validation_result": {
                "paths": _paths_checked,
                "permission_errors": _path_errors,
            },
            "warnings": _path_errors,
            "paths_checked": _paths_checked,
        }
    _brief = str(bp_preflight.get("brief_from_plan") or brief).strip() or brief
    asset_manifest = _facade().prepare_employee_assets(
        session_id=session_id, user_id=int(user.id), raw_files=raw_files
    )
    rule_spec = _facade().build_rule_spec(_brief, asset_manifest, payload=payload)
    runtime_kind = str(rule_spec.get("runtime_kind") or "")
    repair_history: _facade().List[_facade().Dict[str, _facade().Any]] = []
    domain_smoke: _facade().Dict[str, _facade().Any] = {}
    golden_comparison: _facade().Dict[str, _facade().Any] = {}
    use_vibecoding_loop = is_direct_python_template_runtime(runtime_kind) or bool(force_llm_codegen)
    base_manifest = _facade()._normalize_manifest(
        _facade()._fallback_manifest(_brief, rule_spec), _brief, rule_spec
    )
    if use_vibecoding_loop:
        manifest, llm_meta = await _facade().enrich_manifest_productivity_fields(
            db,
            user,
            brief=_brief,
            rule_spec=rule_spec,
            base_manifest=base_manifest,
            provider=provider,
            model=model,
        )
        manifest = _facade()._normalize_manifest(manifest, _brief, rule_spec)
        (
            generated_convert_py,
            runtime_meta,
            domain_smoke,
            golden_comparison,
        ) = await run_vibecoding_codegen_loop(
            db,
            user,
            session_id=session_id,
            brief=_brief,
            rule_spec=rule_spec,
            manifest=manifest,
            asset_manifest=asset_manifest,
            provider=provider,
            model=model,
            payload=payload,
        )
        if isinstance(runtime_meta.get("repair_history"), list):
            repair_history = runtime_meta["repair_history"]
    else:
        manifest, llm_meta = await _facade().design_asset_employee_manifest(
            db, user, brief=_brief, rule_spec=rule_spec, provider=provider, model=model
        )
        manifest = _facade()._normalize_manifest(manifest, _brief, rule_spec)
        (
            generated_convert_py,
            runtime_meta,
        ) = await _facade().generate_runtime_convert_module(
            db,
            user,
            brief=_brief,
            rule_spec=rule_spec,
            asset_manifest=asset_manifest,
            provider=provider,
            model=model,
            force_llm_codegen=bool(force_llm_codegen),
            allow_builtin_codegen=False,
            payload=payload,
        )
    pack_dir, raw_zip = _facade().materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest=asset_manifest,
        generated_convert_py=generated_convert_py,
    )
    warnings = _facade().validate_asset_employee_pack(pack_dir, manifest)
    if use_vibecoding_loop:
        if not generated_convert_py:
            warnings.append(str(runtime_meta.get("error") or "vibecoding 未产出合格 convert"))
        elif domain_smoke.get("ok") is False and (not domain_smoke.get("skipped")):
            warnings.append(f"领域冒烟失败：{domain_smoke.get('error') or ''}"[:200])
        elif golden_comparison and (not golden_comparison.get("passed")):
            warnings.append(
                f"黄金对比未达标：parity={golden_comparison.get('parity_score')} diffs={len(golden_comparison.get('diff_items') or [])}"
            )
    elif runtime_meta.get("warning"):
        warnings.append(f"vibecoding runtime：{runtime_meta['warning']}")
    while (
        warnings
        and generated_convert_py
        and provider
        and (len(repair_history) < _max_repair_rounds)
        and (not use_vibecoding_loop)
    ):
        _fail = {"errors": warnings[:8], "stage": "validate_pack"}
        repaired, repair_meta = await _facade().repair_runtime_convert_module(
            db,
            user,
            brief=_brief,
            rule_spec=rule_spec,
            previous_convert_py=generated_convert_py,
            failure=_fail,
            provider=provider,
            model=model,
            round_no=len(repair_history) + 1,
        )
        repair_history.append(repair_meta)
        if not repaired:
            break
        pack_dir, raw_zip = _facade().materialize_asset_employee_pack(
            manifest=manifest,
            rule_spec=rule_spec,
            asset_manifest=asset_manifest,
            generated_convert_py=repaired,
        )
        warnings = _facade().validate_asset_employee_pack(pack_dir, manifest)
        generated_convert_py = repaired
        runtime_meta = {**runtime_meta, "repaired_after_validate": True}
    if warnings and len(repair_history) >= _max_repair_rounds and (not use_vibecoding_loop):
        _budget_msg = f"动态修复预算已用尽（max_patch_steps={_max_repair_rounds}，max_patch_budget_tokens={_limits.get('max_patch_budget_tokens')}）"
        emit_craft_step_failure(
            step_id="generate",
            error=_budget_msg + "：" + "；".join((str(w) for w in warnings[:3])),
            employee_id="artifact-generator",
            user_id=int(user.id),
            extra={
                "repair_history": repair_history,
                "downstream_context": "pack-registrar：请人工复核 manifest/convert 后再注册",
                "escalate_to_human": True,
            },
        )
    if generated_convert_py:
        runtime_meta["validation"] = (
            "generated_convert_py compiled; execution validation is performed by workbench smoke/tests"
        )
    pid = str(manifest.get("id") or pack_dir.name)
    lib = _facade().modstore_library_path()
    with _facade().tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(raw_zip)
        tmp_path = _facade().Path(tmp.name)
    try:
        dest = _facade().import_zip(tmp_path, lib, replace=replace)
    finally:
        tmp_path.unlink(missing_ok=True)
    saved_package: _facade().Dict[str, _facade().Any] = {}
    if publish_to_catalog:
        with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
            tmp.write(raw_zip)
            pkg_tmp_path = _facade().Path(tmp.name)
        try:
            from modstore_server.catalog_store import append_package

            rec = {
                "id": pid,
                "name": str(manifest.get("name") or pid),
                "version": str(manifest.get("version") or "1.0.0"),
                "description": str(manifest.get("description") or ""),
                "artifact": "employee_pack",
                "industry": str(manifest.get("industry") or "通用"),
                "release_channel": "stable",
                "commerce": {"mode": "free", "price": 0},
                "license": {"type": "personal", "verify_url": None},
            }
            saved_package = append_package(rec, pkg_tmp_path)
            row = (
                db.query(_facade().CatalogItem).filter(_facade().CatalogItem.pkg_id == pid).first()
            )
            if not row:
                row = _facade().CatalogItem(pkg_id=pid, author_id=user.id)
                db.add(row)
            row.version = saved_package.get("version") or rec["version"]
            row.name = saved_package.get("name") or rec["name"]
            row.description = saved_package.get("description") or rec["description"]
            row.price = 0.0
            row.artifact = "employee_pack"
            row.industry = saved_package.get("industry") or rec["industry"]
            row.stored_filename = saved_package.get("stored_filename") or ""
            row.sha256 = saved_package.get("sha256") or ""
            db.commit()
            _facade().mirror_catalog_file_to_market_files(row.stored_filename)
        finally:
            pkg_tmp_path.unlink(missing_ok=True)
    vibecoding_ok = True
    if use_vibecoding_loop:
        golden_ok = bool(golden_comparison.get("passed")) if golden_comparison else True
        vibecoding_ok = bool(
            generated_convert_py
            and domain_smoke.get("ok") is not False
            and golden_ok
            and is_llm_codegen_source(runtime_meta)
        )
    return {
        "ok": vibecoding_ok and (not warnings),
        "id": dest.name,
        "path": str(dest),
        "manifest": manifest,
        "asset_manifest": asset_manifest,
        "rule_spec": rule_spec,
        "validate_warnings": warnings,
        "package": saved_package,
        "published": bool(publish_to_catalog and saved_package),
        "llm": llm_meta,
        "runtime_generation": runtime_meta,
        "runtime_repair_history": repair_history,
        "domain_smoke": domain_smoke,
        "golden_comparison": golden_comparison,
    }


async def run_word_extract_employee_scaffold_async(
    db: _facade().Any,
    user: _facade().User,
    *,
    session_id: str,
    brief: str,
    raw_files: _facade().Optional[_facade().List[_facade().Dict[str, _facade().Any]]] = None,
    replace: bool = True,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    publish_to_catalog: bool = False,
    force_llm_codegen: bool = True,
    payload: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """Word 全量提取员工：走 direct_python 资产脚手架，无上传文件也可生成。"""
    return await _facade().run_asset_employee_scaffold_async(
        db,
        user,
        session_id=session_id,
        brief=brief,
        raw_files=list(raw_files or []),
        replace=replace,
        provider=provider,
        model=model,
        publish_to_catalog=publish_to_catalog,
        force_llm_codegen=True,
        payload=payload,
    )
