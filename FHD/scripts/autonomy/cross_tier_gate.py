"""跨端门禁：动作执行前检查其他端状态，防止跨端副作用。

用户痛点 3：修了 A 崩了 B。跨端门禁在动作执行前检查其他端的远程状态，
避免桌面端回滚到服务器端已冻结的版本、服务器端嵌套回滚等场景。

设计：
- 纯函数 check_before_action(tier, action, remote_state) → GateResult
- 默认启用（env XCAGI_CROSS_TIER_GATE=0 关闭，opt-out）
- 失败模式：跨端查询失败（remote_state=None）fail-closed，allow=false
- 与桌面端 controller.ts / 服务器端 cvm_watcher.py 共用同一语义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Tier = Literal["desktop", "server", "ci"]


@dataclass
class GateResult:
    """门禁结果。"""

    allow: bool
    reasons: list[str] = field(default_factory=list)


def check_before_action(
    tier: Tier,
    action_type: str,
    remote_state: dict[str, Any] | None,
) -> GateResult:
    """跨端门禁纯函数。

    Args:
        tier: 当前执行端（desktop / server / ci）
        action_type: 动作类型（rollback_version / rollback_to_last_tarball / cvm-push-release 等）
        remote_state: 其他端的远程状态快照；None 表示查询失败

    Returns:
        GateResult(allow=True) 可执行；GateResult(allow=False, reasons) 应跳过并写 audit

    语义：
    - remote_state=None（查询失败）→ allow=False（fail-closed）
    - remote_state={}（已知空状态）→ allow=True
    - 命中门禁规则 → allow=False + reasons
    """
    # 跨端查询失败：fail-closed，阻断动作
    if remote_state is None:
        return GateResult(allow=False, reasons=["remote_state unavailable, fail-closed"])

    # 桌面端 rollback_version 前检查服务器端 manifest 是否 frozen
    if tier == "desktop" and action_type == "rollback_version":
        server_manifest_frozen = remote_state.get("server_manifest_frozen", False)
        if server_manifest_frozen:
            return GateResult(
                allow=False,
                reasons=[
                    "服务器端 manifest 已冻结（.frozen），回滚可能冲突；"
                    "请联系运维解除冻结或确认回滚目标版本"
                ],
            )

    # 服务器端 rollback_to_last_tarball 前检查桌面端是否有 pending rollback marker
    if tier == "server" and action_type == "rollback_to_last_tarball":
        desktop_pending_marker = remote_state.get("desktop_pending_rollback_marker", False)
        if desktop_pending_marker:
            return GateResult(
                allow=False,
                reasons=[
                    "桌面端存在 pending rollback marker，嵌套回滚风险；"
                    "请先等待桌面端回滚完成或清除 marker"
                ],
            )

    # CI cvm-push-release 前检查服务器端是否有 manifest_already_frozen
    if tier == "ci" and action_type == "cvm-push-release":
        server_manifest_frozen = remote_state.get("server_manifest_frozen", False)
        if server_manifest_frozen:
            return GateResult(
                allow=False,
                reasons=[
                    "服务器端 manifest 已冻结，推送新版本会覆盖冻结状态；请联系运维解除冻结后再推送"
                ],
            )

    # 默认允许
    return GateResult(allow=True)


def is_enabled() -> bool:
    """检查跨端门禁是否启用（默认启用，opt-out）。

    - env 未设 / 空 / "1" / "true" / "yes" → 启用（True）
    - env "0" / "false" / "no" → 关闭（False）

    与桌面端 cross-tier-gate.ts:isEnabled() 同语义。
    """
    import os

    v = os.environ.get("XCAGI_CROSS_TIER_GATE", "").strip().lower()
    if v in ("", "1", "true", "yes"):
        return True
    return False
