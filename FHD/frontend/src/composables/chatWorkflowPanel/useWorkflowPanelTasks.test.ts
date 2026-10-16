import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useWorkflowPanelTasks, type WorkflowPanelTasksDeps } from './useWorkflowPanelTasks'
import { useWorkflowPanelDisplay } from './useWorkflowPanelDisplay'
import type { PhoneAgentStatusPayload } from './phoneAgentStatus'
import type { TaskItem } from '../useChatPersistence'

function setup(enabled: Record<string, boolean> = {}) {
  const mods = [{ id: 'phone-workflow', workflow_employees: [
    ...['phone', 'adb'].map((id) => ({ id, label: id, phone_channel: id === 'adb' ? 'adb' : 'wechat', phone_agent_base_path: id })),
    ...['wechat_msg', 'label_print', 'shipment_mgmt', 'receipt_confirm'].map((id) => ({ id, label: id })),
  ] }]
  const getModsForUi = () => mods as ReturnType<WorkflowPanelTasksDeps['getModsForUi']>
  const phonePolling = {
    getEnabledPhoneEmployeeIds: vi.fn(() => [] as string[]), isPollActive: vi.fn(() => false),
    startPhoneAgentStatusPoll: vi.fn(), stopPhoneAgentStatusPoll: vi.fn(),
  }
  const deps = {
    taskList: ref<TaskItem[]>([]), activeTaskId: ref(''), upsertTask: vi.fn(), sortTaskList: vi.fn(),
    getModsForUi, readWorkflowEmployeeEnabledMap: () => enabled,
    display: useWorkflowPanelDisplay({ getModsForUi }), phonePolling,
  }
  const panel = useWorkflowPanelTasks(deps)
  const update = (id: string, phoneStatus?: PhoneAgentStatusPayload | null) => {
    panel.upsertWorkflowEmployeeTask(id, { phoneStatus })
    return deps.upsertTask.mock.calls.at(-1)![0]
  }
  return { ...deps, panel, update, mods }
}

