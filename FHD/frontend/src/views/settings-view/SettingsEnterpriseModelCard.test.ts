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
    { id: 'runtime', runtime_selectable: true, execution: { selectable: true, protocol: 'chat_completions' },
      model_capabilities: { context_window: 900, max_input_tokens: 500, max_output_tokens: 300 } },
    { id: 'vision-only', runtime_selectable: false },
  ] }] })
})

describe('enterprise model settings', () => {
  it('disables models rejected by the authoritative executor guards without hiding chat models', async () => {
    catalog.mockResolvedValue({ providers: [{ provider: 'p', runtime_models: ['runtime', 'blocked', 'legacy'], models_detailed: [
      { id: 'runtime', execution: { selectable: true } },
      { id: 'blocked', execution: { selectable: false, message: '当前密钥协议不支持执行器。' } },
      { id: 'legacy' },
    ] }] })
    const wrapper = mount(SettingsEnterpriseModelCard, { props: { owner: 'tenant:2' } })
    await flushPromises()
    const options = wrapper.findAllComponents(ElOption)
    expect(options[2].props('disabled')).toBe(true)
    expect(options[2].props('label')).toContain('当前密钥协议不支持执行器')
    expect(options[3].props('label')).toContain('兼容性待校验')
    wrapper.getComponent(ElSelect).vm.$emit('update:modelValue', JSON.stringify(['p', 'blocked']))
    await flushPromises()
    await wrapper.get('[data-testid="enterprise-model-save"]').trigger('click')
    expect(put).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    [422, { detail: { code: 'runtime_configuration_required', message: '当前模型缺少有效的上下文容量和最大输出量。' } }],
    [422, { detail: '当前模型地址或密钥协议不支持独立运行。' }],
    [503, { message: '平台模型配置暂时无法读取，请检查网络后重试。' }],
  ])('shows the public save failure without claiming a configuration change (%s)', async (status, data) => {
    put.mockRejectedValue({ status, data })
    const wrapper = mount(SettingsEnterpriseModelCard, { props: { owner: 'tenant:2', activeModel: 'original' } })
    await flushPromises()
    wrapper.getComponent(ElSelect).vm.$emit('update:modelValue', JSON.stringify(['p', 'runtime']))
    await flushPromises()
    await wrapper.get('[data-testid="enterprise-model-save"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toMatch(/容量|协议|网络/)
    expect(wrapper.text()).toContain('original')
    expect(changed).not.toHaveBeenCalled()
    expect(put).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('presents real runtime choices and sends a scoped, explicit save', async () => {
    put.mockResolvedValue({ ...settings, provider: 'p', model: 'runtime', revision: 4 })
    const wrapper = mount(SettingsEnterpriseModelCard, { props: { owner: 'tenant:2', activeModel: 'active' } })
    await flushPromises()
    expect(wrapper.text()).toContain('active')
    expect(wrapper.findAllComponents(ElOption).map(row => row.props('label'))).toEqual(['跟随账号默认模型', 'p · runtime'])
    expect(put).not.toHaveBeenCalled()
    wrapper.getComponent(ElSelect).vm.$emit('update:modelValue', JSON.stringify(['p', 'runtime']))
    await flushPromises()
    expect(wrapper.text()).toContain('Chat Completions → Responses · 可用输入 500 tokens · 最大输出 300 tokens')
    await flushPromises()
    await wrapper.get('[data-testid="enterprise-model-save"]').trigger('click')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('/api/workspace/model',
      { provider: 'p', model: 'runtime', expected_owner_id: 'tenant:2', expected_revision: 3 }, expect.objectContaining({ retry: false }))
    expect(changed).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('retries an unrelated preference revision without overwriting a changed model', async () => {
    get.mockResolvedValueOnce(settings).mockResolvedValueOnce({ ...settings, revision: 4 })
    put.mockRejectedValueOnce({ status: 409 }).mockResolvedValueOnce({ ...settings, provider: 'p', model: 'runtime', revision: 5 })
    const wrapper = mount(SettingsEnterpriseModelCard, { props: { owner: 'tenant:2' } })
    await flushPromises()
    wrapper.getComponent(ElSelect).vm.$emit('update:modelValue', JSON.stringify(['p', 'runtime']))
    await flushPromises()
    await flushPromises()
    await wrapper.get('[data-testid="enterprise-model-save"]').trigger('click')
    await flushPromises()
    expect(put).toHaveBeenCalledTimes(2)
    expect(put).toHaveBeenLastCalledWith('/api/workspace/model',
      { provider: 'p', model: 'runtime', expected_owner_id: 'tenant:2', expected_revision: 4 }, expect.objectContaining({ retry: false }))
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
