# mypy: disable-error-code="attr-defined, misc, no-any-return, type-arg, valid-type"
# isort: skip_file
"""Employee build pipeline phase."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


async def _run_employee_pipeline_phase_02(ctx: dict[str]) -> bool:
    if ctx["_should_skip"]("generate"):
        await _facade()._set_step(ctx["sid"], "generate", "done", "已完成（重试复用）")
    else:
        ctx["_emp_current_step"] = "generate"
        _gen_running_msg = (
            "正在解析上传资产并生成员工包"
            if ctx["_use_asset_pipeline"]
            else (
                "正在生成 LLM 驱动文档审核员工包"
                if ctx["_needs_llm_reasoning"] and ctx["_uploaded_docx"]
                else None
            )
        )
        await _facade()._set_step(ctx["sid"], "generate", "running", _gen_running_msg)
        _plan_payload = dict(ctx["payload"]) if isinstance(ctx["payload"], dict) else {}
        if isinstance(ctx["employee_plan"], dict) and ctx["employee_plan"]:
            _plan_payload["employee_plan"] = ctx["employee_plan"]
        _scaffold_kw = dict(
            session_id=ctx["sid"],
            brief=ctx["employee_brief"],
            raw_files=ctx["employee_files"],
            replace=ctx["replace"],
            provider=ctx["prov"],
            model=ctx["mdl"],
            publish_to_catalog=False,
            force_llm_codegen=True,
            payload=_plan_payload or None,
        )
        if ctx["_use_word_extract_pipeline"]:
            from modstore_server.employee_asset_pipeline import (
                run_word_extract_employee_scaffold_async,
            )

            _gen_result = await _facade()._dispatch_craft_step(
                "generate",
                db=ctx["db"],
                user=ctx["user"],
                session_id=ctx["sid"],
                brief=ctx["employee_brief"],
                raw_files=ctx["employee_files"],
                replace=ctx["replace"],
                provider=ctx["prov"],
                model=ctx["mdl"],
                use_word_extract=True,
                payload=ctx["payload"],
            )
            ctx["res"] = (
                _gen_result["res"]
                if _gen_result
                else await run_word_extract_employee_scaffold_async(
                    ctx["db"], ctx["user"], **_scaffold_kw
                )
            )
        elif ctx["_use_asset_pipeline"]:
            from modstore_server.employee_asset_pipeline import (
                run_asset_employee_scaffold_async,
            )

            _gen_result = await _facade()._dispatch_craft_step(
                "generate",
                db=ctx["db"],
                user=ctx["user"],
                session_id=ctx["sid"],
                brief=ctx["employee_brief"],
                raw_files=ctx["employee_files"],
                replace=ctx["replace"],
                provider=ctx["prov"],
                model=ctx["mdl"],
                payload=ctx["payload"],
            )
            ctx["res"] = (
                _gen_result["res"]
                if _gen_result
                else await run_asset_employee_scaffold_async(ctx["db"], ctx["user"], **_scaffold_kw)
            )
        elif ctx["_needs_llm_reasoning"] and ctx["_uploaded_docx"]:
            from modstore_server.employee_asset_pipeline import (
                run_asset_employee_scaffold_async,
            )

            _gen_result = await _facade()._dispatch_craft_step(
                "generate",
                db=ctx["db"],
                user=ctx["user"],
                session_id=ctx["sid"],
                brief=ctx["employee_brief"],
                raw_files=ctx["employee_files"],
                replace=ctx["replace"],
                provider=ctx["prov"],
                model=ctx["mdl"],
                payload=ctx["payload"],
            )
            ctx["res"] = (
                _gen_result["res"]
                if _gen_result
                else await run_asset_employee_scaffold_async(ctx["db"], ctx["user"], **_scaffold_kw)
            )
        else:
            ctx["res"] = await _facade().run_employee_ai_scaffold_async(
                ctx["db"],
                ctx["user"],
                brief=ctx["employee_brief"],
                replace=ctx["replace"],
                provider=ctx["prov"],
                model=ctx["mdl"],
                publish_to_catalog=False,
            )
        if not ctx["res"].get("ok"):
            warns = (
                ctx["res"].get("validate_warnings")
                if isinstance(ctx["res"].get("validate_warnings"), list)
                else []
            )
            errs = (
                ctx["res"].get("validate_errors")
                if isinstance(ctx["res"].get("validate_errors"), list)
                else []
            )
            if errs or not warns:
                await _facade()._fail_session(
                    ctx["sid"],
                    "generate",
                    ctx["res"].get("error") or "；".join(errs[:3]) or "生成失败",
                )
                return True
        if ctx["_use_word_extract_pipeline"] or ctx["_use_asset_pipeline"]:
            from modstore_server.vibecoding_convert_loop import is_llm_codegen_source

            _rt_gate = (
                ctx["res"].get("runtime_generation")
                if isinstance(ctx["res"].get("runtime_generation"), dict)
                else {}
            )
            _ds_gate = (
                ctx["res"].get("domain_smoke")
                if isinstance(ctx["res"].get("domain_smoke"), dict)
                else {}
            )
            _gc_gate = (
                ctx["res"].get("golden_comparison")
                if isinstance(ctx["res"].get("golden_comparison"), dict)
                else {}
            )
            if not is_llm_codegen_source(_rt_gate):
                await _facade()._fail_session(
                    ctx["sid"],
                    "generate",
                    f"convert 须由 LLM 生成（当前 source={_rt_gate.get('source') or 'unknown'}）",
                )
                return True
            if _ds_gate.get("ok") is False:
                await _facade()._fail_session(
                    ctx["sid"],
                    "generate",
                    f"领域冒烟未通过：{_ds_gate.get('error') or 'failed'}"[:1000],
                )
                return True
            if _gc_gate and _gc_gate.get("golden_pack_id") and (not _gc_gate.get("passed")):
                await _facade()._fail_session(
                    ctx["sid"],
                    "generate",
                    f"黄金对比未达标：parity={_gc_gate.get('parity_score')} diffs={len(_gc_gate.get('diff_items') or [])}"[
                        :1000
                    ],
                )
                return True
        _gen_pack_dir = _facade().Path(str(ctx["res"].get("path") or ""))
        if ctx["_use_word_extract_pipeline"] and _gen_pack_dir.is_dir():
            ctx["reconcile_employee_pack_manifest"](_gen_pack_dir, brief=ctx["employee_brief"])
            _gx_errs, ctx["_"] = ctx["validate_word_extract_backend"](_gen_pack_dir)
            if _gx_errs:
                await _facade()._fail_session(ctx["sid"], "generate", "；".join(_gx_errs[:3]))
                return True
        asset_count = (
            len((ctx["res"].get("asset_manifest") or {}).get("assets") or [])
            if isinstance(ctx["res"].get("asset_manifest"), dict)
            else 0
        )
        if ctx["_use_word_extract_pipeline"]:
            _rt_meta = (
                ctx["res"].get("runtime_generation")
                if isinstance(ctx["res"].get("runtime_generation"), dict)
                else {}
            )
            _gc_meta = (
                ctx["res"].get("golden_comparison")
                if isinstance(ctx["res"].get("golden_comparison"), dict)
                else {}
            )
            _round = _rt_meta.get("round")
            _parity = _gc_meta.get("parity_score")
            _gen_done_msg = "已生成 Word 全量提取员工包（LLM convert"
            if _round is not None:
                _gen_done_msg += f"，repair 轮次 {_round}"
            if _parity is not None:
                _gen_done_msg += f"，黄金 parity {_parity}"
            _gen_done_msg += "）"
        elif ctx["_use_asset_pipeline"]:
            _gen_done_msg = f"已生成资产驱动员工包；资产 {asset_count} 个"
        elif ctx["_needs_llm_reasoning"] and ctx["_uploaded_docx"]:
            _gen_done_msg = "已生成 LLM 驱动文档审核员工包"
        else:
            _gen_done_msg = None
        await _facade()._set_step(ctx["sid"], "generate", "done", _gen_done_msg)
    if ctx["_should_skip"]("validate"):
        await _facade()._set_step(ctx["sid"], "validate", "done", "已完成（重试复用）")
    else:
        ctx["_emp_current_step"] = "validate"
        await _facade()._set_step(ctx["sid"], "validate", "running")
        _val_result = await _facade()._dispatch_craft_step(
            "validate",
            res=ctx["res"],
            brief=ctx["employee_brief"] or ctx["_routing_brief"] or ctx["brief"],
            pack_dir=ctx["res"].get("path"),
            user_id=ctx["user_id"],
        )
        validate_warnings = (
            _val_result.get("validate_warnings")
            if _val_result and isinstance(_val_result.get("validate_warnings"), list)
            else (
                ctx["res"].get("validate_warnings")
                if isinstance(ctx["res"].get("validate_warnings"), list)
                else []
            )
        )
        validate_errors = (
            _val_result.get("validate_errors")
            if _val_result and isinstance(_val_result.get("validate_errors"), list)
            else []
        )
        async with _facade()._SESSION_LOCK:
            ctx["sess"] = _facade().WORKBENCH_SESSIONS.get(ctx["sid"])
            if ctx["sess"]:
                ctx["sess"]["validate_warnings"] = validate_warnings
                if validate_errors:
                    ctx["sess"]["validate_errors"] = validate_errors
                _facade()._persist_workbench_session_unlocked(ctx["sid"])
        if validate_errors:
            ctx["msg"] = "；".join((str(ctx["x"]) for ctx["x"] in validate_errors[:5]))
            await _facade()._set_step(ctx["sid"], "validate", "error", ctx["msg"][:480])
            await _facade()._fail_session(ctx["sid"], "validate", ctx["msg"][:1000])
            return True
        await _facade()._set_step(
            ctx["sid"],
            "validate",
            "done",
            (
                "；".join((str(ctx["x"]) for ctx["x"] in validate_warnings[:5]))
                if validate_warnings
                else "manifest、Python 与包体校验通过"
            ),
        )
        ctx["pack_dir"] = _facade().Path(str(ctx["res"].get("path") or ""))
        ctx["script_wf"]: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
        ctx["script_attachment"]: _facade().Dict[str, _facade().Any] = {}
        ctx["script_result"]: _facade().Dict[str, _facade().Any] = {}
    return False
