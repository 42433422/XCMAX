import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '../api'
import { parseByokPaste } from '../byokEnvImport'
import { requestJson } from '../infrastructure/http/client'
import { LLM_OAI_COMPAT_BASE_URL_PROVIDERS } from '../llmModels'
import {
  classifyLlmCatalogIssue,
  catalogIssueCreditHint,
  hasAnyLlmKey,
  walletTileKeyConfigured,
} from '../llmProviderHealth'
import { llmProviderIconImgSrc } from '../llmIconUrls'
import { confirmDanger } from './useDangerConfirm'
import {
  formatPricingDetail,
  modelOptionLabelWithPricing,
  providerTileMinPriceHint,
} from './useLlmPricingDisplay'
import { providerHasImageCapability, providerHasVideoCapability } from '../llmMedia'
import {
  errorMessage,
  LLM_CATEGORY_ORDER,
  type BareCredentialResponse,
  type LlmStatusRecord,
  type WalletCatalog,
  type WalletCatalogProvider,
  type WalletLlmModelRow,
} from '../views/wallet/walletTypes'

/** WalletView 大模型 API 域：目录拉取 / 厂商磁贴 / 模型选择 / BYOK 密钥（自 WalletView.vue 原样迁移） */
export function useWalletLlm() {
  const catalog = ref<WalletCatalog | null>(null)
  const llmStatusList = ref<LlmStatusRecord[]>([])
  const llmCatalogLoading = ref(false)
  const llmErr = ref('')
  const llmNote = ref('')
  const selectedProvider = ref('openai')
  const selectedModel = ref('')
  const iconLoadFailed = reactive<Record<string, boolean>>({})
  const llmBootstrapped = ref(false)
  const byokKey = reactive<Record<string, string>>({})
  const byokBaseUrl = reactive<Record<string, string>>({})
  const byokSaving = ref('')
  const byokBulkPaste = ref('')
  const byokImportBusy = ref(false)
  const llmProviderFilter = ref('all')

  let _prefTimer: ReturnType<typeof setTimeout> | null = null
  let _catalogInterval: ReturnType<typeof setInterval> | null = null

  const catalogProviderBlocks = computed(() => {
    const providers = catalog.value?.providers
    return Array.isArray(providers) ? providers : []
  })

  const currentProviderBlock = computed(() => {
    return catalogProviderBlocks.value.find((p) => p.provider === selectedProvider.value) || null
  })

  function categoryLabel(cat: string): string {
    return catalog.value?.category_labels?.[cat] || cat
  }

  /** @param {{ id: string, category?: string, capability?: Record<string, unknown>, pricing?: Record<string, unknown> }} row */
  function modelOptionLabel(row: WalletLlmModelRow): string {
    const id = row.id || ''
    const c = row.capability
    const tags: string[] = []
    if (c && typeof c === 'object') {
      if (c.l3_status === 'approved') tags.push('L3已通过')
      else if (c.l3_status === 'pending') tags.push('L3审核中')
      if (c.l1_status === 'ok') tags.push('L1探针通过')
      else if (c.l1_status === 'pending') tags.push('L1待探针')
      if (c.platform_billing_ok === false) tags.push('平台计费受限')
    }
    const base = tags.length ? `${id}（${tags.join('·')}）` : id
    return modelOptionLabelWithPricing(row, base)
  }

  const selectedModelPricingDetail = computed(() => {
    const block = currentProviderBlock.value
    const mid = selectedModel.value
    if (!block || !mid) return ''
    const detailed = block.models_detailed || []
    const row = detailed.find((r) => r.id === mid)
    if (row?.pricing) return formatPricingDetail(row.pricing)
    return ''
  })

  /** @param {{ models_detailed?: Array<{ pricing?: Record<string, unknown> }> }} block */
  function providerTilePriceHint(block: WalletCatalogProvider): string {
    return providerTileMinPriceHint(block?.models_detailed, catalog.value?.billing_settings) || ''
  }

  async function onPricingAdminSaved() {
    llmNote.value = '定价已更新，正在刷新模型目录…'
    await refreshCatalog(true)
  }

  function modelsForCategory(cat: string): WalletLlmModelRow[] {
    const block = currentProviderBlock.value
    const detailed = block?.models_detailed
    if (detailed && detailed.length) {
      return detailed.filter((r) => r.category === cat)
    }
    if (cat === 'llm' && block?.models?.length) {
      return (block.models as string[]).map((id: string) => ({ id, category: 'llm' }))
    }
    return []
  }

  const byokConfiguredCount = computed(() => llmStatusList.value.filter((s) => s.has_user_override).length)

  const byokImportDisabled = computed(() => {
    if (!catalog.value?.fernet_configured) return true
    if (byokImportBusy.value) return true
    if (!(byokBulkPaste.value || '').trim()) return true
    return false
  })

  /** 目录同步元信息（用于工具栏徽章） */
  const catalogSyncMeta = computed(() => {
    if (!catalog.value) return null
    const lines = catalogProviderBlocks.value.map((p) => p.fetched_at).filter(Boolean)
    if (!lines.length) return null
    return {
      fetchedAt: lines[lines.length - 1],
      ttlSec: catalog.value.cache_ttl_seconds ?? 600,
    }
  })

  /** provider id -> /api/llm/status 行 */
  const llmStatusByProvider = computed(() => {
    const m: Record<string, LlmStatusRecord> = {}
    for (const s of llmStatusList.value || []) {
      if (s && s.provider) m[s.provider] = s
    }
    return m
  })

  /** 磁贴顺序：目录与健康检查均为 ok 的厂商靠前（密钥错误、降级列表靠后） */
  const catalogProvidersSorted = computed(() => {
    const blocks = catalogProviderBlocks.value
    if (!blocks.length) return []
    let list = blocks
    if (llmProviderFilter.value === 'image') {
      list = list.filter((b) => providerHasImageCapability(b))
    } else if (llmProviderFilter.value === 'video') {
      list = list.filter((b) => providerHasVideoCapability(b))
    }
    const ordered = list.map((b, idx) => ({
      block: b,
      idx,
      catalogOk: providerTileState(b) === 'ok',
      mediaScore:
        Number(b.media_counts?.image ?? 0) + Number(b.media_counts?.video ?? 0),
    }))
    ordered.sort((a, b) => {
      if (a.catalogOk !== b.catalogOk) return a.catalogOk ? -1 : 1
      if (a.mediaScore !== b.mediaScore) return b.mediaScore - a.mediaScore
      return a.idx - b.idx
    })
    return ordered.map((x) => x.block)
  })

  /** @param {{ media_counts?: Record<string, number>, supports_openai_images?: boolean, models_detailed?: unknown[] }} block */
  function providerTileMediaTags(block: WalletCatalogProvider): Array<{ kind: string; label: string }> {
    const tags: Array<{ kind: string; label: string }> = []
    const imgN = Number(block?.media_counts?.image ?? 0)
    const vidN = Number(block?.media_counts?.video ?? 0)
    if (imgN > 0) tags.push({ kind: 'image', label: `生图 ${imgN}` })
    else if (providerHasImageCapability(block)) tags.push({ kind: 'image', label: '生图' })
    if (vidN > 0) tags.push({ kind: 'video', label: `生视频 ${vidN}` })
    else if (providerHasVideoCapability(block)) tags.push({ kind: 'video', label: '生视频' })
    return tags
  }

  function formatCatalogFetchedAt(iso: string | null | undefined): string {
    if (!iso) return ''
    try {
      const d = new Date(iso)
      if (Number.isNaN(d.getTime())) return String(iso)
      return d.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
    } catch {
      return String(iso)
    }
  }

  /** @param {{ provider: string, label?: string, error?: string|null, fetch_source?: string|null }} block */
  function llmTileShowsImg(block: WalletCatalogProvider): boolean {
    const u = llmProviderIconImgSrc(block.provider)
    if (!u) return false
    return !iconLoadFailed[llmTileIconFailKey(block)]
  }

  /** @param {{ provider: string, label?: string, error?: string|null, fetch_source?: string|null }} block */
  function providerTileState(block: WalletCatalogProvider): string {
    const st = llmStatusByProvider.value[block.provider]
    if (!walletTileKeyConfigured(block.provider, st)) return 'inactive'
    const issue = classifyLlmCatalogIssue(block.error, block.fetch_source)
    if (issue === 'expired') return 'danger'
    if (issue === 'danger') return 'danger'
    if (issue === 'warn') return 'warn'
    return 'ok'
  }

  /** 与图标 URL 联动，避免换色后仍沿用旧失败态 */
  function llmTileIconFailKey(block: WalletCatalogProvider): string {
    return `${block.provider}__${providerTileState(block)}`
  }

  /** @param {{ provider: string, label?: string, error?: string|null, fetch_source?: string|null }} block */
  function providerTileTitle(block: WalletCatalogProvider): string {
    const n = block.label || block.provider
    const st = llmStatusByProvider.value[block.provider]
    const ps = providerTileState(block)
    const keyTag =
      st?.has_user_override === true ? 'BYOK' : st?.has_platform_key ? '平台密钥' : '密钥'
    if (ps === 'inactive') {
      if (
        hasAnyLlmKey(st) &&
        st?.has_platform_key &&
        !st?.has_user_override &&
        block.provider !== 'xiaomi'
      ) {
        return `${n}：服务端已配置该平台的环境变量密钥，模型仍可能可用；磁贴未点亮表示您尚未在下方 BYOK 中保存个人密钥`
      }
      return `${n}：未配置 BYOK 且服务端也未设置该平台的环境变量密钥`
    }
    if (classifyLlmCatalogIssue(block.error, block.fetch_source) === 'expired') {
      return `${n}：${keyTag} 已过期或失效；请删除旧密钥后重新配置`
    }
    if (ps === 'warn') {
      if (String(block.fetch_source || '') === 'static_fallback_merged') {
        return `${n}：${keyTag} 已配置；未从厂商拉到模型列表，当前展示为站内静态兜底 ID，请到「刷新模型列表」或检查密钥与 Base URL`
      }
      return `${n}：${keyTag} 已配置；模型列表拉取降级或限流，请检查网络、额度或稍后重试`
    }
    if (ps === 'danger') {
      const creditHint = catalogIssueCreditHint(block.error)
      const creditClause = creditHint ? ` ${creditHint}` : ''
      return `${n}：${keyTag} 已配置；模型目录或接口不可用（认证失败、配置错误或厂商拒绝）${creditClause}`
    }
    return `${n}：${keyTag} 已配置，模型列表正常`
  }

  /** 与磁贴同源：BYOK 列表行旁是否显示「目录报红」提示 */
  function llmByokCatalogDanger(provider: string): boolean {
    const block = catalogProviderBlocks.value.find((p) => p.provider === provider)
    if (!block) return false
    return providerTileState(block) === 'danger'
  }

  function llmInitials(label: string): string {
    const parts = label.replace(/\s+/g, ' ').trim().split(' ')
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
    return label.slice(0, 2).toUpperCase()
  }

  function syncSelectionFromServerPrefs() {
    if (!catalog.value) return
    const pref = catalog.value.preferences || {}
    const providers = catalogProviderBlocks.value
    let prov = pref.provider || 'openai'
    if (!providers.some((p) => p.provider === prov)) {
      prov = providers[0]?.provider || 'openai'
    }
    selectedProvider.value = prov
    const block = providers.find((p) => p.provider === prov)
    const models = block?.models || []
    let mod = pref.model || ''
    if (!mod || !models.includes(mod)) mod = models[0] || ''
    selectedModel.value = mod
  }

  function validateSelectionAfterRefresh() {
    if (!catalog.value) return
    const block = catalogProviderBlocks.value.find((p) => p.provider === selectedProvider.value)
    if (!block) {
      syncSelectionFromServerPrefs()
      return
    }
    if (!selectedModel.value || !block.models.includes(selectedModel.value)) {
      selectedModel.value = block.models[0] || ''
    }
  }

  async function loadLlmStatus() {
    try {
      const res = await api.llmStatus()
      llmStatusList.value = res.providers || []
    } catch (e: unknown) {
      llmStatusList.value = []
      if (localStorage.getItem('modstore_token')) llmErr.value = errorMessage(e)
    }
  }

  async function loadCatalog(isManualRefresh: boolean): Promise<void> {
    if (!localStorage.getItem('modstore_token')) return
    llmCatalogLoading.value = true
    llmErr.value = ''
    try {
      const res = await api.llmCatalog(isManualRefresh)
      catalog.value = res
      if (!llmBootstrapped.value) {
        syncSelectionFromServerPrefs()
        llmBootstrapped.value = true
      } else if (isManualRefresh) {
        validateSelectionAfterRefresh()
      }
    } catch (e: unknown) {
      llmErr.value = errorMessage(e)
    } finally {
      llmCatalogLoading.value = false
    }
  }

  async function refreshCatalog(isManual: boolean): Promise<void> {
    await Promise.all([loadCatalog(isManual), loadLlmStatus()])
  }

  function selectProvider(id: string): void {
    selectedProvider.value = id
    const block = catalogProviderBlocks.value.find((p) => p.provider === id)
    const models = block?.models || []
    if (!selectedModel.value || !models.includes(selectedModel.value)) {
      selectedModel.value = models[0] || ''
    }
    schedulePersistPreferences()
  }

  function schedulePersistPreferences() {
    if (_prefTimer) clearTimeout(_prefTimer)
    _prefTimer = setTimeout(() => {
      persistPreferences()
    }, 450)
  }

  async function persistPreferences() {
    if (!selectedProvider.value || !selectedModel.value) return
    try {
      await api.llmSavePreferences(selectedProvider.value, selectedModel.value)
      llmNote.value = '已保存默认模型'
      setTimeout(() => {
        if (llmNote.value === '已保存默认模型') llmNote.value = ''
      }, 2000)
    } catch (e: unknown) {
      llmErr.value = errorMessage(e)
    }
  }

  async function saveByok(provider: string): Promise<void> {
    const key = (byokKey[provider] || '').trim()
    if (!key) {
      llmErr.value = '请先粘贴 API Key'
      return
    }
    byokSaving.value = provider
    llmErr.value = ''
    try {
      const base = LLM_OAI_COMPAT_BASE_URL_PROVIDERS.includes(provider)
        ? (byokBaseUrl[provider] || '').trim() || null
        : null
      await api.llmSaveCredentials(provider, key, base)
      byokKey[provider] = ''
      llmNote.value = '已保存 BYOK'
      setTimeout(() => {
        if (llmNote.value === '已保存 BYOK') llmNote.value = ''
      }, 2000)
      await refreshCatalog(false)
    } catch (e: unknown) {
      llmErr.value = errorMessage(e)
    } finally {
      byokSaving.value = ''
    }
  }

  function detectBareCredential(apiKey: string): Promise<BareCredentialResponse> {
    return requestJson('/api/llm/credentials/detect-bare', {
      method: 'POST',
      body: JSON.stringify({ api_key: apiKey }),
    })
  }

  async function importByokBulk() {
    if (byokImportDisabled.value) return
    byokImportBusy.value = true
    llmErr.value = ''
    try {
      const { entries, bareKeys, warnings } = parseByokPaste(byokBulkPaste.value)
      if (!entries.length && !bareKeys.length) {
        llmNote.value = [...warnings].filter(Boolean).join(' ') || '未解析到可保存项'
        return
      }

      const ok: string[] = []
      const fail: string[] = []

      if (entries.length) {
        const settled = await Promise.allSettled(
          entries.map((e) =>
            api.llmSaveCredentials(
              e.provider,
              e.api_key,
              LLM_OAI_COMPAT_BASE_URL_PROVIDERS.includes(e.provider) ? e.base_url || null : null,
            ),
          ),
        )
        settled.forEach((r, i) => {
          const id = entries[i].provider
          if (r.status === 'fulfilled') ok.push(id)
          else {
            const msg = r.reason && typeof r.reason === 'object' && r.reason.message ? r.reason.message : String(r.reason || '失败')
            fail.push(`${id}: ${msg}`)
          }
        })
      }

      const detected: string[] = []
      if (bareKeys.length) {
        const settled = await Promise.allSettled(bareKeys.map((k) => detectBareCredential(k)))
        settled.forEach((r, i) => {
          const tag = `裸密钥#${i + 1}`
          if (r.status === 'fulfilled') {
            const provider = (r.value && r.value.provider) || ''
            if (provider) {
              ok.push(provider)
              detected.push(provider)
            } else {
              fail.push(`${tag}: 后端未返回命中厂商`)
            }
          } else {
            const msg = r.reason && typeof r.reason === 'object' && r.reason.message ? r.reason.message : String(r.reason || '失败')
            fail.push(`${tag}: ${msg}`)
          }
        })
      }

      const parts: string[] = []
      if (ok.length) parts.push(`已保存 ${ok.length} 个：${ok.join('、')}`)
      if (detected.length) parts.push(`自动识别命中：${detected.join('、')}`)
      if (fail.length) parts.push(`失败 ${fail.length}：${fail.join('；')}`)
      if (warnings.length) parts.push(warnings.join(' '))
      llmNote.value = parts.filter(Boolean).join('。') || '完成'
      if (ok.length && !fail.length) byokBulkPaste.value = ''
      await Promise.all([loadLlmStatus(), loadCatalog(false)])
    } catch (e: unknown) {
      llmErr.value = errorMessage(e)
    } finally {
      byokImportBusy.value = false
    }
  }

  async function clearByok(provider: string): Promise<void> {
    const ok = await confirmDanger({
      title: '清除 API 密钥',
      message: `确定清除「${provider}」的 BYOK 配置？清除后该厂商将无法再使用你保存的密钥。`,
      confirmLabel: '清除',
      destructive: true,
    })
    if (!ok) return
    byokSaving.value = provider
    llmErr.value = ''
    try {
      await api.llmDeleteCredentials(provider)
      llmNote.value = '已清除 BYOK'
      await refreshCatalog(false)
    } catch (e: unknown) {
      llmErr.value = errorMessage(e)
    } finally {
      byokSaving.value = ''
    }
  }

  function onVisibilityRefresh() {
    if (document.visibilityState === 'visible' && localStorage.getItem('modstore_token')) {
      refreshCatalog(false)
    }
  }

  onMounted(() => {
    void refreshCatalog(false)
    _catalogInterval = setInterval(() => {
      if (localStorage.getItem('modstore_token')) refreshCatalog(false)
    }, 8 * 60 * 1000)
    document.addEventListener('visibilitychange', onVisibilityRefresh)
  })

  onUnmounted(() => {
    if (_catalogInterval) clearInterval(_catalogInterval)
    document.removeEventListener('visibilitychange', onVisibilityRefresh)
    if (_prefTimer) clearTimeout(_prefTimer)
  })

  watch(selectedProvider, () => {
    schedulePersistPreferences()
  })

  return {
    LLM_CATEGORY_ORDER,
    catalog,
    llmStatusList,
    llmCatalogLoading,
    llmErr,
    llmNote,
    selectedProvider,
    selectedModel,
    iconLoadFailed,
    byokKey,
    byokBaseUrl,
    byokSaving,
    byokBulkPaste,
    byokImportBusy,
    llmProviderFilter,
    catalogProviderBlocks,
    currentProviderBlock,
    categoryLabel,
    modelOptionLabel,
    selectedModelPricingDetail,
    providerTilePriceHint,
    onPricingAdminSaved,
    modelsForCategory,
    byokConfiguredCount,
    byokImportDisabled,
    catalogSyncMeta,
    llmStatusByProvider,
    catalogProvidersSorted,
    // 测试兼容面：既有测试经 wrapper.vm 访问原单文件顶层绑定
    syncSelectionFromServerPrefs,
    validateSelectionAfterRefresh,
    onVisibilityRefresh,
    providerTileMediaTags,
    formatCatalogFetchedAt,
    llmTileShowsImg,
    providerTileState,
    llmTileIconFailKey,
    providerTileTitle,
    llmByokCatalogDanger,
    llmInitials,
    loadLlmStatus,
    loadCatalog,
    refreshCatalog,
    selectProvider,
    schedulePersistPreferences,
    persistPreferences,
    saveByok,
    importByokBulk,
    clearByok,
  }
}

export type WalletLlmApi = ReturnType<typeof useWalletLlm>
