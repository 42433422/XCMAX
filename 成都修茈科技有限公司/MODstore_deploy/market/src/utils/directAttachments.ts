export const DIRECT_KB_SUPPORTED_EXTENSIONS = ['txt', 'md', 'json', 'csv', 'pdf', 'docx', 'xlsx'] as const
export const EMPLOYEE_SPREADSHEET_EXTRA_EXTENSIONS = ['xlsm', 'xls', 'doc', 'ppt', 'pptx'] as const
/** 一档/二档附件可选的文档扩展名（含仅「给员工处理」支持的表格类型）。 */
export const DIRECT_ATTACH_DOC_EXTENSIONS = [...DIRECT_KB_SUPPORTED_EXTENSIONS, ...EMPLOYEE_SPREADSHEET_EXTRA_EXTENSIONS] as const
export const DIRECT_KB_SUPPORTED_EXT = new Set<string>(DIRECT_KB_SUPPORTED_EXTENSIONS)
export const DIRECT_ATTACH_DOC_EXT = new Set<string>(DIRECT_ATTACH_DOC_EXTENSIONS)
export const DIRECT_ATTACHMENT_ACCEPT = DIRECT_ATTACH_DOC_EXTENSIONS.map((ext) => `.${ext}`).join(',')
export const DIRECT_KB_MAX_BYTES = 20 * 1024 * 1024
/** 与网关 / 员工 execute-file 上限对齐（默认 100MB），大表走员工通道而非知识抽取。 */
export const DIRECT_EMPLOYEE_FILE_MAX_BYTES = 100 * 1024 * 1024

/** 工作台一档附件：知识库支持的文档 + 可走视觉的多模态图片（不入向量库，压缩后以 data URL 发送）。 */
export const VISION_IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'] as const
export const DIRECT_AND_VISION_ACCEPT = [...DIRECT_ATTACH_DOC_EXTENSIONS, ...VISION_IMAGE_EXTENSIONS]
  .map((ext) => `.${ext}`)
  .join(',')

/** .xlsx / .xlsm / .xls — 可标为「给员工处理」并由 multipart execute-file 提交。 */
export function isEmployeeSpreadsheetExt(ext: string): boolean {
  const e = String(ext || '')
    .trim()
    .toLowerCase()
    .replace(/^\./, '')
  return e === 'xlsx' || e === 'xlsm' || e === 'xls'
}

export { isEmployeeExecuteFileExt, resolveReadEmployeeForExtension } from './tabularReadEmployees'

export type DirectAttachmentStatus = 'uploading' | 'ready' | 'inline' | 'error' | 'skipped'
export type DirectAttachmentKind = 'excel' | 'pdf' | 'word' | 'ppt' | 'csv' | 'json' | 'text' | 'file' | 'vision'

export interface DirectAttachmentOutcome {
  status: 'ready' | 'inline' | 'error'
  canSend: boolean
  extractedText: string
  docId: string
  error: string
  ingestError: string
}

export function formatDirectFileSize(size: number): string {
  const n = Number(size || 0)
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function directFileExt(filename: string): string {
  const s = String(filename || '')
  const i = s.lastIndexOf('.')
  if (i < 0 || i >= s.length - 1) return ''
  return s.slice(i + 1).toLowerCase()
}

export function directFileKind(filename: string, mime = ''): DirectAttachmentKind {
  const ext = directFileExt(filename)
  if (ext === 'xlsx' || ext === 'xlsm' || ext === 'xls') return 'excel'
  if (ext === 'pdf') return 'pdf'
  if (ext === 'docx') return 'word'
  if (ext === 'pptx' || ext === 'ppt') return 'ppt'
  if (ext === 'csv') return 'csv'
  if (ext === 'json') return 'json'
  if (ext === 'txt' || ext === 'md' || String(mime).startsWith('text/')) return 'text'
  return 'file'
}

export function directFileKindLabel(kind: DirectAttachmentKind): string {
  switch (kind) {
    case 'excel':
      return 'Excel'
    case 'pdf':
      return 'PDF'
    case 'word':
      return 'Word'
    case 'ppt':
      return 'PPT'
    case 'csv':
      return 'CSV'
    case 'json':
      return 'JSON'
    case 'text':
      return 'Text'
    case 'vision':
      return 'Image'
    default:
      return 'File'
  }
}

export function normalizeDirectAttachmentError(error: unknown, fallback = '上传失败'): string {
  const raw =
    typeof error === 'string'
      ? error
      : error && typeof error === 'object' && 'message' in error
        ? String((error as { message?: unknown }).message || '')
        : ''
  const text = raw.trim() || fallback
  if (/openpyxl/i.test(text)) return '服务器缺少 openpyxl，暂不能解析 Excel；请重新安装 knowledge 依赖后再试'
  if (/pypdf/i.test(text)) return '服务器缺少 pypdf，暂不能解析 PDF；请重新安装 knowledge 依赖后再试'
  if (/python-docx|docx/i.test(text)) return '服务器缺少 python-docx，暂不能解析 Word；请重新安装 knowledge 依赖后再试'
  if (/internal server error/i.test(text)) return '资料库入库失败，已直接读取附件内容'
  if (/MODSTORE_EMBEDDING_API_KEY|Embedding Key|无法构建向量库/i.test(text)) return '已读取文件内容，未写入向量库'
  if (/有效文本|empty|文本分块为空/i.test(text)) return '未能从文件中提取有效文本，请确认文件不是空表或扫描图片'
  return text
}

export function resolveDirectAttachmentOutcome(input: {
  extractedText?: unknown
  docId?: unknown
  extractError?: unknown
  uploadError?: unknown
}): DirectAttachmentOutcome {
  const extractedText = String(input.extractedText || '').trim()
  if (!extractedText) {
    return {
      status: 'error',
      canSend: false,
      extractedText: '',
      docId: '',
      error: normalizeDirectAttachmentError(input.extractError, '未能从文件中提取有效文本'),
      ingestError: '',
    }
  }

  const docId = String(input.docId || '').trim()
  if (docId) {
    return {
      status: 'ready',
      canSend: true,
      extractedText,
      docId,
      error: '',
      ingestError: '',
    }
  }

  return {
    status: 'inline',
    canSend: true,
    extractedText,
    docId: '',
    error: '',
    ingestError: input.uploadError
      ? normalizeDirectAttachmentError(input.uploadError, '资料库入库失败，已改为直接读取附件内容')
      : '',
  }
}
