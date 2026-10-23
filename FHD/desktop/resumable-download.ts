import { createHash } from 'node:crypto'
import { createReadStream, createWriteStream, type WriteStream } from 'node:fs'
import fs from 'node:fs/promises'
import path from 'node:path'
import { app, net } from 'electron'
import { autoUpdater } from 'electron-updater'

const MAX_ATTEMPTS = 8
const IDLE_TIMEOUT_MS = 60_000
const RETRY_BASE_DELAY_MS = 1_500

type ResponseHeaders = Record<string, string | string[] | undefined>

export interface ResumableRequestHandlers {
  onResponse: (response: {
    statusCode: number
    headers: ResponseHeaders
    stream: NodeJS.ReadableStream
  }) => void
  onError: (error: Error) => void
}

export interface ResumableRequest {
  abort: () => void
}

export type ResumableRequestFactory = (
  url: string,
  headers: Record<string, string>,
  handlers: ResumableRequestHandlers,
) => ResumableRequest

export interface ResumableProgress {
  percent: number
  transferred: number
  total: number
  bytesPerSecond: number
  delta: number
}

export interface ResumableDownloadOptions {
  url: string
  destination: string
  partFile: string
  sha512?: string
  headers?: Record<string, string | string[] | undefined>
  onProgress?: (progress: ResumableProgress) => void
  cancellationToken?: { onCancel: (listener: () => void) => { dispose: () => void } }
  createRequest: ResumableRequestFactory
  attempts?: number
  retryDelayMs?: number
}

function headerValue(headers: ResponseHeaders, name: string): string | undefined {
  const value = headers[name.toLowerCase()]
  if (Array.isArray(value)) {
    return value[0]
  }
  return value
}

async function fileSize(file: string): Promise<number> {
  try {
    return (await fs.stat(file)).size
  } catch {
    return 0
  }
}

async function fileSha512(file: string): Promise<string> {
  const hash = createHash('sha512')
  for await (const chunk of createReadStream(file)) {
    hash.update(chunk as Buffer)
  }
  return hash.digest('base64')
}

function totalSizeFromRange(value: string | undefined, start: number): number {
  const match = /^bytes\s+\d+-\d+\/(\d+)$/i.exec(value || '')
  if (match) {
    return Number(match[1])
  }
  return start
}

async function sleep(ms: number): Promise<void> {
  await new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * Download `url` into `destination` with HTTP Range resume.
 *
 * A stable `.part` file keeps the received bytes across retries and app restarts.
 * The completed file is verified against `sha512` (base64) before it is moved into place.
 */
export async function downloadResumable(options: ResumableDownloadOptions): Promise<void> {
  const attempts = Math.max(1, options.attempts ?? MAX_ATTEMPTS)
  await fs.mkdir(path.dirname(options.partFile), { recursive: true })
  let lastError: Error | null = null

  // A part file left over from an interrupted session may already be complete.
  if (options.sha512 && (await fileSize(options.partFile)) > 0) {
    if ((await fileSha512(options.partFile)) === options.sha512) {
      await fs.mkdir(path.dirname(options.destination), { recursive: true })
      await fs.rename(options.partFile, options.destination)
      return
    }
  }

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await downloadAttempt(options)
      if (options.sha512) {
        const actual = await fileSha512(options.partFile)
        if (actual !== options.sha512) {
          await fs.rm(options.partFile, { force: true })
          throw new Error('更新包 sha512 校验失败，已丢弃分片后重试')
        }
      }
      await fs.mkdir(path.dirname(options.destination), { recursive: true })
      await fs.rename(options.partFile, options.destination)
      return
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error))
      if (attempt < attempts) {
        await sleep((options.retryDelayMs ?? RETRY_BASE_DELAY_MS) * attempt)
      }
    }
  }

  throw lastError ?? new Error('更新包下载失败')
}

