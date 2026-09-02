/** 执行诊断、读取统计、LLM 上下文提取与结果汇总文案（原 tabularReadEmployees 单体拆分） */
import { JSON_REPORT_EMPLOYEE_ID, readEmployeeDisplayName } from './employeeIds'
import { extractDocumentFullJsonText } from './fullJson'
import { pickDocumentFullJsonDownload, parseEmployeeOutputDownloads, pickQuantitativeReportDownload, type EmployeeOutputDownload } from './downloads'
import { normalizeEmployeeExecuteEnvelope, extractDirectPythonPayload, type EmployeeExecuteDiagnostics } from './envelope'

export function extractWordReadStats(result: unknown): {
  paragraphCount?: number
  tableCount?: number
  title?: string
} {
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
      for (const w of Array.isArray(o.warnings) ? o.warnings : []) {
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
  const hasDocForReport = pickDocumentFullJsonDownload(downloads) || Boolean(extractDocumentFullJsonText(result))
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
