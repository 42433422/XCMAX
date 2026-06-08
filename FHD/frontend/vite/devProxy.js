/** Dev server / preview API proxy (extracted from vite.config.js). */

export function rewriteUpstreamRedirectToRelative(proxy, upstreamBase) {
  const prefix = String(upstreamBase || '').trim().replace(/\/$/, '')
  let upstreamOrigin = ''
  try {
    if (prefix) upstreamOrigin = new URL(prefix.includes('://') ? prefix : `http://${prefix}`).origin
  } catch {
    upstreamOrigin = ''
  }
  proxy.on('proxyRes', (proxyRes) => {
    const code = Number(proxyRes.statusCode || 0)
    if (code < 300 || code >= 400) return
    let loc = proxyRes.headers.location
    if (!loc || typeof loc !== 'string') return
    loc = loc.trim()
    // 协议相对 URL
    if (loc.startsWith('//')) {
      const scheme = upstreamOrigin.startsWith('https') ? 'https:' : 'http:'
      loc = scheme + loc
    }
    try {
      if (upstreamOrigin) {
        const u = new URL(loc, upstreamOrigin)
        if (u.origin === upstreamOrigin) {
          proxyRes.headers.location = u.pathname + u.search + u.hash
          return
        }
      }
    } catch {
      /* fall through */
    }
    if (prefix && loc.startsWith(prefix)) {
      const rest = loc.slice(prefix.length)
      const path = rest && rest.startsWith('/') ? rest : `/${rest || ''}`
      proxyRes.headers.location = path
    }
  })
}

/** 代理无法连上 FastAPI 时在终端给出可操作提示（常见：ETIMEDOUT / ECONNREFUSED）。 */
export function logViteProxyConnectFailure(routeLabel, apiBase, err) {
  const msg = err && err.message ? String(err.message) : String(err)
  console.error(`[vite-proxy] ${routeLabel} -> ${apiBase} failed: ${msg}`)
  if (/ETIMEDOUT|ECONNREFUSED|ENOTFOUND|EAI_AGAIN/i.test(msg)) {
    console.error(
      '  → 无法连接代理目标。请检查：① 云主机安全组/系统防火墙是否放行该端口 ② 后端是否监听 0.0.0.0（勿只绑 127.0.0.1）' +
        ' ③ 本机到该 IP 的网络是否可达。本地开发可将 frontend/.env.local 设为 VITE_API_BASE=http://127.0.0.1:5000 后重启 dev。'
    )
  }
}

export function proxyUpstreamErrorPayload(apiBase, err) {
  const msg = err && err.message ? String(err.message) : ''
  const head = '无法连接后端 ' + apiBase + '。'
  if (/ETIMEDOUT/i.test(msg)) {
    return (
      head +
      '（连接超时：核对 VITE_API_BASE、安全组与后端监听地址；本机后端常用 http://127.0.0.1:5000）'
    )
  }
  if (/ECONNREFUSED/i.test(msg)) {
    return head + '（连接被拒绝：该端口无服务或仅监听本机回环）'
  }
  if (/ENOTFOUND|EAI_AGAIN/i.test(msg)) {
    return head + '（域名/IP 解析失败或网络不可用）'
  }
  return head + '请先启动后端（仓库根 python run.py，默认端口见控制台）。'
}

/**
 * 开发服务器与 ``vite preview`` 共用：把 ``/api`` 转到 FastAPI（默认 :5000）。
 * preview 默认不带 proxy，局域网用 ``http://<ip>:5001`` 预览构建产物时会整页 404。
 */
