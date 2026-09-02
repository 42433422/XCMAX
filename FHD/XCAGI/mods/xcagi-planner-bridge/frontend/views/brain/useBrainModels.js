import { ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'

/** 模型注册元数据（拆分自 BrainView.vue，逻辑不变） */
export function useBrainModels({ pushActivity }) {
  /** GET /api/fhd/ai/models 元数据（无密钥） */
  const publicModels = ref([])
  const modelsLoading = ref(true)
  const modelsError = ref('')

  async function loadPublicModels() {
    modelsLoading.value = true
    modelsError.value = ''
    publicModels.value = []
    try {
      const res = await apiFetch('/api/fhd/ai/models')
      if (!res.ok) {
        modelsError.value = `HTTP ${res.status}`
        pushActivity(`模型列表加载失败 HTTP ${res.status}`)
        return
      }
      const data = await res.json()
      const rows = Array.isArray(data?.models) ? data.models : []
      publicModels.value = rows
        .map((row) => ({
          id: String(row?.id || row?.model_id || '').trim(),
          provider: String(row?.provider || '—').trim() || '—',
          label: String(row?.label || row?.id || '').trim() || '—'
        }))
        .filter((r) => r.id)
      pushActivity(`模型元数据 ${publicModels.value.length} 条`)
    } catch (e) {
      modelsError.value = e instanceof Error ? e.message : '请求失败'
      pushActivity('模型列表请求异常')
    } finally {
      modelsLoading.value = false
    }
  }

  return { publicModels, modelsLoading, modelsError, loadPublicModels }
}
