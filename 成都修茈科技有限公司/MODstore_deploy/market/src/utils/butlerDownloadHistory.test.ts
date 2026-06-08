import { describe, expect, it } from 'vitest'
import {
  applyButlerDownloadRetention,
  BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT,
  mergeButlerDownloadRecord,
  parseButlerDownloadStorage,
  serializeButlerDownloadStorage,
} from './butlerDownloadHistory'

function row(n: number, createdAt: number) {
  return {
    id: `id-${n}`,
    jobId: `job-${n}`,
    filename: `file-${n}.xlsx`,
    displayName: `File ${n}`,
    createdAt,
    expired: false,
  }
}

describe('butlerDownloadHistory retention', () => {
  it('keeps all active for members', () => {
    const records = [row(1, 300), row(2, 200), row(3, 100)]
    const out = applyButlerDownloadRetention(records, true)
    expect(out.every((r) => !r.expired)).toBe(true)
    expect(out).toHaveLength(3)
  })

  it('expires beyond limit for non-members', () => {
    const records = Array.from({ length: 7 }, (_, i) => row(i + 1, 700 - i * 10))
    const out = applyButlerDownloadRetention(records, false)
    expect(out.filter((r) => !r.expired)).toHaveLength(BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT)
    expect(out.filter((r) => r.expired)).toHaveLength(7 - BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT)
    expect(out[0].jobId).toBe('job-1')
    expect(out[BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT].expired).toBe(true)
  })

  it('merge dedupes by jobId+filename and re-applies retention', () => {
    const base = applyButlerDownloadRetention(
      Array.from({ length: 5 }, (_, i) => row(i + 1, 500 - i)),
      false,
    )
    const merged = mergeButlerDownloadRecord(
      base,
      {
        jobId: 'job-1',
        filename: 'file-1.xlsx',
        displayName: 'File 1 again',
        createdAt: 999,
      },
      false,
    )
    expect(merged.filter((r) => r.jobId === 'job-1' && r.filename === 'file-1.xlsx')).toHaveLength(1)
    expect(merged[0].createdAt).toBe(999)
    expect(merged.filter((r) => !r.expired)).toHaveLength(BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT)
  })

  it('round-trips storage json', () => {
    const records = applyButlerDownloadRetention([row(1, 100), row(2, 50)], false)
    const raw = serializeButlerDownloadStorage(records)
    const parsed = parseButlerDownloadStorage(raw)
    expect(parsed).toHaveLength(2)
    expect(parsed[0].jobId).toBe('job-1')
  })
})
