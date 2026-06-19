import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mods, packages } from './mods'
import { req, authHeaders, fetchZipBlob, catalogWriteHeaders } from './shared'

vi.mock('./shared', () => ({
  req: vi.fn(),
  authHeaders: vi.fn(() => ({ Authorization: 'Bearer test' })),
  fetchZipBlob: vi.fn(),
  catalogWriteHeaders: vi.fn(() => undefined),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('mods api', () => {
  it('listMods calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await mods.listMods()
    expect(req).toHaveBeenCalledWith('/api/mods')
  })

  it('listMods adds cacheBust param', async () => {
    vi.mocked(req).mockResolvedValue([])
    await mods.listMods(true)
    const call = vi.mocked(req).mock.calls[0] as any[]
    const url = call[0] as string
    expect(url).toContain('_=')
  })

  it('deleteMod encodes modId', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.deleteMod('mod/1')
    expect(req).toHaveBeenCalledWith('/api/mods/mod%2F1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('createMod calls req with POST and industry_id', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.createMod('test-mod', 'Test Mod', '涂料')
    expect(req).toHaveBeenCalledWith(
      '/api/mods/create',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ mod_id: 'test-mod', display_name: 'Test Mod', industry_id: '涂料' }),
      }),
    )
  })

  it('importZIP calls req with FormData', async () => {
    vi.mocked(req).mockResolvedValue({})
    const file = new File(['content'], 'test.zip', { type: 'application/zip' })
    await mods.importZIP(file, true)
    expect(req).toHaveBeenCalledWith('/api/mods/import?replace=true', expect.objectContaining({ method: 'POST' }))
  })

  it('modAiScaffold calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.modAiScaffold('brief', 'suggested', true, '考勤', 'openai', 'gpt-4')
    expect(req).toHaveBeenCalledWith('/api/mods/ai-scaffold', expect.objectContaining({ method: 'POST' }))
  })

  it('modAiScaffold and putRepoConfig apply fallback payload values', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.modAiScaffold('brief', '', true, '', undefined, undefined)
    expect(JSON.parse((vi.mocked(req).mock.calls[0] as any[])[1].body)).toEqual({
      brief: 'brief',
      replace: true,
      industry_id: '通用',
    })

    await mods.putRepoConfig(undefined as any)
    expect(vi.mocked(req).mock.calls[1]).toEqual([
      '/api/config',
      expect.objectContaining({ method: 'PUT', body: '{}' }),
    ])
  })

  it('push calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.push(['mod1'])
    expect(req).toHaveBeenCalledWith('/api/sync/push', expect.objectContaining({ method: 'POST' }))
  })

  it('pull calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.pull(null)
    expect(req).toHaveBeenCalledWith('/api/sync/pull', expect.objectContaining({ method: 'POST' }))
  })

  it('getRepoConfig calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.getRepoConfig()
    expect(req).toHaveBeenCalledWith('/api/config')
  })

  it('putRepoConfig calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.putRepoConfig({ library_root: '/path' })
    expect(req).toHaveBeenCalledWith('/api/config', expect.objectContaining({ method: 'PUT' }))
  })

  it('getMod encodes modId', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.getMod('my mod')
    expect(req).toHaveBeenCalledWith('/api/mods/my%20mod')
  })

  it('putModManifest calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.putModManifest('mod1', { name: 'test' })
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/manifest', expect.objectContaining({ method: 'PUT' }))
  })

  it('getModFile encodes path', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.getModFile('mod1', 'src/main.py')
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/file?path=src%2Fmain.py')
  })

  it('putModFile calls req with PUT', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.putModFile('mod1', 'file.py', 'content')
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/file', expect.objectContaining({ method: 'PUT' }))
  })

  it('regenerateModFrontend calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.regenerateModFrontend('mod1', 'brief')
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/frontend/regenerate', expect.objectContaining({ method: 'POST' }))
  })

  it('listModSnapshots calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await mods.listModSnapshots('mod1')
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/snapshots')
  })

  it('captureModSnapshot calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.captureModSnapshot('mod1', 'label')
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/snapshots', expect.objectContaining({ method: 'POST' }))
  })

  it('restoreModSnapshot calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.restoreModSnapshot('mod1', 'snap1')
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/snapshots/snap1/restore', expect.objectContaining({ method: 'POST' }))
  })

  it('bumpModManifestPatchVersion calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.bumpModManifestPatchVersion('mod1')
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/manifest/bump-patch-version', expect.objectContaining({ method: 'POST' }))
  })

  it('modWorkflowLink calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.modWorkflowLink('mod1', { workflow_id: 1 })
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/workflow-link', expect.objectContaining({ method: 'POST' }))
  })

  it('scaffoldWorkflowEmployee calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.scaffoldWorkflowEmployee('mod1', {})
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/workflow-employees/scaffold', expect.objectContaining({ method: 'POST' }))
  })

  it('getModAuthoringSummary calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.getModAuthoringSummary('mod1')
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/authoring-summary')
  })

  it('getModBlueprintRoutes calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.getModBlueprintRoutes('mod1')
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/blueprint-routes')
  })

  it('getAuthoringExtensionSurface passes mergeHost', async () => {
    vi.mocked(req).mockResolvedValue({})
    await mods.getAuthoringExtensionSurface(true)
    expect(req).toHaveBeenCalledWith('/api/authoring/extension-surface?merge_host=true')
  })

  it('exportModZip calls fetchZipBlob', async () => {
    vi.mocked(fetchZipBlob).mockResolvedValue(new Blob())
    await mods.exportModZip('mod1')
    expect(fetchZipBlob).toHaveBeenCalledWith('/api/mods/mod1/export', expect.any(Object))
  })

  it('exportEmployeePackZip falls back to legacy route on missing new route', async () => {
    const zip = new Blob(['zip'])
    vi.mocked(fetchZipBlob)
      .mockRejectedValueOnce(new Error('Not Found'))
      .mockResolvedValueOnce(zip)

    await expect(mods.exportEmployeePackZip(' mod/1 ', -1)).resolves.toBe(zip)
    expect(fetchZipBlob).toHaveBeenNthCalledWith(
      1,
      '/api/mods/mod%2F1/export-employee-pack?workflow_index=0',
      { Authorization: 'Bearer test' },
    )
    expect(fetchZipBlob).toHaveBeenNthCalledWith(
      2,
      '/api/mods/mod%2F1/export_employee_pack?workflow_index=0',
      { Authorization: 'Bearer test' },
    )
  })

  it('exportEmployeePackZip classifies stale route and non-route errors', async () => {
    vi.mocked(fetchZipBlob)
      .mockRejectedValueOnce(new Error('{\"detail\":\"Not Found\"}'))
      .mockRejectedValueOnce(new Error('{\"detail\":[{\"msg\":\"not found\"}]}'))
    await expect(mods.exportEmployeePackZip('mod1', 1)).rejects.toThrow('8765 上的 API 进程')

    vi.mocked(fetchZipBlob).mockReset()
    vi.mocked(fetchZipBlob).mockRejectedValueOnce(new Error('Mod 不存在'))
    await expect(mods.exportEmployeePackZip('missing', 0)).rejects.toThrow('Mod 不存在')

    vi.mocked(fetchZipBlob).mockReset()
    vi.mocked(fetchZipBlob).mockRejectedValueOnce('string failure')
    await expect(mods.exportEmployeePackZip('mod1', 0)).rejects.toThrow('导出失败')
  })
})

