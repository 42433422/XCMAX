import { describe, it, expect, beforeEach } from 'vitest'
import {
  coreWorkflowTaskDotStatusClass,
  coreWorkflowTaskDotTitle,
  workflowTaskDotStatusClassForTask,
  workflowTaskDotTitleForTask,
} from './coreWorkflowTaskUi'
import { STAR_REFRESH_STORAGE_KEY } from './coreWorkflowPrefs'
import type { TaskItem } from '@/composables/useChatPersistence'

describe('coreWorkflowTaskUi deep branches', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('failed when monitor pollOk is false', () => {
    const payload = { monitor: { pollOk: false }, workflowProgressStarted: true }
    expect(coreWorkflowTaskDotStatusClass('wechat_msg', payload)).toBe('failed')
    expect(coreWorkflowTaskDotTitle('wechat_msg', payload) || '').toContain('失败')
  })

  it('running when started but not complete', () => {
    expect(
      coreWorkflowTaskDotStatusClass('wechat_msg', {
        workflowProgressStarted: true,
        workflowProgressPct: 50,
      }),
    ).toBe('running')
  })

  it('label_print title branches: idle with refresh', () => {
    localStorage.setItem(STAR_REFRESH_STORAGE_KEY, '1')
    const title = coreWorkflowTaskDotTitle('label_print', { workflowProgressStarted: false }) || ''
    expect(title).toContain('等待微信')
  })

  it('label_print title branches: running', () => {
    const title =
      coreWorkflowTaskDotTitle('label_print', {
        workflowProgressStarted: true,
        workflowProgressPct: 40,
      }) || ''
    expect(title).toContain('蓝')
  })

  it('shipment_mgmt title idle and success', () => {
    expect(coreWorkflowTaskDotTitle('shipment_mgmt', { workflowProgressStarted: false }) || '').toContain('灰')
    expect(
      coreWorkflowTaskDotTitle('shipment_mgmt', {
        workflowProgressStarted: true,
        workflowProgressPct: 100,
      }) || '',
    ).toContain('绿')
  })

  it('receipt_confirm warn without starred refresh', () => {
    const title = coreWorkflowTaskDotTitle('receipt_confirm', { workflowProgressStarted: false }) || ''
    expect(title).toContain('橙')
  })

  it('receipt_confirm running and success', () => {
    localStorage.setItem(STAR_REFRESH_STORAGE_KEY, '1')
    expect(
      coreWorkflowTaskDotTitle('receipt_confirm', {
        workflowProgressStarted: true,
        workflowProgressPct: 20,
      }) || '',
    ).toContain('蓝')
    expect(
      coreWorkflowTaskDotStatusClass('receipt_confirm', {
        workflowProgressStarted: true,
        workflowProgressPct: 100,
      }),
    ).toBe('success')
  })

  it('workflowTaskDot helpers for workflow_emp_ tasks', () => {
    const task: TaskItem = {
      id: 'workflow_emp_wechat_msg',
      title: '微信',
      payload: { workflowProgressStarted: true, workflowProgressPct: 100 },
    }
    expect(workflowTaskDotStatusClassForTask(task)).toBe('success')
    expect(workflowTaskDotTitleForTask(task).length).toBeGreaterThan(0)
  })

  it('workflowTaskDot helpers return defaults for non-workflow tasks', () => {
    const task: TaskItem = { id: 'chat_1', title: '普通' }
    expect(workflowTaskDotStatusClassForTask(task)).toBe('queued')
    expect(workflowTaskDotTitleForTask(task)).toBe('')
  })
})
