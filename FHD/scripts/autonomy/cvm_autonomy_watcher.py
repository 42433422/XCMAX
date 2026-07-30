"""cvm-autonomy-watcher：服务器端自治 watcher 主程序（Phase 2）。

职责（与桌面端 controller.ts 对称）：
  1. collect_truth(adapter)：调用 adapter.collect_truth()
  2. **unfreeze 优先检查**：每次 tick 在执行 plan 前优先检查是否有过期 .frozen
     需解除（hold_ttl 已过 + health 通过），避免 frozen marker 无限阻塞 cron
  3. derive_signals(truth)：从 truth 派生信号（health_down / disk_full /
     manifest_drift / compose_unhealthy）
  4. run_policies(signals, policies)：调用匹配的 policy.plan()
  5. execute_plan(adapter, plan, truth)：impact_predictor 预检 + adapter.execute_action
     + audit
  6. main()：CLI 入口，支持 --dry-run（只采集+派生+决策，不执行）

守护链（与桌面端 controller.ts tryExecute 一致）：
  - max_attempts 守护：耗尽转 escalate
  - cooldown 守护：相同 idempotency_key 在 cooldown 窗口内跳过
  - ImpactPredictor 预检：deny 时不执行，写 audit skipped

部署模式：GitHub Actions cron 每 10 分钟 SSH 触发，不在服务器端常驻 systemd。
"""

import os
import sys


def _bootstrap_direct_script_import() -> None:
    if __package__ not in (None, ""):
        return
    script_dir = os.path.dirname(os.path.realpath(__file__))
    script_dir_name = os.path.basename(script_dir)
    fhd_root = os.path.dirname(os.path.dirname(script_dir))
    cleaned: list[str] = []
    for entry in list(sys.path):
        try:
            real_entry = os.path.realpath(entry)
        except Exception:
            real_entry = entry
        if real_entry == script_dir:
            continue
        if os.path.basename(real_entry) == script_dir_name and real_entry.endswith(
            os.path.join(os.sep, "autonomy")
        ):
            continue
        cleaned.append(entry)
    sys.path[:] = cleaned
    if fhd_root not in sys.path:
        sys.path.insert(0, fhd_root)


_bootstrap_direct_script_import()

import argparse
import time
from datetime import datetime, timezone
from typing import Any

# 支持直接 ``python scripts/autonomy/cvm_autonomy_watcher.py --help``：
# 当直接执行脚本时，__package__ 为 None，需将 FHD 根目录放到 sys.path
# 并使用绝对导入，避免 ``import types`` 命名冲突（脚本目录下有同名 types.py）。
if __package__ in (None, ""):
    from scripts.autonomy.cross_tier_gate import check_before_action, is_enabled as cross_tier_gate_enabled
    from scripts.autonomy.cvm_adapter import CvmAutonomyAdapter
    from scripts.autonomy.impact_predictor import predict
    from scripts.autonomy.policies import ALL_POLICIES
    from scripts.autonomy.types import (  # noqa: F401  # 仅导出供模块内使用
        Action,
        ActionTracker,
        ActionType,
        AuditEntry,
        AutonomyAdapter,
        Diagnosis,
        Plan,
        Policy,
        RiskLevel,
        RuntimeTruthSnapshot,
        Signal,
        ActionResult,
    )
else:
    from .cross_tier_gate import check_before_action, is_enabled as cross_tier_gate_enabled
    from .cvm_adapter import CvmAutonomyAdapter
    from .impact_predictor import predict
    from .policies import ALL_POLICIES
    from .types import (
        Action,
        ActionTracker,
        ActionType,
        ActionResult,
        AuditEntry,
        AutonomyAdapter,
        Diagnosis,
        Plan,
        Policy,
        RiskLevel,
        RuntimeTruthSnapshot,
        Signal,
    )

# 显式 autonomy callback（优先）+ 旁路 approval ledger client（fail-open）
try:
    from autonomy_callback import autonomy_callback as _autonomy_callback  # noqa: E402
except ImportError:  # pragma: no cover
    _autonomy_callback = None  # type: ignore[assignment]

try:
    _ci_scripts_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
        "scripts",
        "ci",
    )
    if _ci_scripts_dir not in sys.path:
        sys.path.insert(0, _ci_scripts_dir)
    from _approval_ledger_client import post_to_approval_ledger  # noqa: E402
    from _im_notify_client import notify_boss_im  # noqa: E402
