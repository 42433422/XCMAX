/**
 * DesktopAutonomyAdapter：桌面端 AutonomyAdapter 实现
 *
 * 只执行可逆、明确 allowlist 的本机动作；每个成功结果均在适配器内完成
 * 最小后验校验，避免把“已发起”误记为“已修复”。
 *
 * 与 main.ts 共存：
 * - backendProcessRef / restartCountRef 由 main.ts 注入（闭包引用）
 * - signals 由 main.ts 主动 ingest（subscribeSignals 为空）
 * - audit 写 userData/autonomy/audit.jsonl
 */

import { app } from 'electron'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import type {
  Action,
  ActionResult,
  AuditEntry,
  AutonomyAdapter,
  RuntimeTruthSnapshot,
  Signal,
} from './types.js'
import {
  computeRuntimeTruth,
  appendTruthLog,
  computeConfigFingerprint,
  diskFreeMegabytes,
} from './runtime-truth.js'

/** 桌面端适配器上下文（由 main.ts 注入） */
export interface DesktopAdapterContext {
  /** 后端进程引用（返回 null 表示无后端） */
  backendProcessRef: () => { pid: number | null; running: boolean; startedAt: number | null } | null
  /** 重启计数引用 */
  restartCountRef: () => number
  /** 桌面端端口 */
  port: number
  /** 应用版本 */
  appVersion: string
  /** 构建 SHA */
  buildSha: string
  /** 配置文件路径（桌面端默认 userData/config/database.json） */
  configPath: string | null
  /** 已知良好配置指纹（null 表示尚未快照） */
  knownGoodFingerprint?: string | null
  /** Phase 1 新增：触发 backend 重启（main.ts 注入；调用前 backendProcess 应已为 null） */
  restartBackend?: () => Promise<boolean | void>
  /** Phase 1 新增：触发版本回滚（main.ts 注入；写入 rollback marker） */
  triggerRollback?: () => Promise<boolean | void>
  /** Phase 1 新增：已知良好配置内容（用于 repair_config 恢复；null 表示无配置可恢复） */
  knownGoodConfigContent?: string | null
}

export class DesktopAutonomyAdapter implements AutonomyAdapter {
  private ctx: DesktopAdapterContext
  private userDataDir: string
  private auditPath: string
  private knownGoodFingerprint: string | null
  private knownGoodConfigContent: string | null

  constructor(ctx: DesktopAdapterContext) {
    this.ctx = ctx
    this.userDataDir = app.getPath('userData')
    const autonomyDir = path.join(this.userDataDir, 'autonomy')
    fs.mkdirSync(autonomyDir, { recursive: true })
    this.auditPath = path.join(autonomyDir, 'audit.jsonl')
    this.knownGoodFingerprint = ctx.knownGoodFingerprint ?? null
    this.knownGoodConfigContent = ctx.knownGoodConfigContent ?? null
  }

  /** 测试用：注入自定义 userDataDir */
  static forTest(ctx: DesktopAdapterContext, userDataDir: string): DesktopAutonomyAdapter {
    const inst = Object.create(DesktopAutonomyAdapter.prototype) as DesktopAutonomyAdapter
    inst.ctx = ctx
    inst.userDataDir = userDataDir
    const autonomyDir = path.join(userDataDir, 'autonomy')
    fs.mkdirSync(autonomyDir, { recursive: true })
    inst.auditPath = path.join(autonomyDir, 'audit.jsonl')
    inst.knownGoodFingerprint = ctx.knownGoodFingerprint ?? null
    inst.knownGoodConfigContent = ctx.knownGoodConfigContent ?? null
    return inst
  }

  async collectTruth(): Promise<RuntimeTruthSnapshot> {
    const backendInfo = this.ctx.backendProcessRef() ?? { pid: null, running: false, startedAt: null }
    // 端口检测：尝试连接本地端口
    const portInUse = await isPortInUse(this.ctx.port)
    // 拉取后端状态与 NeuroBus 健康。总线状态不能假定已被 desktop/status 透传。
    let desktopStatus: unknown = undefined
    try {
      const [desktopResponse, neurobusResponse] = await Promise.all([
        fetch(`http://127.0.0.1:${this.ctx.port}/api/desktop/status`, {
          signal: AbortSignal.timeout(2000),
        }),
        fetch(`http://127.0.0.1:${this.ctx.port}/api/neurobus/health`, {
          signal: AbortSignal.timeout(2000),
        }),
      ])
      const desktopPayload = desktopResponse.ok ? await desktopResponse.json() : undefined
      const neurobusPayload = neurobusResponse.ok ? await neurobusResponse.json() : undefined
      if (desktopPayload && typeof desktopPayload === 'object') {
        desktopStatus = {
          ...(desktopPayload as Record<string, unknown>),
          neurobus: neurobusPayload,
        }
      } else {
        desktopStatus = neurobusPayload
      }
    } catch {
      // 后端未就绪时正常情况
    }
    const truth = computeRuntimeTruth({
      userDataDir: this.userDataDir,
      backend: backendInfo,
      portInUse,
      configPath: this.ctx.configPath,
      knownGoodFingerprint: this.knownGoodFingerprint,
      appVersion: this.ctx.appVersion,
      buildSha: this.ctx.buildSha,
      restartCount: this.ctx.restartCountRef(),
      desktopStatus: this.resolveNeurobusStatus(desktopStatus),
      diskFreeMb: diskFreeMegabytes(this.userDataDir),
    })
    appendTruthLog(this.userDataDir, truth)
    return truth
  }

