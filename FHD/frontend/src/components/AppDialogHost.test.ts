import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AppDialogHost from './AppDialogHost.vue'
import { useAppDialogStore } from '@/stores/appDialog'

function mountComponent(piniaInstance: ReturnType<typeof createPinia>) {
  return mount(AppDialogHost, {
    global: {
      plugins: [piniaInstance],
    },
    attachTo: document.body,
  })
}

describe('AppDialogHost', () => {
  let pinia: ReturnType<typeof createPinia>

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    // Clean up any leftover DOM from previous tests
    document.body.innerHTML = ''
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('does not render overlay when not visible', () => {
    const wrapper = mountComponent(pinia)
    expect(document.querySelector('.app-dialog-host-overlay')).toBeNull()
  })

  it('renders overlay when alert is shown', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    store.showAlert('测试提示')
    await flushPromises()
    expect(document.querySelector('.app-dialog-host-overlay')).toBeTruthy()
  })

  it('renders alert message', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    store.showAlert('这是一条提示')
    await flushPromises()
    const message = document.querySelector('.app-dialog-host-message')
    expect(message?.textContent).toContain('这是一条提示')
  })

  it('renders alert with custom title', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    store.showAlert('消息', { title: '自定义标题' })
    await flushPromises()
    const title = document.querySelector('.app-dialog-host-title')
    expect(title?.textContent).toContain('自定义标题')
  })

  it('renders confirm dialog with two buttons', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    store.showConfirm('确认操作？')
    await flushPromises()
    const buttons = document.querySelectorAll('.app-dialog-host-btn')
    expect(buttons.length).toBe(2)
  })

  it('renders confirm dialog with custom button text', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    store.showConfirm('确认？', { confirmText: '是的', cancelText: '不了' })
    await flushPromises()
    const buttons = document.querySelectorAll('.app-dialog-host-btn')
    expect(buttons[0].textContent).toContain('不了')
    expect(buttons[1].textContent).toContain('是的')
  })

  it('renders prompt dialog with input', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    store.showPrompt('请输入名称')
    await flushPromises()
    const input = document.querySelector('.app-dialog-host-input')
    expect(input).toBeTruthy()
  })

  it('alert resolves when ack button is clicked', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    const promise = store.showAlert('提示')
    await flushPromises()
    const btn = document.querySelector('.app-dialog-host-btn-primary') as HTMLElement
    btn?.click()
    await flushPromises()
    await expect(promise).resolves.toBeUndefined()
  })

  it('confirm resolves true when confirm button is clicked', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    const promise = store.showConfirm('确认？')
    await flushPromises()
    const buttons = document.querySelectorAll('.app-dialog-host-btn')
    buttons[1]?.click()
    await flushPromises()
    await expect(promise).resolves.toBe(true)
  })

  it('confirm resolves false when cancel button is clicked', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    const promise = store.showConfirm('确认？')
    await flushPromises()
    const buttons = document.querySelectorAll('.app-dialog-host-btn')
    buttons[0]?.click()
    await flushPromises()
    await expect(promise).resolves.toBe(false)
  })

  it('prompt resolves with input value when confirm is clicked', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    const promise = store.showPrompt('输入', '默认值')
    await flushPromises()
    // Click confirm
    const buttons = document.querySelectorAll('.app-dialog-host-btn')
    buttons[1]?.click()
    await flushPromises()
    await expect(promise).resolves.toBe('默认值')
  })

  it('prompt resolves null when cancel is clicked', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    const promise = store.showPrompt('输入')
    await flushPromises()
    const buttons = document.querySelectorAll('.app-dialog-host-btn')
    buttons[0]?.click()
    await flushPromises()
    await expect(promise).resolves.toBe(null)
  })

  it('overlay click dismisses alert', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    const promise = store.showAlert('提示')
    await flushPromises()
    const overlay = document.querySelector('.app-dialog-host-overlay') as HTMLElement
    overlay?.click()
    await flushPromises()
    await expect(promise).resolves.toBeUndefined()
  })

  it('overlay click dismisses confirm as false', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    const promise = store.showConfirm('确认？')
    await flushPromises()
    const overlay = document.querySelector('.app-dialog-host-overlay') as HTMLElement
    overlay?.click()
    await flushPromises()
    await expect(promise).resolves.toBe(false)
  })

  it('overlay click dismisses prompt as null', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    const promise = store.showPrompt('输入')
    await flushPromises()
    const overlay = document.querySelector('.app-dialog-host-overlay') as HTMLElement
    overlay?.click()
    await flushPromises()
    await expect(promise).resolves.toBe(null)
  })

  it('confirm dialog shows danger button when danger option is true', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    store.showConfirm('危险操作？', { danger: true })
    await flushPromises()
    const dangerBtn = document.querySelector('.app-dialog-host-btn-danger')
    expect(dangerBtn).toBeTruthy()
  })

  it('dialog has aria-labelledby pointing to title', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    store.showAlert('提示')
    await flushPromises()
    const panel = document.querySelector('.app-dialog-host-panel')
    expect(panel?.getAttribute('aria-labelledby')).toBe('app-dialog-host-title-text')
  })

  it('dialog has role="dialog" and aria-modal', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    store.showAlert('提示')
    await flushPromises()
    const panel = document.querySelector('.app-dialog-host-panel')
    expect(panel?.getAttribute('role')).toBe('dialog')
    expect(panel?.getAttribute('aria-modal')).toBe('true')
  })

  it('queues dialogs when one is already visible', async () => {
    mountComponent(pinia)
    const store = useAppDialogStore()
    // Ensure no dialog is currently visible
    if (store.visible) return // Skip if store is dirty from previous test
    // First show a confirm (which stays open)
    const promise1 = store.showConfirm('排队消息一')
    // Then queue an alert
    const promise2 = store.showAlert('排队消息二')
    await flushPromises()
    // First dialog should be visible
    const message = document.querySelector('.app-dialog-host-message')
    expect(message?.textContent).toContain('排队消息一')
    // Dismiss first (click confirm = true)
    const buttons = document.querySelectorAll('.app-dialog-host-btn')
    buttons[1]?.click()
    await flushPromises()
    // Second should now be visible
    const message2 = document.querySelector('.app-dialog-host-message')
    expect(message2?.textContent).toContain('排队消息二')
    // Dismiss second
    const btn = document.querySelector('.app-dialog-host-btn-primary') as HTMLElement
    btn?.click()
    await flushPromises()
  })
})
