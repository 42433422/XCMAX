import { afterEach, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { h, nextTick, onMounted, ref } from 'vue'
import ChatMessageList from './ChatMessageList.vue'
import type { ChatMessage } from '@/composables/useChatMessages'

const cleanups: Array<() => void> = []
afterEach(() => cleanups.splice(0).forEach(cleanup => cleanup()))

function messages(count: number): ChatMessage[] {
  return Array.from({ length: count }, (_, index) => ({
    role: 'ai', content: `消息 ${index}`, time: '12:00',
  }))
}

function mountPage(count: number, header: boolean) {
  const content = ref(messages(count))
  const ready = ref(false)
  const errors: unknown[] = []
  const container = document.createElement('div')
  document.body.appendChild(container)
  const props = {
    isLoading: false, isStreamingReply: false, loadingProgressText: '',
    messageHeights: new Map<number, number>(), latestAiMessageIndex: count - 1,
    playingMsgIdx: -1, isMessageCollapsed: () => false, canSpeakMessage: () => false,
  }
  const wrapper = mount({
    setup() {
      onMounted(() => { ready.value = true })
      return () => h('section', { 'data-ready': ready.value }, [
        // The real ChatView renders both siblings before its parent reaches the DOM.
        header ? h('div', { id: 'chat-history-nav-slot' }) : null,
        h(ChatMessageList, { ...props, messages: content.value }),
      ])
    },
  }, { attachTo: container, global: { config: { errorHandler: error => errors.push(error) } } })
  cleanups.push(() => { wrapper.unmount(); container.remove() })
  return { wrapper, content, errors }
}

it.each([1, 81])('mounts a same-page history target without interrupting updates (%s messages)', async count => {
  const page = mountPage(count, true)
  await nextTick()
  await nextTick()
  expect(page.errors).toEqual([])
  expect(page.wrapper.attributes('data-ready')).toBe('true')
  const target = page.wrapper.get('#chat-history-nav-slot')
  expect(target.find('nav').exists()).toBe(count > 80)
  page.content.value = messages(82)
  await nextTick()
  expect(page.errors).toEqual([])
  expect(target.get('nav').text()).toContain('已载入 82 条')
  expect(page.wrapper.get('.chat-messages-shell').find('nav').exists()).toBe(false)
})

it('keeps the pager local when no header target belongs to the page', async () => {
  const page = mountPage(81, false)
  await nextTick()
  await nextTick()
  expect(page.errors).toEqual([])
  expect(page.wrapper.get('.chat-messages-shell nav').text()).toContain('已载入 81 条')
  page.content.value = messages(1)
  await nextTick()
  expect(page.errors).toEqual([])
  expect(page.wrapper.find('nav').exists()).toBe(false)
})
