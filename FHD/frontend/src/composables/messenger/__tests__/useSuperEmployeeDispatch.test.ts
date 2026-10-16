import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { useSuperEmployeeDispatch, type UseSuperEmployeeDispatchParams } from '../useSuperEmployeeDispatch'
import * as entries from '../useMessengerEntries'

const m = vi.hoisted(() => ({ admin: false, get: vi.fn(), post: vi.fn(), ssot: vi.fn(), toast: vi.fn(),
  codexFetch: vi.fn(), codexSend: vi.fn(), claudeFetch: vi.fn(), claudeSend: vi.fn(), cursorFetch: vi.fn(), cursorSend: vi.fn() }))
vi.mock('@/api', () => ({ default: { get: m.get, post: m.post } }))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa: () => m.admin }))
vi.mock('@/utils/platformShellApi', () => ({ fetchEmployeeSsot: m.ssot }))
vi.mock('@/composables/useAppToast', () => ({ showAppToast: m.toast }))
vi.mock('@/api/codexSuperEmployee', () => ({ fetchCodexSuperEmployeeMessages: m.codexFetch, sendCodexSuperEmployeeMessage: m.codexSend }))
vi.mock('@/api/claudeSuperEmployee', () => ({ fetchClaudeSuperEmployeeMessages: m.claudeFetch, sendClaudeSuperEmployeeMessage: m.claudeSend }))
vi.mock('@/api/cursorSuperEmployee', () => ({ fetchCursorSuperEmployeeMessages: m.cursorFetch, sendCursorSuperEmployeeMessage: m.cursorSend }))
const duty = entries.normalizeDutyEmployee({ id: 'agent/test', name: 'Agent' })!
function setup(admin = true) {
  m.admin = admin
  const p: UseSuperEmployeeDispatchParams = {
    activeSystemEntry: ref(null), activeExternalEntry: ref(null), activeConversationId: ref(42), activeGroupChat: ref(false),
    messages: ref([]), hasMoreHistory: ref(true), localUserId: ref(7), isAdminCustomerServiceConsole: ref(admin),
    imApiReachable: ref(false), dutyEmployees: ref([]), closeContactPicker: vi.fn(), startChatWith: vi.fn(async () => {}),
    closeOverlappingAssistantFloat: vi.fn(), restoreOverlappingAssistantFloat: vi.fn(),
  }
  return { p, s: useSuperEmployeeDispatch(p) }
}
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(1000)
  for (const fn of [m.get, m.post, m.ssot, m.toast, m.codexFetch, m.codexSend, m.claudeFetch, m.claudeSend, m.cursorFetch, m.cursorSend]) fn.mockReset()
  for (const fetch of [m.codexFetch, m.claudeFetch, m.cursorFetch]) fetch.mockResolvedValue([])
  m.ssot.mockResolvedValue({}); m.get.mockResolvedValue({}); m.post.mockResolvedValue({ data: { message: 'done' } })
})
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks() })

