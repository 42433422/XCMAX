import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { createPinia } from 'pinia'
import Modal from './Modal.vue'
import ConfirmDialog from './ConfirmDialog.vue'
import AppDialogHost from './AppDialogHost.vue'
import { appConfirm } from '@/utils/appDialog'

const wrappers: VueWrapper[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = '' })
function key(target: Element, value: string, shiftKey = false) {
  target.dispatchEvent(new KeyboardEvent('keydown', { key: value, shiftKey, bubbles: true, cancelable: true }))
}
async function openHost(component: ReturnType<typeof defineComponent>) {
  const wrapper = mount(component, { attachTo: document.body, global: { plugins: [createPinia()] } })
  wrappers.push(wrapper)
  const launcher = wrapper.get<HTMLButtonElement>('[data-launch]').element
  launcher.focus(); launcher.click()
  await flushPromises()
  return { launcher, wrapper }
}

describe('dialog keyboard boundaries', () => {
  it('starts at cancel, loops both tab directions, and returns to the launcher on Escape', async () => {
    const { launcher } = await openHost(defineComponent({
      components: { ConfirmDialog }, setup: () => ({ open: ref(false) }),
      template: '<button data-launch @click="open = true">删除</button><ConfirmDialog v-model="open" title="确认删除" />',
    }))
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!
    const [cancel, confirm] = dialog.querySelectorAll<HTMLButtonElement>('button')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(document.getElementById(dialog.getAttribute('aria-labelledby')!)?.textContent).toBe('确认删除')
    expect(document.activeElement).toBe(cancel)
    key(cancel, 'Tab', true)
    expect(document.activeElement).toBe(confirm)
    key(confirm, 'Tab')
    expect(document.activeElement).toBe(cancel)
    key(cancel, 'Escape')
    await flushPromises()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(document.activeElement).toBe(launcher)
  })

  it('keeps nested AppDialogHost keyboard actions inside the top dialog and restores each prior focus', async () => {
    const { launcher } = await openHost(defineComponent({
      components: { Modal, AppDialogHost },
      setup: () => ({ open: ref(false), ask: () => appConfirm('继续？') }),
      template: '<button data-launch @click="open = true">打开</button><Modal v-model="open" title="设置"><input aria-label="名称"><button data-ask @click="ask">继续</button></Modal><AppDialogHost />',
    }))
    const base = document.querySelector<HTMLElement>('.modal-content')!
    const ask = base.querySelector<HTMLButtonElement>('[data-ask]')!
    ask.focus(); ask.click()
    await flushPromises()
    const nested = document.querySelector<HTMLElement>('.app-dialog-host-panel')!
    expect(nested.contains(document.activeElement)).toBe(true)
    key(document.activeElement!, 'Escape')
    await flushPromises()
    expect(document.querySelector('.app-dialog-host-panel')).toBeNull()
    expect(document.activeElement).toBe(ask)
    expect(document.querySelector('.modal.visible')).not.toBeNull()
    key(ask, 'Escape')
    await flushPromises()
    expect(document.querySelector('.modal.visible')).toBeNull()
    expect(document.activeElement).toBe(launcher)
  })
})
