import { describe, expect, it, vi } from 'vitest'
import { llmProviderIconImgSrc } from './llmIconUrls'

vi.mock('./llmModels', () => ({
  llmUiMeta: (id: string) => {
    const map: Record<string, { iconSlug: string }> = {
      openai: { iconSlug: 'openai' },
      anthropic: { iconSlug: 'anthropic' },
      deepseek: { iconSlug: 'deepseek' },
      groq: { iconSlug: 'groq' },
      together: { iconSlug: 'togethercomputer' },
      xiaomi: { iconSlug: 'xiaomi' },
    }
    return map[id] || { iconSlug: 'openai' }
  },
}))

describe('llmProviderIconImgSrc', () => {
  it('returns xiaomi data URL for xiaomi provider', () => {
    const result = llmProviderIconImgSrc('xiaomi')
    expect(result).toMatch(/^data:image\/svg\+xml,/)
  })

  it('returns null for deepseek (missing slug)', () => {
    expect(llmProviderIconImgSrc('deepseek')).toBeNull()
  })

  it('returns null for groq (missing slug)', () => {
    expect(llmProviderIconImgSrc('groq')).toBeNull()
  })

  it('returns null for together (missing slug)', () => {
    expect(llmProviderIconImgSrc('together')).toBeNull()
  })

  it('returns CDN URL for openai', () => {
    const result = llmProviderIconImgSrc('openai')
    expect(result).toContain('cdn.jsdelivr.net/npm/simple-icons')
    expect(result).toContain('openai.svg')
  })

  it('returns CDN URL for anthropic', () => {
    const result = llmProviderIconImgSrc('anthropic')
    expect(result).toContain('anthropic.svg')
  })

  it('returns CDN URL for unknown provider using fallback slug', () => {
    const result = llmProviderIconImgSrc('unknown_provider')
    expect(result).toContain('openai.svg')
  })
})
