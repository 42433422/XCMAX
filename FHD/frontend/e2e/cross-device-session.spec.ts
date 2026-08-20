import { test, expect } from '@playwright/test'
import { installE2eShellMocks, isFullStack } from './helpers'

test.describe('Cross-device session reuse @cross_session', () => {
  test('同一 session_id 在第二个浏览器上下文复用登录态', async ({ browser }) => {
    test.skip(isFullStack(), 'full-stack 模式由真实后端覆盖；此处只校验 mock 行为')

    const ctx1 = await browser.newContext()
    const page1 = await ctx1.newPage()
    await installE2eShellMocks(page1)

    let validateCalls = 0
    let seenSessionIds: string[] = []
    await page1.route('**/api/auth/session/validate**', async (route) => {
      validateCalls += 1
      const cookieHeader = route.request().headers()['cookie'] || ''
      const match = cookieHeader.match(/session_id=([^;]+)/)
      if (match) seenSessionIds.push(match[1])
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, valid: true, data: { valid: true, username: 'e2e-user' } }),
      })
    })

    await page1.goto('/', { waitUntil: 'domcontentloaded', timeout: 30_000 })
    await expect(page1.locator('.app-shell.is-ready')).toBeVisible({ timeout: 25_000 })

    await page1.context().addCookies([
      {
        name: 'session_id',
        value: 'e2e-cross-session-001',
        domain: '127.0.0.1',
        path: '/',
        httpOnly: true,
        secure: false,
        sameSite: 'Lax',
      },
    ])

    const firstValidate = await page1.evaluate(async () => {
      const r = await fetch('/api/auth/session/validate')
      const json = await r.json().catch(() => ({}) as any)
      return { status: r.status, body: json }
    })
    expect(firstValidate.status, `first validate status`).toBe(200)
    expect(firstValidate.body?.valid).toBe(true)
    expect(validateCalls).toBeGreaterThanOrEqual(1)

    const state1 = await ctx1.storageState()
    const sessionIdCookie = state1.cookies.find((c) => c.name === 'session_id')
    expect(sessionIdCookie, `session_id cookie in ctx1`).toBeTruthy()
    expect(sessionIdCookie?.value).toBe('e2e-cross-session-001')

    const ctx2 = await browser.newContext({ storageState: state1 })
    const page2 = await ctx2.newPage()
    await installE2eShellMocks(page2)

    await page2.route('**/api/auth/session/validate**', async (route) => {
      validateCalls += 1
      const cookieHeader = route.request().headers()['cookie'] || ''
      const match = cookieHeader.match(/session_id=([^;]+)/)
      if (match) seenSessionIds.push(match[1])
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, valid: true, data: { valid: true, username: 'e2e-user' } }),
      })
    })

    const secondValidate = await page2.evaluate(async () => {
      const r = await fetch('/api/auth/session/validate')
      const json = await r.json().catch(() => ({}) as any)
      return { status: r.status, body: json }
    })
    expect(secondValidate.status, `second validate status`).toBe(200)
    expect(secondValidate.body?.valid, `ctx2 should reuse session without re-login`).toBe(true)

    const state2 = await ctx2.storageState()
    const sessionIdCookie2 = state2.cookies.find((c) => c.name === 'session_id')
    expect(sessionIdCookie2?.value, `ctx2 session_id should match ctx1`).toBe('e2e-cross-session-001')

    expect(
      seenSessionIds.some((sid) => sid === 'e2e-cross-session-001'),
      `seen session ids: ${JSON.stringify(seenSessionIds)}`,
    ).toBe(true)

    await page1.close()
    await page2.close()
    await ctx1.close()
    await ctx2.close()
  })
})
