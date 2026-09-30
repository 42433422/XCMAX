import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { buildMacOSRollbackScript } from './rollback-macos.js'

function setup(recoveryRecordIsDirectory = false) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-macos-rollback-'))
  const app = path.join(root, "Customer's XCAGI.app")
  const backup = path.join(root, 'previous.app')
  const data = path.join(root, 'data')
  const marker = path.join(root, 'rollback-marker.json')
  const applied = path.join(root, 'rollback-applied.json')
  const db = path.join(data, 'xcagi.db')
  const dbBackup = path.join(data, 'pre-migration.db')
  for (const dir of [path.join(app, 'Contents'), path.join(backup, 'Contents'), data]) {
    fs.mkdirSync(dir, { recursive: true })
  }
  fs.writeFileSync(path.join(app, 'Contents', 'version'), 'new')
  fs.writeFileSync(path.join(backup, 'Contents', 'version'), 'old')
  fs.writeFileSync(db, 'migrated')
  fs.writeFileSync(dbBackup, 'pre-migration')
  fs.writeFileSync(marker, '{}')
  if (recoveryRecordIsDirectory) fs.mkdirSync(applied)
  const options = {
    currentPid: 99999999,
    appPath: app,
    backupRoot: backup,
    markerPath: marker,
    appliedPath: applied,
    logPath: path.join(root, 'helper.log'),
    applied: { appliedAt: 'now', reason: 'startup failed', fromVersion: '2', toVersion: '1' },
    databasePath: db,
    databaseBackupPath: dbBackup,
  }
  return { root, app, marker, applied, db, options }
}

describe('macOS full rollback helper', () => {
  it('restores the previous app and database after exit, including paths with quotes', () => {
    const f = setup()
    const bin = path.join(f.root, 'bin')
    const opened = path.join(f.root, 'opened')
    fs.mkdirSync(bin)
    fs.writeFileSync(path.join(bin, 'open'), `#!/bin/sh\nprintf '%s' "$1" > '${opened}'\n`, { mode: 0o700 })
    try {
      const script = buildMacOSRollbackScript(f.options)
      expect(() => execFileSync('/bin/sh', ['-n'], { input: script })).not.toThrow()
      execFileSync('/bin/sh', ['-c', script], { env: { ...process.env, PATH: `${bin}:${process.env.PATH}` } })
      expect(fs.readFileSync(path.join(f.app, 'Contents', 'version'), 'utf8')).toBe('old')
      expect(fs.readFileSync(f.db, 'utf8')).toBe('pre-migration')
      expect(fs.existsSync(f.marker)).toBe(false)
      expect(JSON.parse(fs.readFileSync(f.applied, 'utf8')).toVersion).toBe('1')
      expect(fs.readFileSync(opened, 'utf8')).toBe(f.app)
    } finally { fs.rmSync(f.root, { recursive: true, force: true }) }
  })

  it('restores the new app and database when recording recovery fails', () => {
    const f = setup(true)
    try {
      expect(() => execFileSync('/bin/sh', ['-c', buildMacOSRollbackScript(f.options)], { stdio: 'ignore' })).toThrow()
      expect(fs.readFileSync(path.join(f.app, 'Contents', 'version'), 'utf8')).toBe('new')
      expect(fs.readFileSync(f.db, 'utf8')).toBe('migrated')
      expect(fs.existsSync(f.marker)).toBe(true)
    } finally { fs.rmSync(f.root, { recursive: true, force: true }) }
  })
})
