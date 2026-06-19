export type CaptureBackend = 'html2canvas' | 'dom-snapshot'

export type CaptureFailureReason =
  | 'aborted'
  | 'cors'
  | 'memory'
  | 'no_backend'
  | 'render'
  | 'timeout'
  | 'unsupported'

export type CaptureSeverity = 'critical' | 'degraded' | 'user'

export interface CaptureOptions {
  autoTextFallback?: boolean
  backend?: CaptureBackend | string
  cacheTtlMs?: number
  enableCache?: boolean
  forceRetake?: boolean
  ignoreSelectors?: string[]
  noteMaxLen?: number
  onCaptureMeta?: CaptureMetaListener
  quality?: number
  retry?: number
  routeSig?: string
  scale?: number
  signal?: AbortSignal
}

export interface CaptureSuccess {
  backend: CaptureBackend
  bytes: number
  dataUrl: string
  elapsedMs: number
  fromCache?: boolean
  kind: 'image' | 'text-snapshot'
  ok: true
}

export interface CaptureFailure {
  backend: CaptureBackend | string
  elapsedMs: number
  fromCache?: boolean
  message: string
  noteOriginalLength?: number
  noteTruncated?: boolean
  ok: false
  reason: CaptureFailureReason | string
  severity: CaptureSeverity
  textFallback?: string
}

export type CaptureResult = CaptureSuccess | CaptureFailure

export interface CaptureMeta {
  backend: CaptureBackend | string
  elapsedMs: number
  fromCache?: boolean
}

export type CaptureMetaListener = (result: CaptureResult, meta: CaptureMeta) => void

const captureCache = new Map<string, { result: CaptureResult; ts: number }>()
const captureMetaListeners = new Set<CaptureMetaListener>()

export function _clearCaptureCache(): void {
  captureCache.clear()
}

export function invalidateCaptureCache(): void {
  captureCache.clear()
}

export function onCaptureMeta(listener: CaptureMetaListener | null): () => void {
  if (!listener) {
    captureMetaListeners.clear()
    return () => undefined
  }

  captureMetaListeners.add(listener)
  return () => {
    captureMetaListeners.delete(listener)
  }
}

function now(): number {
  return Date.now()
}

function elapsedSince(startedAt: number): number {
  return Math.max(0, now() - startedAt)
}

function getViewportCacheKey(backend: string, routeSig?: string): string {
  const route = routeSig || globalThis.location?.pathname || 'unknown-route'
  const width = globalThis.innerWidth || 0
  const height = globalThis.innerHeight || 0
  return `${backend}:${route}:${width}x${height}`
}

function emitCaptureMeta(result: CaptureResult, options: CaptureOptions): void {
  const meta: CaptureMeta = {
    backend: result.backend,
    elapsedMs: result.elapsedMs,
    fromCache: result.fromCache,
  }

  for (const listener of captureMetaListeners) {
    try {
      listener(result, meta)
    } catch {
      // telemetry listeners must not break capture
    }
  }

  if (options.onCaptureMeta) {
    try {
      options.onCaptureMeta(result, meta)
    } catch {
      // per-call telemetry listeners must not break capture
    }
  }
}

function cloneCachedResult(result: CaptureResult): CaptureResult {
  return { ...result, fromCache: true } as CaptureResult
}

function cacheResult(cacheKey: string, result: CaptureResult, options: CaptureOptions): CaptureResult {
  if (options.enableCache !== false) {
    captureCache.set(cacheKey, { result, ts: now() })
  }
  return result
}

function bodyText(): string {
  const body = globalThis.document?.body
  return (body?.innerText || body?.textContent || '').trim()
}

function appendTextFallback(failure: CaptureFailure, options: CaptureOptions): CaptureFailure {
  if (options.autoTextFallback === false) return failure

  const text = bodyText()
  if (!text) return failure

  const next: CaptureFailure = {
    ...failure,
    severity: failure.reason === 'aborted' ? 'user' : 'degraded',
  }
  const maxLen = options.noteMaxLen
  if (maxLen && maxLen > 0 && text.length > maxLen) {
    next.textFallback = text.slice(0, maxLen)
    next.noteTruncated = true
    next.noteOriginalLength = text.length
  } else {
    next.textFallback = text
    next.noteOriginalLength = text.length
  }
  return next
}

function classifyError(error: unknown): CaptureFailureReason {
  const message = error instanceof Error ? error.message : String(error || '')
  if (/abort|aborted/i.test(message)) return 'aborted'
  if (/security|tainted|cors/i.test(message)) return 'cors'
  if (/memory/i.test(message)) return 'memory'
  if (/timeout/i.test(message)) return 'timeout'
  return 'render'
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message
  const message = String(error || '')
  return message || fallback
}

function bytesFromDataUrl(dataUrl: string): number {
  const base64 = dataUrl.split(',')[1] || ''
  if (!base64) return dataUrl.length
  try {
    return globalThis.atob ? globalThis.atob(base64).length : base64.length
  } catch {
    return base64.length
  }
}

