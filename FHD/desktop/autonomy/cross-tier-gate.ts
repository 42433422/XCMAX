/**
 * 跨端门禁：动作执行前检查其他端状态，防止跨端副作用。
 *
 * 用户痛点 3：修了 A 崩了 B。跨端门禁在动作执行前检查其他端的远程状态，
 * 避免桌面端回滚到服务器端已冻结的版本、服务器端嵌套回滚等场景。
 *
 * 设计：
 * - 纯函数 checkBeforeAction(tier, action, remoteState) → GateResult
 * - 默认启用（env XCAGI_CROSS_TIER_GATE=0 关闭，opt-out）
 * - 失败模式：跨端查询失败（remoteState=null）fail-closed，allow=false
 *   （仅适用于会改变跨端版本/发布状态的动作）
 * - 与服务器端 scripts/autonomy/cross_tier_gate.py 共用同一语义
 */

/** 执行端标识 */
export type Tier = 'desktop' | 'server' | 'ci'

/** 门禁结果 */
export interface GateResult {
  /** true=允许执行；false=应跳过并写 audit */
  allow: boolean
  /** 拒绝原因（allow=false 时填充） */
  reasons: string[]
}

/**
 * Only these actions can conflict with state owned by another tier.  Local,
 * reversible remediation such as cache cleanup must not become unavailable
 * merely because the product is offline.
 */
const CROSS_TIER_ACTION_TYPES = new Set([
  'rollback_version',
  'rollback_to_last_tarball',
  'cvm-push-release',
])

export function requiresRemoteState(actionType: string): boolean {
  return CROSS_TIER_ACTION_TYPES.has(actionType)
}

/**
 * 跨端门禁纯函数。
 *
 * @param tier 当前执行端（desktop / server / ci）
 * @param actionType 动作类型（rollback_version / rollback_to_last_tarball / cvm-push-release 等）
 * @param remoteState 其他端的远程状态快照；null 表示查询失败
 * @returns GateResult.allow=true 可执行；allow=false 应跳过并写 audit
 *
 * 语义：
 * - 对跨端动作，remoteState=null（查询失败）→ allow=false（fail-closed）
 * - remoteState={}（已知空状态）→ allow=true
 * - 命中门禁规则 → allow=false + reasons
 */
export function checkBeforeAction(
  tier: Tier,
  actionType: string,
  remoteState: Record<string, unknown> | null,
): GateResult {
  // 跨端查询失败：fail-closed，阻断动作
  if (remoteState === null) {
    return { allow: false, reasons: ['remote_state unavailable, fail-closed'] }
  }

  // 桌面端 rollback_version 前检查服务器端 manifest 是否 frozen
  if (tier === 'desktop' && actionType === 'rollback_version') {
    const serverManifestFrozen = Boolean(remoteState.server_manifest_frozen ?? false)
    if (serverManifestFrozen) {
      return {
        allow: false,
        reasons: [
          '服务器端 manifest 已冻结（.hold），回滚可能冲突；请联系运维解除冻结或确认回滚目标版本',
        ],
      }
    }
  }

  // 服务器端 rollback_to_last_tarball 前检查桌面端是否有 pending rollback marker
  if (tier === 'server' && actionType === 'rollback_to_last_tarball') {
    const desktopPendingMarker = Boolean(remoteState.desktop_pending_rollback_marker ?? false)
    if (desktopPendingMarker) {
      return {
        allow: false,
        reasons: [
          '桌面端存在 pending rollback marker，嵌套回滚风险；请先等待桌面端回滚完成或清除 marker',
        ],
      }
    }
  }

  // CI cvm-push-release 前检查服务器端是否有 manifest_already_frozen
  if (tier === 'ci' && actionType === 'cvm-push-release') {
    const serverManifestFrozen = Boolean(remoteState.server_manifest_frozen ?? false)
    if (serverManifestFrozen) {
      return {
        allow: false,
        reasons: [
          '服务器端 manifest 已冻结，推送新版本会覆盖冻结状态；请联系运维解除冻结后再推送',
        ],
      }
    }
  }

  // 默认允许
  return { allow: true, reasons: [] }
}

/**
 * 检查跨端门禁是否启用。
 *
 * 默认启用（opt-out）：
 * - env 未设 / 空 / "1" / "true" / "yes" → 启用（true）
 * - env "0" / "false" / "no" → 关闭（false）
 *
 * 与服务器端 cross_tier_gate.py:is_enabled() 同语义。
 */
export function isEnabled(): boolean {
  const v = (process.env.XCAGI_CROSS_TIER_GATE ?? '').trim().toLowerCase()
  if (v === '' || v === '1' || v === 'true' || v === 'yes') return true
  return false
}