describe('workflow task status and synchronization', () => {
  it.each([
    ['phone', undefined, '正在同步后端', false],
    ['phone', { fetchError: 'offline' }, '排除状态接口', false],
    ...['phone_agent_get_status_failed', 'phone_agent_status_route_failed', 'phone_agent_manager_load_failed'].map((key) =>
      ['phone', { [key]: true }, '排除状态接口', false]),
    ['phone', { running: false }, '采集未启动', false],
    ['phone', { running: false, phone_agent_last_start_error: 'no mic' }, 'no mic', false],
    ['phone', { running: false, phone_agent_last_start_error: 'x'.repeat(70) }, 'x'.repeat(60) + '…', false],
    ['phone', { running: true }, '等待来电', false],
    ...['last_popup_detected_at_ms', 'last_click_at_ms', 'last_opening_at_ms', 'last_asr_at_ms'].map((key) =>
      ['phone', { running: true, [key]: 1 }, '步已完成', true]),
    ...['phone_in_call_ui_visible', 'phone_wechat_call_session_active', 'phone_agent_voice_session_active'].map((key) =>
      ['phone', { running: true, [key]: true }, '步已完成', true]),
    ['adb', undefined, '正在同步 ADB', false],
    ['adb', { running: false }, 'ADB 链路未运行', false],
    ['adb', { running: true }, '未检测到 adb', false],
    ['adb', { running: true, adb_available: true }, '等待设备在线', false],
    ['adb', { running: true, adb_available: true, adb_device_connected: true }, '步已完成', true],
  ])('%s status %j produces an honest progress label', (id, status, label, started) => {
    const task = setup().update(id as string, status as PhoneAgentStatusPayload | undefined)
    expect(task.payload.workflowProgressLabel).toContain(label)
    expect(task.payload.workflowProgressStarted).toBe(started)
    expect(task.payload.workflowProgressIdle).toBe(!started)
    expect(task.progress).toBe(task.payload.workflowProgressPct)
    if (!started) expect(task.progress).toBe(0)
  })

  it.each([false, true])('renders phone call evidence, success=%s', (ok) => {
    const task = setup().update('phone', {
      running: ok, window_monitor_available: ok, lastPolledAt: 1, last_popup_detected_at_ms: 2,
      last_popup_source: ok ? 'window' : '', last_popup_title: 'title'.repeat(20), last_click_at_ms: 3,
      last_click_ok: ok, last_click_method: ok ? 'geometry' : '', last_asr_at_ms: 4,
      last_asr_text: ok ? 'a'.repeat(170) : 'heard', last_reply_at_ms: 5, last_reply_text: ok ? 'r'.repeat(170) : 'reply',
    })
    for (const text of ['电话业务员状态', '上次同步', '识别弹窗', `接听点击：${ok ? '成功' : '失败'}`, '对方语音(ASR)', '回复送 VB']) {
      expect(task.summary).toContain(text)
    }
    expect(task.summary).toContain(ok ? 'a'.repeat(160) + '…' : 'heard')
    expect(task.summary).toContain(ok ? 'r'.repeat(160) + '…' : 'reply')
    expect(task.summary).not.toContain('title'.repeat(13))
  })

  it.each([false, true])('renders ADB device and error diagnostics, connected=%s', (connected) => {
    const task = setup().update('adb', { running: connected, adb_available: connected,
      adb_device_connected: connected, adb_device_serial: connected ? 'serial-1' : '',
      adb_call_state: connected ? 'ringing' : '', adb_last_error: 'e'.repeat(130) })
    expect(task.summary).toContain(connected ? '设备 serial-1 · 状态 RINGING' : '未运行 · ADB 不可用 · 无在线设备')
    expect(task.summary).toContain('最近错误：' + 'e'.repeat(120))
    expect(task.summary).not.toContain('e'.repeat(121))
    if (connected) expect(setup().update('adb', { running: true, adb_device_connected: true }).summary).toContain('设备 online')
  })

  it('keeps stored status until explicitly cleared and ignores missing employee metadata', () => {
    const s = setup()
    s.taskList.value = [{ id: 'workflow_emp_phone', payload: { phoneStatus: { running: true } } },
      { id: 'workflow_emp_wechat_msg', payload: { monitor: { lastPolledAt: 1 } } }] as TaskItem[]
    expect(s.update('phone').payload.phoneStatus).toEqual({ running: true })
    expect(s.update('phone', null).payload).not.toHaveProperty('phoneStatus')
    s.panel.upsertWorkflowEmployeeTask('wechat_msg')
    expect(s.upsertTask.mock.calls.at(-1)![0].payload.monitor).toEqual({ lastPolledAt: 1 })
    s.panel.upsertWorkflowEmployeeTask('wechat_msg', { monitor: null })
    expect(s.upsertTask.mock.calls.at(-1)![0].payload).not.toHaveProperty('monitor')
    s.upsertTask.mockClear()
    s.panel.upsertWorkflowEmployeeTask('missing')
    expect(s.upsertTask).not.toHaveBeenCalled()
  })

  it.each(['lastWechat', 'lastLabelPrint', 'lastShipmentAudit', 'lastReceiptFeedback'] as const)('preserves %s signal in the task payload', (key) => {
    const s = setup()
    const id = { lastWechat: 'wechat_msg', lastLabelPrint: 'label_print', lastShipmentAudit: 'shipment_mgmt', lastReceiptFeedback: 'receipt_confirm' }[key]
    s.panel.upsertWorkflowEmployeeTask(id, { [key]: { at: 1, line: 'signal' } })
    const task = s.upsertTask.mock.calls.at(-1)![0]
    expect(task.payload[key]).toEqual({ at: 1, line: 'signal' })
    expect(task.payload.workflowProgressStarted).toBe(true)
  })

  it.each([false, true])('removes obsolete and disabled tasks and restores selection, survivor=%s', (survivor) => {
    const s = setup({ phone: true })
    s.taskList.value = [{ id: 'workflow_emp_phone', type: 'workflow_employee' },
      { id: 'workflow_emp_stale', type: 'workflow_employee' },
      ...(survivor ? [{ id: 'other', type: 'other' }, { id: 'manual', type: 'workflow_employee' }] : [])] as TaskItem[]
    s.activeTaskId.value = 'workflow_emp_phone'
    s.panel.syncWorkflowEmployeePanelTasks({ phone: false })
    expect(s.taskList.value.map((task) => task.id)).toEqual(survivor ? ['other', 'manual'] : [])
    expect(s.activeTaskId.value).toBe(survivor ? 'other' : '')
    expect(s.sortTaskList).toHaveBeenCalledOnce()
    expect(s.phonePolling.stopPhoneAgentStatusPoll).toHaveBeenCalledOnce()
  })

  it.each([false, true])('starts polling only when enabled and not already active=%s', (active) => {
    const s = setup({ phone: true })
    s.phonePolling.getEnabledPhoneEmployeeIds.mockReturnValue(['phone'])
    s.phonePolling.isPollActive.mockReturnValue(active)
    s.panel.syncWorkflowEmployeePanelTasks({})
    expect(s.upsertTask).toHaveBeenCalledWith(expect.objectContaining({ id: 'workflow_emp_phone' }))
    expect(s.phonePolling.startPhoneAgentStatusPoll).toHaveBeenCalledTimes(active ? 0 : 1)
    s.upsertTask.mockClear()
    s.panel.resyncEnabledWorkflowEmployeeTasks()
    expect(s.upsertTask).toHaveBeenCalledOnce()
  })
})
