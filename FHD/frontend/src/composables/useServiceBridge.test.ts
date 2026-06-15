import { describe, it, expect, vi, beforeEach } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()

vi.mock('@/api', () => ({
  get: (...a: unknown[]) => get(...a),
  post: (...a: unknown[]) => post(...a),
  put: (...a: unknown[]) => put(...a),
}))

import {
  useServiceBridge,
  formatServiceBridgeTime,
  serviceBridgePriorityLabel,
  serviceBridgeStatusLabel,
} from './useServiceBridge'

describe('useServiceBridge helpers', () => {
  it('formatServiceBridgeTime handles empty, seconds and ms and invalid', () => {
    expect(formatServiceBridgeTime('')).toBe('')
    expect(formatServiceBridgeTime(0)).toBe('')
    expect(formatServiceBridgeTime(1_700_000_000)).not.toBe('')
    expect(formatServiceBridgeTime(1_700_000_000_000)).not.toBe('')
    expect(formatServiceBridgeTime('2026-01-01T00:00:00Z')).not.toBe('')
  })

  it('label helpers fall back to raw key', () => {
    expect(serviceBridgePriorityLabel('high')).toBe('高')
    expect(serviceBridgePriorityLabel('weird')).toBe('weird')
    expect(serviceBridgeStatusLabel('pending')).toBe('待受理')
    expect(serviceBridgeStatusLabel('weird')).toBe('weird')
  })
})

describe('useServiceBridge actions', () => {
  beforeEach(() => {
    get.mockReset()
    post.mockReset()
    put.mockReset()
  })

  it('loadRequests stores data and resets loading', async () => {
    get.mockResolvedValue({ data: [{ id: 1 }] })
    const b = useServiceBridge()
    await b.loadRequests({ status: 'pending' })
    expect(b.requests.value).toHaveLength(1)
    expect(b.loadingRequests.value).toBe(false)
  })

  it('loadRequests handles error to empty', async () => {
    get.mockRejectedValue(new Error('x'))
    const b = useServiceBridge()
    await b.loadRequests()
    expect(b.requests.value).toEqual([])
  })

  it('loadStats success and failure', async () => {
    get.mockResolvedValueOnce({ data: { total: 3, pending: 1, processing: 1, resolved: 1 } })
    const b = useServiceBridge()
    await b.loadStats()
    expect(b.stats.value?.total).toBe(3)
    get.mockRejectedValueOnce(new Error('x'))
    await b.loadStats()
    expect(b.stats.value).toBeNull()
  })

  it('loadInstances success and failure', async () => {
    get.mockResolvedValueOnce({ data: [{ instance_id: 'a' }] })
    const b = useServiceBridge()
    await b.loadInstances()
    expect(b.instances.value).toHaveLength(1)
    get.mockRejectedValueOnce(new Error('x'))
    await b.loadInstances()
    expect(b.instances.value).toEqual([])
  })

  it('createRequest posts and returns data', async () => {
    post.mockResolvedValue({ data: { id: 9 } })
    const b = useServiceBridge()
    const r = await b.createRequest({ source_instance_id: 'i', source_instance_name: 'n', title: 't' })
    expect(r?.id).toBe(9)
    expect(b.submitting.value).toBe(false)
  })

  it('createEnterpriseContact uses outbox when config has instance_id', async () => {
    get.mockResolvedValue({ data: { instance_id: 'remote' } })
    post.mockResolvedValue({ data: { id: 11 } })
    const b = useServiceBridge()
    const r = await b.createEnterpriseContact({ source_instance_id: 'i', source_instance_name: 'n', title: 't' })
    expect(r?.id).toBe(11)
    expect(post).toHaveBeenCalledWith('/api/service-bridge/outbox', expect.any(Object))
  })

  it('createEnterpriseContact falls back to direct write without config', async () => {
    get.mockRejectedValue(new Error('no config'))
    post.mockResolvedValue({ data: { id: 12 } })
    const b = useServiceBridge()
    const r = await b.createEnterpriseContact({ source_instance_id: 'i', source_instance_name: 'n', title: 't' })
    expect(r?.id).toBe(12)
    expect(post).toHaveBeenCalledWith('/api/service-bridge/requests', expect.any(Object))
  })

  it('respondToRequest puts payload', async () => {
    put.mockResolvedValue({ data: { id: 5, status: 'resolved' } })
    const b = useServiceBridge()
    const r = await b.respondToRequest(5, { response: 'ok', status: 'resolved' })
    expect(r?.status).toBe('resolved')
    expect(put).toHaveBeenCalledWith('/api/service-bridge/requests/5/respond', expect.any(Object))
  })
})
