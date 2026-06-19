import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import LlmPricingAdminPanel from './LlmPricingAdminPanel.vue'

const apiMock = vi.hoisted(() => ({
  llmAdminOfficialSources: vi.fn(),
  llmAdminSyncOfficialPrices: vi.fn(),
  llmAdminPricingSettings: vi.fn(),
  llmAdminApplyOfficialMarkup: vi.fn(),
  llmAdminListPricing: vi.fn(),
  llmAdminBatchPricing: vi.fn(),
  llmAdminSavePrice: vi.fn(),
}))

vi.mock('../../api', () => ({ api: apiMock }))

function listResponse(settings: Record<string, unknown> = {}) {
  return {
    settings,
    items: [
      {
        provider: 'openai',
        model: 'gpt-4o',
        label: 'GPT 4o',
        official_input_price_per_1k: '0.0123',
        official_output_price_per_1k: null,
        official_source: 'curated',
        input_price_per_1k: '0.02',
        output_price_per_1k: '0.05',
        min_charge: '0.01',
        enabled: false,
      },
    ],
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.llmAdminOfficialSources.mockResolvedValue({ source_url: 'https://pricing.example/openai' })
  apiMock.llmAdminListPricing.mockResolvedValue(listResponse({
    service_fee_multiplier: '2',
    default_input_price_per_1k: '0.01',
    default_output_price_per_1k: '0.03',
    default_min_charge: '0.02',
  }))
  apiMock.llmAdminPricingSettings.mockResolvedValue({ settings: { official_markup_multiplier: 2 } })
  apiMock.llmAdminSyncOfficialPrices.mockResolvedValue({ updated: 2, skipped: 1, apply_markup: { applied: 2 } })
  apiMock.llmAdminApplyOfficialMarkup.mockResolvedValue({ applied: 3, skipped: 1 })
  apiMock.llmAdminBatchPricing.mockResolvedValue({ written: 4 })
  apiMock.llmAdminSavePrice.mockResolvedValue({ ok: true })
})

describe('LlmPricingAdminPanel', () => {
  it('loads pricing data and covers save, sync, batch, row, and new-row flows', async () => {
    const wrapper = mount(LlmPricingAdminPanel, {
      props: { provider: 'openai', providerLabel: 'OpenAI' },
    })
    await flushPromises()

    const vm = wrapper.vm as any
    expect(apiMock.llmAdminListPricing).toHaveBeenCalledWith({ provider: 'openai', limit: 500 })
    expect(apiMock.llmAdminOfficialSources).toHaveBeenCalledWith('openai')
    expect(vm.officialSourceUrl).toBe('https://pricing.example/openai')
    expect(vm.settingsForm.service_fee_multiplier).toBe(2)
    expect(vm.settingsForm.official_markup_multiplier).toBe(2)
    expect(vm.priceRows[0]._edit.enabled).toBe(false)
    expect(vm.fmtOfficial(null)).toBe('—')
    expect(vm.fmtOfficial('0.12345')).toBe('0.1235')

    await vm.saveSettings()
    expect(apiMock.llmAdminPricingSettings).toHaveBeenCalledWith(expect.objectContaining({
      service_fee_multiplier: 2,
      default_min_charge: 0.02,
    }))
    expect(vm.note).toBe('全局计费参数已保存')

    await vm.syncOfficial(false)
    expect(apiMock.llmAdminSyncOfficialPrices).toHaveBeenCalledWith(expect.objectContaining({
      provider: 'openai',
      apply_markup: false,
    }))
    expect(vm.note).toContain('已同步官网价 2 条')

    await vm.syncOfficial(true)
    expect(vm.note).toContain('已应用倍率 2 条')

    await vm.applyMarkup()
    expect(apiMock.llmAdminApplyOfficialMarkup).toHaveBeenCalledWith({ provider: 'openai', multiplier: 2 })
    expect(vm.note).toContain('写入售价 3 条')

    await vm.runBatch('unpriced_only')
    await vm.runBatch('all_catalog')
    expect(apiMock.llmAdminBatchPricing).toHaveBeenCalledWith(expect.objectContaining({ mode: 'all_catalog' }))

    vm.priceRows[0]._edit.enabled = true
    await vm.saveRow(vm.priceRows[0])
    expect(apiMock.llmAdminSavePrice).toHaveBeenCalledWith(expect.objectContaining({
      provider: 'openai',
      model: 'gpt-4o',
      enabled: true,
    }))

    vm.newRow.model = 'gpt-new'
    vm.newRow.input_price_per_1k = 0.1
    await vm.saveNewRow()
    expect(apiMock.llmAdminSavePrice).toHaveBeenCalledWith(expect.objectContaining({ model: 'gpt-new' }))
    expect(vm.newRow.model).toBe('')
    expect(wrapper.emitted('saved')?.length).toBeGreaterThan(0)
  })

  it('covers early returns and error branches', async () => {
    const wrapper = mount(LlmPricingAdminPanel, {
      props: { provider: 'openai', providerLabel: 'OpenAI' },
    })
    await flushPromises()

    const vm = wrapper.vm as any
    vm.newRow.model = '   '
    await vm.saveNewRow()
    expect(apiMock.llmAdminSavePrice).not.toHaveBeenCalled()

    apiMock.llmAdminOfficialSources.mockRejectedValueOnce(new Error('source down'))
    await vm.loadOfficialSource()
    expect(vm.officialSourceUrl).toBe('')

    apiMock.llmAdminListPricing.mockRejectedValueOnce(new Error('list down'))
    await vm.loadPrices()
    expect(vm.err).toContain('list down')

    apiMock.llmAdminPricingSettings.mockRejectedValueOnce(new Error('settings down'))
    await vm.saveSettings()
    expect(vm.err).toContain('settings down')

    apiMock.llmAdminSyncOfficialPrices.mockRejectedValueOnce(new Error('sync down'))
    await vm.syncOfficial(false)
    expect(vm.err).toContain('sync down')

    apiMock.llmAdminApplyOfficialMarkup.mockRejectedValueOnce(new Error('markup down'))
    await vm.applyMarkup()
    expect(vm.err).toContain('markup down')

    apiMock.llmAdminBatchPricing.mockRejectedValueOnce(new Error('batch down'))
    await vm.runBatch('all_catalog')
    expect(vm.err).toContain('batch down')

    apiMock.llmAdminSavePrice.mockRejectedValueOnce(new Error('row down'))
    await vm.saveRow(vm.priceRows[0])
    expect(vm.err).toContain('row down')

    apiMock.llmAdminSavePrice.mockRejectedValueOnce(new Error('new down'))
    vm.newRow.model = 'gpt-bad'
    await vm.saveNewRow()
    expect(vm.err).toContain('new down')

    await wrapper.setProps({ provider: 'deepseek' })
    await flushPromises()
    expect(apiMock.llmAdminListPricing).toHaveBeenCalledWith({ provider: 'deepseek', limit: 500 })
  })
})
