import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ChatTurnTrace from './ChatTurnTrace.vue'
import type { ChatTraceItem } from '@/composables/chat-orchestration/chatOrchestrationShared'

const ITEMS: ChatTraceItem[] = [
  { tool: 'read_slice', args: { sheet: 'Sheet1', long: 'x'.repeat(200) }, ok: true, ms: 18, summary: '读取 3 行' },
  { tool: 'list_attachments', ok: false, ms: 2 },
]

describe('ChatTurnTrace', () => {
  it('附件记录默认折叠，展开后显示任务名称，详情中保留参数与摘要', async () => {
    const wrapper = mount(ChatTurnTrace, { props: { items: ITEMS } })
    const trigger = wrapper.get('button.chat-turn-trace__summary')

    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(wrapper.text()).toContain('附件读取')
    expect(wrapper.text()).not.toContain('本轮执行')
    expect(wrapper.text()).not.toContain('read_slice')
    expect(wrapper.find('.chat-turn-trace__args').exists()).toBe(false)

    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.text()).toContain('读取表格内容')
    expect(wrapper.text()).toContain('读取附件清单')
    expect(wrapper.text()).toContain('18 ms')
    expect(wrapper.findAll('.chat-turn-trace__item')).toHaveLength(2)
    expect(wrapper.findAll('[data-slot="trace-line"][data-status="error"]')).toHaveLength(1)
    expect(wrapper.find('.chat-turn-trace__args').exists()).toBe(false)

    await wrapper.findAll('button.chat-turn-trace__head')[0].trigger('click')
    expect(wrapper.text()).toContain('read_slice')
    expect(wrapper.text()).toContain('读取 3 行')
    expect(wrapper.find('.chat-turn-trace__args').text()).toContain('Sheet1')
    expect(wrapper.find('.chat-turn-trace__args').text()).toContain('…')
    expect(wrapper.find('.chat-turn-trace__args').text()).not.toContain('x'.repeat(121))
    expect(trigger.attributes('aria-expanded')).toBe('true')
  })

  it('无 trace 时不渲染任何内容', () => {
    const wrapper = mount(ChatTurnTrace, { props: { items: [] } })
    expect(wrapper.find('.chat-turn-trace').exists()).toBe(false)
  })
})
