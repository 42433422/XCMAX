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
    if (path.endsWith('/api/xcmax/admin/autonomy/actions/pending')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          count: 1,
          items: [{
            action_id: 'release:layout-regression',
            action: 'apply_release_to_cvm',
            state: 'pending_approval',
            source: 'layout-regression.cron',
            execution_mode: 'external_dispatch_required',
            admin_execution_ready: false,
            execution_guidance: '该发布必须由正式发布工作流审批并执行。',
            risk_decision: { risk_level: 'HIGH', decision: 'confirm' },
          }],
          summary: {
            waiting: 1,
            actionable: 0,
            states: { executed: 15, superseded: 27 },
            execution_modes: { external_dispatch_required: 1 },
          },
        }),
      })
      return
    }
    if (path.endsWith('/api/xcmax/admin/autonomy/audit-log')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          items: Array.from({ length: 40 }, (_, index) => ({
            id: `audit-${index}`,
            action: index % 2 ? 'employee_execute' : 'apply_release_to_cvm',
            risk_level: index % 2 ? 'MEDIUM' : 'HIGH',
            actor: `layout-regression-${index}`,
            timestamp: '2026-08-29T03:30:00Z',
          })),
        }),
      })
      return
    }
    if (path.endsWith('/api/xcmax/admin/market/users')) {
      const users = Array.from({ length: 39 }, (_, index) => ({
        id: index + 1,
        username: `delivery-enterprise-${String(index + 1).padStart(2, '0')}`,
        email: `delivery-${index + 1}@example.test`,
        is_enterprise: true,
      }))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, users, total: users.length }),
      })
      return
    }
    if (path.endsWith('/api/xcmax/market-proxy/customer-service/custom-deliveries')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, items: [] }),
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

test('admin first paint shows a useful loading shell before JavaScript starts', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false })
  const page = await context.newPage()
  try {
    await page.goto('/admin/autonomy-approval-hub', { waitUntil: 'domcontentloaded' })
    const bootstrap = page.locator('.admin-bootstrap')
    await expect(bootstrap).toBeVisible()
    await expect(bootstrap).toContainText('XCMAX 管理中心')
    await expect(bootstrap).toContainText('正在加载管理页面')
    await expect(bootstrap).toHaveCSS('min-height', `${await page.evaluate(() => window.innerHeight)}px`)
  } finally {
    await context.close()
  }
})

test('approval center keeps its header and status summary above a long audit stream', async ({ page }) => {
  await installAdminDisplayMocks(page)

  for (const viewport of VIEWPORTS) {
    await test.step(viewport.name, async () => {
      await page.setViewportSize(viewport)
      await page.goto('/admin/autonomy-approval-hub', { waitUntil: 'domcontentloaded' })
      await page.locator('.app-shell.is-ready').waitFor({ state: 'visible', timeout: 20_000 })
      await expect(page.locator('.audit-item')).toHaveCount(40)

      const geometry = await page.evaluate(() => {
        const rect = (selector: string) => {
          const node = document.querySelector<HTMLElement>(selector)
          if (!node) throw new Error(`missing ${selector}`)
          return node.getBoundingClientRect()
        }
        const header = rect('.approval-hub-view .page-header')
        const headerContent = rect('.approval-hub-view .page-header > div:first-child')
        const status = rect('.approval-hub-view .status-grid')
        const statusCard = rect('.approval-hub-view .status-card')
        const hub = rect('.approval-hub-view .hub-grid')
        return {
          headerHeight: header.height,
          headerContentHeight: headerContent.height,
          statusHeight: status.height,
          statusCardHeight: statusCard.height,
          statusBottom: status.bottom,
          hubTop: hub.top,
        }
      })

      expect(geometry.headerHeight, `${viewport.name}: header content must not be flex-shrunk`).toBeGreaterThanOrEqual(
        geometry.headerContentHeight - 1,
      )
      expect(geometry.statusHeight, `${viewport.name}: status cards must not be flex-shrunk`).toBeGreaterThanOrEqual(
        geometry.statusCardHeight - 1,
      )
      expect(geometry.hubTop, `${viewport.name}: lists must start after the status summary`).toBeGreaterThanOrEqual(
        geometry.statusBottom,
      )
    })
  }
})

test('delivery center keeps every section in document flow with a long enterprise roster', async ({ page }) => {
  await installAdminDisplayMocks(page)

  for (const viewport of VIEWPORTS) {
    await test.step(viewport.name, async () => {
      await page.setViewportSize(viewport)
      await page.goto('/admin/delivery-center', { waitUntil: 'domcontentloaded' })
      await page.locator('.app-shell.is-ready').waitFor({ state: 'visible', timeout: 20_000 })
      await expect(page.locator('.enterprise-roster__grid article')).toHaveCount(39)

      const geometry = await page.evaluate(() => {
        const rect = (selector: string) => {
          const node = document.querySelector<HTMLElement>(selector)
          if (!node) throw new Error(`missing ${selector}`)
          return node.getBoundingClientRect()
        }
        const centerNode = document.querySelector<HTMLElement>('.delivery-center')
        if (!centerNode) throw new Error('missing .delivery-center')
        const hero = rect('.delivery-hero')
        const stats = rect('.delivery-stats')
        const statCard = rect('.delivery-stats article')
        const roster = rect('.enterprise-roster')
        const toolbar = rect('.delivery-toolbar')
        const empty = rect('.delivery-empty')
        return {
          statsHeight: stats.height,
          statCardHeight: statCard.height,
          heroBottom: hero.bottom,
          statsTop: stats.top,
          statsBottom: stats.bottom,
          rosterTop: roster.top,
          rosterBottom: roster.bottom,
          toolbarTop: toolbar.top,
          toolbarBottom: toolbar.bottom,
          emptyTop: empty.top,
          scrollHeight: centerNode.scrollHeight,
          clientHeight: centerNode.clientHeight,
        }
      })

      expect(geometry.statsTop, `${viewport.name}: statistics must start after the page header`).toBeGreaterThanOrEqual(
        geometry.heroBottom,
      )
      expect(geometry.statsHeight, `${viewport.name}: statistic cards must keep their natural height`).toBeGreaterThanOrEqual(
        geometry.statCardHeight - 1,
      )
      expect(geometry.rosterTop, `${viewport.name}: roster must start after statistics`).toBeGreaterThanOrEqual(
        geometry.statsBottom,
      )
      expect(geometry.toolbarTop, `${viewport.name}: custom-order filters must start after the roster`).toBeGreaterThanOrEqual(
        geometry.rosterBottom,
      )
      expect(geometry.emptyTop, `${viewport.name}: empty state must start after its filters`).toBeGreaterThanOrEqual(
        geometry.toolbarBottom,
      )
      expect(geometry.scrollHeight, `${viewport.name}: long delivery content must remain scrollable`).toBeGreaterThan(
        geometry.clientHeight,
      )
    })
  }
})
