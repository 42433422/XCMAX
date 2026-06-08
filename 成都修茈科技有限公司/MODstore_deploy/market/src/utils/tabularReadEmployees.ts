/** 公开市场「全量读取」员工包：扩展名 → pkg_id（与 modstore_server/catalog_quality.PUBLIC_TABULAR 读取类一致） */

import { officeFormatFromExtension, resolveGenerateEmployeeForFormat } from './officeEmployeeOrchestration'

export const GENERATE_EMPLOYEE_IDS = [
  'word-generate-employee',
  'excel-generate-employee',
  'csv-generate-employee',
  'pdf-generate-employee',
  'ppt-generate-employee',
] as const

const GENERATE_EMPLOYEE_ID_SET = new Set<string>(GENERATE_EMPLOYEE_IDS)

export function isGenerateEmployeeId(employeeId: string): boolean {
  return GENERATE_EMPLOYEE_ID_SET.has(String(employeeId || '').trim())
}

export const TABULAR_READ_EMPLOYEE_IDS = [
  'excel-full-read-employee',
  'csv-full-read-employee',
  'pdf-full-read-employee',
  'ppt-full-read-employee',
  'word-full-read-employee',
] as const

export const JSON_REPORT_EMPLOYEE_ID = 'json-report-employee'

const EXT_TO_READ_EMPLOYEE: Record<string, string> = {
  xlsx: 'excel-full-read-employee',
  xlsm: 'excel-full-read-employee',
  xls: 'excel-full-read-employee',
  csv: 'csv-full-read-employee',
  pdf: 'pdf-full-read-employee',
  pptx: 'ppt-full-read-employee',
  ppt: 'ppt-full-read-employee',
  docx: 'word-full-read-employee',
  doc: 'word-full-read-employee',
  docm: 'word-full-read-employee',
  dotx: 'word-full-read-employee',
  dotm: 'word-full-read-employee',
  rtf: 'word-full-read-employee',
  wps: 'word-full-read-employee',
}

export function resolveReadEmployeeForExtension(ext: string): string | null {
  const e = String(ext || '')
    .trim()
    .toLowerCase()
    .replace(/^\./, '')
  return EXT_TO_READ_EMPLOYEE[e] || null
}

export function isEmployeeExecuteFileExt(ext: string): boolean {
  return resolveReadEmployeeForExtension(ext) !== null
}

function normalizeFileExt(ext: string): string {
  return String(ext || '')
    .trim()
    .toLowerCase()
    .replace(/^\./, '')
}

/** 当前员工包是否接受该扩展名（考试页选文件、工作台发送前校验）。 */
export function employeeAcceptsFileExtension(employeeId: string, ext: string): boolean {
  const e = normalizeFileExt(ext)
  if (!e) return false
  if (employeeId === JSON_REPORT_EMPLOYEE_ID) return e === 'json'
  if (isGenerateEmployeeId(employeeId)) {
    if (e === 'json' || e === 'txt') return true
    if (employeeId === 'word-generate-employee' && e === 'docx') return true
    return false
  }
  const suggested = resolveReadEmployeeForExtension(e)
  if (!suggested) return false
  return suggested === employeeId
}

/** 扩展名与所选员工不匹配时的中文提示（与 employee_api 语义对齐）。 */
export function employeeFileMismatchHint(employeeId: string, ext: string): string {
  const e = normalizeFileExt(ext)
  const readId = resolveReadEmployeeForExtension(e)
  if (isGenerateEmployeeId(employeeId) && readId) {
    const readLabel = readEmployeeDisplayName(readId)
    const fmt = officeFormatFromExtension(e)
    const genId = fmt ? resolveGenerateEmployeeForFormat(fmt) : ''
    const genLabel = genId ? readEmployeeDisplayName(genId) : ''
    if (fmt === 'ppt' && genId) {
      return (
        `生成员「${employeeId}」不能直接上传 .${e} 原稿；请改选「${readLabel}」（${readId}）全量解析，` +
        `或先导出 presentation_full.json 再用「${genLabel}」（${genId}）生成`
      )
    }
    return `生成员「${employeeId}」不接受 .${e}；请改选「${readLabel}」（${readId}）`
  }
  if (readId) {
    return `当前员工不接受 .${e}；请改选「${readEmployeeDisplayName(readId)}」（${readId}）`
  }
  if (e === 'json') {
    return 'JSON 请使用 json-report-employee 或对应格式的 *-generate-employee'
  }
  return `不支持 .${e || '该'} 扩展名；读取类支持 Office/PDF，生成员支持 .json/.txt`
}

