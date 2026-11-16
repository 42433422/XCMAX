import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ChatTurnTrace from './ChatTurnTrace.vue'
import type { ChatTraceItem } from '@/composables/chat-orchestration/chatOrchestrationShared'

const ITEMS: ChatTraceItem[] = [
  { tool: 'read_slice', args: { sheet: 'Sheet1', long: 'x'.repeat(200) }, ok: true, ms: 18, summary: '读取 3 行' },
  { tool: 'list_attachments', ok: false, ms: 2 },
]

describe('ChatTurnTrace', () => {
  it('默认折叠，展开后显示参数与摘要', async () => {
    const wrapper = mount(ChatTurnTrace, { props: { items: ITEMS } })
    const details = wrapper.find('details.chat-turn-trace')

    expect(details.exists()).toBe(true)
    expect(details.attributes('open')).toBeUndefined()
    expect(wrapper.text()).toContain('本轮执行')
    expect(wrapper.text()).toContain('read_slice')
    expect(wrapper.text()).toContain('18 ms')
    expect(wrapper.findAll('.chat-turn-trace__item')).toHaveLength(2)
    expect(wrapper.findAll('.chat-turn-trace__dot.is-fail')).toHaveLength(1)

    ;(details.element as HTMLDetailsElement).open = true
    await details.trigger('toggle')
    expect(details.attributes('open')).toBeDefined()
    expect(wrapper.find('.chat-turn-trace__args').text()).toContain('Sheet1')
    expect(wrapper.find('.chat-turn-trace__args').text()).toContain('…')
    expect(wrapper.find('.chat-turn-trace__args').text()).not.toContain('x'.repeat(121))
  })

  it('无 trace 时不渲染任何内容', () => {
    const wrapper = mount(ChatTurnTrace, { props: { items: [] } })
    expect(wrapper.find('.chat-turn-trace').exists()).toBe(false)
  })
})
