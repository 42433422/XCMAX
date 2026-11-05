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

  it('sends exact source coordinates through the existing paged rows endpoint', async () => {
    await eltApi.rows('run/1', 1, 50, 'new', { sheet: '报价 & 单价', row: 99998 })
    expect(apiFetchMock).toHaveBeenCalledWith('/api/elt/runs/run%2F1/rows?page=1&page_size=50&action=new&source_sheet=%E6%8A%A5%E4%BB%B7%20%26%20%E5%8D%95%E4%BB%B7&source_row=99998', {})
  })

  it('maps every ETL center operation to its stable API route', async () => {
    const file = new File(['unit,name\n1,test'], 'test.csv', { type: 'text/csv' })

    await eltApi.capabilities()
    await eltApi.upload(file, {
      batchId: '11111111-1111-4111-8111-111111111111',
      relativePath: '客户资料/test.csv',
    })
    await eltApi.preview({ upload_id: 'upload/1', target_type: 'customers' })
    await eltApi.runs(12)
    await eltApi.runs(12, 'batch/1')
    await eltApi.run('run/1')
    await eltApi.rows('run/1', 2, 25, 'new')
    await eltApi.patchDraft('run/1', { allowed_update_fields: ['phone'] })
    await eltApi.execute('run/1', 'reviewed-revision', true)
    await eltApi.saveShipmentTemplate('run/1', '侯雪梅-发货单版式')
    await eltApi.retry('run/1')
    await eltApi.replay('run/1')
    await eltApi.rollback('run/1')
    await eltApi.templates()
    await eltApi.createTemplate({
      name: '客户模板',
      target_type: 'customers',
      draft: {},
    })
    await eltApi.targetConfigs()
    await eltApi.createTargetConfig({
      name: 'ERP',
      endpoint_url: 'https://erp.example.test/hook',
    })
    await eltApi.updateTargetConfig('target/1', {
      name: 'ERP',
      endpoint_url: 'https://erp.example.test/hook',
    })
    await eltApi.testTarget('target/1')

    const paths = apiFetchMock.mock.calls.map(([path]) => path)
    expect(paths).toEqual([
      '/api/elt/capabilities',
      '/api/elt/uploads',
      '/api/elt/runs/preview',
      '/api/elt/runs?limit=12',
      '/api/elt/runs?limit=12&batch_id=batch%2F1',
      '/api/elt/runs/run%2F1',
      '/api/elt/runs/run%2F1/rows?page=2&page_size=25&action=new',
      '/api/elt/runs/run%2F1/draft',
      '/api/elt/runs/run%2F1/execute',
      '/api/elt/runs/run%2F1/shipment-template',
      '/api/elt/runs/run%2F1/retry',
      '/api/elt/runs/run%2F1/replay',
      '/api/elt/runs/run%2F1/rollback',
      '/api/elt/templates',
      '/api/elt/templates',
      '/api/elt/targets',
      '/api/elt/targets',
      '/api/elt/targets/target%2F1',
      '/api/elt/targets/target%2F1/test',
    ])
    expect(JSON.parse(apiFetchMock.mock.calls[8][1].body)).toEqual({ confirmed: true, preview_revision: 'reviewed-revision', valid_rows_only: true })
    const uploadBody = apiFetchMock.mock.calls[1]?.[1]?.body as FormData
    expect(uploadBody.get('batch_id')).toBe('11111111-1111-4111-8111-111111111111')
    expect(uploadBody.get('relative_path')).toBe('客户资料/test.csv')
    expect(primeCsrfCookieMock).toHaveBeenCalledTimes(12)
    expect(eltApi.exportUrl('run/1')).toBe('/api/elt/runs/run%2F1/download')
    expect(eltApi.errorExportUrl('run/1')).toBe('/api/elt/runs/run%2F1/errors/export')
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

    await expect(eltApi.capabilities()).rejects.toMatchObject({
      message: '数据对接中心仅在企业版中提供',
      code: 'ELT_ENTERPRISE_REQUIRED',
      status: 403,
    })
  })

  it.each([
    { detail: { code: 'FORBIDDEN', message: '权限不足: etl.rollback' } },
    { success: false, error_code: 'http_403', message: "{'code': 'FORBIDDEN', 'message': '权限不足: etl.rollback'}" },
  ])('turns rollback permission denials into readable guidance', async (body) => {
    apiFetchMock.mockResolvedValueOnce(response(body, false, 403))
    await expect(eltApi.rollback('run-1')).rejects.toMatchObject({
      message: '当前账号没有撤销权限，请联系管理员授权后重试。',
      code: 'FORBIDDEN',
      status: 403,
    })
  })

  it('sends the explicitly selected shipment layout region to the save API', async () => {
    await eltApi.saveShipmentTemplate('run/1', '金汉武家私-发货单版式', '侯雪梅!R29C1:10')

    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/elt/runs/run%2F1/shipment-template',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          name: '金汉武家私-发货单版式',
          source_region_id: '侯雪梅!R29C1:10',
        }),
      }),
    )
    expect(primeCsrfCookieMock).toHaveBeenCalledTimes(1)
  })

  it('falls back to an HTTP error when the response body is not JSON', async () => {
    apiFetchMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: vi.fn().mockRejectedValue(new Error('invalid json')),
    })

    await expect(eltApi.capabilities()).rejects.toMatchObject({
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
