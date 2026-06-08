import type { EmployeeOutputDownload } from './tabularReadEmployees'
import { displayNameForOfficeDownload } from './directGeneratedFiles'

/** 非会员可保留的「有效」下载记录条数；更早的标记为已过期。 */
export const BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT = 5

export type ButlerDownloadRecord = {
  id: string
  jobId: string
  filename: string
  displayName: string
  employeeId?: string
  createdAt: number
  expired: boolean
}

export const BUTLER_DOWNLOAD_STORAGE_KEY = 'xc_butler_download_history_v1'

function recordKey(jobId: string, filename: string): string {
  return `${jobId}:${filename}`
}

export function makeButlerDownloadId(jobId: string, filename: string, createdAt: number): string {
  return `${jobId}-${filename}-${createdAt}`.replace(/[^a-zA-Z0-9._-]+/g, '_')
}

/** 按会员策略标记过期：会员全部有效；普通用户仅保留最近 N 条有效。 */
export function applyButlerDownloadRetention(
  records: ButlerDownloadRecord[],
  isMember: boolean,
  activeLimit: number = BUTLER_DOWNLOAD_NON_MEMBER_ACTIVE_LIMIT,
): ButlerDownloadRecord[] {
  const sorted = [...records].sort((a, b) => b.createdAt - a.createdAt)
  if (isMember) {
    return sorted.map((r) => ({ ...r, expired: false }))
  }
  const limit = Math.max(1, activeLimit)
  return sorted.map((r, index) => ({
    ...r,
    expired: index >= limit,
  }))
}

export function mergeButlerDownloadRecord(
  existing: ButlerDownloadRecord[],
  entry: Omit<ButlerDownloadRecord, 'id' | 'expired'> & { id?: string },
  isMember: boolean,
): ButlerDownloadRecord[] {
  const key = recordKey(entry.jobId, entry.filename)
  const withoutDup = existing.filter((r) => recordKey(r.jobId, r.filename) !== key)
  const createdAt = entry.createdAt || Date.now()
  const id = entry.id || makeButlerDownloadId(entry.jobId, entry.filename, createdAt)
  const next: ButlerDownloadRecord = {
    id,
    jobId: entry.jobId,
    filename: entry.filename,
    displayName: entry.displayName,
    employeeId: entry.employeeId,
    createdAt,
    expired: false,
  }
  return applyButlerDownloadRetention([next, ...withoutDup], isMember)
}

export function downloadsToButlerRecords(
  downloads: EmployeeOutputDownload[],
  opts?: { employeeId?: string; createdAt?: number },
): Omit<ButlerDownloadRecord, 'id' | 'expired'>[] {
  const ts = opts?.createdAt ?? Date.now()
  return downloads
    .filter((d) => d?.jobId && d?.filename)
    .map((d) => ({
      jobId: d.jobId,
      filename: d.filename,
      displayName: displayNameForOfficeDownload(d),
      employeeId: opts?.employeeId,
      createdAt: ts,
    }))
}

export function parseButlerDownloadStorage(raw: string | null): ButlerDownloadRecord[] {
  if (!raw) return []
  try {
    const data = JSON.parse(raw) as unknown
    if (!Array.isArray(data)) return []
    const out: ButlerDownloadRecord[] = []
    for (const row of data) {
      if (!row || typeof row !== 'object') continue
      const r = row as Record<string, unknown>
      const jobId = String(r.jobId || '').trim()
      const filename = String(r.filename || '').trim()
      if (!jobId || !filename) continue
      out.push({
        id: String(r.id || makeButlerDownloadId(jobId, filename, Number(r.createdAt) || 0)),
        jobId,
        filename,
        displayName: String(r.displayName || filename),
        employeeId: r.employeeId ? String(r.employeeId) : undefined,
        createdAt: Number(r.createdAt) || 0,
        expired: Boolean(r.expired),
      })
    }
    return out
  } catch {
    return []
  }
}

export function serializeButlerDownloadStorage(records: ButlerDownloadRecord[]): string {
  return JSON.stringify(records)
}

export function storageKeyForUser(userId: string | number | null | undefined): string {
  const uid = userId == null || userId === '' ? 'guest' : String(userId)
  return `${BUTLER_DOWNLOAD_STORAGE_KEY}:${uid}`
}
