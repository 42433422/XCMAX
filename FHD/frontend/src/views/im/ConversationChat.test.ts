import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { describe, expect, it } from 'vitest'

import ConversationChat from './ConversationChat.vue'

function baseProps() {
  return {
    activeTitle: 'wuxinghua1',
    hasMoreHistory: false,
    busy: false,
    messages: [
      {
        id: 1,
        conversation_id: 8,
        sender_user_id: 99,
        body: '请先重新登录。',
        origin: 'ai' as const,
        created_at: '2026-08-31T12:00:00Z',
      },
    ],
    draft: '',
    isMyMessage: () => true,
    formatTime: () => '20:00',
    scrollEl: ref<HTMLElement | null>(null),
  }
}

describe('ConversationChat enterprise CS controls', () => {
  it('shows AI provenance and lets admin take over', async () => {
    const wrapper = mount(ConversationChat, {
      props: {
        ...baseProps(),
        csAutomation: {
          id: 8,
          title: 'wuxinghua1',
          is_direct: true,
          last_message_at: null,
          last_message_preview: '',
          unread_count: 0,
          is_cs_inbox: true,
          cs_mode: 'ai',
          cs_status: 'ai_active',
        },
      },
    })

    expect(wrapper.text()).toContain('AI自动接待')
    expect(wrapper.text()).toContain('AI自动回复')
    await wrapper.find('.im-cs-mode-button').trigger('click')
    expect(wrapper.emitted('change-cs-mode')).toEqual([['human']])
  })

  it('shows handoff reason and lets admin restore AI', async () => {
    const wrapper = mount(ConversationChat, {
      props: {
        ...baseProps(),
        csAutomation: {
          id: 8,
          title: 'wuxinghua1',
          is_direct: true,
          last_message_at: null,
          last_message_preview: '',
          unread_count: 1,
          is_cs_inbox: true,
          cs_mode: 'human',
          cs_status: 'human_pending',
          cs_transfer_reason: '客户主动要求转人工',
        },
      },
    })

    expect(wrapper.text()).toContain('AI 已转人工')
    expect(wrapper.text()).toContain('客户主动要求转人工')
    expect(wrapper.text()).toContain('恢复AI')
    await wrapper.find('.im-cs-mode-button').trigger('click')
    expect(wrapper.emitted('change-cs-mode')).toEqual([['ai']])
  })
})
