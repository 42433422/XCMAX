/**
 * 冒烟：直连后端「产品批量导入」接口（与前端设置页写入令牌同源能力）
 *
 * 默认跳过：未配置时不占 CI 时间。
 * 本地联调时设置：
 *   SMOKE_API_BASE_URL=http://127.0.0.1:8000
 *   SMOKE_DB_WRITE_TOKEN=<与后端 FHD_DB_WRITE_TOKEN 一致>
 * 若后端启用了 FHD_API_KEYS，再加：
 *   SMOKE_API_KEY=<合法 key>
 * 仅检查 OpenAPI 是否挂载 bulk-import（不调用写库）：
 *   SMOKE_CHECK_BULK_ROUTE=1
 *   （可与 SMOKE_API_BASE_URL 同用，无需 token）
 *
 * npm run test:smoke -- tests/smoke/db-bulk-import.smoke.test.js
 */
import http from 'node:http'
import https from 'node:https'
import { describe, it, expect } from 'vitest'

/** Node 内置请求（Vitest jsdom 下无 fetch 也可用） */
function httpRequest(urlStr, { method = 'GET', headers = {}, body = null } = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr)
    const lib = u.protocol === 'https:' ? https : http
    const req = lib.request(
      urlStr,
      { method, headers },
      (res) => {
        const chunks = []
        res.on('data', (c) => chunks.push(c))
        res.on('end', () => {
          const buf = Buffer.concat(chunks)
          const text = buf.toString('utf8')
          resolve({
            ok: res.statusCode >= 200 && res.statusCode < 300,
            status: res.statusCode,
            text: () => Promise.resolve(text),
            json: () => Promise.resolve(JSON.parse(text)),
          })
        })
      }
    )
    req.on('error', reject)
    if (body != null) req.write(body)
    req.end()
  })
}

function smokeBase() {
  return String(
    process.env.SMOKE_API_BASE_URL ||
      process.env.VITE_API_BASE_URL ||
      process.env.VITE_API_BASE ||
      ''
  ).replace(/\/+$/, '')
}

function smokeDbToken() {
  return String(process.env.SMOKE_DB_WRITE_TOKEN || process.env.FHD_DB_WRITE_TOKEN || '').trim()
}

function smokeApiKey() {
  return String(process.env.SMOKE_API_KEY || '').trim()
}

const base = smokeBase()
const dbTok = smokeDbToken()
const apiKey = smokeApiKey()
const canRun = Boolean(base && dbTok)

const verifyRoute = String(process.env.SMOKE_CHECK_BULK_ROUTE || '').trim() === '1'

;(verifyRoute && base ? describe : describe.skip)('bulk-import 路由（OpenAPI）', () => {
  it('当前后端暴露 POST /api/admin/products/bulk-import', async () => {
    const res = await httpRequest(`${base}/openapi.json`)
    expect(res.ok, `GET openapi ${res.status}`).toBe(true)
    const o = await res.json()
    const paths = Object.keys(o.paths || {})
    const hit = paths.some(
      (p) =>
        p.replace(/\/$/, '') === '/api/admin/products/bulk-import' ||
        p.replace(/\/$/, '') === '/api/admin/products/bulk-import/'
    )
    expect(hit, `paths 中应有 bulk-import，实际含 admin 的项: ${paths.filter((x) => x.includes('admin')).join(', ') || '(无)'}`).toBe(
      true
    )
  })
})

;(canRun ? describe : describe.skip)('db bulk-import API (可选集成)', () => {
  it('dry_run 返回 success（不写库）', async () => {
    const hdr = {
      'Content-Type': 'application/json',
      'X-FHD-Db-Write-Token': dbTok,
    }
    if (apiKey) {
      hdr['X-Api-Key'] = apiKey
    }
    const url = `${base}/api/admin/products/bulk-import`
    const payload = JSON.stringify({
      customer_name: 'Vitest冒烟客户',
      dry_run: true,
      items: [
        {
          model_number: 'VITEST-SMOKE-1',
          name: '冒烟产品',
          specification: '1KG/桶',
          price: 9.99,
        },
      ],
    })
    const res = await httpRequest(url, { method: 'POST', headers: hdr, body: payload })
    const text = await res.text()
    let json
    try {
      json = JSON.parse(text)
    } catch {
      json = { _raw: text }
    }
    expect(res.status, `HTTP ${res.status}: ${text.slice(0, 500)}`).toBe(200)
    expect(json.success, JSON.stringify(json)).toBe(true)
    expect(json.data?.success !== false, JSON.stringify(json)).toBe(true)
  })
})
