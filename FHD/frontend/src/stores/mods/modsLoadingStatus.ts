/**
 * /api/mods/loading-status 读取与重试判定（拆分自 stores/mods.ts，行为保持一致）。
 */
import { fetchModLoadingStatusShared } from '@/utils/modLoadingStatusShared'
import { summarizeModLoadingData } from '@/utils/modLoadingStatus'

/**
 * 重启后端后可能出现：磁盘上有 Mod 但首轮 load 尚未进注册表，/api/mods/ 暂时为空。
 * 与 GET /api/mods/loading-status 的 discovered_mod_ids / load_mismatch 对齐后再拉列表。
 */
/**
 * 仅当 loading-status 明确「磁盘上未发现任何 manifest」时为 true。
 * 用于避免：/api/mods/ 暂时空列表 + loading-status 失败时误把 isLoaded 置 true，导致之后 initialize 被短路、Mod 永远不拉。
 */
export async function readLoadingStatusPayload() {
  const d = await fetchModLoadingStatusShared()
  if (!d) return null
  return d as {
    discovered_mod_ids?: string[]
    mods_loaded?: number
    load_mismatch?: boolean
    load_errors?: unknown[]
    manifest_errors?: unknown[]
    blueprint_errors?: unknown[]
    partial_failure?: boolean
    mods_disabled?: boolean
  }
}

export async function confirmServerReportsZeroDiscoveredMods(): Promise<boolean> {
  try {
    const d = await readLoadingStatusPayload()
    if (!d) return false
    const discovered = Array.isArray(d.discovered_mod_ids) ? d.discovered_mod_ids : []
    return discovered.length === 0
  } catch {
    return false
  }
}

export async function shouldRetryModsListWhenEmpty(): Promise<boolean> {
  try {
    const d = await readLoadingStatusPayload()
    if (!d) return false
    const discovered = Array.isArray(d.discovered_mod_ids) ? d.discovered_mod_ids : []
    const loaded = typeof d.mods_loaded === 'number' ? d.mods_loaded : 0
    if (d.mods_disabled === true) return false
    if (d.load_mismatch === true) return true
    if (discovered.length > 0 && loaded === 0) return true
    return false
  } catch {
    return false
  }
}

export async function fetchModLoadingStatusHint(): Promise<string | null> {
  try {
    const d = await readLoadingStatusPayload()
    if (!d) return null
    return summarizeModLoadingData(d as Record<string, unknown>)
  } catch {
    return null
  }
}
