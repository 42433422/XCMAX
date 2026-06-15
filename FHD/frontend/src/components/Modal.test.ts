import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import Modal from './Modal.vue'

describe('Modal', () => {
  it('renders when modelValue is true', () => {
    const wrapper = mount(Modal, {
      props: { modelValue: true },
    })
    expect(wrapper.find('.modal').exists()).toBe(true)
    expect(wrapper.find('.modal').classes()).toContain('visible')
  })

  it('does not have visible class when modelValue is false', () => {
    const wrapper = mount(Modal, {
      props: { modelValue: false },
    })
    expect(wrapper.find('.modal').classes()).not.toContain('visible')
  })

  it('displays title when provided', () => {
    const wrapper = mount(Modal, {
      props: { modelValue: true, title: 'Test Modal' },
    })
    expect(wrapper.find('.modal-header').exists()).toBe(true)
    expect(wrapper.text()).toContain('Test Modal')
  })

  it('hides header when no title', () => {
    const wrapper = mount(Modal, {
      props: { modelValue: true, title: '' },
    })
    expect(wrapper.find('.modal-header').exists()).toBe(false)
  })

  it('renders slot content', () => {
    const wrapper = mount(Modal, {
      props: { modelValue: true },
      slots: { default: '<p class="slot-content">Hello</p>' },
    })
    expect(wrapper.find('.slot-content').exists()).toBe(true)
  })

  it('renders footer slot', () => {
    const wrapper = mount(Modal, {
      props: { modelValue: true },
      slots: { footer: '<button class="footer-btn">OK</button>' },
    })
    expect(wrapper.find('.modal-footer').exists()).toBe(true)
    expect(wrapper.find('.footer-btn').exists()).toBe(true)
  })

  it('hides footer when no footer slot', () => {
    const wrapper = mount(Modal, {
      props: { modelValue: true },
    })
    expect(wrapper.find('.modal-footer').exists()).toBe(false)
  })

  it('emits close on overlay click', async () => {
    const wrapper = mount(Modal, {
      props: { modelValue: true },
    })
    await wrapper.find('.modal').trigger('click.self')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('applies maxWidth style when provided', () => {
    const wrapper = mount(Modal, {
      props: { modelValue: true, maxWidth: '600px' },
    })
    const content = wrapper.find('.modal-content')
    expect(content.attributes('style')).toContain('600px')
  })

  it('does not apply maxWidth when empty', () => {
    const wrapper = mount(Modal, {
      props: { modelValue: true, maxWidth: '' },
    })
    const content = wrapper.find('.modal-content')
    // When maxWidth is empty, the computed style returns an empty object
    const style = content.attributes('style') || ''
    expect(style).not.toContain('max-width')
  })
})
