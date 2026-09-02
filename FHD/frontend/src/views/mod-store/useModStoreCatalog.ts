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

/** 目录域（由 ModStore.vue 机械切出，行为不变）：分类查询、缓存预热、加载/搜索/筛选/切页 */
export function useModStoreCatalog(state: ModStoreState): ModStoreCatalog {
  const {
    allMods,
    filteredMods,
    searchQuery,
    filterInstalled,
    sortBy,
    currentTab,
    loading,
    refreshing,
    fromCache,
    loadError,
    catalogSnapshot,
  } = state

  const storeNavTabs = [
    { id: 'all', label: '全部商品', icon: 'fa-th-large' },
    { id: 'host_foundation', label: '宿主基础员工', icon: 'fa-cubes' },
    { id: 'office', label: '办公员工包', icon: 'fa-file-text-o' },
    { id: 'office_aux', label: '办公员工附属包1', icon: 'fa-bar-chart' },
    { id: 'workflow', label: '工作流员工', icon: 'fa-users' },
    { id: 'ai_employee', label: 'AI 员工', icon: 'fa-user-circle' },
    { id: 'industry_mod', label: '行业扩展', icon: 'fa-industry' },
    { id: 'installed', label: '已安装', icon: 'fa-check-circle' },
  ]

  const MARKET_TAB_QUERY: Record<string, { collection?: string; artifact?: string; material_category?: string }> = {
    host_foundation: {
      collection: 'host_foundation',
      artifact: 'employee_pack',
      material_category: 'ai_employee',
    },
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
      collection: STORE_COLLECTION_WORKFLOW_EMPLOYEE,
      artifact: 'mod',
      material_category: 'ai_employee',
    },
    ai_employee: {
      material_category: 'ai_employee',
    },
  }

  const isMarketCollectionTab = (tab: string): boolean => Boolean(MARKET_TAB_QUERY[tab])

  const mainListTitle = computed(() => {
    if (currentTab.value === 'host_foundation') return '宿主基础能力（预装员工）'
    if (currentTab.value === 'office') return '办公员工包'
    if (currentTab.value === 'office_aux') return '办公员工附属包1'
    if (currentTab.value === 'workflow') return '工作流员工'
    if (currentTab.value === 'ai_employee') return 'AI 员工'
    if (currentTab.value === 'industry_mod') return '行业扩展'
    if (currentTab.value === 'installed') return '已安装'
    return '全部商品'
  })

  const refineMarketItems = (items: StoreModRow[], tab: string): StoreModRow[] => {
    if (tab === 'office') {
      return items.filter((m) => isOfficeEmployeePkg(m.pkg_id || m.id))
    }
    if (tab === 'office_aux') {
      return items.filter((m) => isOfficeAuxPack1Pkg(m.pkg_id || m.id))
    }
    return items
  }

  const filterByCollectionTab = (mods: StoreModRow[]): StoreModRow[] => {
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
    if (currentTab.value === 'ai_employee') {
      return mods.filter((m) => {
        const sc = catalogStoreCollection(m)
        return sc !== STORE_COLLECTION_INDUSTRY_MOD
      })
    }
    if (currentTab.value === 'industry_mod') {
      return mods.filter((m) => catalogStoreCollection(m) === STORE_COLLECTION_INDUSTRY_MOD)
    }
    return mods
  }

  const loadCatalogAvailable = async (): Promise<StoreModRow[]> => {
    const response = await apiFetch('/api/mod-store/catalog', { timeoutMs: 90_000 })
    const data = await response.json()
    if (!data.success) {
      throw new Error(data.message || data.error || '获取本地目录失败')
    }
    const rows = data.data.available || []
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

  const applyCatalogWarmStart = (tab: string): boolean => {
    if (!catalogSnapshot.value.length) return false
    const warmed = refineMarketItems(filterByCollectionTab([...catalogSnapshot.value]), tab)
    if (!warmed.length) return false
    allMods.value = warmed
    applyFilters()
    if (filteredMods.value.length > 0) {
      loading.value = false
      refreshing.value = true
      return true
    }
    return false
  }

  const fetchMarketTabRemote = async (tab: string): Promise<boolean> => {
    const query = MARKET_TAB_QUERY[tab]
    if (!query) return false
    const result = await fetchMarketCatalog({
      ...query,
      q: searchQuery.value.trim() || undefined,
      limit: 80,
    })
    const items = refineMarketItems(result.items || [], tab)
    allMods.value = items
    writeMarketCatalogCache(buildMarketCatalogCacheKey(tab, searchQuery.value), tab, items)
    fromCache.value = false
    loadError.value = ''
    return true
  }

  const loadMarketTab = async (tab: string, { force = false } = {}): Promise<boolean> => {
    const cacheKey = buildMarketCatalogCacheKey(tab, searchQuery.value)
    const cached = !force ? readMarketCatalogCache(cacheKey) : null

    if (cached?.items?.length) {
      allMods.value = cached.items
      applyFilters()
      fromCache.value = true
      if (isMarketCatalogCacheFresh(cached) && !force) {
        loadError.value = ''
        return true
      }
    } else {
      fromCache.value = false
      await warmCatalogSnapshot()
      applyCatalogWarmStart(tab)
    }

    try {
      return await fetchMarketTabRemote(tab)
    } catch (error) {
      console.warn('[ModStore] market-catalog failed, fallback to /catalog:', error)
      try {
        await loadCatalogAvailable()
        allMods.value = refineMarketItems(filterByCollectionTab([...catalogSnapshot.value]), tab)
        if (allMods.value.length) {
          loadError.value = '市场分类接口较慢或暂不可用，已显示本地目录。可点「刷新目录」重试。'
          return true
        }
        throw error
      } catch (fallbackError) {
        if (filteredMods.value.length) {
          loadError.value = '市场同步失败，当前为缓存/本地目录。可点「刷新目录」重试。'
          return true
        }
        loadError.value = productErrorMessage(error ?? fallbackError, '加载市场目录失败，请检查网络后刷新。')
        allMods.value = []
        return false
      }
    }
  }

  const loadMods = async (force = false): Promise<void> => {
    const tab = currentTab.value
    const cacheKey = buildMarketCatalogCacheKey(tab, searchQuery.value)
    const cached = !force && isMarketCollectionTab(tab) ? readMarketCatalogCache(cacheKey) : null
    const canShowInstant = Boolean(cached?.items?.length) || catalogSnapshot.value.length

    loading.value = !canShowInstant
    refreshing.value = canShowInstant as unknown as boolean
    loadError.value = ''
    if (force) fromCache.value = false

    try {
      if (isMarketCollectionTab(tab)) {
        await loadMarketTab(tab, { force })
        applyFilters()
        return
      }

      const response = await apiFetch('/api/mod-store/catalog', { timeoutMs: 90_000 })
      const data = await response.json()

      if (data.success) {
        catalogSnapshot.value = data.data.available || []
        allMods.value = catalogSnapshot.value
        applyFilters()
      }
    } catch (error) {
      console.error('Failed to load mods:', error)
      if (!filteredMods.value.length) {
        loadError.value = error instanceof Error ? error.message : '加载目录失败'
      }
    } finally {
      loading.value = false
      refreshing.value = false
    }
  }

  const searchMods = async (): Promise<void> => {
    loading.value = true
    refreshing.value = false
    try {
      const tab = currentTab.value
      if (isMarketCollectionTab(tab)) {
        await loadMarketTab(tab, { force: true })
        applyFilters()
        return
      }

      if (!searchQuery.value.trim()) {
        await loadMods()
        return
      }

      const params = new URLSearchParams({
        q: searchQuery.value,
        installed: filterInstalled.value,
        limit: 50,
      } as unknown as Record<string, string>)

      const response = await apiFetch(`/api/mod-store/search?${params}`)
      const data = await response.json()

      if (data.success) {
        allMods.value = data.data || []
        applyFilters()
      }
    } catch (error) {
      console.error('Search failed:', error)
    } finally {
      loading.value = false
    }
  }

  const switchTab = async (tab: string): Promise<void> => {
    currentTab.value = tab
    const cacheKey = buildMarketCatalogCacheKey(tab, searchQuery.value)
    const cached = isMarketCollectionTab(tab) ? readMarketCatalogCache(cacheKey) : null
    const instant = Boolean(cached?.items?.length)
    loading.value = !instant
    refreshing.value = instant

    try {
      if (tab !== 'installed') {
        filterInstalled.value = false
      }
      if (tab === 'installed') {
        filterInstalled.value = true
        if (!allMods.value.length) {
          await loadMods(false)
        } else {
          const response = await apiFetch('/api/mod-store/catalog', { timeoutMs: 90_000 })
          const data = await response.json()
          if (data.success) {
            catalogSnapshot.value = data.data.available || []
            allMods.value = catalogSnapshot.value
          }
        }
        applyFilters()
      } else {
        await loadMods(false)
      }
    } catch (error) {
      console.error('Failed to switch tab:', error)
    } finally {
      loading.value = false
      refreshing.value = false
    }
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
