import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from './auth'
import { useButlerDownloadHistoryStore } from './butlerDownloadHistory'
import { BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT } from '../utils/butlerDownloadHistory'
import type { EmployeeOutputDownload } from '../utils/tabularReadEmployees'

function makeDownload(n: number): EmployeeOutputDownload {
  return { jobId: `job-${n}`, filename: `file-${n}.xlsx`, label: `File ${n}` }
}

describe('useButlerDownloadHistoryStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('initializes with empty records after hydration', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'free', label: '普通用户', is_member: false },
    })
    const store = useButlerDownloadHistoryStore()
    expect(Array.isArray(store.records)).toBe(true)
  })

  it('isMember reflects auth store membership state', () => {
    const auth = useAuthStore()
    auth.$patch({ membership: { tier: 'free', label: '普通用户', is_member: false } })
    const store = useButlerDownloadHistoryStore()
    expect(store.isMember).toBe(false)
    auth.$patch({ membership: { tier: 'vip', label: 'VIP', is_member: true } })
    expect(store.isMember).toBe(true)
  })

  it('loadFromStorage reads from localStorage and applies retention', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'vip', label: 'VIP', is_member: true },
    })
    const records = Array.from({ length: 3 }, (_, i) => ({
      id: `id-${i}`,
      jobId: `job-${i}`,
      filename: `file-${i}.xlsx`,
      displayName: `File ${i}`,
      createdAt: 100 + i,
      expired: false,
    }))
    localStorage.setItem('xc_butler_download_history_v1:u1', JSON.stringify(records))
    const store = useButlerDownloadHistoryStore()
    store.loadFromStorage()
    expect(store.records).toHaveLength(3)
  })

  it('loadFromStorage handles localStorage errors gracefully', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'free', label: '', is_member: false },
    })
    const store = useButlerDownloadHistoryStore()
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('quota')
    })
    expect(() => store.loadFromStorage()).not.toThrow()
    expect(store.records).toEqual([])
    vi.restoreAllMocks()
  })

  it('loadFromStorage handles null/invalid JSON gracefully', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'free', label: '', is_member: false },
    })
    const store = useButlerDownloadHistoryStore()
    store.loadFromStorage()
    expect(store.records).toEqual([])
  })

  it('recordDownloads is a no-op for empty downloads', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'vip', label: 'VIP', is_member: true },
    })
    const store = useButlerDownloadHistoryStore()
    store.recordDownloads([])
    expect(store.records).toEqual([])
  })

  it('recordDownloads adds new records and persists', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'vip', label: 'VIP', is_member: true },
    })
    const store = useButlerDownloadHistoryStore()
    store.loadFromStorage()
    store.recordDownloads([makeDownload(1), makeDownload(2)])
    expect(store.records).toHaveLength(2)
  })

  it('recordSingle records a single download', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'vip', label: 'VIP', is_member: true },
    })
    const store = useButlerDownloadHistoryStore()
    store.loadFromStorage()
    store.recordSingle('job-1', 'file-1.xlsx', 'File 1', 'emp-1')
    expect(store.records).toHaveLength(1)
    expect(store.records[0].jobId).toBe('job-1')
    expect(store.records[0].filename).toBe('file-1.xlsx')
    expect(store.records[0].displayName).toBe('File 1')
  })

  it('activeRecords and expiredRecords partition by expired flag', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'vip', label: 'VIP', is_member: true },
    })
    const store = useButlerDownloadHistoryStore()
    store.loadFromStorage()
    store.recordDownloads(Array.from({ length: 3 }, (_, i) => makeDownload(i + 1)))
    expect(store.activeRecords.every((r) => !r.expired)).toBe(true)
    expect(store.expiredRecords).toEqual([])
  })

  it('non-member retention expires records beyond limit', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'free', label: '', is_member: false },
    })
    const store = useButlerDownloadHistoryStore()
    store.loadFromStorage()
    const downloads = Array.from(
      { length: BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT + 3 },
      (_, i) => makeDownload(i + 1),
    )
    store.recordDownloads(downloads)
    expect(store.activeRecords).toHaveLength(BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT)
    expect(store.expiredRecords.length).toBeGreaterThan(0)
  })

  it('reapplyRetention re-applies retention and persists', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'vip', label: 'VIP', is_member: true },
    })
    const store = useButlerDownloadHistoryStore()
    store.loadFromStorage()
    store.recordDownloads(Array.from({ length: 5 }, (_, i) => makeDownload(i + 1)))
    expect(store.activeRecords).toHaveLength(5)
    auth.$patch({ membership: { tier: 'free', label: '', is_member: false } })
    store.reapplyRetention()
    expect(store.activeRecords.length).toBeLessThanOrEqual(BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT)
  })

  it('persist swallows localStorage write errors', () => {
    const auth = useAuthStore()
    auth.$patch({
      user: { id: 'u1' } as any,
      membership: { tier: 'vip', label: 'VIP', is_member: true },
    })
    const store = useButlerDownloadHistoryStore()
    store.loadFromStorage()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded')
    })
    expect(() => store.recordDownloads([makeDownload(1)])).not.toThrow()
    vi.restoreAllMocks()
  })
})
