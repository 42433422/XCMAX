import http from 'node:http'

export function loopbackHttpGet(url: string, timeoutMs: number): Promise<{
  ok: boolean
  getHeader(name: string): string
  json(): Promise<unknown>
}> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url)
    if (parsed.protocol !== 'http:' || parsed.hostname !== '127.0.0.1') {
      throw new Error('backend probe requires an HTTP IPv4 loopback URL')
    }
    const req = http.get(parsed, { agent: false }, res => { // Bypass globalAgent proxyEnv.
      const chunks: Buffer[] = []
      res.on('data', chunk => chunks.push(Buffer.from(chunk)))
      res.on('error', reject)
      res.on('end', () => {
        clearTimeout(timer)
        resolve({
          ok: (res.statusCode ?? 0) >= 200 && (res.statusCode ?? 0) < 300,
          getHeader(name) {
            const value = res.headers[name.toLowerCase()]
            return Array.isArray(value) ? value[0] ?? '' : value ?? ''
          },
          async json() { return JSON.parse(Buffer.concat(chunks).toString('utf8')) as unknown },
        })
      })
    })
    // Bound the entire response, including a stalled or slowly streaming body.
    const timer = setTimeout(() => req.destroy(new Error(`loopback GET timeout after ${timeoutMs}ms`)), timeoutMs)
    req.on('error', reject)
    req.on('close', () => clearTimeout(timer))
  })
}
