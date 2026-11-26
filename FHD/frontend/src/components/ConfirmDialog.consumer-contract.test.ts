import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import ConfirmDialog from './ConfirmDialog.vue'

let wrapper: VueWrapper | undefined
afterEach(() => { wrapper?.unmount(); wrapper = undefined; document.body.replaceChildren() })

function mountConsumer() {
  const visible = ref(false)
  const selected = ref('客户 A')
  const confirmed: string[] = []
  const cancelled: string[] = []
  wrapper = mount(defineComponent({
    components: { ConfirmDialog },
    setup: () => ({
      visible, selected,
      confirm: () => confirmed.push(selected.value),
      cancel: () => cancelled.push(selected.value),
    }),
    template: '<button data-launch @click="visible = true">打开</button><ConfirmDialog v-model="visible" :title="selected" confirm-text="保存" cancel-text="放弃" @confirm="confirm" @cancel="cancel"><span data-consumer-slot>{{ selected }}</span></ConfirmDialog>',
  }), { attachTo: document.body })
  return { wrapper, selected, visible, confirmed, cancelled }
}

function action(text: string) {
  const dialog = document.querySelector('[role="dialog"]')
  expect(dialog).not.toBeNull()
  const button = Array.from(dialog!.querySelectorAll('button')).find(item => item.textContent?.trim() === text)
  expect(button).toBeDefined()
  button!.click()
}

describe('ConfirmDialog public consumer contract', () => {
  it('preserves v-model, slots, reactive props and distinct cancel/confirm events across reuse', async () => {
    const view = mountConsumer()
    await view.wrapper.get('[data-launch]').trigger('click')
    expect(view.visible.value).toBe(true)
    expect(document.querySelector('[data-consumer-slot]')?.textContent).toBe('客户 A')
    action('放弃')
    await flushPromises()
    expect(view.visible.value).toBe(false)
    expect(view.confirmed).toEqual([])
    expect(view.cancelled).toEqual(['客户 A'])
    expect(document.querySelector('[role="dialog"]')).toBeNull()

    view.selected.value = '客户 B'
    await view.wrapper.get('[data-launch]').trigger('click')
    const dialog = document.querySelector('[role="dialog"]')!
    expect(document.getElementById(dialog.getAttribute('aria-labelledby')!)?.textContent).toBe('客户 B')
    expect(dialog.querySelector('[data-consumer-slot]')?.textContent).toBe('客户 B')
    action('保存')
    await flushPromises()
    expect(view.visible.value).toBe(false)
    expect(view.confirmed).toEqual(['客户 B'])
    expect(view.cancelled).toEqual(['客户 A'])
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })
})
