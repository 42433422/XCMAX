import { afterEach, describe, expect, it, vi } from 'vitest'
import { legacyApi } from './api/legacyMonolith'

const mocks = vi.hoisted(() => ({
  clearAuthTokens: vi.fn(),
  fetchZipBlob: vi.fn(),
  getAccessToken: vi.fn(() => 'coverage-token'),
  refreshLevelAndWalletAfterLlm: vi.fn(),
  requestBlob: vi.fn(),
  requestJson: vi.fn(),
  requestStreamBlob: vi.fn(),
  setAuthTokens: vi.fn(),
}))

vi.mock('./infrastructure/http/client', () => ({
  fetchZipBlob: mocks.fetchZipBlob,
  requestBlob: mocks.requestBlob,
  requestJson: mocks.requestJson,
  requestStreamBlob: mocks.requestStreamBlob,
}))

vi.mock('./infrastructure/storage/tokenStore', () => ({
  clearAuthTokens: mocks.clearAuthTokens,
  getAccessToken: mocks.getAccessToken,
  setAuthTokens: mocks.setAuthTokens,
}))

vi.mock('./utils/llmBillingRefresh', () => ({
  refreshLevelAndWalletAfterLlm: mocks.refreshLevelAndWalletAfterLlm,
}))

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('legacyMonolith focused branch coverage', () => {
  it('falls back for employee pack export route variants and surfaces stale route hints', async () => {
    const zip = new Blob(['zip'], { type: 'application/zip' })
    mocks.fetchZipBlob
      .mockRejectedValueOnce(new Error(JSON.stringify({ detail: [{ msg: 'not found' }] })))
      .mockResolvedValueOnce(zip)

    await expect(legacyApi.exportEmployeePackZip('mod 1', -8)).resolves.toBe(zip)
    expect(mocks.fetchZipBlob.mock.calls[0][0]).toBe('/api/mods/mod%201/export-employee-pack?workflow_index=0')
    expect(mocks.fetchZipBlob.mock.calls[1][0]).toBe('/api/mods/mod%201/export_employee_pack?workflow_index=0')

    mocks.fetchZipBlob.mockReset()
    mocks.fetchZipBlob.mockRejectedValue(new Error('{"detail":"Not Found"}'))
    await expect(legacyApi.exportEmployeePackZip('mod-2', 3)).rejects.toThrow('export-employee-pack')

    mocks.fetchZipBlob.mockReset()
    mocks.fetchZipBlob.mockRejectedValueOnce('plain failure')
    await expect(legacyApi.exportEmployeePackZip('mod-3')).rejects.toThrow('导出失败')
  })

  it('maps employee export and script run download fetch failures', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 422,
        json: vi.fn(async () => ({ detail: 'manifest invalid' })),
      })
      .mockResolvedValueOnce({
        ok: false,
        statusText: '',
        blob: vi.fn(async () => new Blob(['unused'])),
      })
    vi.stubGlobal('fetch', fetchMock)

    await expect(legacyApi.employeeExportZip({ bad: true }, 'emp-1', { standalone: true })).rejects.toThrow('manifest invalid')
    await expect(legacyApi.downloadScriptWorkflowRunFile(9, 12, 'report.csv')).rejects.toThrow('下载失败')
  })

  it('returns manifest fallback only for missing employees and rethrows other failures', async () => {
    mocks.requestJson.mockRejectedValueOnce(new Error('404 Not Found'))
    await expect(legacyApi.getEmployeeManifest('missing-pack')).resolves.toEqual({
      pack_id: 'missing-pack',
      name: 'missing-pack',
      version: '0.0.0',
      manifest: {},
    })

    mocks.requestJson.mockRejectedValueOnce(new Error('database down'))
    await expect(legacyApi.getEmployeeManifest('broken-pack')).rejects.toThrow('database down')
  })

  it('refreshes wallet after billed LLM chat and maps PPTX blob responses', async () => {
    mocks.requestJson.mockResolvedValueOnce({ billed: true, charge_amount: 0, content: 'ok' })
    await expect(legacyApi.llmChat('deepseek', 'deepseek-chat', [{ role: 'user', content: 'hi' }])).resolves.toMatchObject({ content: 'ok' })

    const jsonError = new TextEncoder().encode(JSON.stringify({ detail: 'ppt rejected' })).buffer
    const pptBytes = new TextEncoder().encode('pptx').buffer
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false,
        statusText: 'Bad Request',
        arrayBuffer: vi.fn(async () => jsonError),
      })
      .mockResolvedValueOnce({
        ok: true,
        statusText: 'OK',
        arrayBuffer: vi.fn(async () => pptBytes),
      })
    vi.stubGlobal('fetch', fetchMock)

    await expect(legacyApi.llmGeneratePptxBlob('标题', '# 内容')).rejects.toThrow('ppt rejected')
    const blob = await legacyApi.llmGeneratePptxBlob('标题', '# 内容')
    expect(blob.type).toBe('application/vnd.openxmlformats-officedocument.presentationml.presentation')
  })

  it('sends studio asset metadata and knowledge collection owner query parameters', async () => {
    mocks.requestJson.mockResolvedValue({ ok: true })

    await legacyApi.uploadStudioAsset(new File(['asset'], 'asset.png', { type: 'image/png' }), {
      kind: 'image',
      metadata: { owner: 'coverage', width: 320 },
    })
    const uploadInit = mocks.requestJson.mock.calls[0][1] as { body: FormData }
    expect(uploadInit.body.get('kind')).toBe('image')
    expect(uploadInit.body.get('metadata')).toBe(JSON.stringify({ owner: 'coverage', width: 320 }))

    await legacyApi.knowledgeV2ListCollections({ ownerKind: 'employee', ownerId: 'emp/1' })
    expect(mocks.requestJson.mock.calls[1][0]).toBe('/api/knowledge/v2/collections?owner_kind=employee&owner_id=emp%2F1')
  })
})
