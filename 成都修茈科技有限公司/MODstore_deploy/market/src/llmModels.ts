/** 仅 UI 元数据；真实模型列表来自 GET /api/llm/catalog。
 *
 *  厂商 UI 元数据(label/iconSlug/doc)与 BYOK 自定义 base_url 能力均派生自「模型统一 SSOT」：
 *  唯一真相源 FHD/config/models.yaml → ./config/modelsGenerated.ts。
 *  不再在此硬编码厂商副本。新增/改厂商：改 models.yaml + `ssot sync models --apply`。
 */

import { MODEL_PROVIDERS } from './config/modelsGenerated'

export type LlmUiMetaEntry = { id: string; label: string; iconSlug: string; doc: string }

// catalog_listed=true 的厂商 → UI 元数据 map（顺序沿用 SSOT providers[] 展示顺序）。
export const LLM_UI_META: Record<string, LlmUiMetaEntry> = Object.fromEntries(
  MODEL_PROVIDERS.filter((p) => p.catalog_listed).map((p) => [
    p.id,
    { id: p.id, label: p.label, iconSlug: p.icon_slug, doc: p.doc },
  ]),
)

export function llmUiMeta(providerId: string): LlmUiMetaEntry {
  return (
    LLM_UI_META[providerId] || {
      id: providerId,
      label: providerId,
      iconSlug: 'openai',
      doc: '#',
    }
  )
}

/** 可在 BYOK 中填写自定义 Base URL 的 OpenAI 兼容厂商（byok_custom_base_url=true）。 */
export const LLM_OAI_COMPAT_BASE_URL_PROVIDERS: string[] = MODEL_PROVIDERS.filter(
  (p) => p.byok_custom_base_url,
).map((p) => p.id)