  private resolveNeurobusStatus(status: unknown): unknown {
    if (!status || typeof status !== 'object') return status
    const payload = status as Record<string, unknown>
    return payload.neurobus ?? payload
  }

  subscribeSignals(_emit: (signal: Signal) => void): void {
    // 桌面端信号由 main.ts 主动 ingest（backend_exit 等），此处无操作
  }

  async executeAction(action: Action): Promise<ActionResult> {
    const ts = Date.now()
    try {
      switch (action.type) {
        case 'restart_backend': {
          if (!this.ctx.restartBackend) {
            return { action, ok: false, detail: 'restartBackend callback not injected', ts }
          }
          const started = await this.ctx.restartBackend()
          if (started === false) {
            return { action, ok: false, detail: 'backend restart was not confirmed', ts }
          }
          return { action, ok: true, detail: 'backend restart triggered', ts }
        }
        case 'rollback_version': {
          if (!this.ctx.triggerRollback) {
            return { action, ok: false, detail: 'triggerRollback callback not injected', ts }
          }
          const scheduled = await this.ctx.triggerRollback()
          if (scheduled === false) {
            return { action, ok: false, detail: 'rollback was not scheduled (no eligible rollback marker)', ts }
          }
          return { action, ok: true, detail: 'rollback triggered', ts }
        }
        case 'clear_cache': {
          const cacheDir = path.join(this.userDataDir, 'cache')
          const neurobusDir = path.join(this.userDataDir, 'neurobus_cache')
          let cleared = 0
          for (const d of [cacheDir, neurobusDir]) {
            if (fs.existsSync(d)) {
              fs.rmSync(d, { recursive: true, force: true })
              if (fs.existsSync(d)) {
                return { action, ok: false, detail: `cache cleanup verification failed: ${d}`, ts }
              }
              cleared += 1
            }
          }
          return { action, ok: true, detail: `cleared ${cleared} cache dirs`, ts }
        }
        case 'repair_config': {
          if (!this.ctx.configPath) {
            return { action, ok: false, detail: 'no configPath configured', ts }
          }
          if (!this.knownGoodConfigContent) {
            return { action, ok: false, detail: 'no known-good config content to restore', ts }
          }
          if (!fs.existsSync(this.ctx.configPath)) {
            return { action, ok: false, detail: 'configured file no longer exists', ts }
          }
          const backupPath = `${this.ctx.configPath}.autonomy-bak-${Date.now()}`
          fs.copyFileSync(this.ctx.configPath, backupPath)
          fs.writeFileSync(this.ctx.configPath, this.knownGoodConfigContent, 'utf8')
          if (fs.readFileSync(this.ctx.configPath, 'utf8') !== this.knownGoodConfigContent) {
            return { action, ok: false, detail: 'config restore verification failed', ts }
          }
          return { action, ok: true, detail: `config restored (backup: ${backupPath})`, ts }
        }
        case 'escalate':
        case 'noop':
          // escalate/noop 由 controller 已审计，adapter 无需执行
          return { action, ok: true, detail: `${action.type} acknowledged`, ts }
        default:
          return { action, ok: false, detail: `not-implemented:${action.type}`, ts }
      }
    } catch (e) {
      return {
        action,
        ok: false,
        detail: `execute_threw: ${e instanceof Error ? e.message : String(e)}`,
        ts,
      }
    }
  }

  audit(entry: AuditEntry): void {
    try {
      fs.appendFileSync(this.auditPath, `${JSON.stringify(entry)}\n`, 'utf8')
    } catch {
      // 审计失败不影响主流程
    }
  }

  /** 设置已知良好配置指纹（首次启动后由 main.ts 调用） */
  setKnownGoodFingerprint(fp: string): void {
    this.knownGoodFingerprint = fp
  }

  /**
   * Capture the actual desktop database profile only after a healthy backend
   * has started.  The snapshot stays in memory; secrets are never written to
   * the autonomy audit log.  Oversized files are deliberately not restored.
   */
  captureKnownGoodConfigSnapshot(): string | null {
    if (!this.ctx.configPath || !fs.existsSync(this.ctx.configPath)) return null
    try {
      const stat = fs.statSync(this.ctx.configPath)
      if (!stat.isFile() || stat.size > 64 * 1024) return null
      const content = fs.readFileSync(this.ctx.configPath, 'utf8')
      if (!content.trim()) return null
      JSON.parse(content)
      const fingerprint = computeConfigFingerprint(this.ctx.configPath)
      if (!fingerprint) return null
      this.knownGoodConfigContent = content
      this.knownGoodFingerprint = fingerprint
      return fingerprint
    } catch {
      return null
    }
  }

  /** 计算当前配置指纹（供 main.ts 启动时快照） */
  computeCurrentFingerprint(): string {
    return computeConfigFingerprint(this.ctx.configPath)
  }
}

/** 端口占用检测（轻量 TCP 连接尝试） */
function isPortInUse(port: number): Promise<boolean> {
  return new Promise(resolve => {
    const tester = net.createServer()
    tester.once('error', () => resolve(true))
    tester.once('listening', () => {
      tester.close(() => resolve(false))
    })
    tester.listen(port, '127.0.0.1')
  })
}
