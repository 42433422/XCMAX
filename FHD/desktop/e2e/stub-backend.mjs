#!/usr/bin/env node
/**
 * E2E 专用后端替身（Playwright-Electron）。
 *
 * 桌面端 dev 模式通过 `process.env.PYTHON` 指定后端可执行文件（见 desktop-config.ts
 * backendExecutable）。本脚本以 node shebang 充当该可执行文件，忽略 run.py 等参数，
 * 提供一个最小 HTTP 服务，模拟真实后端的三条关键契约：
 *   GET /api/ping            → 200 且 Server 头含 "uvicorn"（waitForBackendPing 据此判定）
 *   GET /api/desktop/status  → { appRoutesReady: true, dbRecovery: { action: 'ok' } }
 *   GET /                    → 带 #e2e-marker 的静态页（验证主界面真实加载）
 *
 * 仅用于 e2e/ 测试，不进入安装包（electron-builder files 仅含 dist/resources）。
 */
import http from 'node:http'

const argv = process.argv.slice(2)
const portIdx = argv.indexOf('--port')
const port = portIdx >= 0 ? Number(argv[portIdx + 1]) : 17500
const hostIdx = argv.indexOf('--host')
const host = hostIdx >= 0 ? String(argv[hostIdx + 1]) : '0.0.0.0'

const INDEX_HTML = `<!doctype html>
<html>
<head><meta charset="utf-8"><title>XCAGI</title></head>
<body><div id="app"><div id="e2e-marker">XCAGI_E2E_OK</div></div></body>
</html>`

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', `http://127.0.0.1:${port}`)
  res.setHeader('Server', 'uvicorn')
  if (url.pathname === '/api/ping') {
    res.writeHead(200, { 'Content-Type': 'text/plain' })
    res.end('pong')
    return
  }
  if (url.pathname === '/api/desktop/status') {
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({
      appRoutesReady: true,
      readyForUi: true,
      dbRecovery: { action: 'ok' },
    }))
    return
  }
  if (url.pathname === '/' || url.pathname === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' })
    res.end(INDEX_HTML)
    return
  }
  res.writeHead(404, { 'Content-Type': 'application/json' })
  res.end(JSON.stringify({ detail: 'stub: not found' }))
})

server.listen(port, host, () => {
  process.stdout.write(`[stub-backend] listening on ${host}:${port}\n`)
})

process.on('SIGTERM', () => {
  server.close(() => process.exit(0))
  setTimeout(() => process.exit(0), 1_000).unref()
})
