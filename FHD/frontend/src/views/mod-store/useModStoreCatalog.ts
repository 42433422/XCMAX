import { computed } from 'vue'
import type { ComputedRef } from 'vue'
import { apiFetch } from '@/utils/apiBase'
import { fetchMarketCatalog } from '@/api/modStore'
import {
  catalogStoreCollection,
  STORE_COLLECTION_HOST_FOUNDATION,
  STORE_COLLECTION_INDUSTRY_MOD,
  STORE_COLLECTION_WORKFLOW_EMPLOYEE,
} from '@/constants/genericModPack'
import {
  isOfficeAuxPack1Pkg,
  isOfficeEmployeePkg,
  OFFICE_AUX_PACK_1_COLLECTION,
  OFFICE_EMPLOYEE_COLLECTION,
} from '@/constants/officeEmployeePack'
import {
  buildMarketCatalogCacheKey,
  isMarketCatalogCacheFresh,
  readMarketCatalogCache,
  writeMarketCatalogCache,
} from '@/utils/marketCatalogCache'
import { productErrorMessage } from '@/utils/productErrorMessage'
import type { ModStoreState, StoreModRow } from './useModStoreState'
import { marketItemType } from './useModStoreState'

export interface ModStoreCatalog {
  storeNavTabs: Array<{ id: string; label: string; icon: string }>
  MARKET_TAB_QUERY: Record<string, { collection?: string; artifact?: string; material_category?: string }>
  isMarketCollectionTab: (tab: string) => boolean
  mainListTitle: ComputedRef<string>
  refineMarketItems: (items: StoreModRow[], tab: string) => StoreModRow[]
  filterByCollectionTab: (mods: StoreModRow[]) => StoreModRow[]
  loadCatalogAvailable: () => Promise<StoreModRow[]>
  warmCatalogSnapshot: () => Promise<StoreModRow[]>
  loadMods: (force?: boolean) => Promise<void>
  searchMods: () => Promise<void>
  applyFilters: () => void
  switchTab: (tab: string) => Promise<void>
}

