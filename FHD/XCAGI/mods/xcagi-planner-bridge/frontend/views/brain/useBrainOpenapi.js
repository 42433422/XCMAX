import { computed, ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'

/** OpenAPI 目录加载与过滤（拆分自 BrainView.vue，逻辑不变） */
export function useBrainOpenapi({ pushActivity }) {
  const openapiSpec = ref(null)
  const openapiLoading = ref(true)
  const openapiError = ref('')
  const apiFilter = ref('')
  const openapiLoadedAt = ref('')

  const openapiTitle = computed(() => {
    const s = openapiSpec.value
    if (!s || typeof s !== 'object') return ''
    const t = s.info && s.info.title
    return typeof t === 'string' && t.trim() ? t.trim() : 'OpenAPI'
  })

  const flatOperations = computed(() => {
    const spec = openapiSpec.value
    if (!spec || typeof spec !== 'object' || !spec.paths || typeof spec.paths !== 'object') {
      return []
    }
    const methods = ['get', 'post', 'put', 'patch', 'delete', 'options', 'head']
    const rows = []
    const pathKeys = Object.keys(spec.paths).sort((a, b) => a.localeCompare(b))
    for (const path of pathKeys) {
      const item = spec.paths[path]
      if (!item || typeof item !== 'object') continue
      for (const m of methods) {
        const op = item[m]
        if (!op || typeof op !== 'object') continue
        const summary =
          (typeof op.summary === 'string' && op.summary.trim()) ||
          (typeof op.operationId === 'string' && op.operationId.trim()) ||
          '—'
        rows.push({
          path,
          method: String(m).toUpperCase(),
          summary
        })
      }
    }
    return rows
  })

  const filteredOperations = computed(() => {
    const q = apiFilter.value.trim().toLowerCase()
    if (!q) return flatOperations.value
    return flatOperations.value.filter(
      (r) =>
        r.path.toLowerCase().includes(q) ||
        r.method.toLowerCase().includes(q) ||
        String(r.summary).toLowerCase().includes(q)
    )
  })

  async function loadOpenapi() {
    openapiLoading.value = true
    openapiError.value = ''
    try {
      const res = await apiFetch('/api/system/openapi')
      if (!res.ok) {
        openapiError.value = `加载失败（HTTP ${res.status}）`
        openapiSpec.value = null
        pushActivity(`OpenAPI 加载失败 HTTP ${res.status}`)
        return
      }
      const data = await res.json()
      if (!data || typeof data !== 'object' || typeof data.paths !== 'object') {
        openapiError.value = '返回体不是有效的 OpenAPI JSON'
        openapiSpec.value = null
        pushActivity('OpenAPI 返回格式无效')
        return
      }
      openapiSpec.value = data
      const pathCount = Object.keys(data.paths || {}).length
      pushActivity(`OpenAPI 已加载（paths ${pathCount}）`)
      const now = new Date()
      openapiLoadedAt.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
    } catch (e) {
      openapiError.value =
        e instanceof Error ? e.message : '网络错误，无法拉取 OpenAPI'
      openapiSpec.value = null
      pushActivity('OpenAPI 请求异常')
    } finally {
      openapiLoading.value = false
    }
  }

  return {
    openapiSpec,
    openapiLoading,
    openapiError,
    apiFilter,
    openapiLoadedAt,
    openapiTitle,
    filteredOperations,
    loadOpenapi,
  }
}
