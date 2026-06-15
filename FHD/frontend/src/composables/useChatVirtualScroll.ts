/** 长会话消息列表虚拟窗口（仅渲染可视区 + 缓冲）。 */
import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import type { ChatMessage } from '@/composables/useChatMessages'

const DEFAULT_ITEM_HEIGHT = 96
const BUFFER_ITEMS = 10
const ENABLE_THRESHOLD = 50

export function useChatVirtualScroll(options: {
  messages: Ref<ChatMessage[]>
  scrollEl: Ref<HTMLElement | null>
  estimateHeight: (index: number) => number
  threshold?: number
}) {
  const { messages, scrollEl, estimateHeight } = options
  const threshold = options.threshold ?? ENABLE_THRESHOLD

  const scrollTop = ref(0)
  const viewportHeight = ref(720)

  const enabled = computed(() => messages.value.length >= threshold)

  const itemHeights = computed(() =>
    messages.value.map((_, idx) => Math.max(48, estimateHeight(idx) || DEFAULT_ITEM_HEIGHT)),
  )

  const offsets = computed(() => {
    const list: number[] = []
    let acc = 0
    for (const h of itemHeights.value) {
      list.push(acc)
      acc += h + 16
    }
    return list
  })

  const totalHeight = computed(() => {
    const hs = itemHeights.value
    if (!hs.length) return 0
    return offsets.value[hs.length - 1]! + hs[hs.length - 1]! + 16
  })

  const visibleRange = computed(() => {
    const count = messages.value.length
    if (!enabled.value || count === 0) {
      return { start: 0, end: count }
    }
    const top = scrollTop.value
    const bottom = top + viewportHeight.value
    const offs = offsets.value
    const hs = itemHeights.value
    let start = 0
    while (start < count && offs[start]! + hs[start]! < top) start += 1
    start = Math.max(0, start - BUFFER_ITEMS)
    let end = start
    while (end < count && offs[end]! < bottom) end += 1
    end = Math.min(count, end + BUFFER_ITEMS)
    return { start, end }
  })

  const renderIndices = computed(() => {
    const { start, end } = visibleRange.value
    const indices: number[] = []
    for (let i = start; i < end; i += 1) indices.push(i)
    return indices
  })

  const topSpacer = computed(() => {
    if (!enabled.value) return 0
    return offsets.value[visibleRange.value.start] ?? 0
  })

  const bottomSpacer = computed(() => {
    if (!enabled.value) return 0
    const end = visibleRange.value.end
    const count = messages.value.length
    if (end >= count) return 0
    const endOffset = offsets.value[end] ?? totalHeight.value
    return Math.max(0, totalHeight.value - endOffset)
  })

  function refreshViewport() {
    const el = scrollEl.value
    if (!el) return
    viewportHeight.value = el.clientHeight || 720
    scrollTop.value = el.scrollTop
  }

  function onScroll() {
    refreshViewport()
  }

  let ro: ResizeObserver | null = null
  watch(
    scrollEl,
    (el, prev) => {
      prev?.removeEventListener('scroll', onScroll)
      ro?.disconnect()
      ro = null
      if (!el) return
      el.addEventListener('scroll', onScroll, { passive: true })
      ro = new ResizeObserver(() => refreshViewport())
      ro.observe(el)
      refreshViewport()
    },
    { immediate: true },
  )

  watch(
    () => messages.value.length,
    () => refreshViewport(),
  )

  onBeforeUnmount(() => {
    scrollEl.value?.removeEventListener('scroll', onScroll)
    ro?.disconnect()
  })

  return {
    enabled,
    renderIndices,
    topSpacer,
    bottomSpacer,
    onScroll,
    refreshViewport,
  }
}
