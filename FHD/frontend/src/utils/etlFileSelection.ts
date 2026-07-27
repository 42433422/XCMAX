export const ETL_FILE_ACCEPT =
  '.xlsx,.xlsm,.csv,.pdf,.jpg,.jpeg,.png,.doc,.docx,.ppt,.pptx'
export const ETL_MAX_FILE_BYTES = 100 * 1024 * 1024

const SUPPORTED_SUFFIXES = new Set(ETL_FILE_ACCEPT.split(','))

export type EtlSelectedSourceFile = {
  id: string
  file: File
  relativePath: string
  suffix: string
}

export type EtlIgnoredSourceFile = {
  name: string
  reason: 'unsupported' | 'too_large' | 'duplicate'
}

function normalizedRelativePath(file: File): string {
  const relativePath = String(
    (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
  )
    .replaceAll('\\', '/')
    .replace(/^\/+/, '')
    .split('/')
    .filter((part) => part && part !== '.' && part !== '..')
    .join('/')
  return (relativePath || file.name).slice(0, 500)
}

export function selectEtlSourceFiles(
  files: Iterable<File>,
  maxFileBytes: number,
): {
  accepted: EtlSelectedSourceFile[]
  ignored: EtlIgnoredSourceFile[]
  folderName: string
} {
  const accepted: EtlSelectedSourceFile[] = []
  const ignored: EtlIgnoredSourceFile[] = []
  const seen = new Set<string>()

  for (const file of files) {
    const relativePath = normalizedRelativePath(file)
    const suffixIndex = file.name.lastIndexOf('.')
    const suffix = suffixIndex >= 0 ? file.name.slice(suffixIndex).toLowerCase() : ''
    if (!SUPPORTED_SUFFIXES.has(suffix)) {
      ignored.push({ name: relativePath, reason: 'unsupported' })
      continue
    }
    if (file.size > maxFileBytes) {
      ignored.push({ name: relativePath, reason: 'too_large' })
      continue
    }
    const id = `${relativePath}\u0000${file.size}\u0000${file.lastModified}`
    if (seen.has(id)) {
      ignored.push({ name: relativePath, reason: 'duplicate' })
      continue
    }
    seen.add(id)
    accepted.push({ id, file, relativePath, suffix })
  }

  const firstPath = accepted[0]?.relativePath || ''
  const firstSlash = firstPath.indexOf('/')
  return {
    accepted,
    ignored,
    folderName: firstSlash > 0 ? firstPath.slice(0, firstSlash) : '',
  }
}

export function formatEtlBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}
