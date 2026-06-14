import { describe, it, expect, vi, beforeEach } from 'vitest'

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
