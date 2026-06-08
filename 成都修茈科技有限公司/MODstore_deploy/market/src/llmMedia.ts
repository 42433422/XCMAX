/** 生图/生视频模型选择（与后端 llm_model_taxonomy 分类一致） */

export type LlmModelRow = { id: string; category?: string }

export type CatalogProviderBlock = {
  provider: string
  models?: string[]
  models_detailed?: LlmModelRow[]
  media_counts?: Partial<Record<'image' | 'video' | 'llm' | 'vlm' | 'other', number>>
  supports_openai_images?: boolean
}

const IMAGE_MODEL_PICK_RE = [
  /gpt-image/i,
  /dall-?e/i,
  /seedream/i,
  /flux/i,
  /wanx|wan2/i,
  /cogview/i,
  /imagen/i,
  /kolors/i,
  /stable-diffusion|sdxl|sd3/i,
  /jimeng/i,
]

const VIDEO_MODEL_PICK_RE = [
  /sora/i,
  /veo/i,
  /seedance/i,
  /cogvideo/i,
  /kling/i,
  /hailuo/i,
  /video-01/i,
  /text-to-video|t2v/i,
]

const FALLBACK_IMAGE_BY_PROVIDER: Record<string, string> = {
  openai: 'gpt-image-1',
  dashscope: 'wanx-v1',
  doubao: 'doubao-seedream-3-0-t2i-250415',
  zhipu: 'cogview-3-plus',
  minimax: 'image-01',
  siliconflow: 'black-forest-labs/FLUX.1-schnell',
  together: 'black-forest-labs/FLUX.1-schnell',
  openrouter: 'openai/gpt-4o',
}

function modelsDetailed(block: CatalogProviderBlock | null | undefined): LlmModelRow[] {
  if (!block) return []
  if (Array.isArray(block.models_detailed) && block.models_detailed.length) {
    return block.models_detailed
  }
  return (block.models || []).map((id) => ({ id, category: 'llm' as const }))
}

function pickByPatterns(ids: string[], patterns: RegExp[]): string | '' {
  for (const re of patterns) {
    const hit = ids.find((id) => re.test(id))
    if (hit) return hit
  }
  return ids[0] || ''
}

export function imageModelIds(block: CatalogProviderBlock | null | undefined): string[] {
  return modelsDetailed(block)
    .filter((r) => r.category === 'image')
    .map((r) => r.id)
    .filter(Boolean)
}

export function videoModelIds(block: CatalogProviderBlock | null | undefined): string[] {
  return modelsDetailed(block)
    .filter((r) => r.category === 'video')
    .map((r) => r.id)
    .filter(Boolean)
}

export function providerHasImageCapability(block: CatalogProviderBlock | null | undefined): boolean {
  if (!block) return false
  const n = Number(block.media_counts?.image ?? 0)
  if (n > 0) return true
  if (block.supports_openai_images) return true
  return imageModelIds(block).length > 0
}

export function providerHasVideoCapability(block: CatalogProviderBlock | null | undefined): boolean {
  if (!block) return false
  const n = Number(block.media_counts?.video ?? 0)
  if (n > 0) return true
  return videoModelIds(block).length > 0
}

export function pickImageModel(provider: string, block: CatalogProviderBlock | null | undefined): string {
  const ids = imageModelIds(block)
  const picked = pickByPatterns(ids, IMAGE_MODEL_PICK_RE)
  if (picked) return picked
  return FALLBACK_IMAGE_BY_PROVIDER[provider] || (provider === 'openai' ? 'gpt-image-1' : '')
}

export function pickVideoModel(provider: string, block: CatalogProviderBlock | null | undefined): string {
  const ids = videoModelIds(block)
  const picked = pickByPatterns(ids, VIDEO_MODEL_PICK_RE)
  if (picked) return picked
  if (provider === 'doubao') return 'doubao-seedance-1-0-lite-250428'
  if (provider === 'zhipu') return 'cogvideox-2'
  if (provider === 'minimax') return 'video-01'
  if (provider === 'dashscope') return 'wan2.2-i2v-plus'
  return ''
}

export function resolveMediaProviderModel(
  kind: 'image' | 'video',
  catalog: { providers?: CatalogProviderBlock[]; preferences?: { provider?: string; model?: string } } | null,
): { provider: string; model: string } {
  const providers = catalog?.providers || []
  const prefP = String(catalog?.preferences?.provider || '').trim()
  const prefBlock = providers.find((p) => p.provider === prefP)
  const hasCap = kind === 'image' ? providerHasImageCapability : providerHasVideoCapability
  const pick = kind === 'image' ? pickImageModel : pickVideoModel

  if (prefBlock && hasCap(prefBlock)) {
    const model = pick(prefP, prefBlock)
    if (model) return { provider: prefP, model }
  }

  for (const block of providers) {
    if (!hasCap(block)) continue
    const model = pick(block.provider, block)
    if (model) return { provider: block.provider, model }
  }

  if (kind === 'image') {
    return { provider: 'openai', model: 'gpt-image-1' }
  }
  return { provider: prefP || 'openai', model: '' }
}
