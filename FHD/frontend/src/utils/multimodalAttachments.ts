/**
 * 聊天多模态附件：转为后端 ``context.multimodal_attachments`` 所需的行结构。
 * 支持图片（jpeg/png/webp/gif）与 PDF（文本抽取由服务端完成）。
 * 格式与大小规则统一来自 ``documentIntake``，不再在此单独维护白名单。
 */

import { CONTEXT_MAX_BATCH_BYTES, CONTEXT_MAX_FILE_BYTES, CONTEXT_MAX_FILES, fileExtension, preflightDocuments } from './documentIntake'

export type MultimodalAttachmentRow = {
  kind: 'image' | 'pdf' | 'log'
  filename: string
  mime_type: string
  /** ``data:<mime>;base64,...`` */
  data_url: string
}

/** 浏览器端不用 ``mime-types``（其依赖 Node ``path``，会被 Vite 外部化并告警）。 */
const EXT_TO_MIME: Record<string, string> = {
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif': 'image/gif',
  '.pdf': 'application/pdf',
  '.log': 'text/plain',
  '.txt': 'text/plain',
}

function resolveMime(file: File): string {
  const t = (file.type || '').trim().toLowerCase()
  if (t) return t
  return EXT_TO_MIME[fileExtension(file.name)] || 'application/octet-stream'
}

function readAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader()
    fr.onload = () => resolve(String(fr.result || ''))
    fr.onerror = () => reject(fr.error || new Error('read failed'))
    fr.readAsDataURL(file)
  })
}

export async function filesToMultimodalRows(
  files: FileList | File[],
  options?: { skipUnsupported?: boolean },
): Promise<{ ok: true; rows: MultimodalAttachmentRow[] } | { ok: false; error: string }> {
  const arr = Array.from(files as FileList)
  if (!arr.length) return { ok: false, error: '未选择文件' }
  const report = preflightDocuments(arr, 'context')
  if (arr.length > CONTEXT_MAX_FILES) {
    return { ok: false, error: `一次最多 ${CONTEXT_MAX_FILES} 个文件` }
  }
  for (const item of report.skipped) {
    if (options?.skipUnsupported) continue
    if (item.reason === 'too_large') {
      const isBatch = item.detail.startsWith('本批')
      const limit = isBatch ? CONTEXT_MAX_BATCH_BYTES : CONTEXT_MAX_FILE_BYTES
      return {
        ok: false,
        error: isBatch
          ? `附件总大小超过 ${Math.round(limit / (1024 * 1024))}MB 上限`
          : `「${item.name}」超过 ${Math.round(limit / (1024 * 1024))}MB 上限`,
      }
    }
    return {
      ok: false,
      error: `不支持的扩展名: ${fileExtension(item.name) || '(无)'}（允许: .png, .jpg, .jpeg, .webp, .gif, .pdf, .log, .txt）`,
    }
  }

  const rows: MultimodalAttachmentRow[] = []
  for (const file of report.accepted) {
    const mime = resolveMime(file)
    const ext = fileExtension(file.name)
    const isLog = ext === '.log' || ext === '.txt'
    if (!isLog && mime !== 'application/pdf' && !mime.startsWith('image/')) {
      if (options?.skipUnsupported) continue
      return { ok: false, error: `不支持的类型: ${mime}（${file.name}）` }
    }
    const dataUrl = await readAsDataURL(file)
    if (!dataUrl.startsWith('data:')) {
      return { ok: false, error: `读取失败: ${file.name}` }
    }
    const kind: MultimodalAttachmentRow['kind'] = isLog ? 'log' : mime === 'application/pdf' ? 'pdf' : 'image'
    rows.push({
      kind,
      filename: String((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name) || (kind === 'pdf' ? 'upload.pdf' : 'image.bin'),
      mime_type: mime,
      data_url: dataUrl,
    })
  }
  if (!rows.length) return { ok: false, error: '所选文件中没有可暂存的附件（支持图片、PDF、TXT、LOG）' }
  return { ok: true, rows }
}