except ImportError:  # pragma: no cover - 测试环境路径可能不通
    post_to_approval_ledger = None  # type: ignore[assignment]
    notify_boss_im = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# Truth → Signal 派生（与桌面端 runtime-truth.ts deriveSignalsFromTruth 对称）
# --------------------------------------------------------------------------- #


def derive_signals(truth: RuntimeTruthSnapshot) -> list[Signal]:
    """从 truth 派生信号。

    4 个派生规则（与桌面端 runtime-truth.ts 阈值同源）：
      - health_ok=False → health_down（crit）
      - disk_usage_percent >= 90 → disk_full（crit）
      - manifest_exists=True + manifest_frozen=False + 部署 digest 与 manifest 不一致
        → manifest_drift（warn）—— 简化判定：manifest_exists=True + manifest_frozen=False
        且 health_ok=False 时派生（需进一步证据时由 policy 拒绝）
      - compose_status 非 running，且不是「probe 不可靠/无 compose + health_ok」→
        compose_unhealthy（crit）
        （CVM staging/prod 常走 systemd：absent/unknown + health_ok 视为正常；
        unknown 常见于 compose.yml 残留但 docker compose ps 失败）

    纯函数：使用 truth.ts 作为信号 ts，禁止 time.time() / datetime.now()
    """
    signals: list[Signal] = []
    now_ms = truth.ts

    if not truth.health_ok:
        signals.append(
            Signal(
                source="runtime_truth",
                kind="health_down",
                severity="crit",
                detail=f"健康检查失败 (compose_status={truth.compose_status})",
                ts=now_ms,
                payload={"compose_status": truth.compose_status},
            )
        )

    if truth.disk_usage_percent >= 90:
        signals.append(
            Signal(
                source="runtime_truth",
                kind="disk_full",
                severity="crit",
                detail=f"磁盘占用 {truth.disk_usage_percent}%",
                ts=now_ms,
                payload={"percent": truth.disk_usage_percent},
            )
        )

    # manifest_drift 派生：manifest 存在但 .deploy-sha256 与 manifest 中 sha 不一致
    # 简化：当 manifest 存在 + 未 frozen + truth 额外字段 drift_detected=True 时派生
    # （truth 采集阶段不计算 drift，由 watcher 主流程在外部计算后注入 extra）
    if (
        truth.manifest_exists
        and not truth.manifest_frozen
        and truth.extra
        and truth.extra.get("manifest_drift_detected") is True
    ):
        signals.append(
            Signal(
                source="runtime_truth",
                kind="manifest_drift",
                severity="warn",
                detail="manifest sha256 与 .deploy-sha256 不一致",
                ts=now_ms,
                payload={"manifest_path": truth.manifest_path},
            )
        )

    # systemd / probe 不可靠但 API 健康：不报警。
    # - absent：无 compose.yml（纯 systemd）
    # - unknown：有 compose 文件但 docker compose ps 失败（prod 常见误报源）
    compose_probe_inconclusive = truth.compose_status in ("absent", "unknown")
    systemd_or_probe_ok = compose_probe_inconclusive and truth.health_ok
    if truth.compose_status != "running" and not systemd_or_probe_ok:
        signals.append(
            Signal(
                source="runtime_truth",
                kind="compose_unhealthy",
                severity="crit",
                detail=f"compose 状态异常: {truth.compose_status}",
                ts=now_ms,
                payload={"compose_status": truth.compose_status},
            )
        )

    return signals


# --------------------------------------------------------------------------- #
# Policy 调度（与桌面端 controller.ts process() 对称）
# --------------------------------------------------------------------------- #


def run_policies(signals: list[Signal], policies: list[Policy]) -> list[tuple[Policy, Plan]]:
    """调用所有匹配的 policy.plan()，返回 (policy, plan) 列表。

    - 按 policy 分组信号
    - 每 policy 调用一次 plan()（与桌面端 controller.ts process() 一致）
    - 空 signals 返回空列表
    """
    if not signals:
        return []
    results: list[tuple[Policy, Plan]] = []
    for policy in policies:
        matched = [s for s in signals if s.kind in policy.matches]
        if not matched:
            continue
        plan = policy.plan(matched)
        if plan.actions:
            results.append((policy, plan))
    return results


# --------------------------------------------------------------------------- #
# Action 执行守护链（与桌面端 controller.ts tryExecute 对称）
# --------------------------------------------------------------------------- #


