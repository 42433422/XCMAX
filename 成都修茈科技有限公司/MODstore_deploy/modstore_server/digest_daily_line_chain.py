# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Phase A/B/C：四产线员工串联 + ProductionLine 子集 + installer/major 日 P5/P6/P9 派发。

Phase A（08:15）：P-S + P-App 补丁派发。
Phase B（08:25）：P-W 更新 + P-App 更新 + S-R（P-S/P-App 补丁已在 Phase A 完成）。
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any, Dict, List, Sequence, Tuple

from modstore_server.digest_daily_phase_chain import PHASE_A_LINES as PHASE_A_LINES
from modstore_server.digest_daily_phase_chain import PHASE_B_LINES_NO_APP as PHASE_B_LINES_NO_APP
from modstore_server.digest_daily_phase_chain import (
    PHASE_B_LINES_WITH_APP as PHASE_B_LINES_WITH_APP,
)
from modstore_server.digest_daily_phase_chain import _env_bool as _env_bool
from modstore_server.digest_daily_phase_chain import _merge_phase_block as _merge_phase_block
from modstore_server.digest_daily_phase_chain import (
    execute_phase_a_line_chain as execute_phase_a_line_chain,
)
from modstore_server.digest_daily_phase_chain import (
    execute_phase_b_line_chain as execute_phase_b_line_chain,
)
from modstore_server.digest_daily_phase_chain import (
    trigger_strategic_layer_dispatch as trigger_strategic_layer_dispatch,
)
from modstore_server.digest_daily_phase_chain import wait_for_phase_a as wait_for_phase_a
from modstore_server.digest_line_executor import (
    _load_digest_execute_context,
    _read_execute_meta,
    persist_line_execute_on_digest_record,
)
from modstore_server.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


INSTALLER_EMPLOYEE_CHAIN: Tuple[Tuple[str, str, str], ...] = (
    (
        "P9",
        "deploy-release-officer",
        "release_train 十日线代际：执行 P9 版本演进与代际快照（installer 日）。",
    ),
    (
        "P5",
        "deploy-release-officer",
        "installer 日全量发布：GitHub Release + 更新元数据 + canary→production 部署。",
    ),
    (
        "P6",
        "push-update-context-officer",
        "installer 日 OTA：electron-updater 元数据 + Ed25519 签名 + Mod 索引 + COS/官网 SKU。",
    ),
)

MAJOR_EXTRA_CHAIN: Tuple[Tuple[str, str, str], ...] = (
    (
        "P9M",
        "dbops-engineer",
        "major 日：数据库迁移与 schema 兼容性门禁（release_train 百日线）。",
    ),
    (
        "SKU",
        "push-update-context-officer",
        "major 日：全 SKU COS 同步 + electron-updater 元数据批量刷新。",
    ),
    (
        "ADM",
        "deploy-release-officer",
        "major 日：扩展 ADMIN/release 审批门 + 全量 promote 至 production。",
    ),
)

PIPELINE_STEPS_BY_KIND: Dict[str, Tuple[str, ...]] = {
    "daily": ("P3", "P7", "P8"),
    "installer": ("P3", "P4", "P5", "P6", "P7", "P8", "P9"),
    "major": ("P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10"),
}


def _ci_correlation(kind: str, step_ids: Sequence[str]) -> Dict[str, Any]:
    """P1-7 · Phase C 窄 CI 审计标识。

    优先采用 GitHub Actions 注入的 run 标识（日更 PR 触发的窄 CI job）；
    CVM 本地编排无 Actions 上下文时回退到本地 correlation id，确保审计可追溯。
    daily 仅跑 P3/P7/P8 窄子集（非全量 P3–P9），narrow=True。
    """
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    job = os.environ.get("GITHUB_JOB", "").strip()
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if run_id:
        source = "github_actions"
        url = f"{server}/{repo}/actions/runs/{run_id}" if repo else ""
    else:
        source = "cvm_local"
        run_id = f"local-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        url = ""
    return {
        "ci_job_id": run_id,
        "ci_job_name": job or "release_train_phase_c",
        "ci_source": source,
        "ci_run_url": url,
        "narrow_ci": kind == "daily",
        "pipeline_subset": list(step_ids),
    }


