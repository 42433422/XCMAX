import { spawn } from 'node:child_process'

export interface BackendMigrationProcessOptions {
  command: string
  args: string[]
  cwd: string
  env: NodeJS.ProcessEnv
  attachBackup?: (path: string) => void
  onStdout?: (data: unknown) => void
  onStderr?: (data: unknown) => void
}

/** Run the packaged migration subprocess and return its verified backup path. */
export function runBackendMigrationProcess(
  options: BackendMigrationProcessOptions,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(options.command, options.args, {
      cwd: options.cwd,
      env: options.env,
      windowsHide: true,
    })
    let stderr = ''
    let stdout = ''
    let databaseBackupPath = ''
    let backupAttachError: unknown
    child.stderr.on('data', data => {
      stderr += String(data)
      options.onStderr?.(data)
    })
    child.stdout.on('data', data => {
      stdout += String(data)
      options.onStdout?.(data)
      if (databaseBackupPath) return
      const match = stdout.match(/^XCAGI_MIGRATION_BACKUP=(.+)$/m)
      const candidate = match?.[1]?.trim() || ''
      if (!candidate) return
      try {
        options.attachBackup?.(candidate)
        databaseBackupPath = candidate
      } catch (error) {
        backupAttachError = error
        child.kill()
      }
    })
    child.on('error', reject)
    child.on('exit', code => {
      if (backupAttachError) {
        reject(backupAttachError)
      } else if (code === 0) {
        resolve(databaseBackupPath)
      } else {
        reject(new Error(`数据库迁移失败（code=${code}）: ${stderr}`))
      }
    })
  })
}
