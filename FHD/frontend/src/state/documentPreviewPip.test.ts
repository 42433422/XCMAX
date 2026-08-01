import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { xlsxRead, sheetToJson } = vi.hoisted(() => ({
  xlsxRead: vi.fn(),
  sheetToJson: vi.fn(),
}))

vi.mock('xlsx', () => ({
  read: xlsxRead,
  utils: { sheet_to_json: sheetToJson },
}))

vi.mock('@/api/core', () => ({
  buildFullApiUrl: vi.fn((path: string) => `http://api.local${path}`),
}))

import { buildFullApiUrl } from '@/api/core'
import {
  closeDocumentPreview,
  documentPreviewPip,
  expandDocumentPreview,
  minimizeDocumentPreview,
  openDocumentPreviewFromBlob,
  openDocumentPreviewFromResult,
} from './documentPreviewPip'

const originalCreateObjectUrl = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
const originalRevokeObjectUrl = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
const createObjectUrl = vi.fn()
const revokeObjectUrl = vi.fn()

function setUrlMethod(name: 'createObjectURL' | 'revokeObjectURL', value: unknown) {
  Object.defineProperty(URL, name, { configurable: true, writable: true, value })
}

function restoreUrlMethod(
  name: 'createObjectURL' | 'revokeObjectURL',
  descriptor: PropertyDescriptor | undefined,
) {
  if (descriptor) Object.defineProperty(URL, name, descriptor)
  else Reflect.deleteProperty(URL, name)
}

function blobLike(type: string, bytes = new ArrayBuffer(8)): Blob {
  return { type, arrayBuffer: vi.fn().mockResolvedValue(bytes) } as unknown as Blob
}

