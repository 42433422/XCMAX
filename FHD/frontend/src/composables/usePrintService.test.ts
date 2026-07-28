import { describe, it, expect, vi, beforeEach } from 'vitest'

const authenticatedRequestInitMock = vi.hoisted(() => vi.fn())

vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiPath: (p: string) => `http://localhost${p}`,
}))
vi.mock('@/utils/authenticatedRequest', () => ({
  authenticatedRequestInit: authenticatedRequestInitMock,
}))

import { usePrintService } from './usePrintService'

describe('usePrintService', () => {
  let service: ReturnType<typeof usePrintService>

  beforeEach(() => {
    vi.clearAllMocks()
    authenticatedRequestInitMock.mockResolvedValue({
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': 'csrf-from-helper',
      },
    })
    service = usePrintService()
  })

  describe('printLabel', () => {
    it('returns success when API responds ok', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      } as Response)
      const result = await service.printLabel('/path/to/label.pdf')
      expect(result.success).toBe(true)
      expect(result.message).toContain('标签打印成功')
    })

    it('returns failure when API responds non-ok', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ success: false, message: 'Printer error' }),
      } as Response)
      const result = await service.printLabel('/path/to/label.pdf')
      expect(result.success).toBe(false)
      expect(result.message).toContain('Printer error')
    })

    it('returns failure with HTTP status when no message', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: false,
        status: 503,
        json: async () => ({}),
      } as Response)
      const result = await service.printLabel('/path/to/label.pdf')
      expect(result.success).toBe(false)
      expect(result.message).toContain('503')
    })

    it('returns failure on network error', async () => {
      vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new Error('Network down'))
      const result = await service.printLabel('/path/to/label.pdf')
      expect(result.success).toBe(false)
      expect(result.message).toContain('Network down')
    })

    it('sends copies parameter', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      } as Response)
      await service.printLabel('/path/to/label.pdf', 3)
      const body = JSON.parse((fetchSpy.mock.calls[0][1] as RequestInit).body as string)
      expect(body.copies).toBe(3)
      expect(body.require_confirm).toBe(false)
    })

    it('uses the authenticated request helper for an explicit print action', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      } as Response)

      await service.printLabel('/path/to/label.pdf')

      expect(authenticatedRequestInitMock).toHaveBeenCalledWith('POST', {
        'Content-Type': 'application/json',
      })
      expect(fetchSpy).toHaveBeenCalledWith(
        'http://localhost/api/print/label',
        expect.objectContaining({
          credentials: 'include',
          headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf-from-helper' }),
        }),
      )
    })

    it('defaults copies to 1', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      } as Response)
      await service.printLabel('/path/to/label.pdf')
      const body = JSON.parse((fetchSpy.mock.calls[0][1] as RequestInit).body as string)
      expect(body.copies).toBe(1)
    })

    it('handles JSON parse failure gracefully', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => { throw new Error('invalid json') },
      } as Response)
      const result = await service.printLabel('/path/to/label.pdf')
      // With empty object, success is falsy, so it falls to HTTP status path
      expect(result.success).toBe(false)
    })
  })

  describe('printDocument', () => {
    it('returns success when API responds ok', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      } as Response)
      const result = await service.printDocument('/path/to/doc.pdf')
      expect(result.success).toBe(true)
      expect(result.message).toContain('发货单打印成功')
    })

    it('returns failure on API error', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: false,
        status: 500,
        json: async () => ({ success: false, message: 'Print failed' }),
      } as Response)
      const result = await service.printDocument('/path/to/doc.pdf')
      expect(result.success).toBe(false)
    })

    it('returns failure on network error', async () => {
      vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new Error('Timeout'))
      const result = await service.printDocument('/path/to/doc.pdf')
      expect(result.success).toBe(false)
      expect(result.message).toContain('Timeout')
    })
  })

  describe('markAsPrinted', () => {
    it('returns success when API responds ok', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true, updated: true }),
      } as Response)
      const result = await service.markAsPrinted('/path/to/doc.pdf', 123, 'receipt-123')
      expect(result.success).toBe(true)
      expect(result.message).toContain('打印状态已更新')
    })

    it('includes orderId in payload when provided', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true, updated: true }),
      } as Response)
      await service.markAsPrinted('/path/to/doc.pdf', 42, 'receipt-42')
      const body = JSON.parse((fetchSpy.mock.calls[0][1] as RequestInit).body as string)
      expect(body.order_id).toBe(42)
      expect(body.post_print_receipt).toBe('receipt-42')
    })

    it('omits orderId when not provided', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true, updated: true }),
      } as Response)
      await service.markAsPrinted('/path/to/doc.pdf', undefined, 'receipt-no-order')
      const body = JSON.parse((fetchSpy.mock.calls[0][1] as RequestInit).body as string)
      expect(body.order_id).toBeUndefined()
    })

    it('returns failure when updated is false', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true, updated: false }),
      } as Response)
      const result = await service.markAsPrinted('/path/to/doc.pdf', undefined, 'receipt-failed')
      expect(result.success).toBe(false)
    })

    it('does not call the mark route without a physical-print receipt', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch')
      const result = await service.markAsPrinted('/path/to/doc.pdf', 42)
      expect(result.success).toBe(false)
      expect(fetchSpy).not.toHaveBeenCalled()
    })
  })

  describe('checkDocumentPrintJob', () => {
    it('returns the owner-bound receipt only after CUPS confirms completion', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          print_completed: true,
          print_state: 'completed',
          post_print_receipt: 'receipt-after-cups',
        }),
      } as Response)

      const result = await service.checkDocumentPrintJob('opaque-job-token')

      expect(result.success).toBe(true)
      expect(result.printCompleted).toBe(true)
      expect(result.postPrintReceipt).toBe('receipt-after-cups')
      expect(fetchSpy).toHaveBeenCalledWith(
        'http://localhost/api/print/jobs/opaque-job-token',
        expect.objectContaining({ credentials: 'include' }),
      )
    })

    it('keeps an unconfirmed CUPS job pending without a receipt', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ success: true, print_completed: false, print_state: 'pending' }),
      } as Response)

      const result = await service.checkDocumentPrintJob('opaque-job-token')

      expect(result.success).toBe(true)
      expect(result.printPending).toBe(true)
      expect(result.postPrintReceipt).toBeUndefined()
    })

    it('surfaces an aborted CUPS job without marking it completed', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          success: false,
          print_completed: false,
          print_state: 'aborted',
          message: 'media-empty-error',
        }),
      } as Response)

      const result = await service.checkDocumentPrintJob('opaque-job-token')

      expect(result.success).toBe(false)
      expect(result.printCompleted).toBe(false)
      expect(result.printState).toBe('aborted')
    })
  })

  describe('executePrintTask', () => {
    it('sets isPrinting during execution', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true }),
      } as Response)
      const promise = service.executePrintTask(['/label.pdf'], '/doc.pdf', 1)
      expect(service.isPrinting.value).toBe(true)
      await promise
      expect(service.isPrinting.value).toBe(false)
    })

    it('returns success summary when all operations succeed', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, updated: true, post_print_receipt: 'receipt-1' }),
      } as Response)
      const summary = await service.executePrintTask(['/label1.pdf', '/label2.pdf'], '/doc.pdf', 1, undefined, 'token-1')
      expect(summary.labelSuccess).toBe(2)
      expect(summary.labelFailed).toBe(0)
      expect(summary.shipmentPrinted).toBe(true)
      expect(summary.shipmentMarked).toBe(true)
      expect(summary.success).toBe(true)
    })

    it('tracks label failures', async () => {
      vi.spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true, summary: { label_printer_ready: true } }),
        } as Response)
        .mockResolvedValueOnce({
          ok: false,
          status: 500,
          json: async () => ({ success: false, message: 'Printer jam' }),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true, print_completed: true, post_print_receipt: 'receipt-2' }),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true, updated: true }),
        } as Response)
      const summary = await service.executePrintTask(['/bad.pdf'], '/doc.pdf', 1, undefined, 'token-2')
      expect(summary.labelFailed).toBe(1)
      expect(summary.logs).toHaveLength(1)
      expect(summary.logs[0]).toContain('标签打印失败')
      // The delivery document and its shipment state are authoritative.  A
      // configured label printer failure is a visible warning, not a false
      // "shipment failed" result.
      expect(summary.success).toBe(true)
    })

    it('tracks document print failure', async () => {
      vi.spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true, summary: { label_printer_ready: true } }),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true }),
        } as Response)
        .mockResolvedValueOnce({
          ok: false,
          status: 500,
          json: async () => ({ success: false, message: 'Doc error' }),
        } as Response)
      const summary = await service.executePrintTask(['/label.pdf'], '/doc.pdf', 1)
      expect(summary.shipmentPrinted).toBe(false)
      expect(summary.logs).toContainEqual(expect.stringContaining('发货单打印失败'))
    })

    it('skips optional labels when no label printer is configured but completes the delivery document', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true, summary: { label_printer_ready: false } }),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true, print_completed: true, post_print_receipt: 'doc-receipt' }),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: async () => ({ success: true, updated: true }),
        } as Response)

      const summary = await service.executePrintTask(
        ['/label-1.pdf', '/label-2.pdf'],
        '/doc.pdf',
        1,
        undefined,
        'token-optional-labels',
      )

      expect(summary.labelSkipped).toBe(2)
      expect(summary.labelFailed).toBe(0)
      expect(summary.shipmentMarked).toBe(true)
      expect(summary.success).toBe(true)
      expect(fetchSpy.mock.calls.map(([url]) => String(url))).not.toContain('http://localhost/api/print/label')
    })

    it('does not mark a shipment printed while CUPS reports a queued document job', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          print_completed: false,
          print_state: 'queued',
          job_id: 'Canon_TS3700_series-42',
          print_job_token: 'opaque-pending-job',
          print_tracking_available: true,
        }),
      } as Response)

      const summary = await service.executePrintTask([], '/doc.pdf', 1, undefined, 'token-queued')

      expect(summary.pending).toBe(true)
      expect(summary.shipmentPending).toBe(true)
      expect(summary.shipmentMarked).toBe(false)
      expect(summary.pendingPrintJobToken).toBe('opaque-pending-job')
      expect(fetchSpy).toHaveBeenCalledTimes(1)
      expect(String(fetchSpy.mock.calls[0][0])).toBe('http://localhost/api/print/document')
    })

    it('logs warning when orderId is missing', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, updated: true }),
      } as Response)
      const summary = await service.executePrintTask(['/label.pdf'], '/doc.pdf')
      expect(summary.logs).toContainEqual(expect.stringContaining('缺少记录ID'))
    })

    it('succeeds with no label paths', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ success: true, updated: true }),
      } as Response)
      const summary = await service.executePrintTask([], '/doc.pdf', 1)
      expect(summary.labelSuccess).toBe(0)
      expect(summary.labelFailed).toBe(0)
    })

    it('succeeds with no file path', async () => {
      const summary = await service.executePrintTask(['/label.pdf'], '', undefined)
      expect(summary.shipmentPrinted).toBe(false)
      expect(summary.shipmentMarked).toBe(false)
    })
  })

  describe('buildPrintSummaryMessage', () => {
    it('builds message with label counts', () => {
      const summary = {
        labelSuccess: 2,
        labelFailed: 0,
        shipmentPrinted: false,
        shipmentMarked: false,
        logs: [],
        success: true,
        message: '打印完成',
      }
      const msg = service.buildPrintSummaryMessage(summary, 2)
      expect(msg).toContain('2/2 成功')
    })

    it('includes shipment status when filePath provided', () => {
      const summary = {
        labelSuccess: 1,
        labelFailed: 0,
        shipmentPrinted: true,
        shipmentMarked: true,
        logs: [],
        success: true,
        message: '打印完成',
      }
      const msg = service.buildPrintSummaryMessage(summary, 1, '/doc.pdf')
      expect(msg).toContain('已确认打印')
      expect(msg).toContain('已标记已打印')
    })

    it('includes log details when present', () => {
      const summary = {
        labelSuccess: 0,
        labelFailed: 1,
        shipmentPrinted: false,
        shipmentMarked: false,
        logs: ['标签打印失败：error1', 'other error'],
        success: false,
        message: '打印未完全成功',
      }
      const msg = service.buildPrintSummaryMessage(summary, 1)
      expect(msg).toContain('详情')
    })
  })
})
