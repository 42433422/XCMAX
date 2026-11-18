/**
 * 本轮对话的附件工件上下文：选文件后把文件上传到 ``/api/attachments`` 收集工件 id，
 * 发送消息时随 ``context.artifact_ids`` 交给后端取数，发送成功后清空。
 * 上传失败全部静默，不影响现有解析 / 摘要流程。
 */
import { apiFetch } from '@/utils/apiBase'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

const ATTACHMENTS_PATH = '/api/attachments/'

const pendingArtifactIds = new Set<string>()

// 本轮 id 是否已经被一次请求带走。之后的「重新上传」或「非重试的新消息」
// 都算新一轮，必须丢弃上一轮失败留下的残留，避免历史工件串进本次导入。
let consumedByRequest = false
let artifactRevision = 0

/** 收集工件 id（去重）。重新上传时以本批为准，不继承上一轮残留。 */
export function addChatArtifactIds(ids: Array<string | null | undefined>): void {
  artifactRevision += 1
  if (consumedByRequest) {
    pendingArtifactIds.clear()
    consumedByRequest = false
  }
  for (const id of ids) {
    const value = String(id || '').trim()
    if (value) pendingArtifactIds.add(value)
  }
}

/** 本轮待发送的工件 id（只读快照，不改动轮次状态）。 */
export function listChatArtifactIds(): string[] {
  return [...pendingArtifactIds]
}

/**
 * 取本次请求要提交的工件 id。
 * 重试沿用上一轮已经带过的工件；非重试的新消息只认本轮新上传的文件。
 */
export function takeChatArtifactIds(options: { retry?: boolean } = {}): string[] {
  if (consumedByRequest && !options.retry) {
    pendingArtifactIds.clear()
    consumedByRequest = false
  }
  return [...pendingArtifactIds]
}

/** 请求已带上本轮工件：在其成功清空前，不能再把它算作「本轮新上传」。 */
export function markChatArtifactsConsumed(): void {
  consumedByRequest = pendingArtifactIds.size > 0
}

/** 移除单个待发送工件：输入框里删掉芯片后，这条 id 不应再随下一条消息提交。 */
export function removeChatArtifactId(id: string | null | undefined): void {
  const value = String(id || '').trim()
  if (value && pendingArtifactIds.delete(value)) artifactRevision += 1
}

/** 发送成功后清空本轮工件 id。 */
export function clearChatArtifactIds(): void {
  artifactRevision += 1
  pendingArtifactIds.clear()
  consumedByRequest = false
}

/** 捕获实际提交批次；迟到完成不能清掉后来上传（即使 id 相同）的附件。 */
export function captureChatArtifacts() {
  const ids = takeChatArtifactIds()
  markChatArtifactsConsumed()
  const revision = artifactRevision
  return {
    ids,
    complete: () => {
      if (revision === artifactRevision) clearChatArtifactIds()
    },
  }
}

export type UploadedChatArtifact = { id: string; name: string }

/** 并行上传（单批 multipart ``files``），返回成功的工件 id 与展示名；任何失败都静默。 */
export async function uploadChatArtifactsDetailed(files: File[]): Promise<UploadedChatArtifact[]> {
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
    addChatArtifactIds(rows.map((row) => row.id))
    return rows
  } catch {
    return []
  }
}

/** 并行上传（单批 multipart ``files``），返回成功工件 id；任何失败都静默。 */
export async function uploadChatArtifacts(files: File[]): Promise<string[]> {
  return (await uploadChatArtifactsDetailed(files)).map((row) => row.id)
}
