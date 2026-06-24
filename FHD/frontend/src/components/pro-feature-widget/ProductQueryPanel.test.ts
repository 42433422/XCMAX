import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ProductQueryPanel from '@/components/pro-feature-widget/ProductQueryPanel.vue'

const sampleProducts = [
  { id: 1, name: '产品A', model: 'M-A', price: 100, companyId: 1, companyName: '公司甲', description: '描述A' },
  { id: 2, name: '产品B', model: 'M-B', price: 200, companyId: 2, companyName: '公司乙', description: '描述B' },
  { id: 3, name: 'Product C', model: 'M-C', price: 300, companyId: 1, companyName: '公司甲', description: '' },
]

const sampleCompanies = [
  { id: 1, name: '公司甲' },
  { id: 2, name: '公司乙' },
]

function mountComponent(propsOverrides = {}) {
  return mount(ProductQueryPanel, {
    props: {
      products: sampleProducts,
      companies: sampleCompanies,
      ...propsOverrides,
    },
  })
}

describe('ProductQueryPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders panel title', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.panel-title').text()).toBe('产品查询')
  })

  it('renders export button', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.action-btn.export').text()).toBe('导出Excel')
  })

  it('renders search input with placeholder', () => {
    const wrapper = mountComponent()
    const input = wrapper.find('.search-input')
    expect(input.attributes('placeholder')).toBe('搜索产品...')
  })

  it('renders "全部" filter button as active by default', () => {
    const wrapper = mountComponent()
    const allBtn = wrapper.findAll('.filter-btn')[0]
    expect(allBtn.text()).toBe('全部')
    expect(allBtn.classes()).toContain('active')
  })

  it('renders one filter button per company', () => {
    const wrapper = mountComponent()
    const btns = wrapper.findAll('.filter-btn')
    // 1 "全部" + 2 companies
    expect(btns).toHaveLength(3)
    expect(btns[1].text()).toBe('公司甲')
    expect(btns[2].text()).toBe('公司乙')
  })

  it('renders all products by default', () => {
    const wrapper = mountComponent()
    expect(wrapper.findAll('.product-card')).toHaveLength(3)
  })

  it('filters products by company when company button clicked', async () => {
    const wrapper = mountComponent()
    const companyBtn = wrapper.findAll('.filter-btn')[1] // 公司甲
    await companyBtn.trigger('click')
    // 公司甲 has products 1 and 3
    expect(wrapper.findAll('.product-card')).toHaveLength(2)
    // 全部 button no longer active
    expect(wrapper.findAll('.filter-btn')[0].classes()).not.toContain('active')
    expect(companyBtn.classes()).toContain('active')
  })

  it('filters products by search query (name)', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.search-input').setValue('产品A')
    expect(wrapper.findAll('.product-card')).toHaveLength(1)
    expect(wrapper.find('.product-name').text()).toBe('产品A')
  })

  it('filters products by search query (model)', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.search-input').setValue('M-B')
    expect(wrapper.findAll('.product-card')).toHaveLength(1)
  })

  it('filters products by search query (companyName)', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.search-input').setValue('公司乙')
    expect(wrapper.findAll('.product-card')).toHaveLength(1)
  })

  it('search query is case-insensitive', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.search-input').setValue('product c')
    expect(wrapper.findAll('.product-card')).toHaveLength(1)
  })

  it('shows empty state when no products match', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.search-input').setValue('不存在的产品')
    expect(wrapper.find('.empty-state').exists()).toBe(true)
    expect(wrapper.find('.empty-text').text()).toBe('暂无产品数据')
  })

  it('shows empty state when products prop is empty', () => {
    const wrapper = mountComponent({ products: [] })
    expect(wrapper.find('.empty-state').exists()).toBe(true)
  })

  it('renders product card with name, model, price, and company', () => {
    const wrapper = mountComponent()
    const card = wrapper.findAll('.product-card')[0]
    expect(card.find('.product-name').text()).toBe('产品A')
    expect(card.find('.product-model').text()).toBe('M-A')
    expect(card.find('.product-price').text()).toBe('¥100')
    expect(card.find('.product-company').text()).toBe('公司甲')
  })

  it('emits select and opens modal when product card clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.findAll('.product-card')[0].trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')![0]).toEqual([sampleProducts[0]])
    // Modal should appear
    expect(wrapper.find('.product-detail-modal').exists()).toBe(true)
  })

  it('modal shows product details', async () => {
    const wrapper = mountComponent()
    await wrapper.findAll('.product-card')[0].trigger('click')
    const modal = wrapper.find('.product-detail-modal')
    expect(modal.find('h4').text()).toBe('产品详情')
    expect(modal.find('.detail-value').text()).toBe('产品A')
  })

  it('modal shows "暂无描述" when product has no description', async () => {
    const wrapper = mountComponent()
    // Product C (index 2) has empty description
    await wrapper.findAll('.product-card')[2].trigger('click')
    const values = wrapper.findAll('.detail-value')
    expect(values[values.length - 1].text()).toBe('暂无描述')
  })

  it('closes modal when close button clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.findAll('.product-card')[0].trigger('click')
    expect(wrapper.find('.product-detail-modal').exists()).toBe(true)
    await wrapper.find('.close-btn').trigger('click')
    expect(wrapper.find('.product-detail-modal').exists()).toBe(false)
  })

  it('closes modal when "关闭" button clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.findAll('.product-card')[0].trigger('click')
    await wrapper.find('.btn.close').trigger('click')
    expect(wrapper.find('.product-detail-modal').exists()).toBe(false)
  })

  it('emits edit with selected product when edit button clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.findAll('.product-card')[0].trigger('click')
    await wrapper.find('.btn.edit').trigger('click')
    expect(wrapper.emitted('edit')).toBeTruthy()
    expect(wrapper.emitted('edit')![0]).toEqual([sampleProducts[0]])
  })

  it('emits export with selected company id', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.action-btn.export').trigger('click')
    // Default selectedCompanyId is null
    expect(wrapper.emitted('export')).toBeTruthy()
    expect(wrapper.emitted('export')![0]).toEqual([null])
  })

  it('emits export with company id after filter', async () => {
    const wrapper = mountComponent()
    await wrapper.findAll('.filter-btn')[1].trigger('click') // 公司甲
    await wrapper.find('.action-btn.export').trigger('click')
    expect(wrapper.emitted('export')![0]).toEqual([1])
  })

  it('resets to all products when "全部" clicked after filter', async () => {
    const wrapper = mountComponent()
    await wrapper.findAll('.filter-btn')[1].trigger('click')
    expect(wrapper.findAll('.product-card')).toHaveLength(2)
    await wrapper.findAll('.filter-btn')[0].trigger('click')
    expect(wrapper.findAll('.product-card')).toHaveLength(3)
  })

  it('combines company filter and search query', async () => {
    const wrapper = mountComponent()
    // Select 公司甲 (products 1 and 3)
    await wrapper.findAll('.filter-btn')[1].trigger('click')
    expect(wrapper.findAll('.product-card')).toHaveLength(2)
    // Search for "产品A" within 公司甲
    await wrapper.find('.search-input').setValue('产品A')
    expect(wrapper.findAll('.product-card')).toHaveLength(1)
  })

  it('uses default empty arrays for products and companies', () => {
    const wrapper = mount(ProductQueryPanel)
    expect(wrapper.findAll('.product-card')).toHaveLength(0)
    expect(wrapper.findAll('.filter-btn')).toHaveLength(1) // just "全部"
  })
})
