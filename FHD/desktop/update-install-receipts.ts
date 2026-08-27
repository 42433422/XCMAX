import { app } from 'electron'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

export type PendingUpdateInstallReceipt = {
  installationId: string
  idempotencyKey: string
  channel: 'stable' | 'staging'
  platform: string
  targetVersion: string
  targetBuildSha: string
  preparedAt: string
}

const INSTALLATION_ID_FILE = 'installation-id'
const PENDING_RECEIPT_FILE = 'pending-update-install-receipt.json'

function installationIdPath(): string {
  return path.join(app.getPath('userData'), INSTALLATION_ID_FILE)
}

function pendingReceiptPath(): string {
  return path.join(app.getPath('userData'), PENDING_RECEIPT_FILE)
}

export function loadOrCreateInstallationId(): string {
  const filePath = installationIdPath()
  try {
    const existing = fs.readFileSync(filePath, 'utf8').trim()
    if (/^[0-9a-f-]{36}$/i.test(existing)) return existing
  } catch {
    /* create below */
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  const installationId = crypto.randomUUID()
  fs.writeFileSync(filePath, `${installationId}\n`, { encoding: 'utf8', mode: 0o600 })
  try { fs.chmodSync(filePath, 0o600) } catch {}
  return installationId
}

export function stageUpdateInstallReceipt(input: {
  targetVersion: string
  targetBuildSha: string
  channel?: string
}): PendingUpdateInstallReceipt {
  const installationId = loadOrCreateInstallationId()
  const targetVersion = String(input.targetVersion || '').trim()
  const targetBuildSha = String(input.targetBuildSha || '').trim()
  const preparedAt = new Date().toISOString()
  const idempotencyKey = crypto
    .createHash('sha256')
    .update(`${installationId}:${targetVersion}:${targetBuildSha}:${preparedAt}`)
    .digest('hex')
  const receipt: PendingUpdateInstallReceipt = {
    installationId,
    idempotencyKey,
    channel: input.channel === 'staging' ? 'staging' : 'stable',
    platform: process.platform,
    targetVersion,
    targetBuildSha,
    preparedAt,
  }
  fs.writeFileSync(pendingReceiptPath(), JSON.stringify(receipt, null, 2), {
    encoding: 'utf8',
    mode: 0o600,
  })
  return receipt
}

export function readPendingUpdateInstallReceipt(): PendingUpdateInstallReceipt | null {
  try {
    const parsed = JSON.parse(fs.readFileSync(pendingReceiptPath(), 'utf8')) as PendingUpdateInstallReceipt
    if (!parsed.installationId || !parsed.idempotencyKey) return null
    return parsed
  } catch {
    return null
  }
}

export function discardPendingUpdateInstallReceipt(): void {
  try { fs.unlinkSync(pendingReceiptPath()) } catch {}
}

export async function reportPendingUpdateInstallation(input: {
  backendPort: number
  installedVersion: string
  installedBuildSha: string
  rollback?: { reason?: string } | null
}): Promise<{ reported: boolean; status?: string; reason?: string }> {
  const pending = readPendingUpdateInstallReceipt()
  if (!pending) return { reported: false, reason: 'no_pending_receipt' }

  const installedBuildSha = String(input.installedBuildSha || '').trim()
  const installedVersion = String(input.installedVersion || '').trim()
  const expectedBuildSha = String(pending.targetBuildSha || '').trim()
  const expectedVersion = String(pending.targetVersion || '').trim()
  const shaMatches = !expectedBuildSha || installedBuildSha === expectedBuildSha
  const versionMatches = !expectedVersion || expectedVersion === 'unknown' || installedVersion === expectedVersion
  const identityMatches = shaMatches && versionMatches
  const status = input.rollback ? 'rolled_back' : identityMatches ? 'installed' : 'failed'
  const error = input.rollback?.reason
    ? String(input.rollback.reason)
    : identityMatches
      ? ''
      : `安装后身份不匹配：expected=${expectedVersion || '<empty>'}+${expectedBuildSha || '<empty>'}, actual=${installedVersion || '<empty>'}+${installedBuildSha || '<empty>'}`
  const response = await fetch(
    `http://127.0.0.1:${input.backendPort}/api/desktop/update-install-receipts/report`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        installation_id: pending.installationId,
        idempotency_key: pending.idempotencyKey,
        channel: pending.channel,
        platform: pending.platform,
        target_version: pending.targetVersion,
        target_build_sha: pending.targetBuildSha,
        installed_version: installedVersion,
        installed_build_sha: installedBuildSha,
        status,
        error,
        source: 'desktop_ota',
        reported_at: new Date().toISOString(),
      }),
      signal: AbortSignal.timeout(10_000),
    },
  )
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`安装回执上报失败: HTTP ${response.status} ${detail}`.trim())
  }
  discardPendingUpdateInstallReceipt()
  return { reported: true, status }
}
