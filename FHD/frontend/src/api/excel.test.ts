import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./core', () => ({ api: apiMock, default: apiMock }))

import excelApi, { normalizeTemplateDtoList } from './excel'

beforeEach(() => {
  apiMock.get.mockReset().mockResolvedValue({ success: true, data: {} })
  apiMock.post.mockReset().mockResolvedValue({ success: true })
})

describe('excelApi', () => {
  it('getTemplates normalizes template list', async () => {
    apiMock.get.mockResolvedValueOnce({
      success: true,
      data: { templates: [{ id: 1, template_type: '标签打印', exists: true, file_path: '/p' }, { id: 2 }] },
    })
    const res = await excelApi.getTemplates()
    expect(res.data.templates[0].category).toBe('label_print')
    expect(res.data.templates[0].preview_capable).toBe(true)
    expect(res.data.templates[1].category).toBe('excel')
    expect(res.data.templates[1].name).toBe('未命名模板')
  })

  it('getTemplates tolerates missing templates field', async () => {
    apiMock.get.mockResolvedValueOnce({ success: true, data: {} })
    const res = await excelApi.getTemplates()
    expect(res.data.templates).toEqual([])
  })

  it('covers post endpoints', async () => {
    await excelApi.saveTemplate({ a: '1' })
    await excelApi.decomposeTemplate({ a: '1' })
    await excelApi.uploadExcel(new FormData())
    await excelApi.extractData({ a: '1' })
    await excelApi.generateExcel({ a: '1' })
    expect(apiMock.post).toHaveBeenCalledTimes(5)
  })

  it('normalizeTemplateDto infers excel category by default', () => {
    const t = excelApi.normalizeTemplateDto({ id: 9, template_type: 'report' })
    expect(t.category).toBe('excel')
    expect(t.is_active).toBe(true)
  })

  it('normalizeTemplateDtoList maps and guards non-array', () => {
    expect(normalizeTemplateDtoList([{ id: 1 }]).length).toBe(1)
    expect(normalizeTemplateDtoList(undefined)).toEqual([])
  })
})
