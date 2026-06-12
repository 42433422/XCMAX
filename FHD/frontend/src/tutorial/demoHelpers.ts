import type { VirtualCursorApi } from './virtualCursor.types'

/** >1 变慢，<1 变快 */
export const TUTORIAL_DEMO_SPEED = 2.0

export type DemoResult = { ok: boolean; fallbackMsg?: string }

export type TimerGroup = {
  set: (fn: () => void, ms: number) => void
  clear: () => void
}

export function makeTimerGroup(): TimerGroup {
  const ids: number[] = []
  return {
    set(fn: () => void, ms: number) {
      ids.push(window.setTimeout(fn, ms))
    },
    clear() {
      ids.forEach((id) => window.clearTimeout(id))
      ids.length = 0
    },
  }
}

export function getVirtualCursor(): VirtualCursorApi | undefined {
  return window.virtualCursor
}

export function cursorClick(
  el: HTMLElement,
  label?: string,
  duration = 700 * TUTORIAL_DEMO_SPEED,
): void {
  const vc = getVirtualCursor()
  if (vc) {
    vc.click(el, { duration, label })
  }
  window.setTimeout(() => {
    try {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    } catch {
      /* ignore */
    }
    el.click()
  }, duration)
}

export function safeClick(
  selector: string,
  label?: string,
  duration = 700 * TUTORIAL_DEMO_SPEED,
): boolean {
  const el = document.querySelector<HTMLElement>(selector)
  if (!el) return false
  try {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  } catch {
    /* ignore */
  }
  cursorClick(el, label, duration)
  return true
}

export function fireKey(key: string, code: string, meta = false): void {
  const isMac =
    typeof navigator !== 'undefined' &&
    /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent)
  const ev = new KeyboardEvent('keydown', {
    key,
    code,
    metaKey: meta && isMac,
    ctrlKey: meta && !isMac,
    bubbles: true,
  })
  document.dispatchEvent(ev)
}

export function highlightElement(el: HTMLElement, ms = 1500 * TUTORIAL_DEMO_SPEED): void {
  el.style.transition = 'outline .3s, outline-offset .3s'
  el.style.outline = '2px solid #3b82f6'
  el.style.outlineOffset = '4px'
  window.setTimeout(() => {
    el.style.outline = ''
    el.style.outlineOffset = ''
  }, ms)
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}
