"""Employee runtime checks for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, List

from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.workbench.employee_state import EmployeeBuildState
from modstore_server.workbench.sessions import ProgressCallbacks

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class EmployeeRuntimePorts:
    progress: ProgressCallbacks
    craft_step: Callable[..., Awaitable[dict[str, Any] | None]]
    vibe_checks: Callable[..., list[dict[str, Any]]]
    compile_warnings: Callable[..., list[str]]
    consistency_warnings: Callable[..., list[str]]
    manifest: Callable[..., tuple[dict[str, Any] | None, str | None]]


async def check_employee_runtime(state: EmployeeBuildState, *, ports: EmployeeRuntimePorts) -> bool:
    if state.should_skip("mod_sandbox"):
        await ports.progress.set_step(state.session_id, "mod_sandbox", "done", "已完成（重试复用）")
    else:
        state.current_step = "mod_sandbox"
        await ports.progress.set_step(
            state.session_id, "mod_sandbox", "running", "正在校验包体（manifest / Python）"
        )
        _msb_result = await ports.craft_step(
            "mod_sandbox",
            pack_dir=state.pack_dir,
            wf_attach=state.workflow_attachment,
            user_id=state.user_id,
        )
        if _msb_result:
            state.package_sandbox = _msb_result["emp_mod_sandbox"]
            mod_sb_msg = _msb_result["mod_sb_msg"]
            mod_checks = state.package_sandbox.get("checks", [])
        else:
            mod_checks = []
            if state.pack_dir.is_dir():
                _mf, mf_err = ports.manifest(state.pack_dir)
                mod_checks.append(
                    {"id": "manifest", "ok": mf_err is None, "message": mf_err or "manifest 可读取"}
                )
                py_warns = ports.compile_warnings(state.pack_dir)
                mod_checks.append(
                    {
                        "id": "python_compile",
                        "ok": not py_warns,
                        "message": (
                            "；".join(py_warns) if py_warns else "未发现需编译的 Python 或检查通过"
                        ),
                    }
                )
                cons_warns = ports.consistency_warnings(state.pack_dir)
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
                vibe_checks = ports.vibe_checks(state.pack_dir, state.workflow_attachment)
                mod_checks.extend(vibe_checks)
            else:
                mod_checks.append(
                    {"id": "manifest", "ok": False, "message": f"包目录无效: {state.pack_dir}"}
                )
            state.package_sandbox = {
                "ok": all((c.get("ok") for c in mod_checks)) if mod_checks else False,
                "checks": mod_checks,
                "note": "员工包轻量校验（含 backend/blueprints 运行时与 vibe-coding 能力检查）",
            }
            _all_pass = state.package_sandbox["ok"]
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
            (c for c in mod_checks if str(c.get("id") or "") == "vibe_system_prompt_quality"), None
        )
        if _prompt_chk is not None and (not _prompt_chk.get("ok")):
            msg = str(_prompt_chk.get("message") or "backend/employees/*.py 缺少 SYSTEM_PROMPT")
            await ports.progress.set_step(state.session_id, "mod_sandbox", "error", msg[:480])
            await ports.progress.fail(state.session_id, "mod_sandbox", msg[:2000])
            return True
        _runtime_chk_id = {
            "word_full_extract": "word_extract_runtime",
            "txt_full_read": "txt_read_runtime",
            "txt_generate": "txt_generate_runtime",
        }.get(state.pipeline_label, "")
        _wx_runtime_chk = (
            next((c for c in mod_checks if str(c.get("id") or "") == _runtime_chk_id), None)
            if _runtime_chk_id
            else None
        )
        if (
            state.pipeline_label in ("word_full_extract", "txt_full_read", "txt_generate")
            and _wx_runtime_chk is not None
            and (not _wx_runtime_chk.get("ok"))
        ):
            msg = str(
                _wx_runtime_chk.get("message") or f"{state.pipeline_label} runtime 校验未通过"
            )
            await ports.progress.set_step(state.session_id, "mod_sandbox", "error", msg[:480])
            await ports.progress.fail(state.session_id, "mod_sandbox", msg[:1000])
            return True
        await ports.progress.set_step(state.session_id, "mod_sandbox", "done", mod_sb_msg[:480])
    if state.should_skip("standalone_smoke"):
        await ports.progress.set_step(
            state.session_id, "standalone_smoke", "done", "已完成（重试复用）"
        )
    else:
        state.current_step = "standalone_smoke"
        await ports.progress.set_step(
            state.session_id,
            "standalone_smoke",
            "running",
            "正在生成独立包并验证 python xxx.xcemp validate …",
        )
        _ss_result = await ports.craft_step(
            "standalone_smoke", res=state.result, pack_dir=state.pack_dir, user_id=state.user_id
        )
        if _ss_result:
            state.standalone_smoke_ok = _ss_result["standalone_smoke_ok"]
            _standalone_smoke_msg = _ss_result["standalone_smoke_msg"]
            _standalone_smoke_skipped = _ss_result.get("standalone_smoke_skipped", False)
        else:
            state.standalone_smoke_ok = False
            _standalone_smoke_skipped = False
            _standalone_smoke_msg = "跳过（未能获取包字节）"
        _standalone_smoke_status = (
            "skipped"
            if _standalone_smoke_skipped
            else "error" if not state.standalone_smoke_ok else "done"
        )
        if _standalone_smoke_status == "error" and state.pipeline_label not in (
            "word_full_extract",
            "txt_full_read",
            "txt_generate",
        ):
            _standalone_smoke_status = "skipped"
            _standalone_smoke_msg = (
                f"⚠️ 独立包自检未通过，已跳过继续后续步骤：{_standalone_smoke_msg}"
            )
        elif _standalone_smoke_status == "error":
            await ports.progress.set_step(
                state.session_id, "standalone_smoke", "error", _standalone_smoke_msg[:480]
            )
            await ports.progress.fail(
                state.session_id, "standalone_smoke", _standalone_smoke_msg[:1000]
            )
            return True
        await ports.progress.set_step(
            state.session_id,
            "standalone_smoke",
            _standalone_smoke_status,
            _standalone_smoke_msg[:480],
        )
    if state.should_skip("host_check"):
        await ports.progress.set_step(state.session_id, "host_check", "done", "已完成（重试复用）")
    else:
        state.current_step = "host_check"
        state.host_probe = {"skipped": True}
        await ports.progress.set_step(
            state.session_id, "host_check", "running", "探测宿主 /api/mods/"
        )
        _hc_result = await ports.craft_step(
            "host_check", fhd_base=state.fhd_base or "", user_id=state.user_id
        )
        if _hc_result:
            state.host_probe = _hc_result["host_probe"]
            host_check_msg = _hc_result["host_check_msg"]
            if state.host_probe.get("skipped"):
                await ports.progress.set_step(
                    state.session_id, "host_check", "skipped", host_check_msg[:480]
                )
            elif state.host_probe.get("ok"):
                await ports.progress.set_step(
                    state.session_id, "host_check", "done", host_check_msg[:480]
                )
            else:
                await ports.progress.set_step(
                    state.session_id, "host_check", "done", host_check_msg[:480]
                )
        elif state.fhd_base:
            try:
                from modstore_server.infrastructure.http_clients import get_external_client

                base = state.fhd_base.rstrip("/")
                host_warnings: List[str] = []
                client = get_external_client()
                r = await client.get(f"{base}/api/mods/", timeout=10.0)
                state.host_probe = {
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
                                state.host_probe["host_min_mod_sdk_version"] = str(
                                    vj.get("min_mod_sdk_version") or ""
                                )
                        except RECOVERABLE_ERRORS:
                            pass
                except RECOVERABLE_ERRORS:
                    pass
                msg = (
                    f"HTTP {r.status_code}"
                    if state.host_probe.get("ok")
                    else f"HTTP {r.status_code}（异常）"
                )
                if host_warnings:
                    msg += "；" + "；".join(host_warnings[:3])[:400]
                    state.host_probe["warnings"] = host_warnings
                await ports.progress.set_step(state.session_id, "host_check", "done", msg[:480])
            except RECOVERABLE_ERRORS as e:
                state.host_probe = {"skipped": False, "ok": False, "error": str(e)[:300]}
                await ports.progress.set_step(
                    state.session_id, "host_check", "done", f"探测失败: {e!s}"[:300]
                )
        else:
            _host_skip = (
                "文件型 direct_python：本地转换无需宿主；未配置 fhd_base_url 已跳过"
                if state.pipeline_label in ("word_full_extract", "txt_full_read", "txt_generate")
                else "未配置 fhd_base_url，已跳过；如需部署到宿主，请在环境变量或配置中设置 FHD_BASE_URL 后重新运行连通性检查"
            )
            await ports.progress.set_step(state.session_id, "host_check", "skipped", _host_skip)
    return False
