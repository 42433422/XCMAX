import { expect, test, type Page } from '@playwright/test'
import fs from 'node:fs'
import nodePath from 'node:path'

const ADMIN_PAGES = [
  '/xcmax-admin',
  '/delivery-center',
  '/founder-autonomy',
  '/automation-policy',
  '/duty-time-architecture',
  '/duty-roster-graph',
  '/server-functions',
  '/autonomy-approval-hub',
  '/employee-autonomy',
  '/ai-ecosystem',
  '/persy/knowledge',
  '/im',
  '/workflow-employee-space',
  '/entitlements',
  '/data-sources',
  '/tools',
  '/settings',
] as const

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'tablet', width: 1024, height: 768 },
  { name: 'mobile', width: 390, height: 844 },
] as const

async function installAdminDisplayMocks(page: Page) {
  await page.route('**/xcmax-dashboard/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/html; charset=utf-8',
      body: '<!doctype html><html><body><main id="s-loops">XCMAX dashboard fixture</main></body></html>',
    })
  })
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) {
      await route.continue()
      return
    }
    if (path.endsWith('/api/auth/session/validate')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, valid: true, data: { valid: true, username: 'layout-admin' } }),
      })
      return
    }
    if (path.endsWith('/api/auth/me')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            account_kind: 'admin',
            market_is_admin: true,
            market_is_enterprise: false,
            username: 'layout-admin',
            user: { id: 1, username: 'layout-admin', role: 'admin' },
            permissions: ['admin'],
          },
        }),
      })
      return
    }
    if (path.endsWith('/api/runtime/product-sku')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: { sku: 'generic' } }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: [], items: [], rows: [] }),
    })
  })
}

test.describe('admin page display regression', () => {
  test.setTimeout(180_000)

  for (const viewport of VIEWPORTS) {
    test(`${viewport.name}: every operator page fills its shell without viewport overflow`, async ({ page }) => {
      await installAdminDisplayMocks(page)
      await page.setViewportSize(viewport)
      const pageErrors: string[] = []
      page.on('pageerror', (error) => pageErrors.push(error.message))
      const evidenceDir = String(process.env.ADMIN_DISPLAY_EVIDENCE_DIR || '').trim()
      if (evidenceDir) fs.mkdirSync(evidenceDir, { recursive: true })

      for (const path of ADMIN_PAGES) {
        await test.step(path, async () => {
          await page.goto(`/admin${path}`, { waitUntil: 'domcontentloaded' })
          const appReady = page.locator('.app-shell.is-ready')
          const ready = await appReady.waitFor({ state: 'visible', timeout: 20_000 }).then(() => true).catch(() => false)
          if (!ready) {
            const body = (await page.locator('body').innerText().catch(() => '')).slice(0, 500)
            throw new Error(`admin shell unavailable: url=${page.url()} pageErrors=${pageErrors.join(' | ')} body=${body}`)
          }
          const shell = page.locator('.main-content')
          const view = page.locator('.route-view-shell')
          await expect(shell).toBeVisible()
          await expect(view).toBeVisible()
          await page.evaluate(async () => {
            await document.fonts.ready
          })

          const metrics = await page.evaluate(() => {
            const shellNode = document.querySelector<HTMLElement>('.main-content')
            const viewNode = document.querySelector<HTMLElement>('.route-view-shell')
            const taskNode = document.querySelector<HTMLElement>('.task-center-trigger')
            const topBarNode = document.querySelector<HTMLElement>('.top-bar')
            if (!shellNode || !viewNode || !taskNode || !topBarNode) return null
            const shellRect = shellNode.getBoundingClientRect()
            const viewRect = viewNode.getBoundingClientRect()
            const taskRect = taskNode.getBoundingClientRect()
            const topBarRect = topBarNode.getBoundingClientRect()
            return {
              documentWidth: document.documentElement.scrollWidth,
              viewportWidth: window.innerWidth,
              shellWidth: shellRect.width,
              viewWidth: viewRect.width,
              viewLeft: viewRect.left,
              shellLeft: shellRect.left,
              taskInsideTopBar: taskRect.top >= topBarRect.top && taskRect.bottom <= topBarRect.bottom + 1,
              imPanelsFit: (() => {
                const body = document.querySelector<HTMLElement>('.im-body')
                const sidebar = document.querySelector<HTMLElement>('.im-sidebar')
                const chat = document.querySelector<HTMLElement>('.im-chat')
                if (!body || !sidebar || !chat) return true
                const bodyRect = body.getBoundingClientRect()
                const sidebarRect = sidebar.getBoundingClientRect()
                const chatRect = chat.getBoundingClientRect()
                return (
                  sidebarRect.width <= bodyRect.width + 1 &&
                  chatRect.width <= bodyRect.width + 1 &&
                  chat.scrollWidth <= chat.clientWidth + 1
                )
              })(),
            }
          })

          expect(metrics, `${path} should expose measurable layout`).not.toBeNull()
          expect(metrics!.documentWidth, `${path} must not overflow the viewport`).toBeLessThanOrEqual(metrics!.viewportWidth + 1)
          expect(metrics!.viewWidth, `${path} must fill the main content width`).toBeGreaterThanOrEqual(metrics!.shellWidth - 2)
          expect(Math.abs(metrics!.viewLeft - metrics!.shellLeft), `${path} must align with the main content`).toBeLessThanOrEqual(1)
          expect(metrics!.taskInsideTopBar, `${path} task center must stay in the top bar`).toBe(true)
          if (viewport.width <= 768) {
            expect(metrics!.shellWidth, `${path} mobile shell must fill the viewport`).toBeGreaterThanOrEqual(metrics!.viewportWidth - 2)
            expect(metrics!.shellLeft, `${path} mobile shell must start at the viewport edge`).toBeLessThanOrEqual(1)
            expect(metrics!.imPanelsFit, `${path} mobile messenger panels must fit their container`).toBe(true)
          }
          if (evidenceDir) {
            const slug = path.replace(/^\//, '').replaceAll('/', '-')
            await page.screenshot({ path: nodePath.join(evidenceDir, `${viewport.name}-${slug}.png`), fullPage: false })
          }
        })
      }
    })
  }
})
