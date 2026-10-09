import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { app } from 'electron'

import { writeBackendLog } from './backend-process'

/** 安装器只能登记默认数据目录；自定义 userData 要在启动后重登记。 */
export function syncWindowsBackupTasks(dataDir: string): void {
  if (process.platform !== 'win32' || process.env.XCAGI_DESKTOP_E2E === '1' || !app.isPackaged) return
  const target = dataDir.trim()
  if (!target || target.includes('"') || target.includes('\n')) {
    writeBackendLog('[backup-task] skipped registration because the data directory is empty or unsafe\n')
    return
  }
  const script = path.join(process.resourcesPath, 'backend', '_internal', 'scripts', 'backup', 'Install-BackupTask.ps1')
  if (!fs.existsSync(script)) {
    writeBackendLog(`[backup-task] installer script missing: ${script}\n`)
    return
  }
  const powershell = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
  const child = spawn(powershell, [
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy', 'Bypass',
    '-File', script,
    '-DataDir', target,
  ], { windowsHide: true, stdio: 'ignore' })
  child.on('error', error => writeBackendLog(`[backup-task] registration failed: ${error.message}\n`))
  child.unref()
}
