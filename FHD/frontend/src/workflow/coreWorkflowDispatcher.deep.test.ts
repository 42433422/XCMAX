import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  buildLabelPrintHostUpdate,
  buildReceiptFeedbackHostUpdate,
  buildWechatMonitorUpdate,
  dispatchCoreWorkflowModRun,
  runLabelPrintSideEffect,
} from './coreWorkflowDispatcher'
import * as employeeApi from '@/utils/coreWorkflowEmployeeApi'

describe('coreWorkflowDispatcher deep', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('dispatchCoreWorkflowModRun skips when mod not installed', () => {
    const spy = vi.spyOn(employeeApi, 'tryPostCoreWorkflowEmployeeRun')
    dispatchCoreWorkflowModRun(false, 'wechat_msg', { action: 'status' })
    expect(spy).not.toHaveBeenCalled()
  })

  it('dispatchCoreWorkflowModRun posts when mod installed', () => {
    const spy = vi.spyOn(employeeApi, 'tryPostCoreWorkflowEmployeeRun').mockResolvedValue(undefined)
    dispatchCoreWorkflowModRun(true, 'label_print', { action: 'signal_ack' })
    expect(spy).toHaveBeenCalledWith('label_print', { action: 'signal_ack' })
  })

  it('buildLabelPrintHostUpdate uses defaults', () => {
    const out = buildLabelPrintHostUpdate({})
    expect(out.lastLabelPrint.line).toBe('标签/打印类消息')
    expect(out.lastLabelPrint.at).toBeGreaterThan(0)
  })

  it('buildLabelPrintHostUpdate preserves custom line', () => {
    const out = buildLabelPrintHostUpdate({ line: '  型号 ABC  ', at: 1000 })
    expect(out.lastLabelPrint.line).toBe('型号 ABC')
    expect(out.lastLabelPrint.at).toBe(1000)
  })

  it('buildReceiptFeedbackHostUpdate composes detail and push', () => {
    const out = buildReceiptFeedbackHostUpdate({
      contactName: '张三',
      messageText: '已收货',
      intentLabel: 'receipt',
      intentDetail: '客户确认',
      line: '自定义行',
    })
    expect(out.pushTitle).toContain('收货确认')
    expect(out.lastReceiptFeedback.detail).toContain('张三')
    expect(out.pushDescription.length).toBeLessThanOrEqual(101)
  })

  it('buildReceiptFeedbackHostUpdate truncates long pushDescription', () => {
    const long = 'x'.repeat(120)
    const out = buildReceiptFeedbackHostUpdate({ line: long })
    expect(out.pushDescription.endsWith('…')).toBe(true)
  })

  it('buildWechatMonitorUpdate maps poll fields', () => {
    const out = buildWechatMonitorUpdate({
      at: 2000,
      intervalMs: 30000,
      contactCount: 5,
      ok: false,
    })
    expect(out.monitor.lastPolledAt).toBe(2000)
    expect(out.monitor.pollIntervalMs).toBe(30000)
    expect(out.monitor.starredContactCount).toBe(5)
    expect(out.monitor.pollOk).toBe(false)
  })

  it('runLabelPrintSideEffect no-ops without model number', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await runLabelPrintSideEffect({ quantity: 2 })
    expect(warn).not.toHaveBeenCalled()
  })

  it('runLabelPrintSideEffect calls printApi on success', async () => {
    const printApi = { printSingleLabel: vi.fn().mockResolvedValue({ success: true }) }
    vi.doMock('@/api', () => ({ printApi }))
    const mod = await import('./coreWorkflowDispatcher')
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await mod.runLabelPrintSideEffect({ model_number: 'M-1', quantity: 3 })
    warn.mockRestore()
  })
})
