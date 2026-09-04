import { apiFetch } from '@/utils/apiBase'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

export type AiModDeliveryProgress = {
  sessionId: string
  status: string
  label: string
  snapshot: Record<string, unknown>
}

export type AiModDeliveryResult = {
  sessionId: string
  modId: string
  installMessage: string
  snapshot: Record<string, unknown>
}

const AI_MOD_PATTERNS = [
  /(?:帮我|给我|为我)?(?:做|生成|创建|开发|定制).{0,18}(?:mod|MOD|模块|小程序|工具|应用|系统|审批流|工作流)/,
  /(?:mod|MOD|模块|审批流|工作流).{0,18}(?:做|生成|创建|开发|定制)/,
]

export function aiModBriefFromChat(text: string): string {
  const brief = String(text || '').trim()
  if (brief.length < 3 || !AI_MOD_PATTERNS.some((pattern) => pattern.test(brief))) return ''
  return brief
}

async function responseData(path: string, init?: RequestInit): Promise<Record<string, unknown>> {
  const response = await apiFetch(path, init)
  const payload = asRecord(await response.json().catch(() => ({})))
  if (!response.ok || payload.success === false) {
    throw new Error(asString(payload.detail || payload.message) || `HTTP ${response.status}`)
  }
  return asRecord(payload.data || payload)
}

function progressLabel(snapshot: Record<string, unknown>): string {
  const steps = asArray<Record<string, unknown>>(snapshot.steps)
  const running = steps.find((step) => asString(step.status) === 'running')
  if (running) return asString(running.message || running.label || running.name) || '正在生成 MOD…'
  const lastDone = [...steps].reverse().find((step) => asString(step.status) === 'done')
  return asString(lastDone?.message || lastDone?.label || lastDone?.name) || '正在生成 MOD…'
}

export async function startAiModDelivery(brief: string): Promise<{ sessionId: string }> {
  const data = await responseData('/api/mod-store/ai-delivery/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ brief }),
  })
  const sessionId = asString(data.session_id).trim()
  if (!sessionId) throw new Error('MOD 生成会话缺少 session_id')
  return { sessionId }
}

export async function getAiModDeliveryProgress(sessionId: string): Promise<AiModDeliveryProgress> {
  const snapshot = await responseData(`/api/mod-store/ai-delivery/sessions/${encodeURIComponent(sessionId)}`)
  return {
    sessionId,
    status: asString(snapshot.status || 'running'),
    label: progressLabel(snapshot),
    snapshot,
  }
}

export async function installAiModDelivery(sessionId: string): Promise<{ message: string; data: Record<string, unknown> }> {
  const response = await apiFetch(`/api/mod-store/ai-delivery/sessions/${encodeURIComponent(sessionId)}/install`, { method: 'POST' })
  const payload = asRecord(await response.json().catch(() => ({})))
  if (!response.ok || payload.success === false) {
    throw new Error(asString(payload.detail || payload.message) || `MOD 安装失败（HTTP ${response.status}）`)
  }
  return { message: asString(payload.message) || 'MOD 已安装', data: asRecord(payload.data) }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

export async function generateAndInstallAiMod(
  brief: string,
  options: {
    intervalMs?: number
    maxRounds?: number
    onProgress?: (progress: AiModDeliveryProgress) => void
  } = {},
): Promise<AiModDeliveryResult> {
  const { sessionId } = await startAiModDelivery(brief)
  const intervalMs = Math.max(10, options.intervalMs ?? 2000)
  const maxRounds = Math.max(1, options.maxRounds ?? 300)
  let latest: AiModDeliveryProgress | null = null
  for (let round = 0; round < maxRounds; round += 1) {
    latest = await getAiModDeliveryProgress(sessionId)
    options.onProgress?.(latest)
    if (latest.status === 'done') break
    if (latest.status === 'error' || latest.status === 'failed') {
      throw new Error(asString(latest.snapshot.error) || 'MOD 生成失败')
    }
    await sleep(intervalMs)
  }
  if (!latest || latest.status !== 'done') throw new Error('MOD 生成超时，会话已保留，可稍后重试')
  const artifact = asRecord(latest.snapshot.artifact)
  const modId = asString(artifact.mod_id).trim()
  if (!modId) throw new Error('MOD 生成结果缺少 mod_id')
  const installed = await installAiModDelivery(sessionId)
  return {
    sessionId,
    modId,
    installMessage: installed.message,
    snapshot: latest.snapshot,
  }
}
