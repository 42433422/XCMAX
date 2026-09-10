"""工单验收判定：市场端回执 → verifying/closed/reopened 状态落回。

从 work_order_ssot 拆出（2026-09-10 #1861 CI：app/ 单文件 ≤500 行门禁），
只承载验收回执判定；事件流存储与状态机本体仍在 work_order_ssot。

整改记录（2026-09-10 #1853 复审，随函数迁移）：
  - 回执只做验收判定，不推进完成阶段：in_dev/merged/released 必须由
    对应的开发/合并/发布证据经 record_transition 驱动，验收回执不再
    把 candidate/routed 一路补齐到 verifying（旧逻辑 pending 回执也会
    推进状态，已修复）。
  - pending 观察回执：不改状态、不写事件，历史保持不变。
  - accepted 关闭要求发布身份（release_version 非空）+ 双平台健康
    回执证据（per_platform：win/mac 均 installed>0 且 failed=0）。
  - 重复/乱序回执不覆盖新状态：同版本重复回执幂等返回；已记录其他
    发布身份后的旧版本回执按 stale_receipt 拒绝。
  - released → verifying 允许单步校正：回执本身携带发布身份与客户机
    安装证据，属发布证据驱动，事件明确标记为起点校正，不当作
    开发/合并动作真实发生。

依赖走函数内延迟导入：work_order_ssot 在模块尾部 re-export 本函数，
保持 ``wo.record_acceptance_verdict`` 既有调用面不变。
"""

from __future__ import annotations

from typing import Any


def record_acceptance_verdict(
    *,
    issue_number: int,
    release_version: str,
    verdict: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """市场端回执验收判定落回主线：verifying → closed / reopened。

    由 release-acceptance-closeout 在回写 GitHub issue 后调用；
    issue 未绑定工单时返回 ok=False（不阻塞 issue 回写本身）。
    """
    from app.services.work_order_ssot import find_by_issue, record_transition

    view = find_by_issue(issue_number)
    if view is None:
        return {"ok": False, "reason": "issue_not_linked", "issue_number": int(issue_number)}
    wo_id = str(view["wo_id"])
    current = str(view.get("status") or "")

    if verdict == "pending":
        # pending 只是观察：不推进任何阶段，不写任何事件
        return {"ok": False, "reason": "verdict_pending", "wo_id": wo_id, "status": current}
    if verdict not in ("accepted", "rejected"):
        return {"ok": False, "reason": "unknown_verdict", "wo_id": wo_id, "status": current}

    version = str(release_version or "").strip()
    if not version:
        # 发布身份缺失：没有版本锚点的回执不能驱动任何状态迁移
        return {
            "ok": False,
            "reason": "missing_release_identity",
            "wo_id": wo_id,
            "status": current,
        }

    # 乱序保护：工单已记录其他发布身份且处于验收终态 → 旧版本回执拒绝
    seen_version = str(view.get("release_version") or "")
    if seen_version and seen_version != version and current in ("closed", "reopened"):
        return {
            "ok": False,
            "reason": "stale_receipt",
            "wo_id": wo_id,
            "status": current,
            "receipt_release_version": version,
            "recorded_release_version": seen_version,
        }

    ref: dict[str, Any] = {"issue_number": int(issue_number), "release_version": version}
    if evidence:
        ref["evidence"] = evidence

    # 验收窗口：verifying 直接判定；released 单步校正进 verifying
    if current == "released":
        record_transition(
            wo_id,
            "verifying",
            ref=ref,
            note="验收期起点校正（市场回执驱动，非开发/合并动作）",
            source="acceptance",
        )
    elif current not in ("verifying", "closed", "reopened"):
        # candidate/routed/in_dev/merged：完成阶段未经对应证据驱动，拒绝判定
        return {
            "ok": False,
            "reason": "not_in_acceptance_window",
            "wo_id": wo_id,
            "status": current,
        }

    if verdict == "accepted":
        if current == "closed":
            # 重复回执：幂等成功，不重复写关闭事件
            return {"ok": True, "reason": "already_closed", "wo_id": wo_id, "status": current}
        # 业务验收证据：双平台健康回执（CI 通过 ≠ 客户能用）
        platforms = (evidence or {}).get("per_platform")
        healthy: list[str] = []
        if isinstance(platforms, dict):
            for p in ("win", "mac"):
                stats = platforms.get(p)
                if isinstance(stats, dict) and int(stats.get("installed") or 0) > 0:
                    if int(stats.get("failed") or 0) == 0:
                        healthy.append(p)
        if len(healthy) < 2:
            return {
                "ok": False,
                "reason": "missing_acceptance_evidence",
                "wo_id": wo_id,
                "status": str((find_by_issue(issue_number) or {}).get("status") or ""),
                "healthy_platforms": healthy,
            }
        return record_transition(
            wo_id, "closed", ref=ref, note="双平台回执健康，客户验收通过", source="acceptance"
        )

    # rejected
    if current == "reopened":
        return {"ok": True, "reason": "already_reopened", "wo_id": wo_id, "status": current}
    return record_transition(
        wo_id, "reopened", ref=ref, note="客户机安装/运行失败，重开原工单", source="acceptance"
    )


__all__ = ["record_acceptance_verdict"]
