import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import AgentChatHistory from './AgentChatHistory.vue'
import { useAgentStore } from '../../stores/agent'
import type { AgentMessage } from '../../types/agent'

vi.mock('vue-router', () => ({ useRoute: () => ({ name: 'home' }) }))
vi.mock('../../corp-butler/corpViewport', () => ({ useCorpMobileViewport: () => ref(false) }))

const message = (id: string, role: AgentMessage['role'] = 'assistant'): AgentMessage => ({
  id, role, content: id, timestamp: 1,
})

beforeEach(() => setActivePinia(createPinia()))

describe('AgentChatHistory scroll continuity', () => {
  it('preserves reader position during reply updates and offers an explicit latest action', async () => {
    const store = useAgentStore()
    store.messages = [message('first')]
    const wrapper = mount(AgentChatHistory, {
      global: { stubs: {
        AgentMessageBubble: true, AgentActionPreview: true, CorpWelcomeBoard: true,
      } },
    })
    await flushPromises()
    const host = wrapper.get('.chat-history')
    const element = host.element as HTMLDivElement
    let height = 800
    Object.defineProperty(element, 'scrollHeight', { configurable: true, get: () => height })
    Object.defineProperty(element, 'clientHeight', { configurable: true, get: () => 200 })

    element.scrollTop = 100
    await host.trigger('scroll')
    expect(wrapper.get('button[aria-label="查看最新消息"]').exists()).toBe(true)

    store.addMessage(message('assistant-reply'))
    await flushPromises()
    store.updateLastMessage({ content: 'stream continuation', isLoading: true })
    await flushPromises()
    expect(element.scrollTop).toBe(100)

    height = 900
    await wrapper.get('button[aria-label="查看最新消息"]').trigger('click')
    await flushPromises()
    expect(element.scrollTop).toBe(900)
    expect(wrapper.find('button[aria-label="查看最新消息"]').exists()).toBe(false)

    element.scrollTop = 100
    await host.trigger('scroll')
    store.addMessage(message('my-new-turn', 'user'))
    await flushPromises()
    expect(element.scrollTop).toBe(900)
    wrapper.unmount()
  })
})
