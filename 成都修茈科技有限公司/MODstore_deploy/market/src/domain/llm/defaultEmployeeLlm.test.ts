import { describe, expect, it } from 'vitest'
import { resolveDefaultEmployeeLlmFromStatusAndCatalog, STATIC_DEFAULT_EMPLOYEE_LLM } from './defaultEmployeeLlm'

describe('resolveDefaultEmployeeLlmFromStatusAndCatalog', () => {
  it('falls back when status missing', () => {
    expect(resolveDefaultEmployeeLlmFromStatusAndCatalog(null, null)).toEqual({
      ...STATIC_DEFAULT_EMPLOYEE_LLM,
    })
  })

  it('picks first provider with platform key and catalog model', () => {
    const out = resolveDefaultEmployeeLlmFromStatusAndCatalog(
      {
        providers: [
          { provider: 'deepseek', has_platform_key: false },
          { provider: 'openai', has_platform_key: true },
        ],
        fernet_configured: true,
      },
      { providers: [{ provider: 'openai', models: ['gpt-4o-mini', 'gpt-4o'] }] },
    )
    expect(out).toEqual({ provider: 'openai', model_name: 'gpt-4o-mini' })
  })

  it('uses default model name when catalog has no list', () => {
    const out = resolveDefaultEmployeeLlmFromStatusAndCatalog(
      {
        providers: [{ provider: 'anthropic', has_platform_key: true }],
        fernet_configured: true,
      },
      { providers: [{ provider: 'anthropic', models: [] }] },
    )
    expect(out.provider).toBe('anthropic')
    expect(out.model_name).toContain('claude')
  })
})
