import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/api/salesContract', () => ({
  salesContractApi: {
    print: vi.fn().mockResolvedValue({ success: true }),
  },
}))
vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn().mockResolvedValue(undefined),
}))

import SalesContractPreview from '@/components/SalesContractPreview.vue'

function mountComponent(propsOverrides = {}) {
  return mount(SalesContractPreview, {
    props: {
      show: true,
      contractData: {
        customer_name: '测试客户',
        contract_date: '2026年06月14日',
        products: [
          {
            model_number: '306B',
            name: 'PU亮光硬化剂',
            spec: '10KG×1',
            unit: '桶',
            quantity: '10 KG',
            unit_price: '39.2',
            amount: '392',
          },
        ],
        total_quantity: 10,
        total_amount: 392,
        return_buckets_expected: 1,
        return_buckets_actual: 0,
      },
      ...propsOverrides,
    },
    global: {
      plugins: [
        createRouter({
          history: createMemoryHistory(),
          routes: [{ path: '/', component: { template: '<div />' } }],
        }),
      ],
      stubs: {
        RouterLink: true,
      },
    },
  })
}

describe('SalesContractPreview', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders when show is true', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.sales-contract-preview').exists()).toBe(true)
  })

  it('does not render when show is false', () => {
    const wrapper = mountComponent({ show: false })
    expect(wrapper.find('.sales-contract-preview').exists()).toBe(false)
  })

  it('renders modal header with title', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.modal-header').text()).toContain('销售合同预览')
  })

  it('renders close button', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.modal-close').exists()).toBe(true)
  })

  it('emits close when close button clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.modal-close').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('emits close when overlay clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.modal-overlay').trigger('click.self')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('renders customer name', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('测试客户')
  })

  it('renders contract date', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('2026年06月14日')
  })

  it('renders product table', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.contract-table').exists()).toBe(true)
  })

  it('renders table headers', () => {
    const wrapper = mountComponent()
    const headers = wrapper.findAll('th')
    expect(headers.length).toBe(7)
    expect(headers.map(h => h.text())).toEqual(['编号', '品名', '规格', '单位', '数量', '单价', '金额'])
  })

  it('renders product rows', () => {
    const wrapper = mountComponent()
    const rows = wrapper.findAll('tbody tr')
    expect(rows.length).toBe(1)
    expect(rows[0].text()).toContain('PU亮光硬化剂')
  })

  it('renders total quantity and amount', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('10 KG')
    expect(wrapper.text()).toContain('392')
  })

  it('renders return buckets info', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('1')
  })

  it('renders signature section', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.contract-signatures').exists()).toBe(true)
  })

  it('renders print button', () => {
    const wrapper = mountComponent()
    const printBtn = wrapper.findAll('.btn-primary')
    expect(printBtn.length).toBeGreaterThanOrEqual(1)
  })

  it('renders close button in footer', () => {
    const wrapper = mountComponent()
    const closeBtn = wrapper.findAll('.btn-secondary')
    expect(closeBtn.length).toBeGreaterThanOrEqual(1)
  })

  it('renders template library link', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('模板库')
  })

  it('calls salesContractApi.print on print button click', async () => {
    const { salesContractApi } = await import('@/api/salesContract')
    const wrapper = mountComponent()
    const printBtn = wrapper.findAll('.btn-primary')[0]
    await printBtn.trigger('click')
    expect(salesContractApi.print).toHaveBeenCalled()
  })

  it('watches contractData and updates previewData', async () => {
    const wrapper = mountComponent()
    await wrapper.setProps({
      contractData: {
        customer_name: '新客户',
        contract_date: '2026年01月01日',
        products: [],
        total_quantity: 0,
        total_amount: 0,
        return_buckets_expected: 0,
        return_buckets_actual: 0,
      },
    })
    expect(wrapper.text()).toContain('新客户')
  })

  it('uses default previewData when no contractData', () => {
    const wrapper = mountComponent({ contractData: null })
    expect(wrapper.text()).toContain('深圳市百木鼎家具有限公司')
  })

  it('goSalesContractTemplateLibrary navigates and closes', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.goSalesContractTemplateLibrary()
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('handles print failure gracefully', async () => {
    const { salesContractApi } = await import('@/api/salesContract')
    ;(salesContractApi.print as any).mockResolvedValueOnce({ success: false, error: '打印失败' })
    const wrapper = mountComponent()
    const printBtn = wrapper.findAll('.btn-primary')[0]
    await printBtn.trigger('click')
    // Should not throw
  })

  it('handles print exception gracefully', async () => {
    const { salesContractApi } = await import('@/api/salesContract')
    ;(salesContractApi.print as any).mockRejectedValueOnce(new Error('Network error'))
    const wrapper = mountComponent()
    const printBtn = wrapper.findAll('.btn-primary')[0]
    await printBtn.trigger('click')
    // Should not throw
  })
})