/** 根据上传文件扩展名推荐员工包（含 .json → 量化报告员）。 */
export function suggestEmployeeForUploadedFile(ext: string): string | null {
  const e = normalizeFileExt(ext)
  if (e === 'json') return JSON_REPORT_EMPLOYEE_ID
  return resolveReadEmployeeForExtension(e)
}

export function readEmployeeDisplayName(pkgId: string): string {
  const map: Record<string, string> = {
    'excel-full-read-employee': 'Excel 读取员',
    'csv-full-read-employee': 'CSV 全量读取员',
    'pdf-full-read-employee': 'PDF 全量读取员',
    'ppt-full-read-employee': 'PPT 全量读取员',
    'ppt-generate-employee': 'PPT 生成员',
    'word-full-read-employee': 'Word 全量读取员',
    'word-generate-employee': 'Word 生成员',
    'excel-generate-employee': 'Excel 生成员',
    'csv-generate-employee': 'CSV 生成员',
    'pdf-generate-employee': 'PDF 生成员',
    [JSON_REPORT_EMPLOYEE_ID]: 'JSON 量化报告员',
  }
  return map[pkgId] || pkgId
}

export type EmployeeExecuteDiagnostics = {
  success: boolean
  error: string
  summary: string
  warnings: string[]
}

function mergeOutputDownloadsField(
  ...candidates: unknown[]
): unknown[] | undefined {
  const merged: unknown[] = []
  const seen = new Set<string>()
  for (const raw of candidates) {
    if (!Array.isArray(raw)) continue
    for (const item of raw) {
      const key =
        item && typeof item === 'object'
          ? JSON.stringify(item)
          : String(item)
      if (seen.has(key)) continue
      seen.add(key)
      merged.push(item)
    }
  }
  return merged.length ? merged : undefined
}

/** execute-file 常返回 { employee_id, result: { outputs, ... }, output_downloads, llm_context_text }，统一展平。 */
export function normalizeEmployeeExecuteEnvelope(result: unknown): Record<string, unknown> {
  if (!result || typeof result !== 'object') return {}
  const root = result as Record<string, unknown>
  const inner = root.result
  if (!inner || typeof inner !== 'object' || Array.isArray(inner)) return root
  const nested = inner as Record<string, unknown>
  return {
    ...nested,
    ...root,
    outputs: root.outputs ?? nested.outputs,
    output_downloads: mergeOutputDownloadsField(
      root.output_downloads,
      root.outputDownloads,
      nested.output_downloads,
      nested.outputDownloads,
      root.downloads,
      nested.downloads,
    ),
    llm_context_text: root.llm_context_text ?? nested.llm_context_text,
    ok: root.ok ?? nested.ok,
    error: root.error ?? nested.error,
    summary: root.summary ?? nested.summary,
  }
}

/** 首个成功的 direct_python output 载荷（含 paragraph_count / items 等）。 */
export function extractDirectPythonPayload(result: unknown): Record<string, unknown> | null {
  const r = normalizeEmployeeExecuteEnvelope(result)
  const outputs = Array.isArray(r.outputs) ? r.outputs : []
  for (const item of outputs) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    if (row.ok === false) continue
    const out = row.output
    if (!out || typeof out !== 'object') continue
    const o = out as Record<string, unknown>
    if (o.ok === false) continue
    return o
  }
  return null
}

function isDocumentFullShape(obj: Record<string, unknown>): boolean {
  return Array.isArray(obj.paragraphs) || Array.isArray(obj.tables) || Array.isArray(obj.blocks)
}

function isPresentationFullShape(obj: Record<string, unknown>): boolean {
  return Array.isArray(obj.slides)
}

