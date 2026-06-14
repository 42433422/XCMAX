/**
 * chat store — 轻量封装供 ChatViewOptimized.vue 使用。
 * 代理 jarvisChat store 并补充 isLoading / isStreamingReply 等状态。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useJarvisChatStore } from './jarvisChat'
import { asRecord, asArray, asString, asBoolean, asDisposable } from '@/utils/typeGuards'

export const useChatStore = defineStore('chat', () => {
  const jarvis = useJarvisChatStore()

  const isLoading = ref(false)
  const isStreamingReply = ref(false)

  const messages = computed(() => jarvis.messages as unknown[])
  const currentTask = computed(() => jarvis.currentTask)

  async function sendMessage(message: string): Promise<void> {
    isLoading.value = true
    try {
      await jarvis.sendMessage(message)
    } finally {
      isLoading.value = false
    }
  }

  function loadMoreMessages(): void {
    // jarvisChat 暂无历史分页；保留 API 供 ChatViewOptimized 兼容
  }

  async function executeTask(_taskId: string): Promise<void> {
    // 任务执行由 useChatOrchestration 承担
  }

  function clearTask(): void {
    jarvis.setCurrentTask(null)
  }

  function initChat(): void {
    jarvis.clearMessages()
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
