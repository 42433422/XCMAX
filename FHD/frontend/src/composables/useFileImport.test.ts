import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useFileImport, FILE_TYPES, FILE_EXTENSIONS } from './useFileImport'

vi.mock('../api/index', () => ({
  api: {
    upload: vi.fn().mockResolvedValue({ success: true, data: {} }),
    post: vi.fn().mockResolvedValue({ success: true, data: {} }),
  },
}))

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

  it('uploadProductImport returns null for null file', async () => {
    const { uploadProductImport } = useFileImport()
    expect(await uploadProductImport(null)).toBeNull()
  })

  it('uploadMultipleFiles returns empty for null', async () => {
    const { uploadMultipleFiles } = useFileImport()
    expect(await uploadMultipleFiles(null)).toEqual([])
  })
})
