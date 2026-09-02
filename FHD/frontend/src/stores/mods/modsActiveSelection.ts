/**
 * 当前扩展包选择逻辑（拆分自 stores/mods.ts，行为保持一致）：
 * ensureActiveModSelection / applyEntitledActiveMod / syncActiveModWithServerIndustry。
 */
import type { Ref } from 'vue'
import type { ModInfo } from '@/types/modInfo'
import { apiFetch, DEFAULT_MOD_API_TIMEOUT_MS } from '@/utils/apiBase'
import { CLIENT_PRIMARY_ERP_MOD_ID, isSelectableExtensionModId } from '@/constants/genericModPack'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { augmentEntitledModIdsForAccount } from '@/constants/accountModBinding'
import { bootstrapHostConfig, clientModPolicies } from '@/stores/hostConfig'
import { entitlementMatchesMod, normalizeEntitledModIds, pickModIdFromEntitled } from './entitlements'
import { pickModMatchingIndustry, type ModsInitializeOptions } from './modsShared'

export interface ModsActiveSelectionDeps {
  mods: Ref<ModInfo[]>
  activeModId: Ref<string>
  clientModsUiOff: Ref<boolean>
  setActiveModId: (modId: string | null | undefined, scope?: string) => void
  resolveModsAccountContext: () => { accountUsername: string; isAdminAccount: boolean }
  readPendingInitOptions: () => ModsInitializeOptions | null
}

export function useModsActiveSelection(deps: ModsActiveSelectionDeps) {
  const { mods, activeModId, clientModsUiOff, setActiveModId, resolveModsAccountContext, readPendingInitOptions } = deps

  function ensureActiveModSelection() {
    if (clientModsUiOff.value) return
    if (isAdminConsoleSpa()) {
      setActiveModId('')
      return
    }
    if (!mods.value.length) {
      setActiveModId('')
      return
    }
    const { isAdminAccount } = resolveModsAccountContext()
    let current = String(activeModId.value || '').trim()
    if (isAdminAccount) {
      if (current === CLIENT_PRIMARY_ERP_MOD_ID) setActiveModId('')
      return
    }
    if (current && mods.value.some((m) => String(m.id || '').trim() === current)) {
      // 若误选宿主 bridge，优先改到第一个行业扩展包（bridge 不作为「当前扩展」）
      if (!isSelectableExtensionModId(current)) {
        const ext = findClientPrimaryErpMod() || mods.value.find((m) => isSelectableExtensionModId(String(m.id || '')))
        if (ext) setActiveModId(String(ext.id || '').trim())
      }
      return
    }
    const preferred =
      mods.value.find((m) => m.primary && isSelectableExtensionModId(String(m.id || ''))) ||
      mods.value.find((m) => isSelectableExtensionModId(String(m.id || '')))
    setActiveModId(preferred ? String(preferred.id || '').trim() : '')
  }

  function findClientPrimaryErpMod(): ModInfo | undefined {
    return mods.value.find((m) => String(m.id || '').trim() === CLIENT_PRIMARY_ERP_MOD_ID)
  }

  /**
   * 企业版登录/会话：按 entitled_mod_ids 与宿主 client_primary_erp_mod_id 选定当前扩展。
   */
  async function applyEntitledActiveMod(
    entitledModIds: string[] | undefined,
    options?: { force?: boolean; accountUsername?: string },
  ): Promise<void> {
    if (clientModsUiOff.value || !mods.value.length) return

    const username = String(options?.accountUsername || readPendingInitOptions()?.accountUsername || '').trim()
    const entitled = augmentEntitledModIdsForAccount(username, normalizeEntitledModIds(entitledModIds))
    if (!entitled.length) return

    await bootstrapHostConfig()
    const primaryErp = String(clientModPolicies.value?.client_primary_erp_mod_id || CLIENT_PRIMARY_ERP_MOD_ID).trim()

    const force = Boolean(options?.force)
    const entitledSet = new Set(entitled)
    const current = String(activeModId.value || '').trim()

    let next = ''
    if (!next && (force || !current || !entitlementMatchesMod(current, entitledSet))) {
      next = pickModIdFromEntitled(entitled, mods.value, primaryErp)
    }
    if (!next) return

    const listedNext = mods.value.some((m) => String(m.id || '').trim() === next)
    if (!listedNext) return

    if (next !== current) {
      setActiveModId(next)
    }
    // SSOT 收敛后：行业由后端 User.industry_id 决定，不再调用 syncIndustryForActiveMod。
  }

  /**
   * 仅在 activeModId 为空时按 server 当前行业回填一个 active mod：
   * 用户已经在 Settings 单选过的 mod，不应被静默换回（此前实现会在每次刷新都
   * 把 activeModId 拉回到与 server 行业匹配的 mod，导致选了 taiyangniao-pro
   * 后下次刷新被换成 sz-qsm-pro）。
   *
   * SSOT 收敛后：行业由后端 User.industry_id 决定，前端不再主动同步行业到 server，
   * 因此这里不需要"刷新对齐"。
   */
  async function syncActiveModWithServerIndustry(): Promise<void> {
    if (clientModsUiOff.value || !mods.value.length) return
    const current = String(activeModId.value || '').trim()
    if (current) {
      // 已经有用户选定的 active mod，server 行业以它为准，不再反向覆盖
      return
    }
    try {
      const response = await apiFetch('/api/system/industry', {
        timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS,
      })
      if (!response.ok) return
      const payload = await response.json()
      const serverId = payload?.success && payload?.data?.id != null ? String(payload.data.id).trim() : ''
      if (!serverId) return
      const picked = pickModMatchingIndustry(mods.value, serverId, '')
      if (picked) {
        setActiveModId(String(picked.id || '').trim())
      }
    } catch {
      /* 忽略：保持 ensureActiveModSelection 结果 */
    }
  }

  return {
    findClientPrimaryErpMod,
    ensureActiveModSelection,
    applyEntitledActiveMod,
    syncActiveModWithServerIndustry,
  }
}
