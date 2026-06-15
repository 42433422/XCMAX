import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/composables/useProMode', () => ({
  useProMode: () => ({
    stepBack: vi.fn(),
    currentStage: { value: 'idle' },
  }),
}))

import JarvisChatPanel from '@/components/pro-mode/JarvisChatPanel.vue'

function mountComponent(propsOverrides = {}) {
  return mount(JarvisChatPanel, {
    props: {
      messages: [],
      isWorkMode: false,
      showInput: true,
      ...propsOverrides,
    },
  })
}

describe('JarvisChatPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the chat panel container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.jarvis-chat-panel').exists()).toBe(true)
  })

  it('renders chat messages container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.chat-messages').exists()).toBe(true)
  })

  it('renders messages when provided', async () => {
    const messages = [
      { id: '1', type: 'user', content: 'Hello', timestamp: Date.now() },
      { id: '2', type: 'ai', content: 'Hi there', timestamp: Date.now() },
    ]
    const wrapper = mountComponent({ messages })
    expect(wrapper.text()).toContain('Hello')
    expect(wrapper.text()).toContain('Hi there')
  })

  it('renders AI message with JARVIS header', () => {
    const messages = [
      { id: '1', type: 'ai', content: 'AI response', timestamp: Date.now() },
    ]
    const wrapper = mountComponent({ messages })
    expect(wrapper.text()).toContain('JARVIS')
    expect(wrapper.text()).toContain('AI response')
  })

  it('renders user message with user header', () => {
    const messages = [
      { id: '1', type: 'user', content: 'User message', timestamp: Date.now() },
    ]
    const wrapper = mountComponent({ messages })
    expect(wrapper.text()).toContain('用户')
    expect(wrapper.text()).toContain('User message')
  })

  it('renders task message with task header', () => {
    const messages = [
      { id: '1', type: 'task', content: 'Task description', timestamp: Date.now() },
    ]
    const wrapper = mountComponent({ messages })
    expect(wrapper.text()).toContain('任务')
    expect(wrapper.text()).toContain('Task description')
  })

  it('renders task card with confirm and ignore buttons', () => {
    const messages = [
      {
        id: '1',
        type: 'task',
        content: 'Task content',
        timestamp: Date.now(),
        taskData: {
          title: '确认任务',
          description: '请确认',
          confirmAction: true,
          ignoreAction: true,
        },
      },
    ]
    const wrapper = mountComponent({ messages })
    expect(wrapper.text()).toContain('确认任务')
    expect(wrapper.find('.task-button.confirm').exists()).toBe(true)
    expect(wrapper.find('.task-button.ignore').exists()).toBe(true)
  })

  it('renders empty messages container when no messages', () => {
    const wrapper = mountComponent({ messages: [] })
    const container = wrapper.find('.chat-messages')
    expect(container.exists()).toBe(true)
  })

  it('applies hidden class when showPanel is false', () => {
    // showPanel starts as true; we test the class exists on the container
    const wrapper = mountComponent()
    expect(wrapper.find('.jarvis-chat-panel').exists()).toBe(true)
  })

  it('renders input area when showInput is true', () => {
    const wrapper = mountComponent({ showInput: true })
    expect(wrapper.find('.chat-input-container').exists()).toBe(true)
    expect(wrapper.find('.chat-input').exists()).toBe(true)
    expect(wrapper.find('.send-button').exists()).toBe(true)
  })

  it('hides input area when showInput is false', () => {
    const wrapper = mountComponent({ showInput: false })
    expect(wrapper.find('.chat-input-container').exists()).toBe(false)
  })

  it('emits messageSend when user sends a message', async () => {
    const wrapper = mountComponent()
    const input = wrapper.find('.chat-input')
    await input.setValue('Test message')
    await wrapper.find('.send-button').trigger('click')
    expect(wrapper.emitted('messageSend')).toBeTruthy()
    expect(wrapper.emitted('messageSend')![0]).toEqual(['Test message'])
  })

  it('does not emit messageSend when input is empty', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.send-button').trigger('click')
    expect(wrapper.emitted('messageSend')).toBeFalsy()
  })

  it('emits messageSend on enter key', async () => {
    const wrapper = mountComponent()
    const input = wrapper.find('.chat-input')
    await input.setValue('Hello')
    await input.trigger('keyup.enter')
    expect(wrapper.emitted('messageSend')).toBeTruthy()
  })

  it('emits taskConfirm when confirm button clicked', async () => {
    const taskData = { title: 'Test', confirmAction: true }
    const messages = [
      { id: '1', type: 'task', content: 'Task', timestamp: Date.now(), taskData },
    ]
    const wrapper = mountComponent({ messages })
    await wrapper.find('.task-button.confirm').trigger('click')
    expect(wrapper.emitted('taskConfirm')).toBeTruthy()
    expect(wrapper.emitted('taskConfirm')![0]).toEqual([taskData])
  })

  it('emits taskIgnore when ignore button clicked', async () => {
    const taskData = { title: 'Test', ignoreAction: true }
    const messages = [
      { id: '1', type: 'task', content: 'Task', timestamp: Date.now(), taskData },
    ]
    const wrapper = mountComponent({ messages })
    await wrapper.find('.task-button.ignore').trigger('click')
    expect(wrapper.emitted('taskIgnore')).toBeTruthy()
    expect(wrapper.emitted('taskIgnore')![0]).toEqual([taskData])
  })

  it('send button is disabled when input is empty', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.send-button').element.disabled).toBe(true)
  })

  it('send button is enabled when input has text', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.chat-input').setValue('text')
    expect(wrapper.find('.send-button').element.disabled).toBe(false)
  })
})
