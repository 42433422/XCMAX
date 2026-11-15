/**
 * 本轮对话的附件工件上下文：选文件后把文件上传到 ``/api/attachments`` 收集工件 id，
 * 发送消息时随 ``context.artifact_ids`` 交给后端取数，发送成功后清空。
 * 上传失败全部静默，不影响现有解析 / 摘要流程。
 */
import { apiFetch } from '@/utils/apiBase'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

const ATTACHMENTS_PATH = '/api/attachments/'

const pendingArtifactIds = new Set<string>()

/** 收集工件 id（去空、去重）。 */
export function addChatArtifactIds(ids: Array<string | null | undefined>): void {
  for (const id of ids) {
    const value = String(id || '').trim()
    if (value) pendingArtifactIds.add(value)
  }
}

/** 本轮待发送的工件 id（不清空，发送失败可重试）。 */
export function listChatArtifactIds(): string[] {
  return [...pendingArtifactIds]
}

/** 发送成功后清空本轮工件 id。 */
export function clearChatArtifactIds(): void {
  pendingArtifactIds.clear()
}

/** 并行上传（单批 multipart ``files``），返回成功工件 id；任何失败都静默。 */
export async function uploadChatArtifacts(files: File[]): Promise<string[]> {
  if (!files.length) return []
  try {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    const response = await apiFetch(ATTACHMENTS_PATH, { method: 'POST', body: form })
    if (!response.ok) return []
    const body = asRecord(await response.json().catch(() => ({})))
    const ids = asArray<Record<string, unknown>>(body.results ?? body.items)
      .filter((row) => asString(row.status) === 'ok')
      .map((row) => asString(asRecord(row.artifact).id).trim())
      .filter(Boolean)
    addChatArtifactIds(ids)
    return ids
  } catch {
    return []
  }
}
