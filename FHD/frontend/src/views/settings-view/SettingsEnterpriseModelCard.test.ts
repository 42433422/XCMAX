import { flushPromises, mount } from '@vue/test-utils'
import { ElOption, ElSelect } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import SettingsEnterpriseModelCard from './SettingsEnterpriseModelCard.vue'

const { get, put, catalog, changed } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), catalog: vi.fn(), changed: vi.fn() }))
vi.mock('@/api/core', () => ({ api: { get, put } }))
vi.mock('@/api/marketAccount', () => ({ fetchMarketLlmCatalog: catalog }))
vi.mock('@/api/platformModel', () => ({ notifyPlatformModelChanged: changed }))

const settings = { owner_id: 'tenant:2', editable: true, revision: 3, provider: null, model: null }
beforeEach(() => {
  vi.resetAllMocks()
  get.mockResolvedValue(settings)
  catalog.mockResolvedValue({ providers: [{ provider: 'p', models_detailed: [
    { id: 'runtime', runtime_selectable: true }, { id: 'vision-only', runtime_selectable: false },
  ] }] })
})

describe('enterprise model settings', () => {
  it('presents real runtime choices and sends a scoped, explicit save', async () => {
    put.mockResolvedValue({ ...settings, provider: 'p', model: 'runtime', revision: 4 })
    const wrapper = mount(SettingsEnterpriseModelCard, { props: { owner: 'tenant:2', activeModel: 'active' } })
    await flushPromises()
    expect(wrapper.text()).toContain('active')
    expect(wrapper.findAllComponents(ElOption).map(row => row.props('label'))).toEqual(['跟随账号默认模型', 'p · runtime'])
    expect(put).not.toHaveBeenCalled()
    wrapper.getComponent(ElSelect).vm.$emit('update:modelValue', JSON.stringify(['p', 'runtime']))
    await flushPromises()
    await wrapper.get('[data-testid="enterprise-model-save"]').trigger('click')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('/api/workspace/model',
      { provider: 'p', model: 'runtime', expected_owner_id: 'tenant:2', expected_revision: 3 }, expect.objectContaining({ retry: false }))
    expect(changed).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('retires an in-flight response across an account epoch change', async () => {
    let resolve!: (value: typeof settings) => void
    get.mockReturnValueOnce(new Promise(done => { resolve = done }))
    const wrapper = mount(SettingsEnterpriseModelCard, { props: { owner: 'tenant:2' } })
    productReadAccountEpoch.value++
    get.mockResolvedValue({ ...settings, editable: false })
    await wrapper.setProps({ owner: 'tenant:3' })
    resolve(settings)
    await flushPromises()
    expect(wrapper.getComponent(ElSelect).props('disabled')).toBe(true)
    expect(put).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
