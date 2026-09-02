// 拆分自 AiStoreView.vue：目录加载、导航与筛选逻辑（逻辑逐字迁移，行为不变）。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../api'
import { ApiError } from '../../infrastructure/http/client'
import {
  OFFICE_AUX_PACK_1_COLLECTION,
  OFFICE_AUX_GROUP_ORDER,
  OFFICE_AUX_PACK_1_PKG_IDS,
  OFFICE_EMPLOYEE_COLLECTION,
  OFFICE_EMPLOYEE_PKG_IDS,
  OFFICE_GROUP_LABELS,
  OFFICE_GROUP_ORDER,
  employeePackIconKind,
  isOfficeAuxPack1Pkg,
  isOfficeEmployeePkg,
  type EmployeePackIconKind,
} from '../../constants/officeEmployeePack'
import { WORKFLOW_EMPLOYEE_COLLECTION } from '../../constants/workflowEmployeePack'
import { HOST_FOUNDATION_COLLECTION } from '../../constants/hostFoundationPack'
import type { AiStoreDisplayGroup, AiStoreItem, CatalogFacets, StoreNavId, StoreNavTab } from './aiStoreTypes'

export function useAiStoreCatalog() {
  const loading = ref(true)
  const err = ref('')
  const items = ref<AiStoreItem[]>([])
  const total = ref(0)
  const activeTheme = ref<'host_foundation' | 'office' | 'office_aux' | 'workflow' | ''>('')
  const storeNav = ref<StoreNavId>('all')
  const showAdvancedFilters = ref(false)
  const bundleDownloading = ref(false)
  let suppressFilterWatch = false
  let loadItemsTimer: ReturnType<typeof setTimeout> | null = null
  const route = useRoute()
  const router = useRouter()
  const attachModId = computed(() => String(route.query.attachModId || '').trim())

  const storeNavTabs: StoreNavTab[] = [
    { id: 'all', label: '全部商品', icon: undefined, badge: '' },
    { id: 'host_foundation', label: '宿主基础员工', icon: undefined, badge: '1' },
    { id: 'office', label: '办公员工包', icon: 'office', badge: String(OFFICE_EMPLOYEE_PKG_IDS.length) },
    { id: 'office_aux', label: '办公员工附属包1', icon: 'report', badge: '' },
    { id: 'workflow', label: '工作流员工', icon: undefined, badge: '6' },
    { id: 'ai_employee', label: 'AI 员工', icon: undefined, badge: '' },
  ]

  /** 附属包角标与市场上架数一致（未上架时为 0，不再写死为 1） */
  const officeAuxNavBadge = ref('')

  const storeNavTabsDisplay = computed(() =>
    storeNavTabs.map((tab) =>
      tab.id === 'office_aux' ? { ...tab, badge: officeAuxNavBadge.value } : tab,
    ),
  )

  async function refreshOfficeAuxNavBadge() {
    try {
      const res = await api.catalog(
        '',
        'employee_pack',
        20,
        0,
        '',
        '',
        'ai_employee',
        '',
        false,
        OFFICE_AUX_PACK_1_COLLECTION,
      )
      const list = ((res.items || []) as AiStoreItem[]).filter((it) => isOfficeAuxPack1Pkg(it.pkg_id))
      officeAuxNavBadge.value = String(list.length)
    } catch {
      officeAuxNavBadge.value = '0'
    }
  }

  const mainListTitle = computed(() => {
    if (activeTheme.value === 'host_foundation') return '宿主基础能力（预装员工）'
    if (activeTheme.value === 'office') return '办公员工包'
    if (activeTheme.value === 'office_aux') return '办公员工附属包1'
    if (activeTheme.value === 'workflow') return '工作流员工'
    if (filters.materialCategory === 'ai_employee') return 'AI 员工'
    if (appliedQ.value) return `搜索「${appliedQ.value}」`
    return '全部商品'
  })

  const advancedFilterCount = computed(() => {
    let n = 0
    if (filters.industry) n++
    if (filters.licenseScope) n++
    if (filters.securityLevel) n++
    if (!isPackCollectionNav.value && filters.materialCategory) n++
    if (!isPackCollectionNav.value && filters.artifact) n++
    return n
  })

  const isPackCollectionNav = computed(
    () =>
      storeNav.value === 'office' ||
      storeNav.value === 'office_aux' ||
      storeNav.value === 'workflow' ||
      storeNav.value === 'host_foundation',
  )

  function buildPackGroups(order: EmployeePackIconKind[]) {
    const map = new Map<EmployeePackIconKind, AiStoreItem[]>()
    for (const item of items.value) {
      const kind = employeePackIconKind(item.pkg_id)
      if (!order.includes(kind)) continue
      const list = map.get(kind) || []
      list.push(item)
      map.set(kind, list)
    }
    return order.filter((k) => map.has(k)).map((kind) => ({
      kind,
      title: OFFICE_GROUP_LABELS[kind],
      items: map.get(kind) || [],
    }))
  }

  const officeGroups = computed(() => {
    if (activeTheme.value !== 'office') return []
    return buildPackGroups([...OFFICE_GROUP_ORDER])
  })

  const officeAuxGroups = computed(() => {
    if (activeTheme.value !== 'office_aux') return []
    return buildPackGroups([...OFFICE_AUX_GROUP_ORDER])
  })

  const displayGroups = computed<AiStoreDisplayGroup[]>(() => {
    if (activeTheme.value === 'office' && officeGroups.value.length) {
      return officeGroups.value.map((g) => ({
        key: g.kind,
        title: g.title,
        kind: g.kind,
        items: g.items,
      }))
    }
    if (activeTheme.value === 'office_aux' && officeAuxGroups.value.length) {
      return officeAuxGroups.value.map((g) => ({
        key: g.kind,
        title: g.title,
        kind: g.kind,
        items: g.items,
      }))
    }
    if (activeTheme.value === 'office_aux') {
      return [{ key: 'aux-flat', title: '', kind: 'report' as EmployeePackIconKind, items: items.value }]
    }
    return [{ key: 'all', title: '', kind: undefined, items: items.value }]
  })

  const searchQ = ref('')
  const appliedQ = ref('')
  const facets = ref<CatalogFacets>({ industries: [], artifacts: [], material_categories: [], license_scopes: [], security_levels: [] })

  const filters = reactive({
    industry: '',
    artifact: '',
    materialCategory: '',
    licenseScope: '',
    securityLevel: '',
  })

  const facetIndustries = computed(() => facets.value.industries || [])
  const facetArtifacts = computed(() => facets.value.artifacts || [])
  const facetMaterialCategories = computed(() => facets.value.material_categories || [])
  const facetLicenseScopes = computed(() => facets.value.license_scopes || [])
  const _facetSecurityLevels = computed(() => facets.value.security_levels || [])

  async function loadFacets() {
    try {
      const res = await api.catalogFacets()
      facets.value = {
        industries: res.industries || [],
        artifacts: res.artifacts || [],
        material_categories: res.material_categories || [],
        license_scopes: res.license_scopes || [],
        security_levels: res.security_levels || [],
      }
    } catch {
      facets.value = { industries: [], artifacts: [], material_categories: [], license_scopes: [], security_levels: [] }
    }
  }

  async function loadItems(cacheBust = false) {
    loading.value = true
    err.value = ''
    try {
      const res = await api.catalog(
        appliedQ.value,
        filters.artifact,
        80,
        0,
        filters.industry,
        filters.securityLevel,
        filters.materialCategory,
        filters.licenseScope,
        cacheBust,
        activeTheme.value === 'host_foundation'
          ? HOST_FOUNDATION_COLLECTION
          : activeTheme.value === 'office'
            ? OFFICE_EMPLOYEE_COLLECTION
            : activeTheme.value === 'office_aux'
              ? OFFICE_AUX_PACK_1_COLLECTION
              : activeTheme.value === 'workflow'
                ? WORKFLOW_EMPLOYEE_COLLECTION
                : '',
      )
      let list = ((res.items || []) as AiStoreItem[]).map((it) => ({
        ...it,
        price: Number(it.price ?? 0) || 0,
        favorite_count: Number(it.favorite_count ?? 0) || 0,
        favorited: !!it.favorited,
      }))
      // 服务端未识别 collection 时会退回「全部 ai_employee」；前端按导航再收窄，避免附属包误展示主包 11 件
      if (activeTheme.value === 'office') {
        list = list.filter((it) => isOfficeEmployeePkg(it.pkg_id))
      } else if (activeTheme.value === 'office_aux') {
        list = list.filter((it) => isOfficeAuxPack1Pkg(it.pkg_id))
      }
      items.value = list
      total.value =
        activeTheme.value === 'office' || activeTheme.value === 'office_aux'
          ? list.length
          : (res.total ?? list.length)
      if (activeTheme.value === 'office_aux') {
        officeAuxNavBadge.value = String(list.length)
      }
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 429) {
        err.value = '请求过于频繁，请稍等几秒后刷新页面'
      } else {
        err.value = e instanceof ApiError ? e.message : (e as Error)?.message || String(e)
      }
      items.value = []
      total.value = 0
    } finally {
      loading.value = false
    }
  }

  function setIndustry(v: string) {
    filters.industry = v
  }

  function setArtifact(v: string) {
    filters.artifact = v
  }

  function setMaterialCategory(v: string) {
    filters.materialCategory = v
  }

  function setLicenseScope(v: string) {
    filters.licenseScope = v
  }

  function setSecurityLevel(v: string) {
    filters.securityLevel = v
  }

  function applyFilters() {
    appliedQ.value = searchQ.value.trim()
    loadItems()
  }

  function resetFilters() {
    searchQ.value = ''
    appliedQ.value = ''
    filters.industry = ''
    filters.artifact = ''
    filters.materialCategory = ''
    filters.licenseScope = ''
    filters.securityLevel = ''
    activeTheme.value = ''
    storeNav.value = 'all'
    loadItems()
  }

  function setStoreNav(id: StoreNavId) {
    if (storeNav.value === id && id !== 'all') return
    suppressFilterWatch = true
    storeNav.value = id
    if (id === 'host_foundation') {
      activeTheme.value = 'host_foundation'
      filters.materialCategory = 'ai_employee'
      filters.artifact = 'employee_pack'
      scheduleLoadItems()
      suppressFilterWatch = false
      return
    }
    if (id === 'office') {
      activeTheme.value = 'office'
      filters.materialCategory = 'ai_employee'
      filters.artifact = 'employee_pack'
      scheduleLoadItems()
      suppressFilterWatch = false
      return
    }
    if (id === 'office_aux') {
      activeTheme.value = 'office_aux'
      filters.materialCategory = 'ai_employee'
      filters.artifact = 'employee_pack'
      scheduleLoadItems()
      suppressFilterWatch = false
      return
    }
    if (id === 'workflow') {
      activeTheme.value = 'workflow'
      filters.materialCategory = 'ai_employee'
      filters.artifact = 'mod'
      scheduleLoadItems()
      suppressFilterWatch = false
      return
    }
    activeTheme.value = ''
    if (id === 'ai_employee') {
      filters.materialCategory = 'ai_employee'
      filters.artifact = ''
    } else {
      filters.materialCategory = ''
      filters.artifact = ''
    }
    scheduleLoadItems()
    suppressFilterWatch = false
  }

  function scheduleLoadItems(cacheBust = false) {
    if (loadItemsTimer) clearTimeout(loadItemsTimer)
    loadItemsTimer = setTimeout(() => {
      loadItemsTimer = null
      void loadItems(cacheBust)
    }, 80)
  }

  function _selectOfficeTheme() {
    setStoreNav('office')
  }

  function _clearTheme() {
    setStoreNav('all')
  }

  watch(
    () => [filters.industry, filters.artifact, filters.materialCategory, filters.licenseScope, filters.securityLevel],
    () => {
      if (suppressFilterWatch) return
      scheduleLoadItems()
    },
  )

  onMounted(async () => {
    await loadFacets()
    void refreshOfficeAuxNavBadge()
    const navHint = String(route.query.nav || route.query.collection || '').trim()
    if (
      navHint === 'office_aux' ||
      navHint === 'office_aux_2' ||
      navHint === OFFICE_AUX_PACK_1_COLLECTION ||
      navHint === 'office_employee_aux_pack_2'
    ) {
      setStoreNav('office_aux')
      return
    }
    await loadItems()
  })

  return {
    loading,
    err,
    items,
    total,
    activeTheme,
    storeNav,
    showAdvancedFilters,
    bundleDownloading,
    attachModId,
    storeNavTabs,
    officeAuxNavBadge,
    storeNavTabsDisplay,
    refreshOfficeAuxNavBadge,
    mainListTitle,
    advancedFilterCount,
    isPackCollectionNav,
    officeGroups,
    officeAuxGroups,
    displayGroups,
    searchQ,
    appliedQ,
    facets,
    facetIndustries,
    facetArtifacts,
    facetMaterialCategories,
    facetLicenseScopes,
    _facetSecurityLevels,
    filters,
    route,
    router,
    loadFacets,
    loadItems,
    setIndustry,
    setArtifact,
    setMaterialCategory,
    setLicenseScope,
    setSecurityLevel,
    applyFilters,
    resetFilters,
    setStoreNav,
    scheduleLoadItems,
    _selectOfficeTheme,
    _clearTheme,
  }
}
