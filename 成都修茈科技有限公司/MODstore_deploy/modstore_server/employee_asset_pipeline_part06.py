# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


def persist_manifest_to_pack_dir(
    pack_dir: _facade().Path, manifest: _facade().Dict[str, _facade().Any], *, brief: str = ""
) -> _facade().Dict[str, _facade().Any]:
    """Write manifest.json on disk; reconcile Word packs when rule_spec exists or brief matches."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    mf_path = pack_dir / "manifest.json"
    mf_path.write_text(
        _facade().json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if (
        _facade().manifest_expects_word_runtime(manifest, brief=brief)
        or (pack_dir / "rule_spec.json").is_file()
    ):
        return _facade().reconcile_employee_pack_manifest(pack_dir, brief=brief)
    return manifest


def build_employee_pack_zip_for_library(
    pack_id: str,
    manifest: _facade().Dict[str, _facade().Any],
    *,
    pack_dir: _facade().Optional[_facade().Path] = None,
    brief: str = "",
) -> bytes:
    """Build .xcemp bytes: prefer on-disk vendor/runtime; never strip Word packs to template-only."""
    from modstore_server.employee_ai_scaffold import build_employee_pack_zip

    pd = pack_dir or _facade().modstore_library_path() / pack_id
    handlers = _facade().manifest_actions_handlers(manifest)
    wants_word = _facade().manifest_expects_word_runtime(manifest, brief=brief)
    if "direct_python" in handlers and wants_word:
        if not pd.is_dir() or not _facade().pack_has_direct_python_runtime(pd):
            raise ValueError(_facade().DIRECT_PYTHON_RUNTIME_MISSING_MSG)
    if pd.is_dir() and (pd / "manifest.json").is_file():
        _facade().persist_manifest_to_pack_dir(pd, manifest, brief=brief)
        if _facade().pack_has_direct_python_runtime(pd) or any(
            (
                p.is_file()
                for p in pd.rglob("*")
                if p.suffix.lower() in {".py", ".json"} and "__pycache__" not in p.parts
            )
        ):
            try:
                return _facade().build_employee_pack_zip_from_dir(pack_id, pd)
            except Exception:
                pass
    return build_employee_pack_zip(pack_id, manifest)


def build_employee_pack_zip_from_dir(pack_id: str, pack_dir: _facade().Path) -> bytes:
    mf_path = pack_dir / "manifest.json"
    if mf_path.is_file():
        try:
            _raw = _facade().json.loads(mf_path.read_text(encoding="utf-8"))
            _dirty = False
            if str(_raw.get("id") or "") != pack_id:
                _raw["id"] = pack_id
                _dirty = True
            if (
                isinstance(_raw.get("employee"), dict)
                and str(_raw["employee"].get("id") or "") != pack_id
            ):
                _raw["employee"]["id"] = pack_id
                _dirty = True
            for _r in _raw.get("workflow_employees") or []:
                if isinstance(_r, dict) and str(_r.get("id") or "") != pack_id:
                    _r["id"] = pack_id
                    _dirty = True
            if _dirty:
                mf_path.write_text(
                    _facade().json.dumps(_raw, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        except Exception:
            pass
    buf = _facade().io.BytesIO()
    with _facade().zipfile.ZipFile(buf, "w", _facade().zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(pack_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(pack_dir).as_posix()
            if "__pycache__" in _facade().Path(rel).parts:
                continue
            if _facade().Path(rel).suffix.lower() not in {
                ".json",
                ".md",
                ".py",
                ".xlsx",
                ".xlsm",
                ".xls",
                ".txt",
                ".yaml",
                ".yml",
            }:
                continue
            zf.write(path, f"{pack_id}/{rel}")
    return buf.getvalue()


def mirror_catalog_file_to_market_files(stored_filename: str) -> None:
    """Keep the browsable market_files copy aligned with catalog_data/files."""
    name = _facade()._safe_basename(stored_filename, "")
    if not name:
        return
    from modstore_server.catalog_store import files_dir

    src = files_dir() / name
    if not src.is_file():
        return
    dest_dir = _facade().Path(__file__).resolve().parent / "market_files"
    dest_dir.mkdir(parents=True, exist_ok=True)
    _facade().shutil.copy2(src, dest_dir / name)


def _copy_template_assets(
    pack_dir: _facade().Path,
    asset_manifest: _facade().Dict[str, _facade().Any],
    rule_spec: _facade().Dict[str, _facade().Any],
) -> None:
    assets = asset_manifest.get("templates") or []
    if not assets:
        assets = [
            a
            for a in asset_manifest.get("assets") or []
            if a.get("suffix") in _facade().EXCEL_SUFFIXES
        ][:1]
    for asset in assets:
        src = _facade().Path(str(asset.get("path") or ""))
        if src.is_file():
            filename = str(asset.get("filename") or src.name)
            rel = str(
                rule_spec.get("template_relpath")
                or _facade()._template_storage_relpath(filename, str(rule_spec.get("brief") or ""))
            )
            dest = pack_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            _facade().shutil.copy2(src, dest)


def materialize_asset_employee_pack(
    *,
    manifest: _facade().Dict[str, _facade().Any],
    rule_spec: _facade().Dict[str, _facade().Any],
    asset_manifest: _facade().Dict[str, _facade().Any],
    generated_convert_py: _facade().Optional[str] = None,
) -> _facade().Tuple[_facade().Path, bytes]:
    pack_id = str(manifest.get("id") or "").strip()
    if not pack_id:
        raise ValueError("manifest.id 缺失")
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    employee_id = pack_id
    label = str(emp.get("label") or manifest.get("name") or employee_id).strip() or employee_id
    stem = _facade().sanitize_employee_stem(employee_id)
    runtime_mod = _facade()._runtime_package_name(pack_id, employee_id)
    runtime_kind = rule_spec.get("runtime_kind") or "generic_excel_transform"
    _is_doc_review = runtime_kind in ("contract_doc_review", "doc_template_transform")
    tmp_dir = _facade().Path(_facade().tempfile.mkdtemp(prefix=f"asset_emp_{pack_id}_"))
    pack_dir = tmp_dir / pack_id
    (pack_dir / "backend" / "employees").mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(
        _facade().json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _readme_desc = "LLM 驱动文档审核" if _is_doc_review else "direct_python"
    (pack_dir / "README.md").write_text(
        "# " + label + f"\n\n由上传资产生成的 {_readme_desc} 员工包。\n", encoding="utf-8"
    )
    (pack_dir / "build_xcemp.py").write_text(
        _facade().render_build_xcemp_py(pack_id), encoding="utf-8"
    )
    (pack_dir / "backend" / "blueprints.py").write_text(
        _facade().render_employee_pack_blueprints_py(
            pack_id=pack_id, employee_id=employee_id, stem=stem, label=label
        ),
        encoding="utf-8",
    )
    (pack_dir / "backend" / "employees" / "__init__.py").write_text(
        '"""Generated employees."""\n', encoding="utf-8"
    )
    if _is_doc_review:
        from modstore_server.employee_pack_blueprints_template import (
            render_employee_pack_employee_py,
        )

        (pack_dir / "backend" / "employees" / f"{stem}.py").write_text(
            render_employee_pack_employee_py(employee_id=employee_id, stem=stem, label=label),
            encoding="utf-8",
        )
    else:
        (pack_dir / "backend" / "vendor" / runtime_mod).mkdir(parents=True, exist_ok=True)
        (pack_dir / "backend" / "employees" / f"{stem}.py").write_text(
            _facade().render_direct_python_asset_worker(
                employee_id=employee_id,
                label=label,
                runtime_module=runtime_mod,
                rule_spec=rule_spec,
            ),
            encoding="utf-8",
        )
        for name, src in (
            _facade()
            .render_runtime_modules(rule_spec, generated_convert_py=generated_convert_py)
            .items()
        ):
            (pack_dir / "backend" / "vendor" / runtime_mod / name).write_text(src, encoding="utf-8")
    _facade()._copy_template_assets(pack_dir, asset_manifest, rule_spec)
    (pack_dir / "asset_manifest.json").write_text(
        _facade().json.dumps(asset_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (pack_dir / "rule_spec.json").write_text(
        _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    raw = _facade().build_employee_pack_zip_from_dir(pack_id, pack_dir)
    return (pack_dir, raw)


def validate_asset_employee_pack(
    pack_dir: _facade().Path, manifest: _facade().Dict[str, _facade().Any]
) -> _facade().List[str]:
    warnings: _facade().List[str] = []
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    top_actions = manifest.get("actions") if isinstance(manifest.get("actions"), dict) else {}
    top_handlers = (
        top_actions.get("handlers") if isinstance(top_actions.get("handlers"), list) else []
    )
    v2_handlers = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
    _is_agent_handler = "agent" in v2_handlers
    if not _is_agent_handler and actions.get("handlers") != ["direct_python"]:
        warnings.append("actions.handlers 必须为 ['direct_python'] 或 ['agent']")
    if top_handlers and v2_handlers and (top_handlers != v2_handlers):
        warnings.append(
            f"顶层 actions.handlers={top_handlers} 与 v2 actions.handlers={v2_handlers} 不一致"
        )
    emp_dir = pack_dir / "backend" / "employees"
    py_files = (
        [p for p in emp_dir.glob("*.py") if p.name != "__init__.py"] if emp_dir.is_dir() else []
    )
    if not py_files:
        warnings.append("缺少 backend/employees 入口脚本")
    direct = actions.get("direct_python") if isinstance(actions.get("direct_python"), dict) else {}
    module_name = str(direct.get("module") or "").strip()
    if module_name:
        expected_file = emp_dir / f"{module_name}.py"
        if not expected_file.is_file():
            warnings.append(
                f"direct_python.module={module_name} 但文件 {expected_file.name} 不存在"
            )
    for pf in py_files:
        code = pf.read_text(encoding="utf-8")
        has_dispatch = "_DISPATCH" in code
        if "direct_python" in (v2_handlers or []) and has_dispatch:
            warnings.append(
                f"{pf.name} 含 _DISPATCH 字典但 handlers 声明为 direct_python，应使用 render_direct_python_asset_worker 模板"
            )
        if "direct_python" not in (v2_handlers or []) and (not has_dispatch):
            pass
    for p in sorted((pack_dir / "backend").rglob("*.py")):
        try:
            _facade().py_compile.compile(str(p), doraise=True)
            _facade().ast.parse(p.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.append(f"{p.relative_to(pack_dir).as_posix()}: {exc}")
    if not list((pack_dir / "backend" / "vendor").rglob("*.py")):
        if not _is_agent_handler:
            warnings.append("缺少 backend/vendor 运行模块")
    tpl = str(direct.get("default_template_relpath") or "").strip()
    if tpl:
        template_dir = pack_dir / "backend" / "templates"
        has_any_template = template_dir.is_dir() and any(
            (p.suffix.lower() in _facade().EXCEL_SUFFIXES for p in template_dir.rglob("*"))
        )
        if not (
            (pack_dir / tpl).is_file()
            or (pack_dir / "backend" / tpl).is_file()
            or (pack_dir / "backend" / "templates" / tpl).is_file()
            or has_any_template
        ):
            warnings.append(f"默认模板未打包：{tpl}")
    return warnings


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
    from modstore_server.artifact_generator_blueprint import artifact_generator_preflight
    from modstore_server.craft_failure_signals import (
        _employee_trigger_limits,
        emit_craft_step_failure,
    )
    from modstore_server.employee_pipeline_routing import is_direct_python_template_runtime
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
    (_paths_ok, _path_errors, _paths_checked) = _facade()._preflight_scaffold_write_access(
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
            "validation_result": {"paths": _paths_checked, "permission_errors": _path_errors},
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
        (manifest, llm_meta) = await _facade().enrich_manifest_productivity_fields(
            db,
            user,
            brief=_brief,
            rule_spec=rule_spec,
            base_manifest=base_manifest,
            provider=provider,
            model=model,
        )
        manifest = _facade()._normalize_manifest(manifest, _brief, rule_spec)
        (generated_convert_py, runtime_meta, domain_smoke, golden_comparison) = (
            await run_vibecoding_codegen_loop(
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
        )
        if isinstance(runtime_meta.get("repair_history"), list):
            repair_history = runtime_meta["repair_history"]
    else:
        (manifest, llm_meta) = await _facade().design_asset_employee_manifest(
            db, user, brief=_brief, rule_spec=rule_spec, provider=provider, model=model
        )
        manifest = _facade()._normalize_manifest(manifest, _brief, rule_spec)
        (generated_convert_py, runtime_meta) = await _facade().generate_runtime_convert_module(
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
    (pack_dir, raw_zip) = _facade().materialize_asset_employee_pack(
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
        (repaired, repair_meta) = await _facade().repair_runtime_convert_module(
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
        (pack_dir, raw_zip) = _facade().materialize_asset_employee_pack(
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
