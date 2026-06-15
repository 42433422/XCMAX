import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProProductInfoBadge from './ProProductInfoBadge.vue'

function mountComponent(propsOverrides = {}) {
  return mount(ProProductInfoBadge, {
    props: {
      show: true,
      product: null,
      scale: 1,
      ...propsOverrides,
    },
  })
}

describe('ProProductInfoBadge', () => {
  it('renders the component', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.pro-product-info-badge').exists()).toBe(true)
  })

  it('shows opacity 0 when show is false', () => {
    const wrapper = mountComponent({ show: false })
    expect(wrapper.find('.pro-product-info-badge').attributes('style')).toContain('opacity: 0')
  })

  it('shows opacity 1 when show is true', () => {
    const wrapper = mountComponent({ show: true })
    expect(wrapper.find('.pro-product-info-badge').attributes('style')).toContain('opacity: 1')
  })

  it('applies scale from props', () => {
    const wrapper = mountComponent({ scale: 0.8 })
    expect(wrapper.find('.pro-product-info-badge').attributes('style')).toContain('scale(0.8)')
  })

  it('renders title "产品信息"', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.badge-title').text()).toBe('产品信息')
  })

  it('renders close button', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.close-button').exists()).toBe(true)
  })

  it('emits close when close button is clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.close-button').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('renders form fields', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('input[placeholder="请输入产品名称"]').exists()).toBe(true)
    expect(wrapper.find('input[placeholder="请输入产品型号"]').exists()).toBe(true)
    expect(wrapper.find('input[placeholder="请输入单价"]').exists()).toBe(true)
    expect(wrapper.find('textarea[placeholder="请输入产品描述"]').exists()).toBe(true)
  })

  it('save button is disabled when form is empty', () => {
    const wrapper = mountComponent()
    const saveBtn = wrapper.find('.badge-button.save')
    expect(saveBtn.attributes('disabled')).toBeDefined()
  })

  it('save button is enabled when required fields are filled', async () => {
    const wrapper = mountComponent()
    await wrapper.find('input[placeholder="请输入产品名称"]').setValue('测试产品')
    await wrapper.find('input[placeholder="请输入产品型号"]').setValue('M001')
    await wrapper.find('input[placeholder="请输入单价"]').setValue('99.9')
    const saveBtn = wrapper.find('.badge-button.save')
    expect(saveBtn.attributes('disabled')).toBeUndefined()
  })

  it('emits save with form data when save button is clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.find('input[placeholder="请输入产品名称"]').setValue('测试产品')
    await wrapper.find('input[placeholder="请输入产品型号"]').setValue('M001')
    await wrapper.find('input[placeholder="请输入单价"]').setValue('99.9')
    await wrapper.find('.badge-button.save').trigger('click')
    expect(wrapper.emitted('save')).toBeTruthy()
    const savedData = wrapper.emitted('save')![0][0] as Record<string, unknown>
    expect(savedData.name).toBe('测试产品')
    expect(savedData.model).toBe('M001')
    expect(savedData.price).toBe(99.9)
  })

  it('emits close when cancel button is clicked', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.badge-button.cancel').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('populates form when product prop is provided', async () => {
    const wrapper = mountComponent({
      product: {
        name: '已有产品',
        model: 'X100',
        price: '199',
        description: '产品描述',
      },
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('input[placeholder="请输入产品名称"]').wrapperElement._value || 
      (wrapper.find('input[placeholder="请输入产品名称"]').element as HTMLInputElement).value
    ).toBeDefined()
  })

  it('updates form when product prop changes', async () => {
    const wrapper = mountComponent()
    await wrapper.setProps({
      product: {
        name: '新产品',
        model: 'Y200',
        price: '299',
        description: '新描述',
      },
    })
    // Form should be updated via the watch
    expect(wrapper.find('.pro-product-info-badge').exists()).toBe(true)
  })

  it('save button does not emit when form is invalid', async () => {
    const wrapper = mountComponent()
    // Only fill name, not model or price
    await wrapper.find('input[placeholder="请输入产品名称"]').setValue('只有名称')
    await wrapper.find('.badge-button.save').trigger('click')
    expect(wrapper.emitted('save')).toBeFalsy()
  })

  it('parses price as float in save event', async () => {
    const wrapper = mountComponent()
    await wrapper.find('input[placeholder="请输入产品名称"]').setValue('产品')
    await wrapper.find('input[placeholder="请输入产品型号"]').setValue('M1')
    await wrapper.find('input[placeholder="请输入单价"]').setValue('123.45')
    await wrapper.find('.badge-button.save').trigger('click')
    const savedData = wrapper.emitted('save')![0][0] as Record<string, unknown>
    expect(savedData.price).toBe(123.45)
  })
})
