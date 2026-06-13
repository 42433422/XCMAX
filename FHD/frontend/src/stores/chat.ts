/**
 * chat store — 轻量封装供 ChatViewOptimized.vue 使用。
 * 代理 jarvisChat store 并补充 isLoading / isStreamingReply 等状态。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useJarvisChatStore } from './jarvisChat'

export const useChatStore = defineStore('chat', () => {
  const jarvis = useJarvisChatStore()

  const isLoading = ref(false)
  const isStreamingReply = ref(false)

  const messages = computed(() => jarvis.messages as unknown[])
  const currentTask = computed(() => jarvis.currentTask)

  async function sendMessage(message: string): Promise<void> {
    isLoading.value = true
    try {
      await (jarvis as unknown).sendMessage?.(message)
    } finally {
      isLoading.value = false
    }
  }

  function loadMoreMessages(): void {
    ;(jarvis as unknown).loadMoreMessages?.()
  }

  async function executeTask(taskId: string): Promise<void> {
    await (jarvis as unknown).executeTask?.(taskId)
  }

  function clearTask(): void {
    ;(jarvis as unknown).clearTask?.()
  }

  function initChat(): void {
    ;(jarvis as unknown).initChat?.()
  }

  return {
    messages,
    isLoading,
    isStreamingReply,
    currentTask,
    sendMessage,
    loadMoreMessages,
    executeTask,
    clearTask,
    initChat,
  }
})
