import { expect, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

export async function capture(page: Page, name: string, scale: 'css' | 'device' = 'css') {
  const dir = process.env.VISUAL_CAPTURE_DIR
  if (!dir) throw new Error('VISUAL_CAPTURE_DIR required; do not overwrite product evidence')
  mkdirSync(dir, { recursive: true })
  await page.evaluate(() => document.fonts.ready)
  const options = { animations: 'disabled', caret: 'hide', scale } as const
  // Capture only after a bounded settle window. Persistent movement still fails.
  let stable = false
  for (let attempt = 0; attempt < 12; attempt++) {
    const first = await page.screenshot(options)
    await page.waitForTimeout(120)
    const second = await page.screenshot({ ...options, path: join(dir, name + '.png') })
    if (first.equals(second)) { stable = true; break }
  }
  expect(stable, 'unstable screenshot after bounded settle: ' + name).toBe(true)
}

export async function isolate(page: Page, baseURL: string) {
  const origin = new URL(baseURL).origin
  await page.clock.setFixedTime(new Date('2026-01-15T04:00:00Z'))
  await page.route('**/*', route => new URL(route.request().url()).origin === origin
    ? route.continue() : route.abort('blockedbyclient'))
  await page.routeWebSocket('**/*', socket => socket.close())
  // Also intercept the legacy Vite proxy endpoint used by the workbench.
  await page.route('**/v1/packages**', route => {
    if (new URL(route.request().url()).origin !== origin || route.request().method() !== 'GET') {
      return route.abort('blockedbyclient')
    }
    return route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ items: [], packages: [], total: 0 }) })
  })
}
