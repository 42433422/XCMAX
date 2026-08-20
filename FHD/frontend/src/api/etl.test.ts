import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiFetchMock, primeCsrfCookieMock } = vi.hoisted(() => ({
  apiFetchMock: vi.fn(),
  primeCsrfCookieMock: vi.fn(),
}))

vi.mock('@/api/core', () => ({ primeCsrfCookie: primeCsrfCookieMock }))
vi.mock('@/utils/apiBase', () => ({ apiFetch: apiFetchMock }))

import { etlApi } from './etl'

function response(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  }
}

describe('etlApi', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    primeCsrfCookieMock.mockReset()
    primeCsrfCookieMock.mockResolvedValue(undefined)
    apiFetchMock.mockImplementation(async () => response({ success: true, data: {} }))
  })

  it('maps every ETL center operation to its stable API route', async () => {
    const file = new File(['unit,name\n1,test'], 'test.csv', { type: 'text/csv' })

    await etlApi.capabilities()
    await etlApi.upload(file, {
      batchId: '11111111-1111-4111-8111-111111111111',
      relativePath: '客户资料/test.csv',
    })
    await etlApi.preview({ upload_id: 'upload/1', target_type: 'customers' })
    await etlApi.runs(12)
    await etlApi.runs(12, 'batch/1')
    await etlApi.run('run/1')
    await etlApi.rows('run/1', 2, 25, 'new')
    await etlApi.patchDraft('run/1', { allowed_update_fields: ['phone'] })
    await etlApi.execute('run/1', true)
    await etlApi.saveShipmentTemplate('run/1', '侯雪梅-发货单版式')
    await etlApi.retry('run/1')
    await etlApi.rollback('run/1')
    await etlApi.templates()
    await etlApi.createTemplate({
      name: '客户模板',
      target_type: 'customers',
      draft: {},
    })
    await etlApi.targetConfigs()
    await etlApi.createTargetConfig({
      name: 'ERP',
      endpoint_url: 'https://erp.example.test/hook',
    })
    await etlApi.updateTargetConfig('target/1', {
      name: 'ERP',
      endpoint_url: 'https://erp.example.test/hook',
    })
    await etlApi.testTarget('target/1')

    const paths = apiFetchMock.mock.calls.map(([path]) => path)
    expect(paths).toEqual([
      '/api/etl/capabilities',
      '/api/etl/uploads',
      '/api/etl/runs/preview',
      '/api/etl/runs?limit=12',
      '/api/etl/runs?limit=12&batch_id=batch%2F1',
      '/api/etl/runs/run%2F1',
      '/api/etl/runs/run%2F1/rows?page=2&page_size=25&action=new',
      '/api/etl/runs/run%2F1/draft',
      '/api/etl/runs/run%2F1/execute',
      '/api/etl/runs/run%2F1/shipment-template',
      '/api/etl/runs/run%2F1/retry',
      '/api/etl/runs/run%2F1/rollback',
      '/api/etl/templates',
      '/api/etl/templates',
      '/api/etl/targets',
      '/api/etl/targets',
      '/api/etl/targets/target%2F1',
      '/api/etl/targets/target%2F1/test',
    ])
    const uploadBody = apiFetchMock.mock.calls[1]?.[1]?.body as FormData
    expect(uploadBody.get('batch_id')).toBe('11111111-1111-4111-8111-111111111111')
    expect(uploadBody.get('relative_path')).toBe('客户资料/test.csv')
    expect(primeCsrfCookieMock).toHaveBeenCalledTimes(11)
    expect(etlApi.exportUrl('run/1')).toBe('/api/etl/runs/run%2F1/download')
    expect(etlApi.errorExportUrl('run/1')).toBe('/api/etl/runs/run%2F1/errors/export')
  })

  it('surfaces the stable server error code and message', async () => {
    apiFetchMock.mockResolvedValueOnce(
      response(
        {
          detail: {
            code: 'ETL_ENTERPRISE_REQUIRED',
            message: '数据对接中心仅在企业版中提供',
          },
        },
        false,
        403,
      ),
    )

    await expect(etlApi.capabilities()).rejects.toMatchObject({
      message: '数据对接中心仅在企业版中提供',
      code: 'ETL_ENTERPRISE_REQUIRED',
      status: 403,
    })
  })

  it('sends the explicitly selected shipment layout region to the save API', async () => {
    await etlApi.saveShipmentTemplate('run/1', '金汉武家私-发货单版式', '侯雪梅!R29C1:10')

    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/etl/runs/run%2F1/shipment-template',
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

    await expect(etlApi.capabilities()).rejects.toMatchObject({
      message: '请求失败 HTTP 502',
      code: 'ETL_REQUEST_FAILED',
      status: 502,
    })
  })
})
