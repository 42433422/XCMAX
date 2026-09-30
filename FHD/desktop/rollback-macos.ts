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
  const backupRoot = path.resolve(options.backupRoot)
  const databasePath = options.databasePath ? path.resolve(options.databasePath) : ''
  const databaseBackupPath = options.databaseBackupPath ? path.resolve(options.databaseBackupPath) : ''
  const timeout = Math.max(5, Math.trunc(options.waitTimeoutSeconds ?? 120))
  const applied = Buffer.from(JSON.stringify(options.applied)).toString('base64')
  const staging = `${appPath}.xcagi-rollback-staging`
  const failed = `${appPath}.xcagi-failed`
  const dbStaging = databasePath ? `${databasePath}.xcagi-rollback-staging` : ''
  const dbFailed = databasePath ? `${databasePath}.xcagi-failed` : ''
  return [
    '#!/bin/sh', 'set -eu',
    `app=${shellQuote(appPath)}`, `backup=${shellQuote(backupRoot)}`,
    `marker=${shellQuote(path.resolve(options.markerPath))}`,
    `applied=${shellQuote(path.resolve(options.appliedPath))}`,
    `log=${shellQuote(path.resolve(options.logPath))}`,
    `staging=${shellQuote(staging)}`, `failed=${shellQuote(failed)}`,
    `db=${shellQuote(databasePath)}`, `db_backup=${shellQuote(databaseBackupPath)}`,
    `db_staging=${shellQuote(dbStaging)}`, `db_failed=${shellQuote(dbFailed)}`,
    `applied_json=${shellQuote(applied)}`, `pid=${pid}`, `deadline=$(($(date +%s) + ${timeout}))`,
    'logline() { printf "%s %s\\n" "$(date -u +%FT%TZ)" "$1" >> "$log" 2>/dev/null || true; }',
    'rollback_pair() { status=$?; if [ "$status" -ne 0 ] && [ -d "$failed" ]; then rm -rf "$app"; mv "$failed" "$app"; if [ -e "$db_failed" ]; then rm -f "$db"; mv "$db_failed" "$db"; fi; rm -f "$applied"; logline "restore of new app and database completed after rollback error"; fi; }',
    'trap rollback_pair EXIT',
    'while kill -0 "$pid" 2>/dev/null; do [ "$(date +%s)" -lt "$deadline" ] || { logline "timed out waiting for app"; exit 1; }; sleep 1; done',
    '[ -d "$backup" ] && [ -d "$backup/Contents" ] || { logline "app backup missing"; exit 1; }',
    'if [ -n "$db" ] && [ -n "$db_backup" ]; then [ -f "$db_backup" ] || { logline "database backup missing"; exit 1; }; fi',
    'rm -rf "$staging" "$failed"',
    'ditto "$backup" "$staging"',
    '[ -d "$staging/Contents" ] || { logline "staged app invalid"; exit 1; }',
    'if [ -n "$db" ] && [ -n "$db_backup" ]; then rm -f "$db_staging" "$db_failed"; cp -p "$db_backup" "$db_staging"; fi',
    '[ ! -e "$app" ] || mv "$app" "$failed"',
    'if ! mv "$staging" "$app"; then [ ! -e "$failed" ] || mv "$failed" "$app"; exit 1; fi',
    'if [ -n "$db" ] && [ -n "$db_backup" ]; then',
    '  if [ -e "$db" ] && ! mv "$db" "$db_failed"; then rm -rf "$app"; [ ! -e "$failed" ] || mv "$failed" "$app"; exit 1; fi',
    '  if ! mv "$db_staging" "$db"; then rm -rf "$app"; [ ! -e "$failed" ] || mv "$failed" "$app"; [ ! -e "$db_failed" ] || mv "$db_failed" "$db"; exit 1; fi',
    '  rm -f "$db-wal" "$db-shm"',
    'fi',
    'printf %s "$applied_json" | /usr/bin/base64 -D > "$applied"',
    'rm -f "$marker"',
    'trap - EXIT',
    'rm -rf "$failed" 2>/dev/null || true; [ -z "$db_failed" ] || rm -f "$db_failed" 2>/dev/null || true',
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