export function buildDevProxy(apiBase) {
  return {
        // 开发时统一把业务 API 代理到完整后端 run.py（5000）。材料拆分进程见 run_warehouse.py（默认 5002），勿占用 5001（Vite）。
        // 规则：尽量使用"更具体的前缀 -> 5000"，最后用 '/api' 兜底到 5000。

        // compat：/orders/*（不带 /api 前缀）。注意 Vue 路由也有页面 /orders，浏览器刷新须走 SPA。
        '/orders': {
          target: apiBase,
          changeOrigin: true,
          bypass(req) {
            const accept = req.headers.accept || ''
            if (req.method === 'GET' && accept.includes('text/html')) {
              return '/index.html'
            }
          },
        },

        // compat：/health
        '/health': {
          target: apiBase,
          changeOrigin: true,
        },

        // 出货/打印/AI/chat/以及 compat 中的相关接口都走 5000
        '/api/shipment': {
          target: apiBase,
          changeOrigin: true,
        },
        // Planner SSE：默认代理超时过短可能中断长连接
        '/api/ai': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
        '/api/print': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/generate': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/orders': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/shipment-records': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/purchase_units': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/product_names': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/printers': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/sales-contract': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/price-list': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/tts': {
          target: apiBase,
          changeOrigin: true,
        },
        // FHD 风格上传（对话 @ Excel 等）：须由 FastAPI 5000 提供
        '/api/upload': {
          target: apiBase,
          changeOrigin: true,
          timeout: 120000,
          proxyTimeout: 120000,
        },

        // 兼容：基础数据/聊天/联系人等也应转发到 5000
        // 否则会落入兜底 '/api'，若 5000 未启动则代理失败（终端见 [vite-proxy] 日志）
        '/api/conversations': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/wechat_contacts': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
        '/api/products': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/materials': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/system': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/state': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/market': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/intent-packages': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/tools': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/wechat': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/db-tools': {
          target: apiBase,
          changeOrigin: true,
        },
        '/api/templates': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
        // 传统模式 watch 为长连接流式响应；默认超时过短易出现 504
        '/api/traditional-mode': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
        },
        // XCmax 同步 SSE 流（/api/xcmax/sync/stream）；长连接须禁用代理超时
        '/api/xcmax': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
          configure: (proxy) => {
            proxy.on('proxyRes', (proxyRes, _req, res) => {
              if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
                proxyRes.headers['cache-control'] = 'no-cache'
                proxyRes.headers['connection'] = 'keep-alive'
                if (!res.headersSent) res.flushHeaders()
              }
            })
            proxy.on('error', (err, _req, res) => {
              logViteProxyConnectFailure('/api/xcmax', apiBase, err)
              if (res && !res.headersSent && typeof res.writeHead === 'function') {
                res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
                res.end(
                  JSON.stringify({
                    success: false,
                    error: proxyUpstreamErrorPayload(apiBase, err),
                  })
                )
              }
            })
          },
        },
        // 奇士美 PRO Mod（含 /api/mod/sz-qsm-pro/phone-agent/*）；代理层失败时返回 JSON 502，避免与后端 500 混淆
        '/api/mod': {
          target: apiBase,
          changeOrigin: true,
          configure: (proxy) => {
            rewriteUpstreamRedirectToRelative(proxy, apiBase)
            proxy.on('error', (err, _req, res) => {
              logViteProxyConnectFailure('/api/mod', apiBase, err)
              if (res && !res.headersSent && typeof res.writeHead === 'function') {
                res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
                res.end(
                  JSON.stringify({
                    success: false,
                    error: proxyUpstreamErrorPayload(apiBase, err),
                  })
                )
              }
            })
          },
        },

        // Mod 系统（显式规则，避免个别环境下 /api 兜底未命中或错误码不直观）
        '/api/mods': {
          target: apiBase,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
          configure: (proxy) => {
            rewriteUpstreamRedirectToRelative(proxy, apiBase)
            proxy.on('error', (err, _req, res) => {
              logViteProxyConnectFailure('/api/mods', apiBase, err)
              if (res && !res.headersSent && typeof res.writeHead === 'function') {
                res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
                res.end(
                  JSON.stringify({
                    success: false,
                    error: proxyUpstreamErrorPayload(apiBase, err),
                  })
                )
              }
            })
          },
        },

        // 兜底：其余所有 /api 都发给后端服务（5000）。若浏览器大量 500/502，先确认已执行：python run.py
        '/api': {
          target: apiBase,
          changeOrigin: true,
          ws: true,
          configure: (proxy) => {
            rewriteUpstreamRedirectToRelative(proxy, apiBase)
            // 把真实客户端 IP 透传给后端，让 LAN Guard 能拿到正确的来源地址
            proxy.on('proxyReq', (proxyReq, req) => {
              const clientIp = req.socket?.remoteAddress || req.headers['x-forwarded-for'] || ''
              const normalizedIp = clientIp.replace(/^::ffff:/, '')
              if (normalizedIp) {
              proxyReq.setHeader('X-Forwarded-For', normalizedIp)
              proxyReq.setHeader('X-Real-IP', normalizedIp)
              }
            })
            proxy.on('error', (err, _req, res) => {
              logViteProxyConnectFailure('/api', apiBase, err)
              if (res && !res.headersSent && typeof res.writeHead === 'function') {
                res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
                res.end(
                  JSON.stringify({
                    success: false,
                    error: proxyUpstreamErrorPayload(apiBase, err),
                  })
                )
              }
            })
          }
        },
  }
}