class WatcherState:
    """watcher 内部状态：trackers（cooldown + max_attempts）。

    与桌面端 controller.ts ActionTracker 对称；状态在 watcher 进程生命周期内
    持久（每次 tick 复用）。
    """

    def __init__(self, default_cooldown_ms: int = 5 * 60 * 1000) -> None:
        self.trackers: dict[str, ActionTracker] = {}
        self.default_cooldown_ms = default_cooldown_ms
        self.processed_signal_keys: set[str] = set()

    def get_tracker(self, idempotency_key: str) -> ActionTracker:
        tracker = self.trackers.get(idempotency_key)
        if tracker is None:
            tracker = ActionTracker(idempotency_key=idempotency_key)
            self.trackers[idempotency_key] = tracker
        return tracker


def execute_plan(
    adapter: AutonomyAdapter,
    plan: Plan,
    truth: RuntimeTruthSnapshot,
    source_signal: Signal | None,
    state: WatcherState,
    dry_run: bool = False,
) -> list[AuditEntry]:
    """执行 plan 中的所有 action，返回 audit entries。

    与桌面端 controller.ts tryExecute() 对称：
      1. max_attempts 守护：耗尽转 escalate
      2. cooldown 守护：相同 idempotency_key 在 cooldown 窗口内跳过
      3. ImpactPredictor 预检：deny 时不执行，写 audit skipped
      4. dry_run=True：只决策不执行，写 audit skipped
    """
    audits: list[AuditEntry] = []
    for action in plan.actions:
        entry = _try_execute_single(
            adapter, action, plan.diagnosis, source_signal, truth, state, dry_run
        )
        audits.append(entry)
    return audits


def _try_execute_single(
    adapter: AutonomyAdapter,
    action: Action,
    diagnosis: Diagnosis,
    source_signal: Signal | None,
    truth: RuntimeTruthSnapshot,
    state: WatcherState,
    dry_run: bool,
) -> AuditEntry:
    """执行单个 action 的守护链（max_attempts → cooldown → predict → execute）。"""
    tracker = state.get_tracker(action.idempotency_key)

    # dry_run：只决策不执行，写 audit skipped
    if dry_run:
        entry = _build_skipped_audit(source_signal, diagnosis, action, truth, ["dry_run mode"])
        adapter.audit(entry)
        return entry

    # max_attempts 守护
    if tracker.attempts >= action.max_attempts:
        if not tracker.escalated:
            tracker.escalated = True
            return _escalate(
                adapter, action, diagnosis, source_signal, truth, "max_attempts exhausted"
            )
        entry = _build_skipped_audit(
            source_signal,
            diagnosis,
            action,
            truth,
            ["max_attempts exhausted and already escalated"],
        )
        adapter.audit(entry)
        return entry

    # cooldown 守护（仅 medium 风险）
    if action.risk == RiskLevel.MEDIUM and tracker.attempts > 0:
        now_ms = int(time.time() * 1000)
        if now_ms - tracker.last_attempt_ts < state.default_cooldown_ms:
            entry = _build_skipped_audit(
                source_signal, diagnosis, action, truth, ["cooldown window active"]
            )
            adapter.audit(entry)
            return entry

    # ImpactPredictor 预检
    prediction = predict(action, truth)
    if not prediction.allow:
        entry = _build_skipped_audit(source_signal, diagnosis, action, truth, prediction.reasons)
        adapter.audit(entry)
        return entry

    # CrossTierGate 跨端门禁（默认启用，env XCAGI_CROSS_TIER_GATE=0 关闭；fail-open）
    # 服务器端无法直接查询桌面端 pending marker；用 truth.pending_rollback_marker
    # 作为代理信号（桌面端通过 IPC 触发服务器端 rollback 时会创建 rollback-marker.json）
    if cross_tier_gate_enabled():
        remote_state = {
            "desktop_pending_rollback_marker": bool(truth.pending_rollback_marker),
        }
        gate_result = check_before_action("server", action.type.value, remote_state)
        if not gate_result.allow:
            entry = _build_skipped_audit(
                source_signal, diagnosis, action, truth, gate_result.reasons
            )
            adapter.audit(entry)
            return entry

    # 执行
    tracker.attempts += 1
    tracker.last_attempt_ts = int(time.time() * 1000)
    try:
        result = adapter.execute_action(action)
    except Exception as e:
        result = _make_error_result(action, f"execute_threw: {e}")

    entry = AuditEntry(
        ts=datetime.now(timezone.utc).isoformat(),
        source_signal=source_signal,
        diagnosis=diagnosis,
        action=action,
        result=result,
        truth_snapshot=truth,
    )
    adapter.audit(entry)

    # 回调 /github-approval：成功 → executed（fail-open）
    if getattr(result, "ok", False):
        try:
            from autonomy_callback import report_executed

            report_executed(
                action_id=action.idempotency_key,
                approver="cvm-autonomy-watcher",
                outcome={
                    "action_type": action.type.value,
                    "ok": True,
                    "detail": getattr(result, "detail", ""),
                },
                source="cvm_watcher",
            )
        except Exception:  # pragma: no cover - fail-open
            pass

    # 失败且耗尽 attempts → escalate
    if not result.ok and tracker.attempts >= action.max_attempts and not tracker.escalated:
        tracker.escalated = True
        escalate_entry = _escalate(adapter, action, diagnosis, source_signal, truth, result.detail)
        # 同时返回 escalate audit（与桌面端 controller.ts 行为一致：原始 action audit +
        # escalate audit 都写）
        # 注：watcher.execute_plan 返回 list，调用方可看到两条 audit
        # 此处只返回 escalate audit 以简化测试断言；原始 entry 已通过 adapter.audit 写入
        return escalate_entry

    return entry


