import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'

const mock = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn(), download: vi.fn(), prime: vi.fn() }))
vi.mock('./core', () => {
  class ApiError extends Error {
    constructor(message: string, public status: number, public data: unknown = null) { super(message) }
  }
  return { default: { post: mock.post, get: mock.get, download: mock.download }, ApiError, primeCsrfCookie: mock.prime }
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
    mock.download.mockReset()
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

  it('preserves structured model failure state without retrying the request', async () => {
    const data = { detail: { code: 'model_processing_failed', message: '模型连接异常，结果未知，请核对', retryable: false, outcome_unknown: true } }
    mock.post.mockRejectedValueOnce(new ApiError('Service Unavailable', 503, data))
    await expect(templatePreviewApi.reviewExcel(new FormData())).rejects.toMatchObject({ message: data.detail.message, status: 503, data })
    expect(mock.post).toHaveBeenCalledTimes(1)
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

  it('does not send original bytes when the current identity cannot be established', async () => {
    const form = new FormData(); form.set('file', new File(['synthetic private workbook'], 'original.xlsx'))
    form.set('expected_actor', 'stale:actor'); mock.get.mockResolvedValueOnce({ actor: '' })
    await expect(templatePreviewApi.classifyExcel(form)).rejects.toThrow('无法确认当前登录身份')
    expect(mock.post).not.toHaveBeenCalled(); expect(mock.prime).not.toHaveBeenCalled()
  })

  it('preserves authorization and read-only archive inventory without claiming a model call', async () => {
    const identity = { actor: '1:7', login_authorization: { status: 'notice_not_published' } }, quota = { configured: true, limit_bytes: 1000, reserved_bytes: 42 }
    const assets = { assets: [{ id: 'asset-7', versions: [{ id: 'version-1', sha256: 'original-hash' }] }] }, history = { files: [{ classification_id: 'class-7', latest: { model_status: 'not_called' } }] }
    mock.get.mockResolvedValueOnce(identity).mockResolvedValueOnce(quota).mockResolvedValueOnce(assets).mockResolvedValueOnce(history)
    expect(await templatePreviewApi.reviewedExcelIdentity()).toBe(identity); expect(await templatePreviewApi.archiveQuota()).toBe(quota)
    expect(await templatePreviewApi.archiveAssets()).toBe(assets); expect(await templatePreviewApi.recentClassifications()).toBe(history)
    expect(mock.get.mock.calls.map(call => call[0])).toEqual(['/api/templates/reviewed-excel/identity', '/api/templates/reviewed-excel/archive-quota', '/api/templates/reviewed-excel/archive-assets', '/api/templates/reviewed-excel/classifications'])
    expect(mock.post).not.toHaveBeenCalled(); expect(mock.prime).not.toHaveBeenCalled()
  })

  it('binds archive quota and an appended original to the freshly resolved actor', async () => {
    const quota = new FormData(); quota.set('limit_bytes', '2048'); quota.set('expected_actor', 'stale')
    const source = new File([new Uint8Array([0x50, 0x4b, 0xff])], '原件.xlsx'), version = new FormData()
    version.set('file', source); version.set('request_key', 'synthetic-upload-1')
    const response = { version_id: 'server-version', sha256: 'server-source-hash' }
    mock.post.mockResolvedValueOnce({ configured: true }).mockResolvedValueOnce(response)
    await templatePreviewApi.setArchiveQuota(quota)
    expect(await templatePreviewApi.appendArchiveVersion('asset/7?draft', version)).toBe(response)
    expect(quota.get('expected_actor')).toBe('1:7'); expect(quota.get('limit_bytes')).toBe('2048')
    expect(version.get('expected_actor')).toBe('1:7'); expect(version.get('file')).toBe(source); expect(version.get('request_key')).toBe('synthetic-upload-1')
    expect(mock.post.mock.calls).toEqual([['/api/templates/reviewed-excel/archive-quota', quota], ['/api/templates/reviewed-excel/archive-assets/asset%2F7%3Fdraft/versions', version]])
  })

  it.each([
    ['setArchiveAssetState', '/api/templates/reviewed-excel/archive-assets/scope%2F7%3Fdraft/state'],
    ['recoverArchiveVersion', '/api/templates/reviewed-excel/archive-versions/scope%2F7%3Fdraft/recover'],
    ['classifyArchiveVersion', '/api/templates/reviewed-excel/archive-versions/scope%2F7%3Fdraft/classify'],
  ] as const)('keeps %s within its encoded scope and rejects rather than fabricating success', async (method, path) => {
    const form = new FormData(); form.set('expected_actor', 'old:account'); form.set('state', 'active')
    const failure = new ApiError('没有当前归档操作权限', 403, { error_code: 'permission_denied' })
    mock.post.mockRejectedValueOnce(failure)
    await expect(templatePreviewApi[method]('scope/7?draft', form)).rejects.toBe(failure)
    expect(form.get('expected_actor')).toBe('1:7'); expect(mock.post).toHaveBeenCalledExactlyOnceWith(path, form)
    expect(mock.get).toHaveBeenCalledExactlyOnceWith('/api/templates/reviewed-excel/identity')
  })

  it('returns scoped model slices and review identity without rewriting either response', async () => {
    const slices = { classification_id: 'class/7', version: 'v/2', slices: [{ index: 3, basis: 'model_group', sha256: 'derived-hash', source_sha256: 'original-hash', filename: '采购单.xlsx' }] }
    const review = { review_id: 'review/7', status: 'template_review_ready', selected_region: { auto_slice_index: 3 }, receipt: {} }
    mock.get.mockResolvedValueOnce(slices).mockResolvedValueOnce(review)
    expect(await templatePreviewApi.autoSlices('class/7', 'v/2')).toBe(slices); expect(await templatePreviewApi.reviewedExcelHistory('review/7')).toBe(review)
    expect(mock.get.mock.calls).toEqual([['/api/templates/reviewed-excel/classifications/class%2F7/auto-slices/v%2F2'], ['/api/templates/reviewed-excel/reviews/review%2F7']])
    expect(mock.post).not.toHaveBeenCalled()
  })

  it('preserves distinct whole-original, document-slice and candidate download bytes and scope', async () => {
    const downloads = [
      ['/api/templates/reviewed-excel/archive-versions/version%2F7/download', () => templatePreviewApi.downloadArchiveVersion('version/7')],
      ['/api/templates/reviewed-excel/classifications/class%2F7/source', () => templatePreviewApi.downloadClassificationSource('class/7')],
      ['/api/templates/reviewed-excel/classifications/class%2F7/auto-slices/v%2F2/3', () => templatePreviewApi.downloadAutoSlice('class/7', 'v/2', 3)],
      ['/api/templates/reviewed-excel/reviews/review%2F7/versions/p%2F2/candidates/candidate%2F3/download', () => templatePreviewApi.downloadReviewedCandidate('review/7', 'p/2', 'candidate/3')],
    ] as const
    for (const [index, [path, download]] of downloads.entries()) {
      const bytes = new Uint8Array([0x50, 0x4b, index, 0xff]), original = new Response(bytes, { headers: { 'cache-control': 'no-store' } })
      mock.download.mockResolvedValueOnce(original)
      const response = await download()
      expect(response).toBe(original); expect(response.headers.get('cache-control')).toBe('no-store')
      expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes); expect(mock.download).toHaveBeenLastCalledWith(path)
    }
    expect(mock.post).not.toHaveBeenCalled()
  })

  it('accepts a database template id and rejects path-like ids before downloading', async () => {
    const response = new Response(new Uint8Array([0x50, 0x4b, 7])); mock.download.mockResolvedValueOnce(response)
    expect(await templatePreviewApi.downloadReviewedExcel('db:42')).toBe(response)
    expect(mock.download).toHaveBeenCalledExactlyOnceWith('/api/templates/reviewed-excel/42/download')
    for (const id of ['db:../42', '42?token=private', 'file:/source']) expect(() => templatePreviewApi.downloadReviewedExcel(id)).toThrow('模板编号无效')
    expect(mock.download).toHaveBeenCalledTimes(1)
  })

  it('returns a paused classification without authorizing another model round', async () => {
    const form = new FormData(); form.set('version', 'classification-v1'); form.set('use_login_notice', 'true')
    const paused = { phase: 'paused', checkpoint: { max_calls: 4, calls_in_round: 4, version: 'classification-v1' } }; mock.post.mockResolvedValueOnce(paused)
    expect(await templatePreviewApi.analyzeClassification('class/7', form)).toBe(paused)
    expect(form.get('continue_authorized')).toBeNull(); expect(form.get('retry_authorized')).toBeNull()
    expect(mock.post).toHaveBeenCalledExactlyOnceWith('/api/templates/reviewed-excel/classifications/class%2F7/analyze', form); expect(mock.get).not.toHaveBeenCalled()
  })

  it('keeps classification confirmation and intake preview separate from model dispatch and saving', async () => {
    const confirmation = new FormData(); confirmation.set('version', 'classification-v1'); confirmation.set('labels_json', '[]')
    const intake = new FormData(); intake.set('review_id', 'review-7'); intake.set('proposal_version', 'p2'); intake.set('candidate_id', 'candidate-3'); intake.set('selections', '[]')
    const confirmed = { version: 'confirmed-v2', confirmed: true }, plan = { intake: { run_id: 'intake-7', business: { status: 'preview_ready', preview_revision: 'r1' } } }
    mock.post.mockResolvedValueOnce(confirmed).mockResolvedValueOnce(plan)
    expect(await templatePreviewApi.confirmClassification('class/7', confirmation)).toBe(confirmed); expect(await templatePreviewApi.previewReviewedIntake(intake)).toBe(plan)
    expect(mock.post.mock.calls).toEqual([['/api/templates/reviewed-excel/classifications/class%2F7/confirm', confirmation], ['/api/templates/reviewed-excel/intake-preview', intake]])
    expect(mock.post.mock.calls.some(call => call[0].endsWith('/save') || call[0].endsWith('/analyze'))).toBe(false)
  })

  it.each([false, true])('preserves correlated model error metadata without acting automatically on retryable=%s', async retryable => {
    const state = { code: retryable ? 'model_configuration_error' : 'model_processing_failed', message: '模型处理未完成，请核对', retryable, outcome_unknown: !retryable }
    const data = retryable ? { ...state, error_code: state.code, request_id: 'model-error-7', stage: 'model_candidates' } : { detail: state, request_id: 'model-error-7', stage: 'model_candidates' }
    mock.post.mockRejectedValueOnce(new ApiError(state.message, 503, data))
    await expect(templatePreviewApi.refineReviewedExcel(new FormData())).rejects.toMatchObject({ status: 503, data, message: '模型处理未完成，请核对（阶段：模型候选） 请求编号：model-error-7' })
    expect(mock.post).toHaveBeenCalledTimes(1)
  })

})
