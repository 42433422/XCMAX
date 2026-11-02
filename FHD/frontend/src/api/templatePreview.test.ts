import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const { apiMock, ApiError } = vi.hoisted(() => {
  class ApiError extends Error {
    status: number
    data: unknown
    constructor(message: string, status: number, data?: unknown) {
      super(message)
      this.status = status
      this.data = data
    }
  }
  return { apiMock: { get: vi.fn(), post: vi.fn() }, ApiError }
})

vi.mock('./core', () => ({ api: apiMock, default: apiMock, ApiError }))

import templatePreviewApi from './templatePreview'

beforeEach(() => {
  apiMock.get.mockReset().mockResolvedValue({ success: true })
  apiMock.post.mockReset().mockResolvedValue({ success: true })
})

describe('templatePreviewApi', () => {
  it('exposes endpoints and covers wrappers', async () => {
    expect(templatePreviewApi.endpoints.list).toBeTruthy()
    await templatePreviewApi.listTemplates()
    await templatePreviewApi.getTemplateDetail(7)
    await templatePreviewApi.decomposeTemplate({ a: 1 })
    await templatePreviewApi.analyzeTemplate(new FormData())
    await templatePreviewApi.getAnalysisProgress('task1')
    await templatePreviewApi.deleteTemplate({ id: 1 })
    await templatePreviewApi.extractGrid(new FormData())
    expect(apiMock.get).toHaveBeenCalled()
    expect(apiMock.post).toHaveBeenCalled()
  })

  it('getTemplateDetail joins detail path', async () => {
    await templatePreviewApi.getTemplateDetail(42)
    expect(apiMock.get).toHaveBeenLastCalledWith(expect.stringMatching(/\/42$/))
  })

  it('create/update/replace succeed', async () => {
    await templatePreviewApi.createTemplate({ a: 1 })
    await templatePreviewApi.updateTemplate({ a: 1 })
    await templatePreviewApi.createTemplateFromGrid({ a: 1 })
    await templatePreviewApi.replaceTemplateById({ a: 1 })
    expect(apiMock.post).toHaveBeenCalledTimes(4)
  })

  it('wraps 404 service-availability error into a descriptive ApiError', async () => {
    apiMock.post.mockRejectedValueOnce(new ApiError('nf', 404))
    await expect(templatePreviewApi.createTemplate({ a: 1 })).rejects.toThrow(/服务未开放/)
  })

  it('rethrows non-availability errors untouched', async () => {
    apiMock.post.mockRejectedValueOnce(new ApiError('boom', 500))
    await expect(templatePreviewApi.updateTemplate({ a: 1 })).rejects.toThrow('boom')
  })
})


afterEach(() => { vi.unstubAllEnvs() })

describe('template transport and configured service availability', () => {
  it('uploads the original multipart file and returns the server analysis receipt', async () => {
    const form = new FormData(), source = new File(['synthetic workbook'], 'template.xlsx'); form.set('file', source)
    const receipt = { success: true, task_id: 'analysis-7', template_saved: false }; apiMock.post.mockResolvedValueOnce(receipt)
    expect(await templatePreviewApi.uploadTemplate(form)).toBe(receipt)
    expect(apiMock.post).toHaveBeenCalledExactlyOnceWith(templatePreviewApi.endpoints.upload, form); expect(form.get('file')).toBe(source)
  })

  it.each([['createTemplateFromGrid', '创建', 'create', 405], ['replaceTemplateById', '替换', 'update', 501]] as const)('reports unavailable %s without claiming the grid was written', async (method, action, endpoint, status) => {
    const payload = { id: 7, cells: [{ cell: 'A1', value: 'synthetic header' }] }, data = { error_code: 'service_unavailable' }
    apiMock.post.mockRejectedValueOnce(new ApiError('unavailable', status, data))
    await expect(templatePreviewApi[method](payload)).rejects.toMatchObject({ message: `模板${action}服务未开放，请检查接口配置：${templatePreviewApi.endpoints[endpoint]}`, status, data })
    expect(apiMock.post).toHaveBeenCalledExactlyOnceWith(templatePreviewApi.endpoints[endpoint], payload)
  })

  it('keeps development loopback requests on the current origin with their query intact', async () => {
    vi.stubEnv('VITE_TEMPLATE_LIST_ENDPOINT', '  http://localhost:5000/api/library/templates?tenant=7  '); vi.resetModules()
    const configured = (await import('./templatePreview')).default
    await configured.listTemplates()
    expect(configured.endpoints.list).toBe('/api/library/templates?tenant=7')
    expect(apiMock.get).toHaveBeenLastCalledWith('/api/library/templates?tenant=7', {}, {})
  })

  it('preserves an explicit remote template service endpoint', async () => {
    vi.stubEnv('VITE_TEMPLATE_LIST_ENDPOINT', 'https://template.example.test/api/templates'); vi.resetModules()
    const configured = (await import('./templatePreview')).default
    await configured.listTemplates()
    expect(apiMock.get).toHaveBeenLastCalledWith('https://template.example.test/api/templates', {}, {})
  })

  it('does not silently replace a malformed configured endpoint with another service', async () => {
    const endpoint = 'http://127.0.0.1:99999/api/templates', failure = new TypeError('invalid configured URL')
    vi.stubEnv('VITE_TEMPLATE_LIST_ENDPOINT', endpoint); vi.resetModules()
    const configured = (await import('./templatePreview')).default; apiMock.get.mockRejectedValueOnce(failure)
    await expect(configured.listTemplates()).rejects.toBe(failure)
    expect(configured.endpoints.list).toBe(endpoint); expect(apiMock.get).toHaveBeenCalledExactlyOnceWith(endpoint, {}, {})
  })
})
