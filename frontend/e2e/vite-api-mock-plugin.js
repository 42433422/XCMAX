/**
 * Playwright critical-paths 使用 page.request，不经过 page.route。
 * 当 E2E_VITE_MOCK_API=1 时由 Vite 开发服在代理前返回契约 JSON（与 critical-paths.spec 对齐）。
 */
const E2E_MOD_LIST = {
  success: true,
  data: [{ id: 'e2e-mod', name: 'E2E Mod', version: '1.0.0', installed: false }],
}

const MOCK_SESSION_ID = 'e2e-playwright-session'

const MOCK_USER = {
  id: 1,
  username: 'admin',
  display_name: 'E2E Admin',
  role: 'admin',
}

function setMockSessionCookie(res) {
  res.setHeader(
    'Set-Cookie',
    `session_id=${MOCK_SESSION_ID}; Path=/; HttpOnly; SameSite=Lax`,
  )
}

function hasMockSession(req) {
  const cookie = String(req.headers.cookie || '')
  return cookie.includes(MOCK_SESSION_ID)
}

function sendJson(res, status, body) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(body))
}

function matchPath(url, prefix) {
  const path = (url || '').split('?')[0]
  return path === prefix || path.startsWith(`${prefix}/`)
}

export function e2eViteApiMockPlugin() {
  return {
    name: 'e2e-vite-api-mock',
    configureServer(server) {
      if (process.env.E2E_VITE_MOCK_API !== '1') return

      server.middlewares.use((req, res, next) => {
        const method = (req.method || 'GET').toUpperCase()
        const url = req.url || ''

        if (method === 'POST' && matchPath(url, '/api/auth/login')) {
          setMockSessionCookie(res)
          sendJson(res, 200, {
            success: true,
            data: { user: MOCK_USER, session_id: MOCK_SESSION_ID },
          })
          return
        }

        if (method === 'GET' && url.includes('/api/auth/session/validate')) {
          if (hasMockSession(req)) {
            sendJson(res, 200, {
              success: true,
              valid: true,
              data: { valid: true, user: MOCK_USER },
            })
          } else {
            sendJson(res, 200, {
              success: false,
              valid: false,
              error: { code: 'NO_SESSION', message: '无会话信息' },
            })
          }
          return
        }

        if (method === 'GET' && matchPath(url, '/api/auth/me')) {
          sendJson(res, 200, {
            success: true,
            data: { user: MOCK_USER, permissions: ['*'] },
          })
          return
        }

        if (url.includes('/api/mods/loading-status')) {
          sendJson(res, 200, { success: true, mods: [], data: { mods: [] } })
          return
        }

        if (method === 'GET' && (matchPath(url, '/api/health') || matchPath(url, '/health'))) {
          sendJson(res, 200, { status: 'ok', success: true })
          return
        }

        if (method === 'GET' && matchPath(url, '/api/printers')) {
          sendJson(res, 200, {
            success: true,
            data: [{ name: 'E2E-Printer', default: true }],
          })
          return
        }

        if (method === 'POST' && matchPath(url, '/api/excel/upload')) {
          sendJson(res, 200, {
            success: true,
            data: { rows: 3, columns: ['A', 'B'], sheet: 'Sheet1' },
          })
          return
        }

        if (method === 'POST' && url.includes('/api/print/')) {
          sendJson(res, 200, {})
          return
        }

        if (method === 'GET' && (url === '/api/mods/' || url === '/api/mods')) {
          sendJson(res, 200, E2E_MOD_LIST)
          return
        }

        if (method === 'POST' && url.includes('/api/mods/') && url.includes('/install')) {
          sendJson(res, 200, {
            success: true,
            data: { id: 'e2e-mod', installed: true },
          })
          return
        }

        if (method === 'GET' && matchPath(url, '/api/system/industry')) {
          sendJson(res, 200, {
            success: true,
            data: { id: 'e2e', name: 'E2E 行业' },
          })
          return
        }

        if (method === 'GET' && matchPath(url, '/api/system/industries')) {
          sendJson(res, 200, {
            success: true,
            data: [{ id: 'e2e', name: 'E2E 行业' }],
          })
          return
        }

        if (method === 'GET' && url.includes('/api/products/list')) {
          sendJson(res, 200, {
            success: true,
            data: { items: [], total: 0, page: 1, per_page: 1 },
          })
          return
        }

        next()
      })
    },
  }
}
