import { afterEach, describe, expect, it } from 'vitest'
import { execFile } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { promisify } from 'node:util'
import { createHash } from 'node:crypto'
import {
  buildWindowsRollbackScript,
  buildWindowsRollbackFileLoader,
  type WindowsRollbackLaunchOptions,
} from './rollback-windows.js'

const powershell = process.env.XCAGI_TEST_POWERSHELL || 'powershell.exe'
const windowsIt = process.platform === 'win32' || process.env.XCAGI_TEST_POWERSHELL ? it : it.skip
const cleanupRoots: string[] = []
const execFileAsync = promisify(execFile)

afterEach(() => {
  for (const root of cleanupRoots.splice(0)) fs.rmSync(root, { recursive: true, force: true })
})

describe('Windows full application rollback helper', () => {
  windowsIt.each([false, true])('checks the private script checksum before execution (tampered=%s)', async (tampered) => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "xcagi-loader-'")); cleanupRoots.push(root)
    const scriptPath = path.join(root, 'restore.ps1'), receipt = path.join(root, 'executed.txt')
    const script = `[IO.File]::WriteAllText('${receipt.replaceAll("'", "''")}', 'executed')`
    const digest = createHash('sha256').update(script).digest('hex')
    fs.writeFileSync(scriptPath, tampered ? script + '\n# changed' : script)
    const encoded = Buffer.from(buildWindowsRollbackFileLoader(scriptPath, digest), 'utf16le').toString('base64')
    expect(encoded.length).toBeLessThan(32767)
    let rejected = false
    try { await execFileAsync(powershell, ['-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], { timeout: 10000 }) } catch { rejected = true }
    expect(rejected).toBe(tampered); expect(fs.existsSync(receipt)).toBe(!tampered)
  }, 15_000)
  it('encodes paths and the applied record without interpolating raw JSON', () => {
    const options: WindowsRollbackLaunchOptions = {
      currentPid: 42,
      installDir: "C:\\Users\\O'Brien\\XCAGI",
      backupRoot: 'C:\\rollback\\app',
      appPath: "C:\\Users\\O'Brien\\XCAGI\\XCAGI.exe",
      markerPath: 'C:\\data\\rollback-marker.json',
      appliedPath: 'C:\\data\\rollback-applied.json',
      logPath: 'C:\\data\\rollback.log',
      applied: {
        appliedAt: '2026-07-16T00:00:00.000Z',
        reason: "window couldn't start",
        fromVersion: '1.0.0.0',
        toVersion: '1.0.0.0',
      },
    }
    const script = buildWindowsRollbackScript(options)
    expect(script).toContain("'C:\\Users\\O''Brien\\XCAGI'")
    expect(script).toContain('FromBase64String')
    expect(script).not.toContain("window couldn't start")
    expect(script).toContain('[IO.Directory]::Move($stagingDir, $installDir)')
    expect(script).toContain('Install-SnapshotInPlace $stagingDir $installDir')
    expect(script).toContain('[IO.Path]::ChangeExtension($appliedPath, ".last.json")')
    expect(script).toContain('$receiptBytes = [IO.File]::ReadAllBytes($appliedPath)')
    expect(script.indexOf('$receiptWrites += $write')).toBeLessThan(script.indexOf('Remove-Item -LiteralPath $markerPath -Force -ErrorAction Stop'))
    expect(script.indexOf('$rollbackCommitted = $true')).toBeLessThan(script.indexOf('Start-Process -FilePath $appPath'))
  })

  windowsIt.each(['success', 'success-long-path', 'success-short-root', 'success-prior', 'success-generated-operation', 'receipt-failure', 'durable-failure', 'durable-failure-prior', 'marker-failure', 'marker-failure-prior', 'retained-failure', 'retained-wal', 'retained-journal'])('keeps app and database consistent after %s', async (scenario) => {
    const failed = !scenario.startsWith('success'), prior = scenario.endsWith('-prior')
    let root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-windows-rollback-'))
    cleanupRoots.push(root)
    if (scenario === 'success-short-root') root = (await execFileAsync('cmd.exe', ['/d', '/s', '/c', `for %I in ("${root}") do @echo %~sI`], { windowsVerbatimArguments: true })).stdout.trim()
    const installDir = path.join(root, 'XCAGI')
    const backupRoot = path.join(root, 'rollback', 'windows-app-current')
    const dataDir = path.join(root, 'data')
    const appPath = path.join(installDir, 'XCAGI.exe')
    const markerPath = path.join(dataDir, 'rollback-marker.json')
    const appliedPath = path.join(dataDir, 'rollback-applied.json'), durablePath = path.join(dataDir, 'rollback-applied.last.json')
    const previous = JSON.stringify({ operationId: 'prior-operation', fromVersion: 'prior-new', toVersion: 'prior-old' })
    const logPath = path.join(dataDir, 'rollback-helper.log')
    const databasePath = path.join(dataDir, 'data', 'xcagi.db')
    const databaseBackupPath = path.join(dataDir, 'backups', 'pre-migration.db')

    fs.mkdirSync(installDir, { recursive: true })
    fs.mkdirSync(backupRoot, { recursive: true })
    fs.mkdirSync(path.dirname(databasePath), { recursive: true })
    fs.mkdirSync(path.dirname(databaseBackupPath), { recursive: true })
    fs.writeFileSync(appPath, 'new-app')
    fs.writeFileSync(path.join(installDir, 'build.txt'), 'new-build')
    fs.writeFileSync(path.join(backupRoot, 'XCAGI.exe'), 'old-app')
    fs.writeFileSync(path.join(backupRoot, 'build.txt'), 'old-build')
    const longFile = path.join('nested-'.repeat(22), 'recovery-'.repeat(12) + '.txt')
    if (scenario === 'success-long-path') { fs.mkdirSync(path.dirname(path.join(backupRoot, longFile)), { recursive: true }); fs.writeFileSync(path.join(backupRoot, longFile), 'long-path-backup'); expect(path.join(backupRoot, longFile).length).toBeGreaterThan(260) }
    if (scenario.startsWith('marker-failure')) fs.mkdirSync(markerPath)
    fs.writeFileSync(scenario.startsWith('marker-failure') ? path.join(markerPath, 'retained') : markerPath, '{}')
    fs.writeFileSync(databasePath, 'new-database')
    fs.writeFileSync(`${databasePath}-wal`, 'new-wal')
    fs.writeFileSync(`${databasePath}-shm`, 'new-shm')
    fs.writeFileSync(databaseBackupPath, 'old-database')
    if (prior) { fs.writeFileSync(appliedPath, previous); if (!scenario.startsWith('durable-failure')) fs.writeFileSync(durablePath, previous) }
    if (scenario === 'receipt-failure') fs.mkdirSync(appliedPath)
    if (scenario.startsWith('durable-failure')) { fs.mkdirSync(durablePath); fs.writeFileSync(path.join(durablePath, 'retained'), previous) }
    const retained = path.join(`${installDir}.xcagi-failed`, 'XCAGI.exe')
    if (scenario === 'retained-failure') { fs.mkdirSync(path.dirname(retained)); fs.writeFileSync(retained, 'prior-failure') }
    if (scenario === 'retained-wal') fs.writeFileSync(`${databasePath}.xcagi-failed-wal`, 'prior-wal')
    if (scenario === 'retained-journal') fs.writeFileSync(`${databasePath}.xcagi-failed-journal`, 'prior-journal')

    const options: WindowsRollbackLaunchOptions = {
      currentPid: 2_000_000_000,
      installDir, backupRoot, appPath, markerPath, appliedPath, logPath, databasePath, databaseBackupPath,
      restartApp: false,
      waitTimeoutSeconds: 5,
      applied: {
        appliedAt: '2026-07-16T00:00:00.000Z',
        reason: 'integration test', operationId: 'current-operation',
        fromVersion: '1.0.0.0-new',
        toVersion: '1.0.0.0-old',
      },
    }
    if (scenario === 'success-long-path') options.expectedAppFiles = Object.fromEntries(['XCAGI.exe', 'build.txt', longFile].map(file => [file, createHash('sha256').update(fs.readFileSync(path.join(backupRoot, file))).digest('hex')]))
    if (scenario === 'success-generated-operation') delete options.applied.operationId
    const script = buildWindowsRollbackScript(options)
    const scriptPath = path.join(dataDir, 'rollback-helper-test.ps1')
    fs.writeFileSync(scriptPath, script, 'utf8')
    const scriptSha256 = createHash('sha256').update(script).digest('hex')
    const loader = buildWindowsRollbackFileLoader(scriptPath, scriptSha256)
    const encoded = Buffer.from(loader, 'utf16le').toString('base64')
    expect(encoded.length).toBeLessThan(32767)
    let executionError = ''
    try {
      await execFileAsync(
        powershell,
        [
          '-NoLogo',
          '-NoProfile',
          '-NonInteractive',
          '-EncodedCommand',
          encoded,
        ],
        // Allow executable fixture scanning; the helper process wait stays capped at five seconds.
        { cwd: dataDir, timeout: 45_000 },
      )
    } catch (error) {
      executionError = error instanceof Error ? error.message : String(error)
    }
    const helperLog = fs.existsSync(logPath) ? fs.readFileSync(logPath, 'utf8') : ''

    expect(fs.readFileSync(appPath, 'utf8'), `${executionError}\n${helperLog}`).toBe(failed ? 'new-app' : 'old-app')
    expect(fs.readFileSync(path.join(installDir, 'build.txt'), 'utf8')).toBe(failed ? 'new-build' : 'old-build')
    expect(fs.readFileSync(databasePath, 'utf8')).toBe(failed ? 'new-database' : 'old-database')
    expect(fs.existsSync(markerPath)).toBe(failed)
    if (scenario === 'success-long-path') expect(fs.readFileSync(path.join(installDir, longFile), 'utf8')).toBe('long-path-backup')
    for (const [suffix, value] of [['wal', 'new-wal'], ['shm', 'new-shm']]) {
      expect(fs.existsSync(`${databasePath}-${suffix}`)).toBe(failed)
      if (failed) expect(fs.readFileSync(`${databasePath}-${suffix}`, 'utf8')).toBe(value)
    }
    if (failed) expect(executionError).not.toBe('')
    else {
      const raw = fs.readFileSync(appliedPath, 'utf8'), applied = JSON.parse(raw)
      expect(applied).toMatchObject({ reason: 'integration test', fromVersion: '1.0.0.0-new', toVersion: '1.0.0.0-old' })
      expect(applied.operationId).toMatch(scenario === 'success-generated-operation' ? /^[0-9a-f]{32}$/ : /^current-operation$/)
      expect(Number.isFinite(Date.parse(applied.completedAt))).toBe(true)
      expect(fs.readFileSync(durablePath, 'utf8')).toBe(raw)
      fs.unlinkSync(appliedPath); expect(fs.readFileSync(durablePath, 'utf8')).toBe(raw)
    }
    if (failed && prior) expect(fs.readFileSync(appliedPath, 'utf8')).toBe(previous)
    if (scenario.startsWith('marker-failure')) {
      expect(fs.existsSync(appliedPath)).toBe(prior); expect(fs.existsSync(durablePath)).toBe(prior)
      if (prior) expect(fs.readFileSync(durablePath, 'utf8')).toBe(previous)
    }
    if (scenario.startsWith('durable-failure')) {
      expect(fs.existsSync(appliedPath)).toBe(prior); expect(fs.readFileSync(path.join(durablePath, 'retained'), 'utf8')).toBe(previous)
    }
    if (scenario === 'retained-failure') expect(fs.readFileSync(retained, 'utf8')).toBe('prior-failure')
    if (scenario === 'retained-wal') expect(fs.readFileSync(`${databasePath}.xcagi-failed-wal`, 'utf8')).toBe('prior-wal')
    if (scenario === 'retained-journal') expect(fs.readFileSync(`${databasePath}.xcagi-failed-journal`, 'utf8')).toBe('prior-journal')
  }, 60_000)

  windowsIt.each(['consumed', 'missing', 'log-only', 'malformed-json', 'missing-time', 'stale-operation', 'wrong-from', 'wrong-to', 'old-time', 'future-time', 'malformed-time', 'wrong-build', 'dirty-db', 'marker'])('collector independently rejects invalid evidence: %s', async (scenario) => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xcagi-receipt-collector-')); cleanupRoots.push(root)
    const install = path.join(root, 'app'), data = path.join(root, 'data'), evidence = path.join(root, 'evidence')
    for (const dir of [path.join(install, 'resources'), data, evidence]) fs.mkdirSync(dir, { recursive: true })
    const old = '2e6f03bf67b88965e450721e5b8432ab6395782b', now = new Date().toISOString()
    fs.writeFileSync(path.join(install, 'resources', 'build-info.json'), JSON.stringify({ gitSha: scenario === 'wrong-build' ? 'candidate' : old }))
    const database = path.join(data, 'xcagi.db'); fs.writeFileSync(database, scenario === 'dirty-db' ? 'dirty' : 'original')
    const receipt = { operationId: 'this-operation', fromVersion: '1.0.0.6', toVersion: `1.0.0.1+${old.slice(0, 12)}`, reason: 'isolated startup failure', appliedAt: now, completedAt: now }
    if (scenario === 'stale-operation') receipt.operationId = 'previous-operation'
    if (scenario === 'wrong-from') receipt.fromVersion = 'unrelated-candidate'
    if (scenario === 'wrong-to') receipt.toVersion = 'unrelated-old-build'
    if (scenario === 'old-time') receipt.appliedAt = receipt.completedAt = '2000-01-01T00:00:00Z'
    if (scenario === 'future-time') receipt.completedAt = '2099-01-01T00:00:00Z'
    if (scenario === 'malformed-time') receipt.completedAt = 'not-a-date'
    if (scenario === 'missing-time') delete (receipt as Partial<typeof receipt>).completedAt
    if (scenario === 'log-only') fs.writeFileSync(path.join(data, 'rollback-helper.log'), 'full application rollback completed')
    if (!['missing', 'log-only'].includes(scenario)) fs.writeFileSync(path.join(data, 'rollback-applied.last.json'), JSON.stringify(receipt))
    if (scenario === 'malformed-json') fs.writeFileSync(path.join(data, 'rollback-applied.last.json'), '{bad json')
    if (scenario === 'marker') fs.writeFileSync(path.join(data, 'rollback-marker.json'), '{}')
    // Use the checksum-verified product loader, including on hosts that disable -File.
    const source = fs.readFileSync(path.resolve('../scripts/package/accept-windows-candidate.ps1'), 'utf8')
    const start = source.indexOf("    $infoPath = Join-Path $installRoot 'resources\\build-info.json'", source.indexOf('function Invoke-FailedRollback'))
    expect(start).toBeGreaterThan(0)
    const body = source.slice(start, source.indexOf('\n  } finally {', start)).replace('Start-Sleep -Seconds 2', '')
    const capture = source.split('\n').find(line => line.includes("if ($appliedPath -and (Test-Path -LiteralPath $appliedPath -PathType Leaf))"))!
    expect(capture).toContain('Copy-Item')
    const quote = (value: string) => `'${value.replaceAll("'", "''")}'`
    const marker = { operationId: 'this-operation', fromVersion: `1.0.0.1+${old.slice(0, 12)}`, toVersion: '1.0.0.6', preparedAt: new Date(Date.now() - 30_000).toISOString() }
    const script = `$ErrorActionPreference='Stop'; function Check([bool]$ok,[string]$name,[string]$detail) { if (-not $ok) { throw $name } }\n` +
      `$installRoot=${quote(install)}; $dataRoot=${quote(data)}; $EvidenceDir=${quote(evidence)}; $db=${quote(database)}; $deadline=Get-Date\n` +
      `$before='${createHash('sha256').update('original').digest('hex')}'; $marker=${quote(JSON.stringify(marker))} | ConvertFrom-Json\n` + `try {\n${body}\n} finally {\n${capture}\n}`
    const scriptPath = path.join(root, 'check.ps1'); fs.writeFileSync(scriptPath, script)
    const encoded = Buffer.from(buildWindowsRollbackFileLoader(scriptPath, createHash('sha256').update(script).digest('hex')), 'utf16le').toString('base64')
    let error = ''
    try { await execFileAsync(powershell, ['-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], { timeout: 10000, env: Object.fromEntries(Object.entries(process.env).filter(([key]) => key.toUpperCase() !== 'PSMODULEPATH')) }) } catch (caught) { error = String(caught) }
    if (scenario === 'consumed') {
      expect(error).toBe('')
    } else expect(error).toContain(scenario === 'wrong-build' || scenario === 'marker' ? 'rollback.restored_build' : scenario === 'dirty-db' ? 'rollback.database_hash' : 'rollback.applied_record')
    if (!['missing', 'log-only'].includes(scenario)) expect(fs.readFileSync(path.join(evidence, 'rollback-applied.last.json'), 'utf8')).toBe(scenario === 'malformed-json' ? '{bad json' : JSON.stringify(receipt))
  }, 15000)
})
