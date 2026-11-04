"""Employee registration for workbench delivery."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Dict, cast

from sqlalchemy.orm import Session

from modstore_server.employee_ai_scaffold import normalize_editor_manifest_for_registry
from modstore_server.employee_asset_pipeline import reconcile_employee_pack_manifest
from modstore_server.models import User
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.word_extract_runtime import validate_word_extract_backend
from modstore_server.workbench.employee_state import EmployeeBuildState
from modstore_server.workbench.sessions import ProgressCallbacks

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class EmployeeRegistrationPorts:
    progress: ProgressCallbacks
    db: Session
    user: User
    craft_step: Callable[..., Awaitable[dict[str, Any] | None]]
    refresh_catalog: Callable[..., dict[str, Any]]
    catalog_registered: Callable[..., bool]
    sandbox: Callable[..., dict[str, Any]]
    record_sandbox: Callable[..., Any]


async def register_and_verify_workflow(
    state: EmployeeBuildState, *, ports: EmployeeRegistrationPorts
) -> bool:
    if state.should_skip("register_pack"):
        await ports.progress.set_step(
            state.session_id, "register_pack", "done", "已完成（重试复用）"
        )
    elif state.target == "pack_plus_workflow" and (
        not (
            isinstance(state.workflow_attachment, dict)
            and (
                state.workflow_attachment.get("automation_complete")
                or (
                    state.workflow_attachment.get("ok")
                    and state.workflow_attachment.get("workflow_id")
                )
            )
        )
    ):
        _reg_upstream = "workflow-automator 未完成（缺少 automation_complete / workflow_id），已拒收登记并退回上游"
        await ports.progress.set_step(
            state.session_id, "register_pack", "error", _reg_upstream[:480]
        )
        await ports.progress.fail(state.session_id, "register_pack", _reg_upstream[:1000])
        return True
    else:
        state.current_step = "register_pack"
        await ports.progress.set_step(
            state.session_id, "register_pack", "running", "正在保存员工包到本地库…"
        )
        state.registration_missing = False
        try:
            _emp_mf = state.result.get("manifest") if isinstance(state.result, dict) else None
            _emp_pack_id = str(state.result.get("id") or (_emp_mf or {}).get("id") or "").strip()
            if _emp_pack_id and state.pack_dir.is_dir():
                reconcile_employee_pack_manifest(state.pack_dir, brief=state.employee_brief)
                _raw_mf = json.loads((state.pack_dir / "manifest.json").read_text(encoding="utf-8"))
                _aligned_mf, _align_errs = normalize_editor_manifest_for_registry(
                    _raw_mf, _emp_pack_id
                )
                (state.pack_dir / "manifest.json").write_text(
                    json.dumps(_aligned_mf, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                reconcile_employee_pack_manifest(state.pack_dir, brief=state.employee_brief)
                if state.use_word_extract:
                    _reg_wx_errs, _ = validate_word_extract_backend(state.pack_dir)
                    if _reg_wx_errs:
                        _reg_fail = "登记前 Word runtime 未就绪：" + "；".join(_reg_wx_errs[:3])
                        await ports.progress.set_step(
                            state.session_id, "register_pack", "error", _reg_fail[:480]
                        )
                        await ports.progress.fail(
                            state.session_id, "register_pack", _reg_fail[:1000]
                        )
                        return True
                try:
                    state.saved_package = ports.refresh_catalog(
                        ports.db, ports.user, state.pack_dir
                    )
                    state.published_to_catalog = True
                    _reg_msg = (
                        f"员工包已保存并登记至目录（{_emp_pack_id}）；可在「员工制作」左侧列表查看"
                    )
                except RECOVERABLE_ERRORS as _cat_exc:
                    _LOG.warning(
                        "register_pack catalog sync failed error_type=%s",
                        type(_cat_exc).__name__,
                    )
                    _reg_msg = f"目录登记失败：{_cat_exc!s}"[:480]
                    await ports.progress.set_step(
                        state.session_id, "register_pack", "error", _reg_msg
                    )
                    await ports.progress.fail(state.session_id, "register_pack", _reg_msg[:1000])
                    return True
                await ports.progress.set_step(
                    state.session_id, "register_pack", "done", _reg_msg[:480]
                )
            else:
                state.registration_missing = True
                msg = "未找到有效包 ID 或包目录，员工包未保存——请确认 manifest.id"
                await ports.progress.set_step(state.session_id, "register_pack", "error", msg[:480])
                await ports.progress.fail(state.session_id, "register_pack", msg[:1000])
                return True
        except RECOVERABLE_ERRORS as _reg_exc:
            _LOG.warning(
                "register_pack failed for employee error_type=%s",
                type(_reg_exc).__name__,
            )
            state.registration_missing = True
            msg = f"保存异常: {_reg_exc!s}"
            await ports.progress.set_step(state.session_id, "register_pack", "error", msg[:480])
            await ports.progress.fail(state.session_id, "register_pack", msg[:1000])
            return True
    if state.should_skip("workflow_sandbox"):
        await ports.progress.set_step(
            state.session_id, "workflow_sandbox", "done", "已完成（重试复用）"
        )
    else:
        state.current_step = "workflow_sandbox"
        await ports.progress.set_step(
            state.session_id,
            "workflow_sandbox",
            "running",
            "工作流结构校验（validate_only）",
        )
        wid_raw = (
            state.workflow_attachment.get("workflow_id")
            if isinstance(state.workflow_attachment, dict)
            else None
        )
        try:
            wid_int = int(wid_raw) if wid_raw is not None else 0
        except (TypeError, ValueError):
            wid_int = 0
        if state.target == "pack_plus_workflow" and wid_int <= 0:
            from modstore_server.craft_failure_signals import (
                invalid_workflow_sandbox_report,
            )

            _wf_invalid_msg = "输入 workflow_id 无效：pack-registrar / workflow-automator 须先创建画布工作流并写入 wf_attach.workflow_id"
            report = invalid_workflow_sandbox_report(wid_raw)
            state.workflow_sandbox = {
                "ok": False,
                "skipped": False,
                "workflow_id": wid_raw,
                "reports": [report],
                "business_tested": False,
                "summary": report.get("summary") or "输入 workflow_id 无效",
            }
            await ports.progress.set_step(
                state.session_id, "workflow_sandbox", "error", _wf_invalid_msg[:480]
            )
            await ports.progress.fail(state.session_id, "workflow_sandbox", _wf_invalid_msg[:1000])
            return True
        if state.target == "pack_plus_workflow" and wid_int > 0:
            state.workflow_id = wid_int
            _ws_result = await ports.craft_step(
                "workflow_sandbox",
                workflow_id=state.workflow_id,
                brief=state.brief or "测试任务",
                user_id=ports.user.id,
                db=ports.db,
            )
            if _ws_result and isinstance(_ws_result.get("report"), dict):
                report = _ws_result["report"]
            elif _ws_result is None:
                report = ports.sandbox(
                    state.workflow_id,
                    {},
                    mock_employees=True,
                    validate_only=True,
                    user_id=ports.user.id,
                )
            else:
                report = (
                    cast(dict[str, Any], _ws_result.get("report"))
                    if isinstance(_ws_result.get("report"), dict)
                    else ports.sandbox(
                        state.workflow_id,
                        {},
                        mock_employees=True,
                        validate_only=True,
                        user_id=ports.user.id,
                    )
                )
            ports.record_sandbox(
                ports.db,
                workflow_id=int(state.workflow_id),
                user_id=ports.user.id,
                report=report,
                validate_only=True,
                mock_employees=True,
            )
            state.workflow_sandbox = {
                "ok": bool(report.get("ok")),
                "skipped": False,
                "workflow_id": int(state.workflow_id),
                "reports": [report],
                "business_tested": False,
                "note": "仅验证了工作流图结构完整性，未执行真实员工业务逻辑",
            }
            if report.get("ok"):
                await ports.progress.set_step(
                    state.session_id,
                    "workflow_sandbox",
                    "running",
                    "结构校验通过，正在执行真实员工调用验证…",
                )
                _biz_pack_id = str(
                    state.result.get("id")
                    or (
                        state.result.get("manifest") or {}
                        if isinstance(state.result.get("manifest"), dict)
                        else {}
                    ).get("id")
                    or state.pack_dir.name
                ).strip()
                if not ports.catalog_registered(ports.db, _biz_pack_id):
                    try:
                        ports.refresh_catalog(ports.db, ports.user, state.pack_dir)
                        state.published_to_catalog = True
                    except RECOVERABLE_ERRORS as _cat_retry_exc:
                        _LOG.warning(
                            "workflow_sandbox catalog retry failed error_type=%s",
                            type(_cat_retry_exc).__name__,
                        )
                if not ports.catalog_registered(ports.db, _biz_pack_id):
                    state.workflow_business_ok = False
                    _wf_sb_msg = (
                        f"结构校验通过 ✅，真实调用验证失败：员工包未登记（{_biz_pack_id}）"
                    )
                    if state.pipeline_label in (
                        "word_full_extract",
                        "txt_full_read",
                        "txt_generate",
                    ):
                        await ports.progress.set_step(
                            state.session_id,
                            "workflow_sandbox",
                            "error",
                            _wf_sb_msg[:480],
                        )
                        await ports.progress.fail(
                            state.session_id, "workflow_sandbox", _wf_sb_msg[:1000]
                        )
                        return True
                else:
                    try:
                        import base64 as _b64mod

                        from modstore_server.txt_extract_runtime import (
                            minimal_txt_fixture_bytes,
                        )
                        from modstore_server.word_extract_runtime import (
                            minimal_docx_fixture_b64,
                        )

                        _biz_input: Dict[str, Any] = {
                            "task": state.routing_brief or state.brief or "测试任务"
                        }
                        if state.pipeline_label == "word_full_extract":
                            _biz_input["files"] = [
                                {
                                    "filename": "smoke.docx",
                                    "content_base64": minimal_docx_fixture_b64(),
                                }
                            ]
                        elif state.pipeline_label in ("txt_full_read", "txt_generate"):
                            _biz_input["files"] = [
                                {
                                    "filename": "smoke.txt",
                                    "content_base64": _b64mod.b64encode(
                                        minimal_txt_fixture_bytes()
                                    ).decode("ascii"),
                                }
                            ]
                        biz_report = ports.sandbox(
                            int(state.workflow_id),
                            _biz_input,
                            mock_employees=False,
                            validate_only=False,
                            user_id=ports.user.id,
                        )
                        ports.record_sandbox(
                            ports.db,
                            workflow_id=int(state.workflow_id),
                            user_id=ports.user.id,
                            report=biz_report,
                            validate_only=False,
                            mock_employees=False,
                        )
                        state.workflow_sandbox["reports"].append(biz_report)
                        state.workflow_sandbox["business_tested"] = True
                        if biz_report.get("ok"):
                            state.workflow_sandbox["ok"] = True
                            state.workflow_business_ok = True
                            _wf_sb_msg = "结构校验通过 ✅ + 真实员工调用验证通过 ✅"
                        else:
                            state.workflow_business_ok = False
                            _biz_errs = biz_report.get("errors") or []
                            _biz_warns = biz_report.get("warnings") or []
                            _wf_sb_msg = f"结构校验通过 ✅，真实调用验证有提示（{len(_biz_errs)} 错误，{len(_biz_warns)} 警告）"
                            if _biz_errs:
                                _wf_sb_msg += "；" + "；".join(
                                    (str(e)[:100] for e in _biz_errs[:2])
                                )
                            if state.pipeline_label in (
                                "word_full_extract",
                                "txt_full_read",
                                "txt_generate",
                            ):
                                await ports.progress.set_step(
                                    state.session_id,
                                    "workflow_sandbox",
                                    "error",
                                    _wf_sb_msg[:480],
                                )
                                await ports.progress.fail(
                                    state.session_id,
                                    "workflow_sandbox",
                                    _wf_sb_msg[:1000],
                                )
                                return True
                    except RECOVERABLE_ERRORS as _biz_exc:
                        state.workflow_sandbox["business_tested"] = True
                        state.workflow_business_ok = False
                        _wf_sb_msg = f"结构校验通过 ✅，真实调用验证异常：{_biz_exc!s}"[:300]
                        if state.pipeline_label in (
                            "word_full_extract",
                            "txt_full_read",
                            "txt_generate",
                        ):
                            await ports.progress.set_step(
                                state.session_id,
                                "workflow_sandbox",
                                "error",
                                _wf_sb_msg[:480],
                            )
                            await ports.progress.fail(
                                state.session_id, "workflow_sandbox", _wf_sb_msg[:1000]
                            )
                            return True
            else:
                _wf_sb_msg = "结构校验有提示，请进画布查看"
            await ports.progress.set_step(state.session_id, "workflow_sandbox", "done", _wf_sb_msg)
        else:
            wf_skip_msg = "已跳过结构校验：未创建画布工作流或模式为仅员工包。如需工作流结构校验，请选择 pack_plus_workflow 模式。"
            state.workflow_sandbox = {
                "ok": True,
                "skipped": True,
                "reason": wf_skip_msg,
                "reports": [],
                "business_tested": False,
            }
            await ports.progress.set_step(
                state.session_id, "workflow_sandbox", "skipped", wf_skip_msg[:520]
            )
    return False
