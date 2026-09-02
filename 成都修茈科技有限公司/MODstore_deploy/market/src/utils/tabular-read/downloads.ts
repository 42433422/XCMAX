/** 可下载产出解析与特定文件挑选（原 tabularReadEmployees 单体拆分） */
import { normalizeEmployeeExecuteEnvelope } from './envelope'

export function pickDocumentFullJsonDownload(items: EmployeeOutputDownload[]): EmployeeOutputDownload | undefined {
  return items.find(
    (d) => d.filename === 'document_full.json' || d.filename.endsWith('/document_full.json') || d.filename.includes('document_full.json'),
  )
}

export function pickPresentationFullJsonDownload(items: EmployeeOutputDownload[]): EmployeeOutputDownload | undefined {
  return items.find(
    (d) =>
      d.filename === 'presentation_full.json' ||
      d.filename.endsWith('/presentation_full.json') ||
      d.filename.includes('presentation_full.json'),
  )
}

export function pickQuantitativeReportDownload(items: EmployeeOutputDownload[]): EmployeeOutputDownload | undefined {
  return items.find(
    (d) =>
      d.filename === 'quantitative_report.html' ||
      d.filename.endsWith('/quantitative_report.html') ||
      d.filename.includes('quantitative_report.html'),
  )
}

export type EmployeeOutputDownload = { jobId: string; filename: string; label?: string }

type DownloadRow = {
  job_id?: string
  jobId?: string
  filename?: string
  name?: string
  file?: string
  path?: string
  label?: string
  files?: unknown[]
}

function pushParsedDownload(out: EmployeeOutputDownload[], seen: Set<string>, jobId: string, filename: string, label?: string) {
  const jid = jobId.trim()
  const fn = filename.trim()
  if (!jid || !fn) return
  const key = `${jid}:${fn}`
  if (seen.has(key)) return
  seen.add(key)
  out.push({
    jobId: jid,
    filename: fn,
    label: label?.trim() ? String(label).trim() : fn.split(/[/\\]/).pop() || fn,
  })
}

function parseDownloadRow(item: unknown, out: EmployeeOutputDownload[], seen: Set<string>, fallbackJobId?: string) {
  if (!item || typeof item !== 'object') return
  const row = item as DownloadRow
  const jobId = String(row.job_id || row.jobId || fallbackJobId || '').trim()
  const filename = String(row.filename || row.name || row.file || row.path || '').trim()
  if (Array.isArray(row.files) && jobId) {
    for (const f of row.files) {
      const name = typeof f === 'string' ? f : String((f as { filename?: string })?.filename || '')
      if (name.trim()) pushParsedDownload(out, seen, jobId, name, row.label)
    }
  }
  if (jobId && filename) {
    pushParsedDownload(out, seen, jobId, filename, row.label)
  }
}

/** 从 execute-file / execute 响应解析可下载产出（兼容 output_downloads、嵌套 result、camelCase）。 */
export function parseEmployeeOutputDownloads(result: unknown): EmployeeOutputDownload[] {
  if (!result || typeof result !== 'object') return []
  const root = result as Record<string, unknown>
  const nested =
    root.result && typeof root.result === 'object' && !Array.isArray(root.result) ? (root.result as Record<string, unknown>) : null
  const env = normalizeEmployeeExecuteEnvelope(result)
  const arrays: unknown[][] = []
  for (const src of [root, nested, env]) {
    if (!src) continue
    for (const key of ['output_downloads', 'outputDownloads', 'downloads'] as const) {
      const v = src[key]
      if (Array.isArray(v) && v.length) arrays.push(v)
    }
  }
  const out: EmployeeOutputDownload[] = []
  const seen = new Set<string>()
  let sharedJobId = ''
  for (const arr of arrays) {
    for (const item of arr) {
      if (!item || typeof item !== 'object') continue
      const row = item as DownloadRow
      const jid = String(row.job_id || row.jobId || '').trim()
      if (jid) sharedJobId = jid
    }
  }
  for (const arr of arrays) {
    for (const item of arr) {
      parseDownloadRow(item, out, seen, sharedJobId)
    }
  }
  return out
}
