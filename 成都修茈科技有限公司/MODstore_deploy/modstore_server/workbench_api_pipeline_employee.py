# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
"""Workbench employee pipeline branch."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


from modstore_server.workbench_api_pipeline_employee_phase01 import (
    _run_employee_pipeline_phase_01,
)
from modstore_server.workbench_api_pipeline_employee_phase02 import (
    _run_employee_pipeline_phase_02,
)
from modstore_server.workbench_api_pipeline_employee_phase03 import (
    _run_employee_pipeline_phase_03,
)
from modstore_server.workbench_api_pipeline_employee_phase04 import (
    _run_employee_pipeline_phase_04,
)
from modstore_server.workbench_api_pipeline_employee_phase05 import (
    _run_employee_pipeline_phase_05,
)
from modstore_server.workbench_api_pipeline_employee_phase06 import (
    _run_employee_pipeline_phase_06,
)
from modstore_server.workbench_api_pipeline_employee_phase07 import (
    _run_employee_pipeline_phase_07,
)


async def _run_workbench_employee_pipeline(
    sid, user_id, payload, intent, brief, prov, mdl, replace, db, user
):
    et = str(payload.get("employee_target") or "pack_only").strip().lower()
    embed_script_workflow = bool(payload.get("embed_script_workflow", True))
    wf_name = (payload.get("employee_workflow_name") or "").strip() or None
    fhd_base = (
        (payload.get("fhd_base_url") or "").strip()
        or (_facade().os.environ.get("FHD_BASE_URL") or "").strip()
        or None
    )
    employee_files = payload.get("_files") or []
    from modstore_server.employee_brief_utils import (
        extract_routing_brief,
        is_contract_doc_review_brief,
    )
    from modstore_server.employee_pipeline_routing import classify_employee_pipeline

    _routing_brief = extract_routing_brief(payload, fallback=brief)
    _emp_brief_lower = (_routing_brief or brief or "").lower()
    _needs_llm_reasoning = is_contract_doc_review_brief(_routing_brief) or any(
        (
            k in _emp_brief_lower
            for k in (
                "合同",
                "法务",
                "合规",
                "审核",
                "条款",
                "法律",
                "评审",
                "分析",
                "建议",
                "contract",
                "legal",
                "compliance",
                "review",
                "analyze",
            )
        )
    )
    (
        _pipeline_label,
        _use_word_extract_pipeline,
        _use_txt_pipeline,
        _use_pdf_pipeline,
        _use_asset_pipeline,
    ) = classify_employee_pipeline(
        _routing_brief,
        employee_files=employee_files,
        needs_llm_reasoning=_needs_llm_reasoning,
    )
    _uploaded_docx = _facade()._contains_uploaded_docx(employee_files)
    from modstore_server.employee_pipeline_routing import (
        resolve_employee_runtime_kind,
        validate_runtime_pipeline_consistency,
    )

    _expected_runtime_kind = resolve_employee_runtime_kind(_routing_brief)
    _pipe_ok, _pipe_err = validate_runtime_pipeline_consistency(
        routing_brief=_routing_brief,
        pipeline_label=_pipeline_label,
        rule_spec={"runtime_kind": _expected_runtime_kind},
    )
    if not _pipe_ok:
        await _facade()._fail_session(sid, "spec", _pipe_err[:1000])
        return
    _resume_cp = None
    async with _facade()._SESSION_LOCK:
        _sess_rc = _facade().WORKBENCH_SESSIONS.get(sid)
        if _sess_rc:
            _resume_cp = _sess_rc.get("_resume_checkpoint")
            if _resume_cp:
                del _sess_rc["_resume_checkpoint"]
                _facade()._persist_workbench_session_unlocked(sid)
    if _resume_cp and _resume_cp.get("res") and _resume_cp.get("pack_dir"):
        res = _resume_cp["res"]
        pack_dir = _facade().Path(_resume_cp["pack_dir"])
        employee_plan = _resume_cp.get("employee_plan")
        script_wf = _resume_cp.get("script_wf")
        script_attachment = _resume_cp.get("script_attachment") or {}
        wf_attach = _resume_cp.get("wf_attach") or {}
        saved_package = _resume_cp.get("saved_package") or {}
        published_to_catalog = _resume_cp.get("published_to_catalog", False)
        et = _resume_cp.get("employee_target") or et
        embed_script_workflow = _resume_cp.get("embed_script_workflow", embed_script_workflow)
        wf_name = _resume_cp.get("wf_name") or wf_name
        fhd_base = _resume_cp.get("fhd_base") or fhd_base
        _resume_from = _resume_cp.get("failed_step", "embed_script")
        _facade()._LOG.info(
            "pipeline resume session=%s from step=%s pack_dir=%s",
            sid,
            _resume_from,
            pack_dir,
        )
    else:
        _resume_from = None
    _emp_current_step = "employee_plan"
    _EMP_STEP_ORDER = [
        "spec",
        "employee_plan",
        "generate",
        "validate",
        "script_workflow",
        "embed_script",
        "workflow",
        "register_pack",
        "workflow_sandbox",
        "mod_sandbox",
        "standalone_smoke",
        "host_check",
        "six_dim_gate",
        "complete",
    ]

    def _should_skip(step_id: str) -> bool:
        if not _resume_from or _resume_from not in _EMP_STEP_ORDER:
            return False
        return _EMP_STEP_ORDER.index(step_id) < _EMP_STEP_ORDER.index(_resume_from)

    from modstore_server.employee_brief_utils import compact_routing_brief
    from modstore_server.employee_pack_cleanup import cleanup_experimental_pack

    ctx = {
        "_emp_current_step": _emp_current_step,
        "_needs_llm_reasoning": _needs_llm_reasoning,
        "_pipeline_label": _pipeline_label,
        "_routing_brief": _routing_brief,
        "_should_skip": _should_skip,
        "_uploaded_docx": _uploaded_docx,
        "_use_asset_pipeline": _use_asset_pipeline,
        "_use_word_extract_pipeline": _use_word_extract_pipeline,
        "brief": brief,
        "compact_routing_brief": compact_routing_brief,
        "db": db,
        "embed_script_workflow": embed_script_workflow,
        "employee_files": employee_files,
        "employee_plan": employee_plan,
        "et": et,
        "fhd_base": fhd_base,
        "replace": replace,
        "cleanup_experimental_pack": cleanup_experimental_pack,
        "mdl": mdl,
        "pack_dir": pack_dir,
        "payload": payload,
        "prov": prov,
        "published_to_catalog": published_to_catalog,
        "res": res,
        "saved_package": saved_package,
        "script_attachment": script_attachment,
        "script_wf": script_wf,
        "sid": sid,
        "user": user,
        "user_id": user_id,
        "wf_attach": wf_attach,
        "wf_name": wf_name,
    }
    try:
        if await _run_employee_pipeline_phase_01(ctx):
            return
        if await _run_employee_pipeline_phase_02(ctx):
            return
        if await _run_employee_pipeline_phase_03(ctx):
            return
        if await _run_employee_pipeline_phase_04(ctx):
            return
        if await _run_employee_pipeline_phase_05(ctx):
            return
        if await _run_employee_pipeline_phase_06(ctx):
            return
        if await _run_employee_pipeline_phase_07(ctx):
            return
    except RECOVERABLE_ERRORS as e:
        ctx["e"] = e
        import traceback as _tb

        _emp_id_debug = ""
        try:
            if ctx["pack_dir"] and ctx["pack_dir"].is_dir():
                _mf_dbg = ctx["pack_dir"] / "manifest.json"
                if _mf_dbg.is_file():
                    _mf_dbg_data = _facade().json.loads(_mf_dbg.read_text(encoding="utf-8"))
                    _emp_dbg = _mf_dbg_data.get("employee") or {}
                    _wf_dbg = _mf_dbg_data.get("workflow_employees") or []
                    _emp_id_debug = " [disk: manifest.id=%s employee.id=%s wf[0].id=%s]" % (
                        _mf_dbg_data.get("id"),
                        _emp_dbg.get("id"),
                        _wf_dbg[0].get("id") if _wf_dbg else "N/A",
                    )
        except RECOVERABLE_ERRORS:
            pass
        _facade()._LOG.exception(
            "workbench employee pipeline failed session=%s step=%s err=%s%s\nTRACEBACK:\n%s",
            ctx["sid"],
            ctx["_emp_current_step"],
            ctx["e"],
            _emp_id_debug,
            _tb.format_exc(),
        )
        try:
            _fail_pack = ""
            if isinstance(ctx["res"], dict):
                _fail_pack = str(ctx["res"].get("id") or "")
            if not _fail_pack and ctx["pack_dir"]:
                _fail_pack = ctx["pack_dir"].name
            if _fail_pack:
                ctx["cleanup_experimental_pack"](
                    _fail_pack,
                    metadata=ctx["payload"] if isinstance(ctx["payload"], dict) else None,
                )
        except RECOVERABLE_ERRORS as _clean_fail:
            _facade()._LOG.warning(
                "experimental cleanup on error failed session=%s: %s",
                ctx["sid"],
                _clean_fail,
            )
        async with _facade()._SESSION_LOCK:
            _sess = _facade().WORKBENCH_SESSIONS.get(ctx["sid"])
            if _sess:
                _sess["_pipeline_checkpoint"] = {
                    "failed_step": ctx["_emp_current_step"],
                    "res": (
                        ctx["res"]
                        if isinstance(ctx["res"], dict) and ctx["res"].get("ok")
                        else None
                    ),
                    "pack_dir": str(ctx["pack_dir"]) if ctx["pack_dir"] else None,
                    "employee_plan": ctx["employee_plan"],
                    "script_wf": ctx["script_wf"],
                    "script_attachment": ctx["script_attachment"],
                    "wf_attach": ctx["wf_attach"],
                    "saved_package": ctx["saved_package"],
                    "published_to_catalog": ctx["published_to_catalog"],
                    "employee_target": locals().get("et"),
                    "embed_script_workflow": locals().get("embed_script_workflow"),
                    "wf_name": locals().get("wf_name"),
                    "fhd_base": locals().get("fhd_base"),
                }
                _facade()._persist_workbench_session_unlocked(ctx["sid"])
        await _facade()._fail_session(ctx["sid"], ctx["_emp_current_step"], str(ctx["e"])[:2000])
    return
