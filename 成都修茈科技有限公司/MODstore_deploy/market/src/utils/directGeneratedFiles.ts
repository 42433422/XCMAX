import type { EmployeeOutputDownload } from './tabularReadEmployees'

/** Composer 底栏「已生成」文件卡片（与附件卡片共用 wb-direct-file-card 样式）。 */
export type DirectGeneratedFile = {
  id: string
  role: 'generated'
  name: string
  status: 'ready'
  jobId: string
  filename: string
}

/** 用户可下载的 Office / PDF 等成品扩展名（顶栏条带与对话下载区仅展示这些）。 */
const USER_FACING_OFFICE_EXT = new Set([
  'pptx',
  'ppt',
  'docx',
  'doc',
  'docm',
  'dotx',
  'dotm',
  'xlsx',
  'xls',
  'xlsm',
  'csv',
  'pdf',
  'rtf',
  'wps',
])

const INTERNAL_ARTIFACT_BASENAMES = new Set([
  'document_full.json',
  'presentation_full.json',
  'presentation_meta.json',
  'images_index.json',
  'speaker_notes.md',
])

export function basenameOfDownloadPath(filename: string): string {
  return (
    String(filename || '')
      .trim()
      .split(/[/\\]/)
      .pop()
      ?.toLowerCase() || ''
  )
}

/** 读取/解析阶段产出的中间 JSON、VLM 标注等，不应出现在「已生成」条带。 */
export function isInternalOfficeArtifactFilename(filename: string): boolean {
  const base = basenameOfDownloadPath(filename)
  if (!base) return true
  if (INTERNAL_ARTIFACT_BASENAMES.has(base)) return true
  if (/^presentation_.*\.json$/i.test(base)) return true
  if (/\.vlm\.json$/i.test(base)) return true
  if (/^s\d+_img.*\.vlm\.json$/i.test(base)) return true
  return false
}

/** 面向用户的可下载成品（如 .pptx / .docx），排除中间产物。 */
export function isUserFacingDeliverableFilename(filename: string): boolean {
  if (!String(filename || '').trim()) return false
  if (isInternalOfficeArtifactFilename(filename)) return false
  const base = basenameOfDownloadPath(filename)
  const dot = base.lastIndexOf('.')
  if (dot < 0) return false
  const ext = base.slice(dot + 1)
  return USER_FACING_OFFICE_EXT.has(ext)
}

/** 生成员/读取员工响应里仅保留用户可见的下载项。 */
export function filterUserFacingOfficeDownloads(
  downloads: EmployeeOutputDownload[],
): EmployeeOutputDownload[] {
  return (downloads || []).filter(
    (d) => d?.jobId && d?.filename && isUserFacingDeliverableFilename(d.filename),
  )
}

export function displayNameForOfficeDownload(d: EmployeeOutputDownload): string {
  const label = String(d.label || '').trim()
  if (label && label !== d.filename) return label
  const base = String(d.filename || '')
    .split(/[/\\]/)
    .pop()
  return base || d.filename || '下载文件'
}

let generatedIdSeq = 0

export function employeeDownloadsToGeneratedFiles(
  downloads: EmployeeOutputDownload[],
): DirectGeneratedFile[] {
  return filterUserFacingOfficeDownloads(downloads).map((d) => {
    generatedIdSeq += 1
    return {
      id: `gen-${d.jobId}-${d.filename}-${generatedIdSeq}`,
      role: 'generated',
      name: displayNameForOfficeDownload(d),
      status: 'ready',
      jobId: d.jobId,
      filename: d.filename,
    }
  })
}

const INTERNAL_DOWNLOAD_LINK =
  /presentation_(?:full|meta)\.json|images_index\.json|\.vlm\.json|document_full\.json|speaker_notes\.md/i

/** LLM 常输出 sandbox: 伪链接；底栏已有真实下载卡片时改为简短提示。 */
export function softenSandboxDownloadLinks(text: string): string {
  let s = String(text || '')
  const hadSandbox = /sandbox:/i.test(s)

  s = s.replace(/\[([^\]]*)\]\(\s*sandbox:[^)]+\)/gi, (_m, label) => {
    const t = String(label || '').trim()
    if (/^下载[：:]/i.test(t)) return ''
    if (INTERNAL_DOWNLOAD_LINK.test(t)) return ''
    return t
  })

  s = s.replace(/^\s*[-*+]\s*.*sandbox:[^\n]*$/gim, '')
  s = s.replace(/^\s*\d+[.)]\s*.*sandbox:[^\n]*$/gim, '')
  s = s.replace(
    /^\s*[-*+]\s*\[[^\]]*(?:presentation_|\.vlm\.json|images_index)[^\]]*\]\([^)]+\)\s*$/gim,
    '',
  )
  s = s.replace(/\n{3,}/g, '\n\n').trim()

  if (hadSandbox && !/sandbox:/i.test(s) && !/见下方文件卡片/.test(s)) {
    s = s ? `${s}\n\n_已生成，见下方文件卡片。_` : '_已生成，见下方文件卡片。_'
  }
  return s
}

export function mergeGeneratedFiles(
  existing: DirectGeneratedFile[],
  incoming: DirectGeneratedFile[],
): DirectGeneratedFile[] {
  if (!incoming.length) return existing
  const seen = new Set(existing.map((f) => `${f.jobId}:${f.filename}`))
  const merged = [...existing]
  for (const f of incoming) {
    const key = `${f.jobId}:${f.filename}`
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(f)
  }
  return merged
}
