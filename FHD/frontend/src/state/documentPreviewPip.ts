import { reactive } from 'vue'
import { buildFullApiUrl } from '@/api/core'

export type DocumentPreviewKind = 'pdf' | 'image' | 'word' | 'excel' | 'office'

export const documentPreviewPip = reactive({
  visible: false,
  minimized: false,
  title: '生成文档',
  summary: '',
  url: '',
  kind: 'office' as DocumentPreviewKind,
  fileName: '',
  mimeType: '',
  previewRows: [] as string[][],
})

let ownedBlobUrl = ''

function releaseOwnedBlobUrl() {
  if (ownedBlobUrl) {
    URL.revokeObjectURL(ownedBlobUrl)
    ownedBlobUrl = ''
  }
}

function inferKind(fileName: string, mimeType: string): DocumentPreviewKind {
  const hint = `${fileName} ${mimeType}`.toLowerCase()
  if (/\.pdf\b|application\/pdf/.test(hint)) return 'pdf'
  if (/image\//.test(hint) || /\.(png|jpe?g|gif|webp|svg)\b/.test(hint)) return 'image'
  if (/\.docx?\b|wordprocessingml|msword/.test(hint)) return 'word'
  if (/\.xlsx?\b|spreadsheetml|ms-excel/.test(hint)) return 'excel'
  return 'office'
}

function showPreview(input: { title?: string; summary?: string; url: string; fileName?: string; mimeType?: string }) {
  const fileName = String(input.fileName || input.title || '生成文档').trim()
  const mimeType = String(input.mimeType || '').trim()
  Object.assign(documentPreviewPip, {
    visible: true,
    minimized: false,
    title: String(input.title || fileName || '生成文档').trim(),
    summary: String(input.summary || '').trim(),
    url: input.url,
    kind: inferKind(fileName, mimeType),
    fileName,
    mimeType,
    previewRows: [],
  })
}

async function hydrateExcelPreview(blob: Blob) {
  try {
    const XLSX = await import('xlsx')
    const workbook = XLSX.read(await blob.arrayBuffer(), { type: 'array' })
    const firstSheetName = workbook.SheetNames[0]
    if (!firstSheetName) return
    const rows = XLSX.utils.sheet_to_json(workbook.Sheets[firstSheetName], {
      header: 1,
      raw: false,
      defval: '',
    }) as unknown[][]
    documentPreviewPip.previewRows = rows
      .slice(0, 30)
      .map((row) => (Array.isArray(row) ? row.slice(0, 12).map((cell) => String(cell ?? '')) : []))
  } catch {
    documentPreviewPip.previewRows = []
  }
}

export function openDocumentPreviewFromBlob(blob: Blob, fileName: string, summary = '') {
  releaseOwnedBlobUrl()
  ownedBlobUrl = URL.createObjectURL(blob)
  showPreview({
    title: fileName,
    fileName,
    mimeType: blob.type,
    summary,
    url: ownedBlobUrl,
  })
  if (documentPreviewPip.kind === 'excel') void hydrateExcelPreview(blob)
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function findDocumentCandidate(value: unknown, depth = 0): Record<string, unknown> | null {
  if (depth > 6) return null
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findDocumentCandidate(item, depth + 1)
      if (found) return found
    }
    return null
  }
  const row = asRecord(value)
  if (!Object.keys(row).length) return null
  const fileName = String(row.file_name || row.filename || row.name || '').trim()
  const mimeType = String(row.mime_type || row.content_type || '').trim()
  const url = String(row.preview_url || row.download_url || row.file_url || '').trim()
  const artifactType = String(row.artifact_type || row.type || '').toLowerCase()
  const documentHint = `${fileName} ${mimeType} ${artifactType} ${url}`
  if (url && /(document|office|pdf|word|excel|docx|xlsx|\.pdf\b|\.docx?\b|\.xlsx?\b)/i.test(documentHint)) {
    return row
  }
  for (const nested of Object.values(row)) {
    const found = findDocumentCandidate(nested, depth + 1)
    if (found) return found
  }
  return null
}

export function openDocumentPreviewFromResult(result: unknown): boolean {
  const candidate = findDocumentCandidate(result)
  if (!candidate) return false
  const rawUrl = String(candidate.preview_url || candidate.download_url || candidate.file_url || '').trim()
  if (!rawUrl) return false
  const fileName = String(candidate.file_name || candidate.filename || candidate.name || '生成文档')
  const mimeType = String(candidate.mime_type || candidate.content_type || '')
  const summary = String(candidate.summary || candidate.message || '')
  showPreview({
    title: fileName,
    fileName,
    mimeType,
    summary,
    url: /^(blob:|data:|https?:\/\/)/i.test(rawUrl) ? rawUrl : buildFullApiUrl(rawUrl),
  })
  return true
}

export function minimizeDocumentPreview() {
  documentPreviewPip.minimized = true
}

export function expandDocumentPreview() {
  documentPreviewPip.minimized = false
}

export function closeDocumentPreview() {
  documentPreviewPip.visible = false
  releaseOwnedBlobUrl()
  documentPreviewPip.url = ''
}
