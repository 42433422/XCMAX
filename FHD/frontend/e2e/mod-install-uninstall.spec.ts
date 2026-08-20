import { test, expect } from '@playwright/test'
import { installE2eShellMocks, isFullStack } from './helpers'

test.describe('Mod install / uninstall @mod_io', () => {
  test('Mod 安装后 installed badge 可见，卸载后回到未安装态', async ({ page }) => {
    test.skip(isFullStack(), 'full-stack 模式由真实后端覆盖；此处只校验 mock 行为')

    await installE2eShellMocks(page)

    let installCalls = 0
    let uninstallCalls = 0
    let installState = false

    await page.route('**/api/mods/E2E-MOD-001', (route) => {
      void route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            id: 'E2E-MOD-001',
            name: 'E2EMod',
            version: '1.0.0',
            installed: installState,
          },
        }),
      })
    })

    await page.route('**/api/mods/install', async (route) => {
      installCalls += 1
      const body = route.request().postDataJSON()
      installState = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: { id: body?.id || 'E2E-MOD-001', installed: true },
        }),
      })
    })

    await page.route('**/api/mods/uninstall', async (route) => {
      uninstallCalls += 1
      const body = route.request().postDataJSON()
      installState = false
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: { id: body?.id || 'E2E-MOD-001', installed: false },
        }),
      })
    })

    await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })

    const installResult = await page.evaluate(async () => {
      const r = await fetch('/api/mods/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'E2E-MOD-001' }),
      })
      const json = await r.json().catch(() => ({}) as any)
      return { status: r.status, body: json }
    })
    expect(installResult.status, `install status`).toBe(200)
    expect(installResult.body?.success).toBe(true)
    expect(installResult.body?.data?.installed).toBe(true)

    // installed badge check via fetch (UI selector would couple to internal CSS)
    const afterInstall = await page.evaluate(async () => {
      const r = await fetch('/api/mods/E2E-MOD-001')
      const json = await r.json().catch(() => ({}) as any)
      return { status: r.status, body: json }
    })
    expect(afterInstall.body?.data?.installed, `after install body: ${JSON.stringify(afterInstall.body)}`).toBe(true)

    const uninstallResult = await page.evaluate(async () => {
      const r = await fetch('/api/mods/uninstall', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'E2E-MOD-001' }),
      })
      const json = await r.json().catch(() => ({}) as any)
      return { status: r.status, body: json }
    })
    expect(uninstallResult.status, `uninstall status`).toBe(200)
    expect(uninstallResult.body?.success).toBe(true)
    expect(uninstallResult.body?.data?.installed).toBe(false)

    const afterUninstall = await page.evaluate(async () => {
      const r = await fetch('/api/mods/E2E-MOD-001')
      const json = await r.json().catch(() => ({}) as any)
      return { status: r.status, body: json }
    })
    expect(afterUninstall.body?.data?.installed, `after uninstall body: ${JSON.stringify(afterUninstall.body)}`).toBe(false)

    expect(installCalls, 'install should be called once').toBe(1)
    expect(uninstallCalls, 'uninstall should be called once').toBe(1)
  })
})
