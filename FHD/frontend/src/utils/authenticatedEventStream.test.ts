import { afterEach, expect, it, vi } from 'vitest'
import { AuthenticatedEventStream } from './authenticatedEventStream'
const scopeState = vi.hoisted(() => ({ mod: 'mod-a', user: 'u1' }))
vi.mock('@/utils/apiBase', () => ({ getActiveExtensionModHeaders: () => ({ 'X-XCAGI-Active-Mod-Id': scopeState.mod }) }))
vi.mock('@/utils/tenantStorageScopeRuntime', () => ({ getRuntimeTenantStorageScopeInput: () => ({ localUserId: scopeState.user }) }))
vi.mock('@/utils/clientShell', () => ({ clientShellRequestHeaders: () => ({ 'X-XCMAX-Client-Shell': 'enterprise' }) }))
afterEach(() => vi.unstubAllGlobals())
it('carries scope and decodes fragmented UTF-8 and CRLF', async () => {
  const bytes = new TextEncoder().encode('event: task.snapshot\r\ndata: ["任务"]\r\n\r\n')
  const fetchMock = vi.fn().mockResolvedValue(new Response(new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
    controller.close()
  } })))
  vi.stubGlobal('fetch', fetchMock)
  const stream = new AuthenticatedEventStream('/api/agent/tasks/events/stream')
  const seen = vi.fn()
  stream.addEventListener('task.snapshot', (event) => seen((event as MessageEvent).data))
  await vi.waitFor(() => expect(seen).toHaveBeenCalledWith('["任务"]'))
  expect(fetchMock).toHaveBeenCalledWith('/api/agent/tasks/events/stream', expect.objectContaining({ credentials: 'include', headers: expect.objectContaining({ 'X-XCAGI-Active-Mod-Id': 'mod-a', 'X-XCMAX-Client-Shell': 'enterprise' }) }))
  stream.close()
})
it('suppresses late snapshots and errors after close', async () => {
  let resolve!: (response: Response) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((r) => { resolve = r })))
  const stream = new AuthenticatedEventStream('/api/agent/tasks/events/stream')
  const seen = vi.fn()
  stream.addEventListener('task.snapshot', seen)
  stream.onerror = seen
  stream.close()
  resolve(new Response('event: task.snapshot\ndata: []\n\n'))
  await new Promise((r) => setTimeout(r, 10))
  expect(seen).not.toHaveBeenCalled()
})

it.each(['mod', 'user'] as const)('rejects late snapshots after %s changes', async (field) => {
  scopeState.mod = 'mod-a'
  scopeState.user = 'u1'
  let controller!: ReadableStreamDefaultController<Uint8Array>
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(new ReadableStream<Uint8Array>({ start(c) { controller = c } }))))
  const stream = new AuthenticatedEventStream('/api/agent/tasks/events/stream')
  const seen = vi.fn()
  const reconnect = vi.fn()
  stream.addEventListener('task.snapshot', seen)
  stream.onerror = reconnect
  await Promise.resolve()
  scopeState[field] = 'changed'
  controller.enqueue(new TextEncoder().encode('event: task.snapshot\ndata: ["old scope"]\n\n'))
  await vi.waitFor(() => expect(reconnect).toHaveBeenCalledTimes(1))
  expect(seen).not.toHaveBeenCalled()
  stream.close()
})
