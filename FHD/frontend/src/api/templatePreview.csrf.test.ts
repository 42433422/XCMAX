import { beforeEach, describe, expect, it, vi } from 'vitest'

const mock = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), prime: vi.fn() }))
vi.mock('./core', () => {
  class ApiError extends Error {
    constructor(message: string, public status: number, public data: unknown = null) { super(message) }
  }
  return { default: { post: mock.post, get: mock.get }, ApiError, primeCsrfCookie: mock.prime }
})
import { ApiError } from './core'
import { templatePreviewApi } from './templatePreview'

describe('reviewed Excel CSRF handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.cookie = 'csrf_token=; Max-Age=0; path=/'
    mock.prime.mockImplementation(async () => { document.cookie = 'csrf_token=initial; path=/' })
    mock.get.mockResolvedValue({ actor: '1:7' })
  })

  it('primes fast upload and retries a rejected request with the current cookie after a concurrent history request', async () => {
    const observed: string[] = []
    mock.get.mockImplementation(async (path: string) => {
      if (path.endsWith('/identity')) return { actor: '1:7' }
      document.cookie = 'csrf_token=other; path=/'
    })
    mock.post.mockImplementation(async () => {
      observed.push(document.cookie)
      if (observed.length === 1) {
        await templatePreviewApi.reviewedExcelHistory('r1')
        throw new ApiError('CSRF token mismatch', 403)
      }
      return { review_id: 'r1' }
    })
    const upload = new FormData()
    upload.set('file', new File(['synthetic'], 'quote.xlsx'))
    expect(await templatePreviewApi.reviewExcel(upload)).toEqual({ review_id: 'r1' })
    expect(mock.prime).toHaveBeenCalledTimes(1)
    expect(observed).toEqual(['csrf_token=initial', 'csrf_token=other'])
    expect(mock.post.mock.calls.map((call) => call[1])).toEqual([upload, upload])
    expect(upload.get('expected_actor')).toBe('1:7')
  })

  it('bounds retries and never retries permission, network, or other errors', async () => {
    mock.post.mockRejectedValue(new ApiError('CSRF token missing', 403))
    await expect(templatePreviewApi.saveReviewedExcel(new FormData())).rejects.toThrow('CSRF token missing')
    expect(mock.post).toHaveBeenCalledTimes(3)
    for (const error of [new ApiError('forbidden', 403), new ApiError('unauthorized', 401), new ApiError('CSRF token mismatch', 500), new Error('network')]) {
      mock.post.mockReset().mockRejectedValue(error)
      await expect(templatePreviewApi.refineReviewedExcel(new FormData())).rejects.toBe(error)
      expect(mock.post).toHaveBeenCalledTimes(1)
    }
  })

  it('does not reuse a token between sessions', async () => {
    const seen: string[] = []
    mock.post.mockImplementation(async () => { seen.push(document.cookie); return {} })
    document.cookie = 'csrf_token=first; path=/'
    await templatePreviewApi.reviewExcel(new FormData())
    document.cookie = 'csrf_token=second; path=/'
    await templatePreviewApi.saveReviewedExcel(new FormData())
    expect(seen).toEqual(['csrf_token=first', 'csrf_token=second'])
  })
})