function findPresentationFullObject(node: unknown, depth = 0): Record<string, unknown> | null {
  if (depth > 12 || node == null) return null
  if (Array.isArray(node)) {
    for (const it of node) {
      const hit = findPresentationFullObject(it, depth + 1)
      if (hit) return hit
    }
    return null
  }
  if (typeof node !== 'object') return null
  const o = node as Record<string, unknown>
  if (isPresentationFullShape(o)) return o
  for (const key of [
    'presentation_full',
    'presentation',
    'ppt',
    'data',
    'output',
    'items',
    'payload',
  ]) {
    if (key in o) {
      const hit = findPresentationFullObject(o[key], depth + 1)
      if (hit) return hit
    }
  }
  const outputs = o.outputs
  if (Array.isArray(outputs)) {
    for (const item of outputs) {
      if (!item || typeof item !== 'object') continue
      const row = item as Record<string, unknown>
      const hit = findPresentationFullObject(row.output ?? row, depth + 1)
      if (hit) return hit
    }
  }
  return null
}

function findDocumentFullObject(node: unknown, depth = 0): Record<string, unknown> | null {
  if (depth > 12 || node == null) return null
  if (Array.isArray(node)) {
    for (const it of node) {
      const hit = findDocumentFullObject(it, depth + 1)
      if (hit) return hit
    }
    return null
  }
  if (typeof node !== 'object') return null
  const o = node as Record<string, unknown>
  if (isDocumentFullShape(o)) return o
  for (const key of ['document_full', 'document', 'doc', 'data', 'output', 'items', 'payload']) {
    if (key in o) {
      const hit = findDocumentFullObject(o[key], depth + 1)
      if (hit) return hit
    }
  }
  const outputs = o.outputs
  if (Array.isArray(outputs)) {
    for (const item of outputs) {
      if (!item || typeof item !== 'object') continue
      const row = item as Record<string, unknown>
      const hit = findDocumentFullObject(row.output ?? row, depth + 1)
      if (hit) return hit
    }
  }
  return null
}

/** 从 llm_context_text 或 items 中提取 document_full JSON 字符串（供报告员工上传）。 */
export function extractDocumentFullJsonText(result: unknown): string | null {
  const r = normalizeEmployeeExecuteEnvelope(result)
  const llm = String(r.llm_context_text || '').trim()
  if (llm) {
    const patterns = [
      /### (?:outputs\/)?document_full\.json\n([\s\S]*?)(?=\n### |\n*$)/,
      /### document_full\.json\n([\s\S]*?)(?=\n### |\n*$)/,
    ]
    for (const re of patterns) {
      const m = llm.match(re)
      if (m?.[1]?.trim()) return m[1].trim()
    }
    const trimmed = llm.trim()
    if (trimmed.startsWith('{') && trimmed.includes('"paragraphs"')) {
      return trimmed
    }
  }
  const embedded = findDocumentFullObject(r)
  if (embedded) {
    try {
      return JSON.stringify(embedded, null, 2)
    } catch {
      /* ignore */
    }
  }
  const payload = extractDirectPythonPayload(result)
  if (!payload) return null
  const items = payload.items
  if (Array.isArray(items)) {
    for (const it of items) {
      if (it && typeof it === 'object') {
        const row = it as Record<string, unknown>
        if (isDocumentFullShape(row)) {
          try {
            return JSON.stringify(row, null, 2)
          } catch {
            /* ignore */
          }
        }
      }
    }
  }
  if (isDocumentFullShape(payload)) {
    try {
      return JSON.stringify(payload, null, 2)
    } catch {
      /* ignore */
    }
  }
  return null
}

