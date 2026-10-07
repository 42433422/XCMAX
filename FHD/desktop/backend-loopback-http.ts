import http from 'node:http'

/** Node fetch/undici 会继承系统 HTTP_PROXY；本地后端探测必须直连 loopback。 */
export type LoopbackHttpResponse = {
  ok: boolean
  status: number
  getHeader(name: string): string
  json(): Promise<unknown>
  text(): Promise<string>
}

export function loopbackHttpGet(url: string, timeoutMs: number): Promise<LoopbackHttpResponse> {
  return new Promise((resolve, reject) => {
    let parsed: URL
    try {
      parsed = new URL(url)
    } catch (error) {
      reject(error)
      return
    }
    if (parsed.protocol !== 'http:') {
      reject(new Error(`loopback probe expects http URL, got ${parsed.protocol}`))
      return
    }

    const req = http.request(
      {
        hostname: parsed.hostname,
        port: parsed.port || 80,
        path: `${parsed.pathname}${parsed.search}`,
        method: 'GET',
        timeout: timeoutMs,
      },
      res => {
        const chunks: Buffer[] = []
        res.on('data', chunk => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)))
        res.on('end', () => {
          const body = Buffer.concat(chunks).toString('utf8')
          const status = res.statusCode ?? 0
          resolve({
            ok: status >= 200 && status < 300,
            status,
            getHeader(name: string) {
              const key = name.toLowerCase()
              const value = res.headers[key]
              if (value === undefined) return ''
              return Array.isArray(value) ? value[0] ?? '' : value
            },
            async json() {
              return JSON.parse(body) as unknown
            },
            async text() {
              return body
            },
          })
        })
      },
    )
    req.on('timeout', () => {
      req.destroy()
      reject(new Error(`loopback GET timeout after ${timeoutMs}ms`))
    })
    req.on('error', reject)
    req.end()
  })
}
