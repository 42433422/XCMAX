import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProOrderFloatPanel from './ProOrderFloatPanel.vue'

const sampleOrder = {
  id: 'ORD-001',
  customer: '客户A',
  amount: 199.9,
  date: '2026-06-24',
  status: 'pending',
  statusText: '待处理',
}

describe('ProOrderFloatPanel', () => {
  it('renders the panel container', () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: null } })
    expect(wrapper.find('.pro-order-float-panel').exists()).toBe(true)
  })

  it('renders panel header with title', () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: null } })
    expect(wrapper.find('.panel-title').text()).toBe('订单信息')
  })

  it('renders empty state when order is null', () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: null } })
    expect(wrapper.find('.empty-state').exists()).toBe(true)
    expect(wrapper.find('.empty-text').text()).toBe('暂无订单信息')
  })

  it('does not render empty state when order is provided', () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: sampleOrder } })
    expect(wrapper.find('.empty-state').exists()).toBe(false)
  })

  it('renders order info when order is provided', () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: sampleOrder } })
    expect(wrapper.find('.panel-body').exists()).toBe(true)
    expect(wrapper.find('.order-info').exists()).toBe(true)
  })

  it('renders order id, customer, amount, date, status', () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: sampleOrder } })
    const text = wrapper.find('.order-info').text()
    expect(text).toContain('ORD-001')
    expect(text).toContain('客户A')
    expect(text).toContain('199.9')
    expect(text).toContain('2026-06-24')
    expect(text).toContain('待处理')
  })

  it('renders status with status class', () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: sampleOrder } })
    const status = wrapper.find('.info-value.status')
    expect(status.exists()).toBe(true)
    expect(status.classes()).toContain('pending')
  })

  it('renders amount with price class and ¥ prefix', () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: sampleOrder } })
    const price = wrapper.find('.info-value.price')
    expect(price.exists()).toBe(true)
    expect(price.text()).toBe('¥199.9')
  })

  it('renders download and view action buttons', () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: sampleOrder } })
    expect(wrapper.find('.action-btn.download').exists()).toBe(true)
    expect(wrapper.find('.action-btn.view').exists()).toBe(true)
  })

  it('emits close when close button is clicked', async () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: sampleOrder } })
    await wrapper.find('.close-btn').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('emits download with order id when download button is clicked', async () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: sampleOrder } })
    await wrapper.find('.action-btn.download').trigger('click')
    expect(wrapper.emitted('download')).toBeTruthy()
    expect(wrapper.emitted('download')![0][0]).toBe('ORD-001')
  })

  it('emits view with order object when view button is clicked', async () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: sampleOrder } })
    await wrapper.find('.action-btn.view').trigger('click')
    expect(wrapper.emitted('view')).toBeTruthy()
    expect(wrapper.emitted('view')![0][0]).toEqual(sampleOrder)
  })

  it('does not render download button when order is null', () => {
    const wrapper = mount(ProOrderFloatPanel, { props: { order: null } })
    expect(wrapper.find('.action-btn.download').exists()).toBe(false)
  })

  it('applies task-acquiring class when isTaskAcquiring is true', () => {
    const wrapper = mount(ProOrderFloatPanel, {
      props: { order: null, isTaskAcquiring: true },
    })
    expect(wrapper.find('.pro-order-float-panel').classes()).toContain('task-acquiring')
  })

  it('applies work-mode class when isWorkMode is true', () => {
    const wrapper = mount(ProOrderFloatPanel, {
      props: { order: null, isWorkMode: true },
    })
    expect(wrapper.find('.pro-order-float-panel').classes()).toContain('work-mode')
  })

  it('does not apply work-mode class when isWorkMode is false', () => {
    const wrapper = mount(ProOrderFloatPanel, {
      props: { order: null, isWorkMode: false },
    })
    expect(wrapper.find('.pro-order-float-panel').classes()).not.toContain('work-mode')
  })
})
