import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

export interface MacOSRollbackLaunchOptions {
  currentPid: number
  appPath: string
  backupRoot: string
  markerPath: string
  appliedPath: string
  logPath: string
  applied: { appliedAt: string; reason: string; fromVersion: string; toVersion: string }
  databasePath?: string
  databaseBackupPath?: string
  waitTimeoutSeconds?: number
}

const shellQuote = (value: string): string => `'${value.replaceAll("'", "'\\''")}'`

export function buildMacOSRollbackScript(options: MacOSRollbackLaunchOptions): string {
  const pid = Math.trunc(options.currentPid)
  if (!Number.isSafeInteger(pid) || pid < 1) throw new Error(`Invalid rollback wait pid: ${options.currentPid}`)
  const appPath = path.resolve(options.appPath)
  const databasePath = options.databasePath ? path.resolve(options.databasePath) : ''
  return [
    '#!/bin/sh', 'set -eu',
    ...Object.entries({
      app: appPath, backup: path.resolve(options.backupRoot), marker: path.resolve(options.markerPath),
      applied: path.resolve(options.appliedPath), log: path.resolve(options.logPath),
      staging: `${appPath}.xcagi-rollback-staging`, failed: `${appPath}.xcagi-failed`,
      db: databasePath, db_backup: options.databaseBackupPath ? path.resolve(options.databaseBackupPath) : '',
      db_staging: databasePath ? `${databasePath}.xcagi-rollback-staging` : '',
      db_failed: databasePath ? `${databasePath}.xcagi-failed` : '',
    }).map(([name, value]) => `${name}=${shellQuote(value)}`),
    `applied_json=${shellQuote(Buffer.from(JSON.stringify(options.applied)).toString('base64'))}`, `pid=${pid}`, `deadline=$(($(date +%s) + ${Math.max(5, Math.trunc(options.waitTimeoutSeconds ?? 120))}))`,
    'logline() { printf "%s %s\\n" "$(date -u +%FT%TZ)" "$1" >> "$log" 2>/dev/null || true; }',
    'rollback_pair() { status=$?; if [ "$status" -ne 0 ] && [ -d "$failed" ]; then rm -rf "$app"; mv "$failed" "$app"; if [ -e "$db_failed" ]; then rm -f "$db"; mv "$db_failed" "$db"; fi; for suffix in -wal -shm; do [ ! -e "$db$suffix.xcagi-failed" ] || mv "$db$suffix.xcagi-failed" "$db$suffix"; done; rm -f "$applied"; logline "restore of new app and database completed after rollback error"; fi; }',
    'while kill -0 "$pid" 2>/dev/null; do [ "$(date +%s)" -lt "$deadline" ] || { logline "timed out waiting for app"; exit 1; }; sleep 1; done',
    '[ -d "$backup" ] && [ -d "$backup/Contents" ] || { logline "app backup missing"; exit 1; }',
    'if [ -n "$db" ] && [ -n "$db_backup" ]; then [ -f "$db_backup" ] || { logline "database backup missing"; exit 1; }; fi',
    'if [ -n "$db" ]; then for suffix in -wal -shm; do [ ! -e "$db$suffix.xcagi-failed" ] || { logline "prior database recovery retained"; exit 1; }; done; fi',
    '[ ! -e "$failed" ] && [ ! -e "$staging" ] && { [ -z "$db_failed" ] || [ ! -e "$db_failed" ]; } || { logline "prior recovery retained"; exit 1; }',
    'trap rollback_pair EXIT',
    'ditto "$backup" "$staging"',
    '[ -d "$staging/Contents" ] || { logline "staged app invalid"; exit 1; }',
    'if [ -n "$db" ] && [ -n "$db_backup" ]; then rm -f "$db_staging" "$db_failed"; cp -p "$db_backup" "$db_staging"; fi',
    '[ ! -e "$app" ] || mv "$app" "$failed"',
    'mv "$staging" "$app"',
    'if [ -n "$db" ] && [ -n "$db_backup" ]; then',
    '  [ ! -e "$db" ] || mv "$db" "$db_failed"',
    '  for suffix in -wal -shm; do [ ! -e "$db$suffix" ] || mv "$db$suffix" "$db$suffix.xcagi-failed"; done',
    '  mv "$db_staging" "$db"',
    'fi',
    'printf %s "$applied_json" | /usr/bin/base64 -D > "$applied"',
    'rm -f "$marker"',
    'trap - EXIT',
    'rm -rf "$failed" 2>/dev/null || true; [ -z "$db_failed" ] || rm -f "$db_failed" 2>/dev/null || true',
    'if [ -n "$db" ]; then rm -f "$db-wal.xcagi-failed" "$db-shm.xcagi-failed"; fi',
    'logline "full application and database rollback completed"',
    'open "$app" || logline "rollback succeeded but app launch failed"',
  ].join('\n') + '\n'
}

export function launchMacOSFullRollback(options: MacOSRollbackLaunchOptions): Promise<number | undefined> {
  const scriptPath = path.join(path.dirname(options.logPath), `rollback-${options.currentPid}.sh`)
  fs.writeFileSync(scriptPath, buildMacOSRollbackScript(options), { mode: 0o700 })
  return new Promise((resolve, reject) => {
    const helper = spawn('/bin/sh', [scriptPath], { cwd: '/', detached: true, stdio: 'ignore' })
    helper.once('error', reject)
    helper.once('spawn', () => { helper.unref(); resolve(helper.pid) })
  })
}
