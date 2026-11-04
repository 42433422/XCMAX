import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, reactive, ref } from 'vue'
import { useSidebarMenuReorder } from './useSidebarMenuReorder'

let scope, ui, layout, items, root
function pointer(type, values = {}) {
  const event = new Event(type, { cancelable: true })
  Object.assign(event, { pointerId: 1, button: 2, clientX: 50, clientY: 20, ...values })
  return event
}
function bounds(top, height) { return { left: 0, right: 100, top, bottom: top + height, height } }
beforeEach(() => {
  vi.useFakeTimers()
  scope = effectScope()
  layout = reactive({ reorderEnabled: true, resetOrder: vi.fn() })
  items = ref(['products', 'customers', 'orders'].map((key) => ({ key, label: key })))
  root = document.createElement('nav')
  root.getBoundingClientRect = () => bounds(0, 120)
  items.value.forEach(({ key }, index) => {
    const button = document.createElement('button')
    button.className = 'menu-item'
    button.dataset.view = key
    button.getBoundingClientRect = () => bounds(index * 40, 40)
    root.appendChild(button)
  })
  ui = scope.run(() => useSidebarMenuReorder({ sidebarLayoutStore: layout, menuItems: items, sidebarMenuRef: ref(root) }))
})
afterEach(() => { ui.clearReorderGesture(); scope.stop(); vi.useRealTimers() })
async function begin(key = 'products') {
  ui.onReorderPointerDown(pointer('pointerdown'), key)
  await vi.advanceTimersByTimeAsync(1000)
  await nextTick()
}
async function move(values = {}) {
  window.dispatchEvent(pointer('pointermove', { clientY: 100, ...values }))
  await vi.advanceTimersByTimeAsync(32)
}

describe('Sidebar menu pointer reorder', () => {
  it.each(['disabled', 'left-button'])('does not start a reorder gesture for %s input', (input) => {
    if (input === 'disabled') layout.reorderEnabled = false
    const event = pointer('pointerdown', { button: input === 'left-button' ? 0 : 2 })
    ui.onReorderPointerDown(event, 'products')
    expect(event.defaultPrevented).toBe(false)
    expect(ui.pressingKey.value).toBe('')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('requires the complete hold duration and cancels a short press without persisting', async () => {
    const event = pointer('pointerdown')
    ui.onReorderPointerDown(event, 'products')
    expect(event.defaultPrevented).toBe(true)
    expect(ui.pressingKey.value).toBe('products')
    await vi.advanceTimersByTimeAsync(999)
    expect(ui.draggingKey.value).toBe('')
    window.dispatchEvent(pointer('pointerup'))
    await vi.advanceTimersByTimeAsync(1000)
    expect(ui.draggingKey.value).toBe('')
    expect(layout.resetOrder).not.toHaveBeenCalled()
  })

  it('previews the nearest destination and persists exactly that order once on release', async () => {
    await begin()
    expect(ui.draggingKey.value).toBe('products')
    await move()
    expect(ui.dragOverKey.value).toBe('orders')
    expect(ui.displayMenuItems.value.map((item) => item.key)).toEqual(['customers', 'orders', 'products'])
    window.dispatchEvent(pointer('pointerup'))
    window.dispatchEvent(pointer('pointerup'))
    expect(layout.resetOrder).toHaveBeenCalledExactlyOnceWith(['customers', 'orders', 'products'])
    expect(ui.draggingKey.value).toBe('')
    expect(ui.dragOverKey.value).toBe('')
  })

  it('ignores a different pointer and movements outside the menu', async () => {
    await begin()
    await move({ pointerId: 2 })
    window.dispatchEvent(pointer('pointerup', { pointerId: 2 }))
    expect(ui.draggingKey.value).toBe('products')
    await move({ clientX: 101 })
    await move({ clientY: -1 })
    expect(ui.dragOverKey.value).toBe('products')
    window.dispatchEvent(pointer('pointerup'))
    expect(layout.resetOrder).not.toHaveBeenCalled()
  })

  it('uses the latest coalesced position and cancels pending frame work on pointer cancellation', async () => {
    await begin()
    window.dispatchEvent(pointer('pointermove', { clientY: 60 }))
    window.dispatchEvent(pointer('pointermove', { clientY: 100 }))
    await vi.advanceTimersByTimeAsync(32)
    expect(ui.dragOverKey.value).toBe('orders')
    window.dispatchEvent(pointer('pointermove', { clientY: 60 }))
    window.dispatchEvent(pointer('pointercancel'))
    await vi.advanceTimersByTimeAsync(32)
    expect(ui.draggingKey.value).toBe('')
    expect(layout.resetOrder).not.toHaveBeenCalled()
  })

  it('does not save a preview if reorder permission is revoked before release', async () => {
    await begin()
    await move()
    layout.reorderEnabled = false
    window.dispatchEvent(pointer('pointerup'))
    expect(layout.resetOrder).not.toHaveBeenCalled()
  })

  it('keeps mandatory top entries pinned when previewing and saving an older menu order', async () => {
    items.value.push({ key: 'chat', label: 'chat' })
    await begin()
    await move()
    expect(ui.displayMenuItems.value[0].key).toBe('chat')
    window.dispatchEvent(pointer('pointerup'))
    expect(layout.resetOrder).toHaveBeenCalledExactlyOnceWith(['chat', 'customers', 'orders', 'products'])
  })

  it('handles a menu removed during the gesture without saving an invented destination', async () => {
    const menuRef = ref(null)
    ui.clearReorderGesture()
    ui = scope.run(() => useSidebarMenuReorder({ sidebarLayoutStore: layout, menuItems: items, sidebarMenuRef: menuRef }))
    await begin()
    await move()
    expect(ui.dragOverKey.value).toBe('products')
    window.dispatchEvent(pointer('pointerup'))
    expect(layout.resetOrder).not.toHaveBeenCalled()
  })
})
