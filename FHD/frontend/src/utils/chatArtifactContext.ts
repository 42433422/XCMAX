import { apiFetch } from '@/utils/apiBase'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

const ATTACHMENTS_PATH = '/api/attachments/'
type ChatArtifactReference = { id?: string; uploadId?: string }
export type UploadedChatArtifact = ChatArtifactReference & { id: string; name: string }

export function createChatArtifactContext() {
  const pending = new Map<string, ChatArtifactReference>()
  let consumed = false
  let revision = 0

  function clearChatArtifactIds() {
    revision += 1
    pending.clear()
    consumed = false
  }
  function addChatArtifacts(artifacts: ChatArtifactReference[]) {
    if (consumed) clearChatArtifactIds()
    revision += 1
    for (const { id, uploadId } of artifacts) {
      const artifactId = id?.trim()
      const key = artifactId || uploadId
      if (key) pending.set(key, { id: artifactId, uploadId: uploadId || pending.get(key)?.uploadId })
    }
  }
  const listChatArtifactIds = () => [...pending.values()].flatMap(({ id }) => id ? [id] : [])
  function removeChatArtifactId(id: string | null | undefined) {
    if (pending.delete(String(id || '').trim())) revision += 1
  }
  function captureChatArtifacts() {
    // Only the original turn snapshot may reuse a submitted attachment.
    if (consumed) clearChatArtifactIds()
    consumed = pending.size > 0
    const submittedRevision = revision
    const uploadIds = [...new Set([...pending.values()].flatMap(({ uploadId }) => uploadId ? [uploadId] : []))]
    return { ids: listChatArtifactIds(), uploadIds, complete: () => { if (submittedRevision === revision) clearChatArtifactIds() } }
  }
  return { addChatArtifacts, listChatArtifactIds, removeChatArtifactId, clearChatArtifactIds, captureChatArtifacts }
}

export const {
  addChatArtifacts, listChatArtifactIds, removeChatArtifactId, clearChatArtifactIds, captureChatArtifacts,
} = createChatArtifactContext()

export async function uploadChatArtifactsDetailed(
  files: File[],
  isCurrent: () => boolean = () => true,
  addArtifacts = addChatArtifacts,
): Promise<UploadedChatArtifact[]> {
  if (!files.length) return []
  try {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    const response = await apiFetch(ATTACHMENTS_PATH, { method: 'POST', body: form })
    if (!response.ok) return []
    const body = asRecord(await response.json().catch(() => ({})))
    const rows = asArray<Record<string, unknown>>(body.results ?? body.items)
      .map((row, index) => {
        const artifact = asRecord(row.artifact)
        const uploadId = asString(artifact.elt_upload_id).trim()
        return {
          id: row.status === 'ok' ? asString(artifact.id).trim() : '',
          name: asString(row.name).trim() || asString(artifact.name).trim() || files[index]?.name || '附件',
          ...(uploadId ? { uploadId } : {}),
        }
      })
      .filter((row) => row.id)
    if (!isCurrent()) return []
    if (rows.length) addArtifacts(rows)
    return rows
  } catch {
    return []
  }
}

/** 并行上传（单批 multipart ``files``），返回成功工件 id；任何失败都静默。 */
export async function uploadChatArtifacts(files: File[]): Promise<string[]> {
  return (await uploadChatArtifactsDetailed(files)).map((row) => row.id)
}
