import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import InputDialog from './InputDialog.vue'

describe('InputDialog', () => {
  function mountDialog(props = {}) {
    return mount(InputDialog, {
      props: { modelValue: true, ...props },
      global: {
        stubs: {
          Teleport: {
            template: '<div><slot /></div>',
          },
        },
      },
    })
  }

  it('renders dialog when modelValue is true', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('.input-dialog-overlay').exists()).toBe(true)
    expect(wrapper.find('.input-dialog').exists()).toBe(true)
  })

  it('renders nothing when modelValue is false', () => {
    const wrapper = mount(InputDialog, {
      props: { modelValue: false },
      global: {
        stubs: {
          Teleport: {
            template: '<div><slot /></div>',
          },
        },
      },
    })
    expect(wrapper.find('.input-dialog-overlay').exists()).toBe(false)
  })

  it('displays default title', () => {
    const wrapper = mountDialog()
    expect(wrapper.find('h3').text()).toBe('输入')
  })

  it('displays custom title', () => {
    const wrapper = mountDialog({ title: '自定义标题' })
    expect(wrapper.find('h3').text()).toBe('自定义标题')
  })

  it('displays message when provided', () => {
    const wrapper = mountDialog({ message: '请输入内容' })
    expect(wrapper.find('p').text()).toBe('请输入内容')
  })

  it('does not display message paragraph when message is empty', () => {
    const wrapper = mountDialog({ message: '' })
    expect(wrapper.find('p').exists()).toBe(false)
  })

  it('renders input field with placeholder', () => {
    const wrapper = mountDialog({ placeholder: '请输入...' })
    expect(wrapper.find('input').attributes('placeholder')).toBe('请输入...')
  })

  it('renders input with custom type', () => {
    const wrapper = mountDialog({ inputType: 'password' })
    expect(wrapper.find('input').attributes('type')).toBe('password')
  })

  it('renders default confirm text', () => {
    const wrapper = mountDialog()
    const buttons = wrapper.findAll('button')
    const confirmBtn = buttons.find((b) => b.text() === '确定')
    expect(confirmBtn).toBeDefined()
  })

  it('renders custom confirm text', () => {
    const wrapper = mountDialog({ confirmText: '提交' })
    const buttons = wrapper.findAll('button')
    const confirmBtn = buttons.find((b) => b.text() === '提交')
    expect(confirmBtn).toBeDefined()
  })

  it('applies confirmClass to confirm button', () => {
    const wrapper = mountDialog({ confirmClass: 'btn-danger' })
    const buttons = wrapper.findAll('button')
    const confirmBtn = buttons.find((b) => !b.classes().includes('btn-secondary'))
    expect(confirmBtn?.classes()).toContain('btn-danger')
  })

  it('applies maxWidth style', () => {
    const wrapper = mountDialog({ maxWidth: '600px' })
    expect(wrapper.find('.input-dialog').attributes('style')).toContain('600px')
  })

  it('emits confirm with input value on confirm button click', async () => {
    const wrapper = mountDialog()
    await wrapper.find('input').setValue('test input')
    const buttons = wrapper.findAll('button')
    const confirmBtn = buttons.find((b) => !b.classes().includes('btn-secondary'))!
    await confirmBtn.trigger('click')
    expect(wrapper.emitted('confirm')).toBeTruthy()
    expect(wrapper.emitted('confirm')![0]).toEqual(['test input'])
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0]).toEqual([false])
  })

  it('emits cancel on cancel button click', async () => {
    const wrapper = mountDialog()
    const cancelBtn = wrapper.find('.btn-secondary')
    await cancelBtn.trigger('click')
    expect(wrapper.emitted('cancel')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0]).toEqual([false])
  })

  it('emits confirm on Enter key in input', async () => {
    const wrapper = mountDialog()
    await wrapper.find('input').setValue('enter test')
    await wrapper.find('input').trigger('keyup.enter')
    expect(wrapper.emitted('confirm')).toBeTruthy()
    expect(wrapper.emitted('confirm')![0]).toEqual(['enter test'])
  })

  it('emits cancel on overlay click', async () => {
    const wrapper = mountDialog()
    await wrapper.find('.input-dialog-overlay').trigger('click.self')
    expect(wrapper.emitted('cancel')).toBeTruthy()
  })

  it('exposes reset method', () => {
    const wrapper = mountDialog()
    expect(typeof wrapper.vm.reset).toBe('function')
  })

  it('reset clears input value', async () => {
    const wrapper = mountDialog()
    await wrapper.find('input').setValue('some text')
    wrapper.vm.reset()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('input').element.value).toBe('')
  })
})
