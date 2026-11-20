/**
 * 本轮对话的附件工件上下文：选文件后把文件上传到 ``/api/attachments`` 收集工件 id，
 * 发送消息时随 ``context.artifact_ids`` 交给后端取数，发送成功后清空。
 * 上传失败全部静默，不影响现有解析 / 摘要流程。
 */
import { apiFetch } from '@/utils/apiBase'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

const ATTACHMENTS_PATH = '/api/attachments/'

export function createChatArtifactContext() {
  const pending = new Set<string>()
  let consumed = false
  let revision = 0

  function clearChatArtifactIds() {
    revision += 1
    pending.clear()
    consumed = false
  }
  function addChatArtifactIds(ids: Array<string | null | undefined>) {
    if (consumed) clearChatArtifactIds()
    revision += 1
    for (const id of ids) {
      const value = String(id || '').trim()
      if (value) pending.add(value)
    }
  }
  const listChatArtifactIds = () => [...pending]
  function takeChatArtifactIds(options: { retry?: boolean } = {}) {
    if (consumed && !options.retry) clearChatArtifactIds()
    return listChatArtifactIds()
  }
  function markChatArtifactsConsumed() { consumed = pending.size > 0 }
  function removeChatArtifactId(id: string | null | undefined) {
    if (pending.delete(String(id || '').trim())) revision += 1
  }
  function captureChatArtifacts() {
    const ids = takeChatArtifactIds()
    markChatArtifactsConsumed()
    const submittedRevision = revision
    return { ids, complete: () => { if (submittedRevision === revision) clearChatArtifactIds() } }
  }
  return {
    addChatArtifactIds, listChatArtifactIds, takeChatArtifactIds, markChatArtifactsConsumed,
    removeChatArtifactId, clearChatArtifactIds, captureChatArtifacts,
  }
}

export const {
  addChatArtifactIds, listChatArtifactIds, takeChatArtifactIds, markChatArtifactsConsumed,
  removeChatArtifactId, clearChatArtifactIds, captureChatArtifacts,
} = createChatArtifactContext()

export type UploadedChatArtifact = { id: string; name: string }

/** 并行上传（单批 multipart ``files``），返回成功的工件 id 与展示名；任何失败都静默。 */
export async function uploadChatArtifactsDetailed(
  files: File[],
  isCurrent: () => boolean = () => true,
  addArtifacts = addChatArtifactIds,
): Promise<UploadedChatArtifact[]> {
  if (!files.length) return []
  try {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    const response = await apiFetch(ATTACHMENTS_PATH, { method: 'POST', body: form })
    if (!response.ok) return []
    const body = asRecord(await response.json().catch(() => ({})))
    const rows = asArray<Record<string, unknown>>(body.results ?? body.items)
      .filter((row) => asString(row.status) === 'ok')
      .map((row, index) => {
        const artifact = asRecord(row.artifact)
        return {
          id: asString(artifact.id).trim(),
          name: asString(artifact.name).trim() || files[index]?.name || '附件',
        }
      })
      .filter((row) => row.id)
    if (!isCurrent()) return []
    if (rows.length) addArtifacts(rows.map((row) => row.id))
    return rows
  } catch {
    return []
  }
}

/** 并行上传（单批 multipart ``files``），返回成功工件 id；任何失败都静默。 */
export async function uploadChatArtifacts(files: File[]): Promise<string[]> {
  return (await uploadChatArtifactsDetailed(files)).map((row) => row.id)
}
