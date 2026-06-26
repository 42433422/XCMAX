import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  fetchAiGroups: vi.fn(),
  fetchAiGroupMessages: vi.fn(),
  postAiGroupMessage: vi.fn(),
  createAiGroup: vi.fn(),
  addAiGroupMember: vi.fn(),
  removeAiGroupMember: vi.fn(),
  apiFetch: vi.fn(),
}))

vi.mock('@/api/aiGroups', () => ({
  fetchAiGroups: mocks.fetchAiGroups,
  fetchAiGroupMessages: mocks.fetchAiGroupMessages,
  postAiGroupMessage: mocks.postAiGroupMessage,
  createAiGroup: mocks.createAiGroup,
  addAiGroupMember: mocks.addAiGroupMember,
  removeAiGroupMember: mocks.removeAiGroupMember,
}))

vi.mock('@/utils/apiBase', () => ({
  apiFetch: mocks.apiFetch,
}))

import AiGroupChatView from './AiGroupChatView.vue'

const {
  fetchAiGroups,
  fetchAiGroupMessages,
  postAiGroupMessage,
  createAiGroup,
  removeAiGroupMember,
  apiFetch: apiFetchMock,
} = mocks

const sampleGroup = {
  id: 'g1',
  name: '测试群',
  member_count: 2,
  last_message_preview: '你好',
  members: [
    { employee_id: 'e1', name: 'AI助手A', avatar: '', summary: '' },
  ],
}

const sampleMessage = {
  id: 'm1',
  group_id: 'g1',
  role: 'assistant',
  sender_id: 'e1',
  sender_name: 'AI助手A',
  sender_avatar: '',
  body: '你好，有什么可以帮你？',
  created_at: '2026-06-24T10:00:00Z',
}

function mountView() {
  return mount(AiGroupChatView)
}

