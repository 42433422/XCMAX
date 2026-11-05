import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { stripTypeScriptTypes } from 'node:module'
const source = fs.readFileSync(new URL('../../desktop/rollback-windows.ts', import.meta.url), 'utf8')
const { buildWindowsRollbackScript, buildWindowsRollbackFileLoader } = await import(`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(source)).toString('base64')}`)

// Generated from the same compensating restore engine used by desktop updates.
const names = ['installDir', 'backupRoot', 'appPath', 'markerPath', 'appliedPath', 'logPath', 'databasePath', 'databaseBackupPath', 'ownedUserDataRoot', 'ownedBackupRoot']
const options = Object.fromEntries(names.map(name => [name, `C:/__${name}__`]))
options.appPath = 'C:/__installDir__/XCAGI.exe'
options.expectedOwnedFiles = {}
options.expectedOwnedDirectories = []
let script = buildWindowsRollbackScript({ ...options, currentPid: 123, restartApp: false, applied: { appliedAt: '', reason: '', fromVersion: '', toVersion: '' } })
for (const name of names) script = script.replaceAll(`'${path.win32.normalize(options[name])}'`, `__${name}__`)
script = script.replace('$waitPid = 123', '$waitPid = __waitPid__').replace("FromBase64String('e30=')", "FromBase64String('__expectedAppFiles__')")
script = script.replace('$expectedDatabaseSha256 = \'\'', '$expectedDatabaseSha256 = __expectedDatabaseSha256__')
script = script.replace("$expectedOwnedFiles = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('e30=')) | ConvertFrom-Json", "$expectedOwnedFiles = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__expectedOwnedFiles__')) | ConvertFrom-Json")
script = script.replace("$expectedOwnedDirectories = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('W10=')) | ConvertFrom-Json", "$expectedOwnedDirectories = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__expectedOwnedDirectories__')) | ConvertFrom-Json")
script = script.replace('$databaseOriginallyAbsent = $false', '$databaseOriginallyAbsent = __databaseOriginallyAbsent__')
script = script.replace(/(\$appliedJson = .*FromBase64String\(')[^']+('\).*)/, '$1__appliedRecord__$2')
const target = fileURLToPath(new URL('../../tools/XcagiInstaller/Assets/WindowsRollback.generated.ps1', import.meta.url))
fs.writeFileSync(target, `# Generated; DO NOT EDIT. Source: desktop/rollback-windows.ts\r\n${script}\r\n`)
const loader = buildWindowsRollbackFileLoader('C:/__scriptPath__', '0'.repeat(64)).replaceAll("'C:/__scriptPath__'", '__scriptPath__').replaceAll('0'.repeat(64), '__scriptSha256__')
fs.writeFileSync(target.replace('WindowsRollback.generated', 'WindowsRollbackLoader.generated'), `# Generated; DO NOT EDIT. Source: desktop/rollback-windows.ts\r\n${loader}\r\n`)
console.log('Generated shared Windows rollback helper')
