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
  execFileSync('python3', ['-c', "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('CREATE TABLE records(value TEXT)'); c.execute(\"INSERT INTO records VALUES ('pre-migration')\"); c.commit(); c.close()", dbBackup])
  fs.writeFileSync(marker, '{}')
  if (recoveryRecordIsDirectory) fs.mkdirSync(applied)
  return { root, app, marker, applied, db, options: {
    currentPid: 99999999,
    appPath: app, backupRoot: backup,
    markerPath: marker, appliedPath: applied,
    logPath: path.join(root, 'helper.log'),
    applied: { appliedAt: 'now', reason: 'startup failed', fromVersion: '2', toVersion: '1' },
    databasePath: db, databaseBackupPath: dbBackup,
  } }
}

const scriptForTestHost = (script: string) => process.platform === 'darwin' ? script : script.replace('ditto "$backup" "$staging"', 'cp -a "$backup" "$staging"').replace('/usr/bin/base64 -D', 'base64 -d')

describe('macOS full rollback helper', () => {
  it('restores the previous app and database after exit, including paths with quotes', () => {
    const f = setup()
    const bin = path.join(f.root, 'bin')
    const opened = path.join(f.root, 'opened')
    fs.mkdirSync(bin)
    fs.writeFileSync(path.join(bin, 'open'), `#!/bin/sh\nprintf '%s\\n' "$@" > '${opened}'\n`, { mode: 0o700 })
    try {
      execFileSync('/bin/sh', ['-c', scriptForTestHost(buildMacOSRollbackScript(f.options))], { env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, XCAGI_DESKTOP_PORT: '18781' } })
      expect(fs.readFileSync(path.join(f.app, 'Contents', 'version'), 'utf8')).toBe('old')
      expect(execFileSync('python3', ['-c', "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('SELECT value FROM records').fetchone()[0])", f.db], { encoding: 'utf8' }).trim()).toBe('pre-migration')
      expect(fs.existsSync(f.marker)).toBe(false)
      expect(JSON.parse(fs.readFileSync(f.applied, 'utf8')).toVersion).toBe('1')
      expect(fs.readFileSync(opened, 'utf8').trim().split('\n')).toEqual(['-n', '--env', `XCAGI_DESKTOP_USER_DATA_DIR=${f.root}`, '--env', 'XCAGI_DESKTOP_PORT=18781', f.app])
    } finally { fs.rmSync(f.root, { recursive: true, force: true }) }
  })

  it.each(['receipt', 'snapshot'])('preserves the new app and committed WAL when %s recovery fails', (failure) => {
    const f = setup(failure === 'receipt')
    if (failure === 'snapshot') fs.writeFileSync(f.options.databaseBackupPath, 'corrupt SQLite snapshot')
    try {
      execFileSync('python3', ['-c', `import sqlite3,os,sys
p=sys.argv[1]; os.unlink(p); c=sqlite3.connect(p)
c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA wal_autocheckpoint=0')
c.execute('CREATE TABLE records(value TEXT)'); c.commit()
c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
c.execute("INSERT INTO records VALUES ('committed customer record')"); c.commit()
os._exit(0)`, f.db])
      expect(fs.existsSync(`${f.db}-wal`)).toBe(true)
      expect(() => execFileSync('/bin/sh', ['-c', scriptForTestHost(buildMacOSRollbackScript(f.options))], { stdio: 'ignore' })).toThrow()
      expect(fs.readFileSync(path.join(f.app, 'Contents', 'version'), 'utf8')).toBe('new')
      expect(execFileSync('python3', ['-c', "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('SELECT value FROM records').fetchone()[0])", f.db], { encoding: 'utf8' }).trim()).toBe('committed customer record')
      expect(fs.existsSync(f.marker)).toBe(true)
    } finally { fs.rmSync(f.root, { recursive: true, force: true }) }
  })
})