def _build_chain_context(record_id: int, release_train: str, release_kind: str) -> Dict[str, Any]:
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = str(repo_root())
    except RECOVERABLE_ERRORS:
        root = ""
    ctx = _load_digest_execute_context(int(record_id)) or {}
    return {
        "digest_record_id": int(record_id),
        "release_train": release_train,
        "release_kind": release_kind,
        "project_root": root,
        "digest_subject": ctx.get("subject") or "",
        "base_version": ctx.get("base_version") or "",
    }


def _dispatch_employee_chain(
    *,
    record_id: int,
    release_train: str,
    release_kind: str,
    steps: Sequence[Tuple[str, str, str]],
    shadow: bool,
    block_key: str,
    phase_label: str,
) -> Dict[str, Any]:
    context = _build_chain_context(record_id, release_train, release_kind)
    started_at = datetime.now(UTC).isoformat()
    step_results: List[Dict[str, Any]] = []
    all_ok = True

    for step_id, employee_id, brief in steps:
        full_brief = f"[{step_id} · release_train {release_train} · {release_kind}]\n{brief}"
        if shadow:
            step_results.append(
                {
                    "ok": True,
                    "shadow": True,
                    "step": step_id,
                    "employee_id": employee_id,
                    "task_brief": full_brief,
                }
            )
            continue
        try:
            from modstore_server.employee_orchestrator import plan_and_dispatch

            out = plan_and_dispatch(
                full_brief,
                context,
                target_employee_id=employee_id,
                created_by_user_id=0,
                include_dependencies=True,
                allow_high_risk_real_run=_env_bool("MODSTORE_INSTALLER_PUSH_ALLOW_HIGH_RISK", "0"),
            )
            step_ok = bool(out.get("ok"))
            step_results.append(
                {
                    "ok": step_ok,
                    "step": step_id,
                    "employee_id": employee_id,
                    "result": out,
                }
            )
            if not step_ok:
                all_ok = False
        except RECOVERABLE_ERRORS as exc:
            logger.exception(
                "%s chain step=%s employee=%s failed", phase_label, step_id, employee_id
            )
            all_ok = False
            step_results.append(
                {
                    "ok": False,
                    "step": step_id,
                    "employee_id": employee_id,
                    "error": str(exc),
                }
            )

    completed_at = datetime.now(UTC).isoformat()
    block = {
        "ok": all_ok,
        "phase": phase_label,
        "shadow": shadow,
        "record_id": int(record_id),
        "release_train": release_train,
        "release_kind": release_kind,
        "employee_chain": [s["employee_id"] for s in step_results],
        "steps": step_results,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    meta = _read_execute_meta(int(record_id))
    persist_line_execute_on_digest_record(
        int(record_id), _merge_phase_block(meta, block_key, block)
    )
    return block


def execute_installer_employee_chain(
    record_id: int,
    *,
    release_train: str,
    release_kind: str,
    shadow: bool = False,
) -> Dict[str, Any]:
    """installer/major 日：P9→P5→P6 员工串联（major 前置 MAJOR_EXTRA_CHAIN）。"""
    if not _env_bool("MODSTORE_INSTALLER_PUSH_ENABLED", "1"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "MODSTORE_INSTALLER_PUSH_ENABLED=0",
        }

    kind = (release_kind or "installer").strip().lower()
    if kind not in ("installer", "major"):
        return {
            "ok": True,
            "skipped": True,
            "reason": f"release_kind={kind} not installer/major",
        }

    steps: List[Tuple[str, str, str]] = list(INSTALLER_EMPLOYEE_CHAIN)
    if kind == "major":
        steps = list(MAJOR_EXTRA_CHAIN) + steps

    block = _dispatch_employee_chain(
        record_id=int(record_id),
        release_train=release_train,
        release_kind=kind,
        steps=steps,
        shadow=shadow,
        block_key="phase_c",
        phase_label="C",
    )
    logger.info(
        "phase_c installer chain record_id=%s kind=%s shadow=%s ok=%s",
        record_id,
        kind,
        shadow,
        block.get("ok"),
    )
    # 真实（非 shadow）installer/major 日：回写下载版本 SSOT last_push + 刷新官网公开清单，
    # 让「P5 构建 → P6 推 COS」在数据面真正落到「官网下载」这一环（解决历史断点）。
    if not shadow and block.get("ok"):
        try:
            # FASTGATE：推 COS / 回写下载 SSOT 前的强制门禁（staging + /api/health + 市场下载页）。
            # 不过则阻断推送、不写 last_push，标记回滚待审（对齐时间轨 FASTGATE 节点）。
            from modstore_server.installer_fastgate import verify_installer_fastgate

            gate = verify_installer_fastgate(
                release_train=str(release_train or ""), release_kind=kind
            )
            block["fastgate"] = gate
            if not gate.get("ok"):
                logger.warning("phase_c installer FASTGATE blocked push: %s", gate.get("reason"))
                block["download_release"] = {
                    "ok": False,
                    "blocked_by": "fastgate",
                    "reason": gate.get("reason"),
                }
                # 即时门禁不过 → 自动回滚闭环（回退上一稳定版 + 告警 + 落 OpsStagedChange 复盘待审）
                try:
                    from modstore_server.auto_rollback import (
                        auto_rollback_on_gate_failure,
                    )

                    block["rollback"] = auto_rollback_on_gate_failure(
                        gate="FASTGATE",
                        release_train=str(release_train or ""),
                        release_kind=kind,
                        reason=str(gate.get("reason") or "fastgate failed"),
                    )
                except BOUNDARY_ERRORS:  # noqa: BLE001
                    logger.exception("phase_c installer FASTGATE auto-rollback failed")
                return block

            from modstore_server.download_release import record_installer_push

            cos_uploaded = _env_bool("MODSTORE_INSTALLER_COS_UPLOADED", "0")
            push = record_installer_push(
                release_train=str(release_train or ""),
                release_kind=kind,
                cos_uploaded=cos_uploaded,
                actor="installer-employee-chain",
            )
            block["download_release"] = push
        except BOUNDARY_ERRORS:  # noqa: BLE001
            logger.exception("phase_c installer chain: record_installer_push failed")
    return block


def execute_major_employee_chain(
    record_id: int,
    *,
    release_train: str,
    shadow: bool = False,
) -> Dict[str, Any]:
    """major 百日线：MAJOR_EXTRA + installer 链（持久化 major_plan）。"""
    if not _env_bool("MODSTORE_MAJOR_PUSH_ENABLED", "1"):
        return {"ok": True, "skipped": True, "reason": "MODSTORE_MAJOR_PUSH_ENABLED=0"}
    return execute_installer_employee_chain(
        int(record_id),
        release_train=release_train,
        release_kind="major",
        shadow=shadow,
    )


def execute_production_pipeline_chain(
    record_id: int,
    *,
    release_train: str,
    release_kind: str,
    shadow: bool = False,
) -> Dict[str, Any]:
    """ProductionLineOrchestrator 子集：daily=P3/P7/P8 · installer/major=含 P5/P6。"""
    if not _env_bool("MODSTORE_RELEASE_TRAIN_PIPELINE_ENABLED", "1"):
        return {
            "ok": True,
            "skipped": True,
            "reason": "MODSTORE_RELEASE_TRAIN_PIPELINE_ENABLED=0",
        }

    kind = (release_kind or "daily").strip().lower()
    step_ids = PIPELINE_STEPS_BY_KIND.get(kind) or PIPELINE_STEPS_BY_KIND["daily"]
    ci_job = _ci_correlation(kind, step_ids)
    started_at = datetime.now(UTC).isoformat()

    if shadow:
        block = {
            "ok": True,
            "shadow": True,
            "phase": "C-pipeline",
            "record_id": int(record_id),
            "release_train": release_train,
            "release_kind": kind,
            "planned_steps": list(step_ids),
            "ci_job": ci_job,
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        meta = _read_execute_meta(int(record_id))
        persist_line_execute_on_digest_record(
            int(record_id), _merge_phase_block(meta, "phase_c_pipeline", block)
        )
        return block

    context = _build_chain_context(record_id, release_train, kind)
    context["release_train_subset"] = True
    try:
        import modstore_server.production_line_orchestrator as plo

        plo._orchestrator = None
        from modstore_server.runtime_async import run_coro_sync

        out = run_coro_sync(_run_pipeline_with_optional_auto_approve(step_ids, context))
    except RECOVERABLE_ERRORS as exc:
        logger.exception("production pipeline chain failed record_id=%s", record_id)
        out = {"ok": False, "error": str(exc)}

    block = {
        **out,
        "phase": "C-pipeline",
        "record_id": int(record_id),
        "release_train": release_train,
        "release_kind": kind,
        "step_ids": list(step_ids),
        "ci_job": ci_job,
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
    }

    # 灰度发布（CANARY）/推送阶段校验不过 → 自动回滚闭环（对齐时间轨 CANARY→ROLLBACK）。
    # 仅 installer/major 日的 P5（含 canary 策略）/P6 失败触发，避免 P3 等测试失败误触发回滚。
    if not block.get("ok") and kind in ("installer", "major"):
        failed_step = str(out.get("failed_at_step") or "")
        if failed_step in ("P5", "P6"):
            try:
                from modstore_server.auto_rollback import auto_rollback_on_gate_failure

                block["rollback"] = auto_rollback_on_gate_failure(
                    gate="CANARY",
                    release_train=str(release_train or ""),
                    release_kind=kind,
                    reason=str(out.get("error") or f"pipeline failed at {failed_step}"),
                    failed_step=failed_step,
                )
            except BOUNDARY_ERRORS:  # noqa: BLE001
                logger.exception("production pipeline auto-rollback failed record_id=%s", record_id)

    meta = _read_execute_meta(int(record_id))
    persist_line_execute_on_digest_record(
        int(record_id), _merge_phase_block(meta, "phase_c_pipeline", block)
    )
    return block


async def _run_pipeline_with_optional_auto_approve(
    step_ids: Sequence[str],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    from modstore_server.production_line_orchestrator import (
        approve_production_line_step,
        get_production_line_orchestrator,
    )

    auto = _env_bool("MODSTORE_RELEASE_TRAIN_AUTO_APPROVE_PIPELINE", "0")
    orch = get_production_line_orchestrator()
    ids = list(step_ids)
    executed: List[str] = []
    ctx = dict(context)

    while ids:
        out = await orch.run_pipeline_steps(ids, context=ctx)
        executed.extend(out.get("executed_steps") or [])
        if not out.get("paused"):
            out["executed_steps"] = executed
            return out
        paused = str(out.get("paused_at_step") or "")
        if not auto or not paused:
            out["executed_steps"] = executed
            return out
        appr = await approve_production_line_step(paused, admin_user_id=0)
        from modstore_server.production_line_orchestrator import StepStatus

        if appr.status == StepStatus.FAILED:
            cur = orch._step_results.get(paused) or None
            if cur and cur.status == StepStatus.COMPLETED:
                pass
            else:
                return {
                    "ok": False,
                    "error": appr.error or "auto approve failed",
                    "paused_at_step": paused,
                    "executed_steps": executed,
                }
            return {
                "ok": False,
                "error": "auto approve failed",
                "paused_at_step": paused,
                "executed_steps": executed,
            }
        try:
            idx = ids.index(paused)
            ids = ids[idx + 1 :]
        except ValueError:
            break
        if isinstance(getattr(appr, "data", None), dict):
            ctx = appr.data
        if not ids:
            return {
                "ok": True,
                "paused": False,
                "executed_steps": executed,
                "auto_approved": True,
            }

    return {"ok": True, "executed_steps": executed, "auto_approved": auto}
