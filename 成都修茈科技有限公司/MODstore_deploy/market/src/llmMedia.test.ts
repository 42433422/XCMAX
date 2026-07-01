import { describe, expect, it } from 'vitest'
import {
  pickImageModel,
  pickVideoModel,
  providerHasImageCapability,
  providerHasVideoCapability,
  resolveMediaProviderModel,
} from './llmMedia'

describe('llmMedia', () => {
  it('detects image capability from media_counts', () => {
    expect(
      providerHasImageCapability({
        provider: 'openai',
        media_counts: { image: 2, video: 1 },
        supports_openai_images: true,
      }),
    ).toBe(true)
  })

  it('picks preferred image model', () => {
    expect(
      pickImageModel('dashscope', {
        provider: 'dashscope',
        models_detailed: [
          { id: 'qwen-max', category: 'llm' },
          { id: 'wanx-v1', category: 'image' },
        ],
      }),
    ).toBe('wanx-v1')
  })

  it('resolves image provider from catalog preferences', () => {
    const r = resolveMediaProviderModel('image', {
      preferences: { provider: 'doubao', model: 'doubao-1.5-pro-32k' },
      providers: [
        {
          provider: 'doubao',
          supports_openai_images: true,
          models_detailed: [
            { id: 'doubao-1.5-pro-32k', category: 'llm' },
            { id: 'doubao-seedream-3-0-t2i-250415', category: 'image' },
          ],
          media_counts: { image: 1, video: 0 },
        },
        {
          provider: 'openai',
          supports_openai_images: true,
          models_detailed: [{ id: 'gpt-image-1', category: 'image' }],
          media_counts: { image: 1 },
        },
      ],
    })
    expect(r.provider).toBe('doubao')
    expect(r.model).toContain('seedream')
  })

  it('picks video model when present', () => {
    expect(
      pickVideoModel('zhipu', {
        provider: 'zhipu',
        models_detailed: [
          { id: 'glm-4-flash', category: 'llm' },
          { id: 'cogvideox-2', category: 'video' },
        ],
      }),
    ).toBe('cogvideox-2')
  })

  it('uses Doubao video fallback even when catalog omits media model rows', () => {
    const block = {
      provider: 'doubao',
      supports_openai_images: true,
      models_detailed: [{ id: 'doubao-pro-32k', category: 'llm' }],
      media_counts: { video: 0 },
    }
    expect(providerHasVideoCapability(block)).toBe(true)
    const r = resolveMediaProviderModel('video', {
      preferences: { provider: 'doubao', model: 'doubao-pro-32k' },
      providers: [block],
    })
    expect(r).toEqual({ provider: 'doubao', model: 'doubao-seedance-2-0-260128' })
  })
})
