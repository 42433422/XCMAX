import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { JSDOM } from 'jsdom'

const indexHtml = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')

function loadStartupDocument() {
  const dom = new JSDOM(indexHtml, { runScripts: 'outside-only' })
  const reload = vi.fn()
  // Execute the actual independent recovery listener against the real DOM.
  // Only browser navigation is substituted; the SPA module never starts here.
  const script = dom.window.document.getElementById('startup-recovery')!.textContent!
  new Function('document', 'location', script)(dom.window.document, { reload })
  return { dom, reload }
}

describe('static frontend startup placeholder', () => {
  it('offers manual recovery even when the SPA entry never loads, without claiming failure or readiness', () => {
    const { dom, reload } = loadStartupDocument()
    try {
      const root = dom.window.document.getElementById('app')!
      expect(root.querySelector('[aria-live="polite"]')).not.toBeNull()
      expect(root.dataset.startupMounted).toBe('false')
      const button = dom.window.document.getElementById('startup-reload')!
      expect(button.hidden).toBe(false)
      expect(root.textContent).not.toContain('超时')
      expect(reload).not.toHaveBeenCalled()
      button.click()
      expect(reload).toHaveBeenCalledTimes(1)
      expect(root.dataset.startupMounted).toBe('false')
    } finally { dom.window.close() }
  })

  it('hands off recovery to the mounted SPA without leaving a static control or delayed navigation', () => {
    const { dom, reload } = loadStartupDocument()
    try {
      const root = dom.window.document.getElementById('app')!
      root.replaceChildren(dom.window.document.createElement('section'))
      root.dataset.startupMounted = 'true'
      expect(dom.window.document.getElementById('startup-reload')).toBeNull()
      root.click()
      expect(reload).not.toHaveBeenCalled()
    } finally { dom.window.close() }
  })
})
