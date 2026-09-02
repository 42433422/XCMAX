import { ref } from 'vue'
import { apiFetch } from '@/utils/apiBase'
import {
  XCAGI_AI_DEVELOPER_MODE_KEY,
  XCAGI_AI_ELEVATED_TOKEN_KEY,
  XCAGI_AI_TIER_CHANGED_EVENT
} from '@/utils/xcagiStorageKeys'

/** 本机 P1/P2 意图与服务端 tier 状态（拆分自 BrainView.vue，逻辑不变） */
export function useBrainTier({ pushActivity }) {
  const tierStatus = ref(null)
  const tierStatusLoading = ref(true)

  function readClientTier() {
    try {
      const dev = window.localStorage.getItem(XCAGI_AI_DEVELOPER_MODE_KEY) === '1'
      const tok = String(window.localStorage.getItem(XCAGI_AI_ELEVATED_TOKEN_KEY) || '').trim()
      return dev && tok ? 'p2' : 'p1'
    } catch {
      return 'p1'
    }
  }

  const clientTier = ref(readClientTier())

  function onStorage(e) {
    if (!e.key || e.key === XCAGI_AI_DEVELOPER_MODE_KEY || e.key === XCAGI_AI_ELEVATED_TOKEN_KEY) {
      clientTier.value = readClientTier()
    }
  }

  function onWindowFocus() {
    const next = readClientTier()
    if (next !== clientTier.value) {
      clientTier.value = next
      pushActivity('已刷新本机 P1/P2 意图（自设置返回）')
    }
  }

  function onAiTierChanged() {
    const next = readClientTier()
    clientTier.value = next
    pushActivity(`本机意图已更新为 ${next.toUpperCase()}（设置已保存）`)
  }

  async function loadTierStatus() {
    tierStatusLoading.value = true
    try {
      const res = await apiFetch('/api/fhd/ai-tier/status')
      if (!res.ok) {
        tierStatus.value = null
        return
      }
      tierStatus.value = await res.json()
    } catch {
      tierStatus.value = null
    } finally {
      tierStatusLoading.value = false
    }
  }

  return {
    clientTier,
    tierStatus,
    tierStatusLoading,
    onStorage,
    onWindowFocus,
    onAiTierChanged,
    loadTierStatus,
  }
}
