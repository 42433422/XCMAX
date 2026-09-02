import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { ModCatalogItemUi } from '@/api/modStore'

/** 市场目录行：ModCatalogItemUi + 视图字段（icon / new_version / config） */
export type StoreModRow = ModCatalogItemUi & {
  icon?: string
  new_version?: string
  config?: { host_foundation_pack?: boolean }
}

export interface ModStoreState {
  allMods: Ref<StoreModRow[]>
  filteredMods: Ref<StoreModRow[]>
  searchQuery: Ref<string>
  filterInstalled: Ref<boolean>
  sortBy: Ref<string>
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
