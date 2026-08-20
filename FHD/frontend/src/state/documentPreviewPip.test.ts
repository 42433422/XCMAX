import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  buildFullApiUrl: vi.fn((path: string) => `https://api.example.test${path}`),
  read: vi.fn(),
  sheetToJson: vi.fn(),
}))

vi.mock('@/api/core', () => ({
  buildFullApiUrl: mocks.buildFullApiUrl,
}))

vi.mock('xlsx', () => ({
  read: mocks.read,
  utils: { sheet_to_json: mocks.sheetToJson },
}))

import {
  closeDocumentPreview,
  documentPreviewPip,
  expandDocumentPreview,
  minimizeDocumentPreview,
  openDocumentPreviewFromBlob,
  openDocumentPreviewFromResult,
} from './documentPreviewPip'

const createObjectUrl = vi.fn(() => 'blob:document-preview')
const revokeObjectUrl = vi.fn()

Object.defineProperty(URL, 'createObjectURL', {
  configurable: true,
  value: createObjectUrl,
})
Object.defineProperty(URL, 'revokeObjectURL', {
  configurable: true,
  value: revokeObjectUrl,
})

describe('documentPreviewPip', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    closeDocumentPreview()
    Object.assign(documentPreviewPip, {
      minimized: false,
      title: '生成文档',
      summary: '',
      kind: 'office',
      fileName: '',
      mimeType: '',
      previewRows: [],
    })
  })

  it('owns blob URLs, hydrates an Excel preview, and releases the URL on close', async () => {
    mocks.read.mockReturnValue({ SheetNames: ['Sheet1'], Sheets: { Sheet1: {} } })
    mocks.sheetToJson.mockReturnValue([['客户', null, 3], ['第二行']])
    const blob = {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)),
    } as unknown as Blob

    openDocumentPreviewFromBlob(blob, '客户清单.xlsx', '导入预览')
    await flushPromises()

    expect(documentPreviewPip).toMatchObject({
      visible: true,
      minimized: false,
      title: '客户清单.xlsx',
      summary: '导入预览',
      kind: 'excel',
      url: 'blob:document-preview',
    })
    expect(documentPreviewPip.previewRows).toEqual([['客户', '', '3'], ['第二行']])

    minimizeDocumentPreview()
    expect(documentPreviewPip.minimized).toBe(true)
    expandDocumentPreview()
    expect(documentPreviewPip.minimized).toBe(false)

    closeDocumentPreview()
    expect(revokeObjectUrl).toHaveBeenCalledWith('blob:document-preview')
    expect(documentPreviewPip).toMatchObject({ visible: false, url: '' })
  })

  it('finds nested document results, resolves relative URLs, and infers every preview kind', () => {
    const cases = [
      ['report.pdf', 'application/pdf', 'pdf'],
      ['photo.png', 'image/png', 'image'],
      ['brief.docx', 'application/msword', 'word'],
      ['ledger.xlsx', 'application/vnd.ms-excel', 'excel'],
      ['notes.bin', 'application/octet-stream', 'office'],
    ] as const

    for (const [fileName, mimeType, kind] of cases) {
      const opened = openDocumentPreviewFromResult({
        envelope: [
          {
            artifact_type: 'document',
            file_name: fileName,
            mime_type: mimeType,
            download_url: `/files/${fileName}`,
            message: `${fileName} ready`,
          },
        ],
      })
      expect(opened).toBe(true)
      expect(documentPreviewPip.kind).toBe(kind)
      expect(documentPreviewPip.url).toBe(`https://api.example.test/files/${fileName}`)
    }

    expect(mocks.buildFullApiUrl).toHaveBeenCalledTimes(cases.length)
  })

  it('keeps absolute URLs intact and rejects values without a document candidate', () => {
    expect(openDocumentPreviewFromResult(null)).toBe(false)
    expect(openDocumentPreviewFromResult(['plain text', { download_url: '' }])).toBe(false)
    expect(
      openDocumentPreviewFromResult({
        artifact_type: 'document',
        file_name: 'manual.pdf',
        preview_url: 'https://cdn.example.test/manual.pdf',
      }),
    ).toBe(true)
    expect(documentPreviewPip.url).toBe('https://cdn.example.test/manual.pdf')
  })

  it('clears Excel rows when workbook hydration fails', async () => {
    mocks.read.mockImplementation(() => {
      throw new Error('broken workbook')
    })
    const blob = {
      type: 'application/vnd.ms-excel',
      arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(0)),
    } as unknown as Blob

    openDocumentPreviewFromBlob(blob, 'broken.xls')
    await flushPromises()

    expect(documentPreviewPip.kind).toBe('excel')
    expect(documentPreviewPip.previewRows).toEqual([])
  })
})
