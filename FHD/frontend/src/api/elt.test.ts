import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiFetchMock, primeCsrfCookieMock } = vi.hoisted(() => ({
  apiFetchMock: vi.fn(),
  primeCsrfCookieMock: vi.fn(),
}))

vi.mock('@/api/core', () => ({ primeCsrfCookie: primeCsrfCookieMock }))
vi.mock('@/utils/apiBase', () => ({ apiFetch: apiFetchMock }))

import { eltApi } from './elt'

function response(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  }
}

describe('eltApi', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    primeCsrfCookieMock.mockReset()
    primeCsrfCookieMock.mockResolvedValue(undefined)
    apiFetchMock.mockImplementation(async () => response({ success: true, data: {} }))
  })

  it('reads one intake run by id', async () => {
    await eltApi.run('run/1')
    expect(apiFetchMock).toHaveBeenCalledWith('/api/elt/runs/run%2F1', {})
  })

  it('surfaces the stable server error code and message', async () => {
    apiFetchMock.mockResolvedValueOnce(
      response(
        {
          detail: {
            code: 'ELT_ENTERPRISE_REQUIRED',
            message: '数据对接中心仅在企业版中提供',
          },
        },
        false,
        403,
      ),
    )

    await expect(eltApi.run('run-1')).rejects.toMatchObject({
      message: '数据对接中心仅在企业版中提供',
      code: 'ELT_ENTERPRISE_REQUIRED',
      status: 403,
    })
  })

  it('falls back to an HTTP error when the response body is not JSON', async () => {
    apiFetchMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: vi.fn().mockRejectedValue(new Error('invalid json')),
    })

    await expect(eltApi.run('run-1')).rejects.toMatchObject({
      message: '请求失败 HTTP 502',
      code: 'ELT_REQUEST_FAILED',
      status: 502,
    })
  })
})


describe('etl auto-ingest approval withdraw', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    primeCsrfCookieMock.mockReset()
    primeCsrfCookieMock.mockResolvedValue(undefined)
    apiFetchMock.mockImplementation(async () => response({ success: true, data: { batch_id: 'aib-1', status: 'withdrawn' } }))
  })

  it('posts withdraw for an auto-ingest batch', async () => {
    await eltApi.withdrawAutoIngestBatch('aib/1')
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/elt/auto-ingest/batches/aib%2F1/withdraw',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('reads auto-ingest progress for true bars', async () => {
    apiFetchMock.mockImplementation(async () => response({
      success: true,
      data: {
        batch_id: 'aib-1',
        status: 'running',
        kb_progress: { stage: 'writing', pct: 55 },
        business_progress: { stage: 'preview', pct: 45 },
      },
    }))
    const progress = await eltApi.autoIngestProgress('aib/1')
    expect(progress.kb_progress?.pct).toBe(55)
    expect(String(apiFetchMock.mock.calls[0][0])).toContain('/api/elt/auto-ingest/batches/aib%2F1/progress')
  })

  it('lists auto-ingest batches', async () => {
    apiFetchMock.mockImplementation(async () => response({ success: true, data: [{ batch_id: 'aib-1', status: 'applied' }] }))
    const items = await eltApi.autoIngestBatches(20, true)
    expect(items).toEqual([{ batch_id: 'aib-1', status: 'applied' }])
    expect(String(apiFetchMock.mock.calls[0][0])).toContain('/api/elt/auto-ingest/batches?limit=20&mine=true')
  })
})
