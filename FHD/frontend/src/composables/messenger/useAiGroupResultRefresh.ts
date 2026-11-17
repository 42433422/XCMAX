import { onUnmounted, ref, watch } from 'vue'
import { fetchAiGroupMessages, type AiGroupMessage } from '@/api/aiGroups'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

/** Pull host task receipts, not new SDK sessions: an OpenIM event alone does not harvest Para work. */
export function useAiGroupResultRefresh(group: () => string, enabled: () => boolean,
  receive: (rows: AiGroupMessage[]) => void) {
  const error = ref('')
  let generation = 0
  let retired = false
  let timer: ReturnType<typeof setTimeout> | undefined
  let request: AbortController | undefined
  function stop() {
    generation++
    clearTimeout(timer)
    request?.abort()
    request = undefined
  }
  function start() {
    stop()
    error.value = ''
    if (retired || !group() || !enabled() || document.visibilityState !== 'visible') return
    const captured = generation, id = group(), epoch = productReadAccountEpoch.value
    const current = () => captured === generation && id === group() && enabled() && epoch === productReadAccountEpoch.value
    async function tick() {
      if (!current()) return
      const controller = new AbortController()
      request = controller
      try {
        const rows = await fetchAiGroupMessages(id, 'admin', controller.signal)
        if (!current()) return
        receive(rows.filter(row => row.group_id === id))
        error.value = ''
      } catch {
        if (current() && !controller.signal.aborted) error.value = '任务回执同步失败，将自动重试；即时消息连接不代表任务已回收'
      } finally {
        if (request === controller) request = undefined
        if (current()) timer = setTimeout(() => void tick(), 5000)
      }
    }
    timer = setTimeout(() => void tick(), 5000)
  }
  const stopSelection = watch([group, enabled], start, { immediate: true, flush: 'sync' })
  const stopAccount = watch(productReadAccountEpoch, () => { retired = true; stop() }, { flush: 'sync' })
  document.addEventListener('visibilitychange', start)
  onUnmounted(() => {
    stop(); stopSelection(); stopAccount()
    document.removeEventListener('visibilitychange', start)
  })
  return error
}
