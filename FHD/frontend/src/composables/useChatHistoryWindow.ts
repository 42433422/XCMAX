import { computed, nextTick, ref, watch, type Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'
import { chatMessageKey } from '@/utils/chatMessageIdentity'

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

  async function moveWindow(direction: number, targetStart?: number) {
    const el = host.value
    const anchor = el && Array.from(el.querySelectorAll<HTMLElement>('[data-message-index]'))
      .find((row) => row.getBoundingClientRect().bottom > el.getBoundingClientRect().top)
    const anchorTop = anchor?.getBoundingClientRect().top ?? 0
    const anchorKey = anchor?.dataset.messageKey
    const current = ++navigation
    followingLatest.value = false
    start.value = Math.max(0, Math.min(messages().length - CHAT_HISTORY_WINDOW, targetStart ?? (start.value + direction * PAGE_STEP)))
    await nextTick()
    if (!el || host.value !== el || current !== navigation) return
    const retained = anchorKey && Array.from(el.querySelectorAll<HTMLElement>('[data-message-key]'))
      .find(row => row.dataset.messageKey === anchorKey)
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

  const firstKey = () => {
    const first = messages()[0]
    return first ? chatMessageKey(first) : ''
  }
  const lastKey = () => {
    const items = messages()
    const last = items[items.length - 1]
    return last ? chatMessageKey(last) : ''
  }
  watch([scope, firstKey], ([key, first], [previousScope, previousFirst]) => {
    if (key !== previousScope || !first || !previousFirst) { showLatest(); return }
    if (first === previousFirst) return
    // The server can prepend an earlier page, replacing the array. Keep the
    // same window of stable IDs instead of jumping to the latest message.
    const offset = messages().findIndex(message => chatMessageKey(message) === previousFirst)
    if (offset <= 0) { showLatest(); return }
    start.value = Math.min(start.value + offset, Math.max(0, messages().length - CHAT_HISTORY_WINDOW))
    if (followingLatest.value) void nextTick().then(bottom)
  })
  watch([() => messages().length, lastKey, () => messages()[messages().length - 1]?.content], ([, lastId], [, previousLastId]) => {
    const items = messages()
    const last = items[items.length - 1]
    // Only a newly appended user message should force the latest window.
    // Prepending history or editing existing content must not steal the viewport.
    if (!followingLatest.value && last?.role === 'user' && lastId !== previousLastId) {
      showLatest()
      return
    }
    if (followingLatest.value) start.value = Math.max(0, messages().length - CHAT_HISTORY_WINDOW)
    else start.value = Math.min(start.value, Math.max(0, messages().length - CHAT_HISTORY_WINDOW))
    void nextTick().then(bottom)
  })
  watch(host, () => { void nextTick().then(bottom) })

  return { start, end, visibleMessages, moveWindow, showLatest, onScroll, revealMessage, scrollToLatestIfFollowing: bottom }
}
