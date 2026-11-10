import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { JSDOM } from 'jsdom'

const indexHtml = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')

function loadStartupDocument() {
  return new JSDOM(indexHtml)
}

describe('static frontend startup placeholder', () => {
  it('offers manual recovery even when the SPA entry never loads, without claiming failure or readiness', () => {
    const dom = loadStartupDocument()
    try {
      const root = dom.window.document.getElementById('app')!
      expect(root.querySelector('[aria-live="polite"]')).not.toBeNull()
      expect(root.dataset.startupMounted).toBe('false')
      const button = dom.window.document.getElementById('startup-reload')!
      expect(button.hidden).toBe(false)
      expect(root.textContent).not.toContain('超时')
      const recovery = dom.window.document.getElementById('startup-recovery')?.textContent
      expect(recovery).toContain("document.getElementById('startup-reload')")
      expect(recovery).toContain('location.reload()')
    } finally { dom.window.close() }
  })

  it('hands off recovery to the mounted SPA without leaving a static control or delayed navigation', () => {
    const dom = loadStartupDocument()
    try {
      const root = dom.window.document.getElementById('app')!
      root.replaceChildren(dom.window.document.createElement('section'))
      root.dataset.startupMounted = 'true'
      expect(dom.window.document.getElementById('startup-reload')).toBeNull()
      root.click()
    } finally { dom.window.close() }
  })
})