/** AI 市场复用现有可安装目录，按模块/员工分类并保护异步查询切换。 */
export function useModStoreCatalog(state: ModStoreState): ModStoreCatalog {
  const {
    allMods,
    filteredMods,
    searchQuery,
    filterInstalled,
    sortBy,
    marketType,
    currentTab,
    loading,
    refreshing,
    fromCache,
    loadError,
    catalogSnapshot,
  } = state

  const storeNavTabs = [
    { id: 'all', label: '全部员工', icon: 'fa-th-large' },
    { id: 'host_foundation', label: '宿主基础员工', icon: 'fa-cubes' },
    { id: 'office', label: '办公员工包', icon: 'fa-file-text-o' },
    { id: 'office_aux', label: '办公员工附属包1', icon: 'fa-bar-chart' },
    { id: 'workflow', label: '工作流员工', icon: 'fa-users' },
    { id: 'ai_employee', label: 'AI 员工', icon: 'fa-user-circle' },
    { id: 'industry_mod', label: '行业扩展', icon: 'fa-industry' },
    { id: 'installed', label: '已安装', icon: 'fa-check-circle' },
  ]

  // 宿主基础员工是随包预装的本地包，市场没有该分类；留在本地目录查询，否则该页永远为空。
  const MARKET_TAB_QUERY: Record<string, { collection?: string; artifact?: string; material_category?: string }> = {
    office: {
      collection: OFFICE_EMPLOYEE_COLLECTION,
      artifact: 'employee_pack',
      material_category: 'ai_employee',
    },
    office_aux: {
      collection: OFFICE_AUX_PACK_1_COLLECTION,
      artifact: 'employee_pack',
      material_category: 'ai_employee',
    },
    workflow: {
      // 市场不支持按 collection 过滤（传了会返回空），先按 AI 员工拉全量再本地按 collection 精筛。
      material_category: 'ai_employee',
    },
    ai_employee: {
      material_category: 'ai_employee',
    },
  }

  const isMarketCollectionTab = (tab: string): boolean => Boolean(MARKET_TAB_QUERY[tab])

  const mainListTitle = computed(() => {
    if (marketType.value === 'module') return currentTab.value === 'installed' ? '已安装模块' : '业务模块'
    if (currentTab.value === 'host_foundation') return '宿主基础能力（预装员工）'
    if (currentTab.value === 'office') return '办公员工包'
    if (currentTab.value === 'office_aux') return '办公员工附属包1'
    if (currentTab.value === 'workflow') return '工作流员工'
    if (currentTab.value === 'ai_employee') return 'AI 员工'
    if (currentTab.value === 'industry_mod') return '行业扩展'
    if (currentTab.value === 'installed') return '已安装'
    return '全部员工'
  })

  const refineMarketItems = (items: StoreModRow[], tab: string): StoreModRow[] => {
    items = items.filter((item) => marketItemType(item) === marketType.value)
    if (tab === 'workflow') {
      return items.filter((m) => catalogStoreCollection(m) === STORE_COLLECTION_WORKFLOW_EMPLOYEE)
    }
    if (tab === 'office') {
      return items.filter((m) => isOfficeEmployeePkg(m.pkg_id || m.id))
    }
    if (tab === 'office_aux') {
      return items.filter((m) => isOfficeAuxPack1Pkg(m.pkg_id || m.id))
    }
    return items
  }

  const filterByCollectionTab = (mods: StoreModRow[]): StoreModRow[] => {
    mods = mods.filter((item) => marketItemType(item) === marketType.value)
    if (currentTab.value === 'host_foundation') {
      return mods.filter((m) => catalogStoreCollection(m) === STORE_COLLECTION_HOST_FOUNDATION)
    }
    if (currentTab.value === 'office') {
      return mods.filter((m) => isOfficeEmployeePkg(m.pkg_id || m.id))
    }
    if (currentTab.value === 'office_aux') {
      return mods.filter((m) => isOfficeAuxPack1Pkg(m.pkg_id || m.id))
    }
    if (currentTab.value === 'workflow') {
      return mods.filter((m) => catalogStoreCollection(m) === STORE_COLLECTION_WORKFLOW_EMPLOYEE)
    }
    if (currentTab.value === 'industry_mod') {
      return mods.filter((m) => catalogStoreCollection(m) === STORE_COLLECTION_INDUSTRY_MOD)
    }
    return mods
  }

  const requestCatalogAvailable = async (): Promise<StoreModRow[]> => {
    const response = await apiFetch('/api/mod-store/catalog', { timeoutMs: 90_000 })
    const data = await response.json()
    if (!data.success) {
      throw new Error(data.message || data.error || '获取本地目录失败')
    }
    return data.data.available || []
  }

  const loadCatalogAvailable = async (): Promise<StoreModRow[]> => {
    const rows = await requestCatalogAvailable()
    catalogSnapshot.value = rows
    return rows
  }

  let catalogSnapshotPromise: Promise<StoreModRow[]> | null = null

  const warmCatalogSnapshot = (): Promise<StoreModRow[]> => {
    if (catalogSnapshot.value.length) {
      return Promise.resolve(catalogSnapshot.value)
    }
    if (!catalogSnapshotPromise) {
      catalogSnapshotPromise = loadCatalogAvailable().catch((err) => {
        catalogSnapshotPromise = null
        console.warn('[ModStore] catalog snapshot prefetch failed:', err)
        return []
      })
    }
    return catalogSnapshotPromise
  }

  const applyFilters = () => {
    let mods = [...allMods.value]

    if (filterInstalled.value) {
      mods = mods.filter((mod) => mod.is_installed)
    }

    mods = filterByCollectionTab(mods)

    if (sortBy.value === 'downloads') {
      mods.sort((a, b) => (b.total_downloads || b.download_count || 0) - (a.total_downloads || a.download_count || 0))
    } else if (sortBy.value === 'rating') {
      mods.sort((a, b) => (b.avg_rating || 0) - (a.avg_rating || 0))
    } else if (sortBy.value === 'created_at') {
      mods.sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime())
    } else {
      mods.sort((a, b) => (a.name || '').localeCompare(b.name || ''))
    }

    filteredMods.value = mods
  }

  // A late response from another type, category or search must never replace this view.
  let requestVersion = 0
  let activeQueryKey = ''
  const loadMods = async (force = false): Promise<void> => {
    const version = ++requestVersion
    const tab = currentTab.value
    const type = marketType.value
    const query = searchQuery.value.trim()
    const current = () => version === requestVersion && tab === currentTab.value && type === marketType.value
    const marketQuery = type === 'employee' ? MARKET_TAB_QUERY[tab] : undefined
    const cacheKey = buildMarketCatalogCacheKey(tab, query)
    const queryKey = `${type}:${cacheKey}`
    if (activeQueryKey !== queryKey) {
      allMods.value = []
      filteredMods.value = []
      activeQueryKey = queryKey
    }
    const cached = !force && marketQuery ? readMarketCatalogCache(cacheKey) : null
    loadError.value = ''
    fromCache.value = false

    if (cached?.items?.length) {
      allMods.value = refineMarketItems(cached.items, tab)
      applyFilters()
      fromCache.value = true
      if (isMarketCatalogCacheFresh(cached)) {
        loading.value = refreshing.value = false
        return
      }
    } else if (marketQuery && !query && catalogSnapshot.value.length) {
      allMods.value = refineMarketItems(filterByCollectionTab(catalogSnapshot.value), tab)
      applyFilters()
    }
    loading.value = !filteredMods.value.length
    refreshing.value = Boolean(filteredMods.value.length)

    try {
      if (marketQuery) {
        const result = await fetchMarketCatalog({ ...marketQuery, q: query || undefined, limit: 200 })
        if (!current()) return
        allMods.value = refineMarketItems(result.items || [], tab)
        writeMarketCatalogCache(cacheKey, tab, allMods.value)
      } else {
        // Filter the complete combined directory; /search caps mixed matches before classification.
        const rows = await requestCatalogAvailable()
        if (!current()) return
        catalogSnapshot.value = rows
        const needle = query.toLowerCase()
        allMods.value = refineMarketItems(rows, tab).filter((item) =>
          !needle || [item.name, item.id, item.description].some((field) => String(field || '').toLowerCase().includes(needle)))
      }
      fromCache.value = false
      applyFilters()
    } catch (error) {
      if (!current()) return
      if (marketQuery) {
        try {
          const rows = await loadCatalogAvailable()
          if (!current()) return
          const matches = refineMarketItems(filterByCollectionTab(rows), tab).filter((item) =>
            !query || [item.name, item.description, item.pkg_id].join(' ').toLowerCase().includes(query.toLowerCase()))
          if (matches.length) {
            allMods.value = matches
            applyFilters()
            loadError.value = '市场分类接口较慢或暂不可用，已显示本地目录。可点「刷新目录」重试。'
            return
          }
        } catch { /* The original remote error remains the actionable failure. */ }
      }
      if (!current()) return
      if (marketQuery && filteredMods.value.length) {
        loadError.value = '市场同步失败，当前为缓存/本地目录。可点「刷新目录」重试。'
      } else if (!filteredMods.value.length) {
        loadError.value = productErrorMessage(error, '加载市场目录失败，请检查网络后刷新。')
      }
    } finally {
      if (current()) loading.value = refreshing.value = false
    }
  }

  const searchMods = (): Promise<void> => loadMods(true)

  const switchTab = async (tab: string): Promise<void> => {
    // Resolve caller input to a fixed navigation ID before loading or caching.
    currentTab.value = storeNavTabs.find(entry => entry.id === tab)?.id ?? 'host_foundation'
    filterInstalled.value = currentTab.value === 'installed'
    allMods.value = []
    filteredMods.value = []
    await loadMods(false)
  }

  return {
    storeNavTabs,
    MARKET_TAB_QUERY,
    isMarketCollectionTab,
    mainListTitle,
    refineMarketItems,
    filterByCollectionTab,
    loadCatalogAvailable,
    warmCatalogSnapshot,
    loadMods,
    searchMods,
    applyFilters,
    switchTab,
  }
}
