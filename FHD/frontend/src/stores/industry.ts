import { defineStore } from 'pinia'
import { ref, computed, readonly } from 'vue'
import { systemApi } from '@/api/system'
import { useModsStore } from '@/stores/mods'
import { DEFAULT_INDUSTRY_ID } from '@/constants/industryDefaults'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { asRecord, asArray, asString } from '@/utils/typeGuards'

interface Industry {
  id: number | string;
  name: string;
  code: string;
  description?: string;
  config?: unknown;
  [key: string]: unknown;
}

export const useIndustryStore = defineStore('industry', () => {
  const industries = ref<Industry[]>([])
  const currentIndustry = ref<Industry | null>(null)
  const currentConfig = ref<unknown>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  // Phase 2 会通过 templatePreviewApi.getTermRules 填充；Phase 1 先留空。
  const termRules = ref<Record<string, unknown>>({})
  let initInFlight: Promise<void> | null = null

  const currentIndustryName = computed(() => {
    return currentIndustry.value?.name || '未知'
  })

  const currentIndustryId = computed(() => {
    // 管理端（admin-console）使用专属「管理端」预设，不套用企业端当前行业（如考勤）
    if (isAdminConsoleSpa()) return '管理端'
    return currentIndustry.value?.id?.toString() || DEFAULT_INDUSTRY_ID
  })

  const primaryUnit = computed(() => {
    const units = asRecord(asRecord(currentConfig.value).units)
    return asString(units.primary, '天')
  })

  const primaryLabel = computed(() => {
    const qf = asRecord(asRecord(currentConfig.value).quantity_fields)
    return asString(qf.primary_label, '出勤天数')
  })

  const isLoaded = computed(() => {
    return currentIndustry.value !== null
  })

  /** 从 modsStore 当前选中的 mod 取 manifest.industry，找不到时返回 null */
  function activeModIndustryConfig(): Record<string, unknown> | null {
    try {
      const modsStore = useModsStore()
      const activeId = String(modsStore.activeModId || '').trim()
      const list = Array.isArray(modsStore.mods) ? modsStore.mods : []
      const exact = activeId
        ? list.find((m: unknown) => String(asRecord(m).id || '').trim() === activeId)
        : null
      const candidate = exact || list[0] || null
      const ind = candidate ? asRecord(asRecord(candidate).industry) : {}
      return Object.keys(ind).length ? ind : null
    } catch {
      return null
    }
  }

  async function loadIndustries() {
    loading.value = true
    error.value = null

    try {
      const response = await systemApi.getIndustries()
      if (response.success && response.data) {
        industries.value = asArray<Industry>(asRecord(response.data).industries)
      } else {
        industries.value = []
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载行业列表失败'
      console.error('Failed to load industries:', err)
      industries.value = []
    } finally {
      loading.value = false
    }
  }

  async function loadCurrentIndustry() {
    loading.value = true
    error.value = null

    try {
      const response = await systemApi.getCurrentIndustry()
      if (response.success && response.data) {
        currentIndustry.value = response.data as Industry
        currentConfig.value = response.data
      } else {
        // server 没给当前行业时，用当前 active mod 的 manifest.industry 兜底，
        // 让 primaryUnit / intent_keywords 至少能跟着 mod 选择走。
        const modInd = activeModIndustryConfig()
        if (modInd) {
          const id = String(modInd.id || '').trim()
          if (id) {
            const fallback: Industry = {
              id,
              name: String(modInd.name || id),
              code: id,
              description: typeof modInd.description === 'string' ? modInd.description : '',
              config: modInd,
              ...modInd,
            }
            currentIndustry.value = fallback
            currentConfig.value = fallback
          }
        }
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : '加载当前行业失败'
      console.error('Failed to load current industry:', err)
      const modInd = activeModIndustryConfig()
      if (modInd) {
        const id = String(modInd.id || '').trim()
        if (id) {
          const fallback: Industry = {
            id,
            name: String(modInd.name || id),
            code: id,
            description: typeof modInd.description === 'string' ? modInd.description : '',
            config: modInd,
            ...modInd,
          }
          currentIndustry.value = fallback
          currentConfig.value = fallback
        }
      }
    } finally {
      loading.value = false
    }
  }

  /**
   * 只读从 server 加载行业 SSOT：同时拉取行业列表与当前行业。
   * Phase 1 不再写入 server（switchIndustry 已删除）；Phase 2 会扩展 termRules。
   */
  async function loadFromServer(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      await Promise.all([loadIndustries(), loadCurrentIndustry()])
    } catch (err) {
      error.value = err instanceof Error ? err.message : '从服务器加载行业失败'
      console.error('Failed to load industry from server:', err)
    } finally {
      loading.value = false
    }
  }

  async function initialize(force = false) {
    if (isLoaded.value && !force) {
      return
    }
    if (initInFlight) {
      await initInFlight
      return
    }
    initInFlight = (async () => {
      await loadIndustries()
      await loadCurrentIndustry()
    })()
    try {
      await initInFlight
    } finally {
      initInFlight = null
    }
  }

  function getIndustryById(id: number | string): Industry | null {
    return industries.value.find(ind => ind.id === id) || null
  }

  return {
    industries,
    // 只读暴露：SSOT 行业只能由 loadFromServer / loadCurrentIndustry 从 server 拉取后写入，
    // 组件层不可直接赋值（switchIndustry 已删除）。
    currentIndustry: readonly(currentIndustry),
    currentConfig,
    loading,
    error,
    termRules,
    currentIndustryName,
    currentIndustryId,
    primaryUnit,
    primaryLabel,
    isLoaded,
    loadIndustries,
    loadCurrentIndustry,
    loadFromServer,
    initialize,
    getIndustryById
  }
})

export default useIndustryStore
