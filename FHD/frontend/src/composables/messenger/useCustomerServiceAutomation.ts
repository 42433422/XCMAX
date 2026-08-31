import { computed, ref, type Ref } from 'vue'
import { updateCsInboxMode, type ImConversationSummary } from '@/api/im'
import { showAppToast } from '@/composables/useAppToast'

type Options = {
  conversations: Ref<ImConversationSummary[]>
  activeConversationId: Ref<number | null>
  reloadConversations: () => Promise<void>
}

export function useCustomerServiceAutomation(options: Options) {
  const busy = ref(false)
  const activeConversation = computed(() => {
    const conversation = options.conversations.value.find(
      (item) => item.id === options.activeConversationId.value,
    )
    return conversation?.is_cs_inbox ? conversation : undefined
  })

  async function changeMode(mode: 'ai' | 'human'): Promise<void> {
    const conversation = activeConversation.value
    if (!conversation || busy.value) return
    busy.value = true
    try {
      Object.assign(conversation, await updateCsInboxMode(conversation.id, mode))
      showAppToast(mode === 'human' ? '已人工接管该会话' : '已恢复 AI 自动接待', 'success')
      await options.reloadConversations()
    } catch (error) {
      showAppToast(error instanceof Error ? error.message : '切换接待模式失败', 'error')
    } finally {
      busy.value = false
    }
  }

  return { activeCsConversation: activeConversation, csAutomationBusy: busy, onChangeCsMode: changeMode }
}
