import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useFileImport, FILE_TYPES, FILE_EXTENSIONS } from './useFileImport'

const apiPost = vi.fn()

vi.mock('../api/index', () => ({
  api: {
    upload: vi.fn().mockResolvedValue({ success: true, data: {} }),
    post: (...args: unknown[]) => apiPost(...args),
  },
}))

function makeFile(name: string, type = 'text/plain'): File {
  return new File(['content'], name, { type })
}

describe('useFileImport', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('exports file type constants', () => {
    expect(FILE_TYPES.EXCEL.length).toBeGreaterThan(0)
    expect(FILE_EXTENSIONS.EXCEL).toContain('.xlsx')
  })

  it('detectFileType identifies excel', () => {
    const { detectFileType } = useFileImport()
    const file = new File([''], 'data.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    expect(detectFileType(file)).toBe('excel')
  })

  it('detectFileType identifies csv by extension', () => {
    const { detectFileType } = useFileImport()
    const file = new File(['a,b'], 'data.csv', { type: 'text/plain' })
    expect(detectFileType(file)).toBe('csv')
  })

  it('detectFileType identifies image', () => {
    const { detectFileType } = useFileImport()
    const file = new File([''], 'pic.png', { type: 'image/png' })
    expect(detectFileType(file)).toBe('image')
  })

  it('detectFileType returns other for unknown', () => {
    const { detectFileType } = useFileImport()
    const file = new File([''], 'readme.txt', { type: 'text/plain' })
    expect(detectFileType(file)).toBe('other')
  })

  it('detectFileType identifies pdf', () => {
    const { detectFileType } = useFileImport()
    const file = new File([''], 'doc.pdf', { type: 'application/pdf' })
    expect(detectFileType(file)).toBe('pdf')
  })

  it('detectFileType identifies word', () => {
    const { detectFileType } = useFileImport()
    const file = new File([''], 'doc.docx', {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    })
    expect(detectFileType(file)).toBe('word')
  })

  it('resetState clears uploading state', () => {
    const imp = useFileImport()
    imp.uploading.value = true
    imp.progress.value = 50
    imp.resetState()
    expect(imp.uploading.value).toBe(false)
    expect(imp.progress.value).toBe(0)
    expect(imp.status.show).toBe(false)
  })

  it('uploadFile returns null for null file', async () => {
    const { uploadFile } = useFileImport()
    const result = await uploadFile(null)
    expect(result).toBeNull()
  })

  it('uploadFile returns response on success', async () => {
    apiPost.mockResolvedValueOnce({ success: true, message: 'ok', data: { id: 1 } })
    const imp = useFileImport()
    const result = await imp.uploadFile(makeFile('a.xlsx'))
    expect(result).toEqual({ success: true, message: 'ok', data: { id: 1 } })
    expect(imp.status.type).toBe('success')
    expect(imp.uploading.value).toBe(false)
  })

  it('uploadFile returns null when response.success is false', async () => {
    apiPost.mockResolvedValueOnce({ success: false, message: 'import failed' })
    const imp = useFileImport()
    const result = await imp.uploadFile(makeFile('a.xlsx'))
    expect(result).toBeNull()
    expect(imp.status.type).toBe('error')
  })

  it('uploadFile catches network error and sets error state', async () => {
    apiPost.mockRejectedValueOnce(new Error('network down'))
    const imp = useFileImport()
    const result = await imp.uploadFile(makeFile('a.xlsx'))
    expect(result).toBeNull()
    expect(imp.error.value).toBeInstanceOf(Error)
    expect(imp.status.type).toBe('error')
  })

  it('uploadFile handles non-Error thrown', async () => {
    apiPost.mockRejectedValueOnce('string error')
    const imp = useFileImport()
    const result = await imp.uploadFile(makeFile('a.xlsx'))
    expect(result).toBeNull()
    expect(imp.error.value).toBeInstanceOf(Error)
  })

  it('uploadProductImport returns null for null file', async () => {
    const { uploadProductImport } = useFileImport()
    expect(await uploadProductImport(null)).toBeNull()
  })

  it('uploadProductImport calls uploadFile with product_import purpose', async () => {
    apiPost.mockResolvedValueOnce({ success: true, data: {} })
    const imp = useFileImport()
    await imp.uploadProductImport(makeFile('p.xlsx'))
    expect(apiPost).toHaveBeenCalled()
  })

  it('uploadCustomersImport returns null for null file', async () => {
    const { uploadCustomersImport } = useFileImport()
    expect(await uploadCustomersImport(null)).toBeNull()
  })

  it('uploadCustomersImport calls uploadFile with customers_import purpose', async () => {
    apiPost.mockResolvedValueOnce({ success: true, data: {} })
    const imp = useFileImport()
    await imp.uploadCustomersImport(makeFile('c.csv'))
    expect(apiPost).toHaveBeenCalled()
  })

  it('uploadOrderParse returns null for null file', async () => {
    const { uploadOrderParse } = useFileImport()
    expect(await uploadOrderParse(null)).toBeNull()
  })

  it('uploadOrderParse calls uploadFile with order_parse purpose', async () => {
    apiPost.mockResolvedValueOnce({ success: true, data: {} })
    const imp = useFileImport()
    await imp.uploadOrderParse(makeFile('o.pdf'))
    expect(apiPost).toHaveBeenCalled()
  })

  it('uploadMaterialsImport returns null for null file', async () => {
    const { uploadMaterialsImport } = useFileImport()
    expect(await uploadMaterialsImport(null)).toBeNull()
  })

  it('uploadMaterialsImport calls uploadFile with materials_import purpose', async () => {
    apiPost.mockResolvedValueOnce({ success: true, data: {} })
    const imp = useFileImport()
    await imp.uploadMaterialsImport(makeFile('m.xlsx'))
    expect(apiPost).toHaveBeenCalled()
  })

  it('uploadMultipleFiles returns empty for null', async () => {
    const { uploadMultipleFiles } = useFileImport()
    expect(await uploadMultipleFiles(null)).toEqual([])
  })

  it('uploadMultipleFiles returns empty for empty array', async () => {
    const { uploadMultipleFiles } = useFileImport()
    expect(await uploadMultipleFiles([])).toEqual([])
  })

  it('uploadMultipleFiles processes all files when all succeed', async () => {
    apiPost.mockResolvedValue({ success: true, data: {} })
    const imp = useFileImport()
    const files = [makeFile('a.csv'), makeFile('b.xlsx')]
    const results = await imp.uploadMultipleFiles(files)
    expect(results).toHaveLength(2)
    expect(results.every((r) => r.success)).toBe(true)
    expect(imp.status.type).toBe('success')
  })

  it('uploadMultipleFiles reports partial success', async () => {
    apiPost.mockResolvedValueOnce({ success: true, data: {} }).mockResolvedValueOnce({ success: false, message: 'fail' })
    const imp = useFileImport()
    const files = [makeFile('a.csv'), makeFile('b.xlsx')]
    const results = await imp.uploadMultipleFiles(files)
    expect(results).toHaveLength(2)
    expect(results[0].success).toBe(true)
    expect(results[1].success).toBe(false)
    expect(imp.status.type).toBe('success') // partial success still uses 'success' type
  })

  it('uploadMultipleFiles reports error when all fail', async () => {
    apiPost.mockResolvedValue({ success: false, message: 'fail' })
    const imp = useFileImport()
    const files = [makeFile('a.csv'), makeFile('b.xlsx')]
    const results = await imp.uploadMultipleFiles(files)
    expect(results.every((r) => !r.success)).toBe(true)
    expect(imp.status.type).toBe('error')
  })

  it('uploadMultipleFiles calls onFileComplete callback', async () => {
    apiPost.mockResolvedValue({ success: true, data: {} })
    const imp = useFileImport()
    const calls: Array<{ current: number; total: number }> = []
    await imp.uploadMultipleFiles([makeFile('a.csv'), makeFile('b.csv')], 'general', (_r, current, total) => {
      calls.push({ current, total })
    })
    expect(calls).toEqual([
      { current: 1, total: 2 },
      { current: 2, total: 2 },
    ])
  })
})
