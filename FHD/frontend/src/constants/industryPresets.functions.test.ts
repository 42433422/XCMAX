import { describe, it, expect, beforeEach } from 'vitest'
import {
  INDUSTRY_PRESET_IDS,
  INDUSTRY_PRESETS,
  listIndustryPresetIdList,
  getIndustryPreset,
  industryPresetFromManifest,
  listIndustryPresets,
  getIndustryQuickButtons,
  isIndustryWelcomePlainText,
  getIndustryWelcomeMarkdown,
  manifestIndustryFromPreset,
} from './industryPresets'
import { industryPresetIds, industryPresets as industryPresetsRef } from '@/stores/hostConfig'

describe('industryPresets constants and functions', () => {
  beforeEach(() => {
    industryPresetIds.value = []
    industryPresetsRef.value = {}
  })

  describe('INDUSTRY_PRESET_IDS', () => {
    it('contains 8 preset ids', () => {
      expect(INDUSTRY_PRESET_IDS).toHaveLength(8)
    })

    it('contains 通用', () => {
      expect(INDUSTRY_PRESET_IDS).toContain('通用')
    })

    it('contains 涂料', () => {
      expect(INDUSTRY_PRESET_IDS).toContain('涂料')
    })

    it('contains 管理端', () => {
      expect(INDUSTRY_PRESET_IDS).toContain('管理端')
    })
  })

  describe('INDUSTRY_PRESETS', () => {
    it('has 通用 preset', () => {
      expect(INDUSTRY_PRESETS['通用']).toBeTruthy()
    })

    it('通用 preset has welcomeIntro', () => {
      expect(INDUSTRY_PRESETS['通用'].welcomeIntro).toBeTruthy()
    })

    it('涂料 preset has menuLabels', () => {
      expect(Object.keys(INDUSTRY_PRESETS['涂料'].menuLabels).length).toBeGreaterThan(0)
    })
  })

  describe('listIndustryPresetIdList', () => {
    it('returns built-in ids when API provides none', () => {
      const result = listIndustryPresetIdList()
      expect(result).toEqual([...INDUSTRY_PRESET_IDS])
    })

    it('returns API-provided ids when available', () => {
      industryPresetIds.value = ['custom-1', 'custom-2']
      expect(listIndustryPresetIdList()).toEqual(['custom-1', 'custom-2'])
    })
  })

  describe('getIndustryPreset', () => {
    it('returns 通用 for empty string', () => {
      expect(getIndustryPreset('').id).toBe('通用')
    })

    it('returns 通用 for whitespace string', () => {
      expect(getIndustryPreset('   ').id).toBe('通用')
    })

    it('returns 涂料 for 涂料 id', () => {
      expect(getIndustryPreset('涂料').id).toBe('涂料')
    })

    it('returns 通用 fallback for unknown id', () => {
      expect(getIndustryPreset('unknown').id).toBe('通用')
    })

    it('returns API-provided preset when available', () => {
      industryPresetsRef.value = { 'custom': { id: 'custom', name: 'Custom', scenario: '', welcomeIntro: 'hi', welcomeBullets: [], quickButtons: [], placeholderNormal: '', placeholderPro: '', menuLabels: {}, uiLabels: {} } }
      expect(getIndustryPreset('custom').id).toBe('custom')
    })
  })

  describe('industryPresetFromManifest', () => {
    it('returns null for null input', () => {
      expect(industryPresetFromManifest(null)).toBeNull()
    })

    it('returns null for undefined input', () => {
      expect(industryPresetFromManifest(undefined)).toBeNull()
    })

    it('returns null for empty object', () => {
      expect(industryPresetFromManifest({})).toBeNull()
    })

    it('returns null when id is empty', () => {
      expect(industryPresetFromManifest({ id: '' })).toBeNull()
    })

    it('returns existing preset for known id', () => {
      const result = industryPresetFromManifest({ id: '涂料' })
      expect(result?.id).toBe('涂料')
    })

    it('builds preset from manifest for unknown id', () => {
      const result = industryPresetFromManifest({
        id: 'custom-industry',
        name: 'Custom',
        scenario: 'Custom scenario',
      })
      expect(result?.id).toBe('custom-industry')
      expect(result?.name).toBe('Custom')
      expect(result?.scenario).toBe('Custom scenario')
    })

    it('uses id as name when name is empty', () => {
      const result = industryPresetFromManifest({ id: 'custom' })
      expect(result?.name).toBe('custom')
    })

    it('parses menu_overrides array', () => {
      const result = industryPresetFromManifest({
        id: 'custom',
        menu_overrides: [{ key: 'products', label: '产品' }],
      })
      expect(result?.menuLabels.products).toBe('产品')
    })

    it('skips menu_overrides entries without key or label', () => {
      const result = industryPresetFromManifest({
        id: 'custom',
        menu_overrides: [{ key: '', label: 'x' }, { key: 'y', label: '' }, { key: 'a', label: 'b' }],
      })
      expect(result?.menuLabels).toEqual({ a: 'b' })
    })

    it('uses ui_labels from manifest when provided', () => {
      const result = industryPresetFromManifest({
        id: 'custom',
        ui_labels: { entity: '项目' },
      })
      expect(result?.uiLabels.entity).toBe('项目')
    })

    it('uses default ui_labels when not provided', () => {
      const result = industryPresetFromManifest({ id: 'custom' })
      expect(result?.uiLabels.entity).toBe('条目')
    })

    it('parses welcome_bullets array', () => {
      const result = industryPresetFromManifest({
        id: 'custom',
        welcome_bullets: ['a', 'b', 'c'],
      })
      expect(result?.welcomeBullets).toEqual(['a', 'b'])
    })

    it('uses default welcome_bullets when not provided', () => {
      const result = industryPresetFromManifest({ id: 'custom' })
      expect(result?.welcomeBullets.length).toBeGreaterThan(0)
    })

    it('parses quick_buttons array', () => {
      const result = industryPresetFromManifest({
        id: 'custom',
        quick_buttons: [{ text: 'x', label: 'y' }],
      })
      expect(result?.quickButtons).toEqual([{ text: 'x', label: 'y' }])
    })
  })

  describe('listIndustryPresets', () => {
    it('returns presets for all built-in ids', () => {
      const result = listIndustryPresets()
      expect(result).toHaveLength(INDUSTRY_PRESET_IDS.length)
    })

    it('first preset is 通用', () => {
      const result = listIndustryPresets()
      expect(result[0].id).toBe('通用')
    })
  })

  describe('getIndustryQuickButtons', () => {
    it('returns quick buttons for 通用', () => {
      const result = getIndustryQuickButtons('通用')
      expect(result.length).toBeGreaterThan(0)
    })

    it('returns a copy (not the original array)', () => {
      const result1 = getIndustryQuickButtons('通用')
      const result2 = getIndustryQuickButtons('通用')
      expect(result1).not.toBe(result2)
      expect(result1).toEqual(result2)
    })

    it('returns quick buttons for unknown id (fallback to 通用)', () => {
      const result = getIndustryQuickButtons('unknown')
      expect(result.length).toBeGreaterThan(0)
    })
  })

  describe('isIndustryWelcomePlainText', () => {
    it('returns false for empty string', () => {
      expect(isIndustryWelcomePlainText('')).toBe(false)
    })

    it('returns false for whitespace string', () => {
      expect(isIndustryWelcomePlainText('   ')).toBe(false)
    })

    it('returns true for legacy attendance welcome text', () => {
      expect(isIndustryWelcomePlainText('您好！我是您的智能考勤助手，请问需要什么帮助？')).toBe(true)
    })

    it('returns true for 通用 welcome intro', () => {
      expect(isIndustryWelcomePlainText(INDUSTRY_PRESETS['通用'].welcomeIntro)).toBe(true)
    })

    it('returns true for 涂料 welcome intro', () => {
      expect(isIndustryWelcomePlainText(INDUSTRY_PRESETS['涂料'].welcomeIntro + ' 后续内容')).toBe(true)
    })

    it('returns false for unknown text', () => {
      expect(isIndustryWelcomePlainText('这是一段未知文本')).toBe(false)
    })
  })

  describe('getIndustryWelcomeMarkdown', () => {
    it('returns markdown with welcome intro', () => {
      const md = getIndustryWelcomeMarkdown('通用')
      expect(md).toContain(INDUSTRY_PRESETS['通用'].welcomeIntro)
    })

    it('contains bullet points', () => {
      const md = getIndustryWelcomeMarkdown('通用')
      expect(md).toContain('- ')
    })

    it('contains 请说出需求', () => {
      const md = getIndustryWelcomeMarkdown('通用')
      expect(md).toContain('请说出需求')
    })

    it('works for unknown id (fallback to 通用)', () => {
      const md = getIndustryWelcomeMarkdown('unknown')
      expect(md).toContain(INDUSTRY_PRESETS['通用'].welcomeIntro)
    })
  })

  describe('manifestIndustryFromPreset', () => {
    it('returns manifest object with id', () => {
      const result = manifestIndustryFromPreset('涂料')
      expect(result.id).toBe('涂料')
    })

    it('returns manifest object with name', () => {
      const result = manifestIndustryFromPreset('涂料')
      expect(result.name).toBe(INDUSTRY_PRESETS['涂料'].name)
    })

    it('returns manifest with ui_labels', () => {
      const result = manifestIndustryFromPreset('涂料')
      expect(result.ui_labels).toBeTruthy()
    })

    it('returns manifest with menu_overrides array', () => {
      const result = manifestIndustryFromPreset('涂料')
      expect(Array.isArray(result.menu_overrides)).toBe(true)
    })

    it('returns manifest with units', () => {
      const result = manifestIndustryFromPreset('通用')
      expect(result.units).toBeTruthy()
      expect(result.units?.primary).toBeTruthy()
    })

    it('returns manifest with product_fields', () => {
      const result = manifestIndustryFromPreset('通用')
      expect(result.product_fields).toBeTruthy()
    })

    it('works for unknown id (fallback to 通用)', () => {
      const result = manifestIndustryFromPreset('unknown')
      expect(result.id).toBe('通用')
    })
  })
})
