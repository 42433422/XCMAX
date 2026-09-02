// 模板市场域端点（自 legacyMonolith.ts 拆分，方法体保持不变）
import { req } from './shared'

export const templateEndpoints = {
  // 模板市场
  templatesList: (
    opts: { q?: string; category?: string; difficulty?: string; sort?: string; limit?: number; offset?: number } = {},
  ) => {
    const p = new URLSearchParams()
    if (opts.q) p.set('q', opts.q)
    if (opts.category) p.set('category', opts.category)
    if (opts.difficulty) p.set('difficulty', opts.difficulty)
    if (opts.sort) p.set('sort', opts.sort)
    if (opts.limit) p.set('limit', String(opts.limit))
    if (opts.offset) p.set('offset', String(opts.offset))
    return req(`/api/templates${p.toString() ? '?' + p.toString() : ''}`)
  },
  templatesCategories: () => req('/api/templates/categories'),
  templateDetail: (id: string | number) => req(`/api/templates/${encodeURIComponent(String(id))}`),
  templateInstall: (id: string | number) =>
    req(`/api/templates/${encodeURIComponent(String(id))}/install`, { method: 'POST' }),
  saveWorkflowAsTemplate: (
    workflowId: string | number,
    payload: {
      name: string
      description?: string
      template_category?: string
      template_difficulty?: string
      price?: number
      is_public?: boolean
      industry?: string
    },
  ) =>
    req(`/api/templates/from-workflow/${workflowId}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
