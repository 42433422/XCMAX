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
    expect(script).toContain('function Get-OwnedFiles')
    expect(script).toContain('function Assert-OwnedInventory')
    expect(script).toContain('function Restore-OwnedState')
    expect(script).toContain('function Get-OwnedDirectories')
    expect(script).toContain('foreach ($relative in $expectedOwnedDirectories)')
    expect(script).toContain('$originalDirectoriesRef.Value = @(Get-OwnedDirectories $ownedUserDataRoot)')
    expect(script).toContain('owned-state compensation could not recreate candidate directory')
    expect(script).toContain('owned-state compensation could not remove created directory')
    expect(script).toContain('Assert-OwnedInventory $ownedUserDataRoot $expectedOwnedFiles')
    expect(script).toContain('if ($ownedQuarantined -and (Test-Path -LiteralPath $ownedFailed))')
    expect(script).toContain('Move-Item -LiteralPath $file.FullName -Destination $dest; $quarantinedFilesRef.Value += $rel')
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
})
