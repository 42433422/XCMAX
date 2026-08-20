# mypy: disable-error-code="attr-defined, misc, no-any-return, no-redef, type-arg, valid-type"
# isort: skip_file
"""Employee build pipeline phase."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_employee_pipeline_phase_05(ctx: dict[str]) -> bool:
    if ctx["_should_skip"]("mod_sandbox"):
        await _facade()._set_step(ctx["sid"], "mod_sandbox", "done", "已完成（重试复用）")
    else:
        ctx["_emp_current_step"] = "mod_sandbox"
        await _facade()._set_step(
            ctx["sid"], "mod_sandbox", "running", "正在校验包体（manifest / Python）"
        )
        _msb_result = await _facade()._dispatch_craft_step(
            "mod_sandbox",
            pack_dir=ctx["pack_dir"],
            wf_attach=ctx["wf_attach"],
            user_id=ctx["user_id"],
        )
        if _msb_result:
            ctx["emp_mod_sandbox"] = _msb_result["emp_mod_sandbox"]
            mod_sb_msg = _msb_result["mod_sb_msg"]
            mod_checks = ctx["emp_mod_sandbox"].get("checks", [])
        else:
            mod_checks: _facade().List[_facade().Dict[str, _facade().Any]] = []
            if ctx["pack_dir"].is_dir():
                _mf, mf_err = _facade().read_manifest(ctx["pack_dir"])
                mod_checks.append(
                    {
                        "id": "manifest",
                        "ok": mf_err is None,
                        "message": mf_err or "manifest 可读取",
                    }
                )
                py_warns = _facade().mod_compileall_warnings(ctx["pack_dir"])
                mod_checks.append(
                    {
                        "id": "python_compile",
                        "ok": not py_warns,
                        "message": (
                            "；".join(py_warns) if py_warns else "未发现需编译的 Python 或检查通过"
                        ),
                    }
                )
                cons_warns = _facade().employee_pack_consistency_warnings(ctx["pack_dir"])
                mod_checks.append(
                    {
                        "id": "employee_pack_consistency",
                        "ok": not cons_warns,
                        "message": (
                            "；".join(cons_warns)[:1200]
                            if cons_warns
                            else "manifest ↔ employees 一致性检查通过"
                        ),
                    }
                )
                vibe_checks = _facade()._check_vibe_coding_capability(
                    ctx["pack_dir"], ctx["wf_attach"]
                )
                mod_checks.extend(vibe_checks)
            else:
                mod_checks.append(
                    {
                        "id": "manifest",
                        "ok": False,
                        "message": f"包目录无效: {ctx['pack_dir']}",
                    }
                )
            ctx["emp_mod_sandbox"] = {
                "ok": all((c.get("ok") for c in mod_checks)) if mod_checks else False,
                "checks": mod_checks,
                "note": "员工包轻量校验（含 backend/blueprints 运行时与 vibe-coding 能力检查）",
            }
            _all_pass = ctx["emp_mod_sandbox"]["ok"]
            _vibe_gaps = [c for c in mod_checks if not c.get("ok") and "vibe" in c.get("id", "")]
            if _all_pass:
                mod_sb_msg = "包体轻量校验通过"
            elif _vibe_gaps:
                mod_sb_msg = "基础校验通过，vibe-coding 能力存在缺口：" + "；".join(
                    (c.get("message", "") for c in _vibe_gaps)
                )
            else:
                mod_sb_msg = "包体校验有提示，见会话 artifact.mod_sandbox"
        _prompt_chk = next(
            (c for c in mod_checks if str(c.get("id") or "") == "vibe_system_prompt_quality"),
            None,
        )
        if _prompt_chk is not None and (not _prompt_chk.get("ok")):
            ctx["msg"] = str(
                _prompt_chk.get("message") or "backend/employees/*.py 缺少 SYSTEM_PROMPT"
            )
            await _facade()._set_step(ctx["sid"], "mod_sandbox", "error", ctx["msg"][:480])
            await _facade()._fail_session(ctx["sid"], "mod_sandbox", ctx["msg"][:2000])
            return True
        _runtime_chk_id = {
            "word_full_extract": "word_extract_runtime",
            "txt_full_read": "txt_read_runtime",
            "txt_generate": "txt_generate_runtime",
        }.get(ctx["_pipeline_label"], "")
        _wx_runtime_chk = (
            next(
                (c for c in mod_checks if str(c.get("id") or "") == _runtime_chk_id),
                None,
            )
            if _runtime_chk_id
            else None
        )
        if (
            ctx["_pipeline_label"] in ("word_full_extract", "txt_full_read", "txt_generate")
            and _wx_runtime_chk is not None
            and (not _wx_runtime_chk.get("ok"))
        ):
            ctx["msg"] = str(
                _wx_runtime_chk.get("message") or f"{ctx['_pipeline_label']} runtime 校验未通过"
            )
            await _facade()._set_step(ctx["sid"], "mod_sandbox", "error", ctx["msg"][:480])
            await _facade()._fail_session(ctx["sid"], "mod_sandbox", ctx["msg"][:1000])
            return True
        await _facade()._set_step(ctx["sid"], "mod_sandbox", "done", mod_sb_msg[:480])
    if ctx["_should_skip"]("standalone_smoke"):
        await _facade()._set_step(ctx["sid"], "standalone_smoke", "done", "已完成（重试复用）")
    else:
        ctx["_emp_current_step"] = "standalone_smoke"
        await _facade()._set_step(
            ctx["sid"],
            "standalone_smoke",
            "running",
            "正在生成独立包并验证 python xxx.xcemp validate …",
        )
        _ss_result = await _facade()._dispatch_craft_step(
            "standalone_smoke",
            res=ctx["res"],
            pack_dir=ctx["pack_dir"],
            user_id=ctx["user_id"],
        )
        if _ss_result:
            ctx["_standalone_smoke_ok"] = _ss_result["standalone_smoke_ok"]
            _standalone_smoke_msg = _ss_result["standalone_smoke_msg"]
            _standalone_smoke_skipped = _ss_result.get("standalone_smoke_skipped", False)
        else:
            ctx["_standalone_smoke_ok"] = False
            _standalone_smoke_skipped = False
            _standalone_smoke_msg = "跳过（未能获取包字节）"
        _standalone_smoke_status = (
            "skipped"
            if _standalone_smoke_skipped
            else "error" if not ctx["_standalone_smoke_ok"] else "done"
        )
        if _standalone_smoke_status == "error" and ctx["_pipeline_label"] not in (
            "word_full_extract",
            "txt_full_read",
            "txt_generate",
        ):
            _standalone_smoke_status = "skipped"
            _standalone_smoke_msg = (
                f"⚠️ 独立包自检未通过，已跳过继续后续步骤：{_standalone_smoke_msg}"
            )
        elif _standalone_smoke_status == "error":
            await _facade()._set_step(
                ctx["sid"], "standalone_smoke", "error", _standalone_smoke_msg[:480]
            )
            await _facade()._fail_session(
                ctx["sid"], "standalone_smoke", _standalone_smoke_msg[:1000]
            )
            return True
        await _facade()._set_step(
            ctx["sid"],
            "standalone_smoke",
            _standalone_smoke_status,
            _standalone_smoke_msg[:480],
        )
    if ctx["_should_skip"]("host_check"):
        await _facade()._set_step(ctx["sid"], "host_check", "done", "已完成（重试复用）")
    else:
        ctx["_emp_current_step"] = "host_check"
        ctx["host_probe"]: _facade().Dict[str, _facade().Any] = {"skipped": True}
        await _facade()._set_step(ctx["sid"], "host_check", "running", "探测宿主 /api/mods/")
        _hc_result = await _facade()._dispatch_craft_step(
            "host_check", fhd_base=ctx["fhd_base"] or "", user_id=ctx["user_id"]
        )
        if _hc_result:
            ctx["host_probe"] = _hc_result["host_probe"]
            host_check_msg = _hc_result["host_check_msg"]
            if ctx["host_probe"].get("skipped"):
                await _facade()._set_step(ctx["sid"], "host_check", "skipped", host_check_msg[:480])
            elif ctx["host_probe"].get("ok"):
                await _facade()._set_step(ctx["sid"], "host_check", "done", host_check_msg[:480])
            else:
                await _facade()._set_step(ctx["sid"], "host_check", "done", host_check_msg[:480])
        elif ctx["fhd_base"]:
            try:
                from modstore_server.infrastructure.http_clients import (
                    get_external_client,
                )

                base = ctx["fhd_base"].rstrip("/")
                host_warnings: _facade().List[str] = []
                client = get_external_client()
                r = await client.get(f"{base}/api/mods/", timeout=10.0)
                ctx["host_probe"] = {
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
                                ctx["host_probe"]["host_min_mod_sdk_version"] = str(
                                    vj.get("min_mod_sdk_version") or ""
                                )
                        except RECOVERABLE_ERRORS:
                            pass
                except RECOVERABLE_ERRORS:
                    pass
                ctx["msg"] = (
                    f"HTTP {r.status_code}"
                    if ctx["host_probe"].get("ok")
                    else f"HTTP {r.status_code}（异常）"
                )
                if host_warnings:
                    ctx["msg"] += "；" + "；".join(host_warnings[:3])[:400]
                    ctx["host_probe"]["warnings"] = host_warnings
                await _facade()._set_step(ctx["sid"], "host_check", "done", ctx["msg"][:480])
            except RECOVERABLE_ERRORS:
                ctx["host_probe"] = {
                    "skipped": False,
                    "ok": False,
                    "error": str(ctx["e"])[:300],
                }
                await _facade()._set_step(
                    ctx["sid"], "host_check", "done", f"探测失败: {ctx['e']!s}"[:300]
                )
        else:
            _host_skip = (
                "文件型 direct_python：本地转换无需宿主；未配置 fhd_base_url 已跳过"
                if ctx["_pipeline_label"] in ("word_full_extract", "txt_full_read", "txt_generate")
                else "未配置 fhd_base_url，已跳过；如需部署到宿主，请在环境变量或配置中设置 FHD_BASE_URL 后重新运行连通性检查"
            )
            await _facade()._set_step(ctx["sid"], "host_check", "skipped", _host_skip)
    return False
