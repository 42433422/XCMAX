import type { Page, Route } from '@playwright/test'

/** Synthetic account only; no installed backend, customer account, or customer files. */
export async function installStartupReadinessMocks(page: Page, desktop = true) {
  const calls = new Map<string, number>()
  const handlers = new Map<string, (route: Route, call: number) => Promise<void>>()
  let userId = 1
  const profile = () => ({ account_kind: 'personal', local_user_id: userId,
    user: { id: userId, username: `startup-test-${userId}`, role: 'user' }, permissions: [] })
  await page.addInitScript(desktop => {
    if (desktop) Object.assign(window, { xcagiDesktop: {} })
    localStorage.setItem('xcagi_product_flow_completed', '1')
    localStorage.setItem('xcagi_product_flow_host_ack', '1')
  }, desktop)
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    // Vite also serves /src/api/*.ts; never replace source modules with JSON.
    if (!path.startsWith('/api/')) return route.continue()
    const call = (calls.get(path) || 0) + 1
    calls.set(path, call)
    const handler = handlers.get(path)
    if (handler) return handler(route, call)
    let body: unknown = { success: true, data: {} }
    if (path === '/api/runtime/product-sku') body = { success: true, data: { sku: 'personal' } }
    else if (path === '/api/auth/session/validate') body = { success: true, valid: true,
      data: { valid: true, username: `startup-test-${userId}`, ...profile() } }
    else if (path === '/api/auth/me' || path === '/api/auth/login') body = { success: true, data: profile() }
    else if (path === '/api/workspace/prefs') body = { success: true, owner_id: `session:${userId}`,
      data: { host_pack_acknowledged: true, product_flow_completed: true, selected_industry_id: '通用' } }
    else if (path === '/api/system/industry') body = { success: true, data: { id: '通用', name: '通用', code: '通用' } }
    else if (path === '/api/system/industries') body = { success: true, data: { industries: [{ id: '通用', name: '通用' }] } }
    else if (['/api/mods/', '/api/mods/routes', '/api/agent/tasks', '/api/agent/runs'].includes(path)) body = { success: true, data: [] }
    else if (path === '/api/mods/loading-status') body = { success: true,
      data: { mods: [], discovered_mod_ids: [], mods_loaded: 0, load_mismatch: false } }
    else if (path.startsWith('/api/conversations/')) body = { success: true, id: path.split('/').pop(), data: [], messages: [], metadata: {} }
    else if (path === '/api/conversation/model-status') body = { ok: true }
    else if (path.includes('/stream')) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': synthetic idle\n\n' })
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  return { calls, handlers, setUser: (id: number) => { userId = id } }
}

export function deferred() {
  let release!: () => void
  return { promise: new Promise<void>(resolve => { release = resolve }), release: () => release() }
}
