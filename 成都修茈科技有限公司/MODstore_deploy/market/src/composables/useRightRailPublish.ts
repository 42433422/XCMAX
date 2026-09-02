import { onUnmounted, ref, watch, type InjectionKey, type Ref } from 'vue'
import { api } from '../api'
import { ApiError } from '../infrastructure/http/client'
import type { SixDimensionReport } from '../types/sixDimension'
import type { useWorkbenchStore } from '../stores/workbench'

type WorkbenchStore = ReturnType<typeof useWorkbenchStore>

export type PublishState = 'idle' | 'testing' | 'done' | 'publishing' | 'published' | 'error'
export type SyncState = 'idle' | 'running' | 'done' | 'error'
export type AuditAnimPhase = 'idle' | 'running' | 'done'

export interface BenchResult {
  tasks_result: Array<{
    level: number; task_id: string; task_desc: string
    ok: boolean; cost_tokens: number; duration_ms: number; score: number
  }>
  level_scores: Record<number, number>
  overall_score: number
  audit: {
    ok: boolean
    dimensions?: Record<string, { score: number; reasons: string[] }>
    summary?: { average: number; pass: boolean }
    error?: string
  }
  passed: boolean
  six_dimension?: SixDimensionReport | null
  six_dimension_llm_meta?: { llm_error?: string } | null
}

export interface SyncResult {
  ok: boolean
  stage: string
  pkg_id?: string
  version?: string
  bench?: BenchResult
  fhd_install?: { ok?: boolean; skipped?: boolean; reason?: string; error?: string }
  reason?: string
}

/**
 * RightRail 上架域：基准测试、五维审核动画、同步测试（bench+发布+推送宿主）与提交上架
 * （自 RightRail.vue 原样迁移）。状态常驻于父组件作用域，跨 tab 切换不丢失。
 */