describe('packages api', () => {
  it('auditPackage calls req with FormData', async () => {
    vi.mocked(req).mockResolvedValue({})
    const file = new File(['content'], 'test.zip')
    await packages.auditPackage(file, { key: 'val' })
    expect(req).toHaveBeenCalledWith('/api/package-audit', expect.objectContaining({ method: 'POST' }))
  })

  it('listV1Packages builds query string', async () => {
    vi.mocked(req).mockResolvedValue([])
    await packages.listV1Packages('employee_pack', 'search', 10, 5)
    const call = vi.mocked(req).mock.calls[0] as any[]
    const url = call[0] as string
    expect(url).toContain('artifact=employee_pack')
    expect(url).toContain('q=search')
    expect(url).toContain('limit=10')
  })

  it('listCatalogPackageVersions calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await packages.listCatalogPackageVersions('pkg1')
    expect(req).toHaveBeenCalledWith('/v1/packages/by-id/pkg1/versions')
  })

  it('promoteCatalogPackage calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await packages.promoteCatalogPackage('pkg1', '1.0.0')
    expect(req).toHaveBeenCalledWith('/v1/packages/pkg1/promote', expect.objectContaining({ method: 'POST' }))
  })

  it('downloadCatalogPackageBlob calls fetchZipBlob', async () => {
    vi.mocked(fetchZipBlob).mockResolvedValue(new Blob())
    await packages.downloadCatalogPackageBlob('pkg1', '1.0.0')
    expect(fetchZipBlob).toHaveBeenCalledWith('/v1/packages/pkg1/1.0.0/download')
  })

  it('uploadPackage calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    const file = new File(['content'], 'test.zip')
    await packages.uploadPackage({ name: 'test' }, file)
    expect(req).toHaveBeenCalledWith('/v1/packages', expect.objectContaining({ method: 'POST' }))
  })

  it('registerWorkflowEmployeeCatalog calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await packages.registerWorkflowEmployeeCatalog('mod1', 0, { industry: 'tech', price: 100, release_channel: 'beta' })
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/register-workflow-employee-catalog', expect.objectContaining({ method: 'POST' }))
  })

  it('registerWorkflowEmployeeCatalog and closure use default options', async () => {
    vi.mocked(req).mockResolvedValue({})
    await packages.registerWorkflowEmployeeCatalog('mod1')
    expect(JSON.parse((vi.mocked(req).mock.calls[0] as any[])[1].body)).toEqual({
      workflow_index: 0,
      industry: '通用',
      price: 0,
      release_channel: 'stable',
    })

    await packages.runWorkflowEmployeeClosure('mod1', { register_missing: false, patch_canvas: false, industry: '' })
    expect(JSON.parse((vi.mocked(req).mock.calls[1] as any[])[1].body)).toEqual({
      register_missing: false,
      patch_canvas: false,
      industry: '通用',
    })
  })

  it('patchModWorkflowEmployeeNodes calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await packages.patchModWorkflowEmployeeNodes('mod1')
    expect(req).toHaveBeenCalledWith('/api/mods/mod1/patch-workflow-employee-nodes', expect.objectContaining({ method: 'POST' }))
  })
})
