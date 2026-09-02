// 创作素材域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { requestBlob } from '../../infrastructure/http/client'
import { req } from './shared'

export const studioAssetEndpoints = {
  listStudioAssets: (params?: { offset?: number; limit?: number }) => {
    const o = params?.offset ?? 0
    const l = params?.limit ?? 50
    return req(`/api/workbench/studio-assets?offset=${encodeURIComponent(String(o))}&limit=${encodeURIComponent(String(l))}`)
  },
  uploadStudioAsset: (file: File, opts?: { kind?: string; metadata?: Record<string, unknown> }) => {
    const form = new FormData()
    form.append('file', file)
    if (opts?.kind) form.append('kind', opts.kind)
    if (opts?.metadata && Object.keys(opts.metadata).length) {
      form.append('metadata', JSON.stringify(opts.metadata))
    }
    return req('/api/workbench/studio-assets', { method: 'POST', body: form })
  },
  deleteStudioAsset: (id: number) =>
    req(`/api/workbench/studio-assets/${encodeURIComponent(String(id))}`, { method: 'DELETE' }),
  patchStudioAssetMetadata: (id: number, metadata: Record<string, unknown>) =>
    req(`/api/workbench/studio-assets/${encodeURIComponent(String(id))}`, {
      method: 'PATCH',
      body: JSON.stringify({ metadata }),
    }),
  downloadStudioAssetBlob: (id: number) =>
    requestBlob(`/api/workbench/studio-assets/${encodeURIComponent(String(id))}/file`),
}
