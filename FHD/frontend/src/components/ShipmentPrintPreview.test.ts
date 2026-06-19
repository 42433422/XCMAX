import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import ShipmentPrintPreview from '@/components/ShipmentPrintPreview.vue'

function makeShipmentData(overrides = {}) {
  return {
    customer_name: '测试客户',
    date: '2026-06-20',
    order_number: 'SO-001',
    products: [
      { name: '产品A', spec: '10KG', quantity: 5, unit: 'KG', unit_price: 100 },
      { name: '产品B', spec: '20KG', quantity: 3, unit: '桶', unit_price: 200 },
    ],
    total_quantity: 8,
    total_amount: 1100,
    unit: 'KG',
    notes: '测试备注',
    signatures: {
      approver: '审批人',
      accountant: '会计',
      manager: '经理',
      warehouse: '仓库',
    },
    ...overrides,
  }
}

function mountComponent(propsOverrides = {}) {
  return mount(ShipmentPrintPreview, {
    props: {
      show: true,
      shipmentData: makeShipmentData(),
      ...propsOverrides,
    },
  })
}

describe('ShipmentPrintPreview', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('rendering', () => {
    it('renders modal when show is true', () => {
      const wrapper = mountComponent()
      expect(wrapper.find('.shipment-preview').exists()).toBe(true)
    })

    it('does not render when show is false', () => {
      const wrapper = mountComponent({ show: false })
      expect(wrapper.find('.shipment-preview').exists()).toBe(false)
    })

    it('renders header with title', () => {
      const wrapper = mountComponent()
      expect(wrapper.find('.modal-header h3').text()).toContain('发货单预览')
    })

    it('renders close button', () => {
      const wrapper = mountComponent()
      expect(wrapper.find('.modal-close').exists()).toBe(true)
    })

    it('renders print button', () => {
      const wrapper = mountComponent()
      expect(wrapper.find('.btn-primary').text()).toContain('打印')
    })

    it('renders download button', () => {
      const wrapper = mountComponent()
      expect(wrapper.find('.btn-success').text()).toContain('下载')
    })

    it('renders product rows from shipmentData', () => {
      const wrapper = mountComponent()
      const rows = wrapper.findAll('.product-table tbody tr')
      expect(rows).toHaveLength(2)
    })

    it('renders add product button', () => {
      const wrapper = mountComponent()
      expect(wrapper.find('.btn-secondary.btn-sm').text()).toContain('添加产品')
    })
  })

  describe('close()', () => {
    it('emits close event when close button clicked', async () => {
      const wrapper = mountComponent()
      await wrapper.find('.modal-close').trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('emits close event when close button in footer clicked', async () => {
      const wrapper = mountComponent()
      const buttons = wrapper.findAll('button')
      const closeBtn = buttons.find((b) => b.text().includes('关闭'))
      await closeBtn!.trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('emits close when overlay clicked', async () => {
      const wrapper = mountComponent()
      await wrapper.find('.modal-overlay').trigger('click.self')
      expect(wrapper.emitted('close')).toBeTruthy()
    })
  })

  describe('calculateAmount(product)', () => {
    it('calculates amount for valid product', () => {
      const wrapper = mountComponent()
      const result = (wrapper.vm as any).calculateAmount({
        quantity: 5,
        unit_price: 100,
      })
      expect(result).toBe('500.00')
    })

    it('returns 0.00 for zero quantity', () => {
      const wrapper = mountComponent()
      const result = (wrapper.vm as any).calculateAmount({
        quantity: 0,
        unit_price: 100,
      })
      expect(result).toBe('0.00')
    })

    it('returns 0.00 for zero price', () => {
      const wrapper = mountComponent()
      const result = (wrapper.vm as any).calculateAmount({
        quantity: 5,
        unit_price: 0,
      })
      expect(result).toBe('0.00')
    })

    it('handles string numeric values', () => {
      const wrapper = mountComponent()
      const result = (wrapper.vm as any).calculateAmount({
        quantity: '5',
        unit_price: '100',
      })
      expect(result).toBe('500.00')
    })

    it('handles null/undefined values as zero', () => {
      const wrapper = mountComponent()
      const result = (wrapper.vm as any).calculateAmount({
        quantity: null,
        unit_price: undefined,
      })
      expect(result).toBe('0.00')
    })

    it('handles NaN values as zero', () => {
      const wrapper = mountComponent()
      const result = (wrapper.vm as any).calculateAmount({
        quantity: NaN,
        unit_price: NaN,
      })
      expect(result).toBe('0.00')
    })

    it('handles decimal values', () => {
      const wrapper = mountComponent()
      const result = (wrapper.vm as any).calculateAmount({
        quantity: 2.5,
        unit_price: 3.4,
      })
      expect(result).toBe('8.50')
    })
  })

  describe('recalculate()', () => {
    it('calculates total quantity and amount from products', () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      vm.localData.products = [
        { quantity: 5, unit_price: 100 },
        { quantity: 3, unit_price: 200 },
      ]
      vm.recalculate()
      expect(vm.localData.total_quantity).toBe(8)
      expect(vm.localData.total_amount).toBe(1100)
    })

    it('handles empty products list', () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      vm.localData.products = []
      vm.recalculate()
      expect(vm.localData.total_quantity).toBe(0)
      expect(vm.localData.total_amount).toBe(0)
    })

    it('handles products with null/undefined values', () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      vm.localData.products = [
        { quantity: null, unit_price: undefined },
        { quantity: 2, unit_price: 50 },
      ]
      vm.recalculate()
      expect(vm.localData.total_quantity).toBe(2)
      expect(vm.localData.total_amount).toBe(100)
    })

    it('handles products with string numeric values', () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      vm.localData.products = [
        { quantity: '5', unit_price: '100' },
      ]
      vm.recalculate()
      expect(vm.localData.total_quantity).toBe(5)
      expect(vm.localData.total_amount).toBe(500)
    })
  })

  describe('addProduct()', () => {
    it('adds a new empty product to the list', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      const initialCount = vm.localData.products.length
      vm.addProduct()
      expect(vm.localData.products).toHaveLength(initialCount + 1)
    })

    it('new product has default values', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      vm.localData.products = []
      vm.addProduct()
      const newProduct = vm.localData.products[0]
      expect(newProduct).toEqual({
        name: '',
        spec: '',
        quantity: 1,
        unit: 'KG',
        unit_price: 0,
      })
    })

    it('triggers add when button clicked', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      const initialCount = vm.localData.products.length
      await wrapper.find('.btn-secondary.btn-sm').trigger('click')
      expect(vm.localData.products).toHaveLength(initialCount + 1)
    })
  })

  describe('removeProduct(index)', () => {
    it('removes product at given index', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      const initialCount = vm.localData.products.length
      vm.removeProduct(0)
      expect(vm.localData.products).toHaveLength(initialCount - 1)
    })

    it('removes correct product (not just first)', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      vm.localData.products = [
        { name: 'A', quantity: 1, unit_price: 10 },
        { name: 'B', quantity: 2, unit_price: 20 },
        { name: 'C', quantity: 3, unit_price: 30 },
      ]
      vm.removeProduct(1)
      expect(vm.localData.products.map((p: any) => p.name)).toEqual(['A', 'C'])
    })

    it('recalculates totals after removal', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      vm.localData.products = [
        { quantity: 5, unit_price: 100 },
        { quantity: 3, unit_price: 200 },
      ]
      vm.recalculate()
      expect(vm.localData.total_quantity).toBe(8)
      vm.removeProduct(0)
      expect(vm.localData.total_quantity).toBe(3)
      expect(vm.localData.total_amount).toBe(600)
    })

    it('triggers remove when delete button clicked', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      const initialCount = vm.localData.products.length
      const deleteBtn = wrapper.find('.btn-delete')
      await deleteBtn.trigger('click')
      expect(vm.localData.products).toHaveLength(initialCount - 1)
    })
  })

  describe('handlePrint()', () => {
    it('emits print event with localData', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      await vm.handlePrint()
      expect(wrapper.emitted('print')).toBeTruthy()
      expect(wrapper.emitted('print')![0][0]).toEqual(vm.localData)
    })

    it('resets loading to false after print completes', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      await vm.handlePrint()
      // handlePrint has no await inside, so loading is set and immediately reset.
      // Verify it ends up false (no stuck loading state).
      expect(vm.loading).toBe(false)
    })

    it('triggers print when button clicked', async () => {
      const wrapper = mountComponent()
      await wrapper.find('.btn-primary').trigger('click')
      expect(wrapper.emitted('print')).toBeTruthy()
    })
  })

  describe('handleDownload()', () => {
    it('emits download event with localData', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      vm.handleDownload()
      expect(wrapper.emitted('download')).toBeTruthy()
      expect(wrapper.emitted('download')![0][0]).toEqual(vm.localData)
    })

    it('triggers download when button clicked', async () => {
      const wrapper = mountComponent()
      const downloadBtn = wrapper.find('.btn-success')
      await downloadBtn.trigger('click')
      expect(wrapper.emitted('download')).toBeTruthy()
    })
  })

  describe('watchers', () => {
    it('shipmentData watcher merges new data into localData', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      await wrapper.setProps({
        shipmentData: makeShipmentData({
          customer_name: '新客户',
          date: '2026-07-01',
        }),
      })
      expect(vm.localData.customer_name).toBe('新客户')
      expect(vm.localData.date).toBe('2026-07-01')
    })

    it('shipmentData watcher merges signatures partially', async () => {
      // Mount with null so localData keeps component defaults (黄种霜/胡小玲/...)
      const wrapper = mountComponent({ shipmentData: null })
      const vm = wrapper.vm as any
      expect(vm.localData.signatures.accountant).toBe('胡小玲')
      // Now pass shipmentData with only one signature field — watcher should merge
      // with component defaults, preserving other signature roles.
      await wrapper.setProps({
        shipmentData: {
          customer_name: '新客户',
          products: [],
          signatures: { approver: '新审批人' },
        },
      })
      expect(vm.localData.signatures.approver).toBe('新审批人')
      // Other signatures should be preserved from component defaults
      expect(vm.localData.signatures.accountant).toBe('胡小玲')
    })

    it('shipmentData watcher triggers recalculate', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      await wrapper.setProps({
        shipmentData: makeShipmentData({
          products: [
            { quantity: 10, unit_price: 50 },
          ],
        }),
      })
      expect(vm.localData.total_quantity).toBe(10)
      expect(vm.localData.total_amount).toBe(500)
    })

    it('shipmentData watcher handles null gracefully', async () => {
      const wrapper = mountComponent({ shipmentData: null })
      const vm = wrapper.vm as any
      // Should not crash, localData keeps defaults
      expect(vm.localData.customer_name).toBe('')
    })

    it('localData watcher emits update event', async () => {
      const wrapper = mountComponent()
      const vm = wrapper.vm as any
      vm.localData.notes = '新备注'
      await wrapper.vm.$nextTick()
      expect(wrapper.emitted('update')).toBeTruthy()
    })
  })

  describe('default data', () => {
    it('initializes with default signatures', () => {
      const wrapper = mountComponent({ shipmentData: null })
      const vm = wrapper.vm as any
      expect(vm.localData.signatures.approver).toBe('黄种霜')
      expect(vm.localData.signatures.accountant).toBe('胡小玲')
      expect(vm.localData.signatures.manager).toBe('姚胜华')
      expect(vm.localData.signatures.warehouse).toBe('廖振卷')
    })

    it('initializes with empty products', () => {
      const wrapper = mountComponent({ shipmentData: null })
      const vm = wrapper.vm as any
      expect(vm.localData.products).toEqual([])
    })

    it('initializes with zero totals', () => {
      const wrapper = mountComponent({ shipmentData: null })
      const vm = wrapper.vm as any
      expect(vm.localData.total_quantity).toBe(0)
      expect(vm.localData.total_amount).toBe(0)
    })

    it('initializes loading as false', () => {
      const wrapper = mountComponent({ shipmentData: null })
      const vm = wrapper.vm as any
      expect(vm.loading).toBe(false)
    })
  })
})