describe('AiGroupChatView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetchAiGroups.mockResolvedValue([])
    fetchAiGroupMessages.mockResolvedValue([])
    apiFetchMock.mockResolvedValue({
      json: async () => ({ data: { items: [] } }),
    } as Response)
  })

  it('renders the main container', () => {
    const wrapper = mountView()
    expect(wrapper.find('.aigc').exists()).toBe(true)
  })

  it('renders group list sidebar', () => {
    const wrapper = mountView()
    expect(wrapper.find('.aigc-list').exists()).toBe(true)
  })

  it('renders create group button', () => {
    const wrapper = mountView()
    expect(wrapper.find('.aigc-icon-btn').exists()).toBe(true)
  })

  it('shows loading text when no groups loaded', () => {
    const wrapper = mountView()
    expect(wrapper.find('.aigc-list__body .aigc-empty').text()).toContain('加载中')
  })

  it('loads groups on mount', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([sampleMessage])
    const wrapper = mountView()
    await flushPromises()
    expect(fetchAiGroups).toHaveBeenCalledWith('admin')
    expect(wrapper.find('.aigc-group__name').text()).toBe('测试群')
  })

  it('selects first group automatically on load', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([sampleMessage])
    const wrapper = mountView()
    await flushPromises()
    expect(fetchAiGroupMessages).toHaveBeenCalledWith('g1', 'admin')
    expect(wrapper.find('.aigc-chat__title').text()).toBe('测试群')
  })

  it('renders messages in chat body', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([sampleMessage])
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc-msg__bubble').text()).toContain('你好，有什么可以帮你？')
  })

  it('renders empty chat placeholder when no active group', async () => {
    fetchAiGroups.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc-chat--empty').exists()).toBe(true)
    expect(wrapper.find('.aigc-chat--empty').text()).toContain('选择左侧的群')
  })

  it('shows member count in chat header when present', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc-chat__sub').text()).toContain('2 个 AI 成员')
  })

  it('shows group member preview when no last_message_preview', async () => {
    const group = { ...sampleGroup, last_message_preview: '' }
    fetchAiGroups.mockResolvedValue([group])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc-group__sub').text()).toContain('2 个 AI 成员')
  })

  it('shows invite prompt when group has no members', async () => {
    const group = { ...sampleGroup, member_count: 0, last_message_preview: '' }
    fetchAiGroups.mockResolvedValue([group])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc-group__sub').text()).toContain('还没有成员')
  })

  it('disables send button when input is empty', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc-send').attributes('disabled')).toBeDefined()
  })

  it('enables send button when input has text', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-input').setValue('你好')
    expect(wrapper.find('.aigc-send').attributes('disabled')).toBeUndefined()
  })

  it('sends message when send button is clicked', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    postAiGroupMessage.mockResolvedValue({
      messages: [sampleMessage],
      group: sampleGroup,
    })
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-input').setValue('你好')
    await wrapper.find('.aigc-send').trigger('click')
    await flushPromises()
    expect(postAiGroupMessage).toHaveBeenCalledWith('g1', '你好', [], 'admin', { dispatch: false })
  })

  it('shows discussion badge for discussion messages', async () => {
    const discussionMsg = {
      ...sampleMessage,
      id: 'd1',
      kind: 'discussion',
      body: '我建议先对齐需求边界，再定负责人。',
    };
    fetchAiGroups.mockResolvedValue([sampleGroup]);
    fetchAiGroupMessages.mockResolvedValue([discussionMsg]);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('.aigc-msg__badge').text()).toBe('讨论');
    expect(wrapper.find('.aigc-msg').classes()).toContain('is-discussion');
  });

  it('shows needs-review badge for false acceptance', async () => {
    const acceptanceMsg = {
      ...sampleMessage,
      id: 'a1',
      kind: 'work_acceptance',
      status: 'needs_review',
      body: '【小C验收】需要复核 0/2',
    };
    fetchAiGroups.mockResolvedValue([sampleGroup]);
    fetchAiGroupMessages.mockResolvedValue([acceptanceMsg]);
    const wrapper = mountView();
    await flushPromises();
    expect(wrapper.find('.aigc-msg__badge').text()).toBe('待复核');
    expect(wrapper.find('.aigc-msg__badge').classes()).toContain('is-review');
  });

  it('sends message in dispatch mode when dispatch toggle is active', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    postAiGroupMessage.mockResolvedValue({
      messages: [
        {
          ...sampleMessage,
          id: 'work-1',
          kind: 'work_report',
          body: '【AI助手A 执行汇报】\n状态：完成',
        },
      ],
      group: sampleGroup,
    })
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-mode').trigger('click')
    await wrapper.find('.aigc-input').setValue('整理客户数据')
    await wrapper.find('.aigc-send').trigger('click')
    await flushPromises()
    expect(postAiGroupMessage).toHaveBeenCalledWith('g1', '整理客户数据', [], 'admin', { dispatch: true })
    expect(wrapper.text()).toContain('执行汇报')
  })

  it('shows typing indicator while sending', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    let resolvePost: (v: unknown) => void
    postAiGroupMessage.mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve
      }),
    )
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-input').setValue('你好')
    await wrapper.find('.aigc-send').trigger('click')
    await flushPromises()
    expect(wrapper.find('.aigc-typing').exists()).toBe(true)
    resolvePost!({ messages: [], group: null })
    await flushPromises()
    expect(wrapper.find('.aigc-typing').exists()).toBe(false)
  })

  it('clears input after sending', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    postAiGroupMessage.mockResolvedValue({ messages: [], group: null })
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-input').setValue('你好')
    await wrapper.find('.aigc-send').trigger('click')
    await flushPromises()
    expect((wrapper.find('.aigc-input').element as HTMLInputElement).value).toBe('')
  })

  it('toggles members panel when group members button is clicked', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc-members').exists()).toBe(false)
    await wrapper.find('.aigc-text-btn').trigger('click')
    expect(wrapper.find('.aigc-members').exists()).toBe(true)
  })

  it('renders existing members in members panel', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-text-btn').trigger('click')
    expect(wrapper.text()).toContain('AI助手A')
  })

  it('removes member when remove button is clicked', async () => {
    const updatedGroup = { ...sampleGroup, members: [] }
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    removeAiGroupMember.mockResolvedValue(updatedGroup)
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-text-btn').trigger('click')
    const removeBtn = wrapper.find('.aigc-text-btn--danger')
    await removeBtn.trigger('click')
    await flushPromises()
    expect(removeAiGroupMember).toHaveBeenCalledWith('g1', 'e1', 'admin')
  })

  it('creates new group when create button is clicked and prompt is filled', async () => {
    fetchAiGroups.mockResolvedValue([])
    createAiGroup.mockResolvedValue({ id: 'g2', name: '新群', member_count: 0, members: [] })
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('新群')
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-icon-btn').trigger('click')
    await flushPromises()
    expect(createAiGroup).toHaveBeenCalledWith('新群', 'admin')
    promptSpy.mockRestore()
  })

  it('does not create group when prompt is cancelled', async () => {
    fetchAiGroups.mockResolvedValue([])
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue(null)
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-icon-btn').trigger('click')
    await flushPromises()
    expect(createAiGroup).not.toHaveBeenCalled()
    promptSpy.mockRestore()
  })

  it('does not create group when prompt is empty', async () => {
    fetchAiGroups.mockResolvedValue([])
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('   ')
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-icon-btn').trigger('click')
    await flushPromises()
    expect(createAiGroup).not.toHaveBeenCalled()
    promptSpy.mockRestore()
  })

  it('loads employees on mount', async () => {
    fetchAiGroups.mockResolvedValue([])
    apiFetchMock.mockResolvedValue({
      json: async () => ({
        data: {
          items: [
            { id: 'e1', display_name: '员工1' },
            { id: 'e2', display_name: '员工2' },
          ],
        },
      }),
    } as Response)
    mountView()
    await flushPromises()
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/mobile/v1/admin/employees',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    )
  })

  it('shows empty state in chat when group has no messages', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc-chat__body .aigc-empty').exists()).toBe(true)
  })

  it('shows different empty state text when group has members vs no members', async () => {
    const groupWithMembers = { ...sampleGroup, member_count: 2 }
    fetchAiGroups.mockResolvedValue([groupWithMembers])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc-chat__body .aigc-empty').text()).toContain('发条消息试试')
  })

  it('renders user message with is-user class', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    const userMsg = { ...sampleMessage, id: 'm2', role: 'user', body: '用户消息' }
    postAiGroupMessage.mockResolvedValue({ messages: [userMsg], group: null })
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-input').setValue('用户消息')
    await wrapper.find('.aigc-send').trigger('click')
    await flushPromises()
    const userMsgEl = wrapper.findAll('.aigc-msg').find((m) => m.classes().includes('is-user'))
    expect(userMsgEl).toBeTruthy()
    expect(userMsgEl!.text()).toContain('用户消息')
  })

  it('handles fetchAiGroups error gracefully', async () => {
    fetchAiGroups.mockRejectedValue(new Error('network'))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc').exists()).toBe(true)
  })

  it('handles fetchAiGroupMessages error gracefully', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockRejectedValue(new Error('network'))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.aigc-chat').exists()).toBe(true)
  })

  it('handles postAiGroupMessage error gracefully', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    postAiGroupMessage.mockRejectedValue(new Error('send failed'))
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-input').setValue('你好')
    await wrapper.find('.aigc-send').trigger('click')
    await flushPromises()
    expect(wrapper.find('.aigc-typing').exists()).toBe(false)
  })

  it('renders AI avatar with first character of sender_name', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([sampleMessage])
    const wrapper = mountView()
    await flushPromises()
    const avatar = wrapper.find('.aigc-msg__avatar')
    expect(avatar.exists()).toBe(true)
    expect(avatar.text()).toBe('A')
  })

  it('uses "AI" as fallback when sender_name is empty', async () => {
    const msg = { ...sampleMessage, sender_name: '' }
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([msg])
    const wrapper = mountView()
    await flushPromises()
    const avatar = wrapper.find('.aigc-msg__avatar')
    expect(avatar.text()).toBe('A')
  })

  it('selects a group when group item is clicked', async () => {
    const g1 = { ...sampleGroup, id: 'g1', name: '群1' }
    const g2 = { ...sampleGroup, id: 'g2', name: '群2', members: [] }
    fetchAiGroups.mockResolvedValue([g1, g2])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    fetchAiGroupMessages.mockClear()
    const groups = wrapper.findAll('.aigc-group')
    await groups[1].trigger('click')
    await flushPromises()
    expect(fetchAiGroupMessages).toHaveBeenCalledWith('g2', 'admin')
  })

  it('marks selected group as active', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    const group = wrapper.find('.aigc-group')
    expect(group.classes()).toContain('is-active')
  })

  it('sends message on enter key in input', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    postAiGroupMessage.mockResolvedValue({ messages: [], group: null })
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-input').setValue('回车发送')
    await wrapper.find('.aigc-input').trigger('keyup.enter')
    await flushPromises()
    expect(postAiGroupMessage).toHaveBeenCalled()
  })

  it('does not send empty message on enter', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-input').trigger('keyup.enter')
    await flushPromises()
    expect(postAiGroupMessage).not.toHaveBeenCalled()
  })

  it('does not send when already sending', async () => {
    fetchAiGroups.mockResolvedValue([sampleGroup])
    fetchAiGroupMessages.mockResolvedValue([])
    let resolvePost: (v: unknown) => void
    postAiGroupMessage.mockReturnValue(
      new Promise((resolve) => {
        resolvePost = resolve
      }),
    )
    const wrapper = mountView()
    await flushPromises()
    await wrapper.find('.aigc-input').setValue('第一条')
    await wrapper.find('.aigc-send').trigger('click')
    await flushPromises()
    postAiGroupMessage.mockClear()
    await wrapper.find('.aigc-input').setValue('第二条')
    await wrapper.find('.aigc-send').trigger('click')
    await flushPromises()
    expect(postAiGroupMessage).not.toHaveBeenCalled()
    resolvePost!({ messages: [], group: null })
    await flushPromises()
  })
})
