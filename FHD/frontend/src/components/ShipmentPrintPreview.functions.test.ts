import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import ShipmentPrintPreview from './ShipmentPrintPreview.vue'

function makeShipmentData(overrides: Record<string, unknown> = {}) {
  return {
    customer_name: '测试客户',
    date: '2026-06-25',
    order_number: 'SO-001',
    products: [
      { name: '产品A', spec: '规格1', quantity: 2, unit: 'KG', unit_price: 10.5 },
      { name: '产品B', spec: '规格2', quantity: 3, unit: '件', unit_price: 20 },
    ],
    total_quantity: 5,
    total_amount: 81,
    unit: 'KG',
    notes: '测试备注',
    signatures: {
      approver: '张三',
      accountant: '李四',
      manager: '王五',
      warehouse: '赵六',
    },
    ...overrides,
  }
}

function mountPreview(props: Record<string, unknown> = {}) {
  return mount(ShipmentPrintPreview, {
    props: {
      show: true,
      shipmentData: makeShipmentData(),
      ...props,
    },
  })
}

describe('ShipmentPrintPreview.vue functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('close', () => {
    it('emits close event', async () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      wrapper.vm.close()
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('emits close via close button click', async () => {
      const wrapper = mountPreview()
      await wrapper.find('.modal-close').trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('emits close via footer close button', async () => {
      const wrapper = mountPreview()
      const btns = wrapper.findAll('.modal-footer .btn')
      const closeBtn = btns.find((b) => b.text().includes('关闭'))
      await closeBtn?.trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })

    it('emits close via overlay click', async () => {
      const wrapper = mountPreview()
      await wrapper.find('.modal-overlay').trigger('click')
      expect(wrapper.emitted('close')).toBeTruthy()
    })
  })

  describe('calculateAmount', () => {
    it('calculates amount for normal product', () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      const result = wrapper.vm.calculateAmount({ quantity: 2, unit_price: 10.5 })
      expect(result).toBe('21.00')
    })

    it('returns 0.00 when quantity is 0', () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      const result = wrapper.vm.calculateAmount({ quantity: 0, unit_price: 10.5 })
      expect(result).toBe('0.00')
    })

    it('returns 0.00 when unit_price is 0', () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      const result = wrapper.vm.calculateAmount({ quantity: 5, unit_price: 0 })
      expect(result).toBe('0.00')
    })

    it('returns 0.00 when quantity is undefined', () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      const result = wrapper.vm.calculateAmount({ unit_price: 10 })
      expect(result).toBe('0.00')
    })

    it('returns 0.00 when unit_price is undefined', () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      const result = wrapper.vm.calculateAmount({ quantity: 5 })
      expect(result).toBe('0.00')
    })

    it('returns 0.00 when both are null', () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      const result = wrapper.vm.calculateAmount({ quantity: null, unit_price: null })
      expect(result).toBe('0.00')
    })

    it('handles string numeric values', () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      const result = wrapper.vm.calculateAmount({ quantity: '3', unit_price: '5.5' })
      expect(result).toBe('16.50')
    })

    it('handles negative values', () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      const result = wrapper.vm.calculateAmount({ quantity: -2, unit_price: 10 })
      expect(result).toBe('-20.00')
    })

    it('handles decimal values precisely', () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      const result = wrapper.vm.calculateAmount({ quantity: 3, unit_price: 3.33 })
      expect(result).toBe('9.99')
    })

    it('handles NaN quantity gracefully', () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      const result = wrapper.vm.calculateAmount({ quantity: NaN, unit_price: 10 })
      expect(result).toBe('0.00')
    })
  })

  describe('recalculate', () => {
    it('calculates totals from products', async () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      wrapper.vm.recalculate()
      expect(wrapper.vm.localData.total_quantity).toBe(5)
      expect(wrapper.vm.localData.total_amount).toBe(81)
    })

    it('resets totals to 0 when products empty', async () => {
      const wrapper = mountPreview({
        shipmentData: makeShipmentData({ products: [] }),
      })
      // @ts-expect-error access internal method
      wrapper.vm.recalculate()
      expect(wrapper.vm.localData.total_quantity).toBe(0)
      expect(wrapper.vm.localData.total_amount).toBe(0)
    })

    it('handles products with missing quantity', async () => {
      const wrapper = mountPreview({
        shipmentData: makeShipmentData({
          products: [{ name: 'X', spec: '', unit_price: 10 }],
        }),
      })
      // @ts-expect-error access internal method
      wrapper.vm.recalculate()
      expect(wrapper.vm.localData.total_quantity).toBe(0)
      expect(wrapper.vm.localData.total_amount).toBe(0)
    })

    it('handles products with missing unit_price', async () => {
      const wrapper = mountPreview({
        shipmentData: makeShipmentData({
          products: [{ name: 'X', spec: '', quantity: 5 }],
        }),
      })
      // @ts-expect-error access internal method
      wrapper.vm.recalculate()
      expect(wrapper.vm.localData.total_quantity).toBe(5)
      expect(wrapper.vm.localData.total_amount).toBe(0)
    })

    it('sums multiple products correctly', async () => {
      const wrapper = mountPreview({
        shipmentData: makeShipmentData({
          products: [
            { name: 'A', quantity: 2, unit_price: 10 },
            { name: 'B', quantity: 3, unit_price: 5 },
            { name: 'C', quantity: 1, unit_price: 100 },
          ],
        }),
      })
      // @ts-expect-error access internal method
      wrapper.vm.recalculate()
      expect(wrapper.vm.localData.total_quantity).toBe(6)
      expect(wrapper.vm.localData.total_amount).toBe(135)
    })

    it('handles string numeric values in products', async () => {
      const wrapper = mountPreview({
        shipmentData: makeShipmentData({
          products: [{ name: 'A', quantity: '2', unit_price: '10.5' }],
        }),
      })
      // @ts-expect-error access internal method
      wrapper.vm.recalculate()
      expect(wrapper.vm.localData.total_quantity).toBe(2)
      expect(wrapper.vm.localData.total_amount).toBe(21)
    })
  })

  describe('addProduct', () => {
    it('adds a new product with default values', async () => {
      const wrapper = mountPreview({
        shipmentData: makeShipmentData({ products: [] }),
      })
      const before = wrapper.vm.localData.products.length
      // @ts-expect-error access internal method
      wrapper.vm.addProduct()
      expect(wrapper.vm.localData.products.length).toBe(before + 1)
      const added = wrapper.vm.localData.products[wrapper.vm.localData.products.length - 1]
      expect(added).toMatchObject({
        name: '',
        spec: '',
        quantity: 1,
        unit: 'KG',
        unit_price: 0,
      })
    })

    it('adds product via button click', async () => {
      const wrapper = mountPreview({
        shipmentData: makeShipmentData({ products: [] }),
      })
      const addBtn = wrapper.find('.grid-add .btn')
      await addBtn.trigger('click')
      expect(wrapper.vm.localData.products.length).toBe(1)
    })
  })

  describe('removeProduct', () => {
    it('removes product at given index', async () => {
      const wrapper = mountPreview()
      const before = wrapper.vm.localData.products.length
      // @ts-expect-error access internal method
      wrapper.vm.removeProduct(0)
      expect(wrapper.vm.localData.products.length).toBe(before - 1)
      expect(wrapper.vm.localData.products[0].name).toBe('产品B')
    })

    it('recalculates totals after removal', async () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      wrapper.vm.removeProduct(0)
      expect(wrapper.vm.localData.total_quantity).toBe(3)
      expect(wrapper.vm.localData.total_amount).toBe(60)
    })

    it('removes via trash button click', async () => {
      const wrapper = mountPreview()
      const deleteBtn = wrapper.findAll('.btn-delete')[0]
      await deleteBtn.trigger('click')
      expect(wrapper.vm.localData.products.length).toBe(1)
    })

    it('handles removing the last product', async () => {
      const wrapper = mountPreview({
        shipmentData: makeShipmentData({
          products: [{ name: 'Only', quantity: 1, unit_price: 5 }],
        }),
      })
      // @ts-expect-error access internal method
      wrapper.vm.removeProduct(0)
      expect(wrapper.vm.localData.products.length).toBe(0)
      expect(wrapper.vm.localData.total_quantity).toBe(0)
    })
  })

  describe('handlePrint', () => {
    it('emits print with localData', async () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      await wrapper.vm.handlePrint()
      const emitted = wrapper.emitted('print')
      expect(emitted).toBeTruthy()
      expect(emitted![0][0]).toBe(wrapper.vm.localData)
    })

    it('resets loading to false after print completes', async () => {
      const wrapper = mountPreview()
      expect(wrapper.vm.loading).toBe(false)
      // @ts-expect-error access internal method
      await wrapper.vm.handlePrint()
      expect(wrapper.vm.loading).toBe(false)
    })

    it('emits print via button click', async () => {
      const wrapper = mountPreview()
      const printBtn = wrapper.findAll('.modal-footer .btn').find((b) => b.text().includes('打印'))
      await printBtn?.trigger('click')
      expect(wrapper.emitted('print')).toBeTruthy()
    })
  })

  describe('handleDownload', () => {
    it('emits download with localData', async () => {
      const wrapper = mountPreview()
      // @ts-expect-error access internal method
      wrapper.vm.handleDownload()
      const emitted = wrapper.emitted('download')
      expect(emitted).toBeTruthy()
      expect(emitted![0][0]).toBe(wrapper.vm.localData)
    })

    it('emits download via button click', async () => {
      const wrapper = mountPreview()
      const downloadBtn = wrapper.findAll('.modal-footer .btn').find((b) => b.text().includes('下载'))
      await downloadBtn?.trigger('click')
      expect(wrapper.emitted('download')).toBeTruthy()
    })
  })

  describe('watch.shipmentData', () => {
    it('merges shipmentData into localData', async () => {
      const wrapper = mountPreview({ show: true, shipmentData: null })
      await wrapper.setProps({ shipmentData: makeShipmentData({ customer_name: '新客户' }) })
      expect(wrapper.vm.localData.customer_name).toBe('新客户')
    })

    it('merges signatures deeply', async () => {
      const wrapper = mountPreview({ show: true, shipmentData: null })
      await wrapper.setProps({
        shipmentData: makeShipmentData({
          signatures: { approver: '新核准' },
        }),
      })
      expect(wrapper.vm.localData.signatures.approver).toBe('新核准')
      // 保留默认的其它签名
      expect(wrapper.vm.localData.signatures.accountant).toBe('胡小玲')
    })

    it('recalculates after data merge', async () => {
      const wrapper = mountPreview({ show: true, shipmentData: null })
      await wrapper.setProps({
        shipmentData: makeShipmentData({
          products: [{ name: 'X', quantity: 4, unit_price: 5 }],
        }),
      })
      expect(wrapper.vm.localData.total_quantity).toBe(4)
      expect(wrapper.vm.localData.total_amount).toBe(20)
    })
  })

  describe('watch.localData', () => {
    it('emits update on localData change', async () => {
      const wrapper = mountPreview()
      wrapper.vm.localData.notes = '改了备注'
      await wrapper.vm.$nextTick()
      const emitted = wrapper.emitted('update')
      expect(emitted).toBeTruthy()
    })
  })

  describe('rendering', () => {
    it('does not render when show is false', () => {
      const wrapper = mountPreview({ show: false })
      expect(wrapper.find('.modal-overlay').exists()).toBe(false)
    })

    it('renders product rows', () => {
      const wrapper = mountPreview()
      expect(wrapper.findAll('.product-table tbody tr').length).toBe(2)
    })

    it('renders default signatures', () => {
      const wrapper = mountPreview({ show: true, shipmentData: null })
      expect(wrapper.vm.localData.signatures.approver).toBe('黄种霜')
    })

    it('renders total amount with 2 decimals', () => {
      const wrapper = mountPreview()
      expect(wrapper.text()).toContain('81.00')
    })
  })
})
