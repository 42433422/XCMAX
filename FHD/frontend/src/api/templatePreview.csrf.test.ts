import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'

const mock = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), prime: vi.fn() }))
vi.mock('./core', () => {
  class ApiError extends Error {
    constructor(message: string, public status: number, public data: unknown = null) { super(message) }
  }
  return { default: { post: mock.post, get: mock.get }, ApiError, primeCsrfCookie: mock.prime }
})
import { ApiError } from './core'
import { templatePreviewApi } from './templatePreview'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
function account(id: number) {
  updateProductReadAccountScope({ tenantId: 1, localUserId: id, accountKind: 'enterprise' })
}

describe('reviewed Excel CSRF handling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mock.post.mockReset()
    invalidateEnterpriseSessionCache()
    account(7)
    document.cookie = 'csrf_token=; Max-Age=0; path=/'
    mock.prime.mockImplementation(async () => { document.cookie = 'csrf_token=initial; path=/' })
    mock.get.mockResolvedValue({ actor: '1:7' })
  })
  afterEach(() => vi.useRealTimers())

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

  it('keeps safe failure diagnostics visible without retrying or exposing arbitrary stage data', async () => {
    const data = { request_id: 'elt-request-7', stage: 'render_candidates' }
    mock.post.mockRejectedValueOnce(new ApiError('文件处理失败', 500, data))
    await expect(templatePreviewApi.reviewExcel(new FormData())).rejects.toMatchObject({
      message: '文件处理失败（阶段：渲染候选） 请求编号：elt-request-7', status: 500, data,
    })
    expect(mock.post).toHaveBeenCalledTimes(1)
    for (const bad of [{ request_id: 'secret\nvalue', stage: 'render_candidates' }, { request_id: 'safe', stage: 'private workbook content' }]) {
      mock.post.mockRejectedValueOnce(new ApiError('文件处理失败', 500, bad))
      const failure = await templatePreviewApi.reviewExcel(new FormData()).catch(error => error)
      expect(failure.message).not.toContain('secret')
      expect(failure.message).not.toContain('private workbook')
    }
  })

  it.each(['A→B', 'A→B→A'])('rejects a late identity response across %s without sending the original file', async transition => {
    const identity = deferred<{ actor: string }>()
    mock.get.mockReturnValue(identity.promise)
    const form = new FormData()
    form.set('file', new File(['synthetic'], 'original.xlsx'))
    const pending = templatePreviewApi.archiveClassifyExcel(form)
    const rejected = expect(pending).rejects.toThrow('登录身份已变化')
    account(8)
    if (transition === 'A→B→A') account(7)
    identity.resolve({ actor: transition === 'A→B' ? '1:8' : '1:7' })
    await rejected
    expect(mock.get).toHaveBeenCalledTimes(1)
    expect(mock.prime).not.toHaveBeenCalled()
    expect(mock.post).not.toHaveBeenCalled()
    expect(form.get('expected_actor')).toBeNull()
  })

  it('classifies a late identity failure after logout as an obsolete session error', async () => {
    let rejectIdentity!: (error: Error) => void
    mock.get.mockReturnValue(new Promise((_resolve, reject) => { rejectIdentity = reject }))
    const pending = templatePreviewApi.archiveClassifyExcel(new FormData())
    const rejected = expect(pending).rejects.toMatchObject({ name: 'ReviewedExcelSessionChangedError' })
    invalidateEnterpriseSessionCache()
    rejectIdentity(new Error('old account network failure'))
    await rejected
    expect(mock.post).not.toHaveBeenCalled()
  })

  it('keeps a delayed identity response usable within the initiating session', async () => {
    const identity = deferred<{ actor: string }>()
    mock.get.mockReturnValue(identity.promise)
    mock.post.mockResolvedValue({ classification_id: 'c1' })
    const form = new FormData()
    const pending = templatePreviewApi.archiveClassifyExcel(form)
    identity.resolve({ actor: '1:7' })
    await expect(pending).resolves.toEqual({ classification_id: 'c1' })
    expect(form.get('expected_actor')).toBe('1:7')
    expect(mock.post).toHaveBeenCalledExactlyOnceWith('/api/templates/reviewed-excel/archive-classify', form)
  })

  it.each(['initial request', 'CSRF retry'])('stops when the session changes during CSRF priming for %s', async phase => {
    const primed = deferred<void>()
    mock.prime.mockReturnValue(primed.promise)
    if (phase === 'CSRF retry') {
      document.cookie = 'csrf_token=before; path=/'
      mock.post.mockImplementationOnce(async () => {
        document.cookie = 'csrf_token=; Max-Age=0; path=/'
        throw new ApiError('CSRF token mismatch', 403)
      })
    }
    const pending = templatePreviewApi.archiveClassifyExcel(new FormData())
    const rejected = expect(pending).rejects.toThrow('登录身份已变化')
    await flushPromises()
    expect(mock.prime).toHaveBeenCalledTimes(1)
    account(8)
    document.cookie = 'csrf_token=after; path=/'
    primed.resolve()
    await rejected
    expect(mock.get).toHaveBeenCalledTimes(1)
    expect(mock.post).toHaveBeenCalledTimes(phase === 'initial request' ? 0 : 1)
  })

  it('does not retry a previously rejected CSRF request after an account change during backoff', async () => {
    vi.useFakeTimers()
    document.cookie = 'csrf_token=before; path=/'
    mock.post.mockRejectedValueOnce(new ApiError('CSRF token mismatch', 403)).mockResolvedValueOnce({})
    const pending = templatePreviewApi.archiveClassifyExcel(new FormData())
    const rejected = expect(pending).rejects.toThrow('登录身份已变化')
    await vi.advanceTimersByTimeAsync(0)
    expect(mock.post).toHaveBeenCalledTimes(1)
    account(8)
    await vi.advanceTimersByTimeAsync(50)
    await rejected
    expect(mock.post).toHaveBeenCalledTimes(1)
  })

  it('retires a pending identity request after logout even when the account ID is unchanged', async () => {
    const identity = deferred<{ actor: string }>()
    mock.get.mockReturnValue(identity.promise)
    const pending = templatePreviewApi.reviewExcel(new FormData())
    const rejected = expect(pending).rejects.toThrow('登录身份已变化')
    invalidateEnterpriseSessionCache()
    identity.resolve({ actor: '1:7' })
    await rejected
    expect(mock.post).not.toHaveBeenCalled()
  })

  it('does not return a late POST result to a different account or resend the original data', async () => {
    const written = deferred<{ review_id: string }>()
    document.cookie = 'csrf_token=before; path=/'
    mock.post.mockReturnValue(written.promise)
    const pending = templatePreviewApi.reviewExcel(new FormData())
    const rejected = expect(pending).rejects.toThrow('登录身份已变化')
    await flushPromises()
    expect(mock.post).toHaveBeenCalledTimes(1)
    account(8)
    written.resolve({ review_id: 'old-account-result' })
    await rejected
    expect(mock.post).toHaveBeenCalledTimes(1)
    expect(mock.get).toHaveBeenCalledTimes(1)
  })
})
