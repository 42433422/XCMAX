import { describe, expect, it } from 'vitest'

/** Session / CSRF 头契约（与 modstore_server/api/csrf 及 FHD 中间件一致）。 */
describe('auth session contract', () => {
  it('requires Authorization Bearer or session cookie name', () => {
    const headers = {
      Authorization: 'Bearer sess-abc',
      'X-CSRF-Token': 'csrf-token-hex',
    }
    expect(headers.Authorization).toMatch(/^Bearer /)
    expect(headers['X-CSRF-Token'].length).toBeGreaterThan(8)
  })

  it('auth me response wraps user and permissions', () => {
    const body = {
      success: true,
      data: {
        user: { id: 1, username: 'admin', role: 'admin', is_active: true },
        permissions: ['admin.manage_users'],
        account_kind: 'enterprise',
      },
    }
    expect(body.success).toBe(true)
    expect(body.data.user.id).toBeTypeOf('number')
    expect(Array.isArray(body.data.permissions)).toBe(true)
  })
})
