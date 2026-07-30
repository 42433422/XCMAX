"""ImpactPredictor：服务器端 8 action 运行时预检门禁（Phase 2）。

用户决策：运行时预检 + Policy 门禁（不做静态依赖图）。
所有动作执行前必须通过 predict()，allow=False 时 controller 写 audit 不执行。

设计：拦截不阻断。误判仅记录 reasons，不抛错。

预检规则（与桌面端 impact-predictor.ts 对称，但 action 集合不同）：
  - restart_service：compose.yml 存在 + service_running=True 才允许
  - rollback_to_last_tarball：.deploy-last.tarball 存在 + pending_rollback_marker=False 才允许
  - freeze_manifest：manifest 存在 + 未已 frozen（.frozen 不存在）才允许
  - unfreeze_manifest：始终允许（mtime + hold_ttl + health 由 adapter._action_unfreeze_manifest 内守护）
  - clear_logs：logs 目录存在 + disk_usage_percent > 70 才允许
  - escalate / noop / open_incident_issue：始终允许（无破坏性副作用；open_incident_issue
    的 token / 去重 / 前置 action 失败判定由 adapter 内守护）
"""

from __future__ import annotations

import os

from .types import Action, ActionType, Prediction, RuntimeTruthSnapshot

# 磁盘清理触发阈值默认值（可被 adaptive_thresholds 覆盖）
DISK_CLEAN_THRESHOLD = 70


def _disk_clean_threshold() -> float:
    """硬常量降级：优先读自适应阈值（带 floor/ceiling）。"""
    try:
        from app.domain.autonomy.adaptive_thresholds import get_threshold

        return float(get_threshold("disk_clean_threshold").value)
    except Exception:  # noqa: BLE001
        return float(DISK_CLEAN_THRESHOLD)


def predict(action: Action, truth: RuntimeTruthSnapshot) -> Prediction:
    """预测动作的副作用风险。

    Args:
        action: 待执行动作
        truth: 当前现实快照

    Returns:
        allow=True 可执行；allow=False 必须记录 reasons 并跳过
    """
    reasons: list[str] = []
    suggestions: list[str] = []

    if action.type == ActionType.RESTART_SERVICE:
        # 风险：compose 文件不存在则 restart 无意义
        compose_file = _resolve_compose_file(truth.deploy_root)
        if compose_file is None:
            reasons.append(f"compose.yml 不存在于 {truth.deploy_root}，restart_service 无目标")
        # 风险：服务未运行则 restart 是空操作（应先 start 而非 restart）
        if not truth.service_running:
            reasons.append("service_running=False，docker compose 无 running 服务，restart 无意义")
            suggestions.append("检查服务是否已 start 或 escalate")

    elif action.type == ActionType.ROLLBACK_TO_LAST_TARBALL:
        # 风险：嵌套回滚（已有 pending marker）
        if truth.pending_rollback_marker:
            reasons.append("已存在 pending rollback marker，禁止嵌套回滚")
        # 风险：无 tarball 可回滚
        rollback_tarball = os.path.join(truth.deploy_root, ".deploy-last.tar.gz")
        if not os.path.isfile(rollback_tarball):
            reasons.append(f"无 .deploy-last.tar.gz 回滚包：{rollback_tarball}")
            suggestions.append("先通过 fhd-push-release.sh 推送新版本，或人工介入")
        # 风险：备份过旧（>7 天）
        if truth.last_backup_ts is not None:
            seven_days_ms = 7 * 24 * 60 * 60 * 1000
            now_ms = truth.ts
            if now_ms - truth.last_backup_ts > seven_days_ms:
                age_days = round((now_ms - truth.last_backup_ts) / (24 * 3600 * 1000))
                reasons.append(f"最近备份超过 7 天（{age_days} 天前），回滚后数据可能丢失")
                suggestions.append("先执行手动备份再回滚")

    elif action.type == ActionType.FREEZE_MANIFEST:
        # 风险：manifest 不存在则 freeze 无意义
        if not truth.manifest_exists:
            reasons.append(f"manifest 不存在：{truth.manifest_path}")
        # 风险：已 frozen（.frozen 存在）则重复 freeze 无意义
        if truth.manifest_frozen:
            reasons.append("manifest 已 frozen（.frozen 存在），无需重复 freeze")

    elif action.type == ActionType.UNFREEZE_MANIFEST:
        # 风险：未 frozen 则 unfreeze 无意义
        if not truth.manifest_frozen:
            reasons.append("manifest 未 frozen（.frozen 不存在），unfreeze_manifest 无目标")
        # mtime + hold_ttl + health_ok 由 adapter._action_unfreeze_manifest 内守护，
        # 不在 predict 阶段重复检查（避免 predict 与 action 双重 health curl）。

    elif action.type == ActionType.CLEAR_LOGS:
        # 风险：logs 目录不存在
        logs_dir = os.path.join(truth.deploy_root, "logs")
        if not os.path.isdir(logs_dir):
            reasons.append(f"logs 目录不存在：{logs_dir}")
        # 风险：磁盘未紧张时清理无意义（且可能误删用户临时文件）
        # 注：> 而非 >=，仅当磁盘占用严格超过阈值时才允许清理
        disk_threshold = _disk_clean_threshold()
        if truth.disk_usage_percent <= disk_threshold:
            reasons.append(
                f"磁盘占用 {truth.disk_usage_percent}% <= 阈值 {disk_threshold}%，无需清理"
            )

    elif action.type in (ActionType.ESCALATE, ActionType.NOOP, ActionType.OPEN_INCIDENT_ISSUE):
        # escalate / noop / open_incident_issue 始终允许（不产生破坏性副作用）
        # open_incident_issue 的 token / 24h 去重 / 前置 action 失败判定
        # 由 adapter._action_open_incident_issue 内守护（避免 predict 与 action 双重 API 调用）
        pass

    return Prediction(
        allow=len(reasons) == 0,
        reasons=reasons,
        suggestions=suggestions,
    )


def _resolve_compose_file(deploy_root: str) -> str | None:
    """查找 compose.yml / docker-compose.yml（与 cvm_adapter._resolve_compose_file 一致）。

    作为模块级私有函数，避免循环依赖（impact_predictor 不依赖 cvm_adapter）。
    """
    for name in ("compose.yml", "docker-compose.yml"):
        path = os.path.join(deploy_root, name)
        if os.path.isfile(path):
            return path
    return None


def batch_predict(actions: list[Action], truth: RuntimeTruthSnapshot) -> list[Prediction]:
    """批量预测（每个 action 一个 Prediction）。测试辅助。"""
    return [predict(a, truth) for a in actions]


def should_skip(action: Action, truth: RuntimeTruthSnapshot) -> tuple[bool, list[str]]:
    """便捷方法：返回 (skip, reasons)。skip=True 时 controller 应跳过并写 audit。"""
    p = predict(action, truth)
    return (not p.allow, p.reasons)
