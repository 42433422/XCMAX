# mypy: disable-error-code="attr-defined, no-any-return, operator, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.employee_asset_pipeline")


def persist_manifest_to_pack_dir(
    pack_dir: _facade().Path,
    manifest: _facade().Dict[str, _facade().Any],
    *,
    brief: str = "",
) -> _facade().Dict[str, _facade().Any]:
    """Write manifest.json on disk; reconcile Word packs when rule_spec exists or brief matches."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    mf_path = pack_dir / "manifest.json"
    mf_path.write_text(
        _facade().json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
            except RECOVERABLE_ERRORS:
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
        except RECOVERABLE_ERRORS:
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
        _facade().json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _readme_desc = "LLM 驱动文档审核" if _is_doc_review else "direct_python"
    (pack_dir / "README.md").write_text(
        "# " + label + f"\n\n由上传资产生成的 {_readme_desc} 员工包。\n",
        encoding="utf-8",
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
        _facade().json.dumps(asset_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (pack_dir / "rule_spec.json").write_text(
        _facade().json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
        except RECOVERABLE_ERRORS as exc:
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
