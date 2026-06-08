/**
 * 办公员工：读取 →（可选）生成，供 WorkbenchHomeView 直接对话调用。
 */
import { api } from '../api'
import {
  extractDocumentFullJsonText,
  extractPresentationFullJsonText,
  extractEmployeeExecuteDiagnostics,
  extractEmployeeReadTextForLlm,
  formatEmployeeReadResultSummary,
  parseEmployeeOutputDownloads,
  pickDocumentFullJsonDownload,
  pickPresentationFullJsonDownload,
  employeeAcceptsFileExtension,
  employeeFileMismatchHint,
  readEmployeeDisplayName,
  type EmployeeOutputDownload,
} from './tabularReadEmployees'
import { resolveGenerateInputs } from './officeGenerateFromText'
import {
  detectOfficeEnhanceAttachedIntent,
  detectOfficeGenerateIntent,
  officeFormatFromFileName,
  pickPptTemplateFromSources,
  primaryOfficeFormatFromAttachments,
  resolveGenerateEmployeeForFormat,
  type OfficeFormat,
} from './officeEmployeeOrchestration'

export type OfficeReadFileItem = {
  file: File
  name: string
  readEmployeeId?: string
}

export type OfficeReadPhaseResult = {
  inlineFiles: Array<{ name: string; text: string }>
  downloads: EmployeeOutputDownload[]
  readErrors: string[]
  readSummary: string
  rawResults: Array<{ name: string; employeeId: string; result: unknown }>
}

export type OfficeGeneratePhaseResult = {
  summary: string
  downloads: EmployeeOutputDownload[]
  errors: string[]
}

