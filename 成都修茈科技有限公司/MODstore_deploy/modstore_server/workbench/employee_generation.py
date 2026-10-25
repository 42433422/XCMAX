"""Employee generation for workbench delivery."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy.orm import Session

from modstore_server.employee_asset_pipeline import reconcile_employee_pack_manifest
from modstore_server.models import User
from modstore_server.word_extract_runtime import validate_word_extract_backend
from modstore_server.workbench.employee_state import EmployeeBuildState
from modstore_server.workbench.sessions import ProgressCallbacks, SessionStore

_LOG = logging.getLogger("modstore_server.workbench_api")


@dataclass(frozen=True)
class EmployeeGenerationPorts:
    sessions: SessionStore
    progress: ProgressCallbacks
    db: Session
    user: User
    craft_step: Callable[..., Awaitable[dict[str, Any] | None]]
    scaffold: Callable[..., Awaitable[dict[str, Any]]]


async def generate_employee(
    state: EmployeeBuildState, *, ports: EmployeeGenerationPorts
) -> bool:
    if state.should_skip("generate"):
        await ports.progress.set_step(
            state.session_id, "generate", "done", "已完成（重试复用）"
        )
    else:
        state.current_step = "generate"
        _gen_running_msg = (
            "正在解析上传资产并生成员工包"
            if state.use_assets
            else (
                "正在生成 LLM 驱动文档审核员工包"
                if state.needs_llm_reasoning and state.uploaded_docx
                else None
            )
        )
        await ports.progress.set_step(
            state.session_id, "generate", "running", _gen_running_msg
        )
        _plan_payload = dict(state.payload) if isinstance(state.payload, dict) else {}
        if isinstance(state.employee_plan, dict) and state.employee_plan:
            _plan_payload["employee_plan"] = state.employee_plan
        _scaffold_kw: dict[str, Any] = dict(
            session_id=state.session_id,
            brief=state.employee_brief,
            raw_files=state.employee_files,
            replace=state.replace,
            provider=state.provider,
            model=state.model,
            publish_to_catalog=False,
            force_llm_codegen=True,
            payload=_plan_payload or None,
        )
        if state.use_word_extract:
            from modstore_server.employee_asset_pipeline import (
                run_word_extract_employee_scaffold_async,
            )

            _gen_result = await ports.craft_step(
                "generate",
                db=ports.db,
                user=ports.user,
                session_id=state.session_id,
                brief=state.employee_brief,
                raw_files=state.employee_files,
                replace=state.replace,
                provider=state.provider,
                model=state.model,
                use_word_extract=True,
                payload=state.payload,
            )
            state.result = (
                _gen_result["res"]
                if _gen_result
                else await run_word_extract_employee_scaffold_async(
                    ports.db, ports.user, **_scaffold_kw
                )
            )
        elif state.use_assets:
            from modstore_server.employee_asset_pipeline import (
                run_asset_employee_scaffold_async,
            )

            _gen_result = await ports.craft_step(
                "generate",
                db=ports.db,
                user=ports.user,
                session_id=state.session_id,
                brief=state.employee_brief,
                raw_files=state.employee_files,
                replace=state.replace,
                provider=state.provider,
                model=state.model,
                payload=state.payload,
            )
            state.result = (
                _gen_result["res"]
                if _gen_result
                else await run_asset_employee_scaffold_async(
                    ports.db, ports.user, **_scaffold_kw
                )
            )
        elif state.needs_llm_reasoning and state.uploaded_docx:
            from modstore_server.employee_asset_pipeline import (
                run_asset_employee_scaffold_async,
            )

            _gen_result = await ports.craft_step(
                "generate",
                db=ports.db,
                user=ports.user,
                session_id=state.session_id,
                brief=state.employee_brief,
                raw_files=state.employee_files,
                replace=state.replace,
                provider=state.provider,
                model=state.model,
                payload=state.payload,
            )
            state.result = (
                _gen_result["res"]
                if _gen_result
                else await run_asset_employee_scaffold_async(
                    ports.db, ports.user, **_scaffold_kw
                )
            )
        else:
            state.result = await ports.scaffold(
                ports.db,
                ports.user,
                brief=state.employee_brief,
                replace=state.replace,
                provider=state.provider,
                model=state.model,
                publish_to_catalog=False,
            )
        if not state.result.get("ok"):
            warns = (
                cast(list[Any], state.result.get("validate_warnings"))
                if isinstance(state.result.get("validate_warnings"), list)
                else []
            )
            errs = (
                cast(list[Any], state.result.get("validate_errors"))
                if isinstance(state.result.get("validate_errors"), list)
                else []
            )
            if errs or not warns:
                await ports.progress.fail(
                    state.session_id,
                    "generate",
                    state.result.get("error") or "；".join(errs[:3]) or "生成失败",
                )
                return True
        if state.use_word_extract or state.use_assets:
            from modstore_server.vibecoding_convert_loop import is_llm_codegen_source

            _rt_gate = (
                cast(dict[str, Any], state.result.get("runtime_generation"))
                if isinstance(state.result.get("runtime_generation"), dict)
                else {}
            )
            _ds_gate = (
                cast(dict[str, Any], state.result.get("domain_smoke"))
                if isinstance(state.result.get("domain_smoke"), dict)
                else {}
            )
            _gc_gate = (
                cast(dict[str, Any], state.result.get("golden_comparison"))
                if isinstance(state.result.get("golden_comparison"), dict)
                else {}
            )
            if not is_llm_codegen_source(_rt_gate):
                await ports.progress.fail(
                    state.session_id,
                    "generate",
                    f"convert 须由 LLM 生成（当前 source={_rt_gate.get('source') or 'unknown'}）",
                )
                return True
            if _ds_gate.get("ok") is False:
                await ports.progress.fail(
                    state.session_id,
                    "generate",
                    f"领域冒烟未通过：{_ds_gate.get('error') or 'failed'}"[:1000],
                )
                return True
            if (
                _gc_gate
                and _gc_gate.get("golden_pack_id")
                and (not _gc_gate.get("passed"))
            ):
                await ports.progress.fail(
                    state.session_id,
                    "generate",
                    f"黄金对比未达标：parity={_gc_gate.get('parity_score')} diffs={len(_gc_gate.get('diff_items') or [])}"[
                        :1000
                    ],
                )
                return True
        _package_path = str(state.result.get("path") or "").strip()
        if not _package_path:
            await ports.progress.fail(
                state.session_id, "generate", "员工生成结果缺少包目录"
            )
            return True
        _gen_pack_dir = Path(_package_path)
        if state.use_word_extract and _gen_pack_dir.is_dir():
            reconcile_employee_pack_manifest(_gen_pack_dir, brief=state.employee_brief)
            _gx_errs, _ = validate_word_extract_backend(_gen_pack_dir)
            if _gx_errs:
                await ports.progress.fail(
                    state.session_id, "generate", "；".join(_gx_errs[:3])
                )
                return True
        asset_count = (
            len((state.result.get("asset_manifest") or {}).get("assets") or [])
            if isinstance(state.result.get("asset_manifest"), dict)
            else 0
        )
        if state.use_word_extract:
            _rt_meta = (
                cast(dict[str, Any], state.result.get("runtime_generation"))
                if isinstance(state.result.get("runtime_generation"), dict)
                else {}
            )
            _gc_meta = (
                cast(dict[str, Any], state.result.get("golden_comparison"))
                if isinstance(state.result.get("golden_comparison"), dict)
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
        elif state.use_assets:
            _gen_done_msg = f"已生成资产驱动员工包；资产 {asset_count} 个"
        elif state.needs_llm_reasoning and state.uploaded_docx:
            _gen_done_msg = "已生成 LLM 驱动文档审核员工包"
        else:
            _gen_done_msg = None
        await ports.progress.set_step(
            state.session_id, "generate", "done", _gen_done_msg
        )
    if state.should_skip("validate"):
        await ports.progress.set_step(
            state.session_id, "validate", "done", "已完成（重试复用）"
        )
    else:
        state.current_step = "validate"
        await ports.progress.set_step(state.session_id, "validate", "running")
        _val_result = await ports.craft_step(
            "validate",
            res=state.result,
            brief=state.employee_brief or state.routing_brief or state.brief,
            pack_dir=state.result.get("path"),
            user_id=state.user_id,
        )
        validate_warnings = (
            _val_result.get("validate_warnings")
            if _val_result and isinstance(_val_result.get("validate_warnings"), list)
            else (
                cast(list[Any], state.result.get("validate_warnings"))
                if isinstance(state.result.get("validate_warnings"), list)
                else []
            )
        )
        validate_errors = (
            _val_result.get("validate_errors")
            if _val_result and isinstance(_val_result.get("validate_errors"), list)
            else []
        )
        async with ports.sessions.lock:
            sess = ports.sessions.data.get(state.session_id)
            if sess:
                sess["validate_warnings"] = validate_warnings
                if validate_errors:
                    sess["validate_errors"] = validate_errors
                ports.sessions.persist(state.session_id)
        if validate_errors:
            msg = "；".join((str(x) for x in validate_errors[:5]))
            await ports.progress.set_step(
                state.session_id, "validate", "error", msg[:480]
            )
            await ports.progress.fail(state.session_id, "validate", msg[:1000])
            return True
        await ports.progress.set_step(
            state.session_id,
            "validate",
            "done",
            (
                "；".join((str(x) for x in validate_warnings[:5]))
                if validate_warnings
                else "manifest、Python 与包体校验通过"
            ),
        )
        state.pack_dir = Path(str(state.result.get("path") or ""))
        state.script_workflow = None
        state.script_attachment = {}
        state.script_result = {}
    return False
