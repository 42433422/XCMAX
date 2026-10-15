import { execFileSync } from 'node:child_process'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import type { RollbackMarker } from './rollback.js'

type RecoveryPackage = { filename: string; sha256: string; gitSha: string; version: string; arch: string; sku: string }

export function promoteLegacyMacRollback(marker: RollbackMarker, dir: string, appBundlePath: string, backendBackup: string): RollbackMarker {
  const missing = () => new Error(`完整旧版应用备份不足：${marker.fromVersion} (${process.arch})；保留当前应用、数据库和旧备份，请提供对应的已签名完整安装包及数据库快照`)
  if (!appBundlePath || !marker.databasePath || !marker.databaseBackupPath || !fs.existsSync(marker.databaseBackupPath)) throw missing()
  const root = path.join(process.resourcesPath, 'legacy-macos-recovery')
  let selected: RecoveryPackage | undefined
  try {
    const sku = JSON.parse(fs.readFileSync(path.join(process.resourcesPath, 'product-sku.json'), 'utf8')).sku
    const sha = marker.fromVersion.split('+')[1] || ''
    const entries = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8')).entries as RecoveryPackage[]
    const matches = entries.filter(entry => entry.arch === process.arch && entry.sku === sku && /^[a-f0-9]{8,40}$/.test(sha) && entry.gitSha.startsWith(sha))
    if (matches.length === 1) selected = matches[0]
  } catch { /* No verified recovery package: never replace only the signed backend. */ }
  if (!selected || selected.filename !== path.basename(selected.filename) || !/^[a-f0-9]{40}$/.test(selected.gitSha) || !/^[a-f0-9]{64}$/.test(selected.sha256)) throw missing()
  const archive = path.join(root, selected.filename)
  if (!fs.existsSync(archive) || crypto.createHash('sha256').update(fs.readFileSync(archive)).digest('hex') !== selected.sha256) throw missing()
  const staging = fs.mkdtempSync(path.join(dir, 'legacy-macos-'))
  execFileSync('ditto', ['-x', '-k', archive, staging])
  const restored = path.join(staging, 'XCAGI.app')
  const resources = path.join(restored, 'Contents', 'Resources')
  const identity = JSON.parse(fs.readFileSync(path.join(resources, 'build-info.json'), 'utf8'))
  if (identity.gitSha !== selected.gitSha || identity.version !== selected.version) throw missing()
  execFileSync('codesign', ['--verify', '--deep', '--strict', restored])
  // Retain the actual old backend's opaque runtime files, not merely a clean vendor copy.
  fs.rmSync(path.join(resources, 'backend'), { recursive: true })
  execFileSync('ditto', [backendBackup, path.join(resources, 'backend')])
  execFileSync('codesign', ['--verify', '--deep', '--strict', restored])
  const promoted: RollbackMarker = { ...marker, mode: 'macos-full', fromVersion: `${selected.version}+${selected.gitSha.slice(0, 12)}`, appBundlePath, appBackupRelPath: path.relative(dir, restored) }
  const temporary = path.join(path.dirname(dir), `rollback-marker.${process.pid}.tmp`)
  fs.writeFileSync(temporary, JSON.stringify(promoted, null, 2), { mode: 0o600 })
  fs.renameSync(temporary, path.join(path.dirname(dir), 'rollback-marker.json'))
  return promoted
}
