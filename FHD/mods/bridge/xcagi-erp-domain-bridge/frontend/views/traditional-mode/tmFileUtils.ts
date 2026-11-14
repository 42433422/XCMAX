import type { FileInfo } from '@/api/traditional'

export type ExplorerViewMode = 'details' | 'icons' | 'large'

export type SortKey = 'name' | 'size' | 'modified' | 'type'

export function getExtension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.substring(dot + 1) : ''
}

export function isImageFile(file: FileInfo): boolean {
  const ext = getExtension(file.name).toLowerCase()
  return ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'].includes(ext)
}

export function isExcelFile(file: FileInfo): boolean {
  const ext = getExtension(file.name).toLowerCase()
  return ['xlsx', 'xls', 'xlsm'].includes(ext)
}

export function getFileIcon(file: FileInfo): string {
  const ext = getExtension(file.name).toLowerCase()
  if (['xlsx', 'xls', 'xlsm'].includes(ext)) return '📄'
  if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'].includes(ext)) return '🖼'
  if ((['pdf'] as string[]).includes(ext)) return '📕'
  if (['doc', 'docx'].includes(ext)) return '📝'
  if (['txt', 'csv', 'log'].includes(ext)) return '📃'
  return '📄'
}

export function formatSize(size: number): string {
  if (!size || size <= 0) return '-'
  if (size < 1024) return size + ' B'
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + ' KB'
  return (size / (1024 * 1024)).toFixed(1) + ' MB'
}

export function formatTime(time: string): string {
  if (!time) return '-'
  try {
    const d = new Date(time)
    return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return time
  }
}

export function buildFileFingerprint(file: FileInfo): string {
  const sz = Number(file.size) || 0
  const mt = String(file.modified_time || '').trim()
  return `${sz}|${mt}`
}
