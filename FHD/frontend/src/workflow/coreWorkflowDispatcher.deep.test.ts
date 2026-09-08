import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  buildLabelPrintHostUpdate,
  buildReceiptFeedbackHostUpdate,
  buildWechatMonitorUpdate,
  dispatchCoreWorkflowModRun,
  runLabelPrintSideEffect,
} from './coreWorkflowDispatcher'
import { printApi } from '@/api/print'
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

  const label = { product_id: 2, template_id: 'db:42', quantity: 3, paper_width_mm: 90, paper_height_mm: 60 }

  it.each([{ model_number: 'M-1', quantity: 2 }, { ...label, quantity: 0 }, { ...label, quantity: 101 }, { ...label, paper_width_mm: NaN }])('reports missing/invalid configuration without submitting %s', async (detail) => {
    const call = vi.spyOn(printApi, 'printSingleLabel')
    expect((await runLabelPrintSideEffect(detail)).status).toBe('needs_configuration')
    expect(call).not.toHaveBeenCalled()
  })

  it('generates a preview with the explicit selection and never confirms automatically', async () => {
    const call = vi.spyOn(printApi, 'printSingleLabel').mockResolvedValue({ success: true, job: { id: 'job-1', status: 'generated' } } as Awaited<ReturnType<typeof printApi.printSingleLabel>>)
    const confirm = vi.spyOn(printApi, 'confirmLabelJob')
    const submit = vi.spyOn(printApi, 'submitLabelJob')
    expect(await runLabelPrintSideEffect(label)).toMatchObject({ status: 'generated', jobId: 'job-1' })
    expect(call).toHaveBeenCalledWith({ product_id: 2, template_id: 'db:42', copies: 3, paper_width_mm: 90, paper_height_mm: 60 })
    expect(confirm).not.toHaveBeenCalled()
    expect(submit).not.toHaveBeenCalled()
  })

  it('does not report success without a generated job receipt', async () => {
    vi.spyOn(printApi, 'printSingleLabel').mockResolvedValue({ success: true } as Awaited<ReturnType<typeof printApi.printSingleLabel>>)
    expect((await runLabelPrintSideEffect(label)).status).toBe('failed')
  })

  it('returns failures for visible workflow feedback', async () => {
    vi.spyOn(printApi, 'printSingleLabel').mockRejectedValue(new Error('offline'))
    expect(await runLabelPrintSideEffect(label)).toEqual({ status: 'failed', message: 'offline' })
  })
})
