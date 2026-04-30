/**
 * 联机冒烟：需本机后端已启动。
 *
 *   set SMOKE_API_BASE_URL=http://127.0.0.1:5000
 *   npm run test:smoke -- tests/smoke/api-health-upload.live.smoke.test.js
 *
 * 上传用 node:http 拼 multipart（Vitest/jsdom 下 fetch+FormData POST 可能一直挂起）。
 */
import http from 'node:http'
import { describe, it, expect } from 'vitest'

const base = String(process.env.SMOKE_API_BASE_URL || '')
  .trim()
  .replace(/\/+$/, '')
const run = Boolean(base)

/** 最小有效 PNG（1×1） */
const MIN_PNG = Buffer.from(
  '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c63000100000500001d0d4e120000000049454e44ae426082',
  'hex'
)

function postMultipartUpload(urlStr, fileField, filename, fileBuf, mime) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr)
    const boundary = `----VitestSmoke${Date.now()}`
    const prelude = Buffer.from(
      `--${boundary}\r\n` +
        `Content-Disposition: form-data; name="${fileField}"; filename="${filename}"\r\n` +
        `Content-Type: ${mime}\r\n\r\n`,
      'utf8'
    )
    const epilog = Buffer.from(`\r\n--${boundary}--\r\n`, 'utf8')
    const body = Buffer.concat([prelude, fileBuf, epilog])
    const req = http.request(
      {
        hostname: u.hostname,
        port: u.port || 80,
        path: u.pathname,
        method: 'POST',
        headers: {
          'Content-Type': `multipart/form-data; boundary=${boundary}`,
          'Content-Length': String(body.length),
        },
      },
      (res) => {
        const chunks = []
        res.on('data', (c) => chunks.push(c))
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8')
          resolve({ status: res.statusCode, text })
        })
      }
    )
    req.on('error', reject)
    req.write(body)
    req.end()
  })
}

;(run ? describe : describe.skip)(`live API (${base || 'set SMOKE_API_BASE_URL'})`, () => {
  it('GET /api/health → 200', async () => {
    const res = await fetch(`${base}/api/health`)
    expect(res.ok, `HTTP ${res.status}`).toBe(true)
    const j = await res.json()
    expect(j.status === 'healthy' || j.success === true || typeof j === 'object').toBe(true)
  })

  it('POST /api/upload/temp multipart → 200', async () => {
    const { status, text } = await postMultipartUpload(
      `${base}/api/upload/temp`,
      'file',
      'smoke.png',
      MIN_PNG,
      'image/png'
    )
    let j
    try {
      j = JSON.parse(text)
    } catch {
      j = {}
    }
    expect(status, text.slice(0, 300)).toBe(200)
    expect(j.success, text).toBe(true)
  })
})
