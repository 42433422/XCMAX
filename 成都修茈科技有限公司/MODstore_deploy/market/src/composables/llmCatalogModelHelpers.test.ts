import { describe, expect, it } from 'vitest'
import {
  categoryLabel,
  modelOptionLabel,
  modelsForCategory,
  LLM_CATEGORY_ORDER,
  type LlmProviderBlock,
  type LlmModelRow,
} from './llmCatalogModelHelpers'

describe('LLM_CATEGORY_ORDER', () => {
  it('has expected categories in order', () => {
    expect(LLM_CATEGORY_ORDER).toEqual(['llm', 'vlm', 'image', 'video', 'other'])
  })
})

describe('categoryLabel', () => {
  it('returns label from catalog when available', () => {
    const catalog = { category_labels: { llm: '大语言模型', vlm: '视觉语言模型' } }
    expect(categoryLabel(catalog, 'llm')).toBe('大语言模型')
  })

  it('falls back to raw category string', () => {
    expect(categoryLabel(null, 'llm')).toBe('llm')
    expect(categoryLabel(undefined, 'vlm')).toBe('vlm')
    expect(categoryLabel({}, 'image')).toBe('image')
  })

  it('falls back when category_labels does not have the key', () => {
    const catalog = { category_labels: { llm: '大语言模型' } }
    expect(categoryLabel(catalog, 'unknown')).toBe('unknown')
  })
})

describe('modelOptionLabel', () => {
  it('returns id when no capability', () => {
    expect(modelOptionLabel({ id: 'gpt-4' })).toBe('gpt-4')
  })

  it('returns id when capability is not an object', () => {
    expect(modelOptionLabel({ id: 'gpt-4', capability: 'string' as any })).toBe('gpt-4')
  })

  it('shows L3 approved tag', () => {
    const row: LlmModelRow = { id: 'gpt-4', capability: { l3_status: 'approved' } }
    expect(modelOptionLabel(row)).toContain('L3已通过')
  })

  it('shows L3 pending tag', () => {
    const row: LlmModelRow = { id: 'gpt-4', capability: { l3_status: 'pending' } }
    expect(modelOptionLabel(row)).toContain('L3审核中')
  })

  it('shows L1 ok tag', () => {
    const row: LlmModelRow = { id: 'gpt-4', capability: { l1_status: 'ok' } }
    expect(modelOptionLabel(row)).toContain('L1探针通过')
  })

  it('shows L1 pending tag', () => {
    const row: LlmModelRow = { id: 'gpt-4', capability: { l1_status: 'pending' } }
    expect(modelOptionLabel(row)).toContain('L1待探针')
  })

  it('shows platform billing restricted tag', () => {
    const row: LlmModelRow = { id: 'gpt-4', capability: { platform_billing_ok: false } }
    expect(modelOptionLabel(row)).toContain('平台计费受限')
  })

  it('shows multiple tags', () => {
    const row: LlmModelRow = { id: 'gpt-4', capability: { l3_status: 'approved', l1_status: 'ok' } }
    const label = modelOptionLabel(row)
    expect(label).toContain('L3已通过')
    expect(label).toContain('L1探针通过')
  })

  it('does not show tag when platform_billing_ok is true', () => {
    const row: LlmModelRow = { id: 'gpt-4', capability: { platform_billing_ok: true } }
    expect(modelOptionLabel(row)).toBe('gpt-4')
  })
})

describe('modelsForCategory', () => {
  it('returns empty array for null block', () => {
    expect(modelsForCategory(null, 'llm')).toEqual([])
  })

  it('returns empty array for undefined block', () => {
    expect(modelsForCategory(undefined, 'llm')).toEqual([])
  })

  it('filters models_detailed by category', () => {
    const block: LlmProviderBlock = {
      provider: 'openai',
      models_detailed: [
        { id: 'gpt-4', category: 'llm' },
        { id: 'gpt-4-vision', category: 'vlm' },
        { id: 'dall-e-3', category: 'image' },
      ],
    }
    expect(modelsForCategory(block, 'llm')).toEqual([{ id: 'gpt-4', category: 'llm' }])
    expect(modelsForCategory(block, 'vlm')).toEqual([{ id: 'gpt-4-vision', category: 'vlm' }])
  })

  it('falls back to models list for llm category', () => {
    const block: LlmProviderBlock = {
      provider: 'openai',
      models: ['gpt-3.5', 'gpt-4'],
    }
    const result = modelsForCategory(block, 'llm')
    expect(result).toHaveLength(2)
    expect(result[0].id).toBe('gpt-3.5')
    expect(result[0].category).toBe('llm')
  })

  it('returns empty for non-llm category when only models list exists', () => {
    const block: LlmProviderBlock = {
      provider: 'openai',
      models: ['gpt-3.5'],
    }
    expect(modelsForCategory(block, 'vlm')).toEqual([])
  })

  it('falls back to models list when models_detailed is empty', () => {
    const block: LlmProviderBlock = {
      provider: 'openai',
      models_detailed: [],
      models: ['gpt-4'],
    }
    const result = modelsForCategory(block, 'llm')
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe('gpt-4')
    expect(result[0].category).toBe('llm')
  })
})
