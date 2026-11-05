import http from 'node:http'
import { afterEach, describe, expect, it } from 'vitest'
import { loopbackHttpGet } from './backend-loopback-http'

const servers: http.Server[] = []
const originalAgent = http.globalAgent
async function serve(handler: http.RequestListener): Promise<string> {
  const server = http.createServer(handler)
  servers.push(server)
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  return `http://127.0.0.1:${(server.address() as import('node:net').AddressInfo).port}`
}
afterEach(async () => {
  if (http.globalAgent !== originalAgent) http.globalAgent.destroy()
  http.globalAgent = originalAgent
  await Promise.all(servers.splice(0).map(server => new Promise<void>(resolve => {
    server.closeAllConnections()
    server.close(() => resolve())
  })))
})

describe('direct backend probe', () => {
  it('bypasses the global agent with an unusable environment proxy', async () => {
    http.globalAgent = new http.Agent({ proxyEnv: { HTTP_PROXY: 'http://127.0.0.1:1', NO_PROXY: '' } })
    const url = await serve((req, res) => {
      res.setHeader('server', 'uvicorn')
      res.end(JSON.stringify({ path: req.url, healthy: true }))
    })
    await expect(new Promise((resolve, reject) => http.get(url, resolve).on('error', reject))).rejects.toThrow()
    const response = await loopbackHttpGet(`${url}/api/ping?ready=1`, 500)
    expect(response.ok).toBe(true)
    expect(response.getHeader('SERVER')).toBe('uvicorn')
    expect(response.getHeader('missing')).toBe('')
    expect(await response.json()).toEqual({ path: '/api/ping?ready=1', healthy: true })
  })
  it('rejects a body that keeps streaming beyond the total time budget', async () => {
    const url = await serve((_req, res) => { res.writeHead(200); res.write('{') })
    await expect(loopbackHttpGet(url, 30)).rejects.toThrow('timeout')
  })
  it('retains non-success status and JSON parsing errors', async () => {
    const url = await serve((_req, res) => { res.writeHead(503); res.end('unavailable') })
    const response = await loopbackHttpGet(url, 500)
    expect(response.ok).toBe(false)
    await expect(response.json()).rejects.toThrow()
  })
  it.each(['https://127.0.0.1/api/ping', 'http://example.com/api/ping', 'invalid'])('rejects unsafe probe %s', async url => {
    await expect(loopbackHttpGet(url, 100)).rejects.toThrow()
  })
})