/** 从读取员工响应提取 presentation_full JSON（PPT 读 → PPT 生）。 */
export function extractPresentationFullJsonText(result: unknown): string | null {
  const r = normalizeEmployeeExecuteEnvelope(result)
  const llm = String(r.llm_context_text || '').trim()
  if (llm) {
    const patterns = [
      /### (?:outputs\/)?presentation_full\.json\n([\s\S]*?)(?=\n### |\n*$)/,
      /### presentation_full\.json\n([\s\S]*?)(?=\n### |\n*$)/,
    ]
    for (const re of patterns) {
      const m = llm.match(re)
      if (m?.[1]?.trim()) return m[1].trim()
    }
    const trimmed = llm.trim()
    if (trimmed.startsWith('{') && trimmed.includes('"slides"')) {
      return trimmed
    }
  }
  const embedded = findPresentationFullObject(r)
  if (embedded) {
    try {
      return JSON.stringify(embedded, null, 2)
    } catch {
      /* ignore */
    }
  }
  const payload = extractDirectPythonPayload(result)
  if (!payload) return null
  const items = payload.items
  if (Array.isArray(items)) {
    for (const it of items) {
      if (it && typeof it === 'object') {
        const row = it as Record<string, unknown>
        if (isPresentationFullShape(row)) {
          try {
            return JSON.stringify(row, null, 2)
          } catch {
            /* ignore */
          }
        }
      }
    }
  }
  if (isPresentationFullShape(payload)) {
    try {
      return JSON.stringify(payload, null, 2)
    } catch {
      /* ignore */
    }
  }
  return null
}

export function extractWordReadStats(result: unknown): { paragraphCount?: number; tableCount?: number; title?: string } {
  const payload = extractDirectPythonPayload(result)
  if (!payload) return {}
  let paragraphCount = payload.paragraph_count as number | undefined
  let tableCount = payload.table_count as number | undefined
  const items = payload.items
  if (Array.isArray(items) && items[0] && typeof items[0] === 'object') {
    const row = items[0] as Record<string, unknown>
    if (paragraphCount === undefined) paragraphCount = row.paragraph_count as number | undefined
    if (tableCount === undefined) tableCount = row.table_count as number | undefined
    const stats = row.stats as Record<string, unknown> | undefined
    if (stats && typeof stats === 'object') {
      if (paragraphCount === undefined) paragraphCount = stats.paragraph_count as number | undefined
      if (tableCount === undefined) tableCount = stats.table_count as number | undefined
    }
  }
  const docText = extractDocumentFullJsonText(result)
  let title = ''
  if (docText) {
    try {
      const doc = JSON.parse(docText) as Record<string, unknown>
      const meta = doc.metadata as Record<string, unknown> | undefined
      title = String(meta?.title || doc.title || '').trim()
    } catch {
      /* ignore */
    }
  }
  return { paragraphCount, tableCount, title: title || undefined }
}

/** 从 execute-file / execute 响应解析 direct_python 成败与可读错误信息。 */
export function extractEmployeeExecuteDiagnostics(result: unknown): EmployeeExecuteDiagnostics {
  const empty: EmployeeExecuteDiagnostics = { success: true, error: '', summary: '', warnings: [] }
  if (!result || typeof result !== 'object') return empty
  const r = normalizeEmployeeExecuteEnvelope(result)
  const topOk = r.ok
  const warnings: string[] = []
  let error = String(r.error || '').trim()
  let summary = String(r.summary || r.message || '').trim()

  const outputs = Array.isArray(r.outputs) ? r.outputs : []
  let handlerFailed = false
  for (const item of outputs) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    if (row.ok === false) handlerFailed = true
    const rowErr = String(row.error || '').trim()
    if (rowErr) error = error || rowErr
    const out = row.output
    if (out && typeof out === 'object') {
      const o = out as Record<string, unknown>
      if (o.ok === false) handlerFailed = true
      const oe = String(o.error || '').trim()
      const os = String(o.summary || '').trim()
      if (oe) error = error || oe
      if (os && !summary) summary = os
      for (const w of o.warnings || []) {
        if (typeof w === 'string' && w.trim()) warnings.push(w.trim())
      }
    }
  }

  const failed = topOk === false || handlerFailed
  if (!failed) return empty
  if (!error && summary) error = summary
  if (!summary && error) summary = error
  return { success: false, error, summary, warnings }
}

export function pickDocumentFullJsonDownload(
  items: EmployeeOutputDownload[],
): EmployeeOutputDownload | undefined {
  return items.find(
    (d) =>
      d.filename === 'document_full.json' ||
      d.filename.endsWith('/document_full.json') ||
      d.filename.includes('document_full.json'),
  )
}

