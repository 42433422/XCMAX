import { describe, expect, it } from 'vitest'
import { buildWindowsRollbackScript, type WindowsRollbackLaunchOptions } from './rollback-windows.js'

describe('Windows rollback owned state', () => {
  it('binds the exact userData inventory and backup to the shared staged restore', () => {
    const inventory = {
      'mods/northwind/manifest.json': 'a'.repeat(64),
      'mods/customer-reporting/backend/report.py': 'b'.repeat(64),
      'products__northwind.db': 'c'.repeat(64),
      'data/mod_dbs/customer-reporting.db': 'd'.repeat(64),
      'data/mod_dbs/xcagi.db': 'e'.repeat(64),
    }
    const options: WindowsRollbackLaunchOptions = {
      currentPid: 4242,
      installDir: 'C:\\XCAGI', backupRoot: 'C:\\userData\\rollback\\owned\\app',
      appPath: 'C:\\XCAGI\\XCAGI.exe', markerPath: 'C:\\userData\\rollback-marker.json',
      appliedPath: 'C:\\userData\\rollback-applied.json', logPath: 'C:\\userData\\rollback\\helper.log',
      ownedUserDataRoot: 'C:\\userData', ownedBackupRoot: 'C:\\userData\\rollback\\owned\\state',
      expectedOwnedFiles: inventory, restartApp: false,
      expectedOwnedDirectories: ['mods', 'mods/northwind', 'mods/northwind/empty-preserved', 'data', 'data/mod_dbs'],
      applied: { appliedAt: '2026-10-12T00:00:00.000Z', reason: 'test', fromVersion: 'candidate', toVersion: 'old' },
    }
    const script = buildWindowsRollbackScript(options)
    const encodedInventory = Buffer.from(JSON.stringify(inventory)).toString('base64')
    expect(script).toContain(String.raw`$ownedUserDataRoot = 'C:\userData'`)
    expect(script).toContain(String.raw`$ownedBackupRoot = 'C:\userData\rollback\owned\state'`)
    expect(script).toContain(encodedInventory)
    expect(script).toContain('foreach ($relative in $expectedOwnedDirectories)')
    expect(script).toContain('$originalDirectoriesRef.Value = @(Get-OwnedDirectories $ownedUserDataRoot)')
    expect(script).toContain('owned-state compensation could not recreate candidate directory')
    expect(script).toContain('owned-state compensation could not remove created directory')
    expect(script).toContain('Assert-OwnedInventory $ownedUserDataRoot $expectedOwnedFiles')
    expect(script).toContain('if ($ownedQuarantined -and (Test-Path -LiteralPath (Native-Path $ownedFailed)))')
    expect(script).toContain('owned-state compensation could not restore')
    expect(script).toContain('retained owned-state rollback files must be recovered first')
  })

  it('keeps legacy C# generated resource placeholders explicit when no owned state is supplied', () => {
    const options: WindowsRollbackLaunchOptions = {
      currentPid: 4242, installDir: 'C:\\XCAGI', backupRoot: 'C:\\rollback\\app',
      appPath: 'C:\\XCAGI\\XCAGI.exe', markerPath: 'C:\\data\\rollback-marker.json',
      appliedPath: 'C:\\data\\rollback-applied.json', logPath: 'C:\\data\\rollback.log',
      applied: { appliedAt: '2026-10-12T00:00:00.000Z', reason: 'legacy', fromVersion: 'new', toVersion: 'old' },
      restartApp: false,
    }
    const script = buildWindowsRollbackScript(options)
    expect(script).toContain("$ownedUserDataRoot = ''")
    expect(script).toContain("$ownedBackupRoot = ''")
    expect(script).toContain("FromBase64String('e30=')")
  })

  it('owns special-named descendants by Mod location and leaves root special directories outside inventory', () => {
    const inventory = {
      'mods/northwind/backend/models/product.py': 'a'.repeat(64),
      'mods/northwind/backend/logs/build.py': 'b'.repeat(64),
      'mods/northwind/backend/uploads/handler.py': 'c'.repeat(64),
      'mods/northwind/backend/secrets/parser.py': 'd'.repeat(64),
      'mods/northwind/backend/rollback/repair.py': 'e'.repeat(64),
      'data/mod_dbs/private/uploads/customer.db': 'f'.repeat(64),
    }
    const script = buildWindowsRollbackScript({
      currentPid: 4242, installDir: 'C:\\XCAGI', backupRoot: 'C:\\userData\\rollback\\app',
      appPath: 'C:\\XCAGI\\XCAGI.exe', markerPath: 'C:\\userData\\rollback-marker.json',
      appliedPath: 'C:\\userData\\rollback-applied.json', logPath: 'C:\\userData\\rollback\\helper.log',
      ownedUserDataRoot: 'C:\\userData', ownedBackupRoot: 'C:\\userData\\rollback\\owned\\state',
      expectedOwnedFiles: inventory,
      expectedOwnedDirectories: ['mods', 'mods/northwind', 'mods/northwind/backend/models', 'mods/northwind/backend/logs', 'data', 'data/mod_dbs', 'data/mod_dbs/private/uploads'],
      applied: { appliedAt: '2026-10-12T00:00:00.000Z', reason: 'test', fromVersion: 'candidate', toVersion: 'old' },
      restartApp: false,
    })
    expect(script).toContain(Buffer.from(JSON.stringify(inventory)).toString('base64'))
    expect(script).toContain('Get-ChildItem -LiteralPath (Native-Path $modRoot) -Recurse -File -Force)')
    expect(script).not.toContain('function Test-OwnedPath')
    expect(inventory).not.toHaveProperty('models/private-model.bin')
    expect(inventory).not.toHaveProperty('logs/private.log')
    expect(inventory).not.toHaveProperty('uploads/customer-file.bin')
    expect(inventory).not.toHaveProperty('secrets/private-token.txt')
  })
})