async function downloadAttempt(options: ResumableDownloadOptions): Promise<void> {
  const start = await fileSize(options.partFile)
  const headers: Record<string, string> = {}
  for (const [name, value] of Object.entries(options.headers || {})) {
    if (typeof value === 'string') {
      headers[name] = value
    } else if (Array.isArray(value) && value.length > 0) {
      headers[name] = value.join(', ')
    }
  }
  if (start > 0) {
    headers.Range = `bytes=${start}-`
  }

  await new Promise<void>((resolve, reject) => {
    let settled = false
    let idleTimer: ReturnType<typeof setTimeout> | null = null
    let request: ResumableRequest | null = null
    let writer: WriteStream | null = null
    let disposeCancellation: (() => void) | null = null

    const finish = (error?: Error) => {
      if (settled) {
        return
      }
      settled = true
      if (idleTimer) {
        clearTimeout(idleTimer)
      }
      disposeCancellation?.()
      if (error) {
        if (writer && !writer.destroyed) {
          // Flush the bytes already received so the next attempt can resume from them.
          writer.end(() => reject(error))
        } else {
          reject(error)
        }
        return
      }
      resolve()
    }

    const armIdleTimer = () => {
      if (idleTimer) {
        clearTimeout(idleTimer)
      }
      idleTimer = setTimeout(() => {
        request?.abort()
        finish(new Error('更新包下载超时'))
      }, IDLE_TIMEOUT_MS)
    }

    if (options.cancellationToken) {
      const disposable = options.cancellationToken.onCancel(() => {
        request?.abort()
        finish(new Error('更新下载已取消'))
      })
      disposeCancellation = () => disposable.dispose()
    }

    try {
      request = options.createRequest(options.url, headers, {
        onResponse: response => {
          if (settled) {
            ;(response.stream as { destroy?: () => void }).destroy?.()
            return
          }
          armIdleTimer()
          if (start > 0 && response.statusCode === 416) {
            // The part file is already complete; the caller verifies its hash below.
            response.stream.resume()
            response.stream.on('end', () => finish())
            return
          }
          if (response.statusCode >= 400) {
            response.stream.resume()
            finish(new Error(`更新包下载失败：HTTP ${response.statusCode}`))
            return
          }
          const resume = start > 0 && response.statusCode === 206
          const append = resume
          const total = resume
            ? totalSizeFromRange(headerValue(response.headers, 'content-range'), start)
            : start + Number(headerValue(response.headers, 'content-length') || 0)
          writer = createWriteStream(options.partFile, { flags: append ? 'a' : 'w' })
          const output = writer
          let transferred = append ? start : 0
          let lastTick = Date.now()
          let lastTransferred = transferred

          const report = () => {
            if (!options.onProgress) {
              return
            }
            const now = Date.now()
            const elapsed = Math.max(1, now - lastTick)
            const delta = transferred - lastTransferred
            lastTick = now
            lastTransferred = transferred
            options.onProgress({
              percent: total > 0 ? Math.min(100, (transferred / total) * 100) : 0,
              transferred,
              total,
              bytesPerSecond: Math.round((delta / elapsed) * 1000),
              delta,
            })
          }

          response.stream.on('data', (chunk: Buffer) => {
            armIdleTimer()
            transferred += chunk.length
            if (!output.write(chunk)) {
              response.stream.pause()
              output.once('drain', () => response.stream.resume())
            }
            report()
          })
          response.stream.on('end', () => {
            output.end(() => finish())
          })
          response.stream.on('error', (error: Error) => finish(error))
          output.on('error', (error: Error) => finish(error))
        },
        onError: error => finish(error),
      })
      armIdleTimer()
    } catch (error) {
      finish(error instanceof Error ? error : new Error(String(error)))
    }
  })
}

function electronRequestFactory(): ResumableRequestFactory {
  return (url, headers, handlers) => {
    const request = net.request({
      url,
      method: 'GET',
      session: autoUpdater.netSession,
      headers,
    })
    request.on('response', response => {
      handlers.onResponse({
        statusCode: response.statusCode,
        headers: response.headers as ResponseHeaders,
        stream: response as unknown as NodeJS.ReadableStream,
      })
    })
    request.on('error', error => handlers.onError(error))
    return request
  }
}

/**
 * Route Electron-updater's full installer downloads through Range resume.
 * Falls back to the original executor for non-Windows targets or non-installer files.
 */
export function installResumableUpdaterDownload(): boolean {
  const updater = autoUpdater as unknown as {
    httpExecutor?: { download: (...args: unknown[]) => Promise<string>; __xcmaxResumable?: boolean }
  }
  const executor = updater.httpExecutor
  if (!executor || executor.__xcmaxResumable) {
    return false
  }

  const original = executor.download.bind(executor)
  executor.download = async (url: unknown, destination: unknown, options: unknown) => {
    const urlText = String(url)
    if (process.platform !== 'win32' || !/\.exe(?:$|\?)/i.test(urlText)) {
      return original(url, destination, options)
    }
    const downloadOptions = (options || {}) as {
      sha512?: string
      headers?: Record<string, string | string[] | undefined>
      onProgress?: (progress: ResumableProgress) => void
      cancellationToken?: { onCancel: (listener: () => void) => { dispose: () => void } }
    }
    const sha512 = String(downloadOptions.sha512 || '')
    const partName = sha512.slice(0, 24).replace(/[^A-Za-z0-9]/g, '') || 'installer'
    await downloadResumable({
      url: urlText,
      destination: String(destination),
      partFile: path.join(app.getPath('userData'), 'update-cache', `${partName}.part`),
      sha512,
      headers: downloadOptions.headers,
      onProgress: downloadOptions.onProgress,
      cancellationToken: downloadOptions.cancellationToken,
      createRequest: electronRequestFactory(),
    })
    return String(destination)
  }
  executor.__xcmaxResumable = true
  return true
}
