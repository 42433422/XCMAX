import { req, authHeaders, fetchZipBlob, catalogWriteHeaders } from './shared'

export const mods = {
  listMods: (cacheBust = false) => req(`/api/mods${cacheBust ? `?_=${Date.now()}` : ''}`),
  deleteMod: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}`, { method: 'DELETE' }),
  createMod: (mod_id: string, display_name: string, industry_id = '通用') =>
    req('/api/mods/create', { method: 'POST', body: JSON.stringify({ mod_id, display_name, industry_id }) }),
  importZIP: (file: File, replace = true) => {
    const fd = new FormData()
    fd.append('file', file)
    return req(`/api/mods/import?replace=${replace}`, { method: 'POST', body: fd })
  },
  modAiScaffold: (
    brief: string,
    suggestedId = '',
    replace = true,
    industryId = '通用',
    provider?: string,
    model?: string,
  ) =>
    req('/api/mods/ai-scaffold', {
      method: 'POST',
      body: JSON.stringify({
        brief,
        suggested_id: suggestedId || undefined,
        replace,
        industry_id: industryId || '通用',
        provider,
        model,
      }),
    }),
  push: (mod_ids: unknown = null) => req('/api/sync/push', { method: 'POST', body: JSON.stringify({ mod_ids }) }),
  pull: (mod_ids: unknown = null) => req('/api/sync/pull', { method: 'POST', body: JSON.stringify({ mod_ids }) }),
  getRepoConfig: () => req('/api/config'),
  putRepoConfig: (body: { library_root?: string; xcagi_root?: string; xcagi_backend_url?: string }) =>
    req('/api/config', { method: 'PUT', body: JSON.stringify(body || {}) }),
  getMod: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}`),
  putModManifest: (modId: string, manifest: unknown) => req(`/api/mods/${encodeURIComponent(modId)}/manifest`, { method: 'PUT', body: JSON.stringify({ manifest }) }),
  getModFile: (modId: string, path: string) => req(`/api/mods/${encodeURIComponent(modId)}/file?path=${encodeURIComponent(path)}`),
  putModFile: (modId: string, path: string, content: string) => req(`/api/mods/${encodeURIComponent(modId)}/file`, { method: 'PUT', body: JSON.stringify({ path, content }) }),
  regenerateModFrontend: (modId: string, brief = '') =>
    req(`/api/mods/${encodeURIComponent(modId)}/frontend/regenerate`, { method: 'POST', body: JSON.stringify({ brief }) }),
  listModSnapshots: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}/snapshots`),
  captureModSnapshot: (modId: string, label = '') => req(`/api/mods/${encodeURIComponent(modId)}/snapshots`, { method: 'POST', body: JSON.stringify({ label }) }),
  restoreModSnapshot: (modId: string, snapId: string) => req(`/api/mods/${encodeURIComponent(modId)}/snapshots/${encodeURIComponent(snapId)}/restore`, { method: 'POST', body: '{}' }),
  bumpModManifestPatchVersion: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}/manifest/bump-patch-version`, { method: 'POST', body: '{}' }),
  modWorkflowLink: (modId: string, body: unknown) => req(`/api/mods/${encodeURIComponent(modId)}/workflow-link`, { method: 'POST', body: JSON.stringify(body) }),
  scaffoldWorkflowEmployee: (modId: string, body: unknown) => req(`/api/mods/${encodeURIComponent(modId)}/workflow-employees/scaffold`, { method: 'POST', body: JSON.stringify(body) }),
  getModAuthoringSummary: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}/authoring-summary`),
  getModBlueprintRoutes: (modId: string) => req(`/api/mods/${encodeURIComponent(modId)}/blueprint-routes`),
  getAuthoringExtensionSurface: (mergeHost = false) =>
    req(`/api/authoring/extension-surface?merge_host=${mergeHost ? 'true' : 'false'}`),
  exportEmployeePackZip: async (modId: string, workflowIndex = 0): Promise<Blob> => {
    const mid = String(modId || '').trim()
    const n = Number.parseInt(String(workflowIndex ?? 0), 10)
    const idx = Number.isFinite(n) && n >= 0 ? n : 0
    const q = `workflow_index=${idx}`
    const headers = authHeaders()
    const urls = [
      `/api/mods/${encodeURIComponent(mid)}/export-employee-pack?${q}`,
      `/api/mods/${encodeURIComponent(mid)}/export_employee_pack?${q}`,
    ]
    const staleHint = '8765 上的 API 进程里若没有该路由，会返回 Not Found。请完全退出旧进程后重启：在 MODstore_deploy 目录执行 start-modstore.bat / restart.bat，或手动运行 python -m modstore_server。自检：打开 http://127.0.0.1:8765/docs 搜索「export-employee-pack」，搜不到即仍是旧代码。'
    const looksLikeMissingRoute = (raw: string): boolean => {
      const m = String(raw || '').trim()
      if (/mod\s*不存在|Mod 不存在/i.test(m)) return false
      if (/^not found$/i.test(m)) return true
      if (m === '{"detail":"Not Found"}') return true
      try {
        const j = JSON.parse(m)
        const d = j?.detail
        if (d === 'Not Found') return true
        if (Array.isArray(d) && d.some((x: any) => String(x?.msg || '').toLowerCase() === 'not found')) return true
      } catch { /* ignore */ }
      return false
    }
    let lastErr: unknown
    for (let i = 0; i < urls.length; i++) {
      try {
        return await fetchZipBlob(urls[i], headers)
      } catch (e) {
        lastErr = e
        const msg = String((e as Error)?.message || '').trim()
        if (looksLikeMissingRoute(msg) && i === 0) continue
        break
      }
    }
    const base = String((lastErr as Error)?.message || '导出失败').trim()
    if (looksLikeMissingRoute(base)) {
      throw new Error(`${base} — ${staleHint}`)
    }
    throw lastErr instanceof Error ? lastErr : new Error(base)
  },
  exportModZip: (modId: string) => fetchZipBlob(`/api/mods/${encodeURIComponent(modId)}/export`, authHeaders()),
}

export const packages = {
  auditPackage: (file: File, metadata: unknown = null) => {
    const fd = new FormData()
    fd.append('file', file)
    if (metadata != null) fd.append('metadata', JSON.stringify(metadata))
    return req('/api/package-audit', { method: 'POST', body: fd })
  },
  listV1Packages: (artifact = '', q = '', limit = 50, offset = 0, cacheBust = false) => {
    const p = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (artifact) p.set('artifact', artifact)
    if (q) p.set('q', q)
    if (cacheBust) p.set('_', String(Date.now()))
    return req(`/v1/packages?${p}`)
  },
  listCatalogPackageVersions: (pkgId: string) => req(`/v1/packages/by-id/${encodeURIComponent(pkgId)}/versions`),
  promoteCatalogPackage: (pkgId: string, fromVersion: string) =>
    req(`/v1/packages/${encodeURIComponent(pkgId)}/promote`, { method: 'POST', body: JSON.stringify({ from_version: fromVersion }), headers: catalogWriteHeaders() }),
  downloadCatalogPackageBlob: (pkgId: string, version: string) => fetchZipBlob(`/v1/packages/${encodeURIComponent(pkgId)}/${encodeURIComponent(version)}/download`),
  uploadPackage: (metadata: unknown, file: File) => {
    const fd = new FormData()
    fd.append('metadata', JSON.stringify(metadata))
    fd.append('file', file)
    return req('/v1/packages', { method: 'POST', body: fd, headers: catalogWriteHeaders() })
  },
  registerWorkflowEmployeeCatalog: (modId: string, workflowIndex = 0, opts: { industry?: string; price?: number; release_channel?: string } = {}) =>
    req(`/api/mods/${encodeURIComponent(modId)}/register-workflow-employee-catalog`, {
      method: 'POST',
      body: JSON.stringify({ workflow_index: workflowIndex, industry: opts.industry || '通用', price: opts.price ?? 0, release_channel: opts.release_channel || 'stable' }),
    }),
  patchModWorkflowEmployeeNodes: (modId: string) =>
    req(`/api/mods/${encodeURIComponent(modId)}/patch-workflow-employee-nodes`, { method: 'POST' }),
  runWorkflowEmployeeClosure: (
    modId: string,
    opts: { register_missing?: boolean; patch_canvas?: boolean; industry?: string } = {},
  ) =>
    req(`/api/mods/${encodeURIComponent(modId)}/workflow-employee-closure`, {
      method: 'POST',
      body: JSON.stringify({
        register_missing: opts.register_missing !== false,
        patch_canvas: opts.patch_canvas !== false,
        industry: opts.industry || '通用',
      }),
    }),
}
