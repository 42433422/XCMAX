import { sha256 } from '@noble/hashes/sha2.js'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

export interface AgentArtifactDownload {
  run_id: string
  artifact_id: string
  name: string
  uri: string
  artifact_type: 'file' | 'office_document'
  metadata?: { sha256: string; size_bytes?: number }
}

const artifactIdPattern = /^[A-Za-z0-9_-]{1,160}$/
const sha256Pattern = /^[0-9a-f]{64}$/

export function readAgentArtifactDownloads(value: unknown, expectedRunId?: string): AgentArtifactDownload[] {
  const files = new Map<string, AgentArtifactDownload>()
  for (const raw of asArray(value)) {
    const row = asRecord(raw)
    const runId = expectedRunId ?? asString(row.run_id)
    const artifactId = asString(row.artifact_id)
    if (row.run_id !== undefined && row.run_id !== runId) continue
    if (!artifactIdPattern.test(runId) || !artifactIdPattern.test(artifactId)) continue
    if (row.artifact_type !== 'file' && row.artifact_type !== 'office_document') continue
    const uri = `/api/agent/runs/${runId}/artifacts/${artifactId}`
    if (row.uri !== uri) continue
    const integrity = asRecord(row.metadata)
    if (integrity.run_id !== undefined && integrity.run_id !== runId) continue
    const digest = asString(integrity.sha256), size = integrity.size_bytes
    if (integrity.sha256 !== undefined && !sha256Pattern.test(digest)) continue
    if (size !== undefined && (typeof size !== 'number' || !Number.isSafeInteger(size) || size < 0)) continue
    files.set(uri, { run_id: runId, artifact_id: artifactId, uri,
      artifact_type: row.artifact_type, name: asString(row.name).trim() || '报表.xlsx',
      ...(digest ? { metadata: { sha256: digest, ...(typeof size === 'number' ? { size_bytes: size } : {}) } } : {}) })
  }
  return [...files.values()]
}

export function readRuntimeOutputDownloads(payload: unknown): AgentArtifactDownload[] {
  const result = asRecord(payload)
  return result.success === true ? readAgentArtifactDownloads(asRecord(result.data).output_artifacts) : []
}

export class ArtifactDownloadIntegrityError extends Error {
  constructor() { super('文件未通过完整性核验，请刷新原任务回执后重试。') }
}

export async function verifiedArtifactDownload(response: Response, file: AgentArtifactDownload): Promise<Blob> {
  if (!response.ok) throw new Error('Artifact download failed')
  const receipt = file.metadata?.sha256
  const served = response.headers.get('X-Artifact-SHA256')
  const expected = receipt ?? served
  if (!expected || !sha256Pattern.test(expected)) throw new ArtifactDownloadIntegrityError()
  const bytes = await response.arrayBuffer()
  const digest = sha256(new Uint8Array(bytes))
  const actual = Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join('')
  const size = file.metadata?.size_bytes
  const servedSize = response.headers.get('X-Artifact-Size')
  if (actual !== expected || (served !== null && served !== actual)
    || (size !== undefined && size !== bytes.byteLength)
    || (servedSize !== null && servedSize !== String(bytes.byteLength))) throw new ArtifactDownloadIntegrityError()
  return new Blob([bytes], { type: response.headers.get('Content-Type') || 'application/octet-stream' })
}