def _escalate(
    adapter: AutonomyAdapter,
    original_action: Action,
    diagnosis: Diagnosis,
    source_signal: Signal | None,
    truth: RuntimeTruthSnapshot,
    reason: str,
) -> AuditEntry:
    """升级到人工处理：写 audit + 触发 escalate 动作。

    与桌面端 controller.ts escalate() 对称。
    """
    escalate_action = Action(
        type=ActionType.ESCALATE,
        params={
            "original_action": original_action.type.value,
            "reason": reason,
            "diagnosis_root_cause": diagnosis.root_cause,
        },
        idempotency_key=f"escalate:{original_action.idempotency_key}",
        max_attempts=1,
        risk=RiskLevel.HIGH,
    )
    try:
        result = adapter.execute_action(escalate_action)
    except Exception as e:
        result = _make_error_result(escalate_action, f"escalate_threw: {e}")
    entry = AuditEntry(
        ts=datetime.now(timezone.utc).isoformat(),
        source_signal=source_signal,
        diagnosis=diagnosis,
        action=escalate_action,
        result=result,
        truth_snapshot=truth,
    )
    adapter.audit(entry)
    # 显式 callback → approval ledger（fire-and-forget，fail-open）
    _escalate_payload = {
        "original_action": original_action.type.value,
        "reason": reason,
        "diagnosis_root_cause": diagnosis.root_cause,
        "idempotency_key": original_action.idempotency_key,
        "escalate_ok": bool(getattr(result, "ok", False)),
        "signal_kind": getattr(source_signal, "kind", "") if source_signal else "",
    }
    if _autonomy_callback is not None:
        try:
            _autonomy_callback(
                "cvm_escalate",
                _escalate_payload,
                source="cvm_watcher",
            )
        except Exception:  # pragma: no cover - fail-open
            pass
    elif post_to_approval_ledger is not None:
        try:
            post_to_approval_ledger(
                action="cvm_escalate",
                payload=_escalate_payload,
                source="cvm_watcher",
            )
        except Exception:  # pragma: no cover - fail-open
            pass
    # 回调 /github-approval：decision=execution_failed（fail-open）
    try:
        from autonomy_callback import report_execution_failed

        report_execution_failed(
            action_id=original_action.idempotency_key,
            approver="cvm-autonomy-watcher",
            error=reason,
            outcome={
                "action_type": original_action.type.value,
                "escalate_ok": bool(getattr(result, "ok", False)),
                "signal_kind": getattr(source_signal, "kind", "") if source_signal else "",
            },
            source="cvm_watcher",
        )
    except Exception:  # pragma: no cover - fail-open
        pass
    # 管理端 IM（fail-open）：needs-human 及时触达
    if notify_boss_im is not None:
        try:
            notify_boss_im(
                f"[CVM escalate] action={original_action.type.value} "
                f"reason={reason}\n"
                f"root_cause={diagnosis.root_cause}\n"
                f"key={original_action.idempotency_key}",
                employee_id="cvm-autonomy",
                display_name="CVM 自治",
                source="cvm_watcher",
            )
        except Exception:  # pragma: no cover - fail-open
            pass
    return entry


