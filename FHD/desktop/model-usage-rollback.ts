import { execFile } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

export function modelUsageLedgerPath(userData: string, env: NodeJS.ProcessEnv, cwd = process.cwd()): string {
  const override = env.MODEL_USAGE_LEDGER_PATH?.trim()
  if (override) return path.resolve(cwd, override)
  const locationFile = path.join(userData, 'data', 'model_usage_storage.json')
  if (fs.existsSync(locationFile)) {
    const location = JSON.parse(fs.readFileSync(locationFile, 'utf8')) as { version?: number; ledger_path?: unknown }
    if (location.version !== 1 || typeof location.ledger_path !== 'string' || !path.isAbsolute(location.ledger_path)) {
      throw new Error('计量账本定位记录无效，已中止回滚。')
    }
    return location.ledger_path
  }
  return path.resolve(userData, 'data', 'model_usage_ledger.json')
}

export function assertLedgerOutsideRollbackTarget(ledger: string, target: string): void {
  const canonical = (value: string): string => {
    const absolute = path.resolve(value)
    const resolved = fs.existsSync(absolute) ? fs.realpathSync(absolute) : absolute
    return process.platform === 'win32' ? resolved.toLowerCase() : resolved
  }
  const root = canonical(target)
  const parent = canonical(path.dirname(ledger))
  if (parent === root || parent.startsWith(`${root}${path.sep}`)) {
    throw new Error('计量账本位于将被替换的安装目录内，已中止回滚；请先迁移账本至持久数据目录。')
  }
}

function verifyRetiredLedger(ledger: string, userData: string): void {
  const parent = path.dirname(ledger)
  const basename = path.basename(ledger)
  const parsed = path.parse(ledger)
  const siblings = fs.existsSync(parent) ? fs.readdirSync(parent) : []
  const migrated = fs.existsSync(path.join(userData, 'data', 'model_usage_storage.json'))
    || siblings.some(name => name.startsWith(`${parsed.name}.`) && name.endsWith(`.legacy${parsed.ext}`))
  if (!migrated) return
  if (!fs.existsSync(ledger)) throw new Error('已迁移计量账本的数据库丢失，已中止回滚。')
  const snapshot = JSON.parse(fs.readFileSync(ledger, 'utf8'))
  const archive = siblings.some(name => name.startsWith(`${basename}.rollback-`) && name.endsWith('.sqlite3')
    && fs.lstatSync(path.join(parent, name)).isFile() && !fs.lstatSync(path.join(parent, name)).isSymbolicLink())
  if (!archive || snapshot?.compatibility_snapshot?.source !== `${ledger}.sqlite3`
    || !Array.isArray(snapshot.entries) || !snapshot.wallets || typeof snapshot.wallets !== 'object' || Array.isArray(snapshot.wallets)) {
    throw new Error('缺少完整账本交接快照，已中止回滚。')
  }
}

/** Call only after the writer has exited; a failed handoff must stop rollback. */
export async function handoffModelUsageLedger(
  executable: { command: string; args: string[]; cwd: string },
  userData: string,
  env: NodeJS.ProcessEnv,
): Promise<void> {
  const ledger = modelUsageLedgerPath(userData, env, executable.cwd)
  const database = `${ledger}.sqlite3`
  if (!fs.existsSync(database)) {
    verifyRetiredLedger(ledger, userData)
    return
  }
  const info = fs.lstatSync(database)
  if (!info.isFile() || info.isSymbolicLink()) throw new Error('计量账本不是普通文件，已中止回滚。')
  await new Promise<void>((resolve, reject) => {
    execFile(executable.command, [...executable.args, '--export-model-usage-ledger', ledger], {
      cwd: executable.cwd, env, windowsHide: true, timeout: 60_000, maxBuffer: 64 * 1024,
    }, (error, stdout) => {
      if (error) { reject(new Error(`计量账本交接失败，保留当前应用和恢复记录：${error.message}`)); return }
      try {
        const receipt = String(stdout).split(/\r?\n/).includes(`XCAGI_MODEL_USAGE_HANDOFF=${ledger}`)
        if (!receipt || fs.existsSync(database) || !fs.existsSync(ledger) || !fs.statSync(ledger).size) {
          throw new Error('计量账本交接未完成，已中止回滚。')
        }
        resolve()
      } catch (failure) {
        reject(failure)
      }
    })
  })
}
