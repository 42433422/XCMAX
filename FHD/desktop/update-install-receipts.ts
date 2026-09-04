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
  source?: 'desktop_ota' | 'desktop_inventory'
}

const INSTALLATION_ID_FILE = 'installation-id'
const LEGACY_DEVICE_ID_FILE = 'device_id'
const PENDING_RECEIPT_FILE = 'pending-update-install-receipt.json'
const REPORTED_INSTALLATION_FILE = 'reported-update-installation.json'

function updaterLogPath(): string {
  return path.join(app.getPath('userData'), 'logs', 'updater-events.jsonl')
}

/** 追加更新流程事件日志（install_start / install_failed 等），失败静默。 */
export function appendUpdaterEvent(type: string, data?: unknown): void {
  try {
    const dir = path.dirname(updaterLogPath())
    fs.mkdirSync(dir, { recursive: true })
    fs.appendFileSync(
      updaterLogPath(),
      `${JSON.stringify({ ts: new Date().toISOString(), type, data })}\n`,
      'utf8',
    )
  } catch {
    /* ignore log failures */
  }
}

function validInstallationId(value: string): boolean {
  return /^[A-Za-z0-9._:-]{16,64}$/.test(value)
}

function installationIdPath(): string {
  return path.join(app.getPath('userData'), INSTALLATION_ID_FILE)
}

function pendingReceiptPath(): string {
  return path.join(app.getPath('userData'), PENDING_RECEIPT_FILE)
}

function reportedInstallationPath(): string {
  return path.join(app.getPath('userData'), REPORTED_INSTALLATION_FILE)
}

export function loadOrCreateInstallationId(): string {
  const filePath = installationIdPath()
  try {
    const existing = fs.readFileSync(filePath, 'utf8').trim()
    if (validInstallationId(existing)) return existing
  } catch {
    /* create below */
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  let installationId = ''
  try {
    const legacyDeviceId = fs
      .readFileSync(path.join(app.getPath('userData'), LEGACY_DEVICE_ID_FILE), 'utf8')
      .trim()
    if (validInstallationId(legacyDeviceId)) installationId = legacyDeviceId
  } catch {
    /* a fresh installation has no legacy identity */
  }
  if (!installationId) installationId = crypto.randomUUID()
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
    source: 'desktop_ota',
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

function stageCurrentInstallationReceipt(input: {
  installedVersion: string
  installedBuildSha: string
}): PendingUpdateInstallReceipt | null {
  const installedVersion = String(input.installedVersion || '').trim()
  const installedBuildSha = String(input.installedBuildSha || '').trim()
  if (!installedVersion || !installedBuildSha) return null

  const installationId = loadOrCreateInstallationId()
  try {
    const reported = JSON.parse(fs.readFileSync(reportedInstallationPath(), 'utf8')) as {
      installationId?: string
      installedVersion?: string
      installedBuildSha?: string
    }
    if (
      reported.installationId === installationId
      && reported.installedVersion === installedVersion
      && reported.installedBuildSha === installedBuildSha
    ) return null
  } catch {
    /* first report or unreadable marker; create a durable outbox below */
  }

  const receipt: PendingUpdateInstallReceipt = {
    installationId,
    idempotencyKey: crypto
      .createHash('sha256')
      .update(`desktop_inventory:${installationId}:${installedVersion}:${installedBuildSha}`)
      .digest('hex'),
    channel: process.env.XCAGI_UPDATE_CHANNEL === 'staging' ? 'staging' : 'stable',
    platform: process.platform,
    targetVersion: installedVersion,
    targetBuildSha: installedBuildSha,
    preparedAt: new Date().toISOString(),
    source: 'desktop_inventory',
  }
  fs.writeFileSync(pendingReceiptPath(), JSON.stringify(receipt, null, 2), {
    encoding: 'utf8',
    mode: 0o600,
  })
  return receipt
}

function rememberReportedInstallation(input: {
  installationId: string
  installedVersion: string
  installedBuildSha: string
}): void {
  fs.writeFileSync(reportedInstallationPath(), JSON.stringify({
    ...input,
    reportedAt: new Date().toISOString(),
  }, null, 2), { encoding: 'utf8', mode: 0o600 })
}

export async function reportPendingUpdateInstallation(input: {
  backendPort: number
  installedVersion: string
  installedBuildSha: string
  rollback?: { reason?: string } | null
}): Promise<{ reported: boolean; status?: string; reason?: string }> {
  const pending = readPendingUpdateInstallReceipt() || (
    input.rollback ? null : stageCurrentInstallationReceipt(input)
  )
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
        source: pending.source || 'desktop_ota',
        reported_at: new Date().toISOString(),
      }),
      signal: AbortSignal.timeout(10_000),
    },
  )
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`安装回执上报失败: HTTP ${response.status} ${detail}`.trim())
  }
  if (status === 'installed') {
    rememberReportedInstallation({
      installationId: pending.installationId,
      installedVersion,
      installedBuildSha,
    })
  }
  discardPendingUpdateInstallReceipt()
  return { reported: true, status }
}
