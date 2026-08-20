import { beforeEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { i18n } from '@/i18n'
import ChatHistoryModal from './ChatHistoryModal.vue'

function mountModal(props: Partial<InstanceType<typeof ChatHistoryModal>['$props']> = {}) {
  return mount(ChatHistoryModal, {
    props: {
      show: true,
      historySessions: [
        {
          session_id: 'session-1',
          title: '第一次使用',
          message_count: 4,
          last_message_at: '2026-07-12T08:30:00',
        },
      ],
      historyLoading: false,
      historyError: '',
      currentSessionId: 'session-1',
      ...props,
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

  it('shows loading state when historyLoading is true', () => {
    const wrapper = mountModal({ historyLoading: true })
    expect(wrapper.text()).toContain('正在加载')
  })

  it('shows error state with retry button when historyError is set', async () => {
    const wrapper = mountModal({
      historyError: '加载失败',
      historySessions: [],
    })
    expect(wrapper.text()).toContain('加载失败')
    const retryBtn = wrapper.findAll('button').find((b) => b.text().includes('重试'))!
    await retryBtn.trigger('click')
    expect(wrapper.emitted('refresh')).toHaveLength(1)
  })

  it('shows empty state when historySessions is empty', () => {
    const wrapper = mountModal({ historySessions: [] })
    expect(wrapper.text()).toContain('暂无历史')
  })

  it('emits refresh when refresh button clicked', async () => {
    const wrapper = mountModal()
    const refreshBtn = wrapper.findAll('button').find((b) => b.text().includes('刷新'))!
    await refreshBtn.trigger('click')
    expect(wrapper.emitted('refresh')).toHaveLength(1)
  })

  it('emits clear when clear button clicked', async () => {
    const wrapper = mountModal()
    const clearBtn = wrapper.findAll('button').find((b) => b.text().includes('清空'))!
    await clearBtn.trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
  })

  it('disables clear button when sessions are empty', () => {
    const wrapper = mountModal({ historySessions: [] })
    const clearBtn = wrapper.findAll('button').find((b) => b.text().includes('清空'))!
    expect(clearBtn.attributes('disabled')).toBeDefined()
  })

  it('emits load-session when a session item is clicked', async () => {
    const wrapper = mountModal({
      currentSessionId: 'other-session',
      historySessions: [
        {
          session_id: 'session-2',
          title: 'Session 2',
          message_count: 2,
          last_message_at: '2026-07-13T10:00:00',
        },
      ],
    })
    const sessionBtn = wrapper.get('button.history-session-item')
    await sessionBtn.trigger('click')
    expect(wrapper.emitted('load-session')).toEqual([['session-2']])
  })

  it('displays is_local_only badge when session is local only', () => {
    const wrapper = mountModal({
      currentSessionId: 'other-session',
      historySessions: [
        {
          session_id: 'session-3',
          title: 'Local',
          message_count: 1,
          last_message_at: '',
          is_local_only: true,
        },
      ],
    })
    expect(wrapper.text()).toContain('本地')
  })

  it('renders nothing when show is false', () => {
    const wrapper = mountModal({ show: false })
    expect(wrapper.find('.modal').exists()).toBe(false)
  })

  it('uses fallback title for sessions without title', () => {
    const wrapper = mountModal({
      currentSessionId: 'other',
      historySessions: [{ session_id: 's-no-title', title: '', message_count: 0, last_message_at: '' }],
    })
    // Falls back to chat.newSession key — should not be empty
    expect(wrapper.get('.history-session-title span').text()).not.toBe('')
  })
})
