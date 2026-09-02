/** execute-file / execute 响应信封展平与 direct_python 载荷提取（原 tabularReadEmployees 单体拆分） */

export type EmployeeExecuteDiagnostics = {
  success: boolean
  error: string
  summary: string
  warnings: string[]
}

function mergeOutputDownloadsField(...candidates: unknown[]): unknown[] | undefined {
  const merged: unknown[] = []
  const seen = new Set<string>()
  for (const raw of candidates) {
    if (!Array.isArray(raw)) continue
    for (const item of raw) {
      const key = item && typeof item === 'object' ? JSON.stringify(item) : String(item)
      if (seen.has(key)) continue
      seen.add(key)
      merged.push(item)
    }
  }
  return merged.length ? merged : undefined
}

/** execute-file 常返回 { employee_id, result: { outputs, ... }, output_downloads, llm_context_text }，统一展平。 */
export function normalizeEmployeeExecuteEnvelope(result: unknown): Record<string, unknown> {
  if (!result || typeof result !== 'object') return {}
  const root = result as Record<string, unknown>
  const inner = root.result
  if (!inner || typeof inner !== 'object' || Array.isArray(inner)) return root
  const nested = inner as Record<string, unknown>
  return {
    ...nested,
    ...root,
    outputs: root.outputs ?? nested.outputs,
    output_downloads: mergeOutputDownloadsField(
      root.output_downloads,
      root.outputDownloads,
      nested.output_downloads,
      nested.outputDownloads,
      root.downloads,
      nested.downloads,
    ),
    llm_context_text: root.llm_context_text ?? nested.llm_context_text,
    ok: root.ok ?? nested.ok,
    error: root.error ?? nested.error,
    summary: root.summary ?? nested.summary,
  }
}

/** 首个成功的 direct_python output 载荷（含 paragraph_count / items 等）。 */
export function extractDirectPythonPayload(result: unknown): Record<string, unknown> | null {
  const r = normalizeEmployeeExecuteEnvelope(result)
  const outputs = Array.isArray(r.outputs) ? r.outputs : []
  for (const item of outputs) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    if (row.ok === false) continue
    const out = row.output
    if (!out || typeof out !== 'object') continue
    const o = out as Record<string, unknown>
    if (o.ok === false) continue
    return o
  }
  return null
}
