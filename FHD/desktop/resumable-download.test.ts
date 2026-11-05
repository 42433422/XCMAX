import { afterEach, describe, expect, it, vi } from 'vitest'
import { createHash, randomBytes } from 'node:crypto'
import { createServer, request as httpRequest, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import type { AddressInfo } from 'node:net'
import { PassThrough } from 'node:stream'

vi.mock('electron', () => ({
  app: { getPath: () => '/tmp' },
  net: { request: vi.fn() },
}))
vi.mock('electron-updater', () => ({ autoUpdater: {} }))

import { downloadResumable, type ResumableRequestFactory } from './resumable-download.js'

function nodeRequestFactory(): ResumableRequestFactory {
  return (url, headers, handlers) => {
    const request = httpRequest(url, { method: 'GET', headers }, response => {
      handlers.onResponse({
        statusCode: response.statusCode || 0,
        headers: response.headers,
        stream: response,
      })
    })
    request.on('error', handlers.onError)
    request.end()
    return request
  }
}

async function withServer(
  handler: (request: IncomingMessage, response: ServerResponse) => void,
  run: (baseUrl: string) => Promise<void>,
): Promise<void> {
  const server: Server = createServer(handler)
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address() as AddressInfo
  try {
    await run(`http://127.0.0.1:${port}`)
  } finally {
    await new Promise<void>(resolve => server.close(() => resolve()))
  }
}

const tmpDirs: string[] = []

afterEach(async () => {
  await Promise.all(tmpDirs.splice(0).map(dir => fs.rm(dir, { recursive: true, force: true })))
})

async function tempPaths(): Promise<{ destination: string; partFile: string }> {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'xcagi-resume-'))
  tmpDirs.push(dir)
  return {
    destination: path.join(dir, 'update.exe'),
    partFile: path.join(dir, 'update.exe.part'),
  }
}

function sha512(buffer: Buffer): string {
  return createHash('sha512').update(buffer).digest('base64')
}

describe('downloadResumable', () => {
  it('resumes from the received bytes after a mid-stream disconnect', async () => {
    const payload = randomBytes(300_000)
    const { destination, partFile } = await tempPaths()
    const ranges: string[] = []
    let interrupted: ServerResponse | undefined

    await withServer((request, response) => {
      const range = request.headers.range
      if (range) {
        ranges.push(range)
        const start = Number(/bytes=(\d+)-/.exec(range)?.[1] || 0)
        const chunk = payload.subarray(start)
        response.writeHead(206, {
          'content-length': String(chunk.length),
          'content-range': `bytes ${start}-${payload.length - 1}/${payload.length}`,
        })
        response.end(chunk)
        return
      }
      response.writeHead(200, { 'content-length': String(payload.length) })
      interrupted = response
      response.write(payload.subarray(0, 90_000))
    }, async baseUrl => {
      await downloadResumable({
        url: `${baseUrl}/XCAGI-Setup.exe`,
        destination,
        partFile,
        sha512: sha512(payload),
        attempts: 3,
        retryDelayMs: 10,
        onProgress: () => {
          interrupted?.destroy()
          interrupted = undefined
        },
        createRequest: nodeRequestFactory(),
      })
    })

    expect(ranges).toHaveLength(1)
    expect(ranges[0]).toMatch(/^bytes=\d+-$/)
    expect((await fs.readFile(destination)).equals(payload)).toBe(true)
    await expect(fs.stat(partFile)).rejects.toThrow()
  })

  it('flushes a received chunk when the stream fails before the file opens', async () => {
    const payload = randomBytes(100_000)
    const { destination, partFile } = await tempPaths()
    const ranges: string[] = []
    await downloadResumable({
      url: 'http://fixture/update.exe',
      destination,
      partFile,
      sha512: sha512(payload),
      attempts: 2,
      retryDelayMs: 0,
      createRequest: (_url, headers, handlers) => {
        const stream = new PassThrough()
        queueMicrotask(() => {
          const start = Number(/bytes=(\d+)-/.exec(headers.Range || '')?.[1] || 0)
          if (headers.Range) ranges.push(headers.Range)
          handlers.onResponse({
            statusCode: start ? 206 : 200,
            headers: {
              'content-length': String(payload.length - start),
              'content-range': `bytes ${start}-${payload.length - 1}/${payload.length}`,
            },
            stream,
          })
          if (start) {
            stream.end(payload.subarray(start))
          } else {
            stream.write(payload.subarray(0, 90_000))
            stream.destroy(new Error('disconnect before open'))
          }
        })
        return { abort: () => stream.destroy() }
      },
    })
    expect(ranges).toEqual(['bytes=90000-'])
    expect((await fs.readFile(destination)).equals(payload)).toBe(true)
  })

  it('reuses a completed part file without another network request', async () => {
    const payload = randomBytes(64_000)
    const { destination, partFile } = await tempPaths()
    await fs.writeFile(partFile, payload)

    await downloadResumable({
      url: 'http://127.0.0.1:1/unused.exe',
      destination,
      partFile,
      sha512: sha512(payload),
      attempts: 1,
      createRequest: () => {
        throw new Error('network should not be used')
      },
    })

    expect((await fs.readFile(destination)).equals(payload)).toBe(true)
  })

  it('discards a part file whose sha512 does not match and retries', async () => {
    const payload = randomBytes(32_000)
    const { destination, partFile } = await tempPaths()
    let requests = 0

    await withServer((_request, response) => {
      requests += 1
      response.writeHead(200, { 'content-length': String(payload.length) })
      response.end(payload)
    }, async baseUrl => {
      await expect(downloadResumable({
        url: `${baseUrl}/XCAGI-Setup.exe`,
        destination,
        partFile,
        sha512: sha512(randomBytes(16)),
        attempts: 2,
        retryDelayMs: 10,
        createRequest: nodeRequestFactory(),
      })).rejects.toThrow(/sha512/)
    })

    expect(requests).toBe(2)
    await expect(fs.stat(partFile)).rejects.toThrow()
  })
})
