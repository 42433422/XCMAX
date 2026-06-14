import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('./core', () => ({ api: apiMock, default: apiMock }))

import printApi from './print'

beforeEach(() => {
  for (const fn of Object.values(apiMock)) fn.mockReset().mockResolvedValue({ success: true })
})

describe('printApi', () => {
  it('covers all endpoints', async () => {
    await printApi.getPrinters()
    await printApi.getDefaultPrinter()
    await printApi.printDocument({ a: 1 })
    await printApi.printLabel({ a: 1 })
    await printApi.listLabels()
    await printApi.printSingleLabel({ a: 1 })
    await printApi.printByFilename('a b.lbl')
    await printApi.validatePrinters()
    await printApi.getDocumentPrinter()
    await printApi.getLabelPrinter()
    await printApi.getPrinterSelection()
    await printApi.savePrinterSelection({ document_printer: 'p1' })
    expect(apiMock.get).toHaveBeenCalled()
    expect(apiMock.post).toHaveBeenCalled()
    expect(apiMock.put).toHaveBeenCalledWith('/api/print/printer-selection', { document_printer: 'p1' })
  })

  it('printByFilename encodes filename', async () => {
    await printApi.printByFilename('a b.lbl')
    expect(apiMock.post).toHaveBeenCalledWith('/api/print/a%20b.lbl', {})
  })
})
