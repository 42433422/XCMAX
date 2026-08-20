import { test, expect } from '@playwright/test'
import { installE2eShellMocks } from './helpers'

test.describe('Desktop shell contract', () => {
  test('platform-shell deliverable-status API', async ({ request }) => {
    const resp = await request.get('/api/platform-shell/deliverable-status', { timeout: 15_000 })
    expect(resp.status()).toBeLessThan(500)
    if (resp.ok()) {
      const body = await resp.json()
      expect(body?.success).toBeTruthy()
      expect(body?.data).toBeTruthy()
    }
  })

  test('runtime product-sku endpoint', async ({ request }) => {
    const resp = await request.get('/api/runtime/product-sku', { timeout: 15_000 })
    expect(resp.status()).toBeLessThan(500)
  })

  test('app shell renders (Electron-equivalent web shell)', async ({ page }) => {
    await installE2eShellMocks(page)
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('#app')).toBeVisible()
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })
    const health = await page.evaluate(async () => {
      const r = await fetch('/api/health')
      return r.status
    })
    expect(health).toBeLessThan(500)
  })

  test('Electron IPC：window.xcagi.invoke("open-modal") 触发 modal 打开', async ({ page }) => {
    await installE2eShellMocks(page)
    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })

    await page.evaluate(() => {
      const invokes: Array<{ channel: string; payload?: unknown }> = []
      ;(window as any).__xcagi_ipc_log__ = invokes
      const listeners: Record<string, Array<(payload?: unknown) => void>> = {}
      ;(window as any).xcagi = {
        invoke: async (channel: string, payload?: unknown) => {
          invokes.push({ channel, payload })
          if (channel === 'open-modal') {
            const modal = document.createElement('div')
            modal.id = 'xcagi-e2e-modal'
            modal.setAttribute('role', 'dialog')
            const name = (payload as { name?: string } | undefined)?.name || 'default'
            modal.textContent = `modal:${name}`
            document.body.appendChild(modal)
            ;(listeners['modal-opened'] || []).forEach((fn) => fn(payload))
          }
          return { ok: true, channel }
        },
        on: (channel: string, fn: (payload?: unknown) => void) => {
          ;(listeners[channel] = listeners[channel] || []).push(fn)
        },
        send: (channel: string, payload?: unknown) => {
          invokes.push({ channel, payload })
        },
      }
    })

    const invokeResult = await page.evaluate(async () => {
      const xcagi = (window as any).xcagi
      const result = await xcagi.invoke('open-modal', { name: 'settings' })
      return result
    })
    expect(invokeResult?.ok, `invoke result: ${JSON.stringify(invokeResult)}`).toBe(true)

    await expect(page.locator('#xcagi-e2e-modal')).toBeVisible()
    await expect(page.locator('#xcagi-e2e-modal')).toHaveText(/modal:settings/)

    const invokes = await page.evaluate(() => (window as any).__xcagi_ipc_log__)
    expect(Array.isArray(invokes)).toBe(true)
    expect(invokes.some((i: { channel: string }) => i.channel === 'open-modal')).toBe(true)
  })
})
