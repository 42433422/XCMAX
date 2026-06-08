/**
 * LLM 流式调用包装。
 *
 * 优先读取后端 /api/llm/chat/stream 的 text/event-stream。
 * 若后端未部署该路由或浏览器不支持 ReadableStream，则回退到 /api/llm/chat + 打字机回放。
 *
 * 调用约定：
 * - request 由调用方传入（保持解耦），返回最终全文
 * - 通过 onToken(chunk) 不断把增量内容回传给 UI
 * - 通过 AbortController 控制取消；取消时 onAbort 被调用，最终错误归一为 AbortError
 */

import { api } from '../api'
import { refreshLevelAndWalletAfterLlm } from './llmBillingRefresh'

export interface StreamHandle {
  abort: () => void
  done: Promise<{ content: string; aborted: boolean }>
}

export type LlmMessageContent = string | Array<{ type: string; text?: string; image_url?: { url: string } }>

export interface StreamOptions {
  provider: string
  model: string
  messages: Array<{ role: string; content: LlmMessageContent }>
  maxTokens?: number | null
  conversationId?: number | null
  onToken: (delta: string, soFar: string) => void
  onError?: (e: Error) => void
  onDone?: (full: string, aborted: boolean) => void
  /** 每个 token 之间的播放间隔（ms），用于打字机感受；默认 14ms */
  intervalMs?: number
}

function parseStreamHttpError(body: string, status: number): string {
  const fallback = body.trim() || `流式接口不可用（HTTP ${status}）`
  if (!body.trim()) return fallback
  try {
    const data = JSON.parse(body)
    const d = data?.detail
    if (typeof d === 'string' && d.trim()) {
      if (status === 401 || d.includes('登录')) return '登录已过期，请重新登录'
      return d.trim()
    }
    if (typeof data?.message === 'string' && data.message.trim()) return data.message.trim()
  } catch {
    /* raw text */
  }
  if (status === 401 || fallback.includes('登录')) return '登录已过期，请重新登录'
  return fallback
}

export function streamLLMChat(opts: StreamOptions): StreamHandle {
  const ctrl = new AbortController()
  let aborted = false
  let timer: ReturnType<typeof setInterval> | null = null

  const runFallback = async () => {
    let fullText = ''
    const res: any = await api.llmChat(
      opts.provider,
      opts.model,
      opts.messages as unknown[],
      opts.maxTokens ?? null,
      opts.conversationId ?? null,
    )
    if (ctrl.signal.aborted) {
      aborted = true
      opts.onDone?.('', true)
      return { content: '', aborted: true }
    }
    fullText = String(res?.content || '').trim()
    if (!fullText) fullText = '（无回复）'

    return await new Promise<{ content: string; aborted: boolean }>((resolve) => {
      let cursor = 0
      const interval = Math.max(2, Math.min(60, Number(opts.intervalMs ?? 14)))
      const charsPerTick = fullText.length > 1200 ? 6 : fullText.length > 300 ? 3 : 1

      const finish = () => {
        if (timer) {
          clearInterval(timer)
          timer = null
        }
        opts.onDone?.(fullText, aborted)
        resolve({ content: fullText, aborted })
      }

      timer = setInterval(() => {
        if (ctrl.signal.aborted) {
          aborted = true
          finish()
          return
        }
        const next = Math.min(fullText.length, cursor + charsPerTick)
        const delta = fullText.slice(cursor, next)
        cursor = next
        if (delta) opts.onToken(delta, fullText.slice(0, cursor))
        if (cursor >= fullText.length) finish()
      }, interval)
    })
  }

  const parseSseChunk = (chunk: string, onEvent: (event: string, data: any) => void) => {
    const lines = chunk.split(/\r?\n/)
    let event = 'message'
    const dataLines: string[] = []
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim() || 'message'
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    }
    if (!dataLines.length) return
    const raw = dataLines.join('\n')
    try {
      onEvent(event, JSON.parse(raw))
    } catch {
      onEvent(event, raw)
    }
  }

  const runSse = async (): Promise<{ content: string; aborted: boolean }> => {
    const res: Response = await api.llmChatStream(
      opts.provider,
      opts.model,
      opts.messages as unknown[],
      opts.maxTokens ?? null,
      opts.conversationId ?? null,
      ctrl.signal,
    )
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => '')
      throw new Error(parseStreamHttpError(text, res.status))
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let fullText = ''
    let sawDelta = false
    let completed = false
    let billedThisStream = false

    const onEvent = (event: string, data: any) => {
      if (event === 'meta' && data && data.billed === true) {
        billedThisStream = true
        return
      }
      if (event === 'delta') {
        const delta = String(data?.delta || '')
        if (!delta) return
        sawDelta = true
        fullText += delta
        opts.onToken(delta, fullText)
        return
      }
      if (event === 'done') {
        if (data && (data.billed === true || (Number(data.charge_amount) || 0) > 0)) billedThisStream = true
        const final = String(data?.content || fullText || '').trim()
        if (final && final !== fullText) {
          const delta = final.slice(fullText.length)
          fullText = final
          if (delta) opts.onToken(delta, fullText)
        }
        completed = true
        return
      }
      if (event === 'error') {
        throw new Error(String(data?.error || data || '流式生成失败'))
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (ctrl.signal.aborted) {
        aborted = true
        break
      }
      buffer += decoder.decode(value, { stream: true })
      buffer = buffer.replace(/\r\n/g, '\n')
      let idx = buffer.indexOf('\n\n')
      while (idx >= 0) {
        const frame = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        if (frame.trim()) parseSseChunk(frame, onEvent)
        idx = buffer.indexOf('\n\n')
      }
    }
    if (buffer.trim()) parseSseChunk(buffer, onEvent)
    if (ctrl.signal.aborted) aborted = true
    if (!completed && !sawDelta && !aborted) {
      throw new Error('流式接口没有返回内容')
    }
    if (!aborted && billedThisStream) refreshLevelAndWalletAfterLlm()
    opts.onDone?.(fullText || '（无回复）', aborted)
    return { content: fullText || '（无回复）', aborted }
  }

  const done = (async () => {
    try {
      return await runSse()
    } catch (e: any) {
      if (ctrl.signal.aborted) {
        opts.onDone?.('', true)
        return { content: '', aborted: true }
      }
      try {
        return await runFallback()
      } catch (fallbackErr: any) {
        if (ctrl.signal.aborted) {
          opts.onDone?.('', true)
          return { content: '', aborted: true }
        }
        const err = fallbackErr instanceof Error ? fallbackErr : new Error(String(fallbackErr?.message || fallbackErr || e))
        opts.onError?.(err)
        throw err
      }
    }
  })()

  return {
    abort: () => {
      aborted = true
      ctrl.abort()
      if (timer) {
        clearInterval(timer)
        timer = null
      }
    },
    done,
  }
}
