import { mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import ChatConversationPanel from './ChatConversationPanel.vue'

const now = new Date('2026-10-15T12:00:00Z').valueOf()
const sessions = [0, 1, 4, 40, NaN].map((days, index) => ({
  session_id: `s${index}`, title: index ? `会话${index}` : '', message_count: index,
  last_message_at: Number.isNaN(days) ? 'invalid' : new Date(now - days * 86400000).toISOString(),
  is_local_only: index === 0,
}))
const setup = (props = {}) => mount(ChatConversationPanel, {
  props: { sessions, currentSessionId: 's0', loading: false, error: '', ...props },
})
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

it('groups dated and invalid history, marks the current local session and emits toolbar and load actions', async () => {
  vi.useFakeTimers(); vi.setSystemTime(now)
  const wrapper = setup()
  expect(wrapper.findAll('.conv-group-label').map(x => x.text())).toEqual(['今天', '昨天', '近 7 天', '更早'])
  expect(wrapper.findAll('.conv-group').map(x => x.findAll('.conv-item').length)).toEqual([1, 1, 1, 2])
  expect(wrapper.findAll('.conv-item--active')).toHaveLength(1)
  expect(wrapper.get('.conv-item-local').text()).toBeTruthy()
  expect(wrapper.findAll('.conv-item-title')[0].text()).not.toBe('')
  for (const [index, event] of ['new', 'clear'].entries()) {
    await wrapper.findAll('.conv-panel-toolbar button')[index].trigger('click')
    expect(wrapper.emitted(event)).toEqual([[]])
  }
  await wrapper.findAll('.conv-item-main')[1].trigger('click')
  expect(wrapper.emitted('load')).toEqual([['s1']])
  wrapper.unmount()
})

it('gates loading, reports a retryable error and renders empty history', async () => {
  const wrapper = setup({ loading: true })
  expect(wrapper.find('.conv-list').exists()).toBe(false)
  expect(wrapper.findAll('.conv-panel-toolbar button').every(x => x.attributes('disabled') !== undefined)).toBe(true)
  await wrapper.setProps({ loading: false, error: '会话加载失败' })
  expect(wrapper.get('.conv-error-text').text()).toBe('会话加载失败')
  await wrapper.get('.conv-error button').trigger('click')
  expect(wrapper.emitted('refresh')).toEqual([[]])
  await wrapper.setProps({ error: '', sessions: [] })
  expect(wrapper.get('.conv-empty-tip').text()).toBeTruthy()
  expect(wrapper.findAll('.conv-panel-toolbar button')[1].attributes('disabled')).toBeDefined()
  wrapper.unmount()
})

it.each(['button', 'enter'])('renames with %s, trims the title and rejects blank names', async mode => {
  const wrapper = setup()
  await wrapper.findAll('.conv-action-btn')[0].trigger('click')
  const input = wrapper.get('input')
  expect((input.element as HTMLInputElement).value).toBe('')
  await input.setValue('   ')
  await input.trigger('keydown.enter')
  expect(wrapper.emitted('rename')).toBeUndefined()
  expect(wrapper.get('.conv-rename-actions .btn-primary').attributes('disabled')).toBeDefined()
  await input.setValue('  客户跟进  ')
  if (mode === 'enter') await input.trigger('keydown.enter')
  else await wrapper.get('.conv-rename-actions .btn-primary').trigger('click')
  expect(wrapper.emitted('rename')).toEqual([['s0', '客户跟进']])
  expect(wrapper.find('.conv-rename-overlay').exists()).toBe(false)
  expect(wrapper.emitted('load')).toBeUndefined()
  wrapper.unmount()
})

it.each(['button', 'escape'])('cancels rename with %s and confirms before deleting', async mode => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
  const wrapper = setup()
  await wrapper.findAll('.conv-action-btn')[2].trigger('click')
  expect((wrapper.get('input').element as HTMLInputElement).value).toBe('会话1')
  if (mode === 'escape') await wrapper.get('input').trigger('keydown.esc')
  else await wrapper.get('.conv-rename-actions .btn-secondary').trigger('click')
  expect(wrapper.find('.conv-rename-overlay').exists()).toBe(false)
  expect(wrapper.emitted('rename')).toBeUndefined()
  for (const index of [0, 1]) await wrapper.findAll('.conv-action-btn--danger')[index].trigger('click')
  expect(confirm.mock.calls[0][0]).toContain('新会话')
  expect(confirm.mock.calls[1][0]).toContain('会话1')
  expect(wrapper.emitted('delete')).toEqual([['s1']])
  wrapper.unmount()
})
