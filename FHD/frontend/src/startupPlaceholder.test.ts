import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'
import { JSDOM } from 'jsdom'

const indexHtml = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')

describe('static frontend startup placeholder', () => {
  let timeoutCallback: (() => void) | undefined
  let timeoutDelay: number | undefined

  beforeEach(() => {
    timeoutCallback = undefined
    timeoutDelay = undefined
  })

  function loadStartupDocument() {
    return new JSDOM(indexHtml, {
      runScripts: 'dangerously',
      beforeParse(window) {
        window.setTimeout = ((callback: TimerHandler, delay?: number) => {
          if (typeof callback === 'function') timeoutCallback = callback as () => void
          timeoutDelay = delay
          return 1
        }) as typeof window.setTimeout
      },
    })
  }

  it('shows a startup status before the SPA mounts and a bounded hint if it remains unmounted', () => {
    const dom = loadStartupDocument()
    const root = dom.window.document.getElementById('app')
    const hint = dom.window.document.getElementById('startup-timeout-hint')

    expect(root?.querySelector('[aria-live="polite"]')).not.toBeNull()
    expect(root?.dataset.startupMounted).toBe('false')
    expect(hint?.hidden).toBe(true)
    expect(timeoutDelay).toBe(20_000)

    timeoutCallback?.()
    expect(hint?.hidden).toBe(false)
    dom.window.close()
  })

  it('does not show the timeout hint after the SPA mount marker is set', () => {
    const dom = loadStartupDocument()
    const root = dom.window.document.getElementById('app')
    const hint = dom.window.document.getElementById('startup-timeout-hint')

    if (root) root.dataset.startupMounted = 'true'
    timeoutCallback?.()

    expect(hint?.hidden).toBe(true)
    dom.window.close()
  })
})
