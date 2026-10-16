import { describe, expect, it, vi } from 'vitest'
import * as entries from '../useMessengerEntries'
import type { CodexSuperEmployeeMessage } from '@/api/codexSuperEmployee'

const duty = entries.normalizeDutyEmployee({ id: 'custom', name: 'Alice' })!
const message = (extra: Record<string, unknown> = {}) => ({ role: 'assistant', body: '', ...extra }) as CodexSuperEmployeeMessage

describe('messenger entry labels and dispatch outcomes', () => {
  it.each([
    [entries.CODEX_SUPER_EMPLOYEE_ENTRY, 'Codex', 'codex'],
    [entries.CLAUDE_SUPER_EMPLOYEE_ENTRY, 'Claude', 'claude'],
    [entries.CURSOR_SUPER_EMPLOYEE_ENTRY, 'Cursor', 'cursor'],
  ] as const)('presents %s consistently across the sidebar and dispatcher', (entry, label, key) => {
    expect(entries.superEmployeeAvatarKey(entry)).toBe(key)
    expect(entries.superEmployeeAvatarSrc(entry)).toContain(key)
    expect(entries.pinnedAvatarText(entry)).toBe(label)
    expect(entries.pinnedEntryPreview(entry)).toBe(entry.subtitle)
    expect(entries.superCliToolLabel(entry)).toBe(label)
    expect(entries.systemEntryStatusLabel(entry)).toBe('多设备调度')
    expect(entries.systemEntryIdentity(entry)).toBe('跨设备协作开发员工')
    expect(entries.systemEntryDispatch(entry)).toBe(`全设备 ${label}`)
  })
  it.each([
    [entries.KELLAI_CUSTOMER_IM_ENTRY, '客'], [entries.AI_GROUP_CHAT_ENTRY, '群'],
    [duty, 'A'], [{ ...duty, avatar_text: '', display_name: 'Bob' }, 'B'],
    [{ id: 1, display_name: 'Cathy', username: 'cathy' }, 'C'],
  ])('renders non-CLI entry %j', (raw, avatar) => {
    const entry = raw as entries.PinnedImEntry
    expect(entries.pinnedAvatarText(entry)).toBe(avatar)
    expect(entries.pinnedEntryPreview(entry)).toBe('subtitle' in entry ? entry.subtitle : '@cathy')
    expect(entries.superEmployeeAvatarKey(entry)).toBeNull()
    expect(entries.superEmployeeAvatarSrc(entry)).toBeNull()
  })
  it.each([['admin-duty', '管理端工作台'], ['mobile', '手机端会话'], ['mobile-chat', '手机端会话'],
    ['super', '超级员工调度'], [' custom ', 'custom'], ['', '员工通讯录']])('formats contact channel %s', (channel, label) => {
    expect(entries.dutyContactLabel(channel)).toBe(label)
    expect(entries.systemEntryDispatch({ ...duty, phone_channel: channel })).toBe(label)
  })
  it('preserves explicit roster data and deduplicates employees without replacing the first entry', () => {
    const explicit = entries.normalizeDutyEmployee({ id: ' x ', label: ' Label ', description: ' Detail ', industry: ' Industry ',
      phone_channel: 'mobile', api_base_path: ' /custom ', status: 'planned' })!
    expect(explicit).toMatchObject({ id: 'x', display_name: 'Label', description: 'Detail', area: 'Industry', api_base_path: '/custom' })
    expect(entries.normalizeDutyEmployee({ id: 'x', title: 'Title', panel_summary: 'Panel', yuangon_area: 'Area' })).toMatchObject({ display_name: 'Title', description: 'Panel', area: 'Area' })
    expect(entries.normalizeDutyEmployee({ id: 'x', name: ' ' })?.display_name).toBe('x')
    expect(entries.uniqueDutyEmployees([explicit, { ...explicit, display_name: 'replacement' }])).toEqual([explicit])
    expect(entries.superCliToolLabel(explicit)).toBe('Label')
    expect(entries.systemEntryStatusLabel(explicit)).toBe('编制员工')
    expect(entries.systemEntryStatusLabel(duty)).toBe('在岗员工')
    expect(entries.systemEntryIdentity(explicit)).toBe('Industry')
    expect(entries.systemEntryIdentity({ ...duty, area: '' })).toBe('管理端编制员工')
  })
  it.each([false, true])('recognizes enterprise dedicated contacts by flag or canonical identity, flag=%s', (flag) => {
    expect(entries.isEnterpriseDedicatedContact({ username: flag ? 'other' : ' Enterprise-CS ', is_enterprise_dedicated_cs: flag } as never)).toBe(true)
    expect(entries.isEnterpriseDedicatedConversation({ title: flag ? 'other' : ' 企业专属客服 ', is_enterprise_dedicated_cs: flag } as never)).toBe(true)
    expect(entries.isEnterpriseDedicatedContact({ username: 'regular' } as never)).toBe(false)
    expect(entries.isEnterpriseDedicatedConversation({ title: 'regular' } as never)).toBe(false)
  })
  it.each([
    [{ role: 'system' }, true, false], [{ kind: 'dispatcher' }, true, false], [{ role: 'user' }, false, false],
    [{ status: 'running', body: '调度器已派发' }, true, false], [{ status: 'running', body: 'actual answer' }, false, true],
    [{ kind: 'task_result', role: 'user' }, false, true], [{}, false, true],
  ])('classifies dispatch message %j', (raw, dispatcher, result) => {
    expect(entries.isCodexDispatcherMessage(message(raw))).toBe(dispatcher)
    expect(entries.isCodexResultMessage(message(raw))).toBe(result)
    expect(entries.isCodexStreamingMessage(message({ ...raw, streaming: true }))).toBe(true)
    expect(entries.isCodexStreamingMessage(message(raw))).toBe(false)
  })
  it.each([
    [null, '正在连接全设备'], [{ body: '未发现在线可用 Codex 设备' }, '等待设备上线'],
    [{ body: '任务运行中，进度 20%' }, '进度 20%'], [{ status: 'queued' }, '排队等待'],
    [{ status: 'accepted' }, '正在连接全设备'], [{ task_status: 'RUNNING' }, '正在连接全设备'],
    [{ body: 'answer' }, 'answer'], [{}, '正在处理'],
  ])('explains dispatcher state %j', (raw, expected) => {
    expect(entries.codexReplyFromDispatcher(raw ? message(raw) : null)).toContain(expected)
  })
  it('selects the latest matching request without mutating history and recognizes terminal states', () => {
    const old = message({ kind: 'dispatcher', dispatch_request_id: 'a' })
    const answer = message({ kind: 'task_result', dispatch_request_id: 'a' })
    const other = message({ kind: 'dispatcher', dispatch_request_id: 'b' })
    const items = [old, answer, other]
    expect(entries.latestCodexDispatcherMessage(items)).toBe(other)
    expect(entries.latestCodexDispatcherMessage(items, 'a')).toBe(old)
    expect(entries.latestCodexResultMessage(items, 'a')).toBe(answer)
    expect(entries.latestCodexResultMessage(items)).toBe(answer)
    expect(entries.latestCodexResultMessage(items, 'missing')).toBeNull()
    expect(entries.latestCodexDispatcherMessage([], 'missing')).toBeNull()
    expect(items).toEqual([old, answer, other])
    for (const status of ['completed', 'merged', 'failed', 'merge_conflict', 'dispatch_failed', 'dispatch_error']) {
      expect(entries.isCodexDispatchStillOpen(message({ task_status: status }))).toBe(false)
    }
    expect(entries.isCodexDispatchStillOpen(message({ status: 'running' }))).toBe(true)
    expect(entries.isCodexDispatchStillOpen(null)).toBe(false)
  })
  it('sanitizes dispatcher jargon and formats invalid dates safely', () => {
    expect(entries.sanitizeCodexReplyText('排比 Para/Codex 多设备调度器 跨设备调度器 多设备调度器 调度器 Para/Codex Para 任务 调用队列 任务 ID: abc-123 。')).toBe('全设备 Codex 全设备 Codex 全设备 Codex Codex Codex Codex 任务 任务队列。')
    expect(entries.sanitizeCodexReplyText('')).toBe('')
    expect(entries.formatTime(null)).toBe('')
    const spy = vi.spyOn(Date.prototype, 'toLocaleString').mockImplementationOnce(() => { throw new Error('locale') })
    expect(entries.formatTime('original')).toBe('original')
    spy.mockRestore()
  })
  it.each([
    [{ data: { result: { outputs: [{ output: 'nested' }] } } }, 'nested'],
    [{ data: { outputs: [null, { output: { reply: 'reply' } }, { message: 'message' }] } }, 'reply\n\nmessage'],
    [{ data: { message: 'direct' } }, 'direct'], [{ data: { result: { response: 'response' } } }, 'response'],
    [{ data: { summary: 'summary' } }, 'summary'], [{ data: { result: { summary: 'inner summary' } } }, 'inner summary'],
    [{ message: 'root' }, 'root'], [{ success: false, data: { error: 'broken' } }, '执行失败：broken'],
    [{ data: { success: false, result: { detail: 'inner error' } } }, '执行失败：inner error'],
    [{ success: false, error: 'root error' }, '执行失败：root error'], [{ success: false }, '执行失败：员工运行时未返回详细原因'],
    [{ success: false, message: 'failure text' }, '执行失败：failure text'],
  ])('extracts employee execution result %j', (result, expected) => {
    expect(entries.dutyEmployeeReplyFromExecution(result, duty)).toBe(expected)
  })
  it('handles empty, scalar and cyclic employee output without losing the completion notice', () => {
    expect(entries.firstTextFromRecord({ blank: ' ', n: 0 }, ['blank', 'n'])).toBe('0')
    expect(entries.firstTextFromRecord({ flag: false }, ['flag'])).toBe('false')
    expect(entries.firstTextFromRecord(null, ['key'])).toBe('')
    for (const value of [null, [], 'text']) expect(entries.asRecord(value)).toBeNull()
    expect(entries.textFromEmployeeOutputs({ outputs: [{ output: {} }] })).toBe('')
    const cyclic: Record<string, unknown> = {}; cyclic.self = cyclic
    expect(entries.shortJson(cyclic)).toBe('')
    expect(entries.shortJson('x'.repeat(1300))).toHaveLength(1201)
    expect(entries.dutyEmployeeReplyFromExecution({ data: cyclic }, duty)).toBe('Alice 已完成执行，但没有返回可读文本。')
    expect(entries.dutyEmployeeReplyFromExecution({ data: { count: 2 } }, duty)).toContain('"count": 2')
  })
})