export async function runOfficeReadPhase(opts: {
  files: OfficeReadFileItem[]
  userText?: string
  onProgress?: (line: string) => void
  resolveReadEmployeeId: (item: OfficeReadFileItem) => string | null
}): Promise<OfficeReadPhaseResult> {
  const inlineFiles: Array<{ name: string; text: string }> = []
  const downloads: EmployeeOutputDownload[] = []
  const readErrors: string[] = []
  const summaryLines: string[] = []
  const rawResults: Array<{ name: string; employeeId: string; result: unknown }> = []

  for (const item of opts.files) {
    const employeeId = opts.resolveReadEmployeeId(item)
    if (!employeeId) {
      readErrors.push(`${item.name}：未匹配读取员工`)
      continue
    }
    const ext = String(item.name || '').split('.').pop()?.toLowerCase() || ''
    if (!employeeAcceptsFileExtension(employeeId, ext)) {
      readErrors.push(`${item.name}：${employeeFileMismatchHint(employeeId, ext)}`)
      continue
    }
    opts.onProgress?.(`正在用 **${readEmployeeDisplayName(employeeId)}** 解析 \`${item.name}\`…`)
    try {
      const res = await api.employeeExecuteFile(employeeId, item.file, {
        task: opts.userText ? '全量读取并供后续问答' : '全量读取',
        inputData: opts.userText ? { user_query: opts.userText } : {},
      })
      rawResults.push({ name: item.name, employeeId, result: res })
      const llmText = extractEmployeeReadTextForLlm(res)
      if (!llmText.trim()) {
        readErrors.push(`${item.name}：读取员工未返回可用正文`)
        const { text } = formatEmployeeReadResultSummary(employeeId, item.name, res)
        summaryLines.push(text)
        continue
      }
      inlineFiles.push({
        name: `${item.name}（读取员工解析·${readEmployeeDisplayName(employeeId)}）`,
        text: llmText,
      })
      const { text } = formatEmployeeReadResultSummary(employeeId, item.name, res)
      summaryLines.push(text)
      downloads.push(...parseEmployeeOutputDownloads(res))
    } catch (e: unknown) {
      readErrors.push(`${item.name}：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  return {
    inlineFiles,
    downloads,
    readErrors,
    readSummary: summaryLines.join('\n\n---\n\n'),
    rawResults,
  }
}

async function buildJsonFileForGenerate(
  raw: unknown,
  _fallbackName: string,
  format: OfficeFormat,
): Promise<File | null> {
  const jsonName = format === 'ppt' ? 'presentation_full.json' : 'document_full.json'
  const text =
    format === 'ppt' ? extractPresentationFullJsonText(raw) : extractDocumentFullJsonText(raw)
  if (text?.trim()) {
    return new File([text], jsonName, { type: 'application/json' })
  }
  const downloads = parseEmployeeOutputDownloads(raw)
  const dl =
    format === 'ppt'
      ? pickPresentationFullJsonDownload(downloads)
      : pickDocumentFullJsonDownload(downloads)
  if (dl) {
    try {
      const blob = await api.employeeOutputDownload(dl.jobId, dl.filename)
      return new File([blob], jsonName, { type: 'application/json' })
    } catch {
      return null
    }
  }
  return null
}

export async function runOfficeGeneratePhase(opts: {
  format: OfficeFormat
  userText?: string
  readResults?: Array<{ name: string; employeeId: string; result: unknown }>
  templateFile?: File | null
  extraAttachmentFiles?: File[]
}): Promise<OfficeGeneratePhaseResult> {
  const generateId = resolveGenerateEmployeeForFormat(opts.format)
  const errors: string[] = []
  const downloads: EmployeeOutputDownload[] = []
  const summaryLines: string[] = []
  const readResults = opts.readResults || []

  let jsonFile: File | null = null
  let sourceName = ''
  let inputData: Record<string, unknown> = {
    user_query: opts.userText || '',
  }

  let presentationPayload: Record<string, unknown> | null = null
  for (const row of readResults) {
    const fmt = officeFormatFromFileName(row.name)
    if (fmt && fmt !== opts.format) continue
    const presText = extractPresentationFullJsonText(row.result)
    if (presText?.trim()) {
      try {
        presentationPayload = JSON.parse(presText) as Record<string, unknown>
      } catch {
        presentationPayload = null
      }
    }
    jsonFile = await buildJsonFileForGenerate(row.result, row.name, opts.format)
    if (jsonFile) {
      sourceName = row.name
      break
    }
  }
  if (!jsonFile && readResults.length) {
    jsonFile = await buildJsonFileForGenerate(readResults[0].result, readResults[0].name, opts.format)
    sourceName = readResults[0].name
  }

  if (!jsonFile && String(opts.userText || '').trim()) {
    const resolved = resolveGenerateInputs({
      format: opts.format,
      userText: opts.userText || '',
      attachmentFiles: opts.extraAttachmentFiles || [],
    })
    jsonFile = resolved.jsonFile
    inputData = { ...inputData, ...resolved.inputData }
    if (resolved.usedUserJson) {
      summaryLines.push('使用您上传的结构化 JSON 作为生成输入。')
    } else {
      summaryLines.push('已根据您的文字描述构建生成输入（支持纯文本直出，无需先上传源 Office 文件）。')
    }
  }

  if (!jsonFile) {
    return {
      summary: '',
      downloads: [],
      errors: [
        `未能得到可供「${readEmployeeDisplayName(generateId)}」使用的输入。请上传源文件、结构化 JSON，或在消息中用文字描述要生成的内容。`,
      ],
    }
  }

  try {
    if (sourceName) inputData.source_filename = sourceName
    if (presentationPayload && opts.format === 'ppt') {
      inputData.presentation_full = presentationPayload
    }
    const templateFile =
      opts.templateFile ??
      (opts.format === 'ppt'
        ? pickPptTemplateFromSources(
            (opts.extraAttachmentFiles || []).map((f) => ({ name: f.name, file: f })),
          )
        : null)
    if (templateFile) {
      inputData.has_template = true
      inputData.enhance_homework_marquee = '1'
      inputData.template_relpath = templateFile.name
    }
    const res = await api.employeeExecuteFile(generateId, jsonFile, {
      task: opts.userText ? `生成：${opts.userText.slice(0, 120)}` : '由结构化 JSON 生成 Office 文件',
      inputData,
      template: templateFile ?? undefined,
      timeoutMs: 180_000,
    })
    const diag = extractEmployeeExecuteDiagnostics(res)
    const { text } = formatEmployeeReadResultSummary(generateId, 'document_full.json', res, {
      includeLlmExcerpt: false,
    })
    summaryLines.push(text)
    downloads.push(...parseEmployeeOutputDownloads(res))
    if (!diag.success) {
      errors.push(diag.error || diag.summary || '生成员工执行失败')
    } else if (!downloads.length) {
      summaryLines.push(`已调用 **${readEmployeeDisplayName(generateId)}**，若未见下载按钮请查看试跑摘要。`)
    } else {
      summaryLines.push(`已生成可下载文件（${downloads.map((d) => d.label || d.filename).join('、')}）。`)
    }
    return { summary: summaryLines.join('\n'), downloads, errors }
  } catch (e: unknown) {
    return {
      summary: '',
      downloads: [],
      errors: [e instanceof Error ? e.message : String(e)],
    }
  }
}

export function pickGenerateFormat(userText: string, attachmentNames: string[]): OfficeFormat {
  const fromAttach = primaryOfficeFormatFromAttachments(attachmentNames)
  const gen = detectOfficeGenerateIntent(userText)
  // 附件为 pptx 时优先 ppt，避免「制作」等泛化关键词把格式判成 word
  if (fromAttach && (!gen || detectOfficeEnhanceAttachedIntent(userText, attachmentNames))) {
    return fromAttach
  }
  return gen?.format || fromAttach || 'word'
}
