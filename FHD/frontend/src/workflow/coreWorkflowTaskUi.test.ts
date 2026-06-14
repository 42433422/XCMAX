import { describe, expect, it, beforeEach } from 'vitest'
import {
  workflowProgressIsIdle,
  coreWorkflowTaskDotStatusClass,
  coreWorkflowTaskDotTitle,
} from './coreWorkflowTaskUi'
import { STAR_REFRESH_STORAGE_KEY } from './coreWorkflowPrefs'

describe('coreWorkflowTaskUi', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('workflowProgressIsIdle respects flags', () => {
    expect(workflowProgressIsIdle({ workflowProgressIdle: true })).toBe(true)
    expect(workflowProgressIsIdle({ workflowProgressStarted: false })).toBe(true)
    expect(workflowProgressIsIdle({ workflowProgressStarted: true })).toBe(false)
  })

  it('returns null for non-core employee', () => {
    expect(coreWorkflowTaskDotStatusClass('other', {})).toBeNull()
    expect(coreWorkflowTaskDotTitle('other', {})).toBeNull()
  })

  it('shipment_mgmt queued when not started', () => {
    expect(coreWorkflowTaskDotStatusClass('shipment_mgmt', {})).toBe('queued')
  })

  it('wechat_msg warn without starred refresh', () => {
    const idle = { workflowProgressStarted: false }
    expect(coreWorkflowTaskDotStatusClass('wechat_msg', idle)).toBe('workflow-warn')
    expect(coreWorkflowTaskDotTitle('wechat_msg', idle) || '').toContain('橙')
  })

  it('wechat_msg queued with starred refresh', () => {
    localStorage.setItem(STAR_REFRESH_STORAGE_KEY, '1')
    expect(coreWorkflowTaskDotStatusClass('wechat_msg', {})).toBe('queued')
  })

  it('success when progress complete', () => {
    expect(
      coreWorkflowTaskDotStatusClass('label_print', { workflowProgressStarted: true, workflowProgressPct: 100 }),
    ).toBe('success')
  })
})
