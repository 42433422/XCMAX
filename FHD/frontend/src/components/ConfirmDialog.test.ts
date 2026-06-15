import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ConfirmDialog from './ConfirmDialog.vue'

describe('ConfirmDialog', () => {
  const teleportStub = { template: '<div><slot /></div>' }

  it('renders when modelValue is true', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true },
      global: { stubs: { Teleport: teleportStub } },
    })
    expect(wrapper.find('.confirm-dialog').exists()).toBe(true)
  })

  it('does not render when modelValue is false', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: false },
      global: { stubs: { Teleport: teleportStub } },
    })
    expect(wrapper.find('.confirm-dialog').exists()).toBe(false)
  })

  it('displays title prop', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true, title: 'Delete Item' },
      global: { stubs: { Teleport: teleportStub } },
    })
    expect(wrapper.text()).toContain('Delete Item')
  })

  it('displays message prop', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true, message: 'Are you sure?' },
      global: { stubs: { Teleport: teleportStub } },
    })
    expect(wrapper.text()).toContain('Are you sure?')
  })

  it('emits confirm on confirm button click', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true },
      global: { stubs: { Teleport: teleportStub } },
    })
    await wrapper.findAll('button').at(-1)?.trigger('click')
    expect(wrapper.emitted('confirm')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
  })

  it('emits cancel on cancel button click', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true, showCancel: true },
      global: { stubs: { Teleport: teleportStub } },
    })
    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('cancel')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
  })

  it('hides cancel button when showCancel is false', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true, showCancel: false },
      global: { stubs: { Teleport: teleportStub } },
    })
    expect(wrapper.findAll('button')).toHaveLength(1)
  })

  it('uses custom confirmText', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true, confirmText: 'Yes, delete' },
      global: { stubs: { Teleport: teleportStub } },
    })
    expect(wrapper.text()).toContain('Yes, delete')
  })

  it('uses custom cancelText', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true, showCancel: true, cancelText: 'Nope' },
      global: { stubs: { Teleport: teleportStub } },
    })
    expect(wrapper.text()).toContain('Nope')
  })

  it('applies confirmClass to confirm button', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true, confirmClass: 'btn-danger' },
      global: { stubs: { Teleport: teleportStub } },
    })
    const btn = wrapper.findAll('button').at(-1)
    expect(btn?.classes()).toContain('btn-danger')
  })

  it('emits cancel on overlay click', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true },
      global: { stubs: { Teleport: teleportStub } },
    })
    await wrapper.find('.confirm-dialog-overlay').trigger('click.self')
    expect(wrapper.emitted('cancel')).toBeTruthy()
  })

  it('renders slot content', () => {
    const wrapper = mount(ConfirmDialog, {
      props: { modelValue: true },
      slots: { default: '<p class="custom-slot">Custom content</p>' },
      global: { stubs: { Teleport: teleportStub } },
    })
    expect(wrapper.find('.custom-slot').exists()).toBe(true)
  })
})