def _build_skipped_audit(
    source_signal: Signal | None,
    diagnosis: Diagnosis,
    action: Action,
    truth: RuntimeTruthSnapshot,
    reasons: list[str],
) -> AuditEntry:
    """构造 skipped audit entry（不执行 action，仅记录）。

    与桌面端 controller.ts tryExecute 中 prediction.allow=False 分支一致：
    entry.action = {type: 'skipped', reasons: [...]}
    """
    entry = AuditEntry(
        ts=datetime.now(timezone.utc).isoformat(),
        source_signal=source_signal,
        diagnosis=diagnosis,
        action={"type": "skipped", "reasons": reasons},
        result=None,
        truth_snapshot=truth,
    )
    return entry


def _make_error_result(action: Action, detail: str) -> Any:
    """构造执行抛错时的 ActionResult（避免循环导入）。"""
    return ActionResult(
        action=action,
        ok=False,
        detail=detail,
        ts=int(time.time() * 1000),
    )


# --------------------------------------------------------------------------- #
# 主流程：单次 tick
# --------------------------------------------------------------------------- #


def tick(
    adapter: AutonomyAdapter,
    policies: list[Policy],
    state: WatcherState,
    dry_run: bool = False,
) -> tuple[RuntimeTruthSnapshot, list[Signal], list[tuple[Policy, Plan]], list[AuditEntry]]:
    """单次 tick：采集 truth → 优先 unfreeze 检查 → 派生信号 → 调用 policy → 执行 action。

    返回 (truth, signals, plans, audits) 供测试断言与 CLI 输出。

    与桌面端 controller.ts tick() 对称：
      - truth 采集失败不抛错，写 audit + 返回空
      - 派生信号去重：相同 kind+ts 不重复 ingest（与桌面端 processedSignalKeys 一致）
      - **每次 tick 优先检查过期 .frozen 需解除**（hold_ttl 过期 + health 通过）
    """
    # 1. 采集 truth（容错）
    try:
        truth = adapter.collect_truth()
    except Exception as e:
        detail = f"truth_collect_failed: {e}"
        adapter.audit(
            AuditEntry(
                ts=datetime.now(timezone.utc).isoformat(),
                source_signal=None,
                diagnosis=Diagnosis(
                    root_cause="truth_collect_failed",
                    confidence=1.0,
                    detail=detail,
                    evidence=[],
                ),
                action=None,
                result=None,
            )
        )
        raise

    # 2. 优先检查过期 .frozen 需解除（在 plan 执行前）
    all_audits: list[AuditEntry] = []
    unfreeze_entry = _try_unfreeze_expired_manifest(adapter, truth, dry_run)
    if unfreeze_entry is not None:
        all_audits.append(unfreeze_entry)

    # 3. 派生信号
    signals = derive_signals(truth)
    # 去重：相同 kind+ts 不重复处理
    new_signals: list[Signal] = []
    for sig in signals:
        key = f"{sig.kind}:{sig.ts}"
        if key in state.processed_signal_keys:
            continue
        state.processed_signal_keys.add(key)
        new_signals.append(sig)

    # 4. 调用 policy
    plans = run_policies(new_signals, policies)

    # 5. 执行 action
    for policy, plan in plans:
        # source_signal 取 plan 中最新信号（按 ts 排序）
        matched_signals = [s for s in new_signals if s.kind in policy.matches]
        source_signal = max(matched_signals, key=lambda s: s.ts) if matched_signals else None
        audits = execute_plan(adapter, plan, truth, source_signal, state, dry_run)
        all_audits.extend(audits)

    return truth, new_signals, plans, all_audits