describe('super employee dispatch and conversation transitions', () => {
  it.each([
    [entries.CODEX_SUPER_EMPLOYEE_ENTRY, 'Codex', m.codexFetch, m.codexSend],
    [entries.CLAUDE_SUPER_EMPLOYEE_ENTRY, 'Claude', m.claudeFetch, m.claudeSend],
    [entries.CURSOR_SUPER_EMPLOYEE_ENTRY, 'Cursor', m.cursorFetch, m.cursorSend],
  ] as const)('routes %s history and messages to the matching service', async (entry, label, fetch, send) => {
    const { p, s } = setup()
    await s.activatePinnedEntry(entry)
    expect(fetch).toHaveBeenCalledWith({ scope: 'admin' })
    expect(p.activeSystemEntry.value?.id).toBe(entry.id)
    expect(p.activeConversationId.value).toBeNull()
    expect(p.hasMoreHistory.value).toBe(false)
    expect(s.codexMessageRoleLabel({ role: 'assistant' } as never)).toBe(label)
    expect(s.codexMessageRoleLabel({ role: 'user' } as never)).toBe('管理端')
    send.mockResolvedValue({ messages: [], dispatch: { status: 'accepted' }, message: { dispatch_request_id: 'r1' } })
    s.codexDraft.value = '  hello  '
    await s.onCodexSend()
    expect(send).toHaveBeenCalledWith('hello', { source: 'admin_im', client_surface: 'admin_console', target_devices: ['all'] }, { scope: 'admin' })
    expect(s.codexDraft.value).toBe('')
    expect(s.codexBusy.value).toBe(false)
    expect(s.codexLastStatus.value).toBe('已分发')
  })
  it.each([entries.AI_GROUP_CHAT_ENTRY, entries.KELLAI_CUSTOMER_IM_ENTRY, duty])('switches pinned entry %j without stale conversation history', async (entry) => {
    const { p, s } = setup()
    const scroll = { scrollTop: 0, scrollHeight: 123 } as HTMLElement
    s.dutyEmployeeScrollEl.value = scroll
    await s.activatePinnedEntry(entry)
    expect(p.closeOverlappingAssistantFloat).toHaveBeenCalledOnce()
    expect(p.closeContactPicker).toHaveBeenCalledOnce()
    expect(p.messages.value).toEqual([])
    expect(p.activeConversationId.value).toBeNull()
    if (entry === entries.AI_GROUP_CHAT_ENTRY) expect(p.activeGroupChat.value).toBe(true)
    else if (entry === entries.KELLAI_CUSTOMER_IM_ENTRY) expect(p.activeExternalEntry.value?.id).toBe(entry.id)
    else { expect(p.activeSystemEntry.value?.id).toBe(duty.id); expect(scroll.scrollTop).toBe(123) }
  })
  it('restores ordinary chat and suppresses sends without an active employee, while busy, or with blank input', async () => {
    const { p, s } = setup()
    const contact = { id: 5, display_name: 'User', username: 'user' }
    await s.activatePinnedEntry(contact)
    expect(p.startChatWith).toHaveBeenCalledWith(contact)
    expect(p.restoreOverlappingAssistantFloat).toHaveBeenCalledOnce()
    await s.onCodexSend(); await s.onDutyEmployeeSend()
    p.activeSystemEntry.value = entries.CODEX_SUPER_EMPLOYEE_ENTRY
    s.codexBusy.value = true; s.codexDraft.value = 'task'; await s.onCodexSend()
    s.codexBusy.value = false; s.codexDraft.value = ' '; await s.onCodexSend()
    p.activeSystemEntry.value = duty; s.dutyEmployeeBusy.value = true; await s.onDutyEmployeeSend()
    s.dutyEmployeeBusy.value = false; s.dutyEmployeeDraft.value = ' '; await s.onDutyEmployeeSend()
    expect(m.codexSend).not.toHaveBeenCalled(); expect(m.post).not.toHaveBeenCalled()
    expect(s.activeDutyEmployeeMessages.value).toEqual([])
  })
  it.each([false, true])('submits duty work with the correct surface and preserves replies, admin=%s', async (admin) => {
    const { p, s } = setup(admin)
    p.activeSystemEntry.value = duty; p.localUserId.value = admin ? 7 : null
    s.dutyEmployeeDraft.value = '  work  '
    expect(s.systemEntryLastStatus(duty)).toBe('等待任务')
    await s.onDutyEmployeeSend()
    expect(m.post).toHaveBeenCalledWith('/api/xcmax/local/employees/agent%2Ftest/execute', expect.objectContaining({ task: 'work', user_id: admin ? 7 : 0,
      input_data: expect.objectContaining({ source: admin ? 'admin_im' : 'enterprise_im', client_surface: admin ? 'admin_console' : 'enterprise_client' }) }))
    expect(s.activeDutyEmployeeMessages.value.map((row) => [row.role, row.body])).toEqual([['user', 'work'], ['assistant', 'done']])
    expect(s.systemEntryLastStatus(duty)).toBe('已回复')
    expect(s.dutyEmployeeDraft.value).toBe(''); expect(s.dutyEmployeeBusy.value).toBe(false)
    expect(s.codexSenderLabel.value).toBe(admin ? '管理端' : '手机端')
  })
  it.each([new Error('offline'), 'unknown'])('shows failed dispatch and employee errors without leaving busy state: %s', async (error) => {
    const { p, s } = setup()
    p.activeSystemEntry.value = entries.CODEX_SUPER_EMPLOYEE_ENTRY; s.codexDraft.value = 'task'
    m.codexSend.mockRejectedValue(error); await s.onCodexSend()
    expect(m.toast).toHaveBeenCalledWith(error instanceof Error ? 'offline' : 'Codex 调用失败', 'error')
    expect(s.codexBusy.value).toBe(false); expect(s.codexStreamBody.value).toBe('')
    m.codexFetch.mockRejectedValue(error); await s.loadCodexConversation()
    expect(m.toast).toHaveBeenCalledWith(error instanceof Error ? 'offline' : '加载 Codex 对话失败', 'error')
    p.activeSystemEntry.value = duty; s.dutyEmployeeDraft.value = 'task'; m.post.mockRejectedValue(error)
    await s.onDutyEmployeeSend()
    expect(s.activeDutyEmployeeMessages.value.at(-1)).toMatchObject({ status: '失败', body: error instanceof Error ? '调用失败：offline' : '调用失败：未知错误' })
    expect(s.dutyEmployeeBusy.value).toBe(false)
  })
  it('rejects uninstalled employees and renders busy and last-message states', async () => {
    const { p, s } = setup()
    p.activeSystemEntry.value = { ...duty, status: 'planned' }; s.dutyEmployeeDraft.value = 'work'
    await s.onDutyEmployeeSend()
    expect(m.toast).toHaveBeenCalledWith(expect.stringContaining('尚未安装'), 'warning')
    expect(m.post).not.toHaveBeenCalled()
    expect(s.systemEntryRuntimeStatus(p.activeSystemEntry.value)).toBe('未安装')
    p.activeSystemEntry.value = duty; s.dutyEmployeeBusy.value = true
    expect(s.systemEntryRuntimeStatus(duty)).toBe('执行中')
    expect(s.systemEntryRuntimeStatus({ ...duty, id: 'other' })).toBe('可对话')
    s.codexBusy.value = true; expect(s.systemEntryRuntimeStatus(entries.CODEX_SUPER_EMPLOYEE_ENTRY)).toBe('提交中')
    s.codexBusy.value = false; s.codexStreamActive.value = true
    expect(s.systemEntryRuntimeStatus(entries.CODEX_SUPER_EMPLOYEE_ENTRY)).toBe('回复中')
    s.codexStreamActive.value = false; expect(s.systemEntryRuntimeStatus(entries.CODEX_SUPER_EMPLOYEE_ENTRY)).toBe('可派工')
    for (const [status, label] of [['', '等待派工'], ['queued', '已入队'], ['dispatch_failed', '待重试'], ['dispatch_error', '待重试'], ['completed', 'completed']]) {
      s.codexDispatch.value = { status } as never; expect(s.systemEntryLastStatus(entries.CODEX_SUPER_EMPLOYEE_ENTRY)).toBe(label)
    }
    s.appendDutyEmployeeMessage(duty.id, { id: '1', role: 'user', body: 'question', created_at: '' })
    expect(s.systemEntryLastStatus(duty)).toBe('已发送')
    s.appendDutyEmployeeMessage(duty.id, { id: '2', role: 'assistant', body: 'answer', created_at: '' })
    expect(s.systemEntryLastStatus(duty)).toBe('已回复')
    p.activeSystemEntry.value = null; expect(s.activeDutyEmployeeMessages.value).toEqual([])
  })
  it.each(['items', 'employees', 'missing', 'error', 'ssot', 'enterprise'] as const)('loads employee roster from %s', async (mode) => {
    const { p, s } = setup(mode !== 'enterprise')
    if (mode === 'ssot' || mode === 'enterprise') m.ssot.mockResolvedValue({ contacts: [{ employee_id: 'intake-dispatcher', display_name: 'Dispatch', installed: true }] })
    else m.ssot.mockRejectedValue(new Error('offline'))
    if (mode === 'error') m.get.mockRejectedValue(new Error('directory failed'))
    else if (mode !== 'missing') m.get.mockResolvedValue({ data: { [mode]: [{ id: 'worker', name: 'Worker' }, {}, { id: 'worker' }] } })
    await s.loadDutyEmployees()
    expect(p.dutyEmployees.value.length).toBeGreaterThan(0)
    if (mode === 'items' || mode === 'employees') expect(p.dutyEmployees.value.map((row) => row.id)).toEqual(['worker'])
    if (mode === 'ssot') expect(p.dutyEmployees.value[0].id).toBe('intake-dispatcher')
    if (mode === 'enterprise') { expect(p.dutyEmployees.value).toHaveLength(7); expect(m.get).not.toHaveBeenCalled() }
    if (mode === 'error') expect(m.toast).toHaveBeenCalledWith(expect.any(String), 'warning')
    else expect(p.imApiReachable.value).toBe(true)
  })
  it('streams pending dispatches and replaces the placeholder when polling receives a result', async () => {
    const { p, s } = setup()
    p.activeSystemEntry.value = entries.CODEX_SUPER_EMPLOYEE_ENTRY
    const dispatch = { id: 'd1', role: 'system', kind: 'dispatcher', status: 'running', body: '任务运行中', dispatch_request_id: 'r1', created_at: '' }
    m.codexFetch.mockResolvedValueOnce([dispatch]).mockResolvedValue([{ id: 'answer', role: 'assistant', kind: 'task_result', body: 'complete answer', dispatch_request_id: 'r1' }])
    await s.loadCodexConversation()
    expect(s.codexVisibleMessages.value).toEqual([expect.objectContaining({ synthetic: true, streaming: true })])
    await vi.advanceTimersByTimeAsync(4500)
    expect(s.codexVisibleMessages.value).toEqual([expect.objectContaining({ id: 'answer', body: 'complete answer', streaming: false })])
    s.stopCodexPolling(); s.stopCodexTypewriter(true)
    expect(s.codexStreamBody.value).toBe('')
    m.codexFetch.mockResolvedValue([dispatch]); await s.loadCodexConversation({ syncStream: false })
    expect(s.codexVisibleMessages.value).toEqual([])
    p.isAdminCustomerServiceConsole.value = false; m.codexFetch.mockClear(); await s.loadCodexConversation()
    expect(m.codexFetch).not.toHaveBeenCalled()
  })
  it('restores keyboard focus after activation and tolerates browsers without focus options', async () => {
    const { p, s } = setup()
    p.activeSystemEntry.value = entries.CODEX_SUPER_EMPLOYEE_ENTRY
    const focus = vi.fn().mockImplementationOnce(() => { throw new Error('unsupported') })
    s.codexInputEl.value = { focus } as unknown as HTMLInputElement
    s.focusCodexInput(); await nextTick()
    expect(focus).toHaveBeenCalledWith({ preventScroll: true }); expect(focus).toHaveBeenCalledWith()
    await vi.advanceTimersByTimeAsync(600)
    expect(focus).toHaveBeenCalledTimes(5)
  })
})
