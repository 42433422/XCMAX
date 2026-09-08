import { getActiveExtensionModHeaders } from '@/utils/apiBase'
import { clientShellRequestHeaders } from '@/utils/clientShell'

/** Credentialed SSE transport. Reconnection belongs to the owning view/store. */
export class AuthenticatedEventStream extends EventTarget {
  onerror: (() => void) | null = null
  private controller = new AbortController()

  constructor(url: string) {
    super()
    void this.read(url)
  }

  close(): void {
    this.controller.abort()
  }

  private async read(url: string): Promise<void> {
    try {
      const response = await fetch(url, {
        credentials: 'include',
        headers: { Accept: 'text/event-stream', ...clientShellRequestHeaders(), ...getActiveExtensionModHeaders(url) },
        signal: this.controller.signal,
      })
      if (!response.ok || !response.body) throw new Error('Task stream unavailable')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let event = 'message'
      let data: string[] = []
      try {
        while (!this.controller.signal.aborted) {
          const chunk = await reader.read()
          if (chunk.done) break
          buffer += decoder.decode(chunk.value, { stream: true })
          let newline: number
          while ((newline = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, newline).replace(/\r$/, '')
            buffer = buffer.slice(newline + 1)
            if (!line) {
              if (data.length && !this.controller.signal.aborted) {
                this.dispatchEvent(new MessageEvent(event, { data: data.join('\n') }))
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
      if (!this.controller.signal.aborted) this.onerror?.()
    } catch {
      if (!this.controller.signal.aborted) this.onerror?.()
    }
  }
}
