import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AgentMessageBubble from './AgentMessageBubble.vue'
import type { AgentMessage } from '../../types/agent'

const msg = (change: Partial<AgentMessage> = {}): AgentMessage => ({
  id: 'message-1', role: 'assistant', content: '处理完成', timestamp: 1, ...change,
})

afterEach(() => vi.unstubAllGlobals())

describe('AgentMessageBubble', () => {
  it('copies raw message text instead of rendered HTML', async () => {
    const writeText = vi.fn(async (_text: string) => undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    const wrapper = mount(AgentMessageBubble, { props: { msg: msg({ content: '**结果**' }) } })
    await wrapper.get('button[aria-label="复制消息正文"]').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('**结果**')
    expect(wrapper.get('[role="status"]').text()).toBe('已复制')
    wrapper.unmount()
  })

  it('never exposes tool argument values in the conversation', () => {
    const wrapper = mount(AgentMessageBubble, {
      props: { msg: msg({ role: 'tool_call', content: '',
        toolCall: { name: 'search', args: { access_token: 'private-value' } } }) },
    })
    expect(wrapper.text()).toContain('search')
    expect(wrapper.text()).not.toContain('private-value')
    wrapper.unmount()
  })

  it('distinguishes a loading reply from an unconfirmed failure', async () => {
    const wrapper = mount(AgentMessageBubble, { props: { msg: msg({ isLoading: true }) } })
    expect(wrapper.get('[role="status"]').attributes('aria-label')).toBe('正在思考')
    await wrapper.setProps({ msg: msg({ isError: true, content: '结果未核实' }) })
    expect(wrapper.get('[role="alert"]').text()).toContain('结果未核实')
    wrapper.unmount()
  })
})
