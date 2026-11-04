import { computed, nextTick, ref, watch, type Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'

export const CHAT_HISTORY_WINDOW = 80
const PAGE_STEP = 60 // Keep an overlap so an on-screen message can anchor navigation.

/** Bound mounted rows without estimating the heights of arbitrary Markdown/cards. */
export function useChatHistoryWindow(messages: () => ChatMessage[], host: Ref<HTMLElement | null>, scope: () => unknown) {
  const start = ref(Math.max(0, messages().length - CHAT_HISTORY_WINDOW))
  const followingLatest = ref(true)
  const end = computed(() => Math.min(messages().length, start.value + CHAT_HISTORY_WINDOW))
  const visibleMessages = computed(() => messages().slice(start.value, end.value).map((msg, offset) => ({ msg, idx: start.value + offset })))
  let navigation = 0
  const bottom = () => { if (host.value && followingLatest.value) host.value.scrollTop = host.value.scrollHeight }

  function onScroll() {
    const el = host.value
    followingLatest.value = Boolean(el && end.value === messages().length && el.scrollHeight - el.scrollTop - el.clientHeight <= 48)
  }

  function showLatest() {
    navigation++
    followingLatest.value = true
    start.value = Math.max(0, messages().length - CHAT_HISTORY_WINDOW)
    void nextTick().then(bottom)
  }

  async function moveWindow(direction: number) {
    const el = host.value
    const anchor = el && Array.from(el.querySelectorAll<HTMLElement>('[data-message-index]'))
      .find((row) => row.getBoundingClientRect().bottom > el.getBoundingClientRect().top)
    const anchorTop = anchor?.getBoundingClientRect().top ?? 0
    const index = anchor?.dataset.messageIndex
    const current = ++navigation
    followingLatest.value = false
    start.value = Math.max(0, Math.min(messages().length - CHAT_HISTORY_WINDOW, start.value + direction * PAGE_STEP))
    await nextTick()
    if (!el || current !== navigation) return
    const retained = index && el.querySelector<HTMLElement>(`[data-message-index="${index}"]`)
    el.scrollTop = retained ? el.scrollTop + retained.getBoundingClientRect().top - anchorTop : 0
  }

  async function revealMessage(event: Event) {
    const index = Number((event as CustomEvent).detail)
    if (!Number.isInteger(index) || index < 0 || index >= messages().length) return
    event.preventDefault()
    const current = ++navigation
    followingLatest.value = false
    start.value = Math.max(0, Math.min(index - CHAT_HISTORY_WINDOW / 2, messages().length - CHAT_HISTORY_WINDOW))
    await nextTick()
    if (current === navigation) host.value?.querySelector<HTMLElement>(`[data-message-index="${index}"]`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  watch([messages, scope], ([items, key], previous) => {
    if (!previous || key !== previous[1] || items[0] !== previous[0][0]) showLatest()
  })
  watch([() => messages().length, () => messages()[messages().length - 1]?.content], () => {
    if (followingLatest.value) start.value = Math.max(0, messages().length - CHAT_HISTORY_WINDOW)
    else start.value = Math.min(start.value, Math.max(0, messages().length - CHAT_HISTORY_WINDOW))
    void nextTick().then(bottom)
  })
  watch(host, () => { void nextTick().then(bottom) })

  return { start, end, visibleMessages, moveWindow, showLatest, onScroll, revealMessage, scrollToLatestIfFollowing: bottom }
}
