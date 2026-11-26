import { asArray, asRecord, asString } from '@/utils/typeGuards'

export interface AgentArtifactDownload {
  run_id: string
  artifact_id: string
  name: string
  uri: string
  artifact_type: 'file' | 'office_document'
}

const artifactIdPattern = /^[A-Za-z0-9_-]{1,160}$/

export function readAgentArtifactDownloads(value: unknown, expectedRunId?: string): AgentArtifactDownload[] {
  const files = new Map<string, AgentArtifactDownload>()
  for (const raw of asArray(value)) {
    const row = asRecord(raw)
    const runId = expectedRunId ?? asString(row.run_id)
    const artifactId = asString(row.artifact_id)
    if (!artifactIdPattern.test(runId) || !artifactIdPattern.test(artifactId)) continue
    if (row.artifact_type !== 'file' && row.artifact_type !== 'office_document') continue
    const uri = `/api/agent/runs/${runId}/artifacts/${artifactId}`
    if (row.uri !== uri) continue
    files.set(uri, { run_id: runId, artifact_id: artifactId, uri,
      artifact_type: row.artifact_type, name: asString(row.name).trim() || '报表.xlsx' })
  }
  return [...files.values()]
}

export function readRuntimeOutputDownloads(payload: unknown): AgentArtifactDownload[] {
  const result = asRecord(payload)
  return result.success === true ? readAgentArtifactDownloads(asRecord(result.data).output_artifacts) : []
}
