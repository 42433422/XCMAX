import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useChatSession } from '@/composables/messenger/useChatSession'
import { useContactPicker } from '@/composables/messenger/useContactPicker'
import {
  isSuperEmployeeEntry,
  isDutyEmployeeEntry,
  isCodexSuperEmployeeEntry,
  avatarText,
  normalizeDutyEmployee,
} from '@/composables/messenger/useMessengerEntries'

const contactsMock = vi.hoisted(() => ({
  fetchImContacts: vi.fn(async () => []),
}))
vi.mock('@/api/im', () => contactsMock)
vi.mock('@/composables/useAppToast', () => ({
  showAppToast: vi.fn(),
}))

describe('useChatSession', () => {
  const conversations = ref([])
  const activeConversationId = ref<number | null>(null)
  const localUserId = ref<number | null>(1)

  beforeEach(() => {
    conversations.value = []
    activeConversationId.value = null
    localUserId.value = 1
  })

  it('为普通会话按 sender_user_id 判定我方/对方气泡', () => {
    const { isMyMessage } = useChatSession({
      conversations,
      activeConversationId,
      localUserId,
    })
    conversations.value = [
      {
        id: 5,
        title: '张三',
        is_direct: true,
        last_message_at: null,
        last_message_preview: '',
        unread_count: 0,
      },
    ]
    activeConversationId.value = 5
    expect(isMyMessage({ id: 1, conversation_id: 5, sender_user_id: 1, body: 'hi', created_at: null })).toBe(true)
    expect(isMyMessage({ id: 2, conversation_id: 5, sender_user_id: 2, body: 'yo', created_at: null })).toBe(false)
  })

  it('CS 收件箱会话里非客户发送者即我方', () => {
    const { isMyMessage } = useChatSession({
      conversations,
      activeConversationId,
      localUserId,
    })
    conversations.value = [
      {
        id: 9,
        title: '某企业客户',
        is_direct: true,
        last_message_at: null,
        last_message_preview: '',
        unread_count: 0,
        is_cs_inbox: true,
        customer_user_id: 42,
      },
    ]
    activeConversationId.value = 9
    expect(isMyMessage({ id: 1, conversation_id: 9, sender_user_id: 42, body: '客户', created_at: null })).toBe(false)
    expect(isMyMessage({ id: 2, conversation_id: 9, sender_user_id: 7, body: '运营', created_at: null })).toBe(true)
  })

  it('按 ws/api 可达性派生连接文案与样式', () => {
    const session = useChatSession({ conversations, activeConversationId, localUserId })
    expect(session.imConnectionClass.value).toBe('is-error')
    expect(session.imConnectionLabel.value).toBe('连接失败')

    session.wsConnecting.value = true
    expect(session.imConnectionClass.value).toBe('is-off')
    expect(session.imConnectionLabel.value).toBe('正在连接...')

    session.wsConnecting.value = false
    session.imApiReachable.value = true
    expect(session.imConnectionClass.value).toBe('is-api-on')
    expect(session.imConnectionLabel.value).toBe('接口已连接')

    session.wsConnected.value = true
    expect(session.imConnectionClass.value).toBe('is-on')
    expect(session.imConnectionLabel.value).toBe('实时已连接')
  })

  it('活跃标题取会话标题，缺省回退"会话"', () => {
    const { activeTitle } = useChatSession({ conversations, activeConversationId, localUserId })
    expect(activeTitle.value).toBe('会话')
    conversations.value = [
      {
        id: 3,
        title: '李四',
        is_direct: true,
        last_message_at: null,
        last_message_preview: '',
        unread_count: 0,
      },
    ]
    activeConversationId.value = 3
    expect(activeTitle.value).toBe('李四')
  })
})

describe('useContactPicker', () => {
  const imApiReachable = ref(false)

  beforeEach(() => {
    imApiReachable.value = false
    contactsMock.fetchImContacts.mockReset()
  })

  it('过滤掉企业专属客服联系人', async () => {
    contactsMock.fetchImContacts.mockResolvedValue([
      { id: 1, display_name: '张三', username: 'zhangsan' },
      {
        id: 99,
        display_name: '企业专属客服',
        username: 'enterprise-cs',
        is_enterprise_dedicated_cs: true,
      },
    ])
    const picker = useContactPicker({ imApiReachable })
    await picker.openContactPicker()
    expect(picker.contactPickerOpen.value).toBe(true)
    expect(picker.filteredContacts.value.map((c) => c.id)).toEqual([1])
    expect(imApiReachable.value).toBe(true)
  })

  it('按姓名/账号关键字本地过滤', async () => {
    contactsMock.fetchImContacts.mockResolvedValue([
      { id: 1, display_name: '张三', username: 'zhangsan' },
      { id: 2, display_name: 'Li Si', username: 'lisi' },
    ])
    const picker = useContactPicker({ imApiReachable })
    await picker.loadContacts()
    picker.contactKeyword.value = 'LI'
    expect(picker.filteredContacts.value.map((c) => c.id)).toEqual([2])
    picker.contactKeyword.value = 'zhang'
    expect(picker.filteredContacts.value.map((c) => c.id)).toEqual([1])
  })

  it('closeContactPicker 关闭弹窗', async () => {
    const picker = useContactPicker({ imApiReachable })
    await picker.openContactPicker()
    picker.closeContactPicker()
    expect(picker.contactPickerOpen.value).toBe(false)
  })
})

describe('useMessengerEntries 纯函数', () => {
  it('isSuperEmployeeEntry / isCodexSuperEmployeeEntry 识别超级员工', () => {
    const codex = {
      id: 'codex-super-employee',
      display_name: 'x',
      username: 'x',
      subtitle: 'x',
      is_codex_super_employee: true,
    }
    const duty = {
      id: 'e1',
      display_name: 'x',
      username: 'x',
      subtitle: 'x',
      description: '',
      area: '',
      status: '',
      api_base_path: '',
      phone_channel: '',
      is_duty_employee_entry: true,
    }
    expect(isSuperEmployeeEntry(codex)).toBe(true)
    expect(isCodexSuperEmployeeEntry(codex)).toBe(true)
    expect(isDutyEmployeeEntry(duty)).toBe(true)
    expect(isSuperEmployeeEntry(duty)).toBe(false)
    expect(isSuperEmployeeEntry(null)).toBe(false)
  })

  it('avatarText 取首字母大写，空名回退 ?', () => {
    expect(avatarText('张三')).toBe('张')
    expect(avatarText('codex')).toBe('C')
    expect(avatarText('')).toBe('?')
    expect(avatarText('  ')).toBe('?')
  })

  it('normalizeDutyEmployee 归一化员工条目', () => {
    const entry = normalizeDutyEmployee({ id: 'ops', name: '运维', status: 'on_duty' })
    expect(entry).not.toBeNull()
    expect(entry!.id).toBe('ops')
    expect(entry!.display_name).toBe('运维')
    expect(entry!.is_duty_employee_entry).toBe(true)
    expect(normalizeDutyEmployee({})).toBeNull()
  })
})
