import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { ModCatalogItemUi } from '@/api/modStore'
import {
  catalogStoreCollection,
  isEmployeePackListingModId,
  STORE_COLLECTION_HOST_FOUNDATION,
  STORE_COLLECTION_INDUSTRY_MOD,
  STORE_COLLECTION_OFFICE_AUX,
  STORE_COLLECTION_OFFICE_EMPLOYEE,
  STORE_COLLECTION_WORKFLOW_EMPLOYEE,
} from '@/constants/genericModPack'

/** 市场目录行：ModCatalogItemUi + 视图字段（icon / new_version / config） */
export type StoreModRow = ModCatalogItemUi & {
  icon?: string
  new_version?: string
  config?: { host_foundation_pack?: boolean }
}

export type MarketType = 'module' | 'employee'

/** Local installed rows can lack artifact metadata; retain the existing employee collection/ID taxonomy. */
export function marketItemType(mod?: StoreModRow | null): MarketType | null {
  if (!mod) return null
  const artifact = String(mod.artifact || '').trim().toLowerCase()
  if (!['', 'mod', 'bundle', 'employee_pack'].includes(artifact)) return null
  if (artifact === 'employee_pack') return 'employee'
  const collection = catalogStoreCollection(mod)
  if ([STORE_COLLECTION_HOST_FOUNDATION, STORE_COLLECTION_OFFICE_EMPLOYEE, STORE_COLLECTION_OFFICE_AUX,
    STORE_COLLECTION_WORKFLOW_EMPLOYEE].includes(collection) || isEmployeePackListingModId(mod.pkg_id || mod.id)) {
    return 'employee'
  }
  return collection === STORE_COLLECTION_INDUSTRY_MOD ? 'module' : null
}

export interface ModStoreState {
  allMods: Ref<StoreModRow[]>
  filteredMods: Ref<StoreModRow[]>
  searchQuery: Ref<string>
  filterInstalled: Ref<boolean>
  sortBy: Ref<string>
  marketType: Ref<MarketType>
  currentTab: Ref<string>
  loading: Ref<boolean>
  refreshing: Ref<boolean>
  fromCache: Ref<boolean>
  loadError: Ref<string>
  catalogSnapshot: Ref<StoreModRow[]>
  selectedMod: Ref<StoreModRow | null>
  deliverableOk: Ref<boolean>
  missingModIds: Ref<string[]>
  bootstrapBusy: Ref<boolean>
  oneClickProgress: Ref<string>
  isMobileViewport: Ref<boolean>
  enterpriseStackLabel: Ref<string>
  missingModHint: ComputedRef<string>
  setupMobileViewport: () => void
  disposeMobileViewport: () => void
}

/** 状态域（由 ModStore.vue 机械切出，行为不变）：全部响应式状态与移动端视口监听 */
export function useModStoreState(): ModStoreState {
  const allMods = ref<StoreModRow[]>([])
  const filteredMods = ref<StoreModRow[]>([])
  const searchQuery = ref('')
  const filterInstalled = ref(false)
  const sortBy = ref('name')
  const marketType = ref<MarketType>('employee')
  const currentTab = ref('all')
  const loading = ref(false)
  const refreshing = ref(false)
  const fromCache = ref(false)
  const loadError = ref('')
  const catalogSnapshot = ref<StoreModRow[]>([])
  const selectedMod = ref<StoreModRow | null>(null)
  const deliverableOk = ref(true)
  const missingModIds = ref<string[]>([])
  const bootstrapBusy = ref(false)
  const oneClickProgress = ref('')
  const isMobileViewport = ref(false)
  const enterpriseStackLabel = ref('')

  const missingModHint = computed(() => (missingModIds.value.length ? missingModIds.value.join(', ') : ''))

  let mobileMedia: MediaQueryList | null = null

  const onMobileViewportChange = (event: MediaQueryList | MediaQueryListEvent) => {
    isMobileViewport.value = event.matches
  }

  const setupMobileViewport = () => {
    mobileMedia = window.matchMedia('(max-width: 768px)')
    onMobileViewportChange(mobileMedia)
    if (typeof mobileMedia.addEventListener === 'function') {
      mobileMedia.addEventListener('change', onMobileViewportChange)
    } else if (typeof mobileMedia.addListener === 'function') {
      mobileMedia.addListener(onMobileViewportChange)
    }
  }

  const disposeMobileViewport = () => {
    if (!mobileMedia) return
    if (typeof mobileMedia.removeEventListener === 'function') {
      mobileMedia.removeEventListener('change', onMobileViewportChange)
    } else if (typeof mobileMedia.removeListener === 'function') {
      mobileMedia.removeListener(onMobileViewportChange)
    }
  }

  return {
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
    selectedMod,
    deliverableOk,
    missingModIds,
    bootstrapBusy,
    oneClickProgress,
    isMobileViewport,
    enterpriseStackLabel,
    missingModHint,
    setupMobileViewport,
    disposeMobileViewport,
  }
}
