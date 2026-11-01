import { test, expect } from '@playwright/test'
import { csrfHeaders, E2E_ACCOUNT_KIND, E2E_USER, E2E_PASSWORD, isFullStack } from './helpers'

const skipUnlessFullStack = !isFullStack()

test.describe('plan2026 skeleton paths (full-stack only)', () => {
  test.skip(skipUnlessFullStack, 'requires E2E_FULL_STACK=1')

  test('skeleton login', async ({ request }) => {
    const headers = await csrfHeaders(request)
    const resp = await request.post('/api/auth/login', {
      headers,
      data: { username: E2E_USER, password: E2E_PASSWORD, account_kind: E2E_ACCOUNT_KIND },
    })
    expect(resp.status(), await resp.text()).toBe(200)
    const body = await resp.json().catch(() => ({}))
    expect(body?.success, `login response: ${JSON.stringify(body)}`).toBe(true)
  })

})
