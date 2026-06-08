import { describe, expect, it } from 'vitest'
import { LLM_UI_META, llmUiMeta, LLM_OAI_COMPAT_BASE_URL_PROVIDERS } from './llmModels'

describe('LLM_UI_META', () => {
  it('has expected providers', () => {
    expect(Object.keys(LLM_UI_META)).toContain('openai')
    expect(Object.keys(LLM_UI_META)).toContain('anthropic')
    expect(Object.keys(LLM_UI_META)).toContain('google')
    expect(Object.keys(LLM_UI_META)).toContain('deepseek')
  })

  it('each provider has required fields', () => {
    for (const [key, meta] of Object.entries(LLM_UI_META)) {
      expect(meta.id).toBe(key)
      expect(typeof meta.label).toBe('string')
      expect(meta.label.length).toBeGreaterThan(0)
      expect(typeof meta.iconSlug).toBe('string')
      expect(typeof meta.doc).toBe('string')
    }
  })
})

describe('llmUiMeta', () => {
  it('returns known provider meta', () => {
    const meta = llmUiMeta('openai')
    expect(meta.id).toBe('openai')
    expect(meta.label).toBe('OpenAI')
    expect(meta.iconSlug).toBe('openai')
  })

  it('returns fallback for unknown provider', () => {
    const meta = llmUiMeta('unknown-provider')
    expect(meta.id).toBe('unknown-provider')
    expect(meta.label).toBe('unknown-provider')
    expect(meta.iconSlug).toBe('openai')
    expect(meta.doc).toBe('#')
  })

  it('returns fallback for empty string', () => {
    const meta = llmUiMeta('')
    expect(meta.id).toBe('')
    expect(meta.label).toBe('')
  })
})

describe('LLM_OAI_COMPAT_BASE_URL_PROVIDERS', () => {
  it('includes expected providers', () => {
    expect(LLM_OAI_COMPAT_BASE_URL_PROVIDERS).toContain('openai')
    expect(LLM_OAI_COMPAT_BASE_URL_PROVIDERS).toContain('deepseek')
    expect(LLM_OAI_COMPAT_BASE_URL_PROVIDERS).toContain('groq')
    expect(LLM_OAI_COMPAT_BASE_URL_PROVIDERS).toContain('dashscope')
  })

  it('excludes anthropic and google', () => {
    expect(LLM_OAI_COMPAT_BASE_URL_PROVIDERS).not.toContain('anthropic')
    expect(LLM_OAI_COMPAT_BASE_URL_PROVIDERS).not.toContain('google')
  })

  it('all entries exist in LLM_UI_META', () => {
    for (const provider of LLM_OAI_COMPAT_BASE_URL_PROVIDERS) {
      expect(LLM_UI_META[provider as keyof typeof LLM_UI_META]).toBeDefined()
    }
  })
})