function encodeUtf8Base64(value: string): string {
  const encoded = encodeURIComponent(value).replace(/%([0-9A-F]{2})/g, (_, hex) =>
    String.fromCharCode(Number.parseInt(hex, 16)),
  )
  return globalThis.btoa ? globalThis.btoa(encoded) : encoded
}

function makeFailure(
  backend: CaptureBackend | string,
  reason: CaptureFailureReason | string,
  message: string,
  startedAt: number,
  options: CaptureOptions,
): CaptureFailure {
  const severity: CaptureSeverity = reason === 'aborted' ? 'user' : 'critical'
  return appendTextFallback(
    {
      backend,
      elapsedMs: elapsedSince(startedAt),
      message,
      ok: false,
      reason,
      severity,
    },
    options,
  )
}

async function captureDomSnapshot(startedAt: number, options: CaptureOptions): Promise<CaptureResult> {
  if (!globalThis.document?.body) {
    return makeFailure('dom-snapshot', 'unsupported', 'document.body is unavailable', startedAt, options)
  }

  const payload = {
    capturedAt: new Date().toISOString(),
    kind: 'dom-snapshot',
    route: options.routeSig || globalThis.location?.pathname || '',
    text: bodyText(),
    title: globalThis.document.title || '',
    url: globalThis.location?.href || '',
  }
  const base64 = encodeUtf8Base64(JSON.stringify(payload))
  const dataUrl = `data:application/json;base64,${base64}`

  return {
    backend: 'dom-snapshot',
    bytes: bytesFromDataUrl(dataUrl),
    dataUrl,
    elapsedMs: elapsedSince(startedAt),
    kind: 'text-snapshot',
    ok: true,
  }
}

function shouldIgnoreElement(element: Element, selectors: string[]): boolean {
  if (element.classList?.contains('butler-float-root')) return true

  for (const selector of selectors) {
    try {
      if (element.matches(selector)) return true
    } catch {
      // Ignore invalid consumer selectors.
    }
  }
  return false
}

async function captureWithHtml2Canvas(startedAt: number, options: CaptureOptions): Promise<CaptureResult> {
  if (!globalThis.document?.body) {
    return makeFailure('html2canvas', 'unsupported', 'document.body is unavailable', startedAt, options)
  }

  const retries = Math.max(0, options.retry || 0)
  let lastFailure: CaptureFailure | null = null

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    if (options.signal?.aborted) {
      return makeFailure('html2canvas', 'aborted', 'capture aborted', startedAt, options)
    }

    try {
      const module = await import('html2canvas')
      const html2canvas = module.default
      const canvas = await html2canvas(globalThis.document.body, {
        ignoreElements: (element: Element) => shouldIgnoreElement(element, options.ignoreSelectors || []),
        logging: false,
        scale: options.scale ?? 0.5,
        useCORS: true,
      })

      if (options.signal?.aborted) {
        return makeFailure('html2canvas', 'aborted', 'capture aborted', startedAt, options)
      }

      const dataUrl = canvas.toDataURL('image/jpeg', options.quality ?? 0.7)
      if (!dataUrl) {
        return makeFailure('html2canvas', 'render', 'canvas export returned empty data', startedAt, options)
      }

      return {
        backend: 'html2canvas',
        bytes: bytesFromDataUrl(dataUrl),
        dataUrl,
        elapsedMs: elapsedSince(startedAt),
        kind: 'image',
        ok: true,
      }
    } catch (error) {
      const reason = classifyError(error)
      lastFailure = makeFailure('html2canvas', reason, errorMessage(error, 'capture failed'), startedAt, options)
      if (reason !== 'cors' || attempt >= retries) break
    }
  }

  return lastFailure || makeFailure('html2canvas', 'render', 'capture failed', startedAt, options)
}

export async function captureViewport(options: CaptureOptions = {}): Promise<CaptureResult> {
  const startedAt = now()
  const backend = options.backend || 'html2canvas'
  const cacheKey = getViewportCacheKey(String(backend), options.routeSig)
  const cacheTtlMs = options.cacheTtlMs ?? 5_000

  if (options.enableCache !== false && !options.forceRetake) {
    const cached = captureCache.get(cacheKey)
    if (cached && now() - cached.ts <= cacheTtlMs) {
      const result = cloneCachedResult(cached.result)
      emitCaptureMeta(result, options)
      return result
    }
  }

  let result: CaptureResult
  if (options.signal?.aborted) {
    result = makeFailure(String(backend), 'aborted', 'capture aborted', startedAt, options)
  } else if (backend === 'dom-snapshot') {
    result = await captureDomSnapshot(startedAt, options)
  } else if (backend === 'html2canvas') {
    result = await captureWithHtml2Canvas(startedAt, options)
  } else {
    result = makeFailure(String(backend), 'no_backend', `unsupported capture backend: ${backend}`, startedAt, options)
  }

  result = cacheResult(cacheKey, result, options)
  emitCaptureMeta(result, options)
  return result
}