export function pickPresentationFullJsonDownload(
  items: EmployeeOutputDownload[],
): EmployeeOutputDownload | undefined {
  return items.find(
    (d) =>
      d.filename === 'presentation_full.json' ||
      d.filename.endsWith('/presentation_full.json') ||
      d.filename.includes('presentation_full.json'),
  )
}

export function pickQuantitativeReportDownload(
  items: EmployeeOutputDownload[],
): EmployeeOutputDownload | undefined {
  return items.find(
    (d) =>
      d.filename === 'quantitative_report.html' ||
      d.filename.endsWith('/quantitative_report.html') ||
      d.filename.includes('quantitative_report.html'),
  )
}

function summarizeDocumentFullJson(text: string): string {
  try {
    const data = JSON.parse(text) as Record<string, unknown>
    const paragraphs = Array.isArray(data.paragraphs) ? data.paragraphs.length : 0
    const tables = Array.isArray(data.tables) ? data.tables.length : 0
    const meta = data.metadata && typeof data.metadata === 'object' ? (data.metadata as Record<string, unknown>) : {}
    const title = String(meta.title || data.title || '').trim()
    const lines = [
      `段落数：${paragraphs}`,
      `表格数：${tables}`,
      title ? `标题：${title}` : '',
    ].filter(Boolean)
    return lines.join('\n')
  } catch {
    return ''
  }
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

function pushParsedDownload(
  out: EmployeeOutputDownload[],
  seen: Set<string>,
  jobId: string,
  filename: string,
  label?: string,
) {
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

function parseDownloadRow(
  item: unknown,
  out: EmployeeOutputDownload[],
  seen: Set<string>,
  fallbackJobId?: string,
) {
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
    root.result && typeof root.result === 'object' && !Array.isArray(root.result)
      ? (root.result as Record<string, unknown>)
      : null
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

const LLM_CONTEXT_MAX_CHARS = 100_000

/** 从 execute-file 响应提取可供 LLM 使用的真实解析正文（优先服务端 llm_context_text）。 */
export function extractEmployeeReadTextForLlm(result: unknown, maxChars = LLM_CONTEXT_MAX_CHARS): string {
  if (!result || typeof result !== 'object') return ''
  const r = normalizeEmployeeExecuteEnvelope(result)
  const direct = String(r.llm_context_text || '').trim()
  if (direct) return direct.length <= maxChars ? direct : direct.slice(0, maxChars) + '\n\n…（已截断）'

  const chunks: string[] = []
  const walk = (node: unknown, depth: number) => {
    if (depth > 8 || node == null) return
    if (typeof node === 'string') {
      const s = node.trim()
      if (s.length > 40 && (s.startsWith('{') || s.includes('\n'))) chunks.push(s)
      return
    }
    if (Array.isArray(node)) {
      for (const it of node) walk(it, depth + 1)
      return
    }
    if (typeof node === 'object') {
      const o = node as Record<string, unknown>
      for (const key of ['output', 'data', 'workbook', 'document', 'text', 'content', 'rows', 'sheets']) {
        if (key in o) walk(o[key], depth + 1)
      }
      if (Array.isArray(o.outputs)) {
        for (const item of o.outputs) {
          if (item && typeof item === 'object') {
            const out = (item as { output?: unknown }).output
            if (out !== undefined) {
              try {
                chunks.push(JSON.stringify(out, null, 2))
              } catch {
                walk(out, depth + 1)
              }
            }
          }
        }
      }
    }
  }
  walk(r.outputs ?? r.result ?? r.data ?? r, 0)
  const merged = chunks.join('\n\n---\n\n').trim()
  if (!merged) {
    try {
      return JSON.stringify(r, null, 2).slice(0, maxChars)
    } catch {
      return ''
    }
  }
  return merged.length <= maxChars ? merged : merged.slice(0, maxChars) + '\n\n…（已截断）'
}

export function formatEmployeeReadResultSummary(
  employeeId: string,
  fileName: string,
  result: unknown,
  opts?: { includeLlmExcerpt?: boolean },
): { text: string; downloads: EmployeeOutputDownload[] } {
  const includeLlmExcerpt = opts?.includeLlmExcerpt !== false
  const label = readEmployeeDisplayName(employeeId)
  const downloads = parseEmployeeOutputDownloads(result)
  const diag = extractEmployeeExecuteDiagnostics(result)
  const lines: string[] = []
  if (diag.success) {
    lines.push(`已使用 **${label}**（\`${employeeId}\`）处理 \`${fileName}\`。`)
  } else {
    lines.push(`**试跑失败**：**${label}**（\`${employeeId}\`）未能成功处理 \`${fileName}\`。`)
    if (diag.error) lines.push(`\n**原因：** ${diag.error}`)
    else if (diag.summary) lines.push(`\n**原因：** ${diag.summary}`)
    if (diag.warnings.length) {
      lines.push('\n**提示：**')
      for (const w of diag.warnings) lines.push(`- ${w}`)
    }
    if (/旧版\s*\.doc|LibreOffice|soffice|textutil|另存为\s*\.docx/i.test(diag.error + diag.summary)) {
      lines.push(
        '\n**考试建议：** 旧版 `.doc` 需服务器安装 LibreOffice 才能转换。请先将 `3.doc` 在 Word/WPS 中 **另存为 .docx** 再上传试跑，或联系管理员在 CVM 安装 `libreoffice-headless`。',
      )
    }
    return { text: lines.join('\n'), downloads }
  }
  const r = normalizeEmployeeExecuteEnvelope(result)
  if (r && typeof r === 'object') {
    if (r.message && !diag.error) lines.push(String(r.message))
  }
  if (employeeId === JSON_REPORT_EMPLOYEE_ID) {
    const meta = r && typeof r === 'object' ? (r.meta as Record<string, unknown> | undefined) : undefined
    const items = r && typeof r === 'object' ? (r.items as Record<string, unknown> | undefined) : undefined
    const title = String(meta?.source_title || items?.source_title || '').trim()
    const pc = meta?.paragraph_count ?? items?.paragraph_count
    const tc = meta?.table_count ?? items?.table_count
    if (title || pc !== undefined || tc !== undefined) {
      lines.push('\n**报告统计：**')
      if (title) lines.push(`- 文档：${title}`)
      if (pc !== undefined) lines.push(`- 段落：${String(pc)}`)
      if (tc !== undefined) lines.push(`- 表格：${String(tc)}`)
    }
    if (pickQuantitativeReportDownload(downloads)) {
      lines.push('\nHTML 量化报告已生成，可点击下方 **预览报告** 或下载 `quantitative_report.html`。')
    }
  }
  if (employeeId === 'word-full-read-employee') {
    const wstats = extractWordReadStats(result)
    if (wstats.paragraphCount !== undefined || wstats.tableCount !== undefined || wstats.title) {
      lines.push('\n**文档结构摘要：**')
      if (wstats.title) lines.push(`- 标题：${wstats.title}`)
      if (wstats.paragraphCount !== undefined) lines.push(`- 段落：${wstats.paragraphCount}`)
      if (wstats.tableCount !== undefined) lines.push(`- 表格：${wstats.tableCount}`)
    }
  }
  if (downloads.length) {
    lines.push('\n**可下载产出：**')
    for (const d of downloads) {
      lines.push(`- ${d.label || d.filename}`)
    }
  }
  const hasDocForReport =
    pickDocumentFullJsonDownload(downloads) || Boolean(extractDocumentFullJsonText(result))
  if (employeeId === 'word-full-read-employee' && hasDocForReport) {
    lines.push(
      '\n**考试报告：** 试跑成功后将**自动**调用 JSON 量化报告员生成 HTML 报告（约 30 秒–2 分钟）；若未自动开始，可点 **重新生成报告**。',
    )
  }
  const llmPreview = includeLlmExcerpt ? extractEmployeeReadTextForLlm(result, 8000) : ''
  if (llmPreview && employeeId !== JSON_REPORT_EMPLOYEE_ID && employeeId !== 'word-full-read-employee') {
    lines.push('\n**解析摘要（节选）：**\n```\n' + llmPreview + '\n```')
  } else if (llmPreview && employeeId === JSON_REPORT_EMPLOYEE_ID) {
    /* 报告员不重复贴大段 JSON */
  }
  /* 成功时不再默认展开整段 outputs JSON，细节见「原始 JSON」折叠区 */
  return { text: lines.join('\n'), downloads }
}