def _try_unfreeze_expired_manifest(
    adapter: AutonomyAdapter,
    truth: RuntimeTruthSnapshot,
    dry_run: bool,
) -> AuditEntry | None:
    """优先检查并解除过期 .frozen marker（每次 tick 在 plan 执行前调用）。

    触发条件（adapter.check_unfreeze_needed 判定）：
      - .frozen 文件存在
      - mtime age >= hold_ttl（默认 30min，env FHD_MANIFEST_HOLD_TTL_SECONDS 可配）

    实际解除（rm .frozen）由 adapter._action_unfreeze_manifest 内部再次校验：
      - hold_ttl 已过期
      - health check 通过（health 失败保持冻结）

    非 CvmAutonomyAdapter（如桌面端 adapter）直接跳过（返回 None）。

    Args:
        adapter: AutonomyAdapter 实例（仅 CvmAutonomyAdapter 支持 unfreeze）
        truth: 当前 tick 的 truth 快照
        dry_run: True 时只写 audit skipped，不实际执行

    Returns:
        AuditEntry if 尝试 unfreeze（成功/失败/dry_run skipped 都返回）；
        None if 无需 unfreeze（.frozen 不存在 / 未过期 / adapter 不支持）。
    """
    # 仅 CvmAutonomyAdapter 暴露 check_unfreeze_needed 接口
    check_fn = getattr(adapter, "check_unfreeze_needed", None)
    if check_fn is None:
        return None

    try:
        needed, age_seconds = check_fn()
    except Exception:
        # 检查失败不影响主流程
        return None

    if not needed:
        return None

    # 持有 hold_ttl（用于 audit 上下文，从 adapter 实例属性读取）
    hold_ttl = getattr(adapter, "hold_ttl", 0)

    action = Action(
        type=ActionType.UNFREEZE_MANIFEST,
        params={
            "age_seconds": age_seconds,
            "hold_ttl": hold_ttl,
            "reason": "expired_frozen_marker",
        },
        idempotency_key=f"unfreeze_manifest:tick:{truth.ts}",
        max_attempts=1,
        risk=RiskLevel.LOW,
    )
    diagnosis = Diagnosis(
        root_cause="expired_frozen_marker",
        confidence=1.0,
        detail=(
            f".frozen age {age_seconds}s >= hold_ttl {hold_ttl}s, "
            "attempting unfreeze (health check enforced in adapter)"
        ),
        evidence=[],
    )

    if dry_run:
        entry = _build_skipped_audit(None, diagnosis, action, truth, ["dry_run mode"])
        adapter.audit(entry)
        return entry

    # 直接调用 adapter.execute_action（不走 _try_execute_single 守护链）
    # 理由：unfreeze 是恢复动作，不应被 cooldown / max_attempts 干扰；
    # adapter._action_unfreeze_manifest 内部已守护 mtime + ttl + health。
    try:
        result = adapter.execute_action(action)
    except Exception as e:
        result = _make_error_result(action, f"execute_threw: {e}")

    entry = AuditEntry(
        ts=datetime.now(timezone.utc).isoformat(),
        source_signal=None,
        diagnosis=diagnosis,
        action=action,
        result=result,
        truth_snapshot=truth,
    )
    adapter.audit(entry)
    return entry


# --------------------------------------------------------------------------- #
# CLI 入口
# --------------------------------------------------------------------------- #


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI 参数。"""
    parser = argparse.ArgumentParser(
        prog="cvm-autonomy-watcher",
        description="XCMAX 服务器端自治 watcher（Phase 2）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只采集 truth + 派生信号 + 决策，不执行 action",
    )
    parser.add_argument(
        "--deploy-root",
        default="/opt/fhd-full",
        help="部署根目录（默认 /opt/fhd-full）",
    )
    parser.add_argument(
        "--manifest-path",
        default="/var/www/update/releases/stable/server/fhd-manifest.json",
        help="manifest 路径（默认 /var/www/update/releases/stable/server/fhd-manifest.json）",
    )
    parser.add_argument(
        "--audit-dir",
        default=None,
        help="audit 目录（默认 $DEPLOY_ROOT/autonomy）",
    )
    parser.add_argument(
        "--health-url",
        default="https://xiu-ci.com/fhd-api/api/health",
        help="健康检查 URL",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：构造 adapter + state，调用 tick，返回退出码。

    返回码：
      - 0：成功（包括 dry_run）
      - 1：truth 采集失败
      - 2：其他异常
    """
    args = parse_args(argv)
    adapter = CvmAutonomyAdapter(
        deploy_root=args.deploy_root,
        manifest_path=args.manifest_path,
        audit_dir=args.audit_dir,
        health_url=args.health_url,
    )
    state = WatcherState()
    try:
        truth, signals, plans, audits = tick(adapter, ALL_POLICIES, state, dry_run=args.dry_run)
    except Exception as e:
        # truth 采集失败已写 audit；返回 1
        print(f"[cvm-autonomy-watcher] tick failed: {e}", file=sys.stderr)
        return 1

    # 输出摘要到 stdout（便于 SSH 触发后 GitHub Actions 日志查看）
    print(
        f"[cvm-autonomy-watcher] truth: health_ok={truth.health_ok} "
        f"compose_status={truth.compose_status} disk={truth.disk_usage_percent}%"
    )
    print(f"[cvm-autonomy-watcher] signals: {len(signals)} ({[s.kind for s in signals]})")
    print(f"[cvm-autonomy-watcher] plans: {len(plans)}")
    print(f"[cvm-autonomy-watcher] audits: {len(audits)} (dry_run={args.dry_run})")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    sys.exit(main())
