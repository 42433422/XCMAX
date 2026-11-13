import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import { getActiveExtensionModHeaders } from '@/utils/apiBase'
import { clientShellRequestHeaders } from '@/utils/clientShell'
import { createTraceId, sseConnections } from '@/utils/networkStability'

/**
 * Credentialed SSE transport.
 *
 * Browsers allow only a handful of concurrent HTTP/1.1 connections per origin;
 * several components subscribe to the task stream, so each URL+scope shares one
 * physical connection and fans events out to every subscriber. Reconnection
 * belongs to the owning view/store.
 */
export class AuthenticatedEventStream extends EventTarget {
  onerror: (() => void) | null = null
  private hub: StreamHub | null

  constructor(url: string) {
    super()
    this.hub = acquireHub(url)
    this.hub.attach(this)
  }

  close(): void {
    const hub = this.hub
    this.hub = null
    hub?.detach(this)
  }

  /** @internal fan-out hooks used by the shared hub. */
  emit(type: string, init: EventInit & { detail?: unknown }): void {
    if (type === 'stream.unauthorized') {
      this.dispatchEvent(new CustomEvent(type, { detail: init.detail }))
      return
    }
    this.dispatchEvent(new MessageEvent(type, init as MessageEventInit))
  }

  /** @internal */
  notifyError(): void {
    this.onerror?.()
  }
}

class StreamHub {
  readonly connId = createTraceId()
  private controller = new AbortController()
  private owners = new Set<AuthenticatedEventStream>()
  private finished = false
  private readonly initialScope: string

  constructor(readonly url: string) {
    this.initialScope = scopeOf(url)
    sseConnections.open(this.connId)
    void this.read()
  }

  get active(): boolean {
    return !this.finished && !this.controller.signal.aborted
  }

  attach(owner: AuthenticatedEventStream): void {
    this.owners.add(owner)
  }

  detach(owner: AuthenticatedEventStream): void {
    this.owners.delete(owner)
    if (!this.owners.size) this.terminate(false)
  }

  private emit(type: string, init: EventInit): void {
    for (const owner of [...this.owners]) owner.emit(type, init)
  }

  private terminate(notifyOwners: boolean): void {
    if (!this.finished) {
      this.finished = true
      this.controller.abort()
      sseConnections.close(this.connId)
      releaseHub(this)
    }
    if (notifyOwners) {
      for (const owner of [...this.owners]) owner.notifyError()
    }
  }

  private async read(): Promise<void> {
    const scopeMatches = () => scopeOf(this.url) === this.initialScope
    try {
      const response = await fetch(this.url, {
        credentials: 'include',
        headers: {
          Accept: 'text/event-stream',
          'X-Request-ID': this.connId,
          ...clientShellRequestHeaders(),
          ...getActiveExtensionModHeaders(this.url),
        },
        signal: this.controller.signal,
      })
      if (response.status === 401 || response.status === 403) {
        this.emit('stream.unauthorized', { detail: response.status } as EventInit)
        this.terminate(false)
        return
      }
      if (!response.ok || !response.body) throw new Error('Task stream unavailable')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let event = 'message'
      let data: string[] = []
      try {
        while (!this.controller.signal.aborted) {
          const chunk = await reader.read()
          if (this.controller.signal.aborted || !scopeMatches() || chunk.done) break
          buffer += decoder.decode(chunk.value, { stream: true })
          let newline: number
          while ((newline = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, newline).replace(/\r$/, '')
            buffer = buffer.slice(newline + 1)
            if (!line) {
              if (data.length && !this.controller.signal.aborted && scopeMatches()) {
                this.emit(event, { data: data.join('\n') })
              }
              event = 'message'
              data = []
            } else if (line.startsWith('event:')) event = line.slice(6).replace(/^ /, '')
            else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
          }
        }
      } finally {
        await reader.cancel().catch(() => undefined)
        reader.releaseLock()
      }
      if (this.controller.signal.aborted) return
      this.terminate(true)
    } catch {
      if (!this.controller.signal.aborted) this.terminate(true)
    }
  }
}

const hubs = new Map<string, StreamHub>()

function scopeOf(url: string): string {
  return JSON.stringify([
    getRuntimeTenantStorageScopeInput(),
    clientShellRequestHeaders(),
    getActiveExtensionModHeaders(url),
  ])
}

function acquireHub(url: string): StreamHub {
  const key = `${url}\n${scopeOf(url)}`
  const existing = hubs.get(key)
  if (existing?.active) return existing
  const hub = new StreamHub(url)
  hubs.set(key, hub)
  return hub
}

function releaseHub(hub: StreamHub): void {
  for (const [key, value] of hubs) {
    if (value === hub) hubs.delete(key)
  }
}
