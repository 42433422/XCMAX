import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/api/system', () => ({
  systemApi: {
    getIndustries: vi.fn().mockResolvedValue({ success: true, data: { industries: [] } }),
    getCurrentIndustry: vi.fn().mockResolvedValue({ success: true, data: { id: '通用', name: '通用', code: '通用' } }),
    setIndustry: vi.fn().mockResolvedValue({ success: true }),
  },
}))

vi.mock('@/api/templatePreview', () => ({
  templatePreviewApi: {
    getTermRules: vi.fn().mockResolvedValue({ success: true, data: {} }),
  },
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    mods: [],
    activeModId: '',
  }),
}))

import { useIndustryStore } from '../industry'

describe('industryStore (readonly SSOT)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('does not have switchIndustry action', () => {
    const store = useIndustryStore()
    expect((store as unknown as { switchIndustry?: unknown }).switchIndustry).toBeUndefined()
  })

  it('does not have mergeModIndustriesInto action', () => {
    const store = useIndustryStore()
    expect(
      (store as unknown as { mergeModIndustriesInto?: unknown }).mergeModIndustriesInto,
    ).toBeUndefined()
  })

  it('has loadFromServer action', () => {
    const store = useIndustryStore()
    expect(typeof (store as unknown as { loadFromServer?: unknown }).loadFromServer).toBe(
      'function',
    )
  })

  it('has termRules state', () => {
    const store = useIndustryStore()
    expect(
      (store as unknown as { termRules?: unknown }).termRules,
    ).toBeDefined()
  })

  it('currentIndustryId defaults to 通用', () => {
    const store = useIndustryStore()
    expect(store.currentIndustryId).toBe('通用')
  })
})
