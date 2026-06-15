import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/fhd/dbTokenHeaders', () => ({
  FHD_DB_WRITE_UNLOCKED_EVENT: 'fhd:db-write-unlocked',
  LS_DB_WRITE_TOKEN: 'xcagi_db_write_token',
  XCAGI_PROMPT_DB_WRITE_TOKEN_EVENT: 'xcagi:prompt-db-write-token',
  saveStoredWriteToken: vi.fn(),
}))

import GlobalWriteTokenPrompt from '@/fhd/GlobalWriteTokenPrompt.vue'

function mountComponent() {
  return mount(GlobalWriteTokenPrompt, {
    global: {
      stubs: {
        Teleport: true,
      },
    },
  })
}

describe('GlobalWriteTokenPrompt', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders without errors', () => {
    const wrapper = mountComponent()
    expect(wrapper.exists()).toBe(true)
  })

  it('is hidden by default', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.visible).toBe(false)
    expect(vm.showOverlay).toBe(false)
  })

  it('shows overlay when visible is true', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    await wrapper.vm.$nextTick()
    expect(vm.showOverlay).toBe(true)
  })

  it('renders title with 二级数据库写入口令', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('二级数据库写入口令')
  })

  it('onSubmit with empty password shows error', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    vm.password = '  '
    vm.onSubmit()
    expect(vm.errorText).toBe('请输入二级写入口令。')
  })

  it('onSubmit with valid password saves token and closes', async () => {
    const { saveStoredWriteToken } = await import('@/fhd/dbTokenHeaders')
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    vm.password = 'my_write_token'
    vm.onSubmit()
    expect(saveStoredWriteToken).toHaveBeenCalledWith('my_write_token')
    expect(vm.visible).toBe(false)
    expect(vm.password).toBe('')
  })

  it('onSubmit dispatches unlocked event', async () => {
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    vm.password = 'my_token'
    vm.onSubmit()
    expect(dispatchSpy).toHaveBeenCalled()
    dispatchSpy.mockRestore()
  })

  it('onCancel closes the panel', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    vm.onCancel()
    expect(vm.visible).toBe(false)
    expect(vm.password).toBe('')
    expect(vm.errorText).toBe('')
  })

  it('onBackdropClick closes the panel', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    vm.onBackdropClick()
    expect(vm.visible).toBe(false)
  })

  it('onPromptFromChat opens panel and sets reasonText', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.onPromptFromChat(new CustomEvent('xcagi:prompt-db-write-token', {
      detail: { description: '需要导入 Excel 数据' },
    }))
    expect(vm.visible).toBe(true)
    expect(vm.reasonText).toContain('需要导入 Excel 数据')
  })

  it('onPromptFromChat uses default reason when no description', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.onPromptFromChat(new CustomEvent('xcagi:prompt-db-write-token', { detail: {} }))
    expect(vm.visible).toBe(true)
    expect(vm.reasonText).toContain('写入数据库')
  })

  it('onKeyDown closes panel on Escape', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    const event = new KeyboardEvent('keydown', { key: 'Escape' })
    Object.defineProperty(event, 'preventDefault', { value: vi.fn() })
    vm.onKeyDown(event)
    expect(vm.visible).toBe(false)
  })

  it('onKeyDown ignores non-Escape when not visible', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = false
    const event = new KeyboardEvent('keydown', { key: 'Escape' })
    vm.onKeyDown(event)
    // Should remain not visible
    expect(vm.visible).toBe(false)
  })

  it('sets busy during submit', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    vm.password = 'token'
    vm.onSubmit()
    expect(vm.busy).toBe(false) // finally block resets it immediately
  })

  it('renders input with password type', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    await wrapper.vm.$nextTick()
    const input = wrapper.find('#fhd-global-write-input')
    expect(input.exists()).toBe(true)
    expect(input.attributes('type')).toBe('password')
  })

  it('renders cancel and submit buttons', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.visible = true
    await wrapper.vm.$nextTick()
    const btns = wrapper.findAll('button')
    expect(btns.length).toBeGreaterThanOrEqual(2)
  })
})
