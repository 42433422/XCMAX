/**
 * Facade：mods store 装配入口（实现拆分至 mods/ 子模块，行为与拆分前一致）。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ModInfo } from '@/types/modInfo'
import { apiFetch, DEFAULT_MOD_API_TIMEOUT_MS, isApiFetchTimeoutError } from '@/utils/apiBase'
import { fetchModRoutesPayloadShared } from '@/utils/modRoutesSharedFetch'
import { fetchPlatformShellCapabilities } from '@/utils/platformShellApi'
import { applyEditionPackPlatformShell } from '@/constants/platformShellMode'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { filterWorkflowRegistrySourceMods } from '@/utils/modWorkflowEmployees'
import { CLIENT_PRIMARY_ERP_MOD_ID, isAuxEmployeePackModId } from '@/constants/genericModPack'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { buildAttendanceIndustryModStub } from '@/constants/sunbirdClientMod'
import { writeActiveExtensionModIdToStorage } from '@/utils/xcagiStorageKeys'
import { isAccountCustomModId, canonicalEntitlementId } from './mods/entitlements'
import { applyModFacadeFlagsFromListing, resetModFacadeProbes } from './mods/modFacadeProbes'
import {
  confirmServerReportsZeroDiscoveredMods,
  fetchModLoadingStatusHint,
  shouldRetryModsListWhenEmpty,
} from './mods/modsLoadingStatus'
import { useModsActiveSelection } from './mods/modsActiveSelection'
import { useModsSidebarMenu } from './mods/modsSidebarMenu'
import {
  CLIENT_MODS_UI_OFF_KEY,
  delay,
  readActiveModId,
  readClientModsUiOff,
  type FetchModsOptions,
  type ModRoute,
  type ModsInitializeOptions,
} from './mods/modsShared'

export { CLIENT_MODS_UI_OFF_KEY } from './mods/modsShared'
export { readEntitledModIdsFromAuthPayload } from './mods/entitlements'
export type { ModsInitializeOptions, ModRoute } from './mods/modsShared'

export const useModsStore = defineStore('mods', () => {
  const mods = ref<ModInfo[]>([])
  const modRoutes = ref<ModRoute[]>([])
  /** 用户在前端启用「原版模式」：完全隔离 Mod（无请求、无路由、无侧栏/工作流痕迹） */
  const clientModsUiOff = ref(readClientModsUiOff())
  /** 当前会话只启用一个扩展包（空字符串表示未选择） */
  const activeModId = ref(readActiveModId())
  /** 仅在为 true 时表示「已成功拉取过 /api/mods/」；失败时为 false，可再次 initialize */
  const isLoaded = ref(false)
  const loadError = ref<string | null>(null)
  let initInFlight: Promise<void> | null = null
  let pendingInitOptions: ModsInitializeOptions | null = null
  let lastInitAccountUsername = ''

  function resolveModsAccountUsername(): string {
    const pending = String(pendingInitOptions?.accountUsername || '').trim()
    if (pending) return pending
    if (lastInitAccountUsername) return lastInitAccountUsername
    try {
      const raw = localStorage.getItem('xcagi_market_user_json')
      if (!raw) return ''
      const parsed = JSON.parse(raw) as { username?: string }
      return String(parsed?.username || '').trim()
    } catch {
      return ''
    }
  }

  function resolveModsAccountContext() {
    const accountUsername = resolveModsAccountUsername()
    let isAdminAccount = false
    try {
      isAdminAccount = useAccountProfileStore().isAdminAccount
    } catch {
      /* pinia not ready */
    }
    return { accountUsername, isAdminAccount }
  }

  function setActiveModId(modId: string | null | undefined, scope?: string) {
    const next = String(modId || '').trim()
    activeModId.value = next
    try {
      writeActiveExtensionModIdToStorage(next || null, scope)
    } catch {
      /* private mode */
    }
  }

  function reloadActiveModForTenantScope(scope?: string) {
    activeModId.value = readActiveModId(scope)
  }

  const selection = useModsActiveSelection({
    mods,
    activeModId,
    clientModsUiOff,
    setActiveModId,
    resolveModsAccountContext,
    readPendingInitOptions: () => pendingInitOptions,
  })
  const { findClientPrimaryErpMod, ensureActiveModSelection, applyEntitledActiveMod, syncActiveModWithServerIndustry } = selection

  /** 侧栏、副窗工作流等应使用此列表；仍为完整拉取结果时用 mods */
  const modsForUi = computed<ModInfo[]>(() => {
    if (clientModsUiOff.value) return []
    if (isAdminConsoleSpa()) return []
    const active = String(activeModId.value || '').trim()
    if (!active) {
      try {
        if (useAccountProfileStore().isAdminAccount) return []
      } catch {
        /* pinia not ready */
      }
      return mods.value
    }
    const activeCanonical = canonicalEntitlementId(active)
    const overlayExtras = (): ModInfo[] =>
      mods.value.filter((m) => {
        const id = String(m.id || '').trim()
        if (!id || id === active) return false
        if (isAuxEmployeePackModId(id)) return true
        return Boolean(activeCanonical && isAccountCustomModId(id) && canonicalEntitlementId(id) === activeCanonical)
      })

    const hit = mods.value.find((m) => String(m.id || '').trim() === active)
    if (hit) return [hit, ...overlayExtras()]
    if (active === CLIENT_PRIMARY_ERP_MOD_ID) {
      return [findClientPrimaryErpMod() || buildAttendanceIndustryModStub(), ...overlayExtras()]
    }
    return mods.value
  })

  /**
   * 工作流员工页 / 副窗 / 流程全景：使用完整已加载 Mod 列表中的 workflow 源包。
   * 管理端 SPA 侧栏用 modsForUi=[]，但运维页仍需看到磁盘上的工作流员工 Mod。
   */
  const modsForWorkflowUi = computed<ModInfo[]>(() => {
    if (clientModsUiOff.value) return []
    return filterWorkflowRegistrySourceMods(mods.value) as ModInfo[]
  })

  const menu = useModsSidebarMenu({ mods, modsForUi, activeModId, findClientPrimaryErpMod })

  /** 启动页 loading-status 先写入，侧栏可立刻显示名称；完整列表仍靠 initialize */
  function applyLoadingStatusPreview(rows: Array<{ id: string; name?: string; version?: string }> | null | undefined) {
    if (clientModsUiOff.value) return
    if (!Array.isArray(rows) || rows.length === 0) return
    if (mods.value.length > 0) return
    mods.value = rows.map((r) => ({
      id: String(r.id || '').trim() || 'unknown',
      name: String(r.name || r.id || '').trim() || String(r.id || ''),
      version: String(r.version || ''),
      author: '',
      description: '',
    }))
  }

  async function fetchModsOnce(fetchOpts?: FetchModsOptions): Promise<{
    ok: boolean
    modsDisabled?: boolean
    /** 连接被拒绝/中断等，适合稍长间隔再试（例如刚启动 Vite 或 run.py） */
    transportError?: boolean
  }> {
    try {
      const response = await apiFetch('/api/mods/', { timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS })
      if (!response.ok) {
        loadError.value = `HTTP ${response.status}`
        return { ok: false }
      }
      const data = await response.json()
      if (!data.success) {
        // 后端 list_mods 异常时返回 message；部分接口用 error —— 都要展示，避免统一成含糊的「列表失败」
        const apiErr = typeof data.error === 'string' ? data.error : typeof data.message === 'string' ? data.message : ''
        loadError.value = apiErr || '列表失败'
        return { ok: false }
      }
      if (data.mods_disabled === true) {
        mods.value = []
        setActiveModId('')
        loadError.value = 'Mod 扩展已关闭（XCAGI_DISABLE_MODS）'
        return { ok: true, modsDisabled: true }
      }
      mods.value = Array.isArray(data.data) ? data.data : []
      ensureActiveModSelection()
      const active = String(activeModId.value || '').trim()
      const postTasks: Promise<unknown>[] = []
      if (!fetchOpts?.skipEntitledApply) {
        postTasks.push(
          applyEntitledActiveMod(pendingInitOptions?.entitledModIds, {
            force: pendingInitOptions?.forceFromEntitlements ?? false,
            accountUsername: pendingInitOptions?.accountUsername,
          }),
        )
      }
      if (!active || !mods.value.some((m) => String(m.id || '').trim() === active)) {
        postTasks.push(syncActiveModWithServerIndustry())
      }
      if (postTasks.length) {
        await Promise.all(postTasks)
      }
      loadError.value = null
      void fetchPlatformShellCapabilities(true).catch((e) => console.warn('[mods] platform-shell capabilities:', e))
      await applyModFacadeFlagsFromListing(mods.value, activeModId.value)
      applyEditionPackPlatformShell(mods.value.map((m) => String(m.id || '')))
      if (typeof performance !== 'undefined' && performance.mark) {
        performance.mark('mods_list_ok')
      }
      return { ok: true }
    } catch (error) {
      if (isApiFetchTimeoutError(error)) {
        loadError.value = 'Mod 列表请求超时，请确认后端已启动'
        console.warn('[mods] /api/mods/ 超时:', error)
        return { ok: false, transportError: true }
      }
      console.error('Failed to fetch mods:', error)
      const raw = error instanceof Error ? error.message : '网络错误'
      const looksLikeTransport =
        raw === 'Failed to fetch' || /networkerror|load failed/i.test(raw) || /socket|ecconn|econnrefused|aborted/i.test(raw)
      loadError.value = looksLikeTransport ? '无法连接后端，请检查服务是否启动' : raw
      return { ok: false, transportError: looksLikeTransport }
    }
  }

  async function fetchModsWithRetry(fetchOpts?: FetchModsOptions): Promise<{ ok: boolean; modsDisabled?: boolean }> {
    const desktopFast = typeof window !== 'undefined' && Boolean((window as Window & { xcagiDesktop?: unknown }).xcagiDesktop)
    const retryDelay = (transport: boolean) => (desktopFast ? (transport ? 600 : 150) : transport ? 1200 : 400)
    const emptyRetryDelay = desktopFast ? 250 : 500
    const emptyRetryDelay2 = desktopFast ? 400 : 800

    let r = await fetchModsOnce(fetchOpts)
    if (r.modsDisabled) return r
    if (!r.ok) {
      await delay(retryDelay(Boolean(r.transportError)))
      r = await fetchModsOnce(fetchOpts)
    }
    if (r.modsDisabled) return r
    if (r.ok && mods.value.length === 0) {
      const mismatch = await shouldRetryModsListWhenEmpty()
      if (mismatch) {
        await delay(emptyRetryDelay)
        r = await fetchModsOnce(fetchOpts)
        if (r.modsDisabled) return r
        if (r.ok && mods.value.length === 0) {
          await delay(emptyRetryDelay2)
          r = await fetchModsOnce(fetchOpts)
        }
      }
    }
    return r
  }

  async function fetchModRoutes(): Promise<void> {
    const data = await fetchModRoutesPayloadShared()
    if (data) {
      modRoutes.value = data
    }
  }

  function setClientModsUiOff(off: boolean) {
    clientModsUiOff.value = off
    if (off) {
      mods.value = []
      modRoutes.value = []
      setActiveModId('')
      loadError.value = null
      isLoaded.value = true
    } else {
      // 从原版切回 Mod：必须允许下一轮 initialize 真正拉 /api/mods*（否则 isLoaded 仍为 true 会短路）
      isLoaded.value = false
      mods.value = []
      modRoutes.value = []
      loadError.value = null
    }
    try {
      if (off) {
        localStorage.setItem(CLIENT_MODS_UI_OFF_KEY, '1')
      } else {
        localStorage.removeItem(CLIENT_MODS_UI_OFF_KEY)
      }
    } catch {
      /* private mode */
    }
  }

  async function initialize(force = false, options?: ModsInitializeOptions) {
    pendingInitOptions = options ?? null
    const uname = String(options?.accountUsername || '').trim()
    if (uname) lastInitAccountUsername = uname
    // 同步原版模式状态到后端
    if (clientModsUiOff.value) {
      try {
        const { syncClientModsStateToBackend } = await import('@/utils/apiBase')
        syncClientModsStateToBackend()
      } catch {
        // ignore
      }
    }

    if (clientModsUiOff.value) {
      mods.value = []
      modRoutes.value = []
      setActiveModId('')
      loadError.value = null
      isLoaded.value = true
      return
    }

    // 已标记 loaded 但没有任何 Mod 数据时视为未就绪（例如刚从原版切回、或异常中断）
    if (isLoaded.value && !force) {
      if (mods.value.length > 0 || modRoutes.value.length > 0) return
      isLoaded.value = false
    }

    if (initInFlight) {
      await initInFlight
      // 并发调用：等首轮结束后若仍失败（后端晚于前端启动），再拉一次
      if (!isLoaded.value && !force) {
        await initialize(false)
      }
      return
    }

    initInFlight = (async () => {
      if (clientModsUiOff.value) {
        mods.value = []
        modRoutes.value = []
        setActiveModId('')
        loadError.value = null
        isLoaded.value = true
        return
      }
      if (force) {
        isLoaded.value = false
        resetModFacadeProbes()
      }
      const r = await fetchModsWithRetry()
      await fetchModRoutes()
      if (r.modsDisabled) {
        setActiveModId('')
        isLoaded.value = true
        return
      }
      const ok = r.ok
      if (ok) {
        ensureActiveModSelection()
        if (mods.value.length > 0) {
          isLoaded.value = true
          loadError.value = null
        } else if (await shouldRetryModsListWhenEmpty()) {
          isLoaded.value = false
          const hint = await fetchModLoadingStatusHint()
          loadError.value = hint || '检测到 Mod 目录有扩展但后端未加载成功，请查看后端日志，或稍后刷新页面'
        } else if (await confirmServerReportsZeroDiscoveredMods()) {
          isLoaded.value = true
          loadError.value = null
        } else {
          isLoaded.value = false
          loadError.value = (await fetchModLoadingStatusHint()) || 'Mod 列表为空，且未能确认后端磁盘扫描结果 — 请确认后端已启动后刷新'
        }
      }
      try {
        const { registerAllModRoutesFromGlob, registerModRoutes } = await import('@/router/registerModRoutes')
        const router = (await import('@/router')).default
        await registerAllModRoutesFromGlob(router)
        if (modRoutes.value.length > 0) {
          await registerModRoutes(router, modRoutes.value)
        }
      } catch (e) {
        console.warn('[mods] registerModRoutes after initialize failed:', e)
      }
    })()

    try {
      await initInFlight
    } finally {
      initInFlight = null
      pendingInitOptions = null
    }
  }

  /** 强制重新拉取（后端晚于前端启动时可调用） */
  async function refresh() {
    await initialize(true)
  }

  return {
    mods,
    modsForUi,
    modsForWorkflowUi,
    modRoutes,
    activeModId,
    clientModsUiOff,
    setActiveModId,
    reloadActiveModForTenantScope,
    setClientModsUiOff,
    isLoaded,
    loadError,
    fetchMods: fetchModsWithRetry,
    fetchModRoutes,
    getModMenu: menu.getModMenu,
    initialize,
    refresh,
    applyLoadingStatusPreview,
    syncActiveModWithServerIndustry,
    applyEntitledActiveMod,
  }
})
