import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const state = vi.hoisted(() => {
  const holder = { userDataDir: '/tmp/xcagi-update-receipt-default' }
  return {
    holder,
    app: { getPath: vi.fn(() => holder.userDataDir) },
  }
})

vi.mock('electron', () => ({ app: state.app }))

import {
  readPendingUpdateInstallReceipt,
  reportPendingUpdateInstallation,
  stageUpdateInstallReceipt,
} from './update-install-receipts'

describe('update installation receipts', () => {
  let root: string

  beforeEach(() => {
    root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-update-receipt-'))
    state.holder.userDataDir = path.join(root, 'userData')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    fs.rmSync(root, { recursive: true, force: true })
  })

  it('reports the installed build and only then removes the durable marker', async () => {
    const pending = stageUpdateInstallReceipt({
      targetVersion: '1.0.0.1',
      targetBuildSha: 'expected-sha',
    })
    expect(readPendingUpdateInstallReceipt()?.idempotencyKey).toBe(pending.idempotencyKey)
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      expect(body.status).toBe('installed')
      expect(body.target_build_sha).toBe('expected-sha')
      expect(body.installed_build_sha).toBe('expected-sha')
      return new Response('{"ok":true}', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(reportPendingUpdateInstallation({
      backendPort: 17600,
      installedVersion: '1.0.0.1',
      installedBuildSha: 'expected-sha',
    })).resolves.toEqual({ reported: true, status: 'installed' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(readPendingUpdateInstallReceipt()).toBeNull()
  })

  it('keeps the marker for retry when the receipt endpoint fails', async () => {
    stageUpdateInstallReceipt({ targetVersion: '1.0.0.1', targetBuildSha: 'expected-sha' })
    vi.stubGlobal('fetch', vi.fn(async () => new Response('offline', { status: 503 })))

    await expect(reportPendingUpdateInstallation({
      backendPort: 17600,
      installedVersion: '1.0.0.0',
      installedBuildSha: 'wrong-sha',
    })).rejects.toThrow('HTTP 503')
    expect(readPendingUpdateInstallReceipt()).not.toBeNull()
  })

  it('bootstraps the first installed-build receipt when the old updater left no marker', async () => {
    const bodies: Record<string, unknown>[] = []
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      bodies.push(JSON.parse(String(init.body)))
      return new Response('{"ok":true}', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(reportPendingUpdateInstallation({
      backendPort: 17600,
      installedVersion: '1.0.0.1',
      installedBuildSha: 'first-receipt-build',
    })).resolves.toEqual({ reported: true, status: 'installed' })
    await expect(reportPendingUpdateInstallation({
      backendPort: 17600,
      installedVersion: '1.0.0.1',
      installedBuildSha: 'first-receipt-build',
    })).resolves.toEqual({ reported: false, reason: 'no_pending_receipt' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(bodies[0]).toMatchObject({
      source: 'desktop_inventory',
      target_version: '1.0.0.1',
      target_build_sha: 'first-receipt-build',
      installed_build_sha: 'first-receipt-build',
      status: 'installed',
    })
  })

  it('keeps one deterministic bootstrap outbox for retry', async () => {
    const idempotencyKeys: string[] = []
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body))
      idempotencyKeys.push(body.idempotency_key)
      return new Response(idempotencyKeys.length === 1 ? 'offline' : '{"ok":true}', {
        status: idempotencyKeys.length === 1 ? 503 : 200,
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const input = {
      backendPort: 17600,
      installedVersion: '1.0.0.1',
      installedBuildSha: 'retry-build',
    }
    await expect(reportPendingUpdateInstallation(input)).rejects.toThrow('HTTP 503')
    expect(readPendingUpdateInstallReceipt()?.source).toBe('desktop_inventory')
    await expect(reportPendingUpdateInstallation(input)).resolves.toEqual({
      reported: true,
      status: 'installed',
    })
    expect(idempotencyKeys[0]).toBe(idempotencyKeys[1])
  })
})
