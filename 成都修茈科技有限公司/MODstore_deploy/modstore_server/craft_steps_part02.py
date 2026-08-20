# mypy: disable-error-code="attr-defined, no-any-return, operator, union-attr, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.craft_steps")


async def _craft_standalone_smoke(
    *,
    res: _facade().Any = None,
    pack_dir: _facade().Any = None,
    user_id: int = 0,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modman.manifest_util import read_manifest

    _pack = (
        _facade().Path(str(pack_dir))
        if pack_dir and (not isinstance(pack_dir, _facade().Path))
        else pack_dir
    )
    _standalone_smoke_ok = False
    _standalone_smoke_skipped = False
    _standalone_smoke_msg = "跳过（未能获取包字节）"
    try:
        from modstore_server.employee_pack_export import (
            _build_employee_pack_zip_with_source,
            collect_vendor_modules_from_pack,
        )

        _sm_manifest = res.get("manifest") if isinstance(res, dict) else None
        if not _sm_manifest and _pack and _pack.is_dir():
            _mf_disk, _mf_disk_err = read_manifest(_pack)
            if not _mf_disk_err:
                _sm_manifest = _mf_disk
        if _sm_manifest and isinstance(_sm_manifest, dict):
            _sm_pid = str(_sm_manifest.get("id") or "employee-pack").strip() or "employee-pack"
            _sm_vendor_modules_first = (
                collect_vendor_modules_from_pack(_pack) if _pack and _pack.is_dir() else None
            )
            _sm_zip_bytes = _build_employee_pack_zip_with_source(
                _sm_pid, _sm_manifest, None, vendor_modules=_sm_vendor_modules_first
            )
            with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as _tf:
                _tf.write(_sm_zip_bytes)
                _tmp_xcemp = _tf.name
            try:
                _proc = await _facade().asyncio.wait_for(
                    _facade().asyncio.create_subprocess_exec(
                        _facade().sys.executable,
                        _tmp_xcemp,
                        "validate",
                        stdout=_facade().asyncio.subprocess.PIPE,
                        stderr=_facade().asyncio.subprocess.PIPE,
                    ),
                    timeout=20,
                )
                _stdout, _stderr = await _facade().asyncio.wait_for(_proc.communicate(), timeout=20)
                if _proc.returncode == 0:
                    _standalone_smoke_ok = True
                    _standalone_smoke_msg = f"独立运行 OK — python {_sm_pid}.xcemp validate 通过 ✅"
                else:
                    _out_text = (_stderr or _stdout or b"").decode("utf-8", errors="replace")[:300]
                    _standalone_smoke_msg = (
                        f"validate 失败（退出码 {_proc.returncode}）：{_out_text}"
                    )
                    if _pack and _pack.is_dir() and _sm_manifest:
                        _repair_msg = await _facade()._standalone_smoke_auto_repair(
                            _pack, _sm_manifest, _sm_pid, _sm_vendor_modules_first
                        )
                        _standalone_smoke_msg = _repair_msg
                        if "成功" in _repair_msg or "✅" in _repair_msg:
                            _standalone_smoke_ok = True
            except RECOVERABLE_ERRORS as _se:
                _standalone_smoke_msg = (
                    f"⚠️ 自检子进程异常：{_se}；建议手动运行 python xxx.xcemp validate 排查"
                )
            finally:
                try:
                    _facade().os.unlink(_tmp_xcemp)
                except RECOVERABLE_ERRORS:
                    pass
        else:
            _standalone_smoke_msg = "manifest 尚未生成，独立自检跳过"
            _standalone_smoke_ok = True
            _standalone_smoke_skipped = True
    except RECOVERABLE_ERRORS as _smoke_exc:
        _standalone_smoke_msg = f"⚠️ 独立自检异常：{_smoke_exc}；建议手动验证 .xcemp 包完整性"
    if not _standalone_smoke_ok:
        _standalone_smoke_msg = "⚠️ " + _standalone_smoke_msg.lstrip("⚠️ ")
    return {
        "standalone_smoke_ok": _standalone_smoke_ok,
        "standalone_smoke_msg": _standalone_smoke_msg,
        "standalone_smoke_skipped": _standalone_smoke_skipped,
    }


async def _standalone_smoke_auto_repair(
    pack_dir: _facade().Path,
    manifest: _facade().Dict[str, _facade().Any],
    pack_id: str,
    vendor_modules: _facade().Optional[_facade().Dict[str, str]] = None,
) -> str:
    from modstore_server.employee_pack_export import (
        _build_employee_pack_zip_with_source,
        collect_vendor_modules_from_pack,
    )

    try:
        await _facade().asyncio.sleep(0)
        from modstore_server.employee_pack_blueprints_template import (
            render_employee_pack_blueprints_py,
            render_employee_pack_employee_py,
        )
        from modstore_server.mod_employee_impl_scaffold import sanitize_employee_stem

        _sm_emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
        _sm_eid = pack_id
        _sm_stem = sanitize_employee_stem(_sm_eid)
        _sm_label = str(_sm_emp.get("label") or _sm_eid).strip()
        _bp_content = render_employee_pack_blueprints_py(
            pack_id=pack_id, employee_id=_sm_eid, stem=_sm_stem, label=_sm_label
        )
        _sm_v2 = (
            manifest.get("employee_config_v2")
            if isinstance(manifest.get("employee_config_v2"), dict)
            else {}
        )
        _sm_actions = _sm_v2.get("actions") if isinstance(_sm_v2.get("actions"), dict) else {}
        _sm_handlers = (
            _sm_actions.get("handlers") if isinstance(_sm_actions.get("handlers"), list) else []
        )
        _is_direct_python = "direct_python" in _sm_handlers
        if _is_direct_python:
            from modstore_server.employee_asset_pipeline import (
                render_direct_python_asset_worker,
            )

            _rule_spec_path = pack_dir / "rule_spec.json"
            _sm_rule_spec = {}
            if _rule_spec_path.is_file():
                try:
                    _sm_rule_spec = _facade().json.loads(
                        _rule_spec_path.read_text(encoding="utf-8")
                    )
                except RECOVERABLE_ERRORS:
                    pass
            _runtime_mod = (
                _facade().re.sub("[^a-z0-9_]+", "_", (_sm_eid or pack_id).lower()).strip("_")
            )
            if _runtime_mod.endswith("_employee"):
                _runtime_mod = _runtime_mod[: -len("_employee")] or _runtime_mod
            _emp_content = render_direct_python_asset_worker(
                employee_id=_sm_eid,
                label=_sm_label,
                runtime_module=_runtime_mod,
                rule_spec=_sm_rule_spec,
            )
        else:
            _emp_content = render_employee_pack_employee_py(
                employee_id=_sm_eid, stem=_sm_stem, label=_sm_label
            )
        _bp_path = pack_dir / "backend" / "blueprints.py"
        _emp_path = pack_dir / "backend" / "employees" / f"{_sm_stem}.py"
        if _bp_path.parent.is_dir():
            _bp_path.write_text(_bp_content, encoding="utf-8")
        if _emp_path.parent.is_dir():
            _emp_path.write_text(_emp_content, encoding="utf-8")
        _sm_vendor_modules = (
            collect_vendor_modules_from_pack(pack_dir)
            if _is_direct_python and pack_dir.is_dir()
            else None
        )
        _sm_zip_bytes = _build_employee_pack_zip_with_source(
            pack_id, manifest, None, vendor_modules=_sm_vendor_modules
        )
        with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as _tf2:
            _tf2.write(_sm_zip_bytes)
            _tmp_xcemp2 = _tf2.name
        try:
            _proc2 = await _facade().asyncio.wait_for(
                _facade().asyncio.create_subprocess_exec(
                    _facade().sys.executable,
                    _tmp_xcemp2,
                    "validate",
                    stdout=_facade().asyncio.subprocess.PIPE,
                    stderr=_facade().asyncio.subprocess.PIPE,
                ),
                timeout=20,
            )
            _stdout2, _stderr2 = await _facade().asyncio.wait_for(_proc2.communicate(), timeout=20)
            if _proc2.returncode == 0:
                return "自检失败后自动修复成功 ✅ — 已重新生成 backend 代码并通过 validate"
            else:
                _out_text2 = (_stderr2 or _stdout2 or b"").decode("utf-8", errors="replace")[:200]
                return f"⚠️ 自动修复后仍失败：{_out_text2}；建议手动检查 run() 函数"
        finally:
            try:
                _facade().os.unlink(_tmp_xcemp2)
            except RECOVERABLE_ERRORS:
                pass
    except RECOVERABLE_ERRORS as _repair_exc:
        return f"⚠️ 自动修复异常：{_repair_exc}；建议手动检查 backend/employees/*.py"


async def _craft_host_check(
    *, fhd_base: str, user_id: int = 0, **_kw: _facade().Any
) -> _facade().Dict[str, _facade().Any]:
    host_probe: _facade().Dict[str, _facade().Any] = {"skipped": True}
    host_check_msg = "未配置 fhd_base_url，已跳过；如需部署到宿主，请在环境变量或配置中设置 FHD_BASE_URL 后重新运行连通性检查"
    if not fhd_base:
        return {"host_probe": host_probe, "host_check_msg": host_check_msg}
    try:
        from modstore_server.infrastructure.http_clients import get_external_client

        base = fhd_base.rstrip("/")
        host_warnings: _facade().List[str] = []
        client = get_external_client()
        r = await client.get(f"{base}/api/mods/", timeout=10.0)
        host_probe = {
            "skipped": False,
            "ok": r.status_code < 500,
            "status_code": r.status_code,
            "url": f"{base}/api/mods/",
        }
        try:
            lr = await client.get(f"{base}/api/mods/llm-status")
            if lr.status_code == 200:
                try:
                    lj = lr.json()
                    if isinstance(lj, dict) and lj.get("api_key_configured") is False:
                        host_warnings.append(
                            "宿主返回 llm-status：未配置 LLM API Key，员工运行时可能无法调用模型"
                        )
                except RECOVERABLE_ERRORS:
                    host_warnings.append("llm-status 返回非 JSON，跳过密钥探测")
            elif lr.status_code == 404:
                host_warnings.append(
                    "宿主未提供 /api/mods/llm-status（可选），无法在编排阶段探测 LLM 密钥"
                )
        except RECOVERABLE_ERRORS:
            host_warnings.append("无法请求宿主 /api/mods/llm-status（可选端点）")
        try:
            vr = await client.get(f"{base}/api/version")
            if vr.status_code == 200:
                try:
                    vj = vr.json()
                    if isinstance(vj, dict) and vj.get("min_mod_sdk_version"):
                        host_probe["host_min_mod_sdk_version"] = str(
                            vj.get("min_mod_sdk_version") or ""
                        )
                except RECOVERABLE_ERRORS:
                    pass
        except RECOVERABLE_ERRORS:
            pass
        msg = f"HTTP {r.status_code}" if host_probe.get("ok") else f"HTTP {r.status_code}（异常）"
        if host_warnings:
            msg += "；" + "；".join(host_warnings[:3])[:400]
            host_probe["warnings"] = host_warnings
        host_check_msg = msg[:480]
    except RECOVERABLE_ERRORS as e:
        host_probe = {"skipped": False, "ok": False, "error": str(e)[:300]}
        host_check_msg = f"探测失败: {e!s}"[:300]
    return {"host_probe": host_probe, "host_check_msg": host_check_msg}


async def _craft_six_dim_gate(
    *,
    pack_dir: _facade().Any = None,
    pipeline_label: str = "",
    routing_brief: str = "",
    structured_requirement: _facade().Any = None,
    spec_warnings: _facade().Any = None,
    validate_errors: _facade().Any = None,
    mod_sandbox: _facade().Any = None,
    workflow_sandbox: _facade().Any = None,
    workflow_biz_ok: _facade().Any = None,
    standalone_smoke_ok: bool = True,
    catalog_registered: bool = True,
    employee_target: str = "pack_only",
    asset_count: int = 0,
    domain_smoke: _facade().Any = None,
    golden_comparison: _facade().Any = None,
    runtime_generation: _facade().Any = None,
    target_employee_id: str = "",
    user_id: int = 0,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.employee_six_dimension import compute_six_dimension_report
    from modstore_server.employee_six_dimension_llm import (
        enrich_six_dimension_report_with_llm,
    )

    _pack = (
        _facade().Path(str(pack_dir))
        if pack_dir and (not isinstance(pack_dir, _facade().Path))
        else pack_dir
    )
    _pack_path = _pack or _facade().Path(".")
    report = compute_six_dimension_report(
        pack_dir=_pack_path,
        pipeline_label=pipeline_label or "",
        routing_brief=routing_brief or "",
        structured_requirement=(
            structured_requirement if isinstance(structured_requirement, dict) else None
        ),
        spec_warnings=spec_warnings if isinstance(spec_warnings, list) else None,
        validate_errors=validate_errors if isinstance(validate_errors, list) else None,
        mod_sandbox=mod_sandbox if isinstance(mod_sandbox, dict) else None,
        workflow_sandbox=workflow_sandbox if isinstance(workflow_sandbox, dict) else None,
        workflow_biz_ok=workflow_biz_ok,
        standalone_smoke_ok=bool(standalone_smoke_ok),
        catalog_registered=bool(catalog_registered),
        employee_target=employee_target or "pack_only",
        asset_count=int(asset_count or 0),
        domain_smoke=domain_smoke if isinstance(domain_smoke, dict) else None,
        golden_comparison=golden_comparison if isinstance(golden_comparison, dict) else None,
        runtime_generation=runtime_generation if isinstance(runtime_generation, dict) else None,
    )
    eid = (target_employee_id or _kw.get("employee_id") or "").strip()
    if not eid and _pack_path.is_dir():
        try:
            mf = _facade().json.loads((_pack_path / "manifest.json").read_text(encoding="utf-8"))
            eid = str(mf.get("id") or (mf.get("identity") or {}).get("id") or "").strip()
        except RECOVERABLE_ERRORS:
            eid = ""
    llm_report, llm_meta = await enrich_six_dimension_report_with_llm(
        report,
        pack_dir=_pack_path,
        target_employee_id=eid or "unknown",
        pipeline_label=pipeline_label or report.get("pipeline_label") or "",
        routing_brief=routing_brief or "",
        validate_errors=validate_errors if isinstance(validate_errors, list) else None,
        mod_sandbox=mod_sandbox if isinstance(mod_sandbox, dict) else None,
        user_id=int(user_id or 0),
    )
    return {"six_dimension_report": llm_report, "six_dimension_llm_meta": llm_meta}


def register_all_craft_steps() -> None:
    _facade().register_craft_step("spec", _facade()._craft_spec)
    _facade().register_craft_step("employee_plan", _facade()._craft_employee_plan)
    _facade().register_craft_step("generate", _facade()._craft_generate)
    _facade().register_craft_step("validate", _facade()._craft_validate)
    _facade().register_craft_step("script_workflow", _facade()._craft_script_workflow)
    _facade().register_craft_step("embed_script", _facade()._craft_embed_script)
    _facade().register_craft_step("workflow", _facade()._craft_workflow)
    _facade().register_craft_step("register_pack", _facade()._craft_register_pack)
    _facade().register_craft_step("workflow_sandbox", _facade()._craft_workflow_sandbox)
    _facade().register_craft_step("mod_sandbox", _facade()._craft_mod_sandbox)
    _facade().register_craft_step("standalone_smoke", _facade()._craft_standalone_smoke)
    _facade().register_craft_step("host_check", _facade()._craft_host_check)
    _facade().register_craft_step("six_dim_gate", _facade()._craft_six_dim_gate)
