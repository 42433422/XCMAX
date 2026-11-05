import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue'

const scrollLocks = new Set<symbol>()
let bodyOverflow: { property: string; value: string; priority: string }[] = []
/** Keep stacked picker/preview dialogs from releasing each other's scroll lock. */
export function useDialogScrollLock(visible: () => boolean) {
  const token = Symbol('dialog-scroll')
  function release() {
    if (!scrollLocks.delete(token) || scrollLocks.size) return
    bodyOverflow.forEach(({ property }) => document.body.style.removeProperty(property))
    bodyOverflow.forEach(({ property, value, priority }) => { if (value) document.body.style.setProperty(property, value, priority) })
  }
  watch(visible, show => {
    if (!show) { release(); return }
    if (!scrollLocks.size) bodyOverflow = ['overflow', 'overflow-x', 'overflow-y'].map(property => ({ property, value: document.body.style.getPropertyValue(property), priority: document.body.style.getPropertyPriority(property) }))
    scrollLocks.add(token)
    document.body.style.setProperty('overflow', 'hidden')
  }, { immediate: true, flush: 'sync' })
  onBeforeUnmount(release)
}

const dialogs: HTMLElement[] = []
const selector = 'button, [href], input, select, textarea, [tabindex], [contenteditable="true"]'

/** Share one keyboard boundary so a confirmation can safely open above another dialog. */
export function useDialogFocus(panel: Ref<HTMLElement | null>, visible: () => boolean, close: () => void) {
  let opened: HTMLElement | null = null
  let previous: HTMLElement | null = null
  let epoch = 0
  const isTop = () => opened !== null && dialogs[dialogs.length - 1] === opened
  function focusable() {
    return [...(opened?.querySelectorAll<HTMLElement>(selector) || [])].filter(el => {
      if (el.tabIndex < 0 || el.matches(':disabled') || el.closest('[hidden], [inert], [aria-hidden="true"]')) return false
      for (let parent: HTMLElement | null = el; parent && parent !== opened; parent = parent.parentElement) {
        const style = getComputedStyle(parent)
        if (style.display === 'none' || style.visibility === 'hidden') return false
      }
      return true
    })
  }
  function focusFirst() {
    const items = focusable()
    const first = items.find(el => el.hasAttribute('data-dialog-initial-focus') || el.hasAttribute('autofocus')) || items[0] || opened
    first?.focus({ preventScroll: true })
  }
  function keydown(event: KeyboardEvent) {
    if (!isTop()) return
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      close()
    } else if (event.key === 'Tab') {
      const items = focusable()
      const index = items.indexOf(document.activeElement as HTMLElement)
      if (!items.length || index < 0 || (!event.shiftKey && index === items.length - 1) || (event.shiftKey && index === 0)) {
        event.preventDefault()
        ;(event.shiftKey ? items[items.length - 1] : items[0])?.focus({ preventScroll: true })
        if (!items.length) opened?.focus({ preventScroll: true })
      }
    }
  }
  function focusin(event: FocusEvent) {
    if (isTop() && !opened?.contains(event.target as Node)) focusFirst()
  }
  function release() {
    const restore = isTop()
    if (opened) dialogs.splice(dialogs.indexOf(opened), 1)
    opened = null
    document.removeEventListener('keydown', keydown, true)
    document.removeEventListener('focusin', focusin)
    if (restore && previous?.isConnected) previous.focus({ preventScroll: true })
    previous = null
  }
  watch(visible, async show => {
    const current = ++epoch
    if (!show) { release(); return }
    previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    if (current !== epoch || !visible() || !panel.value) return
    opened = panel.value
    dialogs.push(opened)
    document.addEventListener('keydown', keydown, true)
    document.addEventListener('focusin', focusin)
    focusFirst()
  }, { immediate: true })
  onBeforeUnmount(() => { epoch++; release() })
}
