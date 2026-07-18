/**
 * DesktopAutonomyAdapter：桌面端 AutonomyAdapter 实现
 *
 * Phase 0：collectTruth / subscribeSignals / audit 已实现；
 *          executeAction 返回 not-implemented（Phase 1 落地 4 个 action）。
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
  /** 配置文件路径（null 表示不跟踪配置指纹） */
  configPath: string | null
  /** 已知良好配置指纹（null 表示尚未快照） */
  knownGoodFingerprint?: string | null
}

export class DesktopAutonomyAdapter implements AutonomyAdapter {
  private ctx: DesktopAdapterContext
  private userDataDir: string
  private auditPath: string
  private knownGoodFingerprint: string | null

  constructor(ctx: DesktopAdapterContext) {
    this.ctx = ctx
    this.userDataDir = app.getPath('userData')
    const autonomyDir = path.join(this.userDataDir, 'autonomy')
    fs.mkdirSync(autonomyDir, { recursive: true })
    this.auditPath = path.join(autonomyDir, 'audit.jsonl')
    this.knownGoodFingerprint = ctx.knownGoodFingerprint ?? null
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
    return inst
  }

  async collectTruth(): Promise<RuntimeTruthSnapshot> {
    const backendInfo = this.ctx.backendProcessRef() ?? { pid: null, running: false, startedAt: null }
    // 端口检测：尝试连接本地端口
    const portInUse = await isPortInUse(this.ctx.port)
    // 拉取后端 /api/desktop/status（如可用）
    let desktopStatus: unknown = undefined
    try {
      const resp = await fetch(`http://127.0.0.1:${this.ctx.port}/api/desktop/status`, {
        signal: AbortSignal.timeout(2000),
      })
      if (resp.ok) desktopStatus = await resp.json()
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
      desktopStatus,
    })
    appendTruthLog(this.userDataDir, truth)
    return truth
  }

  subscribeSignals(_emit: (signal: Signal) => void): void {
    // 桌面端信号由 main.ts 主动 ingest（backend_exit 等），此处无操作
  }

  async executeAction(action: Action): Promise<ActionResult> {
    // Phase 0：所有动作返回 not-implemented
    // Phase 1 将实现 restart_backend / rollback_version / clear_cache / repair_config
    const ts = Date.now()
    return {
      action,
      ok: false,
      detail: `not-implemented:${action.type}`,
      ts,
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
