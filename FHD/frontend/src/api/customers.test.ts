import { describe, it, expect, vi, beforeEach } from 'vitest'
import { customersApi } from './customers'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useCustomers } from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/customers/useCustomers'

vi.mock('./core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true, data: [] }),
    post: vi.fn().mockResolvedValue({ success: true, data: {} }),
    put: vi.fn().mockResolvedValue({ success: true, data: {} }),
    delete: vi.fn().mockResolvedValue({ success: true }),
    download: vi.fn().mockResolvedValue(new Response()),
  },
}))

vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiBase: vi.fn().mockReturnValue('/api/erp'),
}))

vi.mock('@/composables/useCoreNavLabel', () => ({ useCoreNavLabel: (key: string) => ({ value: key }) }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn().mockResolvedValue(undefined) }))
vi.mock('@/api/orders', () => ({ default: { getShipmentRecordUnits: vi.fn().mockResolvedValue({ success: true, data: [] }) } }))
vi.mock('@/api/templatePreview', () => ({ default: { listTemplates: vi.fn().mockResolvedValue({ success: true, templates: [] }) } }))

describe('customersApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })
  it('refreshes customer readback when returning from approval', async () => {
    const { api } = await import('./core'), visible = ref(true)
    const { default: orders } = await import('@/api/orders')
    const { default: templates } = await import('@/api/templatePreview')
    const CustomerHarness = defineComponent({ setup: useCustomers, template: '<p v-for="row in customers">{{ row.customer_name }}</p>' })
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [{ id: 1, customer_name: '原客户' }] })
    const wrapper = mount(defineComponent({ components: { CustomerHarness }, setup: () => ({ visible }), template: '<KeepAlive><CustomerHarness v-if="visible" /></KeepAlive>' }))
    await flushPromises(); expect(wrapper.text()).toBe('原客户')
    expect(orders.getShipmentRecordUnits).toHaveBeenCalledTimes(1)
    expect(templates.listTemplates).toHaveBeenCalledTimes(1)
    visible.value = false; await flushPromises()
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [{ id: 2, customer_name: 'AI客户' }] })
    visible.value = true; await flushPromises(); expect(wrapper.text()).toBe('AI客户')
    expect(orders.getShipmentRecordUnits).toHaveBeenCalledTimes(2)
    expect(templates.listTemplates).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it.each(['data', 'customers'])('renders customer records from the %s list envelope', async (key) => {
    const row = { id: 77, customer_name: 'WIN-READBACK', contact_person: '验收员', contact_phone: '13800000001', contact_address: '隔离地址' }
    const { api } = await import('./core')
    vi.mocked(api.get).mockResolvedValueOnce({ success: true, [key]: [row], total: 1 })
    const wrapper = mount(defineComponent({ setup: useCustomers, template: '<div><p v-for="row in customers" :key="row.id">{{ row.customer_name }} {{ row.contact_person }} {{ row.contact_phone }} {{ row.contact_address }}</p><span>{{ totalCustomers }}</span></div>' }))
    await flushPromises()
    expect(wrapper.find('p').text()).toBe('WIN-READBACK 验收员 13800000001 隔离地址')
    expect(wrapper.find('span').text()).toBe('1')
    wrapper.unmount()
  })

  it('loads the customer from the top-search query and keeps its focus id', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/customers', component: { template: '<div />' } }],
    })
    await router.push({ path: '/customers', query: { keyword: '华星', focus: '3' } })
    await router.isReady()
    const { api } = await import('./core')
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [{ id: 3, customer_name: '华星' }], total: 1 })
    const wrapper = mount(defineComponent({
      setup: useCustomers,
      template: '<div><span class="focus">{{ focusId }}</span><p v-for="row in customers" :key="row.id">{{ row.customer_name }}</p></div>',
    }), { global: { plugins: [router] } })
    await flushPromises()
    expect(wrapper.find('.focus').text()).toBe('3')
    expect(wrapper.text()).toContain('华星')
    expect(vi.mocked(api.get).mock.calls.some((call) => call[1]?.keyword === '华星')).toBe(true)
    wrapper.unmount()
  })

  it.each([
    ['list', () => customersApi.getCustomers({ page: 1 }), 'get', ['/api/erp/customers/list', { page: 1 }]],
    ['detail', () => customersApi.getCustomer(42), 'get', ['/api/erp/customers/42']],
    ['create', () => customersApi.createCustomer({ name: 'Test' } as any), 'post', ['/api/erp/customers', { name: 'Test' }]],
    ['update', () => customersApi.updateCustomer(42, { name: 'Updated' } as any), 'put', ['/api/erp/customers/42', { name: 'Updated' }]],
    ['delete', () => customersApi.deleteCustomer(42), 'delete', ['/api/erp/customers/42']],
    ['batch delete', () => customersApi.batchDeleteCustomers([1, 2, 3]), 'post', ['/api/erp/customers/batch-delete', { ids: [1, 2, 3] }]],
  ] as const)('%s uses the customer API contract', async (_name, call, method, args) => {
    await call()
    const { api } = await import('./core')
    expect(api[method]).toHaveBeenCalledWith(...args)
  })

  it.each([undefined, 'tmpl-1'])('exports with optional template %s', async (template) => {
    await customersApi.exportCustomersXlsx(template)
    const { api } = await import('./core')
    expect(api.download).toHaveBeenCalledWith('/api/erp/customers/export', template ? { template_id: template } : {})
  })

  it('importCustomersExcel calls POST /customers/import', async () => {
    const formData = new FormData()
    await customersApi.importCustomersExcel(formData)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/erp/customers/import', formData)
  })
  it('passes canonical customer alias and optimistic version without inventing tenant ownership', async () => {
    await customersApi.updateCustomer(42, {
      customer_name: '合法名称',
      contact_address: '合法地址',
      expected_version: 3,
    })
    const { api } = await import('./core')
    expect(api.put).toHaveBeenCalledWith('/api/erp/customers/42', {
      customer_name: '合法名称',
      contact_address: '合法地址',
      expected_version: 3,
    })
  })

  it('does not report success or replay when create returns an unknown commit outcome', async () => {
    const { api } = await import('./core')
    const { appAlert } = await import('@/utils/appDialog')
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] })
    vi.mocked(api.post).mockResolvedValueOnce({
      success: false, outcome: 'unknown',
      reconciliation_required: true, retryable: false,
      message: '提交结果未知',
    })
    const wrapper = mount(defineComponent({
      setup: useCustomers,
      template: '<input v-model="addForm.customer_name" /><button @click="saveAdd">create</button>',
    }))
    await flushPromises()
    await wrapper.get('input').setValue('客户1')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(vi.mocked(api.post)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(appAlert).mock.calls.map(([message]) => message).join(' ')).toContain('禁止重复提交')
    expect(vi.mocked(appAlert).mock.calls.map(([message]) => message).join(' ')).not.toContain('创建成功')
    wrapper.unmount()
  })

  it('does not show update success for HTTP-200 business failure', async () => {
    const { api } = await import('./core')
    const { appAlert } = await import('@/utils/appDialog')
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] })
    vi.mocked(api.put).mockResolvedValueOnce({ success: false, error_code: 'version_conflict', message: '客户版本已变化' })
    const wrapper = mount(defineComponent({
      setup: useCustomers,
      template: '<button class="edit" @click="openEditModal({id: 42, customer_name: \'合法名称\'})">open</button><button class="save" @click="saveEdit">save</button>',
    }))
    await flushPromises()
    await wrapper.get('.edit').trigger('click')
    await wrapper.get('.save').trigger('click')
    await flushPromises()
    expect(vi.mocked(api.put)).toHaveBeenCalledTimes(1)
    const alerts = vi.mocked(appAlert).mock.calls.map(([message]) => String(message)).join(' ')
    expect(alerts).toContain('客户版本已变化')
    expect(alerts).not.toContain('保存成功')
    wrapper.unmount()
  })

  it('preserves selected customer and does not reload after protected deletion fails', async () => {
    const { api } = await import('./core')
    const { appAlert } = await import('@/utils/appDialog')
    vi.mocked(api.get).mockResolvedValue({ success: true, data: [] })
    vi.mocked(api.delete).mockResolvedValueOnce({ success: false, message: '关联财务或库存，禁止删除' })
    const wrapper = mount(defineComponent({
      setup: useCustomers,
      template: '<button class="select" @click="handleDelete({id: 42})">select</button><button class="delete" @click="confirmDelete">delete</button>',
    }))
    await flushPromises()
    const readsBefore = vi.mocked(api.get).mock.calls.length
    await wrapper.get('.select').trigger('click')
    await wrapper.get('.delete').trigger('click')
    await flushPromises()
    expect(vi.mocked(api.delete)).toHaveBeenCalledTimes(1)
    expect(vi.mocked(api.get).mock.calls.length).toBe(readsBefore)
    expect(vi.mocked(appAlert).mock.calls.map(([message]) => String(message)).join(' ')).toContain('禁止删除')
    wrapper.unmount()
  })

})
