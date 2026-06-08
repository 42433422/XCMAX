/**
 * 与 WalletView 中大模型目录下拉一致：按 category 分组、展示 capability 标签。
 * 供钱包页以外（如工作台提示词 inspector）复用。
 */

export const LLM_CATEGORY_ORDER = ['llm', 'vlm', 'image', 'video', 'other'] as const

export type LlmModelRow = {
  id: string
  category?: string
  capability?: Record<string, unknown>
}

export type LlmProviderBlock = {
  provider: string
  label?: string
  models?: string[]
  models_detailed?: LlmModelRow[]
}

export function categoryLabel(catalog: { category_labels?: Record<string, string> } | null | undefined, cat: string): string {
  return catalog?.category_labels?.[cat] || cat
}

export function modelOptionLabel(row: LlmModelRow): string {
  const id = row.id || ''
  const c = row.capability
  if (!c || typeof c !== 'object') return id
  const tags: string[] = []
  if (c.l3_status === 'approved') tags.push('L3已通过')
  else if (c.l3_status === 'pending') tags.push('L3审核中')
  if (c.l1_status === 'ok') tags.push('L1探针通过')
  else if (c.l1_status === 'pending') tags.push('L1待探针')
  if (c.platform_billing_ok === false) tags.push('平台计费受限')
  return tags.length ? `${id}（${tags.join('·')}）` : id
}

export function modelsForCategory(block: LlmProviderBlock | null | undefined, cat: string): LlmModelRow[] {
  if (!block) return []
  const detailed = block.models_detailed
  if (detailed && detailed.length) {
    return detailed.filter((r) => r.category === cat)
  }
  if (cat === 'llm' && block.models?.length) {
    return block.models.map((id) => ({ id, category: 'llm' }))
  }
  return []
}
