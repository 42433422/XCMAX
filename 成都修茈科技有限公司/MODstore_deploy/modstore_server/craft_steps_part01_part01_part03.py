# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.craft_steps")


async def _craft_mod_sandbox(
    *,
    pack_dir: _facade().Any,
    wf_attach: _facade().Any = None,
    user_id: int = 0,
    db: _facade().Any = None,
    **_kw: _facade().Any,
) -> _facade().Dict[str, _facade().Any]:
    from modstore_server.mod_scaffold_runner import (
        employee_pack_consistency_warnings,
        run_employee_pack_code_validation_report,
    )

    mod_checks: _facade().List[_facade().Dict[str, _facade().Any]] = []
    _pack = _facade().Path(str(pack_dir)) if not isinstance(pack_dir, _facade().Path) else pack_dir
    validation_report = await run_employee_pack_code_validation_report(
        _pack, db=db, xcemp_timeout_seconds=20.0
    )
    mv = (
        validation_report.get("manifest_validation")
        if isinstance(validation_report.get("manifest_validation"), dict)
        else {}
    )
    pc = (
        validation_report.get("python_compile")
        if isinstance(validation_report.get("python_compile"), dict)
        else {}
    )
    cc = (
        validation_report.get("consistency_check")
        if isinstance(validation_report.get("consistency_check"), dict)
        else {}
    )
    xv = (
        validation_report.get("xcemp_validation")
        if isinstance(validation_report.get("xcemp_validation"), dict)
        else {}
    )
    mod_checks.append(
        {
            "id": "manifest_validation",
            "ok": mv.get("status") == "ok",
            "message": "；".join(mv.get("errors") or [])[:800] or "manifest 校验通过",
        }
    )
    mod_checks.append(
        {
            "id": "python_compile",
            "ok": pc.get("status") in ("ok", "skipped"),
            "message": "；".join(pc.get("errors") or [])[:800]
            or (
                "；".join(pc.get("warnings") or [])[:400]
                if pc.get("warnings")
                else "Python 编译通过"
            ),
        }
    )
    _cc_msg_parts: _facade().List[str] = []
    if cc.get("missing_depends"):
        _cc_msg_parts.append("depends_on 未注册: " + ", ".join(cc["missing_depends"][:6]))
    if cc.get("missing_skills"):
        _cc_msg_parts.append("skills 缺失: " + ", ".join(cc["missing_skills"][:6]))
    if cc.get("warnings"):
        _cc_msg_parts.append("；".join((str(w) for w in cc["warnings"][:4]))[:400])
    mod_checks.append(
        {
            "id": "consistency_check",
            "ok": cc.get("status") in ("ok", "skipped"),
            "message": "；".join(_cc_msg_parts)[:1200] if _cc_msg_parts else "一致性校验通过",
        }
    )
    mod_checks.append(
        {
            "id": "xcemp_validation",
            "ok": xv.get("status") in ("ok", "skipped"),
            "message": "；".join(xv.get("errors") or [])[:800] or "xcemp validate 通过",
        }
    )
    if _pack.is_dir():
        cons_warns = employee_pack_consistency_warnings(_pack)
        if cons_warns and cc.get("status") == "ok":
            mod_checks.append(
                {
                    "id": "employee_pack_consistency",
                    "ok": False,
                    "message": "；".join(cons_warns)[:1200],
                }
            )
        try:
            from modstore_server.workbench_api import _check_vibe_coding_capability

            vibe_checks = _check_vibe_coding_capability(_pack, wf_attach or {})
            mod_checks.extend(vibe_checks)
        except RECOVERABLE_ERRORS as vibe_exc:
            _facade().logger.warning("vibe-coding capability check failed: %s", vibe_exc)
            mod_checks.append(
                {
                    "id": "vibe_check",
                    "ok": False,
                    "message": f"vibe-coding 检查异常: {vibe_exc!s}",
                }
            )
    core_ok = validation_report.get("status") == "ok"
    emp_mod_sandbox = {
        "ok": core_ok and all((c.get("ok") for c in mod_checks if c.get("id") != "vibe_check")),
        "checks": mod_checks,
        "validation_report": validation_report,
        "note": "员工包四阶段校验（manifest / Python / 一致性 / xcemp）",
    }
    if xv.get("escalate_to_human"):
        from modstore_server.craft_failure_signals import emit_craft_step_failure

        _xv_errs = xv.get("errors") if isinstance(xv.get("errors"), list) else []
        _xv_err = str(
            xv.get("timeout_log") or (_xv_errs[0] if _xv_errs else "xcemp validate 超时")
        )[:500]
        emit_craft_step_failure(
            step_id="mod_sandbox",
            error=_xv_err,
            employee_id="code-validator",
            user_id=int(user_id or 0),
            extra={
                "escalate_to_human": True,
                "package_hash": xv.get("package_hash"),
                "validation_report": validation_report,
            },
        )
    _all_pass = emp_mod_sandbox["ok"]
    _vibe_gaps = [c for c in mod_checks if not c.get("ok") and "vibe" in str(c.get("id") or "")]
    mod_sb_msg = str(validation_report.get("summary") or "")
    if _all_pass:
        mod_sb_msg = mod_sb_msg or "包体四阶段校验通过"
    elif _vibe_gaps and core_ok:
        mod_sb_msg = (
            mod_sb_msg
            + "；vibe-coding 能力存在缺口："
            + "；".join((c.get("message", "") for c in _vibe_gaps))
        )[:480]
    elif not mod_sb_msg:
        mod_sb_msg = "包体校验未通过，见 validation_report"
    return {
        "emp_mod_sandbox": emp_mod_sandbox,
        "mod_sb_msg": mod_sb_msg,
        "report": validation_report,
    }
