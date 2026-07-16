import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { i18n } from '@/i18n'
import ChatHistoryModal from './ChatHistoryModal.vue'

function mountModal() {
  return mount(ChatHistoryModal, {
    props: {
      show: true,
      historySessions: [{
        session_id: 'session-1',
        title: '第一次使用',
        message_count: 4,
        last_message_at: '2026-07-12T08:30:00',
      }],
      historyLoading: false,
      historyError: '',
      currentSessionId: 'session-1',
    },
  })
}

describe('ChatHistoryModal', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'zh-CN'
  })

  it('uses Chinese user-facing labels and shows the session date', () => {
    const wrapper = mountModal()
    expect(wrapper.text()).toContain('历史对话')
    expect(wrapper.text()).toContain('4 条消息')
    expect(wrapper.text()).toMatch(/7月12日|今天/)
  })

  it('exposes the close action as an accessible button', async () => {
    const wrapper = mountModal()
    const close = wrapper.get('button.history-modal-close')
    expect(close.attributes('aria-label')).toBe('关闭历史对话')
    await close.trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