export function useRightRailPublish(deps: {
  store: WorkbenchStore
  /** 试运行结果（由 actions 域持有；切回 run 模式时清空，与原 watch 行为一致） */
  runResult: Ref<string | null>
}) {
  const { store, runResult } = deps

  const publishState = ref<PublishState>('idle')
  const publishError = ref<string | null>(null)

  const benchResult = ref<BenchResult | null>(null)

  // 五维审核动画状态
  const auditAnimPhase = ref<AuditAnimPhase>('idle')
  // 显示中的分数（从 0 动画滚动到真实分数）
  const auditAnimScores = ref<Record<string, number>>({})

  const DIM_LABELS: Record<string, string> = {
    manifest_compliance: '清单合规',
    declaration_completeness: '声明完整',
    api_testability_static: 'API 可测',
    security_and_size: '安全尺寸',
    metadata_quality: '元数据质量',
  }

  function _animateAuditScores(dims: Record<string, { score: number }>) {
    auditAnimPhase.value = 'running'
    const keys = Object.keys(dims)
    auditAnimScores.value = Object.fromEntries(keys.map((k) => [k, 0]))

    // 依次点亮每个维度，每个维度数字从 0 滚动到目标值
    const STEP_DELAY = 260   // 每个维度间隔 ms
    const COUNT_STEPS = 20   // 滚动帧数

    keys.forEach((key, i) => {
      const target = dims[key]?.score ?? 0
      const startAt = i * STEP_DELAY
      let step = 0
      const interval = setInterval(() => {
        step++
        auditAnimScores.value = {
          ...auditAnimScores.value,
          [key]: Math.round(target * Math.min(step / COUNT_STEPS, 1)),
        }
        if (step >= COUNT_STEPS) {
          clearInterval(interval)
          if (i === keys.length - 1) {
            // 最后一个维度完成 → 动画结束
            setTimeout(() => { auditAnimPhase.value = 'done' }, 300)
          }
        }
      }, (startAt + 50) / COUNT_STEPS)  // 每帧间隔
    })
  }

  async function startBenchTest() {
    const eid = store.target.id as string | undefined
    if (!eid) {
      publishError.value = '请先保存员工（需要 ID）'
      return
    }
    publishState.value = 'testing'
    publishError.value = null
    benchResult.value = null
    auditAnimPhase.value = 'idle'
    auditAnimScores.value = {}

    try {
      const res = await api.employeeBenchTest(eid) as BenchResult & { ok: boolean; error?: string }
      if (!res.ok) throw new Error(res.error || '测试失败')
      benchResult.value = res
      publishState.value = 'done'
      // 启动五维动画
      const dims = res.audit?.dimensions
      if (dims && Object.keys(dims).length > 0) {
        _animateAuditScores(dims)
      }
    } catch (e: unknown) {
      publishError.value = (e as Error)?.message || String(e)
      publishState.value = 'error'
    }
  }

  async function publishEmployee() {
    const eid = store.target.id as string | undefined
    if (!eid || !benchResult.value?.passed) return
    publishState.value = 'publishing'
    publishError.value = null
    try {
      const res = await api.employeePublish(eid) as { ok: boolean; error?: string; pkg_id?: string }
      if (!res.ok) throw new Error(res.error || '上架失败')
      publishState.value = 'published'
    } catch (e: unknown) {
      publishError.value = (e as Error)?.message || String(e)
      publishState.value = 'error'
    }
  }

  async function downloadPack(standalone = false) {
    const eid = store.target.id as string | undefined
    const manifest = store.target.manifest
    try {
      const blob = await api.employeeExportZip(manifest, eid || undefined, { standalone })
      if (blob.size === 0) {
        publishError.value = '下载失败：服务端返回空包，请检查登录状态与 manifest（identity.id 是否为空）'
        return
      }
      const base = eid || 'employee'
      const filename = standalone ? `${base}-standalone.xcemp` : `${base}.xcemp`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.style.display = 'none'
      document.body.appendChild(a)
      a.click()
      a.remove()
      // 必须在浏览器完成下载读流之后再 revoke；立即 revoke 会导致保存为 0 字节
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (e: unknown) {
      publishError.value = '下载失败: ' + ((e as Error)?.message || String(e))
    }
  }

  // ── Sync test section ─────────────────────────────────────────────────────

  const syncState = ref<SyncState>('idle')
  const syncError = ref<string | null>(null)

  const syncResult = ref<SyncResult | null>(null)
  // 同步步骤动画（7步）
  const SYNC_STEPS = ['读取员工', '生成任务', '执行测试', '量化评分', '发布目录', '推送宿主', '完成'] as const
  const syncCurrentStep = ref(-1)
  /** 已等待秒数（单请求期间由定时器递增，用于步骤推演与右侧元信息） */
  const syncElapsedSec = ref(0)
  let syncProgressTimer: number | null = null

  function clearSyncProgressTimer() {
    if (syncProgressTimer != null) {
      clearInterval(syncProgressTimer)
      syncProgressTimer = null
    }
  }

  /**
   * 后端为单次长连接，无流式阶段回调；按已等待时间推演当前大步骤，避免一直停在「读取员工」。
   * 时间片与 employee_sync_test 中「读 manifest → LLM 生成任务 → bench → 发布 → 推送」大致对齐。
   */
  function syncStepFromElapsed(sec: number): number {
    if (sec < 2) return 0
    if (sec < 22) return 1
    if (sec < 100) return 2
    if (sec < 130) return 3
    if (sec < 160) return 4
    if (sec < 190) return 5
    return 5
  }

  /** 整体粗估进度（0–99），仅作等待反馈，非服务端精确百分比 */
  function syncRoughOverallPct(sec: number): number {
    return Math.min(99, Math.round((sec / 420) * 100))
  }

  function syncStepMeta(i: number): string {
    if (syncState.value === 'idle') return ''
    if (syncState.value === 'running') {
      if (i < syncCurrentStep.value) return ''
      if (i > syncCurrentStep.value) return ''
      const sec = syncElapsedSec.value
      const pct = syncRoughOverallPct(sec)
      return `~${pct}% · ${sec}s`
    }
    if (syncState.value === 'done') {
      return ''
    }
    if (syncState.value === 'error') {
      if (i < syncCurrentStep.value) return ''
      if (i === syncCurrentStep.value) return '×'
      return ''
    }
    return ''
  }

  onUnmounted(() => clearSyncProgressTimer())

  async function startSyncTest() {
    const eid = store.target.id as string | undefined
    if (!eid) {
      syncError.value = '请先保存员工（需要 ID）'
      return
    }
    clearSyncProgressTimer()
    syncState.value = 'running'
    syncError.value = null
    syncResult.value = null
    syncElapsedSec.value = 0
    syncCurrentStep.value = 0

    syncProgressTimer = window.setInterval(() => {
      if (syncState.value !== 'running') {
        clearSyncProgressTimer()
        return
      }
      syncElapsedSec.value += 1
      syncCurrentStep.value = syncStepFromElapsed(syncElapsedSec.value)
    }, 1000)

    try {
      // 读取宿主 URL（从 store.target 或环境）
      const fhdBase = (store.target as Record<string, unknown>).fhd_base_url as string | undefined || ''
      const res = await api.employeeSyncTest(eid, fhdBase) as SyncResult & { ok: boolean }
      clearSyncProgressTimer()
      syncCurrentStep.value = SYNC_STEPS.length - 1
      syncResult.value = res
      if (res.ok) {
        syncState.value = 'done'
        // 同步成功后也更新 benchResult
        if (res.bench) benchResult.value = res.bench as BenchResult
      } else {
        syncState.value = 'error'
        syncError.value = res.reason || '同步测试失败'
      }
    } catch (e: unknown) {
      clearSyncProgressTimer()
      syncState.value = 'error'
      let msg = (e as Error)?.message || String(e)
      if (e instanceof ApiError && e.status === 504) {
        msg =
          'HTTP 504：网关在等待上游时超时。同步测试含 LLM 基准，常需数分钟。请将前置 nginx 的 /api/ 段设为 proxy_read_timeout 3600s（参见仓库根目录 nginx-xiu-ci.conf）。'
      } else if (/^HTTP 504|504 Gateway|Gateway Time-out/i.test(msg)) {
        msg =
          'HTTP 504：网关在等待上游时超时。请将前置 nginx 的 /api/ 段设为 proxy_read_timeout 3600s（参见仓库根目录 nginx-xiu-ci.conf）。'
      } else if (msg.length > 320) {
        msg = `${msg.slice(0, 260)}…`
      }
      syncError.value = msg
    }
  }

  // Watch for run mode from store
  watch(() => store.inspectorMode, (m) => {
    if (m === 'run') runResult.value = null
    if (m === 'publish') {
      // 切换到上架 tab 时重置动画状态
      auditAnimPhase.value = 'idle'
      auditAnimScores.value = {}
    }
  })

  return {
    publishState,
    publishError,
    benchResult,
    auditAnimPhase,
    auditAnimScores,
    DIM_LABELS,
    startBenchTest,
    publishEmployee,
    downloadPack,
    syncState,
    syncError,
    syncResult,
    syncCurrentStep,
    // 测试兼容面：既有测试经 wrapper.vm 访问原单文件顶层绑定
    syncElapsedSec,
    syncStepFromElapsed,
    syncRoughOverallPct,
    SYNC_STEPS,
    syncStepMeta,
    startSyncTest,
  }
}

export type RightRailPublishApi = ReturnType<typeof useRightRailPublish>
export const RIGHT_RAIL_PUBLISH_KEY: InjectionKey<RightRailPublishApi> = Symbol('RightRailPublish')