describe('documentPreviewPip', () => {
  beforeEach(() => {
    setUrlMethod('createObjectURL', createObjectUrl)
    setUrlMethod('revokeObjectURL', revokeObjectUrl)
    closeDocumentPreview()
    vi.clearAllMocks()
    Object.assign(documentPreviewPip, {
      visible: false,
      minimized: false,
      title: '生成文档',
      summary: '',
      url: '',
      kind: 'office',
      fileName: '',
      mimeType: '',
      previewRows: [],
    })
    createObjectUrl.mockReturnValue('blob:preview')
    xlsxRead.mockReturnValue({ SheetNames: ['Sheet1'], Sheets: { Sheet1: {} } })
    sheetToJson.mockReturnValue([])
  })

  afterEach(() => closeDocumentPreview())

  afterAll(() => {
    restoreUrlMethod('createObjectURL', originalCreateObjectUrl)
    restoreUrlMethod('revokeObjectURL', originalRevokeObjectUrl)
  })

  it('owns blob URLs and releases them when replaced or closed', () => {
    createObjectUrl.mockReturnValueOnce('blob:first').mockReturnValueOnce('blob:second')

    openDocumentPreviewFromBlob(blobLike('application/pdf'), 'contract.pdf', '待审核')
    expect(documentPreviewPip).toMatchObject({
      visible: true,
      minimized: false,
      title: 'contract.pdf',
      summary: '待审核',
      url: 'blob:first',
      kind: 'pdf',
    })

    openDocumentPreviewFromBlob(blobLike('image/png'), 'seal.png')
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:first')
    expect(documentPreviewPip.kind).toBe('image')

    minimizeDocumentPreview()
    expect(documentPreviewPip.minimized).toBe(true)
    expandDocumentPreview()
    expect(documentPreviewPip.minimized).toBe(false)
    closeDocumentPreview()
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:second')
    expect(documentPreviewPip).toMatchObject({ visible: false, url: '' })
  })

  it('infers Word and generic office previews from file hints', () => {
    openDocumentPreviewFromBlob(blobLike('application/octet-stream'), 'proposal.docx')
    expect(documentPreviewPip.kind).toBe('word')

    openDocumentPreviewFromBlob(blobLike('application/octet-stream'), 'notes.bin')
    expect(documentPreviewPip.kind).toBe('office')
  })

  it('hydrates and bounds an Excel preview to 30 rows by 12 columns', async () => {
    const rows = Array.from({ length: 35 }, (_, rowIndex) =>
      Array.from({ length: 15 }, (_, columnIndex) =>
        rowIndex === 0 && columnIndex === 1 ? null : rowIndex * 100 + columnIndex,
      ),
    )
    sheetToJson.mockReturnValue(rows)
    const excelBlob = blobLike('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    openDocumentPreviewFromBlob(excelBlob, 'forecast.xlsx')

    await vi.waitFor(() => expect(documentPreviewPip.previewRows).toHaveLength(30))
    expect(documentPreviewPip.kind).toBe('excel')
    expect(documentPreviewPip.previewRows[0]).toHaveLength(12)
    expect(documentPreviewPip.previewRows[0][1]).toBe('')
    expect(xlsxRead).toHaveBeenCalledWith(expect.any(ArrayBuffer), { type: 'array' })
  })

  it('leaves Excel rows empty when the workbook has no sheet or parsing fails', async () => {
    xlsxRead.mockReturnValueOnce({ SheetNames: [], Sheets: {} })
    openDocumentPreviewFromBlob(blobLike('application/vnd.ms-excel'), 'empty.xls')
    await vi.waitFor(() => expect(xlsxRead).toHaveBeenCalledTimes(1))
    expect(documentPreviewPip.previewRows).toEqual([])

    xlsxRead.mockImplementationOnce(() => { throw new Error('broken workbook') })
    openDocumentPreviewFromBlob(blobLike('application/vnd.ms-excel'), 'broken.xls')
    await vi.waitFor(() => expect(xlsxRead).toHaveBeenCalledTimes(2))
    expect(documentPreviewPip.previewRows).toEqual([])
  })

  it('finds a nested document and expands a relative API URL', () => {
    const opened = openDocumentPreviewFromResult({
      response: [null, { artifacts: [{
        file_name: 'plan.docx',
        mime_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        preview_url: '/api/files/plan',
        summary: '方案预览',
      }] }],
    })

    expect(opened).toBe(true)
    expect(buildFullApiUrl).toHaveBeenCalledWith('/api/files/plan')
    expect(documentPreviewPip).toMatchObject({
      visible: true,
      kind: 'word',
      title: 'plan.docx',
      summary: '方案预览',
      url: 'http://api.local/api/files/plan',
    })
  })

  it.each([
    ['https://files.example/report.pdf', 'report.pdf', 'pdf'],
    ['blob:already-owned', 'owned.pdf', 'pdf'],
    ['data:application/pdf;base64,AA==', 'inline.pdf', 'pdf'],
  ])('keeps absolute preview URL %s unchanged', (fileUrl, fileName, kind) => {
    expect(openDocumentPreviewFromResult({
      filename: fileName,
      file_url: fileUrl,
      content_type: fileName.endsWith('.webp') ? 'image/webp' : 'application/pdf',
      message: 'ready',
    })).toBe(true)
    expect(documentPreviewPip).toMatchObject({ url: fileUrl, kind, summary: 'ready' })
  })

  it('rejects primitives, non-document URLs, and candidates beyond the depth limit', () => {
    expect(openDocumentPreviewFromResult(null)).toBe(false)
    expect(openDocumentPreviewFromResult('report.pdf')).toBe(false)
    expect(openDocumentPreviewFromResult({ file_url: '/plain/file', name: 'readme.txt' })).toBe(false)

    let deep: unknown = {
      file_name: 'too-deep.pdf',
      download_url: '/api/files/too-deep.pdf',
    }
    for (let index = 0; index < 8; index += 1) deep = { nested: deep }
    expect(openDocumentPreviewFromResult(deep)).toBe(false)
  })
})
