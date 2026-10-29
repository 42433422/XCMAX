import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import SettingsPlatformModelCard from './SettingsPlatformModelCard.vue'
import { platformModelApi, type PlatformModelConfig, type PlatformModelDraft, type PlatformModelList } from '@/api/platformModel'
import { appConfirm } from '@/utils/appDialog'

vi.mock('@/api/platformModel', () => ({ platformModelApi: { list: vi.fn(), save: vi.fn(), test: vi.fn() } }))
vi.mock('@/utils/appDialog', () => ({ appConfirm: vi.fn() }))

const stored: PlatformModelConfig = {
  provider: 'openai', label: 'OpenAI / OpenAI 兼容', base_url: 'https://models.example.com/v1',
  model: 'platform-model', display_name: '平台模型', has_key: true, masked_key: '****abcd',
  source: 'stored', is_default: true, revision: 'revision-1',
}
const scope = {
  default_provider: 'openai', effective_scope: 'shared_market_gateway',
  scope_description: '共享平台网关的模型调用与默认请求。',
  byok_policy: '显式用户 BYOK 优先，不覆盖用户个人模型选择。',
}
const configList = (): PlatformModelList => ({ ok: true, encryption_ready: true, ...scope,
  providers: [{ ...stored }, { ...stored, provider: 'deepseek', label: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: '', display_name: '', has_key: false, masked_key: '', source: 'none', is_default: false, revision: null }],
})
const wrappers: VueWrapper[] = []
async function render(canManage = true) {
  const wrapper = mount(SettingsPlatformModelCard, { props: { canManage } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
const button = (wrapper: VueWrapper, label: string) => wrapper.findAll('button').find(item => item.text().includes(label))!
const saveResult = (config = stored) => ({ ok: true, config: { ...config }, ...scope })

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(appConfirm).mockResolvedValue(true)
  vi.mocked(platformModelApi.list).mockResolvedValue(configList())
  vi.mocked(platformModelApi.save).mockResolvedValue(saveResult())
  vi.mocked(platformModelApi.test).mockResolvedValue({ ok: true, tested_model: stored.model, latency_ms: 123 })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('platform model settings', () => {
  it('does not expose or request platform configuration without platform admin permission', async () => {
    const wrapper = await render(false)
    expect(wrapper.find('section').exists()).toBe(false)
    expect(platformModelApi.list).not.toHaveBeenCalled()
    expect(platformModelApi.save).not.toHaveBeenCalled()
  })

  it('reads only the masked key and shows actual scope, BYOK priority and independent deployments', async () => {
    const wrapper = await render()
    expect(wrapper.text()).toContain('****abcd')
    expect(wrapper.text()).toContain(scope.scope_description)
    expect(wrapper.text()).toContain(scope.byok_policy)
    expect(wrapper.text()).toContain('独立部署、桌面内网模式和环境变量直连模型不会自动同步')
    expect(wrapper.get<HTMLInputElement>('#platform-model-key').element.value).toBe('')
    expect(wrapper.get('#platform-model-key').attributes('type')).toBe('password')
    expect(wrapper.get('#platform-model-key').attributes('autocomplete')).toBe('new-password')
  })

  it('keeps the current key when blank and sends a revision for concurrency protection', async () => {
    const wrapper = await render()
    await wrapper.get('#platform-model-name').setValue('新展示名称')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(platformModelApi.save).toHaveBeenCalledWith('openai', expect.objectContaining({ display_name: '新展示名称', expected_revision: 'revision-1' }), expect.any(AbortSignal))
    expect(vi.mocked(platformModelApi.save).mock.calls[0][1]).not.toHaveProperty('api_key')
    expect(wrapper.text()).toContain('平台模型配置已保存')
    expect(platformModelApi.test).not.toHaveBeenCalled()
  })

  it('submits a replacement only to the server, then clears it without persisting it', async () => {
    const submitted: PlatformModelDraft[] = []
    vi.mocked(platformModelApi.save).mockImplementation(async (_provider, body) => {
      submitted.push({ ...body })
      return saveResult({ ...stored, masked_key: '****wxyz', revision: 'revision-2' })
    })
    const localWrite = vi.spyOn(Storage.prototype, 'setItem')
    const wrapper = await render()
    await wrapper.get('#platform-model-key').setValue('example-not-real-platform-key')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(submitted[0].api_key).toBe('example-not-real-platform-key')
    expect(wrapper.get<HTMLInputElement>('#platform-model-key').element.value).toBe('')
    expect(wrapper.text()).toContain('****wxyz')
    expect(wrapper.html()).not.toContain('example-not-real-platform-key')
    expect(localWrite).not.toHaveBeenCalled()
    localWrite.mockRestore()
  })

  it('preserves provider labels when the save response only returns configuration fields', async () => {
    const { label: _label, ...config } = stored
    vi.mocked(platformModelApi.save).mockResolvedValue({ ok: true, config, ...scope })
    const wrapper = await render()
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('#platform-model-provider option:checked').text()).toBe(stored.label)
    expect(wrapper.text()).toContain(`平台管理配置的默认供应商：${stored.label}`)
  })

  it('tests a draft without saving and clears the result when a field changes', async () => {
    const wrapper = await render()
    await button(wrapper, '连接测试').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('连接测试成功（123 ms），尚未保存此配置')
    expect(platformModelApi.save).not.toHaveBeenCalled()
    expect(vi.mocked(platformModelApi.test).mock.calls[0][1]).not.toHaveProperty('api_key')
    await wrapper.get('#platform-model-id').setValue('another-model')
    expect(wrapper.text()).not.toContain('连接测试成功')
    expect(wrapper.text()).not.toContain('平台模型配置已保存')
  })

  it('blocks key reuse for a changed endpoint until the administrator supplies a new key', async () => {
    const wrapper = await render()
    await wrapper.get('#platform-model-url').setValue('https://another.example.com/v1')
    await button(wrapper, '连接测试').trigger('click')
    expect(wrapper.text()).toContain('首次配置或修改 API 地址时，请重新输入平台密钥')
    expect(platformModelApi.test).not.toHaveBeenCalled()
    await wrapper.get('#platform-model-key').setValue('example-another-provider-key')
    await button(wrapper, '连接测试').trigger('click')
    await flushPromises()
    expect(platformModelApi.test).toHaveBeenCalledOnce()
  })

  it('clears a key draft when selecting a different provider and requires a first key', async () => {
    const wrapper = await render()
    await wrapper.get('#platform-model-key').setValue('example-original-key')
    await wrapper.get('#platform-model-provider').setValue('deepseek')
    await flushPromises()
    expect(wrapper.get<HTMLInputElement>('#platform-model-key').element.value).toBe('')
    await wrapper.get('#platform-model-id').setValue('other-model')
    await wrapper.get('#platform-model-name').setValue('其他模型')
    await wrapper.get('form').trigger('submit')
    expect(platformModelApi.save).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请重新输入平台密钥')
  })

  it('keeps all unsaved fields and the memory-only key when a provider switch or reload is cancelled', async () => {
    vi.mocked(appConfirm).mockResolvedValue(false)
    const wrapper = await render()
    await wrapper.get('#platform-model-id').setValue('unsaved-model')
    await wrapper.get('#platform-model-key').setValue('synthetic-secret')
    await wrapper.get('#platform-model-provider').setValue('deepseek')
    await flushPromises()
    expect(wrapper.get<HTMLSelectElement>('#platform-model-provider').element.value).toBe('openai')
    expect(wrapper.get<HTMLInputElement>('#platform-model-id').element.value).toBe('unsaved-model')
    expect(wrapper.get<HTMLInputElement>('#platform-model-key').element.value).toBe('synthetic-secret')
    await button(wrapper, '重新读取').trigger('click')
    await flushPromises()
    expect(platformModelApi.list).toHaveBeenCalledTimes(1)
    expect(appConfirm).toHaveBeenCalledTimes(2)
    expect(wrapper.get<HTMLInputElement>('#platform-model-key').element.value).toBe('synthetic-secret')
    vi.mocked(appConfirm).mockResolvedValue(true)
    await button(wrapper, '重新读取').trigger('click')
    await flushPromises()
    expect(platformModelApi.list).toHaveBeenCalledTimes(2)
    expect(wrapper.get<HTMLInputElement>('#platform-model-key').element.value).toBe('')
    expect(wrapper.get<HTMLInputElement>('#platform-model-id').element.value).toBe(stored.model)
  })

  it.each(['http://models.example.com/v1', 'https://user:pass@models.example.com/v1', 'https://models.example.com/v1?key=example', 'https://models.example.com/v1/chat/completions'])('rejects a non-root or credential-bearing endpoint: %s', async endpoint => {
    const wrapper = await render()
    await wrapper.get('#platform-model-url').setValue(endpoint)
    await button(wrapper, '连接测试').trigger('click')
    expect(platformModelApi.test).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('API 地址必须使用 HTTPS')
  })

  it('disables all writes after a failed load and allows an explicit retry', async () => {
    vi.mocked(platformModelApi.list).mockRejectedValueOnce({ status: 502, message: 'example-secret-must-not-appear' })
    const wrapper = await render()
    expect(wrapper.get('fieldset').attributes()).toHaveProperty('disabled')
    await wrapper.get('form').trigger('submit')
    expect(platformModelApi.save).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('example-secret-must-not-appear')
    await button(wrapper, '重新读取').trigger('click')
    await flushPromises()
    expect(wrapper.get('fieldset').attributes()).not.toHaveProperty('disabled')
  })

  it('does not save when server encryption is unavailable', async () => {
    vi.mocked(platformModelApi.list).mockResolvedValue({ ...configList(), encryption_ready: false })
    const wrapper = await render()
    expect(wrapper.text()).toContain('服务端密钥加密尚未就绪')
    expect(button(wrapper, '保存平台配置').attributes()).toHaveProperty('disabled')
    await wrapper.get('form').trigger('submit')
    expect(platformModelApi.save).not.toHaveBeenCalled()
  })

  it.each([401, 403, 409])('fails closed and never renders raw errors after status %s', async status => {
    vi.mocked(platformModelApi.save).mockRejectedValue({ status, message: 'example-secret-in-server-error' })
    const wrapper = await render()
    await wrapper.get('#platform-model-key').setValue('example-pending-key')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('fieldset').attributes()).toHaveProperty('disabled')
    expect(wrapper.get<HTMLInputElement>('#platform-model-key').element.value).toBe('')
    expect(wrapper.text()).not.toContain('example-secret')
    expect(wrapper.text()).not.toContain('平台模型配置已保存')
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })

  it('keeps test failure separate from save state without echoing the provider response', async () => {
    vi.mocked(platformModelApi.test).mockRejectedValue({ status: 502, message: 'echoed-example-key' })
    const wrapper = await render()
    await button(wrapper, '连接测试').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('连接测试失败')
    expect(wrapper.text()).not.toContain('echoed-example-key')
    expect(wrapper.text()).not.toContain('连接测试成功')
    expect(platformModelApi.save).not.toHaveBeenCalled()
  })

  it('blocks duplicate actions in flight, aborts on permission loss, and ignores the stale response', async () => {
    let finish!: (value: { ok: boolean; tested_model: string; latency_ms: number }) => void
    vi.mocked(platformModelApi.test).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    await wrapper.get('#platform-model-key').setValue('example-pending-key')
    await button(wrapper, '连接测试').trigger('click')
    expect(wrapper.get('fieldset').attributes()).toHaveProperty('disabled')
    await wrapper.get('form').trigger('submit')
    expect(platformModelApi.save).not.toHaveBeenCalled()
    const signal = vi.mocked(platformModelApi.test).mock.calls[0][2]
    await wrapper.setProps({ canManage: false })
    expect(signal?.aborted).toBe(true)
    finish({ ok: true, tested_model: stored.model, latency_ms: 10 })
    await flushPromises()
    expect(wrapper.find('section').exists()).toBe(false)
    await wrapper.setProps({ canManage: true })
    await flushPromises()
    expect(wrapper.get<HTMLInputElement>('#platform-model-key').element.value).toBe('')
    expect(wrapper.text()).not.toContain('连接测试成功')
  })
})
