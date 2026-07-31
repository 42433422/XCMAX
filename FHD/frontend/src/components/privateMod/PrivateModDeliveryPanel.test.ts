import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import PrivateModDeliveryPanel from './PrivateModDeliveryPanel.vue'

const mockApiFetch = vi.fn()

vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}))

function okJson(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => ({ success: true, data }),
  }
}

function failJson(status: number, body: Record<string, unknown> = {}) {
  return {
    ok: false,
    status,
    json: async () => body,
  }
}

const sampleProject = {
  mod_id: 'customer-mod',
  name: '客户 Mod',
  description: '定制交付说明',
  current_version: '1.0.0',
  latest_version: '1.1.0',
  update_available: true,
  overall_status: 'partial',
  overall_label: '部分完成',
  business_modules: [{ id: 'biz-1', label: '订单台' }],
  ai_employees: [{ id: 'emp-1', label: '出货员', summary: '负责标签' }],
  tracks: {
    business: { status: 'testing' },
    employees: { status: 'production' },
  },
  stage_labels: {
    business: { testing: '业务测试中' },
  },
}

describe('PrivateModDeliveryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue(okJson({ projects: [], stages: [] }))
  })

  it('shows empty state when account has no private mods', async () => {
    const wrapper = mount(PrivateModDeliveryPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('当前账号还没有绑定客户私有 Mod')
  })

  it('renders projects, modules, employees, and update affordance', async () => {
    mockApiFetch.mockResolvedValue(
      okJson({
        projects: [sampleProject],
        stages: ['production', 'testing', 'rework', 'acceptance', 'delivered'],
        remote_error: 'mirror offline',
      }),
    )
    const wrapper = mount(PrivateModDeliveryPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('客户 Mod')
    expect(wrapper.text()).toContain('订单台')
    expect(wrapper.text()).toContain('出货员')
    expect(wrapper.text()).toContain('负责标签')
    expect(wrapper.text()).toContain('私有版本 v1.1.0 可更新')
    expect(wrapper.text()).toContain('私有版本检查暂不可用：mirror offline')
    expect(wrapper.text()).toContain('业务测试中')
  })

  it('shows error when private delivery load fails', async () => {
    mockApiFetch.mockResolvedValue(failJson(500, { detail: 'boom' }))
    const wrapper = mount(PrivateModDeliveryPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('boom')
  })

  it('saves track status and reloads delivery', async () => {
    mockApiFetch
      .mockResolvedValueOnce(
        okJson({
          projects: [sampleProject],
          stages: ['production', 'testing', 'rework', 'acceptance', 'delivered'],
        }),
      )
      .mockResolvedValueOnce(okJson({}))
      .mockResolvedValueOnce(
        okJson({
          projects: [{ ...sampleProject, tracks: { business: { status: 'acceptance' }, employees: { status: 'production' } } }],
          stages: ['production', 'testing', 'rework', 'acceptance', 'delivered'],
        }),
      )

    const wrapper = mount(PrivateModDeliveryPanel)
    await flushPromises()
    const select = wrapper.get('select[aria-label="业务模块交付阶段"]')
    await select.setValue('acceptance')
    await flushPromises()

    expect(mockApiFetch).toHaveBeenCalledWith(
      '/api/mod-store/private-delivery/status',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ mod_id: 'customer-mod', track: 'business', status: 'acceptance' }),
      }),
    )
    expect(wrapper.text()).toContain('客户 Mod')
  })

  it('updates private mod when update button clicked', async () => {
    mockApiFetch
      .mockResolvedValueOnce(
        okJson({
          projects: [sampleProject],
          stages: ['production', 'testing', 'rework', 'acceptance', 'delivered'],
        }),
      )
      .mockResolvedValueOnce(okJson({}))
      .mockResolvedValueOnce(
        okJson({
          projects: [{ ...sampleProject, update_available: false, current_version: '1.1.0' }],
          stages: ['production', 'testing', 'rework', 'acceptance', 'delivered'],
        }),
      )

    const wrapper = mount(PrivateModDeliveryPanel)
    await flushPromises()
    await wrapper.get('.private-mod-center__update').trigger('click')
    await flushPromises()

    expect(mockApiFetch).toHaveBeenCalledWith(
      '/api/mod-store/private-mod/update',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ mod_id: 'customer-mod', latest_version: '1.1.0' }),
      }),
    )
    expect(wrapper.text()).toContain('已是最新私有版本')
  })

  it('shows empty track placeholders when modules and employees are absent', async () => {
    mockApiFetch.mockResolvedValue(
      okJson({
        projects: [
          {
            ...sampleProject,
            update_available: false,
            business_modules: [],
            ai_employees: [],
          },
        ],
        stages: ['production', 'testing'],
      }),
    )
    const wrapper = mount(PrivateModDeliveryPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('当前 Mod 未声明侧栏模块')
    expect(wrapper.text()).toContain('当前 Mod 未声明 AI 员工')
    expect(wrapper.text()).toContain('已是最新私有版本')
  })

  it('surfaces save/update failures and network throw paths', async () => {
    mockApiFetch
      .mockResolvedValueOnce(
        okJson({
          projects: [sampleProject],
          stages: ['production', 'testing', 'rework', 'acceptance', 'delivered'],
        }),
      )
      .mockResolvedValueOnce(failJson(400, { message: 'status denied' }))
      .mockResolvedValueOnce(
        okJson({
          projects: [sampleProject],
          stages: ['production', 'testing', 'rework', 'acceptance', 'delivered'],
        }),
      )
      .mockResolvedValueOnce(failJson(500, { error: 'update denied' }))

    const wrapper = mount(PrivateModDeliveryPanel)
    await flushPromises()
    await wrapper.get('select[aria-label="业务模块交付阶段"]').setValue('rework')
    await flushPromises()
    expect(wrapper.text()).toContain('status denied')

    mockApiFetch
      .mockResolvedValueOnce(
        okJson({
          projects: [sampleProject],
          stages: ['production', 'testing', 'rework', 'acceptance', 'delivered'],
        }),
      )
      .mockRejectedValueOnce(new Error('socket closed'))
    await wrapper.get('.private-mod-center__refresh').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('socket closed')
  })
})
