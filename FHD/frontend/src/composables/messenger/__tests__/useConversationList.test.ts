import { expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useConversationList } from '../useConversationList'
import { isAiGroupChatEntry } from '../useMessengerEntries'

it('places individual groups alongside employees and selects only the opened group', () => {
  const isAdmin = ref(true), activeGroupChat = ref(true), activeAiGroupId = ref<string | null>('staff')
  const groups = ref(['staff', 'department'].map(id => ({ id, name: id === 'staff' ? '员工大群' : '部门群',
    member_count: 60, members: [], department_key: '', last_message_at: '', last_message_preview: '' })))
  const activatePinnedEntry = vi.fn()
  const list = useConversationList({
    conversations: ref([]), contacts: ref([]), dutyEmployees: ref([]), activeConversationId: ref(null),
    activeSystemEntry: ref(null), activeExternalEntry: ref(null), activeGroupChat, activeAiGroupId, groups,
    isAdminCustomerServiceConsole: isAdmin, selectConversation: vi.fn(), activatePinnedEntry,
  })
  const entries = list.sidebarListItems.value
  expect(entries.slice(0, 3).map(list.sidebarItemTitle)).toEqual(['员工大群', '部门群', '超级员工-Codex'])
  expect(list.isSidebarItemActive(entries[0])).toBe(true)
  expect(list.isSidebarItemActive(entries[1])).toBe(false)
  list.selectSidebarItem(entries[1])
  expect(activatePinnedEntry).toHaveBeenCalledWith(expect.objectContaining({ group_id: 'department' }))
  activeGroupChat.value = false
  expect(list.isSidebarItemActive(entries[0])).toBe(false)
  isAdmin.value = false
  expect(list.pinnedContacts.value.some(isAiGroupChatEntry)).toBe(false)
})
