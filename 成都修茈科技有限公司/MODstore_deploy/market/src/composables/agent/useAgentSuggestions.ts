import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAgentStore } from '../../stores/agent'
import { useWalletStore } from '../../stores/wallet'

export interface Suggestion {
  id: string
  message: string
  actionLabel?: string
  actionRoute?: string
}

/** Phase 3 主动建议规则引擎 */
export function useAgentSuggestions() {
  const route = useRoute()
  const agentStore = useAgentStore()
  const walletStore = useWalletStore()

  const currentSuggestion = ref<Suggestion | null>(null)
  const dismissed = ref<Set<string>>(new Set())

  function dismiss(id: string) {
    dismissed.value.add(id)
    if (currentSuggestion.value?.id === id) {
      currentSuggestion.value = null
    }
  }

  function checkSuggestions() {
    if (!agentStore.consentGiven) return

    // 规则 1：余额低于 10 元提醒充值
    const balance = walletStore.balance
    if (balance !== null && balance < 10) {
      const id = 'low-balance'
      if (!dismissed.value.has(id)) {
        currentSuggestion.value = {
          id,
          message: `您的余额仅剩 ¥${balance.toFixed(2)}，建议及时充值以保持服务正常使用。`,
          actionLabel: '去充值',
          actionRoute: 'recharge',
        }
        return
      }
    }

    // 规则 2：首次进入 AI 市场，引导发现员工
    if (route.name === 'ai-store') {
      const id = 'ai-store-hint'
      if (!dismissed.value.has(id)) {
        currentSuggestion.value = {
          id,
          message: '需要我帮您搜索适合您需求的 AI 员工吗？直接告诉我您想解决什么问题。',
          actionLabel: '对话管家',
        }
        return
      }
    }

    currentSuggestion.value = null
  }

  // 路由变化时重新检查
  watch(() => route.fullPath, checkSuggestions, { immediate: true })
  watch(() => walletStore.balance, checkSuggestions)

  return { currentSuggestion, dismiss }
}
