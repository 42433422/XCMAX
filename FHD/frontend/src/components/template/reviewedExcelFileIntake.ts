/** Pick, drop, and append workbooks without growing the reviewed-template screen. */

const WORKBOOK_NAME = /\.(xlsx|xls|docx)$/i

export const BATCH_BYTE_LIMIT = 50 * 1024 * 1024

export function importableWorkbook(file: File) {
  return WORKBOOK_NAME.test(file.name) && !file.name.startsWith('~$')
}

export function batchBytes(items: File[]) {
  return items.reduce((sum, item) => sum + item.size, 0)
}

export function armFileInput(input: HTMLInputElement | null | undefined, folder: boolean, allowed: boolean) {
  if (!allowed || !input) return
  if (folder) input.setAttribute('webkitdirectory', '')
  else input.removeAttribute('webkitdirectory')
  input.multiple = true
  input.click()
}

export function stageChosenFiles(incoming: File[], existing: File[], existingKeys: string[], canAppend: boolean) {
  if (canAppend && existing.length) {
    const next = [...existing, ...incoming]
    if (next.length > 200) {
      return { files: existing, keys: existingKeys, appended: false, error: '一次最多上传 200 个文件，请分批上传' }
    }
    if (batchBytes(next) > BATCH_BYTE_LIMIT) {
      return { files: existing, keys: existingKeys, appended: false, error: '本批文件超过 50 MB，请分批上传' }
    }
    const kept = existing.map((_, index) => existingKeys[index] || crypto.randomUUID())
    return { files: next, keys: [...kept, ...incoming.map(() => crypto.randomUUID())], appended: true, error: '' }
  }
  return { files: incoming, keys: incoming.map(() => crypto.randomUUID()), appended: false, error: '' }
}

function entryFile(entry: FileSystemFileEntry) {
  return new Promise<File>((resolve, reject) => entry.file(resolve, () => reject(new Error('unreadable'))))
}

async function collectEntry(entry: FileSystemEntry, found: File[]) {
  if (found.length > 200) return
  if (entry.isFile) {
    const file = await entryFile(entry as FileSystemFileEntry)
    if (importableWorkbook(file)) found.push(file)
    return
  }
  if (!entry.isDirectory) return
  const reader = (entry as FileSystemDirectoryEntry).createReader()
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) => {
      reader.readEntries(resolve, () => reject(new Error('unreadable')))
    })
    if (!batch.length) return
    for (const child of batch) {
      await collectEntry(child, found)
      if (found.length > 200) return
    }
  }
}

export async function readComposerDrop(event: DragEvent) {
  const entries = Array.from(event.dataTransfer?.items || []).flatMap((item) => {
    const entry = item.webkitGetAsEntry?.()
    return entry ? [entry] : []
  })
  const folder = entries.some((entry) => entry.isDirectory)
  const files: File[] = []
  try {
    if (folder) {
      for (const entry of entries) {
        await collectEntry(entry, files)
        if (files.length > 200) break
      }
    } else {
      for (const file of Array.from(event.dataTransfer?.files || [])) {
        if (importableWorkbook(file)) files.push(file)
      }
    }
  } catch {
    return { files: [], error: '文件夹没有读完，请改为选择其中的文件' }
  }
  if (!files.length) {
    return {
      files,
      error: folder
        ? '文件夹里没有 Excel 或对账单 Word（.xlsx / .xls / .docx）'
        : '请拖入 Excel 或对账单 Word（.xlsx / .xls / .docx）',
    }
  }
  return { files, error: '' }
}

export function readFileInput(input: HTMLInputElement) {
  const folder = input.hasAttribute('webkitdirectory')
  const files = Array.from(input.files || []).filter((item) => !folder || importableWorkbook(item))
  input.value = ''
  input.removeAttribute('webkitdirectory')
  if (folder && !files.length) {
    return { files, error: '文件夹里没有 Excel 或对账单 Word（.xlsx / .xls / .docx）' }
  }
  return { files, error: '' }
}
